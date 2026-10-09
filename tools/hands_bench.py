# -*- coding: utf-8 -*-
"""СТЕНД РУК И ГЛАЗ: цепочки команд с честными замерами (05.09.2026).

Владелец: «сделай какой-нибудь алгоритм, по которому ты проверишь цепочки
запросов… сделай замеры того, как она отрабатывает и с какой скоростью…
попробуй написать фразы с ошибками, проверь, как она отрабатывает команды».

ЧТО МЕРЯЕТ И ПОЧЕМУ ИМЕННО ЭТО

  дошло       — вызвала ли она вообще инструмент. Ноль здесь значит, что
                команда утонула в разговоре: она ответила словами вместо
                действия. Самый частый и самый незаметный вид отказа.
  тот ли      — вызвала ли она ТОТ инструмент. Вызвать не тот хуже, чем
                не вызвать никакой: человек думает, что сделано.
  сделано     — сказал ли сам инструмент, что действие удалось. Это его
                слово, а не наша догадка по тексту ответа.
  до действия — сколько прошло от фразы до вызова инструмента. Это то
                время, которое человек считает «тормозит».
  всего       — до конца ответа.

ФРАЗЫ С ОШИБКАМИ — ОТДЕЛЬНАЯ КОЛОНКА, А НЕ ОТДЕЛЬНЫЙ ПРОГОН. Владелец
пишет и говорит с опечатками постоянно, и распознавание добавляет своих.
Поэтому у каждой команды есть кривой двойник, и обе идут подряд: разница
между ними и есть мера устойчивости.

НИЧЕГО НЕОБРАТИМОГО. Стенд не закрывает чужие приложения и не трогает
несохранённое: закрывает только то, что открыл сам (блокнот, калькулятор).
Тяжёлые (Blender, UE, Corel) — отдельным списком, руками и по слову
владельца.
"""
import io
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = []
BASE = "http://127.0.0.1:8765"
LOG = ROOT / "logs" / "saika.log"


def say(*a):
    OUT.append(" ".join(str(x) for x in a))


def _post(path, payload, timeout=180):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _log_size():
    try:
        return LOG.stat().st_size
    except Exception:
        return 0


def _log_since(pos):
    """Хвост журнала с байтового смещения.

    ЧИТАЕМ БАЙТАМИ (05.09.2026). В первом прогоне тут был текстовый режим
    с f.seek(байты) — так делать нельзя: в текстовом режиме смещение
    осмысленно только то, что вернул сам f.tell(). Итог: разбор вернул
    «дошло до инструмента 0%», хотя в журнале вызовы были, и стенд
    оболгал живую систему. Стенд, который врёт, хуже отсутствующего."""
    try:
        with open(LOG, "rb") as f:
            f.seek(pos)
            return f.read().decode("utf-8", "ignore")
    except Exception:
        return ""


_TOOL = re.compile(r"tool ([a-zA-Z_0-9]+)\((.*?)\) -> (\d+) символов")
_FIRST = re.compile(r"стрим до 1-го токена (\d+)мс")


def one(name, phrase, want_tool, bad=False):
    """Одна команда: сказать фразу и посмотреть, что произошло на самом
    деле. Смотрим не на её слова, а на журнал: какой инструмент вызван."""
    pos = _log_size()
    t0 = time.monotonic()
    err = ""
    reply = ""
    try:
        r = _post("/api/chat", {"text": phrase, "speak": False})
        reply = (r.get("reply") or "")[:160]
    except Exception as e:
        err = repr(e)[:100]
    total = round((time.monotonic() - t0) * 1000)
    time.sleep(0.6)                      # журнал пишется чуть позже ответа
    tail = _log_since(pos)
    calls = _TOOL.findall(tail)
    first = _FIRST.search(tail)
    got = calls[0][0] if calls else ""
    hit = bool(want_tool) and any(c[0] == want_tool for c in calls)
    # «сделано» — слово самого инструмента, а не наша догадка по ответу
    low = tail.lower()
    failed = any(w in low for w in ("не нашла", "не вышло", "не смогла",
                                    "не удалось", "нет такого", "недоступ"))
    row = {"имя": name, "кривая": bad, "фраза": phrase,
           "ждали": want_tool, "вызвала": got,
           "все_вызовы": [c[0] for c in calls],
           "тот_ли": hit, "похоже_на_отказ": failed,
           "до_действия_мс": int(first.group(1)) if first else None,
           "всего_мс": total, "ответ": reply, "ошибка": err}
    say("%-26s %-7s %-18s -> %-18s %s  до действия %-7s всего %-7s %s"
        % (name, "кривая" if bad else "ровная", want_tool or "—",
           got or "НИЧЕГО", "OK " if hit else "МИМО",
           (str(row["до_действия_мс"]) + "мс") if first else "—",
           str(total) + "мс", "(похоже на отказ)" if failed else ""))
    if reply:
        say("      ответ: " + reply.replace("\n", " ")[:120])
    return row


# ─────────────────────────────────────────── что гоняем
# (имя, ровная фраза, кривая фраза, ожидаемый инструмент)
CHAIN = [
    ("браузер: открыть",  "открой браузер",
     "аткрой браузир", "app_launch"),
    ("вкладка: новая",    "открой новую вкладку в браузере",
     "аткрой новаю фкладку в браузире", "tab_control"),
    ("вкладка: вперёд",   "переключись на следующую вкладку",
     "перключись на следущюю вкладку", "tab_control"),
    ("вкладка: назад",    "вернись на предыдущую вкладку",
     "вернис на предыдушую вкладку", "tab_control"),
    ("музыка: включить",  "включи музыку",
     "вклучи музику", "media_control"),
    ("музыка: найти",     "найди песню Snail Kick",
     "найди песеньку снаил кик", "web_search"),
    ("громкость: тише",   "убавь громкость",
     "убав громкасть", "volume_set"),
    ("громкость: число",  "поставь громкость 30 процентов",
     "пастав громкость 30 працентов", "volume_set"),
    ("окна: свернуть все", "сверни все окна",
     "сверни фсе окна", "minimize_all"),
    ("окна: вернуть",     "верни окна обратно",
     "верни окна абратно", "window_restore_all"),
    ("фокус: приложение", "переключись на окно Клода",
     "перключись на акно клода", "window_focus"),
    ("глаза: посмотри",   "посмотри на экран и скажи, что видишь",
     "пасматри на икран и скажи што видиш", "look_screen"),
    ("блокнот: открыть",  "открой блокнот",
     "аткрой блакнот", "app_launch"),
    ("блокнот: закрыть",  "закрой блокнот",
     "закрой блакнот", "window_close"),
]


def main():
    say("СТЕНД РУК И ГЛАЗ — %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    say("=" * 100)
    rows = []
    for name, ok_phrase, bad_phrase, tool in CHAIN:
        rows.append(one(name, ok_phrase, tool, bad=False))
        time.sleep(1.2)
        rows.append(one(name, bad_phrase, tool, bad=True))
        time.sleep(1.2)

    say("")
    say("=" * 100)
    n = len(rows)
    hit = sum(1 for r in rows if r["тот_ли"])
    got = sum(1 for r in rows if r["вызвала"])
    ok_rows = [r for r in rows if not r["кривая"]]
    bad_rows = [r for r in rows if r["кривая"]]
    say("ИТОГО: команд %d, дошло до инструмента %d (%d%%), тот инструмент "
        "%d (%d%%)" % (n, got, 100 * got // n, hit, 100 * hit // n))
    say("  ровные фразы:  %d из %d попали" % (
        sum(1 for r in ok_rows if r["тот_ли"]), len(ok_rows)))
    say("  кривые фразы:  %d из %d попали" % (
        sum(1 for r in bad_rows if r["тот_ли"]), len(bad_rows)))
    fa = [r["до_действия_мс"] for r in rows if r["до_действия_мс"]]
    if fa:
        fa.sort()
        say("  до действия: медиана %d мс, худшее %d мс" % (
            fa[len(fa) // 2], fa[-1]))
    tt = sorted(r["всего_мс"] for r in rows)
    say("  всего:       медиана %d мс, худшее %d мс" % (
        tt[len(tt) // 2], tt[-1]))
    miss = [r for r in rows if not r["тот_ли"]]
    if miss:
        say("")
        say("ПРОМАХИ (по ним и надо чинить):")
        for r in miss:
            say("  %-26s %-7s «%s» -> %s"
                % (r["имя"], "кривая" if r["кривая"] else "ровная",
                   r["фраза"], r["вызвала"] or "ничего не вызвала"))
    io.open(ROOT / "data" / "hands_bench.json", "w",
            encoding="utf-8").write(json.dumps(rows, ensure_ascii=False,
                                               indent=1))


try:
    main()
except Exception:
    import traceback
    say(traceback.format_exc())
io.open(ROOT / "data" / "hands_bench.txt", "w",
        encoding="utf-8").write("\n".join(OUT))
