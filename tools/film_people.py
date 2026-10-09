# Подсчёт людей в фильме по копилке FILM_VECS (pyexec внутри живого процесса).
import numpy as np, json, collections
V = dict(FILM_VECS)
pids = sorted(V)
X = np.array([V[p]["v"] for p in pids], dtype=np.float32)
X /= (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
n = len(pids)
out = [f"реплик {n}"]
if n >= 2:
    S = X @ X.T
    D = 1.0 - S
    # средняя связь, порог по косинусному расстоянию
    def agg(th):
        cl = [[i] for i in range(n)]
        while True:
            best = None
            for a in range(len(cl)):
                for b in range(a + 1, len(cl)):
                    d = D[np.ix_(cl[a], cl[b])].mean()
                    if best is None or d < best[0]:
                        best = (d, a, b)
            if best is None or best[0] > th:
                break
            d, a, b = best
            cl[a] = cl[a] + cl[b]; del cl[b]
        return cl
    for th in (0.35, 0.45, 0.55):
        cl = agg(th)
        big = [c for c in cl if len(c) >= 3]
        out.append(f"порог {th}: кластеров {len(cl)}, крупных(≥3) {len(big)}")
        if th == 0.45:
            for c in sorted(cl, key=len, reverse=True)[:12]:
                hz = [V[pids[i]]["hz"] for i in c if V[pids[i]]["hz"]]
                vt = [V[pids[i]]["vtl"] for i in c if V[pids[i]]["vtl"]]
                sx = collections.Counter(V[pids[i]]["sex"] for i in c)
                who = collections.Counter(V[pids[i]].get("who") or "-" for i in c)
                txt = " | ".join((V[pids[i]]["text"] or "")[:28] for i in c[:3])
                out.append(f"  n={len(c):3d} hz~{np.median(hz) if hz else 0:.0f} vtl~{np.median(vt) if vt else 0:.1f} {dict(sx)} {dict(who)} :: {txt}")
    # отдельно: насколько реплики Зубарева (по отпечатку) сидят в одном кластере
    zub = [i for i, p in enumerate(pids) if (V[p].get("who") or "").startswith("зуб")]
    if zub:
        zc = X[zub].mean(0); zc /= np.linalg.norm(zc) + 1e-9
        sims = X @ zc
        out.append(f"зубарев: реплик {len(zub)}, сходство своих {sims[zub].mean():.2f}, чужих {np.delete(sims, zub).mean():.2f}, чужих выше 0.6: {int((np.delete(sims, zub) > 0.6).sum())}")
open(r"C:\AI\Saika\data\film_people.txt", "w", encoding="utf-8").write("\n".join(out))
