# -*- coding: utf-8 -*-
"""[БЛОК СТУДИЯ] Снять лишние копии студии, оставив одну.

За вечер перезапусков на соседних портах набирается несколько живых лаунчеров, и
человек видит пять вкладок одного приложения. Здесь мы обходим порты, спрашиваем
каждого, студия ли он, и гасим всех, кроме одного — через /api/quit, без прав.

Запуск: python pipeline/kill_dupes.py
"""
import socket
import sys
import urllib.request

# Обращения к своему же localhost не должны идти через системный прокси: с ним
# проверка «жива ли студия» молча отвечает «нет», хотя порт занят и всё работает.
_БЕЗ_ПРОКСИ = urllib.request.build_opener(urllib.request.ProxyHandler({}))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

НАЧАЛО, КОНЕЦ = 8765, 8780


def занят(порт):
    s = socket.socket(); s.settimeout(0.7)
    try:
        s.connect(("127.0.0.1", порт)); return True
    except OSError:
        return False
    finally:
        s.close()


def это_студия(порт):
    """Опознаём по /api/chars — он в лаунчере есть точно.

    Раньше здесь стоял /api/v, которого в лаунчере нет вовсе: проверка всегда
    отвечала «не студия», и дубли не гасились, хотя порты были заняты.
    """
    try:
        with _БЕЗ_ПРОКСИ.open(f"http://127.0.0.1:{порт}/api/chars", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def умеет_уйти(порт):
    """Новый лаунчер отвечает на пинг маршрута чата — значит знает и /api/quit."""
    try:
        with _БЕЗ_ПРОКСИ.open(f"http://127.0.0.1:{порт}/api/chat", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def погасить(порт):
    try:
        _БЕЗ_ПРОКСИ.open(urllib.request.Request(
            f"http://127.0.0.1:{порт}/api/quit", data=b"{}",
            headers={"Content-Type": "application/json"}), timeout=4).read()
        return True
    except Exception:
        return False


def main():
    порты = [п for п in range(НАЧАЛО, КОНЕЦ + 1) if занят(п)]
    print("занятых портов: %s" % (", ".join(map(str, порты)) or "нет"))
    живые = [п for п in порты if это_студия(п)]
    if not живые:
        print("студий не найдено (порты заняты чем-то другим либо не отвечают на /api/v)")
        return 0
    print("найдено копий: %d (порты %s)" % (len(живые), ", ".join(map(str, живые))))
    if len(живые) == 1:
        print("дублей нет, оставляю %d" % живые[0]); return 0
    # Оставляем самую новую: та, что умеет /api/quit, значит поднята свежим кодом.
    новые = [п for п in живые if умеет_уйти(п)]
    оставить = новые[-1] if новые else живые[-1]
    for п in живые:
        if п == оставить:
            continue
        если_ушёл = погасить(п)
        print("порт %d: %s" % (п, "погашен" if если_ушёл else "не отвечает на /api/quit (старый код, нужны права)"))
    print("осталась студия на http://localhost:%d/genome-studio.html" % оставить)
    return 0


if __name__ == "__main__":
    sys.exit(main())
