"""Единый разбор ошибок подсистем + человеческие подсказки и авто-починка.

Идея: любая ошибка (STT/TTS/LLM/доктор) прогоняется через classify() — по
тексту определяем КАТЕГОРИЮ, отдаём объяснение простым языком («брат, у тебя
что-то с сетью…») и код рекомендуемого авто-действия. Так UI показывает не
сырой стек-трейс, а понятную причину и то, что Сайка уже делает сама.

Возвращаемая структура (dict):
  category : str   — loading / vram / noref / network / space / corrupt /
                     cuda / internal / offline / unknown
  human    : str   — что случилось, человеческим языком
  action   : str   — что Сайка делает автоматически прямо сейчас
  fix      : str|None — код авто-починки для менеджера:
                       "redownload"  снести битый кэш и качать заново
                       "pagefile"    подсказать про tools/fix_pagefile.bat
                       "switch"      просто уйти на запасной движок
                       "cpu"         откатиться на CPU
                       "wait"        ничего не чинить — процесс идёт сам
"""

# каждая запись: (список сигнатур в тексте ошибки, функция-строитель ответа)
# порядок важен — более специфичные категории идут раньше общих.

# 2026-07-23: «модель ещё грузится» — НЕ поломка. Раньше долгую первую
# закачку Voxtral (~9 ГБ) принимали за network-смерть и перезапускали
# воркер по кругу (падал о занятый порт, «код 3»).
_LOADING = ("ещё загружается", "модель ещё грузится", "первая закачка",
            "still loading", "model is loading", "воркер живой")

# 2026-08-13. Обе причины уже писались в лог ПОЛНЫМ человеческим текстом, но
# classify их не знал — и владелец видел «упал с незнакомой мне ошибкой» ×92,
# то есть худшее из двух: причина есть, а до глаз не доходит.
_VRAM_BUSY = ("не хватает видеопамяти", "занята моей же llm",
              "для клон-голоса")

_NO_REF = ("нет референса голоса", "voice_ref_wav", "voice_ref_text",
           "нет wav или транскрипта")

_NETWORK = ("read timed out", "readtimeout", "read timeout", "max retries",
            "httpsconnectionpool", "connectionerror", "getaddrinfo",
            "failed to resolve", "name or service not known",
            "temporarily unavailable", "network is unreachable",
            "connection aborted", "connection reset", "proxy", "ssl",
            # «connection timeout» (без пробела в timed/out) — формулировка
            # aiohttp у edge-tts: в логе 2026-08-13 она уходила в unknown,
            # хотя это буквально «нет сети»
            "connection timeout", "timeout to host", "cannot connect to host",
            "timed out", "no route to host")

_SPACE = ("not enough space", "os error 1455", "error 1455", "paging file",
          "файл подкачки", "cannot allocate", "hugemalloc", "errno 28",
          "no space left", "memoryerror", "bad allocation",
          "cannot reserve", "cudamalloc", "out of memory", "oom")

_CORRUPT = ("checksum", "corrupt", "unexpected eof", "invalid load key",
            "sha256 mismatch", "bad magic", "cannot read model",
            "unpickling", "truncated")

_CUDA = ("cublas", "cudnn", "no kernel image", "device-side assert",
         "cuda error", "cuda driver", ".dll is not found", ".pyd",
         "could not load this library", "nvrtc")

_INTERNAL = ("audio_chunk", "shape of", "must be (", "expected shape",
             "size mismatch", "dimension")

_OFFLINE = ("offline mode", "local_files_only", "hf_hub_offline",
            "can't load", "couldn't find", "is not a local folder")


def _has(text, sigs):
    return any(s in text for s in sigs)


def classify(component: str, error: str) -> dict:
    """component — напр. 'stt.tone' или 'tts.qwen3'; error — текст ошибки."""
    t = (error or "").lower()
    name = component.split(".")[-1] if component else "движок"

    # порядок: loading раньше всех (это вообще не ошибка), сеть перед space
    # (таймаут HF важнее, чем «не хватило места» где-то в тексте),
    # corrupt перед offline, cuda отдельно.
    if _has(t, _LOADING):
        return {
            "category": "loading",
            "human": (f"«{name}» ещё загружает модель — первая закачка "
                      "большая и может идти десятки минут."),
            "action": ("работаю на запасном движке; воркер докачает сам, "
                       "и я вернусь на него автоматически"),
            "fix": "wait"}

    # порядок: обе новые причины ДО network — в их тексте встречается
    # «ssl»/«timed out» из чужих сигнатур не может, но специфичное всегда
    # раньше общего, иначе следующая правка _NETWORK молча их перехватит
    if _has(t, _NO_REF):
        return {
            "category": "noref",
            "human": (f"«{name}» не нашёл образец моего голоса по пути из "
                      "config.json (tts.voice_ref_wav). Сам файл может лежать "
                      "на месте — не сходится путь."),
            "action": ("проверь tts.voice_ref_wav в config.json — он должен "
                       "быть ОТНОСИТЕЛЬНЫМ (voice/ref.wav), иначе после "
                       "переезда или git pull с другого ПК он указывает в "
                       "чужую папку; пока говорю запасным движком"),
            "fix": "switch"}

    if _has(t, _VRAM_BUSY):
        return {
            "category": "vram",
            "human": (f"На «{name}» не осталось видеопамяти — её занимает моя "
                      "же LLM. Это не поломка движка, а очередь за одной "
                      "видеокартой."),
            "action": ("возьми модель полегче, урежь llamacpp.n_ctx или "
                       "выгрузи текущую кнопкой 🧹 — после этого клон-голос "
                       "поднимется; пока говорю запасным движком"),
            "fix": "switch"}

    if _has(t, _NETWORK):
        return {
            "category": "network",
            "human": (f"Похоже, что-то с сетью, брат: «{name}» не скачивается — "
                      "huggingface.co не отвечает. Проверь интернет или VPN."),
            "action": ("переключаюсь на рабочий движок; как появится сеть — "
                       "докачаю модель сама"),
            "fix": "switch"}

    if _has(t, _SPACE):
        return {
            "category": "space",
            "human": (f"Не хватило памяти/файла подкачки, чтобы поднять «{name}». "
                      "Чаще всего — маленький файл подкачки Windows."),
            "action": ("запусти tools/fix_pagefile.bat (один раз, от админа) — "
                       "он увеличит подкачку; пока беру лёгкий движок"),
            "fix": "pagefile"}

    if _has(t, _CORRUPT):
        return {
            "category": "corrupt",
            "human": f"Файл модели «{name}» скачался битым (не сошлась проверка).",
            "action": "удаляю битый файл и качаю заново автоматически",
            "fix": "redownload"}

    if _has(t, _CUDA):
        return {
            "category": "cuda",
            "human": (f"Спотыкается о видеокарту/CUDA при загрузке «{name}» — "
                      "драйвер NVIDIA или несовместимые библиотеки."),
            "action": ("падаю на CPU/запасной движок; если повторяется — "
                       "запусти setup/doctor.py --fix и проверь драйвер NVIDIA"),
            "fix": "cpu"}

    if _has(t, _INTERNAL):
        return {
            "category": "internal",
            "human": (f"«{name}» получил данные не того формата — это моя "
                      "внутренняя несовместимость, не твоя вина."),
            "action": "переключаюсь на другой движок, чиню в фоне",
            "fix": "switch"}

    if _has(t, _OFFLINE):
        return {
            "category": "offline",
            "human": (f"Я в офлайн-режиме, а модели «{name}» ещё нет локально — "
                      "её нужно один раз скачать при интернете."),
            "action": "пока беру уже установленный движок",
            "fix": "switch"}

    return {
        "category": "unknown",
        "human": f"«{name}» упал с незнакомой мне ошибкой.",
        "action": ("переключаюсь на запасной движок; подробности — "
                   "в logs/saika.log"),
        "fix": "switch"}


def short(component: str, error: str) -> str:
    """Однострочник для UI: «причина — что делаю»."""
    d = classify(component, error)
    return f"{d['human']} {d['action']}"


# ---------------------- Беймакс: оценка здоровья 1..10 ----------------------
# «Привет, я Беймакс, твой персональный помощник по здоровью». Оценивает
# каждый модуль по шкале 1..10 и прописывает лечение.

# сломанному модулю оценка зависит от категории причины (что-то лечится легко,
# что-то — глубокая проблема)
_BROKEN_SCORE = {"loading": 6, "corrupt": 4, "network": 4, "offline": 4,
                 # noref/vram чинятся одной строкой в конфиге и кнопкой —
                 # это не «глубоко сломано», а «не настроено под эту машину»
                 "noref": 5, "vram": 5,
                 "internal": 3, "space": 3, "cuda": 2, "unknown": 2}


def assess(component: str, health: str, loaded, is_current: bool,
           diag: dict | None = None) -> dict:
    """Оценка одного модуля.
    health: 'ok'|'broken'|'unknown'; loaded: True|False|None(онлайн).
    Возвращает {score:1..10, verdict:str, treatment:str}."""
    if health == "broken":
        cat = (diag or {}).get("category", "unknown")
        score = _BROKEN_SCORE.get(cat, 2)
        treat = (diag or {}).get("action") or "смотри logs/saika.log"
        human = (diag or {}).get("human", "")
        verdict = "не работает" + (f": {human}" if human else "")
        return {"score": score, "verdict": verdict, "treatment": treat}

    if health == "ok" or loaded:
        if loaded is None:                       # онлайн-сервис (edge-tts)
            return {"score": 8, "verdict": "онлайн, готов",
                    "treatment": "нужен интернет во время работы"}
        if is_current and loaded:
            return {"score": 10, "verdict": "активен, в памяти, работает",
                    "treatment": ""}
        if loaded:
            return {"score": 9, "verdict": "загружен, готов",
                    "treatment": ""}
        return {"score": 7, "verdict": "исправен, но не в памяти",
                "treatment": "загрузится при первом использовании (кнопка ⬇ "
                             "— сразу)"}

    # ещё ни разу не пробовали — состояние неизвестно
    return {"score": 5, "verdict": "не проверялся",
            "treatment": "выбери его или нажми ⬇, чтобы Беймакс проверил"}
