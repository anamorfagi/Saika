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
    """Модели, реально сидящие в памяти. Ollama отдаёт это через /api/ps;
    у LM Studio /v1/models и так показывает только загруженные."""
    out = []
    try:
        r = requests.get(_ollama_url() + "/api/ps", timeout=3)
        for m in r.json().get("models", []):
            name = m.get("name") or m.get("model")
            if name:
                out.append(name)
    except Exception:
        pass
    return out


def warmup(backend: str, model: str) -> bool:
    """Прогружает модель в память (блокирует, пока не загрузится).
    Для Ollama пустой prompt = «просто загрузи», ничего не генерится."""
    try:
        if backend == "ollama":
            requests.post(_ollama_url() + "/api/generate",
                          json={"model": model, "prompt": ""}, timeout=900)
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


def _stream_ollama(messages, model, temperature):
    r = requests.post(
        _ollama_url() + "/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature},
        },
        stream=True,
        timeout=(5, 600),
    )
    r.raise_for_status()
    for line in r.iter_lines():
        if not line:
            continue
        chunk = json.loads(line)
        token = chunk.get("message", {}).get("content", "")
        if token:
            yield token
        if chunk.get("done"):
            break


def _stream_lmstudio(messages, model, temperature):
    r = requests.post(
        _lmstudio_url() + "/v1/chat/completions",
        json={
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
        },
        stream=True,
        timeout=(5, 600),
    )
    r.raise_for_status()
    for line in r.iter_lines():
        if not line:
            continue
        text = line.decode("utf-8", "ignore")
        if not text.startswith("data:"):
            continue
        payload = text[5:].strip()
        if payload == "[DONE]":
            break
        try:
            delta = json.loads(payload)["choices"][0]["delta"]
            token = delta.get("content", "")
            if token:
                yield token
        except Exception:
            continue


def chat_stream(messages, on_fallback=None):
    """Стрим токенов. При падении основного бэкенда — автопереход на второй."""
    primary = CFG.get("llm.backend", "ollama")
    secondary = "lmstudio" if primary == "ollama" else "ollama"
    temperature = CFG.get("llm.temperature", 0.8)
    last_err = None
    for backend in (primary, secondary):
        try:
            model = _pick_model(backend)
            fn = _stream_ollama if backend == "ollama" else _stream_lmstudio
            if backend != primary and on_fallback:
                on_fallback(backend, model)
            yield from fn(messages, model, temperature)
            return
        except Exception as e:
            last_err = e
            log.warning("LLM backend %s failed: %s", backend, e)
    raise LLMError(f"Оба LLM-бэкенда недоступны: {last_err}")


def chat_once(messages, max_len=4000) -> str:
    """Нестриминговый вызов — для суммаризации памяти."""
    return "".join(chat_stream(messages))[:max_len]
