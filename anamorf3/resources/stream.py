"""Потоковый клиент OpenAI-совместимого chat/completions (llama-server,
Mistral, OpenRouter...). Только стандартная библиотека.

Три вещи, ради которых он свой, а не requests:
  1. ОТМЕНА ПО-НАСТОЯЩЕМУ. Отдельный сторож ждёт CancelToken и рвёт сокет —
     чтение сразу падает, генерация на сервере прекращается (llama-server
     останавливает слот, когда клиент ушёл). Старое ядро бросало поток живым.
  2. ВЫЗОВЫ ИНСТРУМЕНТОВ ЦЕЛИКОМ. Модель шлёт их обрывками по символу;
     ядру отдаём один готовый вызов ровно один раз (договор с Codex, v0).
  3. ЧЕСТНЫЕ ЦИФРЫ. ttft (до первого слова), prefill/скорость из timings
     llama-server, реальное имя модели из ответа.
"""
from __future__ import annotations

import http.client
import json
import ssl
import threading
import time
from typing import Any, Iterator
from urllib.parse import urlparse

from anamorf3.contracts import CancelToken, ChatChunk


class _Watch:
    """Сторож отмены: по cancel() закрывает соединение."""

    def __init__(self, conn: http.client.HTTPConnection, cancel: CancelToken):
        self.conn, self.cancel, self.done = conn, cancel, threading.Event()
        threading.Thread(target=self._run, daemon=True, name="m3-cancel").start()

    def _run(self):
        while not self.done.is_set():
            if self.cancel.wait(0.1):
                try:
                    if self.conn.sock:
                        self.conn.sock.shutdown(2)
                    self.conn.close()
                except Exception:
                    pass
                return


def chat_stream(base_url: str, body: dict[str, Any], cancel: CancelToken,
                api_key: str = "", timeout_s: float = 120.0) -> Iterator[ChatChunk]:
    u = urlparse(base_url.rstrip("/") + "/chat/completions")
    if u.scheme == "https":
        conn = http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=timeout_s,
                                           context=ssl.create_default_context())
    else:
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout_s)
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {**body, "stream": True, "stream_options": {"include_usage": True}}

    t0 = time.monotonic()
    ttft = None
    calls: dict[int, dict] = {}          # обрывки вызовов по index
    usage: dict[str, Any] = {}
    model, finish = body.get("model", ""), ""
    watch = _Watch(conn, cancel)
    try:
        try:
            conn.request("POST", u.path, json.dumps(body), headers)
            resp = conn.getresponse()
        except Exception as e:
            if cancel.cancelled:
                yield _end(usage, model, "cancelled", t0, ttft)
                return
            yield _end(usage, model, "error", t0, ttft, f"нет связи: {e}")
            return
        if resp.status != 200:
            txt = resp.read(600).decode("utf-8", "replace")
            yield _end(usage, model, "error", t0, ttft, f"HTTP {resp.status}: {txt}")
            return
        while True:
            try:
                raw = resp.readline()
            except Exception as e:
                if cancel.cancelled:
                    yield _end(usage, model, "cancelled", t0, ttft)
                    return
                yield _end(usage, model, "error", t0, ttft, f"обрыв потока: {e}")
                return
            if not raw:
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                ev = json.loads(data)
            except ValueError:
                continue
            model = ev.get("model") or model
            if ev.get("usage"):
                usage.update(ev["usage"])
            if ev.get("timings"):                       # llama-server
                usage["timings"] = ev["timings"]
            for ch in ev.get("choices") or []:
                d = ch.get("delta") or {}
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
                for tc in d.get("tool_calls") or []:
                    i = int(tc.get("index", 0))
                    c = calls.setdefault(i, {"id": "", "type": "function",
                                             "function": {"name": "", "arguments": ""}})
                    c["id"] = tc.get("id") or c["id"]
                    f = tc.get("function") or {}
                    c["function"]["name"] += f.get("name") or ""
                    c["function"]["arguments"] += f.get("arguments") or ""
                if d.get("content"):
                    if ttft is None:
                        ttft = time.monotonic() - t0
                    yield ChatChunk(text=d["content"], model=model)
            if cancel.cancelled:
                yield _end(usage, model, "cancelled", t0, ttft)
                return
        done_calls = [calls[i] for i in sorted(calls)]
        if done_calls and ttft is None:
            ttft = time.monotonic() - t0               # решение = первый вызов
        if done_calls:
            yield ChatChunk(tool_calls=done_calls, model=model)
        yield _end(usage, model, finish or "stop", t0, ttft)
    finally:
        watch.done.set()
        try:
            conn.close()
        except Exception:
            pass


def _end(usage, model, finish, t0, ttft, error: str = "") -> ChatChunk:
    u = dict(usage)
    u["finish_reason"] = finish                  # stop | tool_calls | length | cancelled | error
    u["total_ms"] = int((time.monotonic() - t0) * 1000)
    u["ttft_ms"] = int(ttft * 1000) if ttft is not None else None
    if error:
        u["error"] = error
    return ChatChunk(done=True, usage=u, model=model)
