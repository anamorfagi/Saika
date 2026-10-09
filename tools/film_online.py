# Онлайн-кластеризация отпечатков фильма: центроиды с памятью. Оценка по
# известной правде — реплики Зубарева (who == "зубарев" по косинусу ≥0.45).
import numpy as np, collections
V = dict(FILM_VECS); pids = sorted(V, key=lambda p: (int(str(p).split("_")[0]), str(p)))
out = []
def run(thr, merge_thr, min_sec=0.8):
    cents = []   # [vec_sum, n, ids]
    assign = {}
    for p in pids:
        d = V[p]
        if (d.get("sec") or 0) < min_sec: continue
        v = np.asarray(d["v"], np.float32); v /= np.linalg.norm(v) + 1e-9
        best, bi = -1, -1
        for i, c in enumerate(cents):
            cv = c[0] / (np.linalg.norm(c[0]) + 1e-9)
            s = float(v @ cv)
            if s > best: best, bi = s, i
        if best >= thr:
            cents[bi][0] += v; cents[bi][1] += 1; cents[bi][2].append(p); assign[p] = bi
        else:
            cents.append([v.copy(), 1, [p]]); assign[p] = len(cents) - 1
        # слияние близких центроидов
        if len(cents) > 1 and len(assign) % 10 == 0:
            i = 0
            while i < len(cents):
                j = i + 1
                while j < len(cents):
                    a = cents[i][0] / (np.linalg.norm(cents[i][0]) + 1e-9); b = cents[j][0] / (np.linalg.norm(cents[j][0]) + 1e-9)
                    if float(a @ b) >= merge_thr and min(cents[i][1], cents[j][1]) >= 3:
                        cents[i][0] += cents[j][0]; cents[i][1] += cents[j][1]; cents[i][2] += cents[j][2]
                        for q in cents[j][2]: assign[q] = i
                        del cents[j]
                    else:
                        j += 1
                i += 1
    # правда: зубарев
    zub = {p for p in assign if (V[p].get("who") or "").startswith("зуб")}
    if not zub: return "нет правды"
    by = collections.Counter(assign[p] for p in zub)
    main, cnt = by.most_common(1)[0]
    size = sum(1 for p in assign if assign[p] == main)
    big = sorted([c[1] for c in cents], reverse=True)
    return "thr %.2f merge %.2f: кластеров %d (≥5: %d) | зубарев %d реплик: в главном %d (%.0f%%), в нём чужих %d | крупные %s" % (
        thr, merge_thr, len(cents), sum(1 for b in big if b >= 5), len(zub), cnt, 100 * cnt / len(zub), size - cnt, big[:8])
for thr in (0.40, 0.45, 0.50, 0.55):
    for mt in (0.60, 0.70):
        out.append(run(thr, mt))
out.append("всего реплик в копилке %d, с who %d" % (len(V), sum(1 for p in V if "who" in V[p])))
open(r"C:\AI\Saika\data\film_online.txt", "w", encoding="utf-8").write("\n".join(out))
