"""LLM-менеджер: Ollama + LM Studio с переключателем и автофоллбэком.

Оба бэкенда опрашиваются на лету — UI показывает объединённый список моделей.
Если выбранный бэкенд упал, менеджер сам пробует второй и сообщает об этом.
"""
import json
import logging
import requests

from server.config import CFG

log = logging.getLogger("saika.llm")


class LLMError(Exception):
    pass


def _ollama_url():
    return CFG.get("llm.ollama_url", "http://127.0.0.1:11434").rstrip("/")


def _lmstudio_url():
    return CFG.get("llm.lmstudio_url", "http://127.0.0.1:1234").rstrip("/")


def list_models() -> list[dict]:
    """Объединённый список моделей обоих бэкендов: [{backend, name}]."""
    out = []
    try:
        r = requests.get(_ollama_url() + "/api/tags", timeout=3)
        for m in r.json().get("models", []):
            out.append({"backend": "ollama", "name": m["name"],
                        "size": m.get("size")})
    except Exception as e:
        log.debug("ollama offline: %s", e)
    try:
        r = requests.get(_lmstudio_url() + "/v1/models", timeout=3)
        for m in r.json().get("data", []):
            out.append({"backend": "lmstudio", "name": m["id"]})
    except Exception as e:
        log.debug("lmstudio offline: %s", e)
    return out


def loaded_models() -> list[str]:
    """Модели, реально сидящие в памяти: Ollama — /api/ps,
    LM Studio — /api/v0/models (поле state)."""
    out = []
    try:
        r = requests.get(_ollama_url() + "/api/ps", timeout=3)
        for m in r.json().get("models", []):
            name = m.get("name") or m.get("model")
            if name:
                out.append(name)
    except Exception:
        pass
    try:
        r = requests.get(_lmstudio_url() + "/api/v0/models", timeout=3)
        for m in r.json().get("data", []):
            if m.get("state") == "loaded" and m.get("id"):
                out.append(m["id"])
    except Exception:
        pass
    return out


def warmup(backend: str, model: str) -> bool:
    """Прогружает модель в память (блокирует, пока не загрузится).
    Для Ollama пустой prompt = «просто загрузи», ничего не генерится."""
    try:
        if backend == "ollama":
            requests.post(_ollama_url() + "/api/generate",
                          json={"model": model, "prompt": "",
                                "keep_alive": CFG.get("llm.keep_alive", "30m")},
                          timeout=900)
        else:
            requests.post(_lmstudio_url() + "/v1/chat/completions",
                          json={"model": model, "max_tokens": 1,
                                "messages": [{"role": "user", "content": "hi"}]},
                          timeout=900)
        log.info("Модель %s/%s прогрета", backend, model)
        return True
    except Exception as e:
        log.warning("Прогрев %s/%s не удался: %s", backend, model, e)
        return False


def unload_model(backend: str, model: str) -> bool:
    """Выгружает модель из памяти. Умеет только Ollama (keep_alive=0);
    LM Studio выгружает по своему TTL, ручки у него нет."""
    if backend != "ollama":
        return False
    requests.post(_ollama_url() + "/api/generate",
                  json={"model": model, "keep_alive": 0}, timeout=30)
    log.info("Модель %s выгружена", model)
    return True


def backend_status() -> dict:
    st = {}
    for name, url, probe in (
        ("ollama", _ollama_url(), "/api/tags"),
        ("lmstudio", _lmstudio_url(), "/v1/models"),
    ):
        try:
            requests.get(url + probe, timeout=2)
            st[name] = True
        except Exception:
            st[name] = False
    return st


def _pick_model(backend: str) -> str:
    model = CFG.get("llm.model", "")
    models = [m for m in list_models() if m["backend"] == backend]
    if model and any(m["name"] == model for m in models):
        return model
    if models:
        return models[0]["name"]
    raise LLMError(f"На бэкенде {backend} нет ни одной модели")


def _stream_ollama(messages, model, temperature, tools=None):
    """Стрим событий: {'type':'token','text':…} и {'type':'tool_call','call':…}."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {"temperature": temperature},
        # держим модель в памяти подольше: по умолчанию Ollama выгружает
        # через 5 минут простоя и «модель постоянно выключается»
        "keep_alive": CFG.get("llm.keep_alive", "30m"),
    }
    if tools:
        payload["tools"] = tools
    r = requests.post(_ollama_url() + "/api/chat", json=payload,
                      stream=True, timeout=(5, 600))
    r.raise_for_status()
    for line in r.iter_lines():
        if not line:
            continue
        chunk = json.loads(line)
        msg = chunk.get("message", {})
        token = msg.get("content", "")
        if token:
            yield {"type": "token", "text": token}
        for tc in msg.get("tool_calls") or []:
            yield {"type": "tool_call", "call": tc}
        if chunk.get("done"):
            break


def _stream_lmstudio(messages, model, temperature, tools=None):
    """Стрим событий, формат как у _stream_ollama.

    В OpenAI-совместимом API (которое отдаёт LM Studio) фрагменты tool_call
    приходят по кусочкам в разных чанках (по index, function.arguments —
    строка, собирается конкатенацией), поэтому копим их и достраиваем
    целиком только когда стрим закончился."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools

    def _do_request(body):
        r = requests.post(_lmstudio_url() + "/v1/chat/completions", json=body,
                          stream=True, timeout=(5, 600))
        r.raise_for_status()
        return r

    try:
        r = _do_request(payload)
    except requests.exceptions.HTTPError:
        if not tools:
            raise
        # некоторые модели/шаблоны в LM Studio не понимают параметр tools
        # и отвечают 400 — откатываемся на обычный чат без инструментов
        log.warning("LM Studio отверг tools (модель без function calling?) "
                    "— повторяю без инструментов")
        payload.pop("tools", None)
        r = _do_request(payload)

    calls = {}  # index -> {"name": str, "arguments": str}
    for line in r.iter_lines():
        if not line:
            continue
        text = line.decode("utf-8", "ignore")
        if not text.startswith("data:"):
            continue
        raw = text[5:].strip()
        if raw == "[DONE]":
            break
        try:
            delta = json.loads(raw)["choices"][0]["delta"]
        except Exception:
            continue
        token = delta.get("content") or ""
        if token:
            yield {"type": "token", "text": token}
        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index", 0)
            slot = calls.setdefault(idx, {"name": "", "arguments": ""})
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["name"] += fn["name"]
            if fn.get("arguments"):
                slot["arguments"] += fn["arguments"]

    for slot in calls.values():
        try:
            args = json.loads(slot["arguments"]) if slot["arguments"] else {}
        except Exception:
            args = {}
        yield {"type": "tool_call",
               "call": {"function": {"name": slot["name"], "arguments": args}}}


def chat_stream(messages, on_fallback=None, on_tool=None):
    """Стрим токенов. При падении основного бэкенда — автопереход на второй.

    Если запущен HandsPC (server/llm/tools.py), модель получает инструменты
    (web_search и др.) на ОБОИХ бэкендах: увидели tool_calls -> выполняем,
    подкладываем результаты и продолжаем диалог (до tools.max_rounds раундов).
    LM Studio: если загруженная модель/шаблон не понимает tools, сервер
    сам откатится на обычный чат без них (см. _stream_lmstudio) — тогда
    модель может по-прежнему писать инструменты текстом, это ограничение
    конкретной модели, не бага менеджера.
    on_tool(name, args) — колбэк для UI («🔎 ищу в сети…»).
    """
    from server.llm import tools as handspc

    primary = CFG.get("llm.backend", "ollama")
    secondary = "lmstudio" if primary == "ollama" else "ollama"
    temperature = CFG.get("llm.temperature", 0.8)
    last_err = None
    for backend in (primary, secondary):
        try:
            model = _pick_model(backend)
            fn = _stream_ollama if backend == "ollama" else _stream_lmstudio
            tools = handspc.schemas()
            if backend != primary and on_fallback:
                on_fallback(backend, model)

            msgs = list(messages)
            for _round in range(CFG.get("tools.max_rounds", 3) + 1):
                calls, text_parts = [], []
                for ev in fn(msgs, model, temperature, tools):
                    if ev["type"] == "token":
                        text_parts.append(ev["text"])
                        yield ev["text"]
                    else:
                        calls.append(ev["call"])
                if not calls or not tools:
                    return
                # выполняем инструменты и продолжаем разговор
                msgs.append({"role": "assistant",
                             "content": "".join(text_parts),
                             "tool_calls": calls})
                for c in calls:
                    f = c.get("function", {})
                    name = f.get("name", "")
                    args = f.get("arguments") or {}
                    if on_tool:
                        try:
                            on_tool(name, args)
                        except Exception:
                            pass
                    result = handspc.call(name, args)
                    log.info("tool %s(%s) -> %s символов",
                             name, args, len(result))
                    msgs.append({"role": "tool", "tool_name": name,
                                 "name": name, "content": result})
            return
        except Exception as e:
            last_err = e
            log.warning("LLM backend %s failed: %s", backend, e)
    raise LLMError(f"Оба LLM-бэкенда недоступны: {last_err}")


def chat_once(messages, max_len=4000) -> str:
    """Нестриминговый вызов — для суммаризации памяти."""
    return "".join(chat_stream(messages))[:max_len]
