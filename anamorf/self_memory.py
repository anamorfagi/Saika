"""СВОЯ ПАМЯТЬ — инструменты, которыми Сайка спрашивает саму себя.

2026-08-13, живой позор: на «что ты вообще помнишь о наших разговорах» она
четыре раза подряд объяснила, что долговременной памяти у неё нет и быть не
может. При этом на диске лежат saika_memory.db, эпизоды в chroma, образ
собеседника и история на три сотни сообщений.

ПОЧЕМУ ТАК ВЫШЛО. Память ей ПОДКЛАДЫВАЛИ: build_context ищет по смыслу
ТЕКУЩЕЙ фразы и вставляет найденное в промпт. Приём хороший и быстрый, но
у него есть слепое пятно: у вопроса «что ты помнишь вообще» нет предмета,
искать не по чему, и в промпт не попадает НИЧЕГО. А раз в промпте пусто —
модель отвечает не как Сайка со своей базой, а как языковая модель вообще,
из общего знания о том, что «у ассистентов нет памяти между сессиями».
То есть врала не она — врало отсутствие вопроса.

Здесь она может СПРОСИТЬ. Четыре инструмента, все только читают.
"""
import logging
import time
from datetime import datetime

from anamorf.config import CFG

log = logging.getLogger("saika.selfmem")

SCHEMAS = [
    {"type": "function", "function": {
        "name": "memory_recall",
        "description": ("Поискать в СВОЕЙ долговременной памяти по теме: "
                        "«помнишь, мы говорили про…», «что я тебе рассказывал "
                        "о…». Ищет по прошлым разговорам, а не по текущему."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "тема или ключевые слова"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "memory_recap",
        "description": ("Пересказ разговоров за период: «о чём мы сегодня "
                        "говорили», «что было вчера», «что мы обсуждали за "
                        "всё время». Зови ВМЕСТО того, чтобы отвечать, что "
                        "не помнишь."),
        "parameters": {"type": "object", "properties": {
            "period": {"type": "string", "description":
                       "сегодня | вчера | неделя | всё"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "memory_about",
        "description": ("Что ты знаешь о собеседнике: имя, привычки, факты, "
                        "которые он о себе рассказывал. Зови на «что ты обо "
                        "мне знаешь», «что ты про меня помнишь»."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "memory_stats",
        "description": ("Объём собственной памяти: сколько сообщений, "
                        "эпизодов, людей и с какого числа. Зови, когда "
                        "спрашивают, есть ли у тебя память вообще."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]
NAMES = {s["function"]["name"] for s in SCHEMAS}


def _mem():
    from anamorf.main import memory
    return memory


def _pid():
    return CFG.get("owner.id", "owner")


def recall(args) -> str:
    q = str((args or {}).get("query") or "").strip()
    if not q:
        return "не поняла, про что вспоминать"
    m = _mem()
    out = []
    try:
        eps = m.relevant_episodes(q, _pid(), k=8) or []
        out += ["- " + str(e) for e in eps if e]
    except Exception as e:
        log.debug("эпизоды: %s", e)
    if not out:
        # эпизодов по теме нет — ищем по сырым сообщениям, грубо, но честно
        try:
            rows = m.recent_raw(_pid(), limit=400)
            low = q.lower()
            hits = [f"{r}: {t}" for r, t in rows
                    if low in str(t).lower()][-8:]
            out += ["- " + h for h in hits]
        except Exception as e:
            log.debug("сырые: %s", e)
    if not out:
        return (f"в памяти по теме «{q}» ничего не нашлось. Так и скажи — "
                "честно, что не помнишь ИМЕННО ЭТОГО. Не говори, что памяти "
                "у тебя нет вообще: она есть, просто в ней нет этого.")
    return f"Из памяти по теме «{q}»:\n" + "\n".join(out[:10])


def _period_start(period: str) -> float:
    p = (period or "").lower()
    now = datetime.now()
    if "сегодня" in p or not p:
        return now.replace(hour=0, minute=0, second=0,
                           microsecond=0).timestamp()
    if "вчера" in p:
        return (now.replace(hour=0, minute=0, second=0,
                            microsecond=0).timestamp() - 86400)
    if "недел" in p:
        return now.timestamp() - 7 * 86400
    return 0.0


def recap(args) -> str:
    period = str((args or {}).get("period") or "сегодня")
    since = _period_start(period)
    m = _mem()
    try:
        rows = m.recent_raw(_pid(), limit=600, since_ts=since, with_ts=True)
    except Exception as e:
        return f"не смогла заглянуть в память: {e}"
    if not rows:
        return (f"за период «{period}» записей нет. Скажи это прямо, но не "
                "выдумывай, будто памяти нет совсем.")
    # только реплики человека: пересказывать себе свои же слова незачем
    mine = [t for _ts, r, t in rows if r == "user" and str(t).strip()]
    if "вчера" in period.lower():
        edge = since + 86400
        mine = [t for ts, r, t in rows
                if r == "user" and ts < edge and str(t).strip()]
    if not mine:
        return f"за «{period}» человек ничего не говорил — только ты."
    body = "\n".join("- " + str(t)[:200] for t in mine[-60:])
    return (f"Реплики человека за «{period}» ({len(mine)} шт., это ТВОЯ "
            f"память, а не догадки):\n{body}\n\n"
            "Перескажи СВОИМИ словами, о чём шла речь: темами, а не "
            "списком. Коротко.")


def about(args=None) -> str:
    m = _mem()
    try:
        p = m.person(_pid())
    except Exception as e:
        return f"не смогла достать образ собеседника: {e}"
    core = p.get("core") or {}
    if not core:
        return ("образа собеседника пока нет — он собирается из разговоров "
                "постепенно. Скажи честно: помнишь разговоры, но цельного "
                "портрета ещё не сложила. Памяти это не отменяет.")
    import json as _j
    return ("Что ты о нём знаешь (из своей памяти, не выдумка):\n"
            + _j.dumps(core, ensure_ascii=False, indent=1)
            + f"\nИмя: {p.get('name') or 'не записано'}")


def stats(args=None) -> str:
    m = _mem()
    try:
        st = m.stats()
        rows = m.recent_raw(_pid(), limit=1, with_ts=True)
    except Exception as e:
        return f"счётчик памяти не ответил: {e}"
    first = ""
    try:
        with m.lock:
            r = m._conn.execute("SELECT MIN(ts) FROM events").fetchone()
        if r and r[0]:
            first = datetime.fromtimestamp(r[0]).strftime("%d.%m.%Y")
    except Exception:
        pass
    return (f"Твоя память ЕСТЬ и вот её объём: сообщений {st['events']}, "
            f"сжатых эпизодов {st['episodes']}, людей {st['persons']}"
            + (f", самая ранняя запись — {first}" if first else "")
            + ". Это факт с диска. Отвечай по нему, а не по общим "
              "представлениям о том, что бывает у языковых моделей.")


CALLS = {"memory_recall": recall, "memory_recap": recap,
         "memory_about": about, "memory_stats": stats}
