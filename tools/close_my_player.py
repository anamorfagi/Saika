# -*- coding: utf-8 -*-
"""Закрыть плеер, который Я запустила (05.09.2026).

Владелец: «нахуя ты запускаешь какой-то медиаплеер, ролик я же тебе
показал где». Верно: стенд поиска петли сам включал data/snailkick.wav,
чтобы было что мерить, — и играл поверх его ролика. Два звука разом.
Здесь закрываем только окна с моим файлом, чужие не трогаем."""
import io, sys, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); os.chdir(str(ROOT))
O = []
def say(*a): print(" ".join(str(x) for x in a)); O.append(" ".join(str(x) for x in a))
MINE = ("snailkick", "bench_1000_1300", "eval_take", "birdsong")
try:
    import win32gui, win32con
    hits = []
    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd): return
        t = (win32gui.GetWindowText(hwnd) or "")
        if any(m in t.lower() for m in MINE): hits.append((hwnd, t))
    win32gui.EnumWindows(cb, None)
    if not hits: say("моих плееров не нашла — ничего не трогаю")
    for hwnd, t in hits:
        say("закрываю моё окно:", t[:70])
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
except Exception as e:
    say("не вышло:", repr(e)[:160])
io.open(ROOT/"data"/"close_my_player.txt","w",encoding="utf-8").write("\n".join(O))
