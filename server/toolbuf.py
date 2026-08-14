"""Что вернули инструменты ПРЯМО СЕЙЧАС — чтобы следующий ход это помнил.

ЖИВОЙ СЛУЧАЙ (15.08.2026, дословно из чата):
    — Что ты видишь на экране?
    — Не получилось получить информацию из окна игры «Genshin Impact»,
      доступны только некоторые клавиши.
    — Какие?
    — Извини, но сейчас я не совсем поняла, что именно ты хочешь узнать…
и так шесть раз подряд, до «бля это пиздец».

Причина не в модели. Результат инструмента живёт РОВНО ОДИН запрос: он
кладётся в messages внутри chat_stream и там же умирает. В память
записывается только её собственный ответ — уже пересказанный своими
словами и без подробностей. На следующем ходу «какие?» опирается на
пустоту: она физически не знает, что сама только что сказала «клавиши»,
потому что список был в результате инструмента, а не в её реплике.

Здесь короткий буфер: несколько последних вызовов с их ответами. Он
подкладывается в промпт следующего хода, живёт минуты и сам вычищается.
Это не память (та про смысл и живёт годами) — это рабочий стол: что у
меня в руках прямо сейчас.
"""
import logging
import threading
import time

log = logging.getLogger("saika.toolbuf")

_LOCK = threading.Lock()
_BUF = []                    # [{"ts", "name", "args", "result"}]
MAX = 6
TTL = 300.0                  # 5 минут: дальше это уже не «только что»


def note(name: str, args, result: str) -> None:
    try:
        a = args if isinstance(args, str) else str(args)
    except Exception:
        a = ""
    item = {"ts": time.time(), "name": str(name)[:40], "args": a[:160],
            "result": (result or "")[:900]}
    with _LOCK:
        _BUF.append(item)
        del _BUF[:-MAX]


def clear() -> None:
    with _LOCK:
        _BUF.clear()


def recent(max_age: float = TTL, limit: int = 3) -> list:
    now = time.time()
    with _LOCK:
        items = [x for x in _BUF if now - x["ts"] <= max_age]
    return items[-limit:]


def block(max_age: float = TTL, limit: int = 3, chars: int = 1200) -> str:
    """Кусок промпта. Пусто — значит инструменты давно не звали."""
    items = recent(max_age, limit)
    if not items:
        return ""
    lines = []
    for x in items:
        ago = int(time.time() - x["ts"])
        lines.append("• %s(%s) %d с назад вернул: %s"
                     % (x["name"], x["args"], ago, x["result"]))
    txt = "\n".join(lines)
    if len(txt) > chars:
        txt = txt[:chars].rstrip() + "…"
    return ("### Что мои инструменты вернули только что (это ФАКТЫ, "
            "отвечай по ним, а не переспрашивай):\n" + txt +
            "\nЕсли человек уточняет («какие?», «а точнее?», «покажи "
            "список») — он спрашивает ПРО ЭТО. Отвечай конкретикой "
            "отсюда, не проси переформулировать.")
