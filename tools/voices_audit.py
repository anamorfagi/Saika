# -*- coding: utf-8 -*-
"""Насколько «рыхлые» эталоны голосов (06.09.2026).

Владелец: «приём голоса вообще нормально по тембру не определяет» — в
ленте все реплики подряд идут как «Голос 5».

Гипотеза, которую проверяем: дело не в кодировщике (он людей разделяет,
это уже замерено — косинусы между кластерами 0.12–0.38), а в ЭТАЛОНЕ.
«Голос 5» набирался месяцами с роликов и кино: в нём лежат образцы
разных людей. Центроид такого эталона — не человек, а облако, и на него
похоже всё подряд.

Меряем разброс внутри каждого эталона: средний косинус образца к
центроиду. У настоящего одного человека он высокий (0.8+). У сборной
солянки — низкий."""
import io, os, sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); os.chdir(str(ROOT))
import numpy as np
from anamorf import voiceprint as vp

O=[]
def say(*a): print(" ".join(str(x) for x in a)); O.append(" ".join(str(x) for x in a))

reg = vp.S.reg
say("голосов в реестре: %d" % len(reg.speakers))
say("")
say("%-12s %6s %7s %8s %8s  %s" % ("имя","обр.","узнан","плотность","мин","что это"))
rows=[]
for nm, v in reg.speakers.items():
    X = np.asarray(v.get("embs"), np.float32)
    if X is None or not len(X): continue
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    c = X.mean(0); c /= (np.linalg.norm(c) + 1e-9)
    sim = X @ c
    n_heard = int((reg.stat.get(nm) or {}).get("n", 0) or 0)
    rows.append((float(sim.mean()), nm, len(X), n_heard, float(sim.min()),
                 bool(v.get("auto")), bool(v.get("owner"))))
rows.sort()
for m, nm, n, heard, mn, auto, own in rows:
    kind = "владелец" if own else ("сама завела" if auto else "записан вручную")
    flag = "  <== СОЛЯНКА" if m < 0.70 else ""
    say("%-12s %6d %7d %8.2f %8.2f  %s%s" % (nm[:12], n, heard, m, mn, kind, flag))
say("")
say("плотность = средний косинус образца к центроиду эталона.")
say("У одного человека обычно 0.80+. Ниже 0.70 — в эталоне несколько разных людей.")
io.open(ROOT/"data"/"voices_audit.txt","w",encoding="utf-8").write("\n".join(O))
