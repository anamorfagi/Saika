# -*- coding: utf-8 -*-
"""Разведка Блендера: где стоит, как запускается, где аддон MCP.

Владелец 05.09.2026: «блендер у меня в стиме и без запуска и выбора акка
он не запускается — нужно придумать, как ей такое запускать, а также сам
коннект нужно как-то ей нажимать, чтобы можно было подрубаться».

Ничего не меняет. Только смотрит и докладывает."""
import io
import os
import sys
import glob
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
O = []


def say(*a):
    O.append(" ".join(str(x) for x in a))


def main():
    say("=== ГДЕ БЛЕНДЕР ===")
    seen = []
    for pat in (r"C:\Program Files\Blender Foundation\*\blender.exe",
                r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
                r"D:\Steam\steamapps\common\Blender\blender.exe",
                r"D:\SteamLibrary\steamapps\common\Blender\blender.exe",
                r"E:\SteamLibrary\steamapps\common\Blender\blender.exe",
                r"C:\SteamLibrary\steamapps\common\Blender\blender.exe"):
        for f in glob.glob(pat):
            seen.append(f)
    # библиотеки Steam из конфига
    for cfg in glob.glob(r"C:\Program Files (x86)\Steam\steamapps\libraryfolders.vdf") + \
               glob.glob(r"C:\Steam\steamapps\libraryfolders.vdf"):
        try:
            t = io.open(cfg, encoding="utf-8", errors="ignore").read()
            import re
            for m in re.finditer(r'"path"\s+"([^"]+)"', t):
                base = m.group(1).replace("\\\\", "\\")
                p = os.path.join(base, "steamapps", "common", "Blender",
                                 "blender.exe")
                if os.path.exists(p):
                    seen.append(p)
        except Exception:
            pass
    for f in dict.fromkeys(seen):
        say("   " + f)
    if not seen:
        say("   (не нашла по обычным местам — поищу по живому процессу)")
    try:
        import psutil
        for pr in psutil.process_iter(["name", "exe", "cmdline"]):
            if (pr.info.get("name") or "").lower().startswith("blender"):
                say("   ЖИВОЙ: " + str(pr.info.get("exe")))
                say("   команда: " + " ".join(pr.info.get("cmdline") or [])[:300])
    except Exception as e:
        say("   psutil: %r" % e)

    say("")
    say("=== ПАПКА НАСТРОЕК И АДДОНЫ ===")
    roots = []
    ap = os.environ.get("APPDATA", "")
    if ap:
        roots += glob.glob(os.path.join(ap, "Blender Foundation", "Blender", "*"))
    for r in roots:
        say("   " + r)
        for sub in ("scripts/addons", "scripts/startup", "extensions"):
            d = os.path.join(r, sub.replace("/", os.sep))
            if os.path.isdir(d):
                names = os.listdir(d)[:40]
                say("      %s: %s" % (sub, ", ".join(names)[:300]))

    say("")
    say("=== ИЩЕМ АДДОН BLENDERMCP ===")
    hits = []
    for r in roots:
        for pat in ("scripts/addons/**/*.py", "extensions/**/*.py"):
            for f in glob.glob(os.path.join(r, pat.replace("/", os.sep)),
                               recursive=True):
                try:
                    t = io.open(f, encoding="utf-8", errors="ignore").read()
                except Exception:
                    continue
                if "blendermcp" in t.lower() or "BlenderMCP" in t:
                    hits.append(f)
    for f in dict.fromkeys(hits)[:6] if isinstance(hits, list) else []:
        say("   " + f)
    for f in list(dict.fromkeys(hits))[:3]:
        try:
            t = io.open(f, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        import re
        ops = sorted(set(re.findall(r'bl_idname\s*=\s*["\']([\w.]+)["\']', t)))
        props = sorted(set(re.findall(r'(blendermcp\w*)\s*[:=]', t)))
        say("   --- %s" % Path(f).name)
        say("       операторы: %s" % ", ".join(ops)[:300])
        say("       свойства : %s" % ", ".join(sorted(set(props)))[:300])


try:
    main()
except Exception:
    import traceback
    say(traceback.format_exc())
io.open(ROOT / "data" / "blender_probe.txt", "w",
        encoding="utf-8").write("\n".join(O))
