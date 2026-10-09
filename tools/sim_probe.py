import numpy as np
from anamorf import voiceprint as v
sp = v.S.reg.speakers.get("зубарев"); X = np.asarray(sp["embs"], np.float32); X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
c = X.mean(0); c /= np.linalg.norm(c) + 1e-9
rows = []
for pid, d in sorted(FILM_VECS.items()):
    if "who" not in d: continue
    vv = np.asarray(d["v"], np.float32); vv /= np.linalg.norm(vv) + 1e-9
    rows.append((pid, d.get("who") or "-", round(float(vv @ c), 2), round(float((X @ vv).max()), 2), d.get("vtl"), d.get("text", "")[:40]))
KEYS=("подружки","друг есть","нелегко","Телесериалы","не для ме","ты где","новый игрок","возражаешь","знают друг","зарабатываете","спрасл","Две карт","Тофер")
out = ["ищу: " + repr([(pid, d.get("who"), d.get("text")[:30], next((r[2] for r in rows if r[0]==pid), None)) for pid, d in sorted(FILM_VECS.items()) if any(k in (d.get("text") or "") for k in KEYS)])] + ["зуб<0.45: " + repr([(r[2], r[5][:30]) for r in rows if r[1].startswith("зуб") and r[2] < 0.45]), "чужие>0.45: " + repr([(r[2], r[1], r[5][:30]) for r in rows if not r[1].startswith("зуб") and r[2] > 0.45])]
z = [r[2] for r in rows if r[1].startswith("зуб")]; o = [r[2] for r in rows if not r[1].startswith("зуб")]
out.append("зубарев n=%d центроид: медиана %.2f мин %.2f | остальные n=%d медиана %.2f макс %.2f" % (len(z), np.median(z), min(z), len(o), np.median(o), max(o)))
open(r"C:\AI\Saika\data\sim_probe.txt", "w", encoding="utf-8").write("\n".join(out))
