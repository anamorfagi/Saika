# -*- coding: utf-8 -*-
"""КНОПКУ «CONNECT» БОЛЬШЕ НЕ НАДО НАЖИМАТЬ РУКАМИ (05.09.2026).

Владелец: «сам коннект нужно как-то ей нажимать, чтобы можно было
подрубаться к блендеру».

Кликать по кнопке — худший из возможных путей: он зависит от того, где
окно, раскрыта ли панель и не перекрыл ли её браузер. У аддона при этом
есть собственная настройка автозапуска (`blendermcp_auto_start_server`),
которую видно прямо в его коде. Включаем её и сохраняем настройки —
дальше сервер поднимается сам при каждом старте Блендера, и нажимать
нечего.

Запасной путь, если настройки нет: файл в scripts/startup — Блендер
выполняет всё оттуда при загрузке."""
import io, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
O = []
def say(*a): O.append(" ".join(str(x) for x in a))

CODE = r'''
import bpy, json
out = {}
prefs = None
for key in ("blendermcp_addon", "blendermcp"):
    a = bpy.context.preferences.addons.get(key)
    if a is not None:
        prefs = getattr(a, "preferences", None)
        out["addon_key"] = key
        break
if prefs is not None:
    out["prefs_fields"] = [p for p in dir(prefs) if "blendermcp" in p or "auto" in p]
    for f in ("blendermcp_auto_start_server", "auto_start_server"):
        if hasattr(prefs, f):
            setattr(prefs, f, True)
            out["set_on_prefs"] = f
            break
sc = bpy.context.scene
out["scene_fields"] = [p for p in dir(sc) if "blendermcp" in p]
for f in ("blendermcp_auto_start_server",):
    if hasattr(sc, f):
        setattr(sc, f, True)
        out["set_on_scene"] = f
try:
    bpy.ops.wm.save_userpref()
    out["prefs_saved"] = True
except Exception as e:
    out["prefs_saved"] = str(e)
print(json.dumps(out, ensure_ascii=False))
'''

try:
    from anamorf import blender_hands as bh
    say("канал жив:", bh.alive())
    say(bh.run(CODE, timeout=40))
except Exception:
    import traceback; say(traceback.format_exc())

io.open(ROOT / "data" / "blender_autoconnect.txt", "w",
        encoding="utf-8").write("\n".join(O))
