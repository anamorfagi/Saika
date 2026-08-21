"""Единый разбор ошибок подсистем + человеческие подсказки и авто-починка.

Идея: любая ошибка (STT/TTS/LLM/доктор) прогоняется через classify() — по
тексту определяем КАТЕГОРИЮ, отдаём объяснение простым языком («брат, у тебя
что-то с сетью…») и код рекомендуемого авто-действия. Так UI показывает не
сырой стек-трейс, а понятную причину и то, что Сайка уже делает сама.

Возвращаемая структура (dict):
  category : str   — loading / vram / noref / network / space / corrupt /
                     cuda / internal / offline / nomodel / absent / unknown
  human    : str   — что случилось, человеческим языком
  action   : str   — что Сайка делает автоматически прямо сейчас
  fix      : str|None — код авто-починки для менеджера:
                       "redownload"  снести битый кэш и качать заново
                       "pagefile"    подсказать про tools/fix_pagefile.bat
                       "switch"      просто уйти на запасной движок
                       "cpu"         откатиться на CPU
                       "wait"        ничего не чинить — процесс идёт сам
                       "download"    движок есть, весов нет — качать модель
                       "absent"      движка нет в этой сборке — чинить нечего
"""

import re

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

# 2026-08-21. Третий случай, который тоже нельзя звать поломкой: модуль
# на месте, а ВЕСОВ нет. Билд едет без моделей — их качают при первом
# запуске, — и движок без своего файла не поднимется никогда, сколько его
# ни переключай. Сообщение в логе было уже человеческим («Модель Vosk не
# найдена: …. Запусти setup/first_run.py»), но classify его не знал, и до
# глаз доходило «упал с незнакомой мне ошибкой» — та же беда, что описана
# выше про 2026-08-13: причина есть, а человек её не видит.
_NO_WEIGHTS = ("model not found", "first_run", "не скачана",
               "нет файла модели", "model path does not exist",
               "checkpoint not found", "weights not found")

def _looks_like_no_weights(t: str) -> bool:
    if _has(t, _NO_WEIGHTS):
        return True
    # «модель … не найдена» — два слова врозь, одним списком не поймать:
    # «не найдена» само по себе слишком общее и хватало бы чужое.
    return ("модел" in t) and ("не найден" in t)


# 2026-08-21. Клиентский билд собирается ПРОФИЛЕМ, и всё, что в профиль не
# вошло, физически отсутствует — импорт честно падает ModuleNotFoundError.
# Владелец открыл билд профиля base, увидел шесть движков слуха и пять
# голоса, все красные, у каждого «упал с незнакомой мне ошибкой», — и решил,
# что сломалась Сайка. Не сломалась: их там просто нет.
#
# Отсутствие и поломка — разные вещи, и называть их одним словом хуже, чем
# молчать: поломку идут чинить, а тут чинить нечего. Стоит ПОСЛЕ _CUDA
# намеренно: сбой драйвера NVIDIA часто выходит наружу тем же ImportError,
# и путать его с «не собрали» нельзя — там как раз есть что чинить.
_NO_MODULE = ("no module named", "modulenotfounderror",
              "cannot import name", "importerror",
              "не в этой сборке")


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
        # У КАЖДОГО ДВИЖКА СВОЙ АДРЕС (2026-08-14). Здесь во всех сетевых
        # бедах винился huggingface.co — и владелец справедливо не понимал,
        # при чём тут HF, когда «не заводится edge»: Edge-TTS ходит вообще
        # не туда, это сервис Microsoft. Неверный диагноз хуже отсутствия
        # диагноза: человек идёт чинить то, что не сломано.
        _where = {
            "edge": "сервис Microsoft (speech.platform.bing.com) недоступен "
                    "— он неофициальный и режется провайдерами чаще всего",
            "tts.edge": "сервис Microsoft (speech.platform.bing.com) "
                        "недоступен — он неофициальный и режется "
                        "провайдерами чаще всего",
        }.get(str(name), "huggingface.co не отвечает")
        return {
            "category": "network",
            "human": (f"Похоже, что-то с сетью, брат: «{name}» не "
                      f"работает — {_where}. Проверь интернет или VPN."),
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

    if _looks_like_no_weights(t):
        m = re.search(r"[:\s]([A-Za-z]:\\[^\s,;]+|/[^\s,;]+)", error or "")
        where = m.group(1) if m else ""
        try:
            from anamorf import features as _f
            built = _f.is_build()
        except Exception:
            built = False
        return {
            "category": "nomodel",
            "human": (f"У «{name}» нет файла модели"
                      + (f" — жду его тут: {where}" if where else "")
                      + ". Сам движок на месте, а весов рядом нет."),
            "action": ("беру движок, у которого файл есть; скачать этот — "
                       + ("билд едет без моделей, их надо один раз докачать"
                          if built else "python setup/first_run.py")),
            "fix": "download"}

    if _has(t, _NO_MODULE):
        m = re.search(r"no module named ['\"]?([\w.]+)", t)
        mod = m.group(1) if m else ""
        try:
            from anamorf import features as _f
            built = _f.is_build()
        except Exception:
            built = False
        if built:
            return {
                "category": "absent",
                "human": (f"«{name}» нет в этой сборке — движок не вошёл в "
                          f"профиль, которым собран билд"
                          + (f" (не хватает модуля «{mod}»)." if mod else ".")),
                "action": ("беру тот движок, что есть; чтобы появился этот — "
                           "нужен билд с этой фичой или докачиваемый блок"),
                "fix": "absent"}
        return {
            "category": "absent",
            "human": (f"«{name}» не установлен"
                      + (f": нет пакета «{mod}»." if mod else ".")),
            "action": ("беру тот движок, что есть; поставить — "
                       "python setup/install.py или docs по этой фиче"),
            "fix": "absent"}

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
