# Очистка эталона от чужих отпечатков: оставить главный сгусток.
import numpy as np
from anamorf import voiceprint as v
NAME = "зубарев"
sp = v.S.reg.speakers.get(NAME)
out = []
if sp is not None:
    X = np.asarray(sp["embs"], np.float32); n0 = len(X)
    Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    S = Xn @ Xn.T
    # итеративно: центр -> выкинуть дальние (< 0.55 к центру) -> пересчитать
    keep = np.ones(len(X), bool)
    for _ in range(5):
        c = Xn[keep].mean(0); c /= np.linalg.norm(c) + 1e-9
        sims = Xn @ c
        newkeep = sims >= 0.55
        if newkeep.sum() < 8: break
        if (newkeep == keep).all(): break
        keep = newkeep
    c = Xn[keep].mean(0); c /= np.linalg.norm(c) + 1e-9
    out.append(f"{NAME}: было {n0}, оставлено {int(keep.sum())}, плотность {float((Xn[keep] @ c).mean()):.2f}, выброшенные sims: {np.round((Xn @ c)[~keep], 2).tolist()}")
    sp["embs"] = X[keep]; sp["_c"] = None
    try:
        v.S.reg.save(force=True); out.append("сохранено")
    except Exception as e:
        out.append("save: " + repr(e))
else:
    out.append("нет эталона")
open(r"C:\AI\Saika\data\clean_name.txt", "w", encoding="utf-8").write("\n".join(out))
