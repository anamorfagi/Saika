# -*- coding: utf-8 -*-
"""Закрыл прогу — значит закрыл: сторож не воскрешает, дети умирают с ней."""
import io, sys
main_p, wd_p = sys.argv[1], sys.argv[2]

# ══ 1. main.py: метка «человек закрыл» + убийство детей ═══════════════════
s = io.open(main_p, encoding='utf-8').read()

a = '''def _on_exit():
    _close_handspc()
    _unload_llms()
    _unload_workers()'''
b = '''def _quit_flag_path():
    return DATA_ROOT / "data" / "quit.flag"


def _mark_quit_by_human():
    """ЗАКРЫЛИ РУКАМИ — ЗНАЧИТ ЗАКРЫЛИ (27.08.2026, владелец: «я никогда не
    говорил, что прога должна оживать, если я её напрямую закрываю»).

    Сторож снаружи не может отличить падение от закрытия: и там и там порт
    перестал отвечать. Разницу знаем только мы сами — нормальный выход
    проходит через atexit, падение не проходит. Поэтому на выходе кладём
    метку. Сторож, увидев её, не поднимает никого и уходит сам."""
    try:
        p = _quit_flag_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(time.time()), encoding="utf-8")
    except Exception:
        pass


def _kill_children():
    """Погасить всё, что мы породили и что переживает наше окно.

    llama-server — отдельный процесс на своём порту: он специально сделан
    так, чтобы переживать перезапуск Сайки (не греть модель заново). Но
    ЗАКРЫТИЕ — это не перезапуск: после него на карте не должно остаться
    ничего нашего."""
    try:
        from anamorf import proc_utils as _pu
        from anamorf.llm import llamacpp as _lc
        try:
            _port = int((_lc._cfg() or {}).get("port", 8771))
        except Exception:
            _port = 8771
        _pu.kill_by_port(_port, "llama-server")
    except Exception:
        pass


def _on_exit():
    _mark_quit_by_human()
    _close_handspc()
    _unload_llms()
    _unload_workers()
    _kill_children()'''
assert s.count(a) == 1, '_on_exit'
s = s.replace(a, b)

# метка снимается на каждом нормальном старте
a2 = '''    try:
        import subprocess as _sp
        wd = ROOT.parent / "watchdog_saika.pyw"'''
b2 = '''    try:
        # прошлая метка «закрыли руками» больше не действует: мы снова живы
        try:
            _quit_flag_path().unlink()
        except Exception:
            pass
        import subprocess as _sp
        wd = ROOT.parent / "watchdog_saika.pyw"'''
assert s.count(a2) == 1, 'spawn watchdog'
s = s.replace(a2, b2)
io.open(main_p, 'w', encoding='utf-8').write(s)

# ══ 2. сторож: увидел метку — не поднимает и уходит ═══════════════════════
s = io.open(wd_p, encoding='utf-8').read()

a3 = '''def raise_saika():'''
b3 = '''# ══ ЗАКРЫТИЕ РУКАМИ — НЕ ПАДЕНИЕ (27.08.2026, владелец) ══
# Сторож существует ради одного случая: правка уронила процесс. Всё
# остальное время он обязан молчать. Отличить закрытие от падения снаружи
# нельзя — порт в обоих случаях мёртв, — поэтому Сайка сама кладёт метку
# при нормальном выходе. Есть метка — человек закрыл: не поднимаем и
# уходим совсем, чтобы не висеть фоном после закрытой программы.
QUITF = os.path.join(ROOT, "data", "quit.flag")


def closed_by_human():
    return os.path.exists(QUITF)


def raise_saika():'''
assert s.count(a3) == 1, 'raise_saika'
s = s.replace(a3, b3)

a4 = '''        stable_since = 0.0
        miss += 1'''
b4 = '''        if closed_by_human():
            log("человек закрыл программу — не поднимаю, ухожу")
            return
        stable_since = 0.0
        miss += 1'''
assert s.count(a4) == 1, 'main loop'
s = s.replace(a4, b4)

a5 = '''        if alive(PORT):
            miss = fails = 0'''
b5 = '''        if alive(PORT):
            miss = fails = 0'''
assert s.count(a5) == 1
io.open(wd_p, 'w', encoding='utf-8').write(s)
print('ok')
