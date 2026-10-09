"""ModelPort — единственная дверь ядра к моделям (контракт v0).

Режим задаёт ЧЕЛОВЕК, и он не подменяется молча:
  * local — только своя модель на своей карте. Движок не поднялся —
    честная ошибка, а не тихий уход в облако (просьба Codex/Витали:
    в полном локальном режиме ничего не уходит наружу);
  * cloud — только облако по ключу из secrets.json.
"""
from __future__ import annotations

import time
from typing import Any, Iterator

from anamorf3.contracts import (CancelToken, ChatChunk, ChatRequest, Event,
                                EventBus, ResourceReport)

from . import gpu
from . import settings as S
from .local_engine import ALIAS, LocalEngine
from .stream import chat_stream


class _Base:
    mode = ""

    def __init__(self, s: dict, bus: EventBus | None):
        self.s, self.bus = s, bus
        self.last: dict[str, Any] = {}      # цифры последнего ответа

    def _emit(self, typ: str, data: dict, task_id: str | None = None):
        if self.bus:
            self.bus.publish(Event(typ, "resources", data, task_id))

    def _run(self, url: str, body: dict, req: ChatRequest, cancel: CancelToken,
             key: str = "", timeout: float = 120) -> Iterator[ChatChunk]:
        for ch in chat_stream(url, body, cancel, key, timeout):
            if ch.done:
                ch.usage["mode"] = self.mode
                self.last = {"model": ch.model, **ch.usage, "ts": time.time()}
                if ch.usage.get("finish_reason") == "error":
                    self._emit("model.error", {"mode": self.mode,
                                               "error": ch.usage.get("error", "")}, req.task_id)
            yield ch


class LocalPort(_Base):
    mode = "local"

    def __init__(self, s: dict, bus: EventBus | None = None):
        super().__init__(s, bus)
        self.engine = LocalEngine(s["local"], S.path(s["state_dir"]))

    def chat(self, req: ChatRequest, cancel: CancelToken) -> Iterator[ChatChunk]:
        if req.mode not in ("local", "auto"):
            yield _fail(f"LocalPort не обслуживает mode={req.mode}")
            return
        if not self.engine.ensure(lambda t, d: self._emit(t, d, req.task_id)):
            yield _fail("локальная модель недоступна: " + self.engine.error)
            return
        body = {"model": ALIAS, "messages": req.messages, "max_tokens": req.max_tokens,
                "cache_prompt": True,
                "id_slot": 0 if req.role == "main" else 1,
                "chat_template_kwargs": {"enable_thinking": False}}
        if req.tools:
            body["tools"] = req.tools
        if req.temperature is not None:
            body["temperature"] = req.temperature
        yield from self._run(self.engine.base_url, body, req, cancel)

    def unload_all(self) -> ResourceReport:
        before = gpu.settle_used_mb(2)
        self._emit("model.unloading", {"mode": "local"})
        r = self.engine.stop()
        after = gpu.settle_used_mb()
        foreign = [p for p in LocalEngine.find_llama() if not p["ours"]]
        ok = not r["survivors"]
        self._emit("model.unloaded", {"mode": "local", "vram_before_mb": before,
                                      "vram_after_mb": after, "ok": ok})
        detail = ""
        if foreign:
            detail = "чужие llama-server (не наши, не трогал): " + ", ".join(
                f"pid {p['pid']} порт {p['port']} alias {p['alias']}" for p in foreign)
        return ResourceReport("unload_all", ok, before, after, r["killed"],
                              r["survivors"], detail)

    def status(self) -> dict:
        used, total = gpu.vram_mb()
        return {"mode": "local", "engine": self.engine.status(),
                "vram_used_mb": used, "vram_total_mb": total, "last": self.last}


class CloudPort(_Base):
    mode = "cloud"

    def __init__(self, s: dict, bus: EventBus | None = None):
        super().__init__(s, bus)
        self.c = s["cloud"]

    def chat(self, req: ChatRequest, cancel: CancelToken) -> Iterator[ChatChunk]:
        if req.mode not in ("cloud", "auto"):
            yield _fail(f"CloudPort не обслуживает mode={req.mode}")
            return
        key = S.secret(self.s, self.c["key_ref"])
        if not key:
            yield _fail(f"нет ключа облака ({self.c['key_ref']} в {self.s['secrets_file']})")
            return
        body = {"model": self.c["model"], "messages": req.messages,
                "max_tokens": req.max_tokens}
        if req.tools:
            body["tools"] = req.tools
        if req.temperature is not None:
            body["temperature"] = req.temperature
        yield from self._run(self.c["base_url"], body, req, cancel, key,
                             float(self.c.get("timeout_s", 120)))

    def unload_all(self) -> ResourceReport:
        u, _ = gpu.vram_mb()
        return ResourceReport("unload_all", True, u, u, [], [],
                              "облако: на этой машине выгружать нечего")

    def status(self) -> dict:
        return {"mode": "cloud", "provider": self.c["provider"], "model": self.c["model"],
                "base_url": self.c["base_url"],
                "key_present": bool(S.secret(self.s, self.c["key_ref"])),
                "last": self.last}


def _fail(msg: str) -> ChatChunk:
    return ChatChunk(done=True, usage={"finish_reason": "error", "error": msg})
