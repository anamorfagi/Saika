"""СБОРКА ПРОМПТА ЯДРА v2 — порядок решает скорость.

    [system: характер + правила рук + ядро памяти + указатель инструментов]  ← не меняется в сеансе
    [история: user/assistant ...]                                            ← только дописывается
    [system: факты хода — время и т.п., пара строк]                          ← меняется каждый ход
    [user: реплика]

Всё до «фактов хода» совпадает с прошлым ходом байт в байт, поэтому
llama.cpp пересчитывает только хвост (~100–300 токенов ≈ 0.3–0.8 с).
История держится ЯКОРЕМ: окно не скользит каждый ход (это ломало бы
префикс), а когда переполнилось — прыгает вперёд один раз, оставляя
свежие 60 %.
"""
import time

from anamorf.config import CFG
from anamorf.core import persona, registry

_ANCHOR = {"ts": 0.0}
_CORE_MEM = {"text": "", "ts": 0.0}
_WEEK = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def _budget_chars() -> int:
    # 32k окна, ~2.4 символа на токен у Qwen3.6, минус система и ответ
    return int(CFG.get("core.history_chars", 24000))


def core_memory() -> str:
    """Короткое «что я знаю о Витале» — ОДИН РАЗ НА СЕАНС.

    Стенд v2g, 09.10: кэш держался только для непустого текста и «раз в
    час»; memory_about то падал в пустоту, то менялся по мере роста базы —
    системный промпт мигал (хэш b5079d49 → 46f34310 → b5c6fa46), и каждый
    раз движок пересчитывал весь разговор: 8–12 с на «решение». Теперь
    снимок берётся при первом ходе и меняется только при reset() — или
    когда стенограмма и так обрезается (_trim), т.е. кэш всё равно ломается.
    """
    if _CORE_MEM["ts"]:
        return _CORE_MEM["text"]
    try:
        from anamorf.llm import tools as _t
        txt = str(_t._call("memory_about", {}) or "")
        if txt.lower().startswith(("отказ", "ошибка", "не ")):
            txt = ""
    except Exception:
        txt = ""
    _CORE_MEM.update(text=txt[:1500], ts=time.time())
    return _CORE_MEM["text"]


def system_text(owner_name: str) -> str:
    return (persona.system_prompt(owner_name, core_memory()) + "\n\n"
            + registry.index_text())


# ── СТЕНОГРАММА СЕАНСА (как у агента Claude) ──────────────────────────
# Разговор — это СВОЙ список сообщений ядра, а не выборка из базы: в нём
# лежат и вызовы инструментов, и их результаты. Почему это важно (стенд
# 09.10, 18:00): в базе хранятся только тексты, и модель видела в истории
# «Открыла YouTube» БЕЗ вызова — и начинала так же «открывать» словами.
# Здесь же каждое «открыла» стоит рядом с настоящим вызовом и результатом,
# и модель учится на правде. Плюс список только дописывается — префикс
# промпта совпадает байт в байт, кэш движка живёт.
# База (memory.add_event) по-прежнему получает тексты для долгой памяти.
import json as _json
import os as _os

_SESSION = {"msgs": None}


def _sess_path() -> str:
    from anamorf.config import resolve
    return str(resolve("data/core_session.jsonl"))


def _load() -> list:
    if _SESSION["msgs"] is not None:
        return _SESSION["msgs"]
    since = float(CFG.get("core.history_since", 0) or 0)
    out = []
    try:
        with open(_sess_path(), encoding="utf-8") as f:
            for ln in f:
                try:
                    r = _json.loads(ln)
                except Exception:
                    continue
                if float(r.get("ts", 0)) >= since:
                    out.append(r["m"])
    except FileNotFoundError:
        pass
    _SESSION["msgs"] = out
    return out


def _trim(msgs: list) -> list:
    """Переполнилось — отрезаем старые 40 % по границе реплики человека."""
    budget = _budget_chars()
    size = lambda m: len(str(m.get("content", ""))) + len(_json.dumps(m.get("tool_calls", "")))
    if sum(size(m) for m in msgs) <= budget:
        return msgs
    acc, cut = 0, 0
    for i, m in enumerate(msgs):
        acc += size(m)
        if acc > budget * 0.4 and m.get("role") == "user":
            cut = i
            break
    return msgs[cut:]


def history(memory=None, person_id: str = "") -> list:
    msgs = _load()
    t = _trim(msgs)
    if t is not msgs:
        _SESSION["msgs"] = t
        _CORE_MEM["ts"] = 0.0      # кэш всё равно сломан — освежим и память
    return list(_SESSION["msgs"])


def commit(user_msg: dict, new_msgs: list):
    """Дописать ход в стенограмму (результаты инструментов — коротко)."""
    msgs = _load()
    add = [user_msg]
    for m in new_msgs:
        m = dict(m)
        if m.get("role") == "tool":
            m["content"] = str(m.get("content", ""))[:1500]   # ровно как ушло в модель
        add.append(m)
    msgs.extend(add)
    try:
        import time as _t
        with open(_sess_path(), "a", encoding="utf-8") as f:
            for m in add:
                f.write(_json.dumps({"ts": _t.time(), "m": m}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def turn_facts() -> str:
    t = time.localtime()
    return (f"Факты хода: сейчас {t.tm_hour:02d}:{t.tm_min:02d}, "
            f"{_WEEK[t.tm_wday]}, {t.tm_mday:02d}.{t.tm_mon:02d}.{t.tm_year}.")


def build(memory, person_id: str, owner_name: str, user_text: str):
    """-> (messages, user_msg). user_msg кладётся в стенограмму ровно таким,
    каким ушёл в модель: следующий ход совпадёт с этим префиксом байт в байт."""
    msgs = [{"role": "system", "content": system_text(owner_name)}]
    msgs += history()
    user_msg = {"role": "user", "content": f"({turn_facts()})\n{user_text}"}
    msgs.append(user_msg)
    return msgs, user_msg


def reset():
    """Новый разговор ядра: стенограмма с чистого листа (долгая память цела).
    Через CFG.set — иначе работающая Сайка перезапишет config.json своим."""
    import time as _t
    CFG.set("core.history_since", _t.time())
    _SESSION["msgs"] = []
    _ANCHOR["ts"] = 0.0
    _CORE_MEM["ts"] = 0.0
