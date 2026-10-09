# -*- coding: utf-8 -*-
"""
[ОБМЕН] Файл персонажа <id>.genome.json — карточка (char.json) + геном с уликами (genome.json) в одном файле.
Формат "saika-genome/1": {"format","id","exported","meta":{…карточка…},"genome":{ген:[v,c,[[kind,"улика"],…]]},"genes_total","genes_captured"}
Тот же файл читает и пишет студия (кнопка «файл персонажа» на карточке, «загрузить файл» в «Новом персонаже»).
Запуск:  python export_char.py <id>            → chars/<id>/<id>.genome.json
         python export_char.py --import файл.genome.json   → chars/<id>/{char.json,genome.json} (потом node build_char.js <id>)
"""
import sys, json, pathlib, datetime
FORMAT = "saika-genome/1"
GENES = json.loads((pathlib.Path(__file__).parent / "genes.json").read_text(encoding="utf-8"))
TOTAL = sum(len(b["genes"]) for b in GENES)

def export(cid):
    d = pathlib.Path("chars") / cid
    meta = json.loads((d / "char.json").read_text(encoding="utf-8")); G = json.loads((d / "genome.json").read_text(encoding="utf-8"))
    genome = {k: [v[0], v[1], v[2]] for k, v in G.items() if v[1] > 0}
    meta = {k: v for k, v in meta.items() if k not in ("id",)}
    out = {"format": FORMAT, "id": cid, "exported": datetime.datetime.now().isoformat(timespec="minutes"), "studio": "pipeline",
           "genes_total": TOTAL, "genes_captured": len(genome), "meta": meta, "genome": genome}
    p = d / f"{cid}.genome.json"; p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(p, "·", len(genome), "генов ·", round(p.stat().st_size / 1024), "КБ")

def imp(path):
    obj = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    assert obj.get("format") == FORMAT, "не файл персонажа Genome Studio"
    cid = obj["id"]; d = pathlib.Path("chars") / cid; d.mkdir(parents=True, exist_ok=True)
    meta = dict(obj["meta"]); meta["id"] = cid; meta.setdefault("gender", (meta.get("voice") or {}).get("gender", "женский"))
    (d / "char.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "genome.json").write_text(json.dumps(obj["genome"], ensure_ascii=False), encoding="utf-8")
    print("→", d, "·", len(obj["genome"]), "генов; дальше: node build_char.js", cid)

if __name__ == "__main__":
    if sys.argv[1] == "--import": imp(sys.argv[2])
    else: export(sys.argv[1])
