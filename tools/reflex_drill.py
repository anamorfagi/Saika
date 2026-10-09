# -*- coding: utf-8 -*-
"""ЭКЗАМЕН РЕФЛЕКСОВ: какие фразы идут мимо модели, а какие в раздумья.

Владелец 05.09.2026: «такие вещи вообще должны быть моментальными… мы же
знаем примерно, какие запросы к системе могут быть — пропиши ей сразу
такие вещи в быстрые команды, где нужна скорость, а не обдумывание».

Стенд ничего не исполняет. Он только спрашивает у таблицы рефлексов, что
она думает про фразу, — и это можно гонять сотнями за секунду, не трогая
ни окон, ни музыки. Красным выходит всё, что уйдёт в модель на двадцать
секунд, — то есть ровно список того, что надо дописать в таблицу."""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
O = []


def say(*a):
    O.append(" ".join(str(x) for x in a))


# фразы, которые владелец говорит на самом деле, включая кривые
CASES = [
    ("открой браузер", "app_launch"),
    ("аткрой браузир", "app_launch"),
    ("запусти хром", "app_launch"),
    ("открой блендер", "app_launch"),
    ("аткрой блендар", "app_launch"),
    ("запусти анрил", "app_launch"),
    ("открой корел", "app_launch"),
    ("открой блокнот", "app_launch"),
    ("открой проводник", "app_launch"),
    ("закрой браузер", "window_close"),
    ("закрой блокнот", "window_close"),
    ("закрой блендер", "window_close"),
    ("новая вкладка", "tab_control"),
    ("открой новую вкладку", "tab_control"),
    ("следующая вкладка", "tab_control"),
    ("переключись на следующую вкладку", "tab_control"),
    ("предыдущая вкладка", "tab_control"),
    ("вернись на предыдущую вкладку", "tab_control"),
    ("закрой вкладку", "tab_control"),
    ("включи музыку", "media_control"),
    ("вклучи музику", "media_control"),
    ("выключи музыку", "media_control"),
    ("поставь на паузу", "media_control"),
    ("следующий трек", "media_control"),
    ("предыдущий трек", "media_control"),
    ("громче", "volume_set"),
    ("сделай громче", "volume_set"),
    ("тише", "volume_set"),
    ("убавь громкость", "volume_set"),
    ("убав громкасть", "volume_set"),
    ("поставь громкость 30 процентов", "volume_set"),
    ("громкость 50", "volume_set"),
    ("выключи звук", "volume_set"),
    ("сверни все окна", "minimize_all"),
    ("сверни фсе окна", "minimize_all"),
    ("сверни всё", "minimize_all"),
    ("верни окна обратно", "window_restore_all"),
    ("разверни окна назад", "window_restore_all"),
    ("сверни это окно", "window_minimize"),
    ("разверни на весь экран", "window_maximize"),
    ("переключись на окно клода", "window_focus"),
    ("покажи браузер", "window_focus"),
    ("выведи блендер вперёд", "window_focus"),
    ("посмотри на экран", "look_screen"),
    ("пасматри на икран", "look_screen"),
    ("что на экране", "look_screen"),
]


def main():
    from anamorf import reflex as rx
    ok = bad = wrong = 0
    say("ЭКЗАМЕН РЕФЛЕКСОВ — что исполнится мгновенно, а что уйдёт думать")
    say("=" * 84)
    miss = []
    for phrase, want in CASES:
        hit = None
        try:
            hit = rx.match(phrase)
        except Exception as e:
            say("  ! %s — разбор упал: %r" % (phrase, e))
        got = hit[0] if hit else ""
        if not got:
            bad += 1
            miss.append((phrase, want, ""))
            mark = "В РАЗДУМЬЯ"
        elif got != want:
            wrong += 1
            miss.append((phrase, want, got))
            mark = "НЕ ТОТ"
        else:
            ok += 1
            mark = "мгновенно"
        say("  %-38s %-12s %-19s %s"
            % ("«" + phrase + "»", mark, got or "—", "" if got == want
               else ("ждали " + want)))
    say("")
    say("ИТОГО: мгновенно %d из %d, уходит думать %d, не тот инструмент %d"
        % (ok, len(CASES), bad, wrong))
    if miss:
        say("")
        say("ДОПИСАТЬ В ТАБЛИЦУ:")
        for p, w, g in miss:
            say("  «%s» -> %s%s" % (p, w, ("  (сейчас ловит " + g + ")") if g else ""))


try:
    main()
except Exception:
    import traceback
    say(traceback.format_exc())
io.open(ROOT / "data" / "reflex_drill.txt", "w",
        encoding="utf-8").write("\n".join(O))
