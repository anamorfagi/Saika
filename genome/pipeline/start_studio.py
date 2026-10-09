# -*- coding: utf-8 -*-
"""
[БЛОК СТУДИЯ] Поднять лаунчер студии и сразу отпустить консоль.

Зачем отдельный файл: исполнитель заданий ждёт завершения процесса, а лаунчер
живёт постоянно — запусти его напрямую, и задание висело бы до таймаута.
Здесь процесс отвязывается, а скрипт выходит через секунду, отчитавшись,
поднялся порт или нет. Настоящая проверка — соединением, а не «наверное».

Запуск: python pipeline/start_studio.py [--restart]
--restart — снять прежнюю студию с порта и поднять заново с новым кодом.
"""
import os
import pathlib
import socket
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("PORT", "8765"))


def busy(port):
    """Порт занят = кто-то уже слушает. Проверяем соединением, без догадок."""
    s = socket.socket()
    s.settimeout(1.0)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def holder(port):
    """PID того, кто слушает порт. Берём из netstat — это штатный способ Windows,
    и он точен: убиваем именно занявший порт процесс, а не «все node»."""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=20).stdout
    except Exception:
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[1].endswith(":%d" % port) \
                and parts[3].upper() == "LISTENING":
            return parts[4]
    return None


def stop(port):
    pid = holder(port)
    if not pid:
        return False
    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
    for _ in range(10):
        time.sleep(0.3)
        if not busy(port):
            print("прежняя студия остановлена (pid %s)" % pid)
            return True
    return False


def main():
    restart = "--restart" in sys.argv
    if busy(PORT) and restart:
        stop(PORT)
    if busy(PORT):
        print("студия уже работает: http://localhost:%d/genome-studio.html" % PORT)
        return 0
    script = ROOT / "pipeline" / "launcher.js"
    if not script.exists():
        print("нет pipeline/launcher.js — поднимать нечего")
        return 1
    flags = 0
    if os.name == "nt":                      # отвязать от консоли задания
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    log = (ROOT / "studio.log").open("a", encoding="utf-8")
    # Служебный подъём не должен открывать вкладку: страница у человека уже открыта,
    # а новая вкладка на каждую пересборку — это то, что он закрывает руками.
    env = dict(os.environ, GENOME_NO_OPEN="1")
    subprocess.Popen(["node", str(script)], cwd=str(ROOT), stdout=log, stderr=log,
                     creationflags=flags, close_fds=True, env=env)
    for _ in range(20):                      # до 10 секунд на подъём
        time.sleep(0.5)
        if busy(PORT):
            print("студия поднята: http://localhost:%d/genome-studio.html" % PORT)
            return 0
    print("лаунчер запущен, но порт %d за 10 с не отозвался — смотри studio.log" % PORT)
    return 1


if __name__ == "__main__":
    sys.exit(main())
