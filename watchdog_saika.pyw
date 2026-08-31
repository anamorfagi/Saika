"""СТОРОЖ-СУПЕРВИЗОР САЙКИ. Чтобы прога никогда не падала насовсем.

27.08.2026, владелец: «сделай так, чтобы прога никогда не падала… делай
себе скрипт, который сможет перезапустить exe». Живёт ОТДЕЛЬНЫМ процессом
вне Сайки — переживает любое её падение, включая битую правку кода.

Что делает:
  • раз в 5 с стучится на порт Сайки;
  • три молчания подряд — поднимает ANAMORF.exe;
  • если после трёх подъёмов подряд она так и не встала (битый код) —
    ОТКАТЫВАЕТ код из code_backup и поднимает снова. Так «мигающий цикл
    падений» лечится сам, без человека.
  • пока Сайка жива и стабильна минуту — обновляет code_backup её текущим
    кодом (значит откат всегда на последнюю РАБОЧУЮ версию).

Один экземпляр держит замок на сокете. Логи — data/logs/watchdog.log.
"""
import os, shutil, socket, subprocess, sys, time

ROOT   = os.path.dirname(os.path.abspath(__file__))
EXE    = os.path.join(ROOT, "ANAMORF.exe")
APP    = os.path.join(ROOT, "app")
BACKUP = os.path.join(ROOT, "code_backup")
PORT, LOCK = 8765, 8759
CHECK_S, MISSES, WARMUP_S = 5.0, 3, 45.0
# ОТКАТ — КРАЙНЯЯ МЕРА, А НЕ РЕАКЦИЯ НА ТРИ ТИШИНЫ (27.08.2026). Три
# молчания подряд бывают и когда человек просто закрывает окно несколько
# раз (метку он ставит, но между стартами она снимается). Порог поднят, а
# после отката бэкап не обновляется десять минут — иначе откатанный код
# сам себя объявляет «последней рабочей версией» и правки уже не вернуть.
FAIL_ROLLBACK = 6          # столько неудачных подъёмов подряд -> откат
STABLE_S = 60.0            # столько живёт стабильно -> обновить бэкап
QUIET_AFTER_ROLLBACK_S = 600.0


# ═══ ОТКРЫТЫЙ ПОРТ — ЕЩЁ НЕ ЖИЗНЬ (27.08.2026) ═══
# Живой случай, стоивший владельцу часа: приложение зависло на старте
# (лог замер сразу после подъёма Vosk), но HTTP-сокет остался открыт и
# отвечал за 47 мс. Сторож проверял только порт, считал, что всё хорошо,
# и не поднимал её — а окно висело мёртвой оболочкой: движок слуха не
# выбран, канал команд молчит, ответить она не может.
#
# Поэтому теперь спрашиваем два раза: открыт ли порт И ШЕВЕЛИТСЯ ли она.
# Признак жизни — растущий лог: живая Сайка пишет в него постоянно, а
# зависшая не пишет ничего. Порог берём с запасом, чтобы не будить её
# из-за тихой минуты без событий.
#
# 180с ОКАЗАЛОСЬ МАЛО (30.08.2026). На практике Сайка спокойно молчит
# в логе дольше трёх минут, когда просто нет новых звуков/событий —
# это не зависание. Сторож принимал тишину за смерть и поднимал
# ANAMORF.exe заново поверх уже живого и открытого окна (человек видел
# «вторую копию» программы). Само окно теперь защищено отдельным замком
# (см. _acquire_window_lock в launcher/main.py) — вторая копия больше не
# нарисуется, даже если сторож ошибётся. Но ошибаться реже — тоже дело:
# порог поднят до 10 минут, это всё ещё намного меньше, чем нужно для
# отката (FAIL_ROLLBACK попыток), и настоящее зависание он ловит так же
# надёжно.
HEARTBEAT_S = 600.0
LOGF = os.path.join(ROOT, "logs", "saika.log")


def _breathing():
    """Растёт ли лог. Нет файла — не судим, пусть решает порт."""
    try:
        if not os.path.exists(LOGF):
            return True
        return (time.time() - os.path.getmtime(LOGF)) < HEARTBEAT_S
    except OSError:
        return True


def alive(port):
    try:
        with socket.create_connection(("127.0.0.1", port), 1.5):
            pass
    except OSError:
        return False
    if not _breathing():
        log("порт отвечает, но лог не растёт %.0f с — считаю зависшей"
            % HEARTBEAT_S)
        return False
    return True


def only_one():
    global _l
    _l = socket.socket()
    try:
        _l.bind(("127.0.0.1", LOCK)); _l.listen(1); return True
    except OSError:
        return False


def log(m):
    try:
        p = os.path.join(ROOT, "data", "logs", "watchdog.log")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "a", encoding="utf-8").write(time.strftime("%Y-%m-%d %H:%M:%S ") + m + "\n")
    except Exception:
        pass


# ══ ЗАКРЫТИЕ РУКАМИ — НЕ ПАДЕНИЕ (27.08.2026, владелец) ══
# Сторож существует ради одного случая: правка уронила процесс. Всё
# остальное время он обязан молчать. Отличить закрытие от падения снаружи
# нельзя — порт в обоих случаях мёртв, — поэтому Сайка сама кладёт метку
# при нормальном выходе. Есть метка — человек закрыл: не поднимаем и
# уходим совсем, чтобы не висеть фоном после закрытой программы.
QUITF = os.path.join(ROOT, "data", "quit.flag")


def closed_by_human():
    return os.path.exists(QUITF)


def raise_saika():
    subprocess.Popen([EXE], cwd=ROOT, creationflags=0x00000008)  # DETACHED


def snapshot():
    """Сохранить текущий рабочий код как слот отката."""
    try:
        for part in ("anamorf", "ui"):
            src, dst = os.path.join(APP, part), os.path.join(BACKUP, part)
            if os.path.isdir(src):
                shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst)
        log("бэкап кода обновлён (рабочая версия)")
    except Exception as e:
        log("бэкап не удался: %s" % e)


def keep_broken():
    """Отложить ТЕКУЩИЙ код в сторону перед откатом (27.08.2026).

    Откат — это стирание. Сегодня он стёр несколько часов правок: человек
    трижды закрыл программу руками, сторож трижды поднял её, счёл «не
    встаёт» и вернул код из бэкапа, а через минуту записал возвращённое
    как «последнюю рабочую версию». Ни строчки об этом в чате, ни копии.
    Теперь перед откатом текущее состояние ложится в code_broken/ —
    вернуть его можно обычным копированием."""
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
    """Вернуть последний рабочий код в app/."""
    keep_broken()
    try:
        for part in ("anamorf", "ui"):
            src, dst = os.path.join(BACKUP, part), os.path.join(APP, part)
            if os.path.isdir(src):
                shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst)
        log("ОТКАТ: код возвращён на последнюю рабочую версию")
        return True
    except Exception as e:
        log("откат не удался: %s" % e); return False


# ═══ ПЕРВЫЙ ПОДЪЁМ — ХОЛОДНЫЙ, А НЕ ГОРЯЧИЙ (30.08.2026) ═══
# START_SAIKA.bat запускает ANAMORF.exe и сторожа ОДНОВРЕМЕННО. WARMUP_S
# (45с) рассчитан на подъём ПОСЛЕ падения — там всё уже тёплое, модели
# прогреты диском/кэшем ОС. А самый первый холодный старт — с нуля грузятся
# STT/TTS/голосовые модели — легко занимает больше, чем MISSES*CHECK_S=15с,
# которые сторож раньше готов был ждать даже в первый раз. Итог живьём:
# человек запускает .bat, первая ANAMORF.exe ещё грузится, а сторож уже
# решил «не встаёт» и поднял вторую — два окна сразу при каждом старте.
# Пока Сайку ни разу не видели живой — не поднимаем никого, только считаем
# промахи после того, как истёк щедрый потолок (на случай, если она и
# правда не встаёт, а не просто долго грузится).
BOOT_GRACE_S = 180.0


def main():
    if not only_one():
        return
    log("сторож-супервизор на посту")
    miss = fails = 0
    stable_since = 0.0
    rolled_at = 0.0
    booted = False
    boot_deadline = time.time() + BOOT_GRACE_S
    while True:
        time.sleep(CHECK_S)
        if alive(PORT):
            booted = True
            miss = fails = 0
            if not stable_since:
                stable_since = time.time()
            elif time.time() - stable_since > STABLE_S:
                if time.time() - rolled_at < QUIET_AFTER_ROLLBACK_S:
                    continue          # свежий откат бэкапом не закрепляем
                snapshot(); stable_since = time.time() + 1e9  # раз за сессию
            continue
        if closed_by_human():
            log("человек закрыл программу — не поднимаю, ухожу")
            return
        if not booted and time.time() < boot_deadline:
            continue          # первый холодный подъём ещё может идти
        stable_since = 0.0
        miss += 1
        if miss < MISSES:
            continue
        miss = 0
        if not os.path.exists(EXE):
            log("нет " + EXE); continue
        fails += 1
        if fails >= FAIL_ROLLBACK:
            log("Сайка не встаёт %d раз подряд — откатываю код" % fails)
            rollback(); fails = 0; rolled_at = time.time()
        try:
            raise_saika(); log("подняли ANAMORF.exe (попытка %d)" % (fails or 1))
        except Exception as e:
            log("поднять не вышло: %s" % e)
        time.sleep(WARMUP_S)


if __name__ == "__main__":
    main()
