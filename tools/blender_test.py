# -*- coding: utf-8 -*-
"""Живая проверка канала в Блендер + разбор аддона (05.09.2026)."""
import io, sys, re, glob, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
O = []
def say(*a): O.append(" ".join(str(x) for x in a))

ADDON = (r"C:\Users\QWADRO\AppData\Roaming\Blender Foundation\Blender"
         r"\5.2\scripts\addons\blendermcp_addon.py")
try:
    t = io.open(ADDON, encoding="utf-8", errors="ignore").read()
    say("=== АДДОН ===")
    say("операторы: " + ", ".join(sorted(set(
        re.findall(r'bl_idname\s*=\s*["\']([\w.]+)["\']', t))))[:400])
    say("свойства : " + ", ".join(sorted(set(
        re.findall(r'blendermcp[\w]*', t))))[:400])
    say("порт по умолчанию: " + str(re.findall(r'default\s*=\s*(\d{4})', t)[:3]))
except Exception as e:
    say("аддон не прочитался: %r" % e)

say("")
say("=== КАНАЛ ===")
try:
    from anamorf import blender_hands as bh
    say("жив: %s" % bh.alive())
    if bh.alive():
        say("сцена: " + bh.scene()[:500])
        say("")
        say("--- проба: спрошу версию и имя файла (ничего не меняю)")
        say(bh.run("import bpy\n"
                   "print('версия', bpy.app.version_string,"
                   " '| файл', bpy.data.filepath or 'не сохранён',"
                   " '| объектов', len(bpy.data.objects))\n"))
except Exception as e:
    import traceback; say(traceback.format_exc())

io.open(ROOT / "data" / "blender_test.txt", "w",
        encoding="utf-8").write("\n".join(O))
