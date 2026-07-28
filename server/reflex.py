"""РЕФЛЕКСЫ: действия, исполняемые ДО модели (2026-07-27).

ЗАЧЕМ. LLM-путь дожат до ~0.6с, и его потолок на этом железе ~0.3-0.4с —
физика мелких партий prefill. Но у живого существа часть реакций вообще не
проходит через «подумать»: одёрнуть руку — спинной мозг, а не кора. Здесь
то же самое: «закрой браузер», «громче», «сверни всё» — фраза распознаётся
регексом за долю миллисекунды, действие исполняется СРАЗУ (< 50 мс), а
Сайка комментирует уже сделанное — вдогонку, своими словами.

ФИЛОСОФИЯ (важно, см. PHILOSOPHY.md). Рефлекс НЕ вкладывает ей реплики —
готовых фраз тут нет. Он исполняет ДЕЙСТВИЕ, а факт «уже сделано» уезжает
в промпт, и она реагирует сама. Разница с обычным tool-call только в том,
КОГДА исполнено: до её ответа, а не в середине.

БЕЗОПАСНОСТЬ. Рефлекс идёт через тот же tools.call, что и вызовы модели, —
со всеми предохранителями (_intent_ok, trust). Сюда попадают только команды
с однозначным разбором аргументов; всё, где нужно ДУМАТЬ (пути, поиск,
«открой ту штуку, что вчера»), — не рефлекс, пусть решает модель.
"""
import logging
import re

from server.config import CFG

log = logging.getLogger("saika.reflex")

# (регекс, имя инструмента, разбор аргументов из match)
# Порядок важен: первое совпадение выигрывает.
_RULES = [
    # глаза: включить/выключить своё зрение — мгновенно
    (re.compile(r"\b(?:включи|открой)\s+(?:сво\w+\s+)?(?:глаза|зрение)\b", re.I),
     "eyes", lambda m: {"on": True}),
    (re.compile(r"\b(?:выключи|закрой)\s+(?:сво\w+\s+)?(?:глаза|зрение)\b", re.I),
     "eyes", lambda m: {"on": False}),
    # проводник: «открой проводник» = ОТКРЫТЬ НОВОЕ окно рабочей папки
    # (2026-07-28, просьба владельца: не «он уже открыт», а сделать)
    (re.compile(r"\b(?:открой|запусти|покажи)\s+(?:мне\s+)?проводник\b", re.I),
     "open_folder", lambda m: {}),
    # браузер Сайки
    (re.compile(r"\bзакрой\s+(свой\s+)?браузер\b", re.I),
     "close_browser", lambda m: {}),
    # все окна
    (re.compile(r"\bсверни\s+вс[её]\b", re.I),
     "minimize_all", lambda m: {}),
    # громкость: процент
    (re.compile(r"\bгромкость\s*(?:на\s*)?(\d{1,3})\s*%?", re.I),
     "volume_set", lambda m: {"percent": max(0, min(100, int(m.group(1))))}),
    # громче/тише (шаг из конфига)
    (re.compile(r"\b(по)?громче\b", re.I),
     "volume_set", lambda m: {"delta": int(CFG.get("reflex.volume_step", 10))}),
    (re.compile(r"\b(по)?тише\b", re.I),
     "volume_set", lambda m: {"delta": -int(CFG.get("reflex.volume_step", 10))}),
    (re.compile(r"\bвыключи\s+звук\b|\bзаглуши\b", re.I),
     "volume_set", lambda m: {"mute": True}),
    (re.compile(r"\bвключи\s+звук\b", re.I),
     "volume_set", lambda m: {"mute": False}),
    # вкладки
    (re.compile(r"\bзакрой\s+вкладку\b", re.I),
     "tab_control", lambda m: {"action": "close"}),
    (re.compile(r"\b(следующ\w+|дальше)\s+вкладк\w*\b|\bвкладку\s+вперёд\b", re.I),
     "tab_control", lambda m: {"action": "next"}),
    # запуск программы: только «запусти/открой <одно слово>», без путей и
    # уточнений — многословное пусть разбирает модель
    (re.compile(r"^(?:сайка[,!\s]*)?(?:запусти|открой)\s+([a-zа-яё0-9._-]{2,20})\s*$",
                re.I),
     "app_launch", lambda m: {"name": m.group(1)}),
]

# слова, при которых «открой X» — НЕ запуск программы (папки/файлы/страницы
# требуют решений — это работа модели, не спинного мозга)
_NOT_APPS = {"папку", "файл", "сайт", "страницу", "ссылку", "глаза",
             "окно", "настройки", "доску", "память"}


# СВОИ РЕФЛЕКСЫ ИЗ КОНФИГА (2026-07-28): владелец добавляет правила без
# правки кода — reflex.extra в config.json:
#   [{"pattern": "стрим-режим", "tool": "minimize_all", "args": {}}]
# pattern — регекс по фразе, tool — любой из списка инструментов.
_extra_cache = {"src": None, "rules": []}


def _extra_rules():
    src = CFG.get("reflex.extra", []) or []
    if _extra_cache["src"] == src:
        return _extra_cache["rules"]
    rules = []
    for r in src:
        try:
            rules.append((re.compile(r["pattern"], re.I), r["tool"],
                          dict(r.get("args") or {})))
        except Exception as e:
            log.warning("рефлекс из конфига не собрался (%s): %s", r, e)
    _extra_cache.update(src=src, rules=rules)
    return rules


# ЦЕПОЧКИ КОМАНД (2026-07-28, практика Talon: команды идут связками без
# пауз). «Сверни всё и открой проводник» раньше уходило модели целиком —
# теперь фраза режется по связкам « и / потом / затем / а после », и если
# КАЖДЫЙ кусок — рефлекс, исполняется вся цепочка (до 3 действий). Если
# хоть один кусок рефлексом не ловится — вся фраза уходит модели, как
# раньше: полкоманды делать хуже, чем не делать вовсе.
_CHAIN_SPLIT = re.compile(r"\s*(?:,\s*)?(?:\bи\b|\bпотом\b|\bзатем\b|"
                          r"\bа после\b|\bпосле этого\b)\s+", re.I)


def match_chain(user_text: str) -> list:
    """[(имя, аргументы), ...] если ВСЯ фраза — цепочка рефлексов, иначе []."""
    t = (user_text or "").strip()
    if not t or len(t) > 120:
        return []
    parts = [p.strip() for p in _CHAIN_SPLIT.split(t) if p.strip()]
    if len(parts) < 2 or len(parts) > 3:
        return []
    hits = [match(p) for p in parts]
    return hits if all(hits) else []


def match(user_text: str):
    """None или (имя_инструмента, аргументы). Стоит доли миллисекунды."""
    if not CFG.get("reflex.enabled", True):
        return None
    t = (user_text or "").strip()
    if not t or len(t) > 60:          # длинная фраза = контекст, пусть думает
        return None
    for rx, name, args in _extra_rules():   # правила владельца — первыми
        if rx.search(t):
            return name, args
    for rx, name, args_fn in _RULES:
        m = rx.search(t)
        if not m:
            continue
        if name == "app_launch" and m.group(1).lower() in _NOT_APPS:
            continue
        try:
            return name, args_fn(m)
        except Exception as e:
            log.debug("рефлекс %s не разобрал аргументы: %s", name, e)
    return None


def execute(hit, user_text: str) -> str:
    """Исполняет рефлекс через штатный tools.call (со всеми
    предохранителями). Возвращает результат для вставки в промпт."""
    name, args = hit
    from server.llm import tools as _tls
    _tls.LAST_USER["text"] = user_text     # предохранитель намерения
    res = _tls.call(name, args)
    log.info("Рефлекс: %s(%s) -> %s", name, args, str(res)[:120])
    return str(res or "сделано")
