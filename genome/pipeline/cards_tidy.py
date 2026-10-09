# -*- coding: utf-8 -*-
"""Оставить по одной лучшей карточке на персонажа, слабые убрать в share/_trash.

Каждый прогон исследования создаёт новую карточку со своим идентификатором, и
после ночи доводки алгоритма на Карен и Джарвиса накопилось по нескольку штук.
Ничего не удаляется навсегда: файлы переезжают в _trash, вернуть можно руками.

Лучшей считается карточка с наибольшим числом улик; при равенстве — свежая.
Ручные карточки (без улик и не из исследования) не трогаются вовсе.
"""
import json
import pathlib
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ЗДЕСЬ = pathlib.Path(__file__).resolve().parent
ГЕНОМ = ЗДЕСЬ.parent
ДОЛЯ = ГЕНОМ / "share"
КОРЗИНА = ДОЛЯ / "_trash"
ПРОБА = "--проба" in sys.argv or "--dry" in sys.argv


def сведения(файл):
    d = json.loads(файл.read_text(encoding="utf-8"))
    m = d.get("meta") or {}
    return {"файл": файл, "имя": (m.get("name") or "?").strip(),
            "улик": len(m.get("evidence") or []),
            "генов": len(d.get("genome") or {}),
            "когда": d.get("exported", ""),
            "исследование": файл.stem.startswith("research_")}


карточки = []
for f in sorted(ДОЛЯ.glob("*.genome.json")):
    try:
        карточки.append(сведения(f))
    except Exception as e:
        print("не читается:", f.name, str(e)[:60])

по_именам = {}
for к in карточки:
    по_именам.setdefault(к["имя"].lower(), []).append(к)

убрано = 0
for имя, группа in sorted(по_именам.items()):
    if len(группа) < 2:
        continue
    # Ручную карточку и карточку из исследования не считаем дублями друг друга:
    # у них разное происхождение, и владелец мог вести свою отдельно.
    свои = [к for к in группа if к["исследование"]]
    if len(свои) < 2:
        continue
    свои.sort(key=lambda к: (-к["улик"], -к["генов"], к["когда"]), reverse=False)
    лучшая, слабые = свои[0], свои[1:]
    print(f"\n{лучшая['имя']}: оставляю {лучшая['файл'].stem} "
          f"({лучшая['улик']} улик, {лучшая['генов']} генов)")
    for к in слабые:
        print(f"   убираю {к['файл'].stem} ({к['улик']} улик, {к['генов']} генов)")
        if not ПРОБА:
            КОРЗИНА.mkdir(exist_ok=True)
            цель = КОРЗИНА / к["файл"].name
            if цель.exists():
                цель = КОРЗИНА / (к["файл"].stem + "_" + к["когда"][:10] + ".genome.json")
            shutil.move(str(к["файл"]), str(цель))
        убрано += 1

if ПРОБА:
    print(f"\nпроба: убрали бы {убрано} карточек, файлы не тронуты")
    raise SystemExit

print(f"\nубрано в _trash: {убрано}")
r = subprocess.run(["node", str(ЗДЕСЬ / "share_index.js")], capture_output=True, text=True,
                   encoding="utf-8", errors="replace", cwd=str(ГЕНОМ))
итог = (r.stdout or r.stderr).strip()[:200]
print("список:", итог)
if "0 персонажей" in итог:
    print("ВНИМАНИЕ: список собрался пустым — проверь рабочую папку")
