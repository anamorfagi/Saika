"""LLM-менеджер: Ollama + LM Studio с переключателем и автофоллбэком.

Оба бэкенда опрашиваются на лету — UI показывает объединённый список моделей.
Если выбранный бэкенд упал, менеджер сам пробует второй и сообщает об этом.
"""
import json
import logging
import re
import time

import requests

from anamorf.config import CFG, ROOT, DATA_ROOT

log = logging.getLogger("saika.llm")


class LLMError(Exception):
    pass


def _ollama_url():
    return CFG.get("llm.ollama_url", "http://127.0.0.1:11434").rstrip("/")


def _lmstudio_url():
    return CFG.get("llm.lmstudio_url", "http://127.0.0.1:1234").rstrip("/")


def _llamacpp_url():
    """Свой llama-server (server/llm/llamacpp.py). Адрес — настройкой, чтобы
    движок можно было унести на другую машину, не трогая код."""
    u = CFG.get("llamacpp.url", "")
    if u:
        return u.rstrip("/")
    from anamorf.llm import llamacpp
    return llamacpp.base_url()


def _locallm_url():
    """Свой воркер LocalLM (workers/locallm_worker.py) — OpenAI-совместимый,
    как LM Studio, только модель живёт прямо в проекте (без Ollama/LM Studio)."""
    from anamorf.llm import locallm
    return locallm.base_url()


# ---------------------- облачные (онлайн) модели по API-ключу ----------------
def _secrets() -> dict:
    """secrets.json (в .gitignore) — тут храним API-ключ облака, чтобы он не
    улетел в git при пуше."""
    # ДВА МЕСТА, А НЕ ОДНО (2026-08-22, живой вечер: «не задан API-ключ
    # облачной модели» при том, что ключ у владельца есть — он лежал в
    # `secrets.json` основного проекта, а в сборку не поехал вовсе).
    # ROOT в сборке — это `app\`, папка КОДА: её сносит любое обновление.
    # Ключи там жить не могут по определению, поэтому смотрим и рядом со
    # сборкой (DATA_ROOT), где живут данные, модели и настройки.
    for p in (ROOT / "secrets.json", DATA_ROOT / "secrets.json"):
        try:
            if p.exists():
                d = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(d, dict) and d:
                    return d
        except Exception:
            continue
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
            "model": c.get("model", ""), "key": key, "provider": prov}


def _host(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return (urlparse(url or "").netloc or "").lower()
    except Exception:
        return ""


def provider_for_url(url: str) -> str:
    """Чей это адрес по каталогу бесплатных тиров. Пусто — незнакомый.

    Нужно потому, что интерфейс сохраняет провайдера «custom», когда в
    каталоге у записи не было готового base_url: человек вписал адрес
    руками — и ключ уехал в слот «своё». Живой случай 2026-08-13 с
    Cloudflare: разговаривать можно, а автоподключение остальных моделей
    того же вендора мимо, потому что по имени «custom» каталог ничего не
    находит. Узнаём вендора по хосту — он не врёт."""
    h = _host(url)
    if not h:
        return ""
    try:
        from anamorf.llm import free_tiers
        for e in free_tiers.CATALOG:
            if _host(e.get("base_url", "")) == h:
                return e.get("id", "")
    except Exception:
        pass
    return ""


def cloud_key_for(provider: str) -> str:
    """Ключ конкретного провайдера — без переключения активного слота.
    Нужен лестнице мозгов (anamorf/llm/brains.py): она должна знать, до кого
    из настроенных облаков реально можно дозвониться, ДО попытки."""
    s = _secrets().get("llm", {}) or {}
    ck = s.get("cloud_keys", {}) or {}
    if provider and ck.get(provider):
        return ck[provider]
    c = CFG.get("llm.cloud", {}) or {}
    if provider and provider == c.get("provider", ""):
        return s.get("cloud_api_key", "") or c.get("api_key", "")
    # КЛЮЧ МОГ ЛЕЧЬ ПОД ЧУЖИМ ИМЕНЕМ (см. provider_for_url): ищем по хосту.
    # Иначе ключ есть, работает, а система про него не знает — худший вид
    # поломки, потому что снаружи всё выглядит исправным.
    if provider:
        for e in cloud_saved():
            slot = e.get("provider", "")
            if not slot or not ck.get(slot):
                continue
            if provider_for_url(e.get("base_url", "")) == provider:
                return ck[slot]
    return ""


def cloud_for(model: str) -> dict:
    """Адрес и ключ ДЛЯ КОНКРЕТНОЙ облачной модели (2026-08-13).

    Раньше _stream_cloud всегда брал _cloud() — единственный активный слот.
    Поэтому «позвать модель посильнее» работало только если она случайно
    оказывалась активной: попытка сходить к другому провайдеру уходила по
    чужому base_url с чужим ключом и падала на 401/404. Теперь адрес и ключ
    ищутся ПО ИМЕНИ МОДЕЛИ среди всех настроенных — лестница может звать
    любого, не трогая настройки владельца."""
    want = (model or "").strip()
    c = _cloud()
    if want and want != c.get("model", ""):
        for e in cloud_saved():
            if e.get("model") != want:
                continue
            prov = e.get("provider", "")
            key = cloud_key_for(prov)
            if key:
                return {"enabled": True, "provider": prov,
                        "base_url": (e.get("base_url") or "").rstrip("/"),
                        "model": want, "key": key}
        # МОДЕЛЬ ТОГО ЖЕ ПРОВАЙДЕРА, НЕ ЗАПИСАННАЯ В СЛОТЫ (2026-08-15):
        # у Cloudflare на одном аккаунте живёт весь каталог — в т.ч.
        # зрячая llama-3.2-11b-vision. Раньше позвать её было нельзя,
        # пока владелец не заведёт слот руками. Любое имя @cf/… обслужит
        # уже настроенный Cloudflare с его же адресом и ключом.
        if want.startswith("@cf/"):
            for e in cloud_saved():
                if e.get("provider") == "cloudflare":
                    key = cloud_key_for("cloudflare")
                    if key:
                        return {"enabled": True, "provider": "cloudflare",
                                "base_url": (e.get("base_url") or "").rstrip("/"),
                                "model": want, "key": key}
    return c


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

# ── ЕДИНАЯ ТОЧКА ДЛЯ КЛЮЧЕЙ (2026-08-25) ──
# Ключи задаются клиентом через интерфейс, а не приезжают в сборке. Здесь —
# бэкенд для будущей панели «Ключи»: что вообще можно задать, что уже задано
# (без значений — их наружу не отдаём), куда писать. Всё пишется в
# secrets.json РЯДОМ со сборкой (DATA_ROOT), а не в app\, который сносит
# обновление; на машине автора это тот же secrets.json проекта.
KEY_SLOTS = [
    {"id": "openrouter", "title": "OpenRouter", "where": "llm.cloud_keys",
     "hint": "sk-or-... — один ключ, много моделей"},
    {"id": "mistral",    "title": "Mistral",    "where": "llm.cloud_keys",
     "hint": "ключ из console.mistral.ai"},
    {"id": "gigachat",   "title": "GigaChat",   "where": "llm.cloud_keys",
     "hint": "Authorization key из кабинета Сбера"},
    {"id": "kimi",       "title": "Kimi (Moonshot)", "where": "llm.cloud_keys",
     "hint": "ключ platform.moonshot"},
    {"id": "cloudflare", "title": "Cloudflare Workers AI",
     "where": "llm.cloud_keys", "hint": "API-токен"},
    {"id": "custom",     "title": "Свой OpenAI-совместимый",
     "where": "llm.cloud_keys", "hint": "любой ключ к своему base_url"},
    {"id": "telegram",   "title": "Telegram-бот", "where": "messengers",
     "hint": "токен от @BotFather"},
    {"id": "vk",         "title": "VK-бот", "where": "messengers",
     "hint": "ключ группы VK"},
    {"id": "github",     "title": "GitHub", "where": "github",
     "hint": "personal access token (для обновлений)"},
]


def _secrets_path():
    """Куда писать secrets.json: рядом со сборкой (DATA_ROOT), а на машине
    автора — в корне проекта. Читаем-то из обоих (см. _secrets), но пишем в
    одно предсказуемое место, чтобы ключ не потерялся при обновлении app\\."""
    if (ROOT / "secrets.json").exists():
        return ROOT / "secrets.json"
    return DATA_ROOT / "secrets.json"


def keys_status() -> dict:
    """Какие ключи заданы — БЕЗ значений (для панели «Ключи»)."""
    sec = _secrets()
    llm_ck = (sec.get("llm", {}) or {}).get("cloud_keys", {}) or {}
    msg = sec.get("messengers", {}) or {}
    gh = sec.get("github", {}) or {}
    out = []
    for slot in KEY_SLOTS:
        i = slot["id"]
        if slot["where"] == "llm.cloud_keys":
            has = bool(llm_ck.get(i))
        elif slot["where"] == "messengers":
            has = bool(((msg.get(i) or {}) or {}).get("token"))
        elif slot["where"] == "github":
            has = bool(gh.get("token"))
        else:
            has = False
        out.append({**slot, "set": has})
    return {"slots": out}


def set_key(slot_id: str, value: str) -> dict:
    """Задать/очистить один ключ. Пустое значение — стереть слот."""
    slots = {s["id"]: s for s in KEY_SLOTS}
    slot = slots.get(slot_id)
    if not slot:
        return {"error": "неизвестный слот ключа: %s" % slot_id}
    path = _secrets_path()
    data = _secrets()
    val = (value or "").strip()
    if slot["where"] == "llm.cloud_keys":
        data.setdefault("llm", {}).setdefault("cloud_keys", {})[slot_id] = val
    elif slot["where"] == "messengers":
        m = data.setdefault("messengers", {}).setdefault(slot_id, {})
        m["token"] = val
    elif slot["where"] == "github":
        data.setdefault("github", {})["token"] = val
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except Exception as e:
        return {"error": "не смогла записать ключ: %s" % e}
    return {"ok": True, "set": bool(val), "slot": slot_id}


# СПИСОК МОДЕЛЕЙ — В КЭШ (2026-07-27). list_models() опрашивает по сети ВСЕ
# бэкенды: Ollama, два эндпоинта LM Studio, свой воркер. На каждую реплику
# он зовётся дважды (сам по себе и изнутри _pick_model), плюс loaded_models()
# — это под десяток localhost-запросов ПЕРЕД тем, как уйти в модель, и все
# они лежат внутри замеряемого «prefill». Пока все бэкенды подняты, это
# миллисекунды; стоит одному из них быть закрытым, но с висящим портом (или
# просто задуматься) — и каждый такой запрос ждёт свой таймаут.
# Список моделей меняется редко: держим его несколько секунд.
_MODELS_CACHE: dict = {"t": 0.0, "val": None}

# ПАМЯТЬ О МЁРТВЫХ ПОРТАХ (2026-07-28). Симметричные грабли дважды за день:
# утром неустановленный LocalLM стоил 2с на каждую реплику, вечером владелец
# закрыл LM Studio (она больше не нужна — мозги на своём движке), и опросы
# ЕЁ мёртвого порта стали жечь по 3с таймаута на каждый из двух эндпоинтов.
# Файрвол Windows на закрытом порту молча ест SYN — «отказа» не приходит,
# запрос честно ждёт весь таймаут. Правило: порт не ответил — не трогаем его
# N секунд, потом пробуем снова (вернувшаяся программа обнаружится за минуту).
_DOWN: dict = {}


def _down(key: str) -> bool:
    """Молчит ли бэкенд. Плюс ЖЁСТКОЕ ОТКЛЮЧЕНИЕ LM STUDIO (2026-08-22,
    владелец: «нах лм студио запускает такую же модель синхронно?»).

    LM Studio поднимает модель в память по ЛЮБОМУ запросу к себе — даже по
    безобидному «покажи список». Сайка опрашивает его регулярно, чтобы
    знать, что доступно, и этим сама заставляла его держать вторую копию
    той же gemma. На карте в 16 ГБ это ровно та половина памяти, которой
    потом не хватало клон-голосу.

    Выключатель llm.use_lmstudio закрывает ВСЕ опросы разом: здесь
    единственная точка, через которую они проходят.

    УМОЛЧАНИЕ ПЕРЕВЁРНУТО (2026-08-23, владелец: «найди, из-за чего наша
    модель на C++ запускалась вместе с моделью из ЛМ с похожим названием»).
    Выключатель был, но по умолчанию стоял ВКЛ, а строчка «выключить» так
    и не доехала до конфига — починка, которая требует правки файла руками,
    это не починка. Теперь правило само собой разумеющееся: когда мозги
    живут в НАШЕМ llama-server (backend=llamacpp), опрашивать LM Studio
    незачем вовсе — GGUF-файл из его каталога мы читаем напрямую, без его
    участия, а каждый опрос заставлял его держать в видеопамяти ВТОРУЮ
    копию модели с похожим именем. Кто реально работает через LM Studio
    (backend=lmstudio) — у того опросы живут как жили. Явно заданный
    llm.use_lmstudio в конфиге главнее любых умолчаний."""
    if key == "lmstudio":
        use = CFG.get("llm.use_lmstudio", None)
        if use is None:
            use = str(CFG.get("llm.backend", "")) == "lmstudio"
        if not use:
            return True
    return time.time() < _DOWN.get(key, 0)


def _mark_down(key: str):
    _DOWN[key] = time.time() + float(CFG.get("llm.down_retry_s", 60))


def _mark_up(key: str):
    _DOWN.pop(key, None)


def invalidate_models_cache():
    _MODELS_CACHE["val"] = None


def list_models() -> list[dict]:
    """Объединённый список моделей обоих бэкендов: [{backend, name, size}].
    size (байты) нужен UI для индикатора нагрузки на систему."""
    ttl = float(CFG.get("llm.models_cache_s", 5) or 0)
    if ttl and _MODELS_CACHE["val"] is not None \
            and time.time() - _MODELS_CACHE["t"] < ttl:
        return list(_MODELS_CACHE["val"])
    out = []
    # эвристика зрения по имени для Ollama (там нет поля capabilities)
    vhint = ("llava", "vision", "gemma3", "gemma-3", "gemma4", "gemma-4",
             "minicpm-v", "qwen2-vl", "qwen2.5-vl", "qwen3-vl", "llama3.2-vision",
             "moondream", "bakllava", "pixtral", "mllama", "-vl")
    rhint = ("r1", "qwq", "reason", "thinking", "deepseek-r")
    try:
        if _down("ollama"):
            raise ConnectionError("порт недавно молчал")
        r = requests.get(_ollama_url() + "/api/tags", timeout=3)
        _mark_up("ollama")
        for m in r.json().get("models", []):
            nm = m["name"]
            low = nm.lower()
            out.append({"backend": "ollama", "name": nm, "size": m.get("size"),
                        "caps": {"vision": any(h in low for h in vhint),
                                 "tools": False,
                                 "reasoning": any(h in low for h in rhint)}})
    except ConnectionError:
        pass
    except Exception as e:
        _mark_down("ollama")
        log.debug("ollama offline: %s", e)
    # LM Studio: сперва REST API v1 — там есть size_bytes (для индикатора веса),
    # если версия старая и его нет, откатываемся на OpenAI-совместимый /v1/models
    lm_ok = _down("lmstudio")   # молчал недавно — не пробуем ни один эндпоинт
    try:
        if lm_ok:
            raise ConnectionError("порт недавно молчал")
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
        _mark_up("lmstudio")
    except ConnectionError:
        pass
    except Exception as e:
        log.debug("lmstudio REST v1 unavailable: %s", e)
    if not lm_ok:
        try:
            r = requests.get(_lmstudio_url() + "/v1/models", timeout=3)
            _mark_up("lmstudio")
            for m in r.json().get("data", []):
                out.append({"backend": "lmstudio", "name": m["id"],
                            "size": None})
        except Exception as e:
            _mark_down("lmstudio")
            log.debug("lmstudio offline: %s", e)
    # своя LocalLM: показываем, если окружение установлено ИЛИ она выбрана
    # основным бэкендом (тогда спавнер сам поставит окружение при первом
    # запросе). Воркер может быть ещё не запущен — это нормально.
    try:
        from anamorf.llm import locallm
        if locallm.installed() or CFG.get("llm.backend") == "locallm":
            out.append({"backend": "locallm", "name": locallm.model_name(),
                        "size": None,
                        "caps": {"vision": False, "tools": False,
                                 "reasoning": True}})
    except Exception as e:
        log.debug("locallm unavailable: %s", e)
    # свой llama-server: показываем, если бинарь скачан ИЛИ он выбран
    # основным бэкендом (тогда спавнер поставит его при первом запросе).
    # МОДЕЛИ — С ДИСКА, А НЕ ЧЕРЕЗ LM STUDIO (2026-08-23, владелец: «модели
    # от ЛМ не отображаются, порт при этом открыт»). Порт и правда открыт —
    # но каждый вопрос к нему заставлял LM Studio держать в видеопамяти
    # СВОЮ копию модели рядом с нашей (см. _down). А спрашивать его и не
    # за чем: скачанные им GGUF лежат обычными файлами, наш llama-server
    # их и так запускает напрямую. Читаем каталоги — файлам от чтения
    # ничего не делается, и список полон без единого запроса к ЛМ.
    try:
        from anamorf.llm import llamacpp
        if llamacpp.installed() or CFG.get("llm.backend") == "llamacpp":
            cur = (CFG.get("llamacpp.model")
                   or CFG.get("llm.model", "local"))
            seen_gguf = set()
            try:
                from anamorf.config import resolve as _res
                roots = [_res("models/gguf"), _res("models/llm")]
            except Exception:
                roots = []
            roots += llamacpp._lmstudio_roots()
            for root in roots:
                try:
                    from pathlib import Path as _P
                    for f in _P(root).rglob("*.gguf"):
                        nm = f.stem
                        low = nm.lower()
                        if "mmproj" in low or "vision" in low:
                            continue          # проектор — не модель
                        import re as _re
                        mpart = _re.search(r"-(\d{5})-of-\d{5}$", nm)
                        if mpart and mpart.group(1) != "00001":
                            continue          # куски мультичастевого — один раз
                        if low in seen_gguf:
                            continue
                        seen_gguf.add(low)
                        try:
                            sz = f.stat().st_size
                        except OSError:
                            sz = None
                        out.append({"backend": "llamacpp", "name": nm,
                                    "size": sz,
                                    "current": low in str(cur).lower()
                                    or str(cur).lower() in low,
                                    "caps": {"vision": any(h in low
                                                           for h in vhint),
                                             "tools": True,
                                             "reasoning": any(h in low
                                                              for h in rhint)}})
                except Exception as e:
                    log.debug("скан GGUF в %s: %s", root, e)
            # выбранная модель обязана быть в списке, даже если файл не нашли
            if not any(o["backend"] == "llamacpp"
                       and str(cur).lower() in o["name"].lower()
                       for o in out):
                out.append({"backend": "llamacpp", "name": cur,
                            "size": None, "current": True,
                            "caps": {"vision": False, "tools": True,
                                     "reasoning": True}})
    except Exception as e:
        log.debug("llamacpp unavailable: %s", e)
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
    _MODELS_CACHE.update(t=time.time(), val=list(out))
    return out


# кэш как у list_models и по той же причине (2026-07-27): loaded_models()
# зовётся перед КАЖДОЙ репликой, а внутри — сетевые опросы всех бэкендов.
# Замер поймал ровно её: «загруженные 2000мс» на каждый ответ — это проба
# /health НЕУСТАНОВЛЕННОГО LocalLM выедала свой таймаут 2с целиком (порт
# мёртв, а файрвол Windows молча ест SYN вместо мгновенного отказа).
_LOADED_CACHE: dict = {"t": 0.0, "val": None}


def loaded_models() -> list[str]:
    """Модели, реально сидящие в памяти: Ollama — /api/ps,
    LM Studio — /api/v0/models (поле state)."""
    ttl = float(CFG.get("llm.models_cache_s", 5) or 0)
    if ttl and _LOADED_CACHE["val"] is not None \
            and time.time() - _LOADED_CACHE["t"] < ttl:
        return list(_LOADED_CACHE["val"])
    out = []
    try:
        if not _down("ollama"):
            r = requests.get(_ollama_url() + "/api/ps", timeout=3)
            for m in r.json().get("models", []):
                name = m.get("name") or m.get("model")
                if name:
                    out.append(name)
    except Exception:
        _mark_down("ollama")
    try:
        if not _down("lmstudio"):
            r = requests.get(_lmstudio_url() + "/api/v0/models", timeout=3)
            for m in r.json().get("data", []):
                if m.get("state") == "loaded" and m.get("id"):
                    out.append(m["id"])
    except Exception:
        _mark_down("lmstudio")
    try:
        # мёртвый порт не опрашиваем вовсе: нет окружения — нечего спрашивать
        from anamorf.llm import locallm
        if locallm.installed() and not _down("locallm"):
            r = requests.get(_locallm_url() + "/health", timeout=2)
            if r.ok and r.json().get("model_loaded"):
                out.append(locallm.model_name())
    except Exception:
        # 2026-08-13: одного кэша (TTL 5с) было мало — «загруженные 2032мс»
        # возвращались КАЖДЫЕ 5 секунд. У ollama/lmstudio предохранитель был,
        # у locallm его забыли: воркер установлен, но не запущен — обычное
        # состояние, а платили за него полным таймаутом перед каждой репликой.
        _mark_down("locallm")
    try:
        from anamorf.llm import llamacpp
        if llamacpp.installed():
            r = requests.get(_llamacpp_url() + "/v1/models", timeout=2)
            if r.ok:
                # ЧТО РЕАЛЬНО НА ПОРТУ, А НЕ ЧТО В КОНФИГЕ (2026-08-23,
                # живой обман: «в памяти» горело у gemma, отвечала подпись
                # huihui, а правды не знал никто). Сервер сам говорит,
                # какой файл он крутит, — ему и верим.
                nm = ""
                try:
                    data = (r.json() or {}).get("data") or []
                    if data:
                        from pathlib import Path as _P
                        nm = _P(str(data[0].get("id") or "")).stem
                except Exception:
                    nm = ""
                # ИМЯ — ТО, ЧТО ВИДИТ ЧЕЛОВЕК В СПИСКЕ (2026-08-23,
                # значок «в памяти» пропал вовсе: сервер называет ФАЙЛ,
                # строка в меню — каталожное имя, и они не совпали буква в
                # букву). Правда остаётся серверной: если файл на порту —
                # это та модель, что выбрана, отдаём её ИМЯ ИЗ СПИСКА,
                # чтобы значок нашёл свою строку. Чужой файл — отдаём как
                # есть, пусть расхождение будет видно.
                def _nrm(x):
                    return re.sub(r"[^a-z0-9]+", "", str(x).lower())
                for cand in (CFG.get("llm.model", ""),
                             CFG.get("llamacpp.model", "")):
                    if cand and nm and (_nrm(nm) in _nrm(cand)
                                        or _nrm(cand) in _nrm(nm)):
                        nm = cand
                        break
                out.append(nm or CFG.get("llamacpp.model")
                           or CFG.get("llm.model", "local"))
    except Exception:
        pass
    _LOADED_CACHE.update(t=time.time(), val=list(out))
    return out


# СКОЛЬКО КОНТЕКСТА РЕАЛЬНО ЗАГРУЖЕНО (2026-07-27).
# Замер вскрыл главное: у Сайки промпт ~10к токенов, а модель в LM Studio
# была загружена с окном 4096 — и LM Studio МОЛЧА резала начало промпта
# (usage стабильно показывал prompt_tokens ≈ 4049 при промпте вдвое больше).
# Отсюда сразу две беды: (1) Сайка теряла системный промпт и половину
# истории, не подавая виду; (2) KV-кэш не мог сработать в принципе — окно
# каждый ход сдвигается, префикс не совпадает, и каждая фраза стоила полного
# prefill. Гадать об этом нельзя — спрашиваем у самой LM Studio.
# Ответ кэшируем: это горячий путь, лишний HTTP на каждую фразу не нужен.
_CTX_CACHE: dict = {"t": 0.0, "val": {}}
_CTX_TTL_S = 120


def loaded_context_tokens(backend: str, model: str) -> int:
    """Окно контекста загруженной модели в токенах. 0 — не удалось узнать."""
    if backend == "llamacpp":
        # свой сервер отвечает честно и сразу: /props отдаёт настройки, с
        # которыми модель РЕАЛЬНО поднята, а не то, что мы просили в конфиге
        try:
            r = requests.get(_llamacpp_url() + "/props", timeout=3)
            g = (r.json() or {}).get("default_generation_settings") or {}
            return int(g.get("n_ctx") or 0)
        except Exception:
            return int((CFG.get("llamacpp", {}) or {}).get("n_ctx", 0) or 0)
    if backend != "lmstudio":
        return 0                       # у Ollama окно задаётся нами в options
    now = time.time()
    if now - _CTX_CACHE["t"] > _CTX_TTL_S:
        vals = {}
        try:
            if _down("lmstudio"):
                raise ConnectionError("порт недавно молчал")
            r = requests.get(_lmstudio_url() + "/api/v0/models", timeout=3)
            for m in r.json().get("data", []):
                if not m.get("id"):
                    continue
                # loaded_context_length — то, с чем модель РЕАЛЬНО поднята
                # (ползунок Context Length в LM Studio); max_context_length —
                # потолок модели. Нас интересует первое.
                n = (m.get("loaded_context_length")
                     or m.get("context_length")
                     or m.get("max_context_length") or 0)
                if n:
                    vals[m["id"]] = int(n)
        except Exception as e:
            log.debug("окно контекста LM Studio не спросилось: %s", e)
        _CTX_CACHE["val"] = vals or _CTX_CACHE["val"]
        _CTX_CACHE["t"] = now
    return int(_CTX_CACHE["val"].get(model, 0))


def _loaded_with_backend() -> list[tuple]:
    """Список реально загруженных локальных моделей с бэкендом: [(backend,name)]."""
    out = []
    try:
        if not _down("ollama"):
            r = requests.get(_ollama_url() + "/api/ps", timeout=3)
            for m in r.json().get("models", []):
                n = m.get("name") or m.get("model")
                if n:
                    out.append(("ollama", n))
    except Exception:
        _mark_down("ollama")
    try:
        if not _down("lmstudio"):
            r = requests.get(_lmstudio_url() + "/api/v0/models", timeout=3)
            for m in r.json().get("data", []):
                if m.get("state") == "loaded" and m.get("id"):
                    out.append(("lmstudio", m["id"]))
    except Exception:
        _mark_down("lmstudio")
    try:
        # те же два предохранителя, что и в loaded_models (2026-08-13):
        # здесь не было даже проверки installed(), хотя функция зовётся из
        # unload_others — то есть при каждом переключении модели
        from anamorf.llm import locallm
        if locallm.installed() and not _down("locallm"):
            r = requests.get(_locallm_url() + "/health", timeout=2)
            if r.ok and r.json().get("model_loaded"):
                out.append(("locallm", locallm.model_name()))
    except Exception:
        _mark_down("locallm")
    # свой llama-server (2026-07-27): без этой записи keep_only_one не видел
    # его в списке «кто в памяти» — при переключении на другую модель наш
    # движок оставался жить со своей копией, и в VRAM висели две больших LLM
    # одновременно (ровно то, от чего keep_only_one и должен защищать)
    try:
        from anamorf.llm import llamacpp
        if llamacpp.installed():
            r = requests.get(_llamacpp_url() + "/v1/models", timeout=2)
            if r.ok:
                out.append(("llamacpp", CFG.get("llamacpp.model")
                            or CFG.get("llm.model", "local")))
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


def drop_all_local(why: str = "") -> list:
    """Выгрузить из видеопамяти все локальные модели.

    Ручной инструмент, а не автоматика. Когда человек выключает мозги
    посреди работы, модель СПЕЦИАЛЬНО остаётся в памяти: он может включить
    их обратно тем же кликом, и ждать прогрева заново незачем. А вот при
    следующем запуске она уже не грузится — это делает замок в warmup().
    Эта функция нужна, когда память надо освободить прямо сейчас.
    """
    ушли = []
    try:
        for m in (loaded_models() or []):
            for bk in ("llamacpp", "locallm", "ollama"):
                try:
                    if unload_model(bk, m):
                        ушли.append("%s/%s" % (bk, m))
                except Exception:
                    pass
        invalidate_models_cache(); _LOADED_CACHE["val"] = None
    except Exception as e:
        log.info("выгрузка моделей не удалась: %s", e)
    if ушли:
        log.warning("Мозги выключены%s — выгрузила из видеопамяти: %s",
                    (" (" + why + ")") if why else "", ", ".join(ушли))
    return ушли


def switch_model(backend: str, model: str) -> dict:
    """Переключение LLM с защитой памяти: по умолчанию держим в памяти только
    ОДНУ модель (llm.keep_only_one) — сперва выгружаем прочие, потом греем
    новую. Нужны две сразу (маленькая+большая связка) — выключи keep_only_one.

    Возвращает {"ok": bool, "unload_failed": [(backend, model), …]} — раньше
    отдавался голый bool, и молчаливый провал выгрузки старой модели (см.
    unload_others) никак не долетал до UI/чата."""
    unload_failed = []
    invalidate_models_cache()   # состав загруженного сейчас изменится
    _LOADED_CACHE["val"] = None
    # ЗАПОМИНАЕМ, КЕМ РАБОТАЛИ (2026-08-14). Не рейтинг — привычка: при
    # равном уме первым берётся тот, с кем человек работал последним.
    try:
        from anamorf.llm import brains as _br_recent
        _br_recent.note_used(backend, model)
    except Exception as _e:
        log.debug("память последних мозгов: %s", _e)
    if backend != "cloud" and CFG.get("llm.keep_only_one", True):
        unload_failed = unload_others(backend, model)
    ok = warmup(backend, model)
    return {"ok": ok, "unload_failed": unload_failed}


def keep_cloud_warm():
    """«Облако запущено одновременно» (2026-07-27). Запущенного процесса у
    облака не бывает — но бывает холодный вход: у GigaChat это OAuth-токен
    (живёт 30 минут), и без прогрева ПЕРВАЯ настоящая задача платила бы
    лишние секунды за его получение. Держим токен вечно тёплым: обновляем
    в фоне до истечения. Остальным провайдерам греть нечего — вход по
    статичному ключу, а постоянная HTTP-сессия и так живёт.
    Зовётся фоновым потоком из автопуска, только при включённом
    маршрутизаторе — без него облако может вообще не использоваться."""
    while True:
        try:
            if CFG.get("llm.router.enabled", False):
                c = _cloud()
                if c["enabled"] and c["key"] and _is_gigachat(c["base_url"]):
                    _gigachat_token(c["key"])
        except Exception as e:
            log.debug("прогрев облака: %s", e)
        time.sleep(20 * 60)          # токен живёт 30 мин — обновляем за 10 до


def prewarm_next(messages: list, reply_text: str):
    """ПРОГРЕВ СЛЕДУЮЩЕГО ХОДА (2026-07-27, гонка за <0.1с «обдумывания»).

    Сразу после того как Сайка договорила, отправляем движку ВЕСЬ диалог
    вместе с её свежим ответом и max_tokens=1. Пока человек читает и думает,
    что сказать, сервер уже уложил в KV-кэш всё, включая последний обмен
    репликами. Следующая фраза человека доплачивает prefill только за себя
    и блок динамики — это десятки миллисекунд, а не сотни.

    Это того же рода приём, что prefetch в браузерах: работа делается в
    паузе, которая всё равно случится. Стоимость — один короткий запрос к локальному
    серверу в фоне; облаку такое не шлём (там это деньги)."""
    backend = CFG.get("llm.backend", "")
    if backend not in ("llamacpp", "lmstudio", "locallm"):
        return
    if not CFG.get("llm.prewarm_next", True):
        return
    try:
        url = {"llamacpp": _llamacpp_url, "lmstudio": _lmstudio_url,
               "locallm": _locallm_url}[backend]()
        model = CFG.get("llm.model", "")
        body = {"model": model,
                "messages": list(messages) + [
                    {"role": "assistant", "content": reply_text or "…"}],
                "max_tokens": 1, "stream": False, "cache_prompt": True,
                "chat_template_kwargs": {"enable_thinking": False}}
        # ТЕ ЖЕ ИНСТРУМЕНТЫ, ЧТО И В БОЮ (2026-08-13). Без этого прогрев не
        # грел, а ВЫТИРАЛ: боевой запрос уходит с tools (51 схема, ~21к
        # символов), шаблон рендерит их в самое начало промпта, а прогрев
        # слал те же сообщения БЕЗ tools — префиксы расходились почти сразу.
        # В llamacpp_server.log это читалось прямо: два промпта (12.2к и
        # 6.8к токенов) ходили по кругу в единственном слоте (--parallel 1),
        # «selected slot by LCP similarity» скакал 0.58 -> 0.325 -> 0.58, а
        # cached_tokens замер на 3959 — общей голове двух разных промптов.
        # Цена ошибки: 8200 токенов полного prefill КАЖДЫЙ ход, ~1.6с.
        try:
            from anamorf.llm import tools as handspc
            # ТОТ ЖЕ ОТБОР, ЧТО И В БОЮ: прогрев с другим набором схем
            # не греет, а вытирает кэш — на этом уже горели (см. ниже)
            _tools = handspc.schemas_for(_last_user_text(messages))
            # модели с нечитаемым tool_calls инструментов не получают и в
            # бою (см. chat_stream) — прогрев обязан повторять это решение,
            # иначе он снова разойдётся с боевым промптом
            if model in set(CFG.get("llm.tools_broken", [])):
                _tools = []
            if _tools:
                body["tools"] = _tools
        except Exception as e:
            log.debug("прогрев без инструментов: %s", e)
        _HTTP.post(url + "/v1/chat/completions", json=body, timeout=120)
        log.debug("KV-кэш прогрет следующим ходом")
    except Exception as e:
        log.debug("прогрев следующего хода пропущен: %s", e)


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
        elif backend == "llamacpp":
            url = _llamacpp_url()
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
    # МОЗГИ ВЫКЛЮЧЕНЫ — В ПАМЯТЬ НИЧЕГО НЕ ГРУЗИМ (01.09.2026).
    #
    # Владелец: «уеби этому коду, чтобы не загружал модель… когда включён
    # режим без мозгов». Флаг llm.off проверялся при подъёме (bringup), но
    # не здесь — а сюда ведут ещё несколько дорог (переключение модели,
    # паспорт, тумблеры). Достаточно было одной из них, чтобы модель встала
    # в видеопамять при выключенных мозгах и висела там мёртвым грузом.
    # Сегодня это стоило трёх падений системы: видеопамять кончилась,
    # драйвер не смог перезапуститься, VIDEO_TDR_ERROR.
    # Здесь — единственное место, где модель СОЗНАТЕЛЬНО грузят в память,
    # значит и запрет ставим здесь: одна дверь, один замок.
    if CFG.get("llm.off", False):
        log.info("Прогрев %s/%s отменён: мозги выключены", backend, model)
        return False
    # ОДИН ЛОКАЛЬНЫЙ ДВИЖОК НА ВИДЕОКАРТУ (2026-08-20). Единственное место,
    # где модель СОЗНАТЕЛЬНО грузят в память, — значит, и проверять здесь.
    # Разбор случая и правило — anamorf/llm/one_local.py.
    from anamorf.llm import one_local
    _no = one_local.refuse(backend)
    if _no:
        log.info("Прогрев %s/%s отменён: %s", backend, model, _no["error"])
        return False
    try:
        if backend == "ollama":
            requests.post(_ollama_url() + "/api/generate",
                          json={"model": model, "prompt": "",
                                "keep_alive": CFG.get("llm.keep_alive", "30m")},
                          timeout=900)
        elif backend == "llamacpp":
            from anamorf.llm import llamacpp
            st = llamacpp.ensure_running()
            if st.get("error"):
                raise LLMError(st["error"])
            if st.get("installing"):
                return False           # ещё качается — грелка не при чём
            requests.post(_llamacpp_url() + "/v1/chat/completions",
                          json={"model": model, "max_tokens": 1,
                                "messages": [{"role": "user",
                                              "content": "hi"}]},
                          timeout=900)
        elif backend == "locallm":
            from anamorf.llm import locallm
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
        # ЖИВОЙ ОТВЕТ = ЗДОРОВА. Прогрев только что реально получил ответ
        # от модели — держать её после этого в карантине бессмысленно и
        # жестоко: живой вечер 23.08 — huihui уже прогрета и крутится, а
        # разговор ещё десять минут вёл GigaChat, потому что карантин от
        # старой ошибки не истёк. Выздоровление по факту, не по таймеру.
        try:
            from anamorf.llm import brains as _brv
            _brv.revive(backend, model)
        except Exception:
            pass
        try:
            from anamorf.llm import passport
            passport.ensure_async(backend, model)  # паспорт: пробы в фоне
        except Exception:
            pass
        return True
    except Exception as e:
        log.warning("Прогрев %s/%s не удался: %s", backend, model, e)
        return False


# ВЫГРУЗКА ИЗ LM STUDIO (2026-08-19). Ручки /api/v1/models/unload у LM
# Studio нет — она отдаёт 404, и мы девять раз подряд писали в лог
# «нужна свежая версия», а 6.2 ГБ VRAM продолжали висеть занятыми рядом с
# llama.cpp. Настоящий способ один: консоль lms (LM Studio → Developer →
# Install CLI). REST оставлен вторым шансом на случай, что ручку вернут.
_LMS_MISS = {"logged": False}


def _lms_cli() -> str:
    """Путь к консоли lms: конфиг → переменная среды → PATH → стандартные
    места установки LM Studio."""
    import os
    import shutil
    home = os.path.expanduser("~")
    for p in (CFG.get("lmstudio.cli", ""), os.environ.get("LMS_PATH", ""),
              os.path.join(home, ".lmstudio", "bin", "lms.exe"),
              os.path.join(home, ".lmstudio", "bin", "lms.cmd"),
              os.path.join(home, ".lmstudio", "bin", "lms"),
              os.path.join(home, ".cache", "lm-studio", "bin", "lms.exe")):
        if p and os.path.isfile(p):
            return p
    return shutil.which("lms") or ""


def _lm_loaded() -> set:
    """Кто РЕАЛЬНО сейчас в памяти LM Studio. Единственный источник правды
    при выгрузке: код возврата `lms` о содержимом памяти не говорит."""
    try:
        r = requests.get(_lmstudio_url() + "/api/v0/models", timeout=3)
        return {m["id"] for m in (r.json().get("data") or [])
                if m.get("state") == "loaded" and m.get("id")}
    except Exception:
        return set()


def _lm_gone(model: str) -> bool:
    """Ушла ли модель из памяти. Даём LM Studio полсекунды: выгрузка
    асинхронная, и сразу после команды список ещё показывает старое."""
    import time as _t
    for _ in range(6):
        _t.sleep(0.5)
        cur = _lm_loaded()
        if not cur:
            # список пуст: либо памяти правда ничего нет, либо порт молчит.
            # Молчащий порт за успех не считаем — иначе снова соврём.
            return bool(_lm_probe_ok())
        if model not in cur:
            return True
    return False


def _lm_probe_ok() -> bool:
    try:
        return requests.get(_lmstudio_url() + "/api/v0/models",
                            timeout=3).ok
    except Exception:
        return False


def _lmstudio_unload(model: str) -> bool:
    """ВЫГРУЗКА С ПРОВЕРКОЙ (2026-08-22, владелец: «300 раз нажал, не
    выгружается»).

    Было: доверяли коду возврата `lms`. А `lms unload <имя>` выходит с
    нулём и когда НИЧЕГО не выгрузил — имя ключа модели в lms не всегда
    совпадает с именем в OpenAI-совместимом списке. Получалось худшее:
    в лог писалось «Модель выгружена», интерфейс верил, а модель висела
    в видеопамяти. Пять нажатий — пять бодрых записей об успехе и ноль
    освобождённых гигабайт.

    Стало: после каждой попытки СМОТРИМ, что реально в памяти. Не ушла —
    честно идём дальше, к `--all` и к HTTP. Не ушла нигде — возвращаем
    False и говорим человеку, почему."""
    import subprocess
    if model not in _lm_loaded() and _lm_probe_ok():
        return True                     # её и так нет — чинить нечего
    cli = _lms_cli()
    if cli:
        # сначала точечно, потом «всё» — имя ключа модели в lms может
        # отличаться от имени в OpenAI-совместимом списке, и тогда точечная
        # выгрузка не находит цель, а память надо освободить всё равно
        for args in ([cli, "unload", model], [cli, "unload", "--all"]):
            try:
                # encoding явно: на русской Windows text=True берёт
                # cp1251 и давится UTF-8 выводом (см. git_sync._run)
                r = subprocess.run(
                    args, capture_output=True, encoding="utf-8",
                    errors="replace", timeout=60,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if r.returncode == 0:
                    # НОЛЬ — ЕЩЁ НЕ УСПЕХ. Проверяем память.
                    if _lm_gone(model):
                        log.info("Модель %s выгружена (%s)", model,
                                 " ".join(args[1:]))
                        _LMS_MISS["logged"] = False
                        return True
                    log.warning(
                        "lms %s отчитался успехом, но %s ОСТАЛАСЬ в памяти "
                        "— пробую дальше", " ".join(args[1:]), model)
                else:
                    log.debug("lms %s: %s", " ".join(args[1:]),
                              ((r.stderr or "") or (r.stdout or ""))[:200])
            except Exception as e:
                log.debug("lms %s не отработал: %s", " ".join(args[1:]), e)
    for path, payload in (("/api/v1/models/unload", {"instance_id": model}),
                          ("/api/v0/models/unload", {"model": model})):
        try:
            r = requests.post(_lmstudio_url() + path, json=payload, timeout=30)
            if r.ok and _lm_gone(model):
                log.info("Модель %s выгружена (LM Studio %s)", model, path)
                _LMS_MISS["logged"] = False
                return True
        except Exception:
            pass
    if model in _lm_loaded():
        # самое частое и самое обидное: инструмент есть, команда проходит,
        # а память не пустеет. Говорим именно это, а не «нет консоли».
        log.warning(
            "LM Studio: %s не выгружается — команда проходит, но модель "
            "остаётся в памяти. Скорее всего имя в lms отличается от "
            "имени в списке. Выгрузи её в самом LM Studio.", model)
        return False
    if not _LMS_MISS["logged"]:
        _LMS_MISS["logged"] = True
        log.warning(
            "LM Studio держит %s в памяти, а выгрузить нечем: консоли lms не "
            "нашла (LM Studio → Developer → Install CLI, либо пропиши путь в "
            "config lmstudio.cli), ручки выгрузки по HTTP в этой сборке тоже "
            "нет. Пока — выгружай в самом LM Studio; повторяться в логе не "
            "буду.", model)
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
    if backend == "llamacpp":
        # у llama-server нет ручки «выгрузи модель, но живи» — модель живёт
        # ровно столько, сколько процесс. Гасим процесс: это и есть выгрузка,
        # и VRAM освобождается полностью (важно — карту делим с TTS и STT).
        try:
            from anamorf.llm import llamacpp
            log.info("%s", llamacpp.unload())
            return True
        except Exception as e:
            log.warning("llama-server: выгрузка не удалась: %s", e)
            return False
    if backend == "locallm":
        try:
            requests.post(_locallm_url() + "/admin/unload", timeout=30)
            log.info("Модель %s выгружена (LocalLM)", model)
            return True
        except Exception as e:
            log.warning("LocalLM: выгрузка не удалась: %s", e)
            return False
    return _lmstudio_unload(model)


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
        ("llamacpp", _llamacpp_url(), "/v1/models"),
    ):
        if _down(name):
            st[name] = False       # молчал недавно — перепроба через минуту
            continue
        try:
            requests.get(url + probe, timeout=2)
            st[name] = True
            _mark_up(name)
        except Exception:
            st[name] = False
            _mark_down(name)
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


def _strip_images(messages):
    """Убрать вложенные картинки, оставив текст. Нужно, когда бэкенд
    отказался их принимать: молчать из-за необязательного вложения — худшее
    из решений."""
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            txt = " ".join(p.get("text", "") for p in c
                           if isinstance(p, dict) and p.get("type") == "text")
            out.append({**m, "content": txt.strip()})
        else:
            out.append(m)
    return out


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
    # Ollama, как и LM Studio, грузит модель по первому же запросу —
    # см. разбор в _stream_lmstudio и правило в anamorf/llm/one_local.py
    if model not in (loaded_models() or []):
        from anamorf.llm import one_local
        _no = one_local.refuse("ollama")
        if _no:
            raise LLMError("Ollama: " + _no["error"])
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
                    from anamorf import capabilities as _caps
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
        token = str(msg.get("content") or "")
        if token:
            yield {"type": "token", "text": token}
        for tc in msg.get("tool_calls") or []:
            yield {"type": "tool_call", "call": tc}
        if chunk.get("done"):
            break


def _stream_lmstudio(messages, model, temperature, tools=None, image=None):
    """LM Studio — OpenAI-совместимый локальный сервер.

    ВАЖНО ПРО JIT (2026-08-20). Запрос к незагруженной модели LM Studio не
    отвергает — он молча ГРУЗИТ её в видеокарту. Поэтому мало запретить
    прогрев: обычный запрос делает ровно то же самое, только без слова
    «загружаю» в логе. Владелец из-за этого выключал LM Studio руками.
    Модель уже в памяти — идём как обычно; нет — сперва спрашиваем, не
    занята ли видеокарта кем-то другим.
    """
    if model not in (loaded_models() or []):
        from anamorf.llm import one_local
        _no = one_local.refuse("lmstudio")
        if _no:
            raise LLMError("LM Studio: " + _no["error"])
    yield from _stream_openai(_lmstudio_url() + "/v1", None,
                              messages, model, temperature, tools, image)


def _stream_llamacpp(messages, model, temperature, tools=None, image=None):
    """Свой llama-server: сперва убеждаемся, что он поднят (спавнер сам
    скачает бинарь и запустит процесс), дальше — обычный OpenAI-стрим.

    Отдельного разбора ответа не нужно: llama.cpp говорит на том же
    OpenAI-диалекте, что LM Studio и облако. Больше того, chat_template_kwargs
    здесь РАБОТАЕТ (это родное поле llama.cpp, а не расширение) — то самое,
    которое OpenAI-слой LM Studio молча выбрасывал, из-за чего gemma-4
    думала по 4-9 секунд перед каждым словом."""
    from anamorf.llm import llamacpp
    if not CFG.get("llamacpp.url"):        # свой процесс, а не чужая машина
        st = llamacpp.ensure_running()
        if st.get("error"):
            raise LLMError("llama-server: " + st["error"])
        if st.get("installing"):
            raise LLMError("llama-server " + st.get(
                "note", "ещё устанавливается — попробуй через минуту"))
    _T["t_engine"] = time.monotonic()
    for ev in _stream_openai(_llamacpp_url() + "/v1", None,
                             messages, model, temperature, tools, image):
        if ev.get("type") == "token":
            # настоящий ответ дошёл — значит сервер жив, отдельная проверка
            # перед следующей репликой не нужна
            llamacpp.note_alive()
        yield ev


def _stream_locallm(messages, model, temperature, tools=None, image=None):
    """Свой воркер LocalLM: сперва убеждаемся, что он поднят (спавнер сам
    поставит окружение/запустит процесс), затем — обычный OpenAI-стрим.
    tools воркер в v1 игнорирует молча (без 400), картинок у модели нет —
    _attach_image_openai всё равно приложит, воркер сам отбросит."""
    from anamorf.llm import locallm
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
    c = cloud_for(model)
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
# ОДНА HTTP-СЕССИЯ НА ВСЕ ЛОКАЛЬНЫЕ ЗАПРОСЫ (2026-07-27, охота за 300мс).
# requests.post() без сессии на каждый вызов: (1) лезет в реестр Windows за
# системным прокси (getproxies — это сотни миллисекунд на некоторых
# машинах), (2) заново открывает TCP-соединение. Для облака это шум на фоне
# сети, для localhost — БОЛЬШАЯ часть задержки. Session с trust_env=False
# держит соединение открытым и не трогает реестр вообще.
_HTTP = requests.Session()
_HTTP.trust_env = False


_API_QUIRKS: dict = {}


def _persist_quirks(base_url, model, fields):
    """Запомнить причуды провайдера В КОНФИГ. Память в процессе умирает с
    ним, и каждый запуск заново платил холостым 4xx за то, что мы уже
    выясняли вчера."""
    try:
        d = dict(CFG.get("llm.api_quirks", {}) or {})
        key = f"{base_url}|{model}"
        d[key] = sorted(set(d.get(key, [])) | set(fields))
        CFG.set("llm.api_quirks", d)
    except Exception as e:
        log.debug("причуды не сохранились: %s", e)


def _load_quirks(base_url, model):
    """Слить сохранённые причуды в память процесса (зовётся перед сборкой
    запроса — дёшево, это чтение словаря из уже загруженного конфига)."""
    try:
        d = CFG.get("llm.api_quirks", {}) or {}
        saved = d.get(f"{base_url}|{model}")
        if saved:
            _API_QUIRKS.setdefault((base_url, model), set()).update(saved)
    except Exception:
        pass

# отсечки одного вызова: выбор моделей -> сборка запроса -> ответ сервера ->
# первый токен. Живут между chat_stream и _stream_openai, поэтому модульные.
_T: dict = {}

# модели, про которые уже сказали «размышления не выключились» — предупреждаем
# один раз на модель, а не на каждую фразу
_THINK_WARNED: set = set()

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
                     "system role must be the first",
                     # шаблон Qwen3.5 (2026-08-23): её jinja кидает
                     # raise_exception('System message must be at the
                     # beginning') — та же болезнь, другие слова
                     "system message must be at the beginning",
                     "must be at the beginning")


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


def _is_cloud_url(url: str) -> bool:
    """Облако или свой порт. Считаем по адресу: локальные движки всегда на
    127.0.0.1/localhost, всё остальное — чужой сервер за деньги."""
    u = (url or "").lower()
    return not ("127.0.0.1" in u or "localhost" in u or "::1" in u)


def _local_backend_of(url: str) -> str:
    u = (url or "").lower()
    for name, fn in (("llamacpp", _llamacpp_url), ("locallm", _locallm_url),
                     ("lmstudio", _lmstudio_url), ("ollama", _ollama_url)):
        try:
            if fn().lower().rstrip("/") in u:
                return name
        except Exception:
            continue
    return "local"


def _stream_openai(base_url, api_key, messages, model, temperature, tools=None,
                   image=None):
    """Общий OpenAI-совместимый стрим (LM Studio и облако).

    Фрагменты tool_call приходят по кусочкам в разных чанках (по index,
    function.arguments — строка, собирается конкатенацией), поэтому копим их
    и достраиваем целиком, когда стрим закончился."""
    if image is not None and "_noimg" in _API_QUIRKS.get((base_url, model), ()):
        image = None            # уже выяснили: этот бэкенд картинок не ест
    messages = _attach_image_openai(messages, image)
    # GigaChat известен заранее, остальных выучиваем по первому 422 (ниже)
    # ═══ СИСТЕМНОЕ СООБЩЕНИЕ — ТОЛЬКО ПЕРВЫМ (27.08.2026) ═══
    # Живой отказ её собственного llama.cpp на Qwen3.5-9B:
    #   Unable to generate parser for this template …
    #   raise_exception('System message must be at the beginning')
    # Шаблоны Qwen/Llama в llama.cpp это требование проверяют жёстко и
    # роняют ВЕСЬ запрос, а системные вставки у нас добавляются по ходу
    # (предупреждения, восстановление, повтор без инструментов — там
    # десяток мест вида msgs + [{"role":"system"...}]). Чинить каждое
    # место бессмысленно: сворачиваем здесь, у самой отправки, для всех
    # локальных движков — они все на openai-совместимом протоколе, но с
    # настоящим Jinja-шаблоном модели внутри.
    _local = any(h in str(base_url or "") for h in
                 ("127.0.0.1", "localhost", "0.0.0.0"))
    if (_local or _is_gigachat(base_url)
            or "mid_system" in _MSG_QUIRKS.get((base_url, model), ())):
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
        payload["chat_template_kwargs"] = {"enable_thinking": False,
                                           "thinking": False}
        # ВТОРОЙ ЗАМОК НА ТУ ЖЕ ДВЕРЬ (2026-07-27, подтверждено замером).
        # gemma-4 в LM Studio думает ДАЖЕ когда мы просим не думать: её
        # OpenAI-совместимый слой выбрасывает chat_template_kwargs (поле
        # придумано llama.cpp, в API LM Studio его нет). В логе это видно
        # как completion_tokens_details.reasoning_tokens = 243..546 — то
        # есть секунды генерации мыслей до первого видимого слова.
        #
        # tools/latency_bench.py прогнал все известные способы на живой
        # сборке. Итог (reasoning_tokens в ответе):
        #   chat_template_kwargs enable_thinking=false ... 202  — НЕ работает
        #   reasoning: {"effort": "none"} (вложенное) ....... 254  — НЕ работает
        #   reasoning: {"effort": "minimal"} ................ 180  — НЕ работает
        #   reasoning_effort: "none"  (ПЛОСКОЕ поле) ........   0  — работает
        # Поэтому шлём именно плоское поле. Вложенный вариант из changelog
        # LM Studio (0.3.29, «reasoning.effort») её же слоем и игнорируется —
        # не возвращать его обратно, это уже проверено.
        if not api_key:
            payload["reasoning_effort"] = CFG.get("llm.reasoning_effort",
                                                  "none")
        # целевое время ответа (llm.target_response_s, 0 = выкл): если
        # паспорт знает скорость модели — считаем потолок токенов под цель.
        # ТОЛЬКО при выключенных размышлениях: думающий режим съедает лимит
        # мыслями и получает 0 токенов ответа (грабли 2026-07-21).
        try:
            from anamorf.llm import passport
            target = float(CFG.get("llm.target_response_s", 0) or 0)
            tps = passport.tps_for(model)
            if target > 0 and tps:
                payload["max_tokens"] = max(96, int(tps * target * 0.8))
        except Exception:
            pass
    # ТРЕТИЙ ЗАМОК — ДОСЫЛ НАЧАТОГО ХОДА (llm.nothink_prefill, по умолчанию
    # выключен). Если сборка игнорирует и chat_template_kwargs, и
    # reasoning.effort — остаётся приём, который не зависит от полей вообще:
    # последним сообщением кладём УЖЕ НАЧАТЫЙ ответ ассистента с закрытым
    # блоком мыслей («<think>\n\n</think>»). Шаблон продолжает начатый ход,
    # фаза размышления оказывается пройденной ещё до первого токена.
    # Включать только если замер (tools/latency_bench.py) показал, что поля
    # не работают: приём ломает tool-calling у части шаблонов.
    _prefill = CFG.get("llm.nothink_prefill", "") if not api_key else ""
    if _prefill and not CFG.get("llm.think", False):
        payload["messages"] = list(payload["messages"]) + [
            {"role": "assistant", "content": _prefill}]
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
    _load_quirks(base_url, model)
    for f in _API_QUIRKS.get((base_url, model), ()):
        payload.pop(f, None)
    _T["t_build"] = time.monotonic()
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    # у GigaChat та же история с российским УЦ, что и у его OAuth —
    # решение принято один раз в _gigachat_token и переиспользуется здесь
    _verify = _giga["verify"] if _is_gigachat(base_url) else True

    def _do_request(body):
        # локальный сервер — через постоянную сессию (см. _HTTP выше);
        # облако — обычным requests: там свои прокси и env уместны
        _req = _HTTP.post if not api_key else requests.post
        r = _req(base_url + "/chat/completions", json=body,
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
        _T["t_resp"] = time.monotonic()
    except requests.exceptions.HTTPError as e0:
        # 400/422 бывает по РАЗНЫМ причинам у разных облаков: строгий
        # temperature у Moonshot («only 1 is allowed»), незнакомый
        # chat_template_kwargs (расширение llama.cpp/LM Studio), кривые
        # tools-схемы. Ищем виновника ПО ОДНОМУ (не скопом — иначе вместе с
        # виноватым полем навсегда потеряли бы, например, инструменты),
        # а найденное запоминаем в _API_QUIRKS: следующая фраза строит
        # запрос сразу правильно, без холостых заходов.
        recovered, last = False, e0
        _txt0 = str(e0).lower()
        # ФАЗА «ПО ИМЕНАМ» (2026-08-23, живой вечер: mistral на КАЖДУЮ
        # фразу отвечал 422 extra_forbidden, Сайка сваливалась в GigaChat
        # и говорила канцеляритом — «че она как ботяра отвечает»).
        # Перебор по одному не лечил: запрещённых полей у mistral
        # НЕСКОЛЬКО сразу (typical_p, repeat_penalty, xtc_*…), и каждая
        # одиночная проба падала об остальные. А ведь провайдер САМ
        # перечисляет виновников — pydantic-ошибка содержит
        # "loc":["body","<поле>"] на каждое. Читаем имена и снимаем все
        # разом: одна повторная проба вместо шестнадцати холостых.
        if not recovered:
            _bad_fields = set(re.findall(
                r'"loc"\s*:\s*\[\s*"body"\s*,\s*"([a-z_]+)"', str(e0)))
            _bad_fields &= set(payload.keys())
            _bad_fields -= {"messages", "model", "stream"}   # святое не трогаем
            if _bad_fields:
                trial = {k: v for k, v in payload.items()
                         if k not in _bad_fields}
                try:
                    r = _do_request(trial)
                    recovered = True
                    payload = trial
                    _API_QUIRKS.setdefault((base_url, model),
                                           set()).update(_bad_fields)
                    _persist_quirks(base_url, model, _bad_fields)
                    log.warning("API %s сам назвал запрещённые поля (%s) — "
                                "сняла их разом и запомнила насовсем",
                                model, ", ".join(sorted(_bad_fields)))
                except requests.exceptions.HTTPError as e1:
                    last = e1
        # ФАЗА «МИНУС ОДИН» — БЭКЕНД НЕ УМЕЕТ КАРТИНКИ (2026-07-29).
        # llama-server, запущенный без --mmproj, на любой запрос с
        # изображением отвечает 500 «image input is not supported». Модель
        # мультимодальная, но её глаза не подключены. Раньше это валило весь
        # ход целиком: «Ни одна LLM не ответила», и Сайка молчала на
        # «открой проводник» — хотя картинка там была не нужна вовсе, её
        # просто приложило включённое зрение.
        #
        # Правильное поведение — ответить БЕЗ картинки, а не умереть с ней.
        # Текст важнее вложения: человек спросил про проводник, а не про
        # скриншот. Запоминаем неумение за (адрес, модель), чтобы следующие
        # ходы шли сразу правильно и без холостого захода.
        # ТЕСНОЕ ОКНО — НЕ БОЛЕЗНЬ (2026-08-23, живой вечер: прикидка
        # «3 символа = токен» насчитала 7700, а токенизатор сервера — 8570
        # при окне 8192; за этот 400 модель уводили в карантин, и разговор
        # забирал гигачат). Лечение по месту: срезаем старую историю
        # (система и последняя реплика неприкосновенны) и пробуем ещё раз.
        if any(h in _txt0 for h in ("exceed", "context size",
                                    "context length", "too many tokens")):
            try:
                _msgs = list(payload.get("messages") or [])
                _sys = [m for m in _msgs if m.get("role") == "system"]
                _rest = [m for m in _msgs if m.get("role") != "system"]

                def _try(trial, said):
                    nonlocal r, payload, recovered, last
                    try:
                        r = _do_request(trial)
                        payload = trial
                        recovered = True
                        log.warning("Окно контекста тесное — %s — и "
                                    "ответила", said)
                        return True
                    except requests.exceptions.HTTPError as e1:
                        last = e1
                        return False

                # ступень 1: история половинами, от старого к новому
                while not recovered and len(_rest) > 2:
                    _rest = _rest[max(1, len(_rest) // 2):]
                    if _try(dict(payload, messages=_sys + _rest),
                            "срезала историю до %d сообщений" % len(_rest)):
                        break
                    _et = str(getattr(last.response, "text", "") or last
                              ).lower()
                    if not any(h in _et for h in ("exceed", "context")):
                        break
                # ступень 2: УЖАТЬ СИСТЕМУ, А НЕ ОТНИМАТЬ РУКИ (2026-08-23,
                # живой разнос: первая версия этой лесенки выбрасывала
                # схемы инструментов — и Сайка, оставшись без рук, начала
                # ГОВОРИТЬ, что свернула окна, вместо того чтобы свернуть.
                # «Алгоритмы врут о своём действительном намерении» —
                # ровно отсюда. Руки отнимаем последними, характер и
                # болтовню режем первыми.)
                def _squeeze_sys(limit=7000, head=5000, tail=2000):
                    out = []
                    for m in _sys:
                        c = str(m.get("content") or "")
                        if len(c) > limit:
                            c = c[:head] + "\n…\n" + c[-tail:]
                        out.append(dict(m, content=c))
                    return out
                if not recovered and _sys:
                    _try(dict(payload, messages=_squeeze_sys() + _rest[-2:]),
                         "ужала системный промпт, руки оставила")
                if not recovered and _sys:
                    _try(dict(payload,
                              messages=_squeeze_sys(3000, 2000, 800)
                              + _rest[-1:]),
                         "ужала систему до костяка, руки оставила")
                # ступень 3: рук слишком много — оставляем ЯДРО (окна,
                # запуск, громкость, плеер), а не выбрасываем все
                if not recovered and payload.get("tools"):
                    try:
                        from anamorf.llm.tools import _CORE_TOOLS as _CT
                        _keep = set(_CT) | {"media_control", "window_minimize",
                                            "window_list", "avatar_action",
                                            "orb_mode", "type_text"}
                        _few = [t for t in payload["tools"]
                                if ((t.get("function") or {}).get("name")
                                    in _keep)]
                    except Exception:
                        _few = payload["tools"][:20]
                    if _few and len(_few) < len(payload["tools"]):
                        _try(dict(payload, tools=_few,
                                  messages=_squeeze_sys(3000, 2000, 800)
                                  + _rest[-1:]),
                             "оставила только основные руки (%d из %d)"
                             % (len(_few), len(payload["tools"])))
                # ступень 4, последняя: рук нет совсем — и модели об этом
                # говорим ПРЯМО, чтобы она не выдумывала, будто сделала
                if not recovered and payload.get("tools"):
                    _warn = {"role": "system", "content":
                             "ВНИМАНИЕ: в этот ход инструменты недоступны — "
                             "рук у тебя сейчас НЕТ. Никогда не пиши, что "
                             "ты что-то сделала, свернула, закрыла или "
                             "перенесла: ты этого не делала. Честно скажи "
                             "одной фразой, что руки отвалились на секунду, "
                             "и попроси повторить."}
                    t4 = dict(payload,
                              messages=_squeeze_sys(3000, 2000, 800)
                              + [_warn] + _rest[-1:])
                    t4.pop("tools", None)
                    _try(t4, "рук не осталось — предупредила её об этом")
            except Exception as e2:
                log.debug("обрезка истории не спасла: %s", e2)
        # картинка может лежать и внутри messages (кадр зрения), а не в
        # параметре image — лечим по ТЕКСТУ ошибки, не по параметру
        if any(h in _txt0 for h in (
                "image input is not supported", "mmproj",
                "does not support image", "vision is not supported")):
            trial = dict(payload, messages=_strip_images(payload["messages"]))
            try:
                r = _do_request(trial)
                payload = trial
                _API_QUIRKS.setdefault((base_url, model), set()).add("_noimg")
                log.warning("API %s не принимает картинки (запущен без "
                            "--mmproj?) — отвечаю по тексту, картинку "
                            "отбрасываю. Дальше шлю сразу без неё", model)
                recovered = True
            except requests.exceptions.HTTPError as e1:
                last = e1
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
            # «reasoning» — первым: поле новое (LM Studio 0.3.29+), и если
            # сборка старше, ругаться она будет именно на него
            f for f in ("reasoning_effort", "tools", "chat_template_kwargs",
                        "cache_prompt", "max_tokens", "temperature",
                        "stream_options")
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
            # «sampling» — имя ГРУППЫ, а не поля: раскрываем в настоящие
            # ключи, иначе фаза 2 снимала всё, кроме как раз сэмплинга
            # (2026-08-23, тот самый вечер с mistral)
            _drop = set(suspects) - {"sampling"}
            if "sampling" in suspects:
                _drop |= set(_SAMPLING_OPENAI)
            trial = {k: v for k, v in payload.items() if k not in _drop}
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
    _tgate: dict = {}          # состояние резака <think> между чанками
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
            # СЧЁТ (2026-08-13): цифры и раньше проходили через лог, но
            # нигде не копились — узнать «сколько сожгли за день» можно было
            # только грепом. Бюджет нельзя соблюдать, не умея считать, а
            # фоновым облачным задачам бюджет обязателен.
            try:
                from anamorf import usage as _u
                _bk = ("cloud" if _is_cloud_url(base_url)
                       else _local_backend_of(base_url))
                _u.add(_bk, model, _usage)
            except Exception as e:
                log.debug("счётчик расхода пропущен: %s", e)
            # ГЛАВНЫЙ ПОЖИРАТЕЛЬ СЕКУНД, ЕСЛИ ОН ВЕРНЁТСЯ (2026-07-27).
            # Размышления не видно ни в чате, ни в счётчике токенов ответа —
            # они всплывают ТОЛЬКО здесь, отдельным полем usage. Пока это
            # лежало сырым JSON'ом в логе, «Сайка думает 6 секунд» месяц
            # списывалось на «модель медленная». Теперь: просили не думать,
            # а мысли всё равно есть -> кричим один раз на модель, с
            # рецептом, а не с загадкой.
            try:
                _rt = int(((_usage.get("completion_tokens_details") or {})
                           .get("reasoning_tokens") or 0))
            except Exception:
                _rt = 0
            if _rt and not CFG.get("llm.think", False) \
                    and model not in _THINK_WARNED:
                _THINK_WARNED.add(model)
                log.warning(
                    "Размышления НЕ выключились: %s потратила %d токенов "
                    "мыслей до первого слова (это ~%.1fс на 60 ток/с). "
                    "Поля запроса сборка игнорирует. Лечение: в LM Studio "
                    "открыть модель -> Prompt Template и первой строкой "
                    "добавить {%%- set enable_thinking = false %%}, либо "
                    "включить в config llm.nothink_prefill. Проверить: "
                    "python tools/latency_bench.py", model, _rt, _rt / 60.0)
        if not chunk.get("choices"):
            continue
        try:
            delta = chunk["choices"][0]["delta"]
        except Exception:
            continue
        token = str(delta.get("content") or "")
        if token and not CFG.get("llm.think", False):
            token = _think_gate(_tgate, token)
        if token:
            if not _T.get("logged"):
                _T["logged"] = True
                _ms = lambda a, b: max(0, round((b - a) * 1000))
                _now = time.monotonic()
                t0 = _T.get("t0", _now)
                _g = lambda k, d=None: _T.get(k, d if d is not None else t0)
                _pick = _g("t_pick")
                _load = _g("t_loaded", _pick)
                _tls = _g("t_tools", _load)
                _eng = _g("t_engine", _tls)
                log.info(
                    "LLM разбивка: список моделей %dмс | загруженные %dмс "
                    "| инструменты %dмс | движок %dмс | сборка %dмс "
                    "| ответ сервера %dмс | стрим до 1-го токена %dмс "
                    "| итого %dмс",
                    _ms(t0, _pick), _ms(_pick, _load), _ms(_load, _tls),
                    _ms(_tls, _eng), _ms(_eng, _g("t_build", _eng)),
                    _ms(_g("t_build", _eng), _g("t_resp", _eng)),
                    _ms(_g("t_resp", _eng), _now), _ms(t0, _now))
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
        "locallm": _stream_locallm, "llamacpp": _stream_llamacpp,
        "cloud": _stream_cloud}


def _think_gate(st: dict, tok: str) -> str:
    """Вырезать <think>…</think> ИЗ ПОТОКА, тег может быть разрезан чанками.

    2026-08-23, живой вечер: тумблер «размышления выкл» стоит, а близнец
    qwen3-14b-abliterated-q4_k_m шлёт <think> прямо в текст — его шаблон
    не понимает enable_thinking. Черновик уходил в чат и в ГОЛОС. Режем на
    уровне потока: между <think> и </think> наружу не выходит ничего."""
    st["buf"] = st.get("buf", "") + tok
    out = []
    while True:
        b = st["buf"]
        if st.get("in"):
            i = b.find("</think>")
            if i < 0:
                st["buf"] = b[-9:]            # хвост на случай разреза тега
                break
            st["in"] = False
            st["buf"] = b[i + 8:]
            continue
        # ОДИНОКИЙ ЗАКРЫВАЮЩИЙ ТЕГ (2026-08-23): шаблон открыл <think> сам,
        # до нас дошёл только «</think>». Всё, что перед ним, — черновик:
        # выбрасываем и его, и тег.
        j = b.find("</think>")
        if j >= 0 and (b.find("<think>") < 0 or b.find("<think>") > j):
            out = []                       # уже накопленное — тоже черновик
            st["buf"] = b[j + 8:]
            st["stray"] = True
            continue
        i = b.find("<think>")
        if i < 0:
            keep = 0
            for k in range(min(7, len(b)), 0, -1):
                if "<think>"[:k] == b[-k:]:
                    keep = k
                    break
            out.append(b[:len(b) - keep])
            st["buf"] = b[len(b) - keep:]
            break
        out.append(b[:i])
        st["in"] = True
        st["buf"] = b[i + 7:]
    return "".join(out)


def _flatten_content(messages):
    """Мультимодальный content (список частей) -> обычная строка.

    2026-08-13, живой обвал: у Сайки были включены глаза, и кадр экрана
    уходил КАЖДОМУ мозгу подряд. Cloudflare отвечал 400 «Type mismatch of
    '/messages/0/content', 'array' not in 'string'», GigaChat — тем же по
    смыслу, и падала вся цепочка фолбэка разом: в интерфейсе «Ни одна LLM
    не ответила», хотя ключи живые и модели на месте. Слепой модели
    картинку слать незачем — снимаем её и оставляем текст."""
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            txt = " ".join(p.get("text", "") for p in c
                           if isinstance(p, dict) and p.get("type") == "text")
            m = dict(m, content=txt.strip() or "(смотрю на экран)")
        out.append(m)
    return out


def _can_see(backend: str, model: str) -> bool:
    """Пустят ли этой модели картинку. Неизвестность трактуем как «нет»:
    лишний кадр в лучшем случае стоит денег и секунд, а в худшем — роняет
    весь запрос (см. _flatten_content). Локальным оставляем прежнюю
    вольность — там опыт накапливается пробой и ничего не стоит."""
    try:
        from anamorf import capabilities as caps
        v = caps.vision(model)
        if v is not None:
            return bool(v)
    except Exception:
        pass
    return backend != "cloud"


def _last_user_text(messages) -> str:
    """Последняя реплика человека — по ней выбираются схемы инструментов."""
    for m in reversed(list(messages or [])):
        if (m or {}).get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, list):
            c = " ".join(x.get("text", "") for x in c
                         if isinstance(x, dict) and x.get("type") == "text")
        return str(c or "")[:600]
    return ""


_LAST_OK = {"bm": None}      # (backend, model), который дал прошлый ответ


def chat_stream(messages, on_fallback=None, on_tool=None, image=None,
                on_model=None, use_tools=True, should_stop=None,
                prefer=None):
    """Стрим токенов. При падении основного бэкенда — автопереход на второй.

    Если запущен HandsPC (anamorf/llm/tools.py), модель получает инструменты
    (web_search и др.) на ОБОИХ бэкендах: увидели tool_calls -> выполняем,
    подкладываем результаты и продолжаем диалог (до tools.max_rounds раундов).
    LM Studio: если загруженная модель/шаблон не понимает tools, сервер
    сам откатится на обычный чат без них (см. _stream_lmstudio) — тогда
    модель может по-прежнему писать инструменты текстом, это ограничение
    конкретной модели, не бага менеджера.
    on_tool(name, args) — колбэк для UI («🔎 ищу в сети…»).
    """
    from anamorf.llm import tools as handspc
    from anamorf import ratings

    # РАЗБИВКА «prefill» (2026-07-27). В логе Сайки время от отправки до
    # первого токена — одно число, и когда движок отчитывается о 0.9с, а
    # число показывает 3.0с, спорить не с чем: неизвестно, где эти секунды.
    # Здесь ставим отсечки, чтобы разбивка была видна прямым текстом.
    _T.clear()
    _T["t0"] = time.monotonic()
    primary = CFG.get("llm.backend", "ollama")
    temperature = CFG.get("llm.temperature", 0.8)
    last_err = None
    _fns = _FNS

    # ПОРЯДОК ФОЛЛБЭКА ПО РЕЙТИНГУ: сперва выбранная модель, затем ОСТАЛЬНЫЕ
    # локальные модели по убыванию оценки (лучшая — первой запаской). Так при
    # ошибке подхватывается хороший вариант, а не случайная мелкая модель.
    try:
        # ДЕЙСТВУЮЩИЕ оценки: ручной выбор владельца ГЛАВНЕЕ замера скорости,
        # имена сведены к общему виду (см. ratings.effective_scores).
        scores = ratings.effective_scores()
    except Exception:
        try:
            scores = ratings.llm_scores()
        except Exception:
            scores = {}
    candidates = []
    # prefer=(backend, model) — выбор «быстрого мышления» НА ЭТОТ ход
    # (anamorf/llm/router.py): облако для настоящей задачи, локальная для
    # болтовни. Конфиг не меняется, фолбэк обычный: не ответило — следом
    # пойдёт штатная модель.
    if prefer:
        candidates.append(tuple(prefer))
    try:
        primary_model = _pick_model(primary)
        if (primary, primary_model) not in candidates:
            candidates.append((primary, primary_model))
    except Exception as e:
        last_err = e
    # БОЛЬНОГО НЕ ДЁРГАЕМ, СОБЕСЕДНИКА НЕ МЕНЯЕМ (2026-08-15). Живой вечер:
    # mistral (выбранная) ловит 429 «Rate limit exceeded», уходит в карантин
    # на 600с — и через десять секунд снова стоит ПЕРВОЙ, потому что этот
    # список всегда начинался с выбранной, а карантин смотрела только
    # лестница. Итог: mistral, GigaChat, mistral, GigaChat — через реплику,
    # у каждой свой характер, и человек говорит то с одной, то с другой:
    # «нах она такая тупая и в контекст просто пиздец не может». Плюс
    # каждый 429 — это секунды ожидания впустую перед фолбэком.
    # Теперь: больная (по карантину brains) уезжает в конец списка, а тот,
    # кто РЕАЛЬНО ответил прошлый раз, встаёт первым — разговор держит
    # один голос, пока выбранная не выздоровеет.
    try:
        from anamorf.llm import brains as _br
        _lastok = _LAST_OK.get("bm")
        if (_lastok and _lastok not in candidates[:1]
                and candidates and _br.is_sick(*candidates[0])):
            candidates.insert(0, _lastok)
        # БОЛЬНОГО НЕ ЗОВЁМ ПЕРВЫМ, ЕСЛИ ЕСТЬ ЗДОРОВЫЙ (2026-08-23, живой
        # лог: mistral отваливался по таймауту КАЖДЫЙ раз, и каждый ответ
        # начинался с десяти секунд ожидания в закрытую дверь — «думала
        # 17.8с» на «включи музыку». Раньше больные просто съезжали в
        # хвост списка, но выбор человека вставлялся в начало заново, и
        # хвост не спасал. Пока есть хоть один здоровый — больные из
        # очереди убираются совсем; здоровых нет — зовём как раньше, это
        # лучше, чем не ответить.)
        _ok = [bm for bm in candidates if not _br.is_sick(*bm)]
        _ill = [bm for bm in candidates if _br.is_sick(*bm)]
        if _ok and _ill:
            log.info("Пропускаю отложенные мозги: %s",
                     ", ".join(f"{b}/{m}" for b, m in _ill)[:120])
        candidates = _ok + (_ill if not _ok else [])
    except Exception as e:
        log.debug("сортировка по здоровью не вышла: %s", e)
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
    _T["t_pick"] = time.monotonic()
    # уже загруженные в память — раньше по списку: фолбэк не должен
    # устраивать карусель JIT-загрузок в LM Studio
    try:
        loaded = set(loaded_models())
    except Exception:
        loaded = set()
    _T["t_loaded"] = time.monotonic()
    # ═══ ПОРЯДОК — ПО РЕЙТИНГУ, А НЕ ПО ТОМУ, ЧТО СЛУЧАЙНО В ПАМЯТИ ═══
    # (27.08.2026, владелец: «нахуй мы систему рейтинга писали, если модели
    # произвольно вырубаются из середины, а не логично по рейтингу».)
    #
    # Было: ПЕРВЫМ ключом стояло «уже загружена», рейтинг — только при
    # равенстве. То есть побеждала та модель, которую движок держал в
    # памяти, независимо от оценки. Живой случай: mistral-7b-grok вообще
    # БЕЗ оценки отвечал вместо Qwen3.5-9B с ручной десяткой — просто
    # потому, что висел резидентом.
    #
    # Стало: первым ключом рейтинг. «Уже в памяти» осталось, но лишь как
    # решение спора между равными — грузить лишние гигабайты по-прежнему
    # не хотим, а вот подменять выбор владельца больше не будем.
    def _sc(nm):
        try:
            return ratings.score_for(nm, scores)
        except Exception:
            return int(scores.get(nm, 0) or 0)
    locals_.sort(key=lambda bm: (-_sc(bm[1]), bm[1] not in loaded))
    # ЗАПАСКА НЕ ГРУЗИТ ЧУЖИЕ ГИГАБАЙТЫ (2026-08-23, владелец: «заебал он
    # запускать то, что не просят»). Фолбэк на ДРУГУЮ локальную модель —
    # это молчаливая загрузка гигабайтов в видеопамять, которую человек не
    # заказывал, и война за карту с тем, что он заказал. Локальная запаска
    # разрешена только если она УЖЕ в памяти (ничего не грузим); всё
    # остальное — облако: у него видеопамять не своя, а выбранной модели
    # оно не мешает.
    for bm in locals_:
        if bm[1] not in loaded:
            continue
        if bm not in candidates:
            candidates.append(bm)
    # ЗАПАСНОЙ МОЗГ ПОСИЛЬНЕЕ (2026-08-13, просьба владельца: «если не
    # получилось — просто использует мозг с более высоким рейтингом»).
    # Раньше запаской шли ТОЛЬКО локальные модели: упало облако — Сайка
    # сползала на мелкую домашнюю и мучилась там. Теперь следом за текущей
    # идут настроенные облака с живым ключом, по убыванию мозгов, и только
    # потом парк. Ключи бесплатных тиров (GigaChat/Mistral/GitHub/Kimi)
    # уже лежат в secrets.json — они просто не участвовали в подъёме.
    if CFG.get("llm.escalate_on_fail", True):
        try:
            from anamorf.llm import brains
            strong = [(c["backend"], c["model"]) for c in brains.ladder()
                      if c["backend"] == "cloud"]
            head = candidates[:1]
            tail = [bm for bm in candidates[1:] if bm not in strong]
            candidates = head + [bm for bm in strong if bm not in head] + tail
        except Exception as e:
            log.debug("лестница мозгов недоступна: %s", e)
    # НОЛЬ — ЭТО ЗАПРЕТ, А НЕ ОЦЕНКА (2026-08-23, владелец: «все модели,
    # которые снижены до 0 по рейтингу, не должны вообще никак работать»).
    # Ручной ноль означает «выключена насовсем»: не выбранная, не запаска,
    # не лестница — никак. Если человек занулил всех, кроме одной, и она
    # упала — честнее промолчать с объяснением, чем позвать запрещённую.
    try:
        from anamorf import ratings as _rt0
        # запрет тоже по СВЕДЁННОМУ имени: иначе занулённая модель спокойно
        # проходила под своим вторым именем (та же беда с именами)
        _ban = {_rt0.norm_name(n)
                for n, v in (_rt0.manual_scores() or {}).items() if not v}
        if _ban:
            def _banned(m):
                nn = _rt0.norm_name(m)
                return nn in _ban or any(
                    b and nn and (b in nn or nn in b) and min(len(b), len(nn)) >= 6
                    for b in _ban)
            _kept = [bm for bm in candidates if not _banned(bm[1])]
            _cut = [m for _, m in candidates if _banned(m)]
            if _cut:
                log.info("Оценка 0 = запрет: не зову %s",
                         ", ".join(_cut)[:160])
            candidates = _kept
    except Exception as e:
        log.debug("фильтр нулевых оценок не сработал: %s", e)
    # КАДР ЭКРАНА НЕ УХОДИТ В ОБЛАКО САМ (2026-08-25, аудит). Слежка за
    # экраном шлёт скриншоты в LLM без спроса, а автоэскалация при сбое
    # локальной модели ставит облако первым в очередь — и кадр (с чужими
    # окнами, перепиской, документами) уходил стороннему провайдеру без
    # разового согласия. Пока vision.cloud_ok не включён явно, запросы с
    # картинкой обслуживают только локальные модели; облака из очереди
    # убираем. Нет локальной зрячей модели — честнее промолчать, чем
    # отправить экран на сторону.
    if image and not CFG.get("vision.cloud_ok", False):
        _before = len(candidates)
        candidates = [bm for bm in candidates if bm[0] != "cloud"]
        if _before > len(candidates):
            log.info("Кадр экрана: облачные модели исключены из ответа "
                     "(vision.cloud_ok выключен) — экран в облако не шлём")
    # максимум выбранная + 3 запасные: перебирать весь зоопарк моделей —
    # это минуты загрузок и непредсказуемое поведение
    candidates = candidates[:4]

    yielded_any = False
    for idx, (backend, model) in enumerate(candidates):
        # ПОЯС И ПОДТЯЖКИ (2026-08-23): карантин проверяем ещё раз у
        # самой двери. Сортировка выше могла отработать до того, как
        # мозг заболел (карантин ставится ВНУТРИ этого же цикла на
        # прошлой итерации знаний не имеет), и больной снова оказывался
        # первым — человек платил таймаутом за каждый ответ.
        try:
            from anamorf.llm import brains as _br2
            if _br2.is_sick(backend, model) and any(
                    not _br2.is_sick(*bm) for bm in candidates[idx + 1:]):
                log.info("Пропускаю %s/%s — в карантине, есть здоровый "
                         "дальше по списку", backend, model)
                continue
        except Exception:
            pass
        # если уже начали писать ответ этой моделью и она вдруг споткнулась
        # (например контекст переполнился на 2-3 раунде инструментов) —
        # НЕ подхватываем чужой моделью посреди фразы: две разные "личности"
        # в одном сообщении читаются как баг, а не как фоллбэк. Сообщаем
        # об обрыве честно и на этом останавливаемся.
        if yielded_any:
            raise LLMError(f"{backend}/{model} прервалась на середине ответа: {last_err}")
        try:
            fn = _fns.get(backend, _stream_lmstudio)
            # КАРТИНКА — ТОЛЬКО ЗРЯЧИМ (2026-08-13). Иначе включённые глаза
            # роняли ВСЮ цепочку: каждый следующий запасной мозг получал тот
            # же неудобоваримый запрос и падал так же.
            _img = image if _can_see(backend, model) else None
            _msgs0 = messages if _img else _flatten_content(messages)
            # СХЕМЫ ПОД ФРАЗУ, А НЕ ВСЕ 51 ШТУКА (2026-08-15): полный
            # набор — 36 тысяч символов, он вычитался из окна и
            # оставлял разговору полторы тысячи. Набор растёт с хвоста,
            # чтобы префикс промпта (и кэш) не рвался каждый ход.
            tools = (handspc.schemas_for(_last_user_text(messages))
                     if use_tools else [])
            _T["t_tools"] = time.monotonic()
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

            msgs = list(_msgs0)
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
                img = _img if _round == 0 else None
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
                    # ЖУРНАЛ ПРОМАХОВ РЕФЛЕКСА (2026-08-23, владелец:
                    # «нужно, чтобы она правильно фокусировалась на том,
                    # что сказали, а не выдумывала — просто моментально
                    # запускала команды»). Каждая команда, дошедшая до
                    # действия ЧЕРЕЗ размышления, — это фраза, которую
                    # рефлекс мог бы исполнить мгновенно и без выдумок.
                    # Записываем такие фразы: расширять рефлексы надо по
                    # тому, что человек говорит на самом деле, а не по
                    # тому, что мы придумали за столом.
                    try:
                        _rec_reflex_miss(name, args)
                        # …и та же фраза идёт в обучение: повторится с тем
                        # же вызовом — станет мгновенной. Успехом считаем
                        # результат без слов отказа: инструменты в этом
                        # проекте при провале говорят «не нашла/не вышло/
                        # не смогла», а не бросают исключения.
                        _res_l = str(result or "").lower()
                        _ok = not any(w in _res_l[:80] for w in
                                      ("не нашла", "не вышло", "не смогла",
                                       "не понял", "нет такого", "ошибк",
                                       "не удалось", "недоступ"))
                        from anamorf import reflex_learn as _rl
                        from anamorf.llm import tools as _tls2
                        _born = _rl.consider(_tls2.LAST_USER.get("text", ""),
                                             name, args, _ok)
                        if _born:
                            result = (result or "") + "\n[скажи человеку: "
                            result += _born + "]"
                    except Exception:
                        pass
                    # РАБОЧИЙ СТОЛ НА СЛЕДУЮЩИЙ ХОД (2026-08-15): результат
                    # инструмента жил ровно один запрос и умирал вместе с
                    # msgs — поэтому на «какие?» она честно не знала, о чём
                    # речь. См. anamorf/toolbuf.py, там разобран живой случай.
                    try:
                        from anamorf import toolbuf as _tb
                        _tb.note(name, args, result)
                    except Exception:
                        pass
                    if backend == "ollama":
                        msgs.append({"role": "tool", "tool_name": name,
                                     "name": name, "content": result})
                    else:
                        msgs.append({"role": "tool",
                                     "tool_call_id": c.get("id", f"call_{i}"),
                                     "content": result})
            _LAST_OK["bm"] = (backend, model)
            return
        except Exception as e:
            last_err = e
            log.warning("LLM %s/%s failed: %s", backend, model, e)
            # НЕСУЩЕСТВУЮЩАЯ МОДЕЛЬ — НАВСЕГДА, А НЕ НА 10 МИНУТ
            # (2026-08-13: каталог обещал @cf/zhipu/glm-4.7-flash, а
            # Cloudflare на неё отвечает «No such model». Через десять
            # минут карантина она возвращалась и роняла разговор снова.)
            _msg = str(e)
            if backend == "cloud" and ("No such model" in _msg
                                       or "model_not_found" in _msg
                                       or "does not exist" in _msg):
                try:
                    forget_cloud(model)
                    log.warning("Модель %s у провайдера не существует — "
                                "убрала из парка совсем", model)
                except Exception as e2:
                    log.debug("не вышло убрать %s: %s", model, e2)
            # мозг не отозвался — уводим его из лестницы на 10 минут, чтобы
            # следующая эскалация не билась в ту же закрытую дверь
            try:
                from anamorf.llm import brains
                brains.note_fail(backend, model, _msg[:120])
            except Exception:
                pass
    raise LLMError(f"Ни одна LLM не ответила: {last_err}")


def _rec_reflex_miss(name, args):
    """Фраза человека, которая доехала до инструмента через LLM.

    Пишем только то, что рефлекс НЕ узнал: узнанное и так мгновенно.
    Файл — простой jsonl, по строке на промах, без ротации: за вечер там
    десятки строк, и читать их будет человек, а не программа."""
    from anamorf.llm import tools as _tls
    text = (_tls.LAST_USER.get("text") or "").strip()
    if not text or len(text) > 200:
        return
    try:
        from anamorf import reflex as _rx
        if _rx.match(text):
            return                      # рефлекс её знает — не промах
    except Exception:
        pass
    import json as _json
    import time as _time
    from anamorf.config import resolve
    p = resolve("data") / "reflex_misses.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(_json.dumps({"ts": _time.strftime("%Y-%m-%d %H:%M:%S"),
                             "text": text, "tool": name,
                             "args": args}, ensure_ascii=False) + "\n")


def chat_once(messages, max_len=4000) -> str:
    """Нестриминговый вызов — для СЛУЖЕБНЫХ дел: суммаризация памяти,
    осмотр Беймакса, сводки диалога, решения агентного цикла.

    НЕ ЧЕРЕЗ МОДЕЛЬ СОБЕСЕДНИКА (2026-08-15). Раньше это шло через
    chat_stream, то есть через ТУ ЖЕ модель, что ведёт разговор. У
    бесплатного mistral лимит порядка запроса в секунду — и его съедали
    внутренние жильцы: Беймакс на старте (14 тысяч токенов!), сжатие
    памяти каждые полчаса, сводка после каждого ответа. Разговору
    оставались 429-е, фолбэк уводил на другую модель, у той свой характер
    — владелец: «они просто беспорядочно переключаются… всё делается не
    чтобы ускорить ответ, а наоборот». Он прав: служба объедала беседу.
    Теперь службе — другой здоровый облачный мозг, НЕ тот, что говорит с
    человеком. Некому — тогда по-старому, это редкость."""
    try:
        from anamorf.llm import brains
        cur_m = CFG.get("llm.model", "")
        # НОЛЬ — ЗАПРЕТ И ДЛЯ СЛУЖБЫ (2026-08-23: человек занулил облака,
        # разговор держит локальная — а служебные сводки продолжали бегать
        # к GigaChat боковой дверью. «Не должны вообще никак работать» —
        # значит и посуду мыть не зовём.)
        try:
            from anamorf import ratings as _rt1
            _ban1 = {n for n, v in (_rt1.manual_scores() or {}).items()
                     if not v}
        except Exception:
            _ban1 = set()
        for c in brains.ladder():
            if c["backend"] != "cloud" or c["model"] == cur_m:
                continue
            if c["model"] in _ban1:
                continue
            if brains.is_sick(c["backend"], c["model"]):
                continue
            try:
                txt = ask_specific(c["backend"], c["model"], messages,
                                   max_len=max_len)
                if txt.strip():
                    return txt
            except Exception as e:
                log.debug("служебный мозг %s не ответил: %s", c["model"], e)
                continue
    except Exception as e:
        log.debug("выбор служебного мозга не сложился: %s", e)
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
            from anamorf import capabilities as _caps
            _caps.note(model, "vision", True)
        except Exception:
            pass
    return text
