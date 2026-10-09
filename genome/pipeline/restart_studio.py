# -*- coding: utf-8 -*-
"""
[БЛОК СТУДИЯ] ПЕРЕЗАПУСК лаунчера студии: снять старый с порта и поднять заново.

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

# Консоль на Windows живёт в cp1251, и один символ вне неё (стрелка, тире, кавычка-ёлочка)
# роняет весь скрипт UnicodeEncodeError — падает не печать, а вся работа. Поэтому вывод
# переводится в utf-8 с заменой непечатаемого: отчёт может потерять символ, но не смысл.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
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


def holders(port):
    """ВСЕ слушатели порта, а не первый попавшийся: записей в netstat бывает несколько
    (IPv4 и IPv6, разные адреса), и убив одну, порт освободить не получится."""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=20).stdout
    except Exception as e:
        print("netstat не отработал: %s" % e)
        return []
    найдено = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[1].endswith(":%d" % port) \
                and parts[3].upper() == "LISTENING" and parts[4] not in найдено:
            найдено.append(parts[4])
    return найдено


def по_командной_строке():
    """Запасной заход: найти node, который держит launcher.js. Нужен, когда netstat
    показал порт занятым, но владельца назвать не смог."""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | "
                              "Where-Object { $_.CommandLine -like '*launcher.js*' } | "
                              "Select-Object -ExpandProperty ProcessId"],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=30).stdout
    except Exception:
        return []
    return [x.strip() for x in out.split() if x.strip().isdigit()]


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


def _открывашка():
    """Свой localhost — мимо системного прокси, иначе проверки врут."""
    import urllib.request
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def попросить_уйти(port):
    """Вежливый путь: попросить лаунчер завершиться самому.

    Убивать процесс правами получается не всегда — если студия поднята из окна
    с другими правами, taskkill отвечает «отказано в доступе». Свой же сервер
    по просьбе с localhost выходит сам, и никакие права для этого не нужны.
    """
    import urllib.request
    try:
        _открывашка().open(urllib.request.Request(
            "http://127.0.0.1:%d/api/quit" % port, data=b"{}",
            headers={"Content-Type": "application/json"}), timeout=5).read()
    except Exception:
        return False
    for _ in range(20):
        time.sleep(0.3)
        if not busy(port):
            print("прежняя студия вышла сама по /api/quit")
            return True
    return False


def это_студия(port):
    """На соседних портах живут и другие наши службы — воркер исследований, например.
    Гасить надо только студию, поэтому сначала спрашиваем её опознавательный маршрут.
    Без этой проверки перезапуск студии стучался бы «уходи» во всё подряд."""
    import urllib.request
    try:
        with _открывашка().open("http://127.0.0.1:%d/api/chars" % port, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def свободный(с=8765, до=8775):
    for порт in range(с, до + 1):
        if not busy(порт):
            return порт
    return None


def stop(port):
    """Снимаем ВСЕХ, кто держит порт, и честно отчитываемся, что получилось.

    Раньше здесь было тихое поражение: не убил — вернул False, а main печатал
    «студия уже работает» и выходил с кодом 0. Снаружи это выглядело как успешный
    перезапуск, хотя работал старый код без новых маршрутов. Теперь каждый шаг
    виден в отчёте, а неудача остаётся неудачей.
    """
    if попросить_уйти(port):
        return True
    пиды = holders(port) or по_командной_строке()
    if not пиды:
        print("порт %d занят, но владельца найти не удалось" % port)
        return False
    for pid in пиды:
        r = subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        print("taskkill pid %s -> код %s %s" % (pid, r.returncode, (r.stdout or r.stderr or "").strip()[:120]))
    for _ in range(20):
        time.sleep(0.3)
        if not busy(port):
            print("прежняя студия остановлена (pid %s)" % ", ".join(пиды))
            return True
    # второй заход: возможно, netstat назвал не того
    ещё = [x for x in по_командной_строке() if x not in пиды]
    for pid in ещё:
        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True)
        print("добит node с launcher.js, pid %s" % pid)
    for _ in range(10):
        time.sleep(0.3)
        if not busy(port):
            return True
    return False


def main():
    # Отдельный файл-перезапуск: аргументы до задания не всегда доходят, а тут
    # решение принято заранее — всегда снять старое и поднять с нынешним кодом.
    restart = True
    if busy(PORT) and restart:
        stop(PORT)
    # Студия могла переехать на соседний порт (когда прежнюю не удалось снять по правам).
    # Перезапуск должен находить её там, где она есть, а не только на «своём» порту.
    for соседний in range(PORT + 1, PORT + 11):
        if busy(соседний) and это_студия(соседний):
            print("нашлась студия на порту %d" % соседний)
            попросить_уйти(соседний)
    порт = PORT
    if busy(PORT):
        # Старый процесс не снимается — значит он запущен с другими правами.
        # Это не повод оставлять человека на старом коде и просить его что-то закрыть
        # руками: поднимаем новую студию на соседнем порту и открываем её сами.
        порт = свободный(PORT + 1, PORT + 10)
        if порт is None:
            print("ОШИБКА: порт %d занят и свободного соседнего не нашлось" % PORT)
            return 1
        print("порт %d снять не удалось (чужие права) — поднимаю студию на %d" % (PORT, порт))
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
    # Вкладку не открываем НИКОГДА. Раньше при переезде на соседний порт лаунчер
    # распахивал новое окно браузера — и за вечер набиралось пять вкладок одного
    # приложения. Страница сама перечитывается по ver.js, а если студия переехала,
    # открытая вкладка сама находит живой порт.
    env = dict(os.environ, PORT=str(порт), GENOME_NO_OPEN="1")
    subprocess.Popen(["node", str(script)], cwd=str(ROOT), stdout=log, stderr=log,
                     creationflags=flags, close_fds=True, env=env)
    for _ in range(20):                      # до 10 секунд на подъём
        time.sleep(0.5)
        if busy(порт):
            print("студия поднята: http://localhost:%d/genome-studio.html" % порт)
            return 0
    print("лаунчер запущен, но порт %d за 10 с не отозвался — смотри studio.log" % порт)
    return 1


if __name__ == "__main__":
    sys.exit(main())
