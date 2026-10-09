# -*- coding: utf-8 -*-
"""Открыть ролик ДНК в MPC-HC ровно с 31:44 — по прямой просьбе владельца.

Прошлая попытка (глобальная клавиша «воспроизведение/пауза») была
ошибкой: эта клавиша не адресная, Windows отдаёт её тому приложению,
которое последним заявило на неё права. Она включила чужое приложение, а
ролик остался на паузе — владелец его так и не услышал.

Здесь адресно: запускаем ИМЕННО mpc-hc64.exe с ИМЕННО этим файлом и
позицией в миллисекундах. Никаких догадок о том, какое окно в фокусе.
"""
import subprocess, sys, time
from pathlib import Path

EXE = Path(r"C:\Program Files\MPC-HC\mpc-hc64.exe")
VID = Path(r"C:\AI\Saika\slux_test\snailkik_dnk\ДЯДЯ ОТЦА МАТЕРИ СЫНА _ СМОТРИМ ДНК.mp4")
START_MS = 31 * 60 * 1000 + 44 * 1000          # 31:44

if not EXE.exists():
    print("нет плеера:", EXE); sys.exit(1)
if not VID.exists():
    print("нет файла:", VID); sys.exit(1)
subprocess.Popen([str(EXE), str(VID), "/start", str(START_MS), "/play"],
                 close_fds=True)
print("запущен ролик с", START_MS, "мс", time.strftime("%H:%M:%S"))
