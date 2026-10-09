# -*- coding: utf-8 -*-
"""Картинка персонажу и пересборка списка — с правильной рабочей папкой.

Первая версия запускала share_index.js из pipeline, а он ищет share/ рядом с
собой: список собрался пустым и стёр всех персонажей в студии. Папка задаётся
явно — это genome, уровнем выше.
"""
import pathlib
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ЗДЕСЬ = pathlib.Path(__file__).resolve().parent
ГЕНОМ = ЗДЕСЬ.parent
sys.path.insert(0, str(ЗДЕСЬ))
import ava_fetch

ид = sys.argv[1]
запрос = sys.argv[2] if len(sys.argv) > 2 else None
имя = sys.argv[3] if len(sys.argv) > 3 else None
try:
    ava_fetch.вшить(ид, запрос, имя)
except SystemExit as e:
    print("картинка не встала:", str(e)[:200])

r = subprocess.run(["node", str(ЗДЕСЬ / "share_index.js")], capture_output=True, text=True,
                   encoding="utf-8", errors="replace", cwd=str(ГЕНОМ))
итог = (r.stdout or r.stderr).strip()[:200]
print("список:", итог)
if "0 персонажей" in итог:
    print("ВНИМАНИЕ: список собрался пустым — не сохраняю такое состояние молча")
