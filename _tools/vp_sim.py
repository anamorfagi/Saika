# -*- coding: utf-8 -*-
"""Матрица похожести автоголосов: понять, где реально проходит граница."""
import io, json, os
import numpy as np
D = r"C:\AI\Saika\build\ANAMORF-0.2.1\data\voiceprint"
meta = json.load(io.open(os.path.join(D, "meta.json"), encoding="utf-8"))
z = np.load(os.path.join(D, "state.npz"), allow_pickle=True)
keys = list(z.keys())
out = io.open(r"C:\AI\Saika\_tools\vp_sim.txt", "w", encoding="utf-8")
out.write("ключи npz: %s\n" % keys[:40])
sp = meta.get("speakers")
out.write("speakers в meta: %r\n" % (sp if not isinstance(sp, list) else sp[:40],))
cen = {}
for k in keys:
    v = z[k]
    if getattr(v, "ndim", 0) == 2 and v.shape[1] in (68, 128, 192, 256):
        c = v.mean(axis=0)
        n = np.linalg.norm(c)
        if n > 0:
            cen[k] = c / n
        out.write("%s: %s\n" % (k, v.shape))
names = sorted(cen)
out.write("\nимён с векторами: %d\n" % len(names))
for i, a in enumerate(names):
    row = []
    for b in names:
        row.append("%.2f" % float(cen[a] @ cen[b]))
    out.write("%-14s %s\n" % (a[:14], " ".join(row)))
off = []
for i, a in enumerate(names):
    for b in names[i + 1:]:
        off.append((float(cen[a] @ cen[b]), a, b))
off.sort(reverse=True)
out.write("\nтоп-25 пар:\n")
for s, a, b in off[:25]:
    out.write("  %.3f  %s <-> %s\n" % (s, a, b))
out.close()
print("ok")
