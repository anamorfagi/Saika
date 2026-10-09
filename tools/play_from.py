# -*- coding: utf-8 -*-
"""Перемотать ролик ДНК на секунду из data/play_at.txt и играть.

Канал runpy аргументов не передаёт — он принимает только путь к скрипту,
поэтому позицию кладём в файл рядом. Это же и якорь: печатаем стенное
время старта, по нему потом пересчитываем «когда услышала» в «на какой
секунде ролика», без чего сравнение с расшифровкой невозможно.
"""
import subprocess, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
EXE = Path(r"C:\Program Files\MPC-HC\mpc-hc64.exe")
VID = ROOT / "slux_test" / "snailkik_dnk" / "ДЯДЯ ОТЦА МАТЕРИ СЫНА _ СМОТРИМ ДНК.mp4"
try:
    sec = int((ROOT / "data" / "play_at.txt").read_text(encoding="utf-8").strip())
except Exception:
    sec = 0
subprocess.Popen([str(EXE), str(VID), "/start", str(sec * 1000), "/play"],
                 close_fds=True)
line = "ЯКОРЬ ts=%.3f видео_сек=%d" % (time.time(), sec)
(ROOT / "data" / "play_anchor.txt").write_text(line, encoding="utf-8")
print(line)
