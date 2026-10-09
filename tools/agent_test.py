# -*- coding: utf-8 -*-
"""Живой прогон сценария совместной работы (05.09.2026).

Не через модель — напрямую по инструментам. Так проверяется, что РУКИ
работают, отдельно от того, догадается ли модель их позвать. Смешивать
эти два вопроса в одном тесте — верный способ полдня чинить не то."""
import io, sys, json, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
O = []
def say(*a): O.append(" ".join(str(x) for x in a))

try:
    from anamorf import project as pr
    from anamorf import blender_hands as bh
    from anamorf import pc_control as pc

    say("=== 1. ГДЕ ЗАВОДИМ ===")
    say("проводник сейчас тут:", pc.here())
    say("прошлый корень проектов:", pr.where_last() or "(нет)")

    say("")
    say("=== 2. ЗАВОДИМ ПРОЕКТ ===")
    r = pr.start("Персонаж под UE5", "новый персонаж: одежда, худи, повседневное",
                 place=pc.here())
    say(json.dumps(r, ensure_ascii=False))
    say("папка рефов:", pr.folder("рефы"))
    say("папка блендера:", pr.folder("блендер"))

    say("")
    say("=== 3. БЛЕНДЕР: НОВЫЙ ФАЙЛ В ПАПКУ ПРОЕКТА ===")
    if bh.alive():
        say(bh.new_project(pr.folder("блендер"), "персонаж"))
        say("сцена после:", bh.scene()[:220])
    else:
        say("Блендер не на связи")

    say("")
    say("=== 4. ЧТО ВИДИТ МОДЕЛЬ В ПРОМПТЕ ===")
    say(pr.for_llm())
except Exception:
    import traceback; say(traceback.format_exc())

io.open(ROOT / "data" / "agent_test.txt", "w",
        encoding="utf-8").write("\n".join(O))
