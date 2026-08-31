"""«ВКЛЮЧИ МУЗЫКУ, ОНА УЖЕ ОТКРЫТА» — НАЖАТЬ, А НЕ ИСКАТЬ.

Живой провал 23.08, десять минут владельца и ведро мата. Два независимых
слоя сломались в одну сторону — «сказала, что сделала, и не сделала»:

  1. Модель писала маркер СВОИМИ словами: [медиа_контрол:action=play,
     app="youtube", screen=2]. Разбор ждал латинское имя, маркер не
     опознавался вообще — не исполнялся и даже не получал честного «нет
     такого инструмента». Он просто вырезался как мусор, а следом шло
     «Всё, включила».

  2. «Включи музыку в браузере, она уже открыта» уходило в поиск: на
     ютубе открывалась выдача по запросу «музыку короче она уже открыта».
     Владелец: «зачем ты гуглишь какую-то хрень?»

Проверяем оба слоя.
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run():
    rows = []

    # ── 1. ИМЯ ИНСТРУМЕНТА ПО-РУССКИ ──
    src = io.open(os.path.join(ROOT, "anamorf", "main.py"),
                  encoding="utf-8").read()
    ns = {"re": re}
    for nm in ("_CALL_PREFIX_RE", "_RU_TOOL", "_RU_NAME_RE", "_TOOL_MARK_RE"):
        m = re.search(r"^%s = .*?(?=\n[_A-Za-z@#]|\Z)" % nm, src, re.S | re.M)
        exec(m.group(0), ns)
    exec(re.search(r"^def _norm_call_dialect.*?(?=\n\n)", src, re.S | re.M)
         .group(0), ns)

    def call_of(text):
        out = ns["_norm_call_dialect"](text)
        hit = ns["_TOOL_MARK_RE"].search(out)
        return hit.group(1) if hit else None

    rows.append(("«медиа_контрол» — это media_control, а не мусор",
                 call_of('[медиа_контрол:action=play, app="youtube"] Включаю.')
                 == "media_control", ""))
    rows.append(("жест-маркер не трогаем — он не инструмент",
                 call_of("[жест:good] Привет") is None, ""))
    rows.append(("ремарка в скобках командой не считается",
                 call_of("[прим.: она задумалась] и дальше") is None, ""))
    rows.append(("любой маркер с параметрами получает честный ответ, "
                 "а не тишину",
                 're.search(r"[a-zа-яё_]{2,}\\s*=", m.group(2) or ""' in src,
                 ""))

    # ── 2. УЖЕ ОТКРЫТО — ЗНАЧИТ НАЖАТЬ ──
    from anamorf import reflex
    play = ("Включи музыку в браузере.",
            "Вот музыка, которая сейчас на YouTube открыта, просто запусти её.",
            "Включи музыку, короче, в YouTube. Она уже открыта.",
            "поставь музыку в хроме")
    for t in play:
        h = reflex.match(t)
        rows.append((f"«{t[:34]}…» -> нажать плей",
                     h == ("media_control", {"action": "играй"}), str(h)))

    # ── 3. ЖИВЫЕ СЛОВА ВЛАДЕЛЬЦА (23.08: «лисни музыку, переключи на
    #    след, мотни назад») — каждое должно быть мгновенным, без раздумий
    want = {"переключи на следующий": ("media_control", "следующий"),
            "переключи на след": ("media_control", "следующий"),
            "следующая песня": ("media_control", "следующий"),
            "мотни назад": ("media_control", "назад"),
            "отмотай назад": ("media_control", "назад"),
            "перемотай назад": ("media_control", "назад"),
            "промотай вперёд": ("media_control", "вперёд"),
            "лисни музыку": ("service_open", None)}
    for t, (tool, act) in want.items():
        h = reflex.match(t)
        ok = bool(h) and h[0] == tool and (act is None
                                           or h[1].get("action") == act)
        rows.append((f"«{t}» — мгновенно", ok, str(h)))

    # перемотка теперь работает и в ЧУЖОМ окне, а не только в её собственном
    pc = io.open(os.path.join(ROOT, "anamorf", "pc_control.py"),
                 encoding="utf-8").read()
    rows.append(("перемотка ищет окно, где играет, и возвращает фокус",
                 "def _seek_foreign" in pc and "SetForegroundWindow(back)" in pc,
                 ""))
    rows.append(("«включи музыку» при уже открытом плеере не открывает второй",
                 "открывать второе не стала" in io.open(
                     os.path.join(ROOT, "anamorf", "llm", "tools.py"),
                     encoding="utf-8").read(), ""))

    # и наоборот: где площадка названа как МЕСТО ПОИСКА — ищем, как и раньше
    keep = {"найди музыку на ютубе": "web_open",
            "включи музыку": "service_open",
            "включи музыку в папке Музыка": "service_open"}
    for t, want in keep.items():
        h = reflex.match(t)
        rows.append((f"«{t}» осталось прежним ({want})",
                     bool(h) and h[0] == want, str(h)))
    return rows
