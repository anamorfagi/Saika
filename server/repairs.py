"""ЖУРНАЛ ПОЧИНОК: память Беймакса о том, что уже пробовали (2026-08-14).

ПРОСЬБА ВЛАДЕЛЬЦА:

    «сделай Беймаксу понимание, что он работает по сути совместно с тобой,
     и нежелательно ломать или сильно пересобирать логику. если он
     конкретно увидит большое количество удачных запусков до этого, логи,
     как решались проблемы, — чтобы он хотя бы брал это во внимание и с
     пониманием дела и нашего проекта подходил к задаче»

ПОЧЕМУ ЭТО ВАЖНО, А НЕ КРАСИВО. Беймакс просыпается ровно в тот момент,
когда всё плохо: сервер упал, что-то не встало. Из этой точки система
выглядит сломанной ЦЕЛИКОМ — и соблазн «пересобрать» максимальный. Но
факты обычно ровно обратные: до этого были сотни здоровых запусков, а
сломалось что-то одно и недавно. Знание «двести раз поднималась нормально»
превращает диагноз из «тут всё гнилое» в «что изменилось за последние
сутки» — а это совсем другая, куда более дешёвая починка.

ТРИ ВЕЩИ, КОТОРЫЕ ЗДЕСЬ ХРАНЯТСЯ:
  1. сколько раз система поднималась ЗДОРОВОЙ (и когда в последний раз);
  2. что уже чинили: симптом -> действие -> помогло или нет;
  3. чем чиним сейчас — чтобы на следующем старте отметить, помогло ли.

Отсюда же главное правило самого Беймакса: если его прошлое лечение НЕ
помогло, повторять его нельзя — надо идти другим путём. Ровно то же
правило, что у агентного цикла (server/agent.py) и у памяти цепочек
(server/recipes.py): не ломиться дважды в одну дверь.
"""
from __future__ import annotations

import json
import time

from server.config import ROOT

PATH = ROOT / "data" / "repairs.json"
MAX = 60


def _load() -> dict:
    try:
        d = json.loads(PATH.read_text("utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d: dict):
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except Exception:
        pass


def note_healthy():
    """Система поднялась и работает. Зовётся, когда автопуск дошёл до конца."""
    d = _load()
    d["healthy"] = int(d.get("healthy", 0)) + 1
    d["last_healthy"] = time.time()
    d["streak"] = int(d.get("streak", 0)) + 1
    # прошлое лечение дожило до здорового запуска — значит помогло
    fixes = d.setdefault("fixes", [])
    if fixes and fixes[0].get("worked") is None:
        fixes[0]["worked"] = True
    _save(d)


def note_crash():
    d = _load()
    d["crashes"] = int(d.get("crashes", 0)) + 1
    d["streak"] = 0
    fixes = d.setdefault("fixes", [])
    # упали ПОСЛЕ лечения — значит оно не помогло
    if fixes and fixes[0].get("worked") is None:
        fixes[0]["worked"] = False
    _save(d)


def note_fix(symptom: str, action: str):
    """Беймакс что-то починил. Помогло или нет — узнаем на следующем старте."""
    d = _load()
    fixes = d.setdefault("fixes", [])
    fixes.insert(0, {"symptom": (symptom or "")[:200],
                     "action": (action or "")[:300],
                     "ts": time.time(), "worked": None})
    del fixes[MAX:]
    _save(d)


def tried_before(symptom: str) -> list:
    """Что уже пробовали против этого симптома. Самое свежее первым."""
    key = (symptom or "").lower()[:60]
    out = []
    for f in _load().get("fixes", []):
        if key and key[:24] in (f.get("symptom", "") or "").lower():
            out.append(f)
    return out


def summary() -> dict:
    d = _load()
    return {"healthy": int(d.get("healthy", 0)),
            "crashes": int(d.get("crashes", 0)),
            "streak": int(d.get("streak", 0)),
            "fixes": (d.get("fixes") or [])[:8]}


def block() -> str:
    """История проекта словами — для промпта умного доктора.

    Это не украшение: без неё модель, разбуженная в момент падения, видит
    только падение и предлагает переделать архитектуру."""
    s = summary()
    lines = []
    if s["healthy"]:
        lines.append(
            f"ИСТОРИЯ ЭТОЙ МАШИНЫ: система поднималась здоровой "
            f"{s['healthy']} раз(а), падений {s['crashes']}. "
            + (f"Прямо перед этим было {s['streak']} здоровых запусков "
               "подряд — значит сломалось что-то ОДНО и НЕДАВНО, а не "
               "«всё плохо»." if s["streak"] else
               "Последние запуски были неудачными подряд."))
    if s["fixes"]:
        lines.append("ЧТО УЖЕ ЧИНИЛИ (и чем это кончилось):")
        for f in s["fixes"]:
            mark = ("помогло" if f.get("worked") is True
                    else "НЕ помогло" if f.get("worked") is False
                    else "результат пока неизвестен")
            lines.append(f"- {f.get('symptom', '')} -> "
                         f"{f.get('action', '')} [{mark}]")
        lines.append("То, что помечено «НЕ помогло», ПОВТОРЯТЬ НЕЛЬЗЯ — "
                     "ищи другой путь.")
    return "\n".join(lines)
