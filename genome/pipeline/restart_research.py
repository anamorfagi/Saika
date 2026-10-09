# -*- coding: utf-8 -*-
"""Перезапуск сервера исследований, чтобы подхватился новый research.py.

Модуль research.py читается один раз при старте процесса: пока старый
сервер жив, правки поиска ни на что не влияют. Скрипт гасит старый
процесс по его командной строке и поднимает новый отвязанным от консоли.
"""
import os
import pathlib
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
КОРЕНЬ = pathlib.Path(__file__).resolve().parent
СЕРВЕР = КОРЕНЬ / "research_server.py"


def живые():
    """PID процессов python, в командной строке которых есть research_server."""
    # wmic из Windows убрали, и опрос молча возвращал пустоту — старый сервер
    # оставался жить, а новый падал на занятом порту. Спрашиваем через CIM.
    запрос = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "
              "'*research_server*' } | ForEach-Object { $_.ProcessId }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", запрос],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60).stdout
    except Exception as e:
        print("не смог опросить процессы:", e)
        return []
    return [int(x.strip()) for x in out.split() if x.strip().isdigit()]


def main():
    было = живые()
    for pid in было:
        if pid == os.getpid():
            continue
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        print("остановлен pid", pid)
    if not было:
        print("работающего сервера исследований не было")
    time.sleep(1.5)
    if not СЕРВЕР.exists():
        print("нет файла", СЕРВЕР)
        return 1
    флаги = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    журнал = (КОРЕНЬ.parent / "logs")
    журнал.mkdir(exist_ok=True)
    f = (журнал / "research_server.log").open("a", encoding="utf-8")
    p = subprocess.Popen([sys.executable, str(СЕРВЕР)], cwd=str(КОРЕНЬ),
                         stdout=f, stderr=subprocess.STDOUT, creationflags=флаги,
                         env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1"))
    time.sleep(2.5)
    жив = p.poll() is None
    print("запущен pid", p.pid, "жив:" , жив)
    return 0 if жив else 2


if __name__ == "__main__":
    raise SystemExit(main())
