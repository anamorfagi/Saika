import numpy as np
V = dict(FILM_VECS); pids = [p for p in sorted(V, key=lambda p: (int(str(p).split("_")[0]), str(p))) if "who" in V[p] and (V[p].get("sec") or 0) >= 1.0]
same, diff = [], []
for a, b in zip(pids, pids[1:]):
    va = np.asarray(V[a]["v"], np.float32); vb = np.asarray(V[b]["v"], np.float32)
    c = float(va @ vb / (np.linalg.norm(va) * np.linalg.norm(vb) + 1e-9))
    za = (V[a].get("who") or "").startswith("зуб"); zb = (V[b].get("who") or "").startswith("зуб")
    if za and zb: same.append(c)
    elif za != zb: diff.append(c)
def q(v, p): v = sorted(v); return v[int(len(v) * p)] if v else None
out = "соседние реплики: зуб→зуб n=%d медиана %.2f p10 %.2f p25 %.2f | зуб↔фильм n=%d медиана %.2f p75 %.2f p90 %.2f" % (
    len(same), q(same, .5), q(same, .1), q(same, .25), len(diff), q(diff, .5), q(diff, .75), q(diff, .9))
open(r"C:\AI\Saika\data\pair_cos.txt", "w", encoding="utf-8").write(out)
