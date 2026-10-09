# -*- coding: utf-8 -*-
"""
[ШАГ 3] Свод: улики → геном (chars/<id>/genome.json)

Формула слияния (спека §9, Наблюдение): улики по гену идут по порядку корпуса,
    v' = (v·c + v_new·c_new) / (c + c_new)        — новое значение тянет пропорционально уверенности
    c' = min(1, c + c_new·(1 − c))                 — уверенность растёт с повторами, единичная улика двигает мало
Спор: если |v_new − v| > 0.6 при c > 0.5 — ген помечается «спорный», обе улики остаются видны.
Гены без улик остаются серыми (0, 0) — не заполняются наугад.

Выход genome.json: {"<ген>": [v, c, [[kind, "цитата · источник"], …], "spor"?]}, статистика печатается и пишется в stats.json.
Запуск: python aggregate.py <id> [--merge-into другой_genome.json] (досъёмка dyn поверх готового генома)
"""
import json, pathlib, argparse, collections

def merge(v, c, vn, cn):
    if c == 0: return vn, cn, False
    spor = abs(vn - v) > 0.6 and c > 0.5
    return (v * c + vn * cn) / (c + cn), min(1.0, c + cn * (1 - c)), spor

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("id"); ap.add_argument("--merge-into"); a = ap.parse_args()
    cdir = pathlib.Path("chars") / a.id
    ev = [json.loads(l) for l in (cdir / "evidence.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    base = json.loads(pathlib.Path(a.merge_into).read_text(encoding="utf-8")) if a.merge_into else {}
    G = {k: [x[0], x[1], list(x[2]), *(x[3:])] for k, x in base.items()}
    by = collections.defaultdict(list)
    for e in ev: by[e["g"]].append(e)
    spor_n = 0
    for g, L in by.items():
        v, c, evid, spor = (G.get(g, [0, 0, [], False]) + [False])[:4]
        seen = set(x[1] for x in evid)
        for e in L:
            q = f'{e["q"]} — {e["src"]}'
            if q in seen: continue
            v, c, s = merge(v, c, e["v"], e["c"]); spor = spor or s
            evid.append([e["kind"], q]); seen.add(q)
        G[g] = [round(v, 2), round(c, 2), evid] + (["spor"] if spor else [])
        spor_n += bool(spor)
    (cdir / "genome.json").write_text(json.dumps(G, ensure_ascii=False, indent=0), encoding="utf-8")
    genes = json.loads((pathlib.Path(__file__).parent / "genes.json").read_text(encoding="utf-8"))
    total = sum(len(b["genes"]) for b in genes); captured = sum(1 for x in G.values() if x[1] > 0)
    conf = sum(x[1] for x in G.values() if x[1] > 0) / max(1, captured)
    per_block = {b["block"]: f"{sum(1 for g in b['genes'] if G.get(g['id'],[0,0])[1]>0)}/{len(b['genes'])}" for b in genes}
    st = {"улик": len(ev), "снято": captured, "всего": total, "уверенность": round(conf, 2), "спорных": spor_n, "по_блокам": per_block}
    (cdir / "stats.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(st, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
