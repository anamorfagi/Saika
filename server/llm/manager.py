"""LLM-менеджер: Ollama + LM Studio с переключателем и автофоллбэком.

Оба бэкенда опрашиваются на лету — UI показывает объединённый список моделей.
Если выбранный бэкенд упал, менеджер сам пробует второй и сообщает об этом.
"""
import json
import logging
import requests

from server.config import CFG, ROOT

log = logging.getLogger("saika.llm")


class LLMError(Exception):
    pass


def _ollama_url():
    return CFG.get("llm.ollama_url", "http://127.0.0.1:11434").rstrip("/")


def _lmstudio_url():
    return CFG.get("llm.lmstudio_url", "http://127.0.0.1:1234").rstrip("/")


# ---------------------- облачные (онлайн) модели по API-ключу ----------------
def _secrets() -> dict:
    """secrets.json (в .gitignore) — тут храним API-ключ облака, чтобы он не
    улетел в git при пуше."""
    p = ROOT / "secrets.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _cloud() -> dict:
    """Настройки облачного бэкенда. Ключ — из secrets.json (приоритет) или из
    config (запасной вариант). Дефолт base_url — OpenRouter (один ключ, много
    моделей; OpenAI-совместимый). Подходит и OpenAI/Groq/DeepSeek и т.п."""
    c = CFG.get("llm.cloud", {}) or {}
    key = ((_secrets().get("llm", {}) or {}).get("cloud_api_key", "")
           or c.get("api_key", ""))
    return {"enabled": bool(c.get("enabled")),
            "base_url": (c.get("base_url") or "https://openrouter.ai/api/v1").rstrip("/"),
            "model": c.get("model", ""), "key": key}


def save_cloud_key(key: str):
    """Пишем/обновляем API-ключ в secrets.json (не трогая остальное)."""
    p = ROOT / "secrets.json"
    data = _secrets()
    data.setdefault("llm", {})["cloud_api_key"] = key or ""
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_models() -> list[dict]:
    """Объединённый список моделей обоих бэкендов: [{backend, name, size}].
    size (байты) нужен UI для индикатора нагрузки на систему."""
    out = []
    # эвристика зрения по имени для Ollama (там нет поля capabilities)
    vhint = ("llava", "vision", "gemma3", "gemma-3", "gemma4", "gemma-4",
             "minicpm-v", "qwen2-vl", "qwen2.5-vl", "qwen3-vl", "llama3.2-vision",
             "moondream", "bakllava", "pixtral", "mllama", "-vl")
    rhint = ("r1", "qwq", "reason", "thinking", "deepseek-r")
    try:
        r = requests.get(_ollama_url() + "/api/tags", timeout=3)
        for m in r.json().get("models", []):
            nm = m["name"]
            low = nm.lower()
            out.append({"backend": "ollama", "name": nm, "size": m.get("size"),
                        "caps": {"vision": any(h in low for h in vhint),
                                 "tools": False,
                                 "reasoning": any(h in low for h in rhint)}})
    except Exception as e:
        log.debug("ollama offline: %s", e)
    # LM Studio: сперва REST API v1 — там есть size_bytes (для индикатора веса),
    # если версия старая и его нет, откатываемся на OpenAI-совместимый /v1/models
    lm_ok = False
    try:
        r = requests.get(_lmstudio_url() + "/api/v1/models", timeout=3)
        r.raise_for_status()
        for m in r.json().get("models", []):
            if m.get("type") == "embedding":
                continue
            caps = m.get("capabilities") or {}
            out.append({"backend": "lmstudio",
                        "name": m.get("key") or m.get("id"),
                        "size": m.get("size_bytes"),
                        "caps": {"vision": bool(caps.get("vision")),
                                 "tools": bool(caps.get("trained_for_tool_use")),
                                 "reasoning": bool(caps.get("reasoning"))}})
        lm_ok = True
    except Exception as e:
        log.debug("lmstudio REST v1 unavailable: %s", e)
    if not lm_ok:
        try:
            r = requests.get(_lmstudio_url() + "/v1/models", timeout=3)
            for m in r.json().get("data", []):
                out.append({"backend": "lmstudio", "name": m["id"],
                            "size": None})
        except Exception as e:
            log.debug("lmstudio offline: %s", e)
    # облачная модель (если включена) — показываем как выбираемую
    c = _cloud()
    if c["enabled"] and c["model"]:
        out.append({"backend": "cloud", "name": c["model"], "size": None})
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


def _loaded_with_backend() -> list[tuple]:
    """Список реально загруженных локальных моделей с бэкендом: [(backend,name)]."""
    out = []
    try:
        r = requests.get(_ollama_url() + "/api/ps", timeout=3)
        for m in r.json().get("models", []):
            n = m.get("name") or m.get("model")
            if n:
                out.append(("ollama", n))
    except Exception:
        pass
    try:
        r = requests.get(_lmstudio_url() + "/api/v0/models", timeout=3)
        for m in r.json().get("data", []):
            if m.get("state") == "loaded" and m.get("id"):
                out.append(("lmstudio", m["id"]))
    except Exception:
        pass
    return out


def unload_others(keep_backend: str, keep_model: str):
    """Выгружает ВСЕ прочие загруженные локальные модели, кроме указанной —
    чтобы две большие LLM не висели в памяти одновременно (это и вешало ПК
    чёрным экраном). Работает и через LM Studio, и через Ollama."""
    for b, n in _loaded_with_backend():
        if b == keep_backend and n == keep_model:
            continue
        try:
            if unload_model(b, n):
                log.info("Освободила память: выгрузила %s/%s", b, n)
        except Exception as e:
            log.warning("Не смогла выгрузить %s/%s: %s", b, n, e)


def switch_model(backend: str, model: str) -> bool:
    """Переключение LLM с защитой памяти: по умолчанию держим в памяти только
    ОДНУ модель (llm.keep_only_one) — сперва выгружаем прочие, потом греем
    новую. Нужны две сразу (маленькая+большая связка) — выключи keep_only_one."""
    if backend != "cloud" and CFG.get("llm.keep_only_one", True):
        unload_others(backend, model)
    return warmup(backend, model)


def warmup(backend: str, model: str) -> bool:
    """Прогружает модель в память (блокирует, пока не загрузится).
    Для Ollama пустой prompt = «просто загрузи», ничего не генерится."""
    if backend == "cloud":
        return True  # облако грузить не нужно — модель на стороне провайдера
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
    """Выгружает модель из памяти.
    Ollama — keep_alive=0. LM Studio — REST API v1 (/api/v1/models/unload,
    появился в актуальных версиях LM Studio; на старых вернёт False,
    выгружай через TTL или вручную в приложении)."""
    if backend == "ollama":
        requests.post(_ollama_url() + "/api/generate",
                      json={"model": model, "keep_alive": 0}, timeout=30)
        log.info("Модель %s выгружена", model)
        return True
    try:
        r = requests.post(_lmstudio_url() + "/api/v1/models/unload",
                          json={"instance_id": model}, timeout=30)
        r.raise_for_status()
        log.info("Модель %s выгружена (LM Studio)", model)
        return True
    except Exception as e:
        log.warning("LM Studio: выгрузка %s не удалась (нужна свежая версия "
                    "с REST API v1 /models/unload): %s", model, e)
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
    # облако: «на связи», если включено и есть ключ (не пингуем — это платно/долго)
    c = _cloud()
    st["cloud"] = bool(c["enabled"] and c["key"])
    return st


def _pick_model(backend: str) -> str:
    if backend == "cloud":
        m = _cloud()["model"]
        if m:
            return m
        raise LLMError("не задана онлайн-модель (меню модели → Онлайн)")
    model = CFG.get("llm.model", "")
    models = [m for m in list_models()
              if m["backend"] == backend and "embed" not in m["name"].lower()]
    if model and any(m["name"] == model for m in models):
        return model
    if models:
        # выбранной нет (выгружена/переименована) — берём уже загруженную
        # в память, а не первую попавшуюся (та может утянуть JIT-загрузку
        # совсем другой модели в LM Studio)
        try:
            loaded = set(loaded_models())
        except Exception:
            loaded = set()
        models.sort(key=lambda m: m["name"] not in loaded)
        return models[0]["name"]
    raise LLMError(f"На бэкенде {backend} нет ни одной модели")


def _img_b64(dataurl: str) -> str:
    """Из 'data:image/png;base64,XXXX' достаём чистый base64 (для Ollama)."""
    if dataurl and dataurl.startswith("data:") and "," in dataurl:
        return dataurl.split(",", 1)[1]
    return dataurl or ""


def _attach_image_ollama(messages, image):
    """Прикрепляем картинку к последнему сообщению пользователя (Ollama-формат:
    поле images со списком base64)."""
    if not image:
        return messages
    msgs = [dict(m) for m in messages]
    for m in reversed(msgs):
        if m.get("role") == "user":
            m["images"] = [_img_b64(image)]
            break
    return msgs


def _attach_image_openai(messages, image):
    """OpenAI-формат: content последнего user-сообщения становится списком
    [text, image_url(data-url)]."""
    if not image:
        return messages
    msgs = [dict(m) for m in messages]
    for m in reversed(msgs):
        if m.get("role") == "user":
            m["content"] = [{"type": "text", "text": m.get("content", "")},
                            {"type": "image_url", "image_url": {"url": image}}]
            break
    return msgs


def _stream_ollama(messages, model, temperature, tools=None, image=None):
    """Стрим событий: {'type':'token','text':…} и {'type':'tool_call','call':…}."""
    messages = _attach_image_ollama(messages, image)
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
    # think=false выключает «размышления» у reasoning-моделей (qwen3 и др.) —
    # это главный пожиратель секунд перед ответом. Модель без поддержки think
    # может ответить 400 — тогда повторяем без параметра.
    think = CFG.get("llm.think", False)
    if think is not None:
        payload["think"] = bool(think)
    try:
        r = requests.post(_ollama_url() + "/api/chat", json=payload,
                          stream=True, timeout=(5, 600))
        r.raise_for_status()
    except requests.exceptions.HTTPError:
        if "think" not in payload:
            raise
        payload.pop("think", None)
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


def _stream_lmstudio(messages, model, temperature, tools=None, image=None):
    """LM Studio — OpenAI-совместимый локальный сервер."""
    yield from _stream_openai(_lmstudio_url() + "/v1", None,
                              messages, model, temperature, tools, image)


def _stream_cloud(messages, model, temperature, tools=None, image=None):
    """Онлайн-модель по API-ключу (OpenRouter/OpenAI/Groq/… — OpenAI-совместимо)."""
    c = _cloud()
    if not c["key"]:
        raise LLMError("не задан API-ключ облачной модели — впиши его в "
                       "интерфейсе (меню модели → Онлайн) или в secrets.json")
    yield from _stream_openai(c["base_url"], c["key"],
                              messages, model, temperature, tools, image)


def _stream_openai(base_url, api_key, messages, model, temperature, tools=None,
                   image=None):
    """Общий OpenAI-совместимый стрим (LM Studio и облако).

    Фрагменты tool_call приходят по кусочкам в разных чанках (по index,
    function.arguments — строка, собирается конкатенацией), поэтому копим их
    и достраиваем целиком, когда стрим закончился."""
    messages = _attach_image_openai(messages, image)
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def _do_request(body):
        r = requests.post(base_url + "/chat/completions", json=body,
                          headers=headers, stream=True, timeout=(10, 600))
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

    calls = {}  # index -> {"id": str, "name": str, "arguments": str}
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
            slot = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["name"] += fn["name"]
            if fn.get("arguments"):
                slot["arguments"] += fn["arguments"]

    for i, slot in calls.items():
        try:
            args = json.loads(slot["arguments"]) if slot["arguments"] else {}
        except Exception:
            args = {}
        yield {"type": "tool_call",
               "call": {"id": slot["id"] or f"call_{i}",
                        "function": {"name": slot["name"], "arguments": args}}}


def chat_stream(messages, on_fallback=None, on_tool=None, image=None,
                on_model=None):
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
    from server import ratings

    primary = CFG.get("llm.backend", "ollama")
    temperature = CFG.get("llm.temperature", 0.8)
    last_err = None
    _fns = {"ollama": _stream_ollama, "lmstudio": _stream_lmstudio,
            "cloud": _stream_cloud}

    # ПОРЯДОК ФОЛЛБЭКА ПО РЕЙТИНГУ: сперва выбранная модель, затем ОСТАЛЬНЫЕ
    # локальные модели по убыванию оценки (лучшая — первой запаской). Так при
    # ошибке подхватывается хороший вариант, а не случайная мелкая модель.
    try:
        scores = ratings.llm_scores()
    except Exception:
        scores = {}
    candidates = []
    try:
        primary_model = _pick_model(primary)
        candidates.append((primary, primary_model))
    except Exception as e:
        last_err = e
    locals_ = []
    try:
        for m in list_models():
            # embedding-модели — никогда (это не чат); их попадание в фолбэк
            # заставляло LM Studio грузить nomic-embed как «собеседника»
            if (m["backend"] in ("ollama", "lmstudio")
                    and "embed" not in m["name"].lower()):
                locals_.append((m["backend"], m["name"]))
    except Exception:
        pass
    # уже загруженные в память — раньше по списку: фолбэк не должен
    # устраивать карусель JIT-загрузок в LM Studio
    try:
        loaded = set(loaded_models())
    except Exception:
        loaded = set()
    locals_.sort(key=lambda bm: (bm[1] not in loaded, -scores.get(bm[1], 0)))
    for bm in locals_:
        if bm not in candidates:
            candidates.append(bm)
    # максимум выбранная + 2 запасные: перебирать весь зоопарк моделей —
    # это минуты загрузок и непредсказуемое поведение
    candidates = candidates[:3]

    yielded_any = False
    for idx, (backend, model) in enumerate(candidates):
        # если уже начали писать ответ этой моделью и она вдруг споткнулась
        # (например контекст переполнился на 2-3 раунде инструментов) —
        # НЕ подхватываем чужой моделью посреди фразы: две разные "личности"
        # в одном сообщении читаются как баг, а не как фоллбэк. Сообщаем
        # об обрыве честно и на этом останавливаемся.
        if yielded_any:
            raise LLMError(f"{backend}/{model} прервалась на середине ответа: {last_err}")
        try:
            fn = _fns.get(backend, _stream_lmstudio)
            tools = handspc.schemas()
            if on_model:
                try:
                    on_model(backend, model)  # кто реально отвечает (для UI)
                except Exception:
                    pass
            if idx > 0 and on_fallback:
                on_fallback(backend, model)

            msgs = list(messages)
            for _round in range(CFG.get("tools.max_rounds", 3) + 1):
                calls, text_parts = [], []
                # картинку прикладываем только в первом раунде (это ход юзера)
                img = image if _round == 0 else None
                for ev in fn(msgs, model, temperature, tools, img):
                    if ev["type"] == "token":
                        text_parts.append(ev["text"])
                        yielded_any = True
                        yield ev["text"]
                    else:
                        calls.append(ev["call"])
                if not calls or not tools:
                    return
                # выполняем инструменты и продолжаем разговор.
                # Форматы у бэкендов разные: Ollama — arguments объектом и
                # tool_name в ответе; OpenAI-стиль (LM Studio/облако) —
                # arguments СТРОКОЙ и обязательный tool_call_id.
                if backend == "ollama":
                    msgs.append({"role": "assistant",
                                 "content": "".join(text_parts),
                                 "tool_calls": calls})
                else:
                    msgs.append({"role": "assistant",
                                 "content": "".join(text_parts) or None,
                                 "tool_calls": [
                                     {"id": c.get("id", f"call_{i}"),
                                      "type": "function",
                                      "function": {
                                          "name": c["function"].get("name", ""),
                                          "arguments": json.dumps(
                                              c["function"].get("arguments") or {},
                                              ensure_ascii=False)}}
                                     for i, c in enumerate(calls)]})
                for i, c in enumerate(calls):
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
                    if backend == "ollama":
                        msgs.append({"role": "tool", "tool_name": name,
                                     "name": name, "content": result})
                    else:
                        msgs.append({"role": "tool",
                                     "tool_call_id": c.get("id", f"call_{i}"),
                                     "content": result})
            return
        except Exception as e:
            last_err = e
            log.warning("LLM %s/%s failed: %s", backend, model, e)
    raise LLMError(f"Ни одна LLM не ответила: {last_err}")


def chat_once(messages, max_len=4000) -> str:
    """Нестриминговый вызов — для суммаризации памяти."""
    return "".join(chat_stream(messages))[:max_len]
