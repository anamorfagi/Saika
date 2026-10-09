#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
presets_survey_full.py — делает 20 образов опроса ЭТАЛОНАМИ: заполнен каждый человеческий ген (348).

Слои (сильный перекрывает слабый):
  1. оси образа (14 чисел, etalon_axes.py) → все 348 генов, c 0.6, улика k «эталон: оси …»
  2. ядро образа (12–13 генов из presets_survey.py) → c 0.85, улика k «ядро образа»
nat.* и beast.* не заполняются: для вида «персонаж» студия показывает их «не применимо».
Аватар, сделанный comfy_avatars.py, сохраняется.
"""
import json, pathlib, datetime, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import presets_survey as PS, etalon_axes as EA, persona as P

AXN = {"W":"тепло","D":"напор","A":"энергия","V":"оптимизм","X":"общительность","O":"открытость","C":"собранность",
       "N":"ранимость","H":"честность","I":"импульсивность","R":"маска","S":"чувственность","K":"рассудочность","P":"игривость"}

def ax(s):  # «W-.3 D.2 …» → {'W':-.3,'D':.2}
    return {t[0]: float(t[1:]) for t in s.split()}

AX = {
 "obraz_holodnaya":      ax("W-.3 D.2 A-.4 V-.1 X-.8 O0 C.4 N-.3 H.3 I-.4 R.8 S-.3 K.4 P-.5"),
 "obraz_pylkaya":        ax("W.3 D.6 A.8 V.4 X.6 O.2 C-.3 N.2 H.6 I.8 R-.8 S.3 K-.2 P.3"),
 "obraz_oderzhimaya":    ax("W.4 D.3 A.3 V-.3 X-.2 O-.1 C.2 N.8 H-.5 I.4 R.4 S.6 K.1 P-.2"),
 "obraz_geroicheskaya":  ax("W.5 D.7 A.7 V.6 X.4 O.4 C.2 N-.6 H.6 I.4 R-.3 S.1 K.1 P.3"),
 "obraz_holod_dobraya":  ax("W.7 D.2 A-.2 V0 X-.4 O0 C.5 N.2 H.5 I-.3 R.8 S0 K.4 P-.3"),
 "obraz_tomnaya":        ax("W.5 D-.1 A-.7 V.5 X.3 O.4 C-.4 N-.5 H.2 I0 R-.1 S.8 K0 P.5"),
 "obraz_zagadochnaya":   ax("W0 D.2 A-.3 V0 X-.4 O.8 C.1 N-.3 H-.2 I-.2 R.8 S.3 K.6 P.2"),
 "obraz_bodraya":        ax("W.6 D.2 A.8 V.9 X.9 O.5 C-.2 N-.5 H.5 I.5 R-.8 S.2 K-.2 P.7"),
 "obraz_elegantnaya":    ax("W.3 D.5 A-.4 V.2 X.2 O.1 C.9 N-.4 H.4 I-.7 R.6 S.4 K.2 P-.3"),
 "obraz_ostroumnaya":    ax("W.3 D.3 A.5 V.5 X.6 O.7 C-.2 N-.4 H.2 I.4 R-.2 S.2 K.5 P.9"),
 "obraz_zastenchivaya":  ax("W.5 D-.7 A-.4 V-.1 X-.8 O.3 C.3 N.6 H.6 I-.4 R.4 S.1 K.4 P-.2"),
 "obraz_zrelaya":        ax("W.5 D.5 A-.3 V.4 X.2 O.3 C.6 N-.7 H.6 I-.6 R.3 S.3 K.7 P.1"),
 "obraz_myagkaya":       ax("W.9 D-.3 A-.3 V.4 X.3 O.3 C.3 N.2 H.7 I-.4 R-.3 S.3 K.4 P.1"),
 "obraz_kovarnaya":      ax("W-.4 D.5 A.2 V.1 X.3 O.6 C.2 N-.4 H-.8 I0 R.5 S.4 K.7 P.6"),
 "obraz_uyazvimaya":     ax("W.5 D-.6 A.1 V-.4 X0 O.2 C-.1 N.9 H.6 I.3 R-.5 S.3 K0 P-.2"),
 "obraz_chestnaya":      ax("W.8 D.1 A.2 V.5 X.4 O.2 C.4 N0 H.9 I0 R-.4 S.2 K.2 P.2"),
 "obraz_skrytaya_strast":ax("W.4 D.2 A-.2 V0 X-.3 O.3 C.6 N.3 H.3 I-.3 R.8 S.8 K.4 P-.3"),
 "obraz_vlastnaya":      ax("W-.1 D.9 A.4 V.4 X.4 O.2 C.6 N-.7 H-.2 I0 R.5 S.4 K.5 P0"),
 "obraz_naivnaya":       ax("W.7 D-.3 A.5 V.8 X.6 O.5 C-.3 N.2 H.8 I.5 R-.7 S-.2 K-.7 P.5"),
 "obraz_rassuditelnaya": ax("W.2 D.1 A-.6 V.2 X-.3 O.5 C.4 N-.5 H.5 I-.8 R.1 S-.2 K.9 P0"),
}

def why(g, axes):
    parts = sorted(((w * axes.get(a, 0), a, w) for a, w in EA.LOAD[g]), key=lambda x: -abs(x[0]))
    return "эталон: " + ", ".join(f"{AXN[a]} {axes.get(a,0):+.1f}×{w:+.1f}" for c, a, w in parts if abs(c) >= .02)[:160] or "эталон: на этой оси тип как у всех (0)"

def build(p):
    axes = AX[p["id"]]; base = EA.full_genome(axes)
    miss = [g for g in base if g not in P.IDS]
    G = {g: [v, 0.6, [["k", why(g, axes)]]] for g, v in base.items() if g in P.IDS}
    for g, v in p["main"].items():
        G[g] = [v, 0.85, [["k", f"ядро образа «{p['name']}»: {v:+.1f}"]]]
    obj, *_ = PS.make(p)
    obj["genome"] = G; obj["genes_captured"] = len(G)
    obj["meta"]["alias"] = "эталон образа"; obj["meta"]["kind"] = "синтез"   # не персонаж: у эталона нет истории-первоисточника
    obj["meta"]["method"] = f"синтез · эталон: 348 генов из 14 осей образа (c 0.6) + ядро {len(p['main'])} генов (c 0.85)"
    obj["meta"]["axes"] = {AXN[a]: axes.get(a, 0) for a in EA.AXES}
    return obj, miss

if __name__ == "__main__":
    out = pathlib.Path(__file__).parent.parent / "share"
    for p in PS.PRESETS:
        obj, miss = build(p); f = out / f"{p['id']}.genome.json"
        if f.exists():
            old = json.loads(f.read_text(encoding="utf-8"))
            for k in ("avatar",):
                if old.get(k): obj[k] = old[k]
            if old.get("meta", {}).get("avatar_gen"): obj["meta"]["avatar_gen"] = old["meta"]["avatar_gen"]
        f.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        nz = sum(1 for v in obj["genome"].values() if abs(v[0]) >= .15)
        print(f"{p['id']:24} генов {len(obj['genome'])}  выражено (|x|≥.15) {nz:3}  ава {'да' if obj.get('avatar') else 'НЕТ'}" + (f"  нет в геноме: {miss}" if miss else ""))
