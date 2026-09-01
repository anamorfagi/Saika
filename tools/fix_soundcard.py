# -*- coding: utf-8 -*-
"""ВЕРНУТЬ ЗАХВАТ ЗВУКА С КОМПЬЮТЕРА (2026-08-31).

Живой случай: владелец запускает ролик в плеере — в стенограмме пусто.
В журнале одна строка: «Системный звук не поднялся: No module named
soundcard». Тесты этого не ловили, потому что реплей подаёт звук прямо
в очередь слуха, минуя захват, — то есть проверяли всё, кроме той
двери, через которую звук приходит на самом деле.
"""
import subprocess, sys, importlib

def have(m):
    try:
        importlib.import_module(m); return True
    except Exception:
        return False

print("python:", sys.executable)
for mod, pkg in (("soundcard", "soundcard"),):
    if have(mod):
        print("%s уже стоит" % mod); continue
    print("ставлю %s ..." % pkg)
    r = subprocess.run([sys.executable, "-m", "pip", "install", pkg],
                       capture_output=True, text=True, timeout=600)
    print("rc=%d" % r.returncode)
    print((r.stdout or "")[-1500:])
    print((r.stderr or "")[-800:])

importlib.invalidate_caches()
if have("soundcard"):
    import soundcard as sc
    print("\nПЕТЛИ (что можно слушать как звук компьютера):")
    for m in sc.all_microphones(include_loopback=True):
        print("   ", ("[петля] " if m.isloopback else "        ") + m.name)
    try:
        print("\nдинамик по умолчанию:", sc.default_speaker().name)
    except Exception as e:
        print("динамик по умолчанию не определился:", e)
else:
    print("soundcard так и не поднялся")
