"""ВЫКЛЮЧИТЬ «ВЫДЕЛЕНИЕ МЫШЬЮ» У КОНСОЛИ САЙКИ, НЕ ПЕРЕЗАПУСКАЯ ЕЁ.

Зачем: в режиме QuickEdit один клик по окну консоли переводит её в
состояние «Выбрать» — Windows блокирует запись в stdout, и Сайка
замирает на первом же print. Снаружи это неотличимо от смерти сервера.

Как это работает без перезапуска: скрипт запускается ЧЕРЕЗ саму Сайку
(канал команд, cmd=runpy) и наследует её консоль. Значит SetConsoleMode
здесь меняет режим ровно того окна, в котором она живёт.

Постоянное лекарство лежит в anamorf/main._unstick_console — оно
срабатывает при каждом старте. Этот скрипт нужен один раз, для уже
запущенной копии.
"""
import ctypes
import os

QUICK_EDIT, EXTENDED = 0x0040, 0x0080

if os.name != "nt":
    raise SystemExit("не Windows — нечего чинить")

k32 = ctypes.windll.kernel32
h = k32.GetStdHandle(-10)                     # STD_INPUT_HANDLE
mode = ctypes.c_uint32()
if not h or not k32.GetConsoleMode(h, ctypes.byref(mode)):
    raise SystemExit("консоли нет (запущено без окна) — режим не меняю")

before = mode.value
new = (before | EXTENDED) & ~QUICK_EDIT
ok = bool(k32.SetConsoleMode(h, new))
print(f"режим консоли: было 0x{before:04X}, стало 0x{new:04X}, "
      f"применено: {'да' if ok else 'НЕТ'}")
print("выделение мышью " + ("выключено" if ok and not (new & QUICK_EDIT)
                            else "осталось как было"))
