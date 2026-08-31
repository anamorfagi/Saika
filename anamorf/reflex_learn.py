"""РЕФЛЕКСЫ, КОТОРЫЕ ОНА ВЫУЧИВАЕТ САМА (2026-08-23).

Владелец: «мы сейчас работаем над рефлекторными командами, которые
нейронка должна учиться понимать: что она уже имеет и какие должны у неё
появляться в результате работы с человеком».

КАК УСТРОЕНО. Каждая фраза, доехавшая до инструмента ЧЕРЕЗ раздумья LLM
(см. _rec_reflex_miss в llm/manager.py), попадает сюда. Мы считаем, как
часто ОДНА И ТА ЖЕ фраза приводит к ОДНОМУ И ТОМУ ЖЕ вызову. Совпало
learn_after раз (по умолчанию 2) — фраза становится выученным рефлексом:
следующий раз она исполнится мгновенно, мимо модели.

ЗАЩИТА — ГЛАВНАЯ ЧАСТЬ, А НЕ ПРИЛОЖЕНИЕ. Владелец: «не забудь про
защиту, где нейронка по какой-то причине закидывала написание; предположи
возможные кривые отработки». Кривые пути, которые мы закрываем:

  1. МОДЕЛЬ ВЫДУМАЛА ВЫЗОВ. Она уже писала [медиа_контрол:...] и
     рапортовала об успехе. Если такое заучить — выдумка станет
     мгновенной. Поэтому учимся ТОЛЬКО на вызовах, которые реально
     исполнились без ошибки (об этом говорит вызывающий код).
  2. ОПАСНЫЙ ИНСТРУМЕНТ. «Выключи компьютер» нельзя делать рефлексом:
     цена ложного срабатывания — потерянная работа. Берём только
     инструменты с риском ≤ 2 по trust.py (открыть, показать, громкость,
     пульт) и отдельный чёрный список сверх того.
  3. СЛУЧАЙНАЯ ФРАЗА. «Ну давай посмотрим» может один раз привести к
     look_screen — это разговор, а не команда. Лечится порогом
     повторений: случайность не повторяется с тем же вызовом.
  4. ПЕРЕОБОБЩЕНИЕ. Выученное — это ТОЧНАЯ фраза (после нормализации),
     а не регулярка: «включи свет» не должно ловить «включи светомузыку».
     Обобщать — работа человека или большой модели, не счётчика.
  5. ДЛИННАЯ РЕЧЬ. Фразы длиннее 60 символов не заучиваем: там контекст,
     и он в другой день может значить другое.
  6. ЭХО ИЗ КОЛОНОК. Если фраза совпадает с тем, что она сама только что
     говорила, — не учимся (remember_said/эхо режется раньше, но пояс
     безопасности лишним не бывает).

Всё выученное лежит в data/reflex_learned.json — человекочитаемо, каждое
правило можно стереть руками. О каждом новом рефлексе она говорит вслух:
молча выросшая привычка — это сюрприз, а сюрпризов у рук быть не должно.
"""
import json
import logging
import re
import threading
import time

from anamorf.config import CFG, resolve

log = logging.getLogger("saika.reflex_learn")

_lock = threading.Lock()
_cache = {"rules": None, "mtime": 0.0}

# риск выше этого не заучиваем никогда (шкала trust.py: 2 = обратимо одним
# движением)
MAX_RISK = 2
# и отдельный чёрный список: даже «безопасное» из этого списка требует
# головы, а не спинного мозга
NEVER = {"fs_delete", "fs_write", "fs_move", "fs_rename", "proc_kill",
         "pc_shutdown", "shutdown_self", "close_browser", "window_close",
         "minimize_all", "web_open", "web_search", "app_launch"}


def _path():
    return resolve("data") / "reflex_learned.json"


def _norm(text: str) -> str:
    """Нормализация фразы: регистр, мусор, «сайка» в начале.

    Ровно та же фраза, сказанная чуть иначе, должна совпасть; другая —
    нет. Поэтому только бесспорное: пунктуация и обращение."""
    t = (text or "").strip().lower()
    t = re.sub(r"^(?:сайка|сайк)[,!\s]+", "", t)
    t = re.sub(r"[.!?,]+$", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _load() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except Exception:
        return {"pending": {}, "learned": {}}


def _save(d: dict):
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                 encoding="utf-8")


def _risk_of(tool: str) -> int:
    try:
        from anamorf import trust
        return int(trust.RISK.get(tool, 5))
    except Exception:
        return 5


def consider(text: str, tool: str, args: dict, succeeded: bool) -> str:
    """Учесть один вызов, случившийся через LLM. Вернёт фразу-отчёт, если
    прямо сейчас родился новый рефлекс (чтобы сказать вслух), иначе ''."""
    if not succeeded:
        return ""                      # защита 1: на выдумках не учимся
    t = _norm(text)
    if not t or len(t) > 60:
        return ""                      # защита 5: длинное — это контекст
    if tool in NEVER or _risk_of(tool) > MAX_RISK:
        return ""                      # защита 2: опасное — только головой
    try:
        from anamorf import reflex
        if reflex.match(text):
            return ""                  # уже рефлекс — учить нечему
    except Exception:
        pass
    try:                               # защита 6: не её ли это эхо
        from anamorf.main import was_said_recently
        if was_said_recently(text):
            return ""
    except Exception:
        pass

    thr = int(CFG.get("reflex.learn_after", 2))
    key = t
    sig = json.dumps({"tool": tool, "args": args}, ensure_ascii=False,
                     sort_keys=True)
    with _lock:
        d = _load()
        if key in d["learned"]:
            return ""
        row = d["pending"].get(key)
        if row and row.get("sig") == sig:
            row["n"] = int(row.get("n", 1)) + 1
            row["ts"] = time.time()
        else:
            # защита 3: другой вызов на ту же фразу обнуляет счёт —
            # неоднозначная фраза рефлексом быть не может
            row = {"sig": sig, "n": 1, "ts": time.time()}
        d["pending"][key] = row
        born = ""
        if row["n"] >= thr:
            d["learned"][key] = {"tool": tool, "args": args,
                                 "n": row["n"], "born": time.time()}
            del d["pending"][key]
            _cache["rules"] = None
            born = (f"Выучила команду: «{t}» теперь делаю сразу "
                    f"({tool}). Разучить: «забудь команду {t}».")
            log.info("Новый выученный рефлекс: %r -> %s %s", t, tool, args)
        # чистка: незакреплённое старше недели забываем
        cut = time.time() - 7 * 24 * 3600
        d["pending"] = {k: v for k, v in d["pending"].items()
                        if v.get("ts", 0) > cut}
        _save(d)
    return born


def lookup(text: str):
    """None или (tool, args) — выученный рефлекс для точной фразы."""
    if not CFG.get("reflex.learn", True):
        return None
    t = _norm(text)
    if not t:
        return None
    with _lock:
        rules = _cache["rules"]
        if rules is None:
            rules = _cache["rules"] = _load().get("learned", {})
    row = rules.get(t)
    if not row:
        return None
    # защита на каждом срабатывании, не только при заучивании: правила
    # риска могли ужесточиться после того, как рефлекс был выучен
    if row["tool"] in NEVER or _risk_of(row["tool"]) > MAX_RISK:
        return None
    return row["tool"], dict(row.get("args") or {})


def forget(text: str) -> str:
    """«Забудь команду …» — стереть выученное руками."""
    t = _norm(re.sub(r"^забудь\s+команду\s+", "", _norm(text)))
    with _lock:
        d = _load()
        if t in d.get("learned", {}):
            del d["learned"][t]
            _save(d)
            _cache["rules"] = None
            return f"забыла команду «{t}»"
        return f"такой выученной команды нет: «{t}»"


def report() -> str:
    d = _load()
    if not d.get("learned"):
        return "выученных команд пока нет"
    rows = [f"«{k}» → {v['tool']}" for k, v in d["learned"].items()]
    return "выучено: " + "; ".join(rows[:20])
