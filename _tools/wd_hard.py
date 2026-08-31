# -*- coding: utf-8 -*-
"""Откат кода не должен молча съедать работу."""
import io, sys
p = sys.argv[1]
s = io.open(p, encoding='utf-8').read()

a = """def rollback():
    \"\"\"Вернуть последний рабочий код в app/.\"\"\"
    try:"""
b = """def keep_broken():
    \"\"\"Отложить ТЕКУЩИЙ код в сторону перед откатом (27.08.2026).

    Откат — это стирание. Сегодня он стёр несколько часов правок: человек
    трижды закрыл программу руками, сторож трижды поднял её, счёл «не
    встаёт» и вернул код из бэкапа, а через минуту записал возвращённое
    как «последнюю рабочую версию». Ни строчки об этом в чате, ни копии.
    Теперь перед откатом текущее состояние ложится в code_broken/ —
    вернуть его можно обычным копированием.\"\"\"
    try:
        for part in ("anamorf", "ui"):
            src = os.path.join(APP, part)
            dst = os.path.join(ROOT, "code_broken", part)
            if os.path.isdir(src):
                shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst)
        log("текущий код отложен в code_broken/ — откат ничего не потерял")
    except Exception as e:
        log("отложить текущий код не вышло: %s" % e)


def rollback():
    \"\"\"Вернуть последний рабочий код в app/.\"\"\"
    keep_broken()
    try:"""
assert s.count(a) == 1, 'rollback'
s = s.replace(a, b)

# после отката не объявляем откатанное «рабочим» сразу
a2 = """FAIL_ROLLBACK = 3          # столько неудачных подъёмов подряд -> откат
STABLE_S = 60.0            # столько живёт стабильно -> обновить бэкап"""
b2 = """# ОТКАТ — КРАЙНЯЯ МЕРА, А НЕ РЕАКЦИЯ НА ТРИ ТИШИНЫ (27.08.2026). Три
# молчания подряд бывают и когда человек просто закрывает окно несколько
# раз (метку он ставит, но между стартами она снимается). Порог поднят, а
# после отката бэкап не обновляется десять минут — иначе откатанный код
# сам себя объявляет «последней рабочей версией» и правки уже не вернуть.
FAIL_ROLLBACK = 6          # столько неудачных подъёмов подряд -> откат
STABLE_S = 60.0            # столько живёт стабильно -> обновить бэкап
QUIET_AFTER_ROLLBACK_S = 600.0"""
assert s.count(a2) == 1, 'consts'
s = s.replace(a2, b2)

a3 = """    miss = fails = 0
    stable_since = 0.0
    while True:"""
b3 = """    miss = fails = 0
    stable_since = 0.0
    rolled_at = 0.0
    while True:"""
assert s.count(a3) == 1, 'vars'
s = s.replace(a3, b3)

a4 = """            elif time.time() - stable_since > STABLE_S:
                snapshot(); stable_since = time.time() + 1e9  # раз за сессию"""
b4 = """            elif time.time() - stable_since > STABLE_S:
                if time.time() - rolled_at < QUIET_AFTER_ROLLBACK_S:
                    continue          # свежий откат бэкапом не закрепляем
                snapshot(); stable_since = time.time() + 1e9  # раз за сессию"""
assert s.count(a4) == 1, 'snapshot guard'
s = s.replace(a4, b4)

a5 = """            log("Сайка не встаёт %d раз подряд — отткатываю код" % fails)
            rollback(); fails = 0"""
b5 = """            log("Сайка не встаёт %d раз подряд — откатываю код" % fails)
            rollback(); fails = 0; rolled_at = time.time()"""
assert s.count(a5) == 1, 'rollback call'
s = s.replace(a5, b5)

io.open(p, 'w', encoding='utf-8').write(s)
print('ok')
