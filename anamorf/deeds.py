"""ЖУРНАЛ ДЕЛ: что получилось, что нет и почему (05.09.2026).

Владелец: «как она проверяет выполненное действие, если оно не было
выполнено по запросу; как она записывает это себе в журнал, что не
получилось и как получилось, чтобы она могла учиться на ошибках и в
следующий раз моментально выполнять».

═══ ЧЕГО НЕ ХВАТАЛО ═══

Учёба у неё была ОДНОСТОРОННЯЯ. `reflex_learn` считает совпадения «фраза
→ тот же вызов» и после второго раза делает фразу мгновенным рефлексом —
но только на УДАЧАХ. Провал просто не засчитывался: он не записывался
никуда и через минуту переставал существовать. Поэтому одна и та же
ошибка повторялась бесконечно, и со стороны это выглядело как «она не
учится вообще».

Здесь вторая половина: провалы тоже помнятся, и помнятся ИМЕННО так,
чтобы из них можно было что-то сделать — с фразой, вызовом, причиной
отказа и тем, что в итоге сработало.

═══ ПОЧЕМУ НЕ ПРОСТО «СЧЁТЧИК ОШИБОК» ═══

Счётчик отвечает «сколько раз не вышло». Это бесполезное знание: оно не
меняет следующего действия. Полезное знание отвечает на другой вопрос —
«что вместо этого сработало в прошлый раз». Поэтому запись хранит пару:
чем пробовала и чем получилось. Одной строкой в промпте это превращается
в подсказку, которая экономит целый неудачный ход.

═══ ЧЕГО ЖУРНАЛ НЕ ДЕЛАЕТ ═══

Не решает за модель. Подсказка идёт в промпт как наблюдение о прошлом
(«в прошлый раз на эту фразу окно по имени не нашлось, помог список
окон»), а не как приказ. Разница принципиальная: приказ превращает
единичную случайность в правило и ломает работу там, где в прошлый раз
просто не повезло.

Не обобщает. Совпадение — по нормализованной фразе и по пересечению
слов, а не по смыслу. Обобщать должна модель, а не текстовый файл: файл,
который начинает «понимать», — это способ тихо испортить поведение.

Не растёт бесконечно. Держим последние `deeds.keep` записей (по
умолчанию 400), пишем строками JSON — файл читается глазами и чинится
руками.
"""
import json
import logging
import re
import threading
import time

from anamorf.config import CFG, DATA_ROOT

log = logging.getLogger("saika.deeds")

PATH = DATA_ROOT / "data" / "deeds.jsonl"
_LOCK = threading.Lock()
_CACHE = {"rows": None, "mtime": 0.0}

# слова, которыми инструменты этого проекта сообщают о провале. Список
# именно такой, потому что инструменты тут не бросают исключения, а
# отвечают человеческой фразой — и это правильно для разговора, но
# требует знать словарь отказа.
_FAIL_WORDS = ("не нашла", "не нашёл", "не вышло", "не смогла", "не удалось",
               "нет такого", "недоступ", "не открыл", "не запустил",
               "не отвечает", "ошибка", "не получилось", "не вижу")


def _norm(t: str) -> str:
    t = (t or "").lower().replace("ё", "е")
    t = re.sub(r"[^а-яa-z0-9 ]+", " ", t)
    return " ".join(t.split())


def _words(t: str) -> set:
    return {w for w in _norm(t).split() if len(w) > 2}


def looks_failed(result: str) -> tuple:
    """Похоже ли, что инструмент отказал, и какими словами он это сказал.

    Смотрим только на НАЧАЛО ответа: инструменты сообщают об отказе
    первой фразой, а дальше может идти длинный текст, где слово «ошибка»
    встретится в совершенно мирном смысле («в логе ошибок нет»)."""
    head = str(result or "").lower()[:120]
    for w in _FAIL_WORDS:
        if w in head:
            return True, w
    return False, ""


def _load() -> list:
    try:
        m = PATH.stat().st_mtime
    except Exception:
        return []
    if _CACHE["rows"] is not None and _CACHE["mtime"] == m:
        return _CACHE["rows"]
    rows = []
    try:
        for line in PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        rows = []
    _CACHE.update(rows=rows, mtime=m)
    return rows


def record(phrase: str, tool: str, args, ok: bool, why: str = "",
           verified=None, took_ms: int = 0):
    """Записать дело. Зовётся из одного места — там, где инструмент уже
    отработал и известен его собственный ответ.

    verified: True/False/None. None означает «проверить было нечем» — и
    это ЧЕСТНЕЕ, чем записать True: невозможность проверки не то же
    самое, что подтверждённый успех, и путать их нельзя."""
    if not CFG.get("deeds.enabled", True):
        return
    try:
        row = {"ts": round(time.time(), 1), "p": _norm(phrase)[:160],
               "tool": str(tool or "")[:40], "ok": bool(ok),
               "why": str(why or "")[:120], "ver": verified,
               "ms": int(took_ms or 0)}
        try:
            row["args"] = json.dumps(args, ensure_ascii=False)[:180]
        except Exception:
            row["args"] = str(args)[:180]
        with _LOCK:
            PATH.parent.mkdir(parents=True, exist_ok=True)
            keep = int(CFG.get("deeds.keep", 400))
            rows = _load()
            rows.append(row)
            rows = rows[-keep:]
            PATH.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                                      for r in rows) + "\n", encoding="utf-8")
            _CACHE.update(rows=rows, mtime=PATH.stat().st_mtime)
    except Exception as e:
        log.debug("журнал дел не записался: %s", e)


def _similar(rows, phrase, min_share=0.6):
    """Записи про ту же просьбу. Совпадение — по пересечению слов, а не
    по смыслу: смысл — работа модели, а не текстового файла."""
    w = _words(phrase)
    if not w:
        return []
    out = []
    for r in rows:
        rw = _words(r.get("p", ""))
        if not rw:
            continue
        share = len(w & rw) / max(1, min(len(w), len(rw)))
        if share >= min_share:
            out.append((share, r))
    out.sort(key=lambda x: (-x[0], -x[1].get("ts", 0)))
    return [r for _s, r in out]


def hint(phrase: str, max_chars: int = 260) -> str:
    """Подсказка в промпт: что на похожую просьбу уже пробовали.

    Возвращает строку ТОЛЬКО когда есть чему научить — то есть когда в
    прошлом был провал. Удачи в промпт не идут: они уже стали рефлексом
    или и так повторятся, а место в окне не бесплатное.

    Пустая строка — законный и самый частый ответ."""
    if not CFG.get("deeds.enabled", True):
        return ""
    try:
        rows = _similar(_load(), phrase)
        if not rows:
            return ""
        bad = [r for r in rows if not r.get("ok")][:2]
        if not bad:
            return ""
        good = next((r for r in rows if r.get("ok")), None)
        parts = []
        for r in bad:
            parts.append("«%s» не сработал%s" % (
                r.get("tool", "?"),
                (" (" + r["why"] + ")") if r.get("why") else ""))
        s = "На такую же просьбу раньше: " + "; ".join(parts)
        if good:
            s += ". Сработал «%s»" % good.get("tool", "?")
        s += ". Это наблюдение о прошлом, а не правило — решай по месту."
        return s[:max_chars]
    except Exception:
        return ""


def stats(n: int = 12) -> dict:
    """Сводка для панели: сколько дел, сколько провалов, кто чаще падает."""
    rows = _load()
    by = {}
    for r in rows:
        t = r.get("tool", "?")
        d = by.setdefault(t, {"n": 0, "bad": 0, "ms": 0})
        d["n"] += 1
        d["ms"] += int(r.get("ms") or 0)
        if not r.get("ok"):
            d["bad"] += 1
    top = sorted(by.items(), key=lambda kv: -kv[1]["bad"])[:n]
    return {
        "n": len(rows),
        "bad": sum(1 for r in rows if not r.get("ok")),
        "unverified": sum(1 for r in rows if r.get("ver") is None),
        "tools": [{"tool": t, "n": d["n"], "bad": d["bad"],
                   "avg_ms": round(d["ms"] / max(1, d["n"]))}
                  for t, d in top],
        "last": rows[-n:][::-1],
    }
