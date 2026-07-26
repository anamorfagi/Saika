"""LLM-менеджер: Ollama + LM Studio с переключателем и автофоллбэком.

Оба бэкенда опрашиваются на лету — UI показывает объединённый список моделей.
Если выбранный бэкенд упал, менеджер сам пробует второй и сообщает об этом.
"""
import json
import logging
import time

import requests

from server.config import CFG, ROOT

log = logging.getLogger("saika.llm")


class LLMError(Exception):
    pass


def _ollama_url():
    return CFG.get("llm.ollama_url", "http://127.0.0.1:11434").rstrip("/")


def _lmstudio_url():
    return CFG.get("llm.lmstudio_url", "http://127.0.0.1:1234").rstrip("/")


def _locallm_url():
    """Свой воркер LocalLM (workers/locallm_worker.py) — OpenAI-совместимый,
    как LM Studio, только модель живёт прямо в проекте (без Ollama/LM Studio)."""
    from server.llm import locallm
    return locallm.base_url()


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
    моделей; OpenAI-совместимый). Подходит и OpenAI/Groq/DeepSeek/Kimi и т.п.

    2026-07-23: ключи хранятся ПО-ПРОВАЙДЕРНО (llm.cloud_keys[provider]) —
    переключение OpenRouter↔Groq↔Kimi больше не затирает предыдущий ключ.
    Старый одиночный слот cloud_api_key остаётся запасным (миграция)."""
    c = CFG.get("llm.cloud", {}) or {}
    s = _secrets().get("llm", {}) or {}
    prov = c.get("provider", "openrouter")
    key = ((s.get("cloud_keys", {}) or {}).get(prov, "")
           or s.get("cloud_api_key", "")
           or c.get("api_key", ""))
    return {"enabled": bool(c.get("enabled")),
            "base_url": (c.get("base_url") or "https://openrouter.ai/api/v1").rstrip("/"),
            "model": c.get("model", ""), "key": key}


# ─────────────── СПИСОК НАСТРОЕННЫХ ОБЛАЧНЫХ МОДЕЛЕЙ ───────────────
# 2026-07-26, жалоба владельца: «добавил GigaChat, потом Mistral, потом
# GitHub Models — а модели куда-то исчезли». Ничего не исчезало: слот
# llm.cloud.{provider,base_url,model} ОДИН, и каждое «Сохранить и включить»
# затирало предыдущее. Ключи-то хранились по-провайдерно и уцелели, а вот
# сама пара адрес+модель — нет. Теперь настроенные облачные модели копятся
# списком и показываются в общем перечне наравне с локальными, между ними
# можно переключаться кликом.
_CLOUD_SAVED = "llm.cloud_saved"


def cloud_saved() -> list[dict]:
    """Все настроенные облачные модели. Текущую подмешиваем сюда же —
    так в список попадают и те, что настроены до появления реестра."""
    out, seen = [], set()
    for e in (CFG.get(_CLOUD_SAVED, []) or []):
        if not isinstance(e, dict):
            continue
        key = ((e.get("base_url") or "").rstrip("/"), e.get("model") or "")
        if not key[1] or key in seen:
            continue
        seen.add(key)
        out.append({"provider": e.get("provider", ""),
                    "base_url": key[0], "model": key[1]})
    c = CFG.get("llm.cloud", {}) or {}
    key = ((c.get("base_url") or "").rstrip("/"), c.get("model") or "")
    if key[1] and key not in seen:
        out.append({"provider": c.get("provider", ""),
                    "base_url": key[0], "model": key[1]})
    return out


def remember_cloud(provider: str, base_url: str, model: str):
    """Запомнить настроенную облачную модель (без ключа — он в secrets)."""
    if not model:
        return
    base = (base_url or "").rstrip("/")
    rest = [e for e in cloud_saved()
            if not (e["base_url"] == base and e["model"] == model)]
    # свежая — первой: чаще всего человек только что её и настраивал
    CFG.set(_CLOUD_SAVED, [{"provider": provider or "", "base_url": base,
                            "model": model}] + rest[:19])


def forget_cloud(model: str, base_url: str | None = None) -> str:
    """Убрать облачную модель из списка (крестик ✕ в перечне моделей).
    Ключ провайдера НЕ трогаем: у одного провайдера моделей много."""
    base = (base_url or "").rstrip("/")
    rest = [e for e in cloud_saved()
            if e["model"] != model or (base and e["base_url"] != base)]
    CFG.set(_CLOUD_SAVED, rest)
    # выкинули ту, что сейчас активна — переезжаем на первую оставшуюся,
    # иначе бэкенд «cloud» остался бы указывать в пустоту
    c = CFG.get("llm.cloud", {}) or {}
    if c.get("model") == model:
        if rest:
            use_cloud(rest[0]["model"], rest[0]["base_url"])
        else:
            CFG.set("llm.cloud.enabled", False)
    return f"«{model}» убрана из списка облачных моделей"


def use_cloud(model: str, base_url: str | None = None) -> dict:
    """Сделать эту облачную модель текущей: подставить её адрес и
    провайдера (а значит и её ключ из secrets.json)."""
    base = (base_url or "").rstrip("/")
    for e in cloud_saved():
        if e["model"] == model and (not base or e["base_url"] == base):
            CFG.set("llm.cloud.provider", e["provider"])
            CFG.set("llm.cloud.base_url", e["base_url"])
            CFG.set("llm.cloud.model", e["model"])
            CFG.set("llm.cloud.enabled", True)
            return e
    return {}


def save_cloud_key(key: str, provider: str | None = None):
    """Пишем/обновляем API-ключ в secrets.json (не трогая остальное).
    Ключ кладётся в слот СВОЕГО провайдера (cloud_keys[provider]) — у
    каждого облака свой ключ, и они не перетирают друг друга."""
    p = ROOT / "secrets.json"
    data = _secrets()
    prov = provider or CFG.get("llm.cloud.provider", "openrouter")
    llm_s = data.setdefault("llm", {})
    llm_s.setdefault("cloud_keys", {})[prov] = key or ""
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
    # своя LocalLM: показываем, если окружение установлено ИЛИ она выбрана
    # основным бэкендом (тогда спавнер сам поставит окружение при первом
    # запросе). Воркер может быть ещё не запущен — это нормально.
    try:
        from server.llm import locallm
        if locallm.installed() or CFG.get("llm.backend") == "locallm":
            out.append({"backend": "locallm", "name": locallm.model_name(),
                        "size": None,
                        "caps": {"vision": False, "tools": False,
                                 "reasoning": True}})
    except Exception as e:
        log.debug("locallm unavailable: %s", e)
    # ОБЛАЧНЫЕ: показываем ВСЕ настроенные, а не только активную. Раньше в
    # списке была одна — та, что записана в llm.cloud прямо сейчас, — и
    # выглядело это так, будто прежние «куда-то исчезли».
    c = CFG.get("llm.cloud", {}) or {}
    cur = ((c.get("base_url") or "").rstrip("/"), c.get("model") or "")
    for e in cloud_saved():
        out.append({"backend": "cloud", "name": e["model"], "size": None,
                    "provider": e["provider"], "base_url": e["base_url"],
                    "current": (e["base_url"], e["model"]) == cur,
                    "caps": {"vision": False, "tools": True,
                             "reasoning": False}})
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
    try:
        r = requests.get(_locallm_url() + "/health", timeout=2)
        if r.ok and r.json().get("model_loaded"):
            from server.llm import locallm
            out.append(locallm.model_name())
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
    try:
        r = requests.get(_locallm_url() + "/health", timeout=2)
        if r.ok and r.json().get("model_loaded"):
            from server.llm import locallm
            out.append(("locallm", locallm.model_name()))
    except Exception:
        pass
    return out


def unload_others(keep_backend: str, keep_model: str) -> list:
    """Выгружает ВСЕ прочие загруженные локальные модели, кроме указанной —
    чтобы две большие LLM не висели в памяти одновременно (это и вешало ПК
    чёрным экраном). Работает и через LM Studio, и через Ollama.

    Возвращает список (backend, model) моделей, которые выгрузить НЕ
    удалось — раньше это молча терялось в логе, и владелец видел «клик по
    модели — предыдущая всё ещё в памяти» без единого объяснения (частая
    причина: старая версия LM Studio без REST API /models/unload)."""
    failed = []
    for b, n in _loaded_with_backend():
        if b == keep_backend and n == keep_model:
            continue
        try:
            if unload_model(b, n):
                log.info("Освободила память: выгрузила %s/%s", b, n)
            else:
                failed.append((b, n))
        except Exception as e:
            log.warning("Не смогла выгрузить %s/%s: %s", b, n, e)
            failed.append((b, n))
    return failed


def switch_model(backend: str, model: str) -> dict:
    """Переключение LLM с защитой памяти: по умолчанию держим в памяти только
    ОДНУ модель (llm.keep_only_one) — сперва выгружаем прочие, потом греем
    новую. Нужны две сразу (маленькая+большая связка) — выключи keep_only_one.

    Возвращает {"ok": bool, "unload_failed": [(backend, model), …]} — раньше
    отдавался голый bool, и молчаливый провал выгрузки старой модели (см.
    unload_others) никак не долетал до UI/чата."""
    unload_failed = []
    if backend != "cloud" and CFG.get("llm.keep_only_one", True):
        unload_failed = unload_others(backend, model)
    ok = warmup(backend, model)
    return {"ok": ok, "unload_failed": unload_failed}


def prewarm_context(backend: str, model: str, system_text: str):
    """Прогрев KV-кэша БОЕВЫМ префиксом (персоной) — быстрый старт
    2026-07-23. warmup() греет модель крошечным 'hi', и первый реальный
    ответ платил полный prefill персоны (~9с холодный). Скормив персону
    заранее, первый ответ докатывает только хвост (память/история) — ~1с.
    Работает для openai-бэкендов (llama.cpp/LM Studio переиспользуют KV по
    совпадению префикса); ollama греется своим keep_alive."""
    try:
        if backend == "locallm":
            url = _locallm_url()
        elif backend == "lmstudio":
            url = _lmstudio_url()
        else:
            return
        requests.post(url + "/v1/chat/completions",
                      json={"model": model, "stream": False, "max_tokens": 1,
                            "chat_template_kwargs": {"enable_thinking": False},
                            "messages": [
                                {"role": "system", "content": system_text},
                                {"role": "user", "content": "Привет"}]},
                      timeout=300)
        log.info("KV-кэш прогрет персоной (%s/%s)", backend, model)
    except Exception as e:
        log.info("Прогрев персоной пропущен: %s", e)


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
        elif backend == "locallm":
            from server.llm import locallm
            st = locallm.ensure_running()
            if st.get("error"):
                raise LLMError(st["error"])
            requests.post(_locallm_url() + "/v1/chat/completions",
                          json={"model": model, "max_tokens": 1,
                                "messages": [{"role": "user", "content": "hi"}]},
                          timeout=900)
        else:
            requests.post(_lmstudio_url() + "/v1/chat/completions",
                          json={"model": model, "max_tokens": 1,
                                "messages": [{"role": "user", "content": "hi"}]},
                          timeout=900)
        log.info("Модель %s/%s прогрета", backend, model)
        try:
            from server.llm import passport
            passport.ensure_async(backend, model)  # паспорт: пробы в фоне
        except Exception:
            pass
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
    if backend == "locallm":
        try:
            requests.post(_locallm_url() + "/admin/unload", timeout=30)
            log.info("Модель %s выгружена (LocalLM)", model)
            return True
        except Exception as e:
            log.warning("LocalLM: выгрузка не удалась: %s", e)
            return False
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


def delete_model(backend: str, model: str) -> str:
    """Удаляет модель С ДИСКА (крестик ✕ в списке моделей UI).
    Ollama — родное API /api/delete. LM Studio — своего API удаления нет:
    выгружаем из памяти и сносим папку модели в каталоге LM Studio
    (~/.lmstudio/models/издатель/модель, старые версии — ~/.cache/lm-studio).
    Возвращает человеческое описание результата, кидает RuntimeError с
    понятной причиной, если удалить нельзя."""
    if backend == "ollama":
        r = requests.delete(_ollama_url() + "/api/delete",
                            json={"model": model, "name": model}, timeout=120)
        if r.status_code == 404:
            raise RuntimeError(f"Ollama не знает модель {model}")
        r.raise_for_status()
        log.info("Модель %s УДАЛЕНА из Ollama", model)
        return f"{model} удалена из Ollama"
    if backend == "lmstudio":
        try:
            unload_model("lmstudio", model)
        except Exception:
            pass
        import shutil
        from pathlib import Path
        home = Path.home()
        roots = [home / ".lmstudio" / "models",
                 home / ".cache" / "lm-studio" / "models"]
        # каталог LM Studio часто ПЕРЕНЕСЁН на другой диск — настоящий путь
        # лежит в файле-указателе ~/.lmstudio-home-pointer (первая строка)
        try:
            ptr = home / ".lmstudio-home-pointer"
            if ptr.exists():
                target = Path(ptr.read_text(encoding="utf-8",
                                            errors="ignore")
                              .strip().splitlines()[0].strip())
                if target.exists():
                    roots.insert(0, target / "models")
        except Exception as e:
            log.debug("lmstudio home-pointer: %s", e)
        for root in roots:
            if not root.exists():
                continue
            cand = (root / Path(*model.split("/"))).resolve()
            # защита от выхода за каталог моделей (имя с ..)
            if not str(cand).startswith(str(root.resolve())):
                continue
            if cand.is_dir():
                shutil.rmtree(cand)
                log.info("Модель %s УДАЛЕНА с диска (%s)", model, cand)
                return f"{model}: файлы стёрты ({cand})"
        raise RuntimeError(
            "папка модели не нашлась в каталоге LM Studio — удали её в самом "
            "LM Studio (My Models)")
    raise RuntimeError("удаление умею для Ollama и LM Studio; облако — это "
                       "просто настройка, а LocalLM-модели лежат в models/ "
                       "проекта")


def backend_status() -> dict:
    st = {}
    for name, url, probe in (
        ("ollama", _ollama_url(), "/api/tags"),
        ("lmstudio", _lmstudio_url(), "/v1/models"),
        ("locallm", _locallm_url(), "/v1/models"),
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
    [text, image_url(data-url)].

    2026-07-23: реальный инцидент — пользователь прислал ТОЛЬКО картинку, без
    подписи (текст ''). Пустая text-часть тут же ловилась 400 у Moonshot/Kimi
    («text content is empty»), и — куда хуже — эта пустая user-реплика
    сохранялась в память и лежала в истории ПОСТОЯННО: Kimi 400-ила на КАЖДОМ
    следующем ходу («message at position 8 with role user must not be
    empty»), пока не отвалилась совсем — Сайка молча и незаметно для
    пользователя осталась сидеть на мелкой локальной модели. Пустой text
    рядом с картинкой больше никогда не уходит наружу."""
    if not image:
        return messages
    msgs = [dict(m) for m in messages]
    for m in reversed(msgs):
        if m.get("role") == "user":
            _txt = (m.get("content") or "").strip() or "(без подписи — просто посмотри)"
            m["content"] = [{"type": "text", "text": _txt},
                            {"type": "image_url", "image_url": {"url": image}}]
            break
    return msgs


# Маркеры «пользователь просит длинный ответ» — сказка, разбор, текст и т.п.
# Для таких запросов лимита длины нет вообще. Для коротких бытовых реплик —
# мягкая рамка (llm.max_tokens_short), чтобы мелкая модель не лила портянки
# на «привет, как дела». Основной механизм — правила в промпте, лимит — страховка.
_LONGFORM_MARKERS = (
    "расскаж", "сказк", "истори", "объясн", "напиши", "опиши", "разбор",
    "подробн", "развёрнут", "разверни", "план", "стих", "песн", "доклад",
    "инструкц", "гайд", "шаги", "почему", "как работает", "сочини", "придумай",
    "перескажи", "переведи", "сравни", "список")


def _max_tokens_for(messages) -> int | None:
    """None = без лимита. Число = мягкая рамка для короткой бытовой реплики."""
    last_user = next((m["content"] for m in reversed(messages)
                      if m.get("role") == "user"), "")
    if isinstance(last_user, list):  # мультимодальное сообщение
        last_user = " ".join(p.get("text", "") for p in last_user
                             if isinstance(p, dict))
    text = last_user.lower()
    if len(text) > 120 or any(m in text for m in _LONGFORM_MARKERS):
        return None
    limit = int(CFG.get("llm.max_tokens_short", 300))
    return limit if limit > 0 else None


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
    # Ollama: мягкий лимит безопасен, только если «размышления» выключены
    # (think=false ниже) — иначе лимит съедается мыслями и ответ пустой
    if not CFG.get("llm.think", False):
        mt = _max_tokens_for(messages)
        if mt:
            payload["options"]["num_predict"] = mt
    if tools:
        payload["tools"] = tools
    # продвинутый сэмплинг: у Ollama он живёт в options и без XTC/DRY
    payload["options"].update(_sampling_fields(_SAMPLING_OLLAMA))
    # think=false выключает «размышления» у reasoning-моделей (qwen3 и др.) —
    # это главный пожиратель секунд перед ответом. Модель без поддержки think
    # может ответить 400 — тогда повторяем без параметра.
    think = CFG.get("llm.think", False)
    if think is not None:
        payload["think"] = bool(think)
    def _post_chat():
        rr = requests.post(_ollama_url() + "/api/chat", json=payload,
                           stream=True, timeout=(5, 600))
        rr.raise_for_status()
        return rr

    try:
        r = _post_chat()
    except requests.exceptions.HTTPError:
        # 400 бывает по трём причинам — снимаем подозреваемых по одному:
        # think не поддержан -> без think; картинка на не-vision модели ->
        # без картинки; tools не поддержаны -> без tools.
        recovered = False
        for fix, action in (
            ("think", lambda: payload.pop("think", None)),
            ("image", lambda: payload.__setitem__(
                "messages", [
                    {k: v for k, v in m.items() if k != "images"}
                    for m in payload["messages"]])),
            ("tools", lambda: payload.pop("tools", None)),
        ):
            if fix == "think" and "think" not in payload:
                continue
            if fix == "image" and not image:
                continue
            if fix == "image":
                try:  # запоминаем ОПЫТ: эта модель без зрения
                    from server import capabilities as _caps
                    _caps.note(model, "vision", False)
                except Exception:
                    pass
            if fix == "tools" and not payload.get("tools"):
                continue
            action()
            log.warning("Ollama 400 — пробую без %s", fix)
            try:
                r = _post_chat()
                recovered = True
                break
            except requests.exceptions.HTTPError:
                continue
        if not recovered:
            raise
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


def _stream_locallm(messages, model, temperature, tools=None, image=None):
    """Свой воркер LocalLM: сперва убеждаемся, что он поднят (спавнер сам
    поставит окружение/запустит процесс), затем — обычный OpenAI-стрим.
    tools воркер в v1 игнорирует молча (без 400), картинок у модели нет —
    _attach_image_openai всё равно приложит, воркер сам отбросит."""
    from server.llm import locallm
    st = locallm.ensure_running()
    if st.get("error"):
        raise LLMError("LocalLM: " + st["error"])
    if st.get("installing"):
        raise LLMError("LocalLM " + st.get(
            "note", "ещё устанавливается — попробуй через пару минут"))
    yield from _stream_openai(_locallm_url() + "/v1", None,
                              messages, model, temperature, tools, image)


# ─────────────────── GigaChat: токен вместо ключа ───────────────────
# Единственный провайдер в нашем списке, где «вставь API-ключ» не работает
# как у всех: Сбер выдаёт Authorization key, который надо МЕНЯТЬ на
# access-токен, живущий 30 минут. Зато это единственный вариант для человека
# из России без VPN, без карты и без зарубежного телефона — ради этого стоит
# держать отдельную ветку.
_GIGA_OAUTH = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
_giga = {"token": "", "exp": 0.0, "verify": True}


def _is_gigachat(base_url: str) -> bool:
    # Сбер развёл два адреса на один и тот же API: старый
    # gigachat.devices.sberbank.ru и новый api.giga.chat (его теперь
    # показывают в кабинете). Оба ходят через один OAuth и одинаково не
    # терпят системное сообщение в середине — распознаём оба.
    u = (base_url or "").lower()
    return "gigachat.devices.sberbank.ru" in u or "api.giga.chat" in u


def _gigachat_token(auth_key: str) -> str:
    """Access-токен Сбера. Кэшируем до истечения минус минута запаса."""
    import uuid
    if _giga["token"] and time.time() < _giga["exp"] - 60:
        return _giga["token"]
    body = {"scope": CFG.get("llm.cloud.giga_scope", "GIGACHAT_API_PERS")}
    headers = {"Authorization": "Basic " + auth_key.strip(),
               "RqUID": str(uuid.uuid4()),
               "Content-Type": "application/x-www-form-urlencoded"}
    last = None
    # Сбер отдаёт сертификат, подписанный российским УЦ: в системном
    # хранилище Windows его может не быть, и requests падает на проверке.
    # Сначала пробуем честно, потом без проверки — с громким предупреждением
    # в лог, чтобы это не выглядело нормой.
    for verify in ([True, False] if _giga["verify"] else [False]):
        try:
            r = requests.post(_GIGA_OAUTH, headers=headers, data=body,
                              timeout=20, verify=verify)
            r.raise_for_status()
            j = r.json()
            _giga["token"] = j.get("access_token", "")
            # expires_at приходит в миллисекундах
            exp = float(j.get("expires_at", 0) or 0)
            _giga["exp"] = exp / 1000.0 if exp > 1e11 else (
                time.time() + (exp or 1800))
            _giga["verify"] = verify
            if not verify:
                log.warning("GigaChat: TLS-сертификат Сбера не проверяется "
                            "(нет российского корневого УЦ в системе). "
                            "Поставь сертификаты Минцифры, чтобы убрать это.")
            log.info("GigaChat: токен получен, живёт %.0f мин",
                     max(0, (_giga["exp"] - time.time()) / 60))
            return _giga["token"]
        except Exception as e:
            last = e
    raise LLMError(f"GigaChat не отдал токен: {last}. Проверь Authorization "
                   f"key в меню модели → Онлайн (это длинная base64-строка "
                   f"из кабинета Сбера, а не Client Secret отдельно).")


def _stream_cloud(messages, model, temperature, tools=None, image=None):
    """Онлайн-модель по API-ключу (Groq/Mistral/GitHub/GigaChat/… —
    OpenAI-совместимо)."""
    c = _cloud()
    if not c["key"]:
        raise LLMError("не задан API-ключ облачной модели — впиши его в "
                       "интерфейсе (меню модели → Онлайн) или в secrets.json")
    key = c["key"]
    if _is_gigachat(c["base_url"]):
        key = _gigachat_token(key)
    yield from _stream_openai(c["base_url"], key,
                              messages, model, temperature, tools, image)


# ЗАНЯТОСТЬ бэкенда живым диалогом (2026-07-23). Обнаружено по логу
# пользователя: passport.ensure_async() запускает фоновые пробы (ping +
# несколько big-prompt попыток + tools-проба, суммарно МИНУТЫ, каждая —
# отдельный блокирующий HTTP-запрос той же модели) через 180с после
# warmup(). Но у Ollama/LM Studio модель обслуживает запросы ПО ОДНОМУ —
# если за эти 180с пользователь продолжает живой разговор (частый случай:
# только что переключил модель и тут же тестирует её), проба и настоящий
# ответ дерутся за одну и ту же модель. В логе это выглядело как
# «думала 76.3с» / «думала 253.2с» (обрыв по таймауту 180с) на gemma4:26b
# и ping_s=40.8 у паспорта gemma4:12b — ровно во время probe-окон.
# Фикс: живой чат метит бэкенд «занят» на каждый токен, паспорт ждёт тишины.
_BUSY: dict = {}
_BUSY_GRACE_S = 20  # столько секунд после последнего токена бэкенд ещё "занят"


def mark_busy(backend: str, model: str):
    _BUSY[(backend, model)] = time.time() + _BUSY_GRACE_S


def is_busy(backend: str, model: str) -> bool:
    return time.time() < _BUSY.get((backend, model), 0.0)


# Причуды конкретных API, выученные на лету: (base_url, model) -> поля,
# которые этот провайдер не принимает (2026-07-23: Moonshot/kimi-k3 отвечает
# 400 «invalid temperature: only 1 is allowed» на наш temperature=0.8).
# Выучив один раз, дальше строим запрос сразу без неугодного поля — без
# трёх холостых запросов на каждую фразу.
_API_QUIRKS: dict = {}

# ФОРМА СООБЩЕНИЙ, а не поля запроса (2026-07-26). GigaChat отвечает
# 422 «Invalid params: system message must be the first message» — он
# принимает ровно ОДНО системное сообщение и только первым. У нас же вся
# динамика хода (память, лорбук, зрение) намеренно уезжает отдельным
# system-сообщением В КОНЕЦ, перед последней фразой человека: так стабильный
# префикс не ломается и KV-кэш живёт (см. комментарий в run_dialog). Для
# таких провайдеров склеиваем «поздний system» с ближайшей репликой
# пользователя — смысл и позиция сохраняются, ценой кэша (у облака он всё
# равно не наш).
_MSG_QUIRKS: dict = {}
_MID_SYSTEM_HINTS = ("system message must be the first",
                     "system message must be first",
                     "only one system message",
                     "system role must be the first")


def _fold_mid_system(messages):
    """Системные сообщения ПОСЛЕ первого вклеиваем в следующую реплику
    пользователя. Возвращает новый список, исходный не трогаем."""
    out, pending = [], []
    for i, m in enumerate(messages):
        if i > 0 and m.get("role") == "system":
            txt = m.get("content")
            # мультимодальный content (список частей) сюда не попадает:
            # системные блоки у нас всегда текст
            if isinstance(txt, str) and txt.strip():
                pending.append(txt.strip())
            continue
        if pending and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                m = dict(m, content="\n\n".join(pending) + "\n\n" + c)
                pending = []
            elif isinstance(c, list):
                # картинка + текст: своё вставляем отдельной текстовой частью
                m = dict(m, content=[{"type": "text",
                                      "text": "\n\n".join(pending)}] + c)
                pending = []
        out.append(m)
    if pending:
        # не нашлось пользовательской реплики после — цепляем к последней
        if out:
            last = out[-1]
            c = last.get("content")
            if isinstance(c, str):
                out[-1] = dict(last, content=c + "\n\n"
                               + "\n\n".join(pending))
            else:
                out.append({"role": "user", "content": "\n\n".join(pending)})
        else:
            out.append({"role": "user", "content": "\n\n".join(pending)})
    return out

# ─────────────────── ПРОДВИНУТЫЙ СЭМПЛИНГ (2026-07-26) ───────────────────
# Раньше из настроек генерации у нас была одна temperature. Этого мало:
# главные болезни локальных мелких моделей — повторы и вялость — лечатся не
# температурой, а DRY (штраф за повторяющиеся n-граммы) и XTC (выбрасывание
# самых вероятных токенов, чтобы речь не сползала в шаблон).
#
# Поля кладём на верхний уровень JSON: llama.cpp и LM Studio читают их прямо
# оттуда (в python-SDK это называлось бы extra_body, но мы шлём сырой HTTP).
# Провайдеры, которые их не знают, ответят 400 — и сработает уже готовый
# механизм _API_QUIRKS: он запомнит, что этому API сэмплинг не давать, и
# следующий запрос уйдёт сразу без него. Одним куском, а не по полю за раз.
_SAMPLING_OPENAI = (
    "top_p", "top_k", "min_p", "typical_p", "repeat_penalty",
    "presence_penalty", "frequency_penalty", "stop", "seed",
    "xtc_probability", "xtc_threshold",
    "dry_multiplier", "dry_base", "dry_allowed_length",
    "dynatemp_range", "dynatemp_exponent",
)
# Ollama знает НЕ ВСЁ: XTC/DRY/dynatemp у него нет, поэтому шлём подмножество
# и внутрь options, а не на верхний уровень.
_SAMPLING_OLLAMA = ("top_p", "top_k", "min_p", "typical_p", "repeat_penalty",
                    "presence_penalty", "frequency_penalty", "stop", "seed")

# 0 или -1 значит «параметр выключен» — такие вообще не шлём, чтобы не
# навязывать модели дефолт, отличный от её собственного.
_SAMPLING_OFF_AT_ZERO = {
    "top_k", "min_p", "typical_p", "presence_penalty", "frequency_penalty",
    "xtc_probability", "dry_multiplier", "dynatemp_range",
}


def sampling_cfg() -> dict:
    """Настройки сэмплинга из config (llm.sampling). enabled=false — пусто."""
    s = CFG.get("llm.sampling", {}) or {}
    return s if s.get("enabled") else {}


def _sampling_fields(keys) -> dict:
    """Отобрать из конфига то, что имеет смысл послать."""
    cfg = sampling_cfg()
    out = {}
    for k in keys:
        if k not in cfg:
            continue
        v = cfg[k]
        if v is None:
            continue
        if k == "stop":
            v = [x for x in (v if isinstance(v, list) else [v]) if str(x).strip()]
            if not v:
                continue
        elif k == "seed":
            if int(v) < 0:
                continue
        elif k in _SAMPLING_OFF_AT_ZERO and float(v) == 0:
            continue
        out[k] = v
    return out


def _stream_openai(base_url, api_key, messages, model, temperature, tools=None,
                   image=None):
    """Общий OpenAI-совместимый стрим (LM Studio и облако).

    Фрагменты tool_call приходят по кусочкам в разных чанках (по index,
    function.arguments — строка, собирается конкатенацией), поэтому копим их
    и достраиваем целиком, когда стрим закончился."""
    messages = _attach_image_openai(messages, image)
    # GigaChat известен заранее, остальных выучиваем по первому 422 (ниже)
    if _is_gigachat(base_url) or "mid_system" in _MSG_QUIRKS.get(
            (base_url, model), ()):
        messages = _fold_mid_system(messages)
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
    }
    # НИКАКОГО max_tokens здесь: gemma-4 и другие думающие модели сначала
    # тратят токены на размышление и только потом пишут ответ. Лимит 300
    # съедался мыслями целиком — наружу приходило 0 токенов, «Сайка молчит»
    # (2026-07-21). Краткость держат правила в промпте, от зацикливания —
    # LoopGuard с аварийным потолком.
    if not CFG.get("llm.think", False):
        # выключенные «размышления» (тумблер 💭 в меню модели): просим шаблон
        # не включать thinking-фазу. llama.cpp/LM Studio понимают
        # chat_template_kwargs, остальные молча игнорируют поле.
        payload["chat_template_kwargs"] = {"enable_thinking": False}
        # целевое время ответа (llm.target_response_s, 0 = выкл): если
        # паспорт знает скорость модели — считаем потолок токенов под цель.
        # ТОЛЬКО при выключенных размышлениях: думающий режим съедает лимит
        # мыслями и получает 0 токенов ответа (грабли 2026-07-21).
        try:
            from server.llm import passport
            target = float(CFG.get("llm.target_response_s", 0) or 0)
            tps = passport.tps_for(model)
            if target > 0 and tps:
                payload["max_tokens"] = max(96, int(tps * target * 0.8))
        except Exception:
            pass
    if tools:
        payload["tools"] = tools
    # ПОВТОРНОЕ ИСПОЛЬЗОВАНИЕ KV-КЭША. llama.cpp-server (и LM Studio на нём)
    # понимают cache_prompt: совпавший префикс промпта не пережёвывается
    # заново. У свежих сборок это уже по умолчанию, у сборок постарше — нет,
    # и тогда каждый ход стоит полного prefill всех ~5 тысяч токенов. Поле
    # безобидное: провайдер, который его не знает, ответит 400, и _API_QUIRKS
    # уберёт его навсегда после одного холостого захода. Облаку не шлём —
    # там кэш префикса на стороне провайдера и своими правилами.
    if not api_key and CFG.get("llm.cache_prompt", True):
        payload["cache_prompt"] = True
    # продвинутый сэмплинг — панель «Сэмплинг» в меню модели
    payload.update(_sampling_fields(_SAMPLING_OPENAI))
    # 2026-07-23: облако (Kimi/Moonshot) по 7-47с «думает» даже на реплики в
    # 30-90 токенов — то есть почти всё время это ПРЕФИЛЛ растущей истории,
    # не генерация. Moonshot заявляет автоматическое кэширование префикса
    # (без нашего участия, просто по совпадению начала запроса), но со
    # стороны не видно, попадаем мы в кэш или нет. stream_options.include_usage
    # — стандартное OpenAI-расширение, просим провайдера вернуть usage в
    # финальном чанке стрима; ЕСЛИ там есть поля про кэш (у части провайдеров
    # это prompt_tokens_details.cached_tokens) — увидим в логе и поймём,
    # реально ли работает кэш или бьёмся об одну и ту же стену каждый раз.
    # 2026-07-26: просим usage и у ЛОКАЛЬНЫХ бэкендов тоже. Без него
    # непонятно, сколько токенов реально ушло в prefill — а без этого числа
    # «prefill 2.3с» невозможно оценить: то ли промпт огромный, то ли кэш не
    # сработал и модель жуёт его целиком каждый ход. Если LM Studio/llama.cpp
    # поля не знает — сработает _API_QUIRKS и уберёт его навсегда.
    payload["stream_options"] = {"include_usage": True}
    # выученные причуды этого API: неугодные поля не кладём с самого начала
    for f in _API_QUIRKS.get((base_url, model), ()):
        payload.pop(f, None)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    # у GigaChat та же история с российским УЦ, что и у его OAuth —
    # решение принято один раз в _gigachat_token и переиспользуется здесь
    _verify = _giga["verify"] if _is_gigachat(base_url) else True

    def _do_request(body):
        r = requests.post(base_url + "/chat/completions", json=body,
                          headers=headers, stream=True, timeout=(10, 600),
                          verify=_verify)
        if not r.ok:
            # тело ответа — единственное место, где провайдер объясняет,
            # ЧТО ему не понравилось («unknown field», «model not found»…).
            # requests.HTTPError сам по себе теряет его (только код и URL) —
            # 2026-07-23: именно из-за этого Kimi/облако тихо фолбэчилось на
            # локальную модель, а причина не долетала даже до лога.
            detail = ""
            try:
                detail = r.text[:400]
            except Exception:
                pass
            err = requests.exceptions.HTTPError(
                f"{r.status_code} от {base_url}: {detail}", response=r)
            raise err
        return r

    try:
        r = _do_request(payload)
    except requests.exceptions.HTTPError as e0:
        # 400/422 бывает по РАЗНЫМ причинам у разных облаков: строгий
        # temperature у Moonshot («only 1 is allowed»), незнакомый
        # chat_template_kwargs (расширение llama.cpp/LM Studio), кривые
        # tools-схемы. Ищем виновника ПО ОДНОМУ (не скопом — иначе вместе с
        # виноватым полем навсегда потеряли бы, например, инструменты),
        # а найденное запоминаем в _API_QUIRKS: следующая фраза строит
        # запрос сразу правильно, без холостых заходов.
        recovered, last = False, e0
        # ФАЗА 0 — провайдер ругается не на поле, а на СТРУКТУРУ диалога.
        # Убирать поля тут бессмысленно (именно так GigaChat молча уводил
        # разговор на локальный фолбэк): чиним форму и пробуем ещё раз.
        _txt = str(e0).lower()
        if any(h in _txt for h in _MID_SYSTEM_HINTS):
            trial = dict(payload, messages=_fold_mid_system(payload["messages"]))
            try:
                r = _do_request(trial)
                payload = trial
                _MSG_QUIRKS.setdefault((base_url, model),
                                       set()).add("mid_system")
                log.warning("API %s принимает system только первым — "
                            "запомнила, дальше склеиваю поздние системные "
                            "блоки с репликой пользователя", model)
                recovered = True
            except requests.exceptions.HTTPError as e1:
                last = e1
        suspects = [] if recovered else [
            f for f in ("tools", "chat_template_kwargs", "cache_prompt",
                                "max_tokens", "temperature", "stream_options")
                    if payload.get(f) is not None]
        # «sampling» — не поле, а целая группа: снимаем её ОДНИМ ходом.
        # Иначе перебор по одному стоил бы до 16 холостых запросов на фразу,
        # а провайдер, который не знает XTC, обычно не знает и DRY.
        if not recovered and any(k in payload for k in _SAMPLING_OPENAI):
            suspects.insert(0, "sampling")
        for fix in suspects:                    # фаза 1: по одному
            if fix == "sampling":
                trial = {k: v for k, v in payload.items()
                         if k not in _SAMPLING_OPENAI}
            else:
                trial = {k: v for k, v in payload.items() if k != fix}
            try:
                r = _do_request(trial)
                recovered = True
                payload = trial
                bad = (set(_SAMPLING_OPENAI) if fix == "sampling" else {fix})
                _API_QUIRKS.setdefault((base_url, model), set()).update(bad)
                log.warning("API %s не принял «%s» (%s) — запомнила, "
                            "дальше шлю без него", model, fix,
                            str(last)[:160])
                break
            except requests.exceptions.HTTPError as e1:
                last = e1
        if not recovered and len(suspects) > 1:  # фаза 2: все разом
            trial = {k: v for k, v in payload.items() if k not in suspects}
            try:
                r = _do_request(trial)
                recovered = True
                payload = trial
                _API_QUIRKS.setdefault((base_url, model),
                                       set()).update(suspects)
                log.warning("API %s принял запрос только без %s — запомнила",
                            model, ", ".join(suspects))
            except requests.exceptions.HTTPError as e1:
                last = e1
        if not recovered:
            raise last

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
            chunk = json.loads(raw)
        except Exception:
            continue
        # финальный чанк с include_usage несёт "usage" и ПУСТОЙ choices —
        # разбор токена ниже по коду тут упал бы на choices[0], перехватываем
        # раньше и просто логируем, что провайдер рассказал о промпте
        _usage = chunk.get("usage")
        if _usage:
            log.info("API %s usage: %s", model,
                     json.dumps(_usage, ensure_ascii=False))
        if not chunk.get("choices"):
            continue
        try:
            delta = chunk["choices"][0]["delta"]
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


# Реестр стрим-функций по бэкендам. Раньше жил локальной переменной внутри
# chat_stream, но ask_specific() обращался к нему снаружи — NameError при
# первом же «одалживании» способностей моделей оркестратором. Теперь модульный.
_FNS = {"ollama": _stream_ollama, "lmstudio": _stream_lmstudio,
        "locallm": _stream_locallm, "cloud": _stream_cloud}


def chat_stream(messages, on_fallback=None, on_tool=None, image=None,
                on_model=None, use_tools=True, should_stop=None):
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
    _fns = _FNS

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
            if (m["backend"] in ("ollama", "lmstudio", "locallm")
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
            tools = handspc.schemas() if use_tools else []
            # модели с нечитаемым форматом tool_calls (ловятся автоматически
            # ниже и запоминаются в конфиге) — инструменты не даём вообще
            if model in set(CFG.get("llm.tools_broken", [])):
                tools = []
            if on_model:
                try:
                    on_model(backend, model)  # кто реально отвечает (для UI)
                except Exception:
                    pass
            if idx > 0 and on_fallback:
                # last_err — причина, по которой ПРЕДЫДУЩИЙ кандидат не
                # ответил (2026-07-23: раньше терялась, и в чате/логе была
                # только «переключилась на X» без единого слова, ПОЧЕМУ —
                # напр. Kimi «включена», а по факту всегда фолбэчилась)
                try:
                    on_fallback(backend, model, last_err)
                except TypeError:
                    on_fallback(backend, model)   # старые колбэки без reason

            msgs = list(messages)
            seen_calls = set()      # от зацикливания на одном и том же вызове
            tools_t0 = time.monotonic()
            tools_budget = CFG.get("tools.max_tool_seconds", 150)
            for _round in range(CFG.get("tools.max_rounds", 3) + 1):
                if should_stop and should_stop():
                    log.info("Стоп во время инструментальных раундов — выхожу")
                    return
                # общий дедлайн на возню с инструментами: web_research по
                # 60с × перезапросы = минуты амока. Время вышло — забираем
                # инструменты и просим ответить по тому, что уже есть
                if tools and time.monotonic() - tools_t0 > tools_budget:
                    log.warning("Бюджет времени инструментов исчерпан "
                                "(%sс) — отвечаем словами", tools_budget)
                    tools = []
                    msgs = msgs + [{"role": "system", "content":
                        "(Служебный лог сторожа: ты застряла в цикле "
                        f"инструментов — {len(seen_calls)} вызовов за "
                        f"{int(time.monotonic() - tools_t0)} секунд, система "
                        "отобрала у тебя инструменты и привела тебя в "
                        "чувство. Начни ответ с КОРОТКОГО признания сбоя в "
                        "своём характере, с самоиронией, каждый раз своими "
                        "словами — в духе «кхм… кажется, меня слегка унесло. "
                        "Уже пришла в себя» — а потом ответь по уже "
                        "собранным результатам или честно скажи, что не "
                        "нашла. Без драмы и длинных извинений.)"}]
                calls, text_parts = [], []
                # картинку прикладываем только в первом раунде (это ход юзера)
                img = image if _round == 0 else None
                mark_busy(backend, model)   # начали реальный запрос — паспорт подождёт
                for ev in fn(msgs, model, temperature, tools, img):
                    if ev["type"] == "token":
                        text_parts.append(ev["text"])
                        yielded_any = True
                        mark_busy(backend, model)   # продлеваем на каждый токен
                        yield ev["text"]
                    else:
                        calls.append(ev["call"])
                if calls and tools:
                    # САМОЛЕЧЕНИЕ: если ВСЕ вызовы с именами, которых нет в
                    # наших схемах (модель эмитит собственный формат вроде
                    # «call:fs_list» — шаблон не дружит с function calling),
                    # то раунды сгорят впустую и ответ будет пустым. Выключаем
                    # этой модели инструменты НАВСЕГДА (конфиг) и делаем ещё
                    # раунд без них — ответит обычными словами. Работает для
                    # любой модели, отладка под каждую не нужна.
                    known = {s["function"]["name"] for s in tools}
                    if all(c["function"].get("name", "") not in known
                           for c in calls):
                        log.warning(
                            "Модель %s выдаёт нечитаемые tool_calls (%r) — "
                            "выключаю ей инструменты навсегда", model,
                            str(calls[0]["function"].get("name", ""))[:40])
                        CFG.set("llm.tools_broken", sorted(
                            set(CFG.get("llm.tools_broken", []) + [model])))
                        tools = []
                        msgs = msgs + [{"role": "system", "content":
                            "(Служебно: инструменты в этом чате недоступны — "
                            "отвечай обычными словами, БЕЗ tool_call.)"}]
                        continue
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
                    if should_stop and should_stop():
                        log.info("Стоп перед инструментом %s — обрываю", name)
                        return
                    # повтор того же вызова с теми же аргументами = амок
                    # («арфография» по кругу). Не выполняем, вразумляем.
                    sig = name + "|" + json.dumps(args, sort_keys=True,
                                                  ensure_ascii=False)[:200]
                    if sig in seen_calls:
                        result = ("(Служебный лог сторожа: это ПОВТОР того "
                                  "же вызова с теми же аргументами — признак "
                                  "зацикливания, инструмент НЕ выполнен. "
                                  "Останови поиск. Начни ответ с короткой "
                                  "самоироничной ремарки, что тебя занесло "
                                  "в цикл — своими словами, в своём "
                                  "характере — и ответь по имеющемуся или "
                                  "честно скажи, что не нашла.)")
                        if backend == "ollama":
                            msgs.append({"role": "tool", "tool_name": name,
                                         "name": name, "content": result})
                        else:
                            msgs.append({"role": "tool",
                                         "tool_call_id": c.get("id", f"call_{i}"),
                                         "content": result})
                        continue
                    seen_calls.add(sig)
                    if on_tool:
                        try:
                            on_tool(name, args)
                        except Exception:
                            pass
                    result = handspc.call(name, args)
                    # ОБРЕЗКА результата (2026-07-23): web_search/fetch_page
                    # возвращают целые страницы (десятки КБ) — и это дважды
                    # душило Сайку: раздувало промпт за окно модели
                    # («exceed context window») и оставалось в истории на
                    # следующие ходы. Модели хватает выжимки; лимит в
                    # config (tools.max_result_chars).
                    _lim = int(CFG.get("tools.max_result_chars", 2500))
                    if result and len(result) > _lim:
                        result = (result[:_lim]
                                  + f"\n…[обрезано, всего {len(result)} симв.]")
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


def ask_specific(backend: str, model: str, messages, image=None,
                 max_len=6000) -> str:
    """Прямой вопрос КОНКРЕТНОЙ модели, минуя выбор из конфига.
    Оркестратор одалживает у моделей их способности: например, зрение
    vision-модели для OCR картинки, когда за рулём слепая болтушка."""
    fn = _FNS.get(backend, _stream_lmstudio)
    parts = []
    for ev in fn(messages, model, 0.2, None, image):
        if ev["type"] == "token":
            parts.append(ev["text"])
            if sum(len(p) for p in parts) > max_len:
                break
    text = "".join(parts)[:max_len]
    if image and text.strip():
        try:  # успешно посмотрела на картинку — опыт: зрение есть
            from server import capabilities as _caps
            _caps.note(model, "vision", True)
        except Exception:
            pass
    return text
