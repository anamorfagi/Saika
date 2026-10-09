# -*- coding: utf-8 -*-
"""ПОДНИМАТЬ КАНАЛ САМ, ПРИ КАЖДОМ СТАРТЕ БЛЕНДЕРА (05.09.2026).

Настройка автозапуска у аддона оказалась СВОЙСТВОМ СЦЕНЫ, а не
настройкой программы: она лежит внутри .blend-файла. Значит на новом
файле её нет, и кнопку снова придётся нажимать руками — то есть решения
нет.

Настоящее решение — файл в scripts/startup. Блендер выполняет всё оттуда
при каждом запуске, до открытия любого файла. Пишем туда крошечный
скрипт, который через секунду после старта зовёт штатный оператор
аддона. Одна установка — и кнопка «Connect» больше не нужна никогда."""
import io, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
O = []
def say(*a): O.append(" ".join(str(x) for x in a))

STARTUP = r'''# -*- coding: utf-8 -*-
"""Сайка: поднять канал BlenderMCP при старте Блендера.

Положено автоматически (Сайка, 05.09.2026). Смысл: сокет аддона нужен
для совместной работы, а нажимать «Connect» руками каждый раз — потеря,
которую человек справедливо считает поломкой.

Почему через таймер, а не сразу: на момент выполнения startup-скриптов
аддоны ещё не все зарегистрированы, и оператора может физически не быть.
Секундная отсрочка это решает, а несколько повторов страхуют от долгой
загрузки тяжёлых аддонов.

Ничего не ломает: если сервер уже поднят или оператора нет — тихо
выходим. Удалить — просто убрать этот файл."""
import bpy

_tries = {"n": 0}


def _start():
    _tries["n"] += 1
    try:
        sc = getattr(bpy.context, "scene", None)
        if sc is not None and getattr(sc, "blendermcp_server_running", False):
            return None                      # уже поднят — уходим
        op = getattr(bpy.ops, "blendermcp", None)
        if op is not None and hasattr(op, "start_server"):
            op.start_server()
            print("[Сайка] канал BlenderMCP поднят автоматически")
            return None
    except Exception as e:
        print("[Сайка] канал не поднялся:", e)
    return 2.0 if _tries["n"] < 6 else None   # ещё попытка, потом молчим


def register():
    bpy.app.timers.register(_start, first_interval=1.5, persistent=True)


def unregister():
    try:
        bpy.app.timers.unregister(_start)
    except Exception:
        pass
'''

CODE = '''
import bpy, os, json
d = bpy.utils.user_resource('SCRIPTS', path="startup", create=True)
p = os.path.join(d, "saika_mcp_autostart.py")
open(p, "w", encoding="utf-8").write(%r)
print(json.dumps({"written": p}, ensure_ascii=False))
''' % STARTUP

try:
    from anamorf import blender_hands as bh
    if not bh.alive():
        say("Блендер не отвечает — нечего настраивать.")
    else:
        say(bh.run(CODE, timeout=40))
except Exception:
    import traceback; say(traceback.format_exc())

io.open(ROOT / "data" / "blender_startup.txt", "w",
        encoding="utf-8").write("\n".join(O))
