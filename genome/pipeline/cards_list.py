# -*- coding: utf-8 -*-
"""Показать все карточки в share/: кто, сколько улик, когда, есть ли картинка."""
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ДОЛЯ = pathlib.Path(__file__).resolve().parent.parent / "share"
строки = []
for f in sorted(ДОЛЯ.glob("*.genome.json")):
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        print("не читается:", f.name, str(e)[:60]); continue
    m = d.get("meta") or {}
    улик = len((m.get("evidence") or []))
    строки.append((улик, f.stem, m.get("name", "?"), m.get("kind", "?"),
                   len(d.get("genome") or {}), bool(d.get("avatar")),
                   (m.get("alias") or "")[:28], d.get("exported", "")[:16]))
for улик, ид, имя, вид, генов, есть_лицо, псевдо, когда in sorted(строки, key=lambda x: (x[2].lower(), -x[0])):
    print(f"{имя:<16} {вид:<9} улик {улик:>4} · генов {генов:>3} · "
          f"{'лицо' if есть_лицо else '  — '} · {когда} · {ид}  «{псевдо}»")
print("\nвсего карточек:", len(строки))
