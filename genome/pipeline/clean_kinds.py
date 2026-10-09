# -*- coding: utf-8 -*-
"""Убрать из карточек гены, неприменимые к виду персонажа.

Разбор предлагал модели все 383 гена подряд, без оглядки на вид, и она находила,
куда их пристроить. Эльзе-человеку достались «Ответ на угрозу», «Настороженность
к чужим» и «Защита своих» из блока природы существа. Блок после этого целиком
всплывал в спирали, и счётчик показывал 364 гена вместо 348.

Снятое не удаляется молча: по каждому гену печатается, у кого и что убрано.
Резервная копия карточки кладётся рядом с меткой времени.
"""
import json
import pathlib
import shutil
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ЗДЕСЬ = pathlib.Path(__file__).resolve().parent
ДОЛЯ = ЗДЕСЬ.parent / "share"
ПРОБА = "--проба" in sys.argv

БЛОКИ_ВИДА = {"beast": {"существо"}, "nat": {"ии"}}


def лишний(ид, вид):
    блок = ид.split(".")[0]
    кому = БЛОКИ_ВИДА.get(блок)
    return bool(кому) and (вид or "персонаж") not in кому


всего = 0
for файл in sorted(ДОЛЯ.glob("*.genome.json")):
    try:
        карта = json.loads(файл.read_text(encoding="utf-8"))
    except Exception as e:
        print("не читается:", файл.name, str(e)[:60]); continue
    вид = (карта.get("meta") or {}).get("kind", "персонаж")
    геном = карта.get("genome") or {}
    убрать = [k for k in геном if лишний(k, вид)]
    if not убрать:
        continue
    имя = (карта.get("meta") or {}).get("name", файл.stem)
    print(f"\n{имя} ({вид}) — лишних генов {len(убрать)}:")
    for k in убрать:
        зн = геном[k]
        print(f"   {k:24} {зн[0]:+.2f} уверенность {зн[1]:.2f}")
    всего += len(убрать)
    if ПРОБА:
        continue
    shutil.copy2(файл, файл.with_suffix(".bak" + time.strftime("%H%M%S")))
    for k in убрать:
        геном.pop(k, None)
    улики = (карта.get("meta") or {}).get("evidence") or []
    карта["meta"]["evidence"] = [e for e in улики if not лишний(str(e.get("g", "")), вид)]
    карта["genes_captured"] = len(геном)
    файл.write_text(json.dumps(карта, ensure_ascii=False, indent=2), encoding="utf-8")

if ПРОБА:
    print(f"\nпроба: убрали бы {всего} генов, файлы не тронуты")
else:
    print(f"\nубрано генов: {всего}")
    import subprocess
    r = subprocess.run(["node", str(ЗДЕСЬ / "share_index.js")], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", cwd=str(ЗДЕСЬ.parent))
    print("список:", (r.stdout or r.stderr).strip()[:160])
