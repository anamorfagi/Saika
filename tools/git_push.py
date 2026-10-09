# -*- coding: utf-8 -*-
"""Отправка ветки dev на GitHub с машины владельца (там живёт менеджер учёток)."""
import os, subprocess, sys

КОРЕНЬ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ОТЧЁТ = os.path.join(КОРЕНЬ, "data", "git_push_report.txt")

def запуск(*аргументы, окружение=None):
    среда = dict(os.environ)
    if окружение:
        среда.update(окружение)
    п = subprocess.run(["git"] + list(аргументы), cwd=КОРЕНЬ, env=среда,
                       capture_output=True, text=True, errors="replace", timeout=240)
    return п.returncode, (п.stdout or "") + (п.stderr or "")

строки = []
for имя, арг in (("версия", ("--version",)),
                 ("ветка", ("rev-parse", "--abbrev-ref", "HEAD")),
                 ("голова", ("log", "--oneline", "-1")),
                 ("хелпер", ("config", "--get", "credential.helper"))):
    код, текст = запуск(*арг)
    строки.append("[%s] rc=%d %s" % (имя, код, текст.strip()))

код, текст = запуск("push", "origin", "dev")
строки.append("[push] rc=%d\n%s" % (код, текст.strip()))

if код != 0:
    код2, текст2 = запуск("push", "origin", "dev", окружение={"GIT_TERMINAL_PROMPT": "0"})
    строки.append("[push2] rc=%d\n%s" % (код2, текст2.strip()))

os.makedirs(os.path.dirname(ОТЧЁТ), exist_ok=True)
with open(ОТЧЁТ, "w", encoding="utf-8") as ф:
    ф.write("\n".join(строки))
print("\n".join(строки))
