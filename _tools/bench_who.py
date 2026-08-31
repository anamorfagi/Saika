# -*- coding: utf-8 -*-
"""СТЕНД: насколько верно система понимает, КТО это сказал.

Меряем числом, а не на глаз. Эталон — разметка pyannote по той же записи.
Считаем две цифры: долю верно размеченных кусков и СБАЛАНСИРОВАННУЮ
точность (среднее по людям) — иначе результат надувается за счёт того,
что один человек говорит две трети записи.
"""
import io, os, sys, json, time, wave, traceback
import numpy as np

APP = r"C:\AI\Saika\build\ANAMORF-0.2.1\app"
WAV = r"C:\AI\Saika\build\ANAMORF-0.1.2\data\eval_take.wav"
GT  = r"C:\AI\Saika\build\ANAMORF-0.1.2\data\bench\pyannote_result5.json"
OUT = r"E:\Loading\_atlas_tmp\bench_who.json"
LOG = r"E:\Loading\_atlas_tmp\bench_who.log"

def note(m):
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))

try:
    note("=== новый прогон ===")
    sys.path.insert(0, APP)
    from anamorf.config import CFG
    CFG.set("voiceprint.encoder", "ecapa")      # как в бою, а не «авто»
    CFG.set("voiceprint.device", "cpu")
    os.environ["HF_HUB_OFFLINE"] = "1"       # модель уже лежит рядом, сеть не нужна
    from anamorf.voiceprint.encoder import Encoder
    enc = Encoder()
    # тяжёлый движок поднимается ЛЕНИВО — без этого вызова замер шёл бы
    # по лёгким 68 признакам, а в бою работает ECAPA на 192
    try:
        enc.warmup()
    except Exception as _e:
        note("warmup упал: %r" % _e)
    note("кодировщик: %s dim=%s ошибка=%s" % (enc.backend, enc.dim, enc.last_error[:200]))
    if enc.backend != "ecapa":
        note("ВНИМАНИЕ: ECAPA не поднялась, меряем лёгкий кодировщик")

    w = wave.open(WAV, "rb"); sr = w.getframerate()
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16); w.close()
    gt = json.load(open(GT, encoding="utf-8"))["segments"]

    WIN, HOP = 1.5, 0.5
    nw, nh = int(WIN * sr), int(HOP * sr)
    af = a.astype(np.float32) / 32768.0
    E, T = [], []
    for off in range(0, max(0, len(a) - nw), nh):
        seg = af[off:off + nw]
        if float(np.sqrt((seg * seg).mean())) < 0.006:
            continue
        try:
            v, f0 = enc.encode(a[off:off + nw])
        except Exception:
            continue
        if v is None: continue
        E.append(np.asarray(v, dtype=np.float32)); T.append((off / sr, (off + nw) / sr))
    E = np.array(E)
    E = E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)
    note("кусков %d, отпечаток %s" % (len(T), E.shape))

    def truth_at(t):
        for s in gt:
            if s["start"] <= t < s["end"]: return s["spk"]
        return None
    G = [truth_at((t0 + t1) / 2) for (t0, t1) in T]
    keep = [i for i, g in enumerate(G) if g]
    note("кусков с эталоном: %d, людей: %d" % (len(keep), len(set(G[i] for i in keep))))

    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import pdist
    D = pdist(E, metric="cosine")
    Z = linkage(D, method="average")

    def smooth(lab, k=2):
        """Сглаживание по времени: говорящий не меняется каждые полсекунды.
        Одиночный чужой кусок посреди длинной реплики — почти всегда ошибка."""
        out = list(lab)
        for i in range(len(lab)):
            lo, hi = max(0, i - k), min(len(lab), i + k + 1)
            win = list(lab[lo:hi])
            out[i] = max(set(win), key=win.count)
        return out

    def score(lab):
        pair = {}
        for i in keep:
            pair.setdefault(lab[i], {}).setdefault(G[i], 0)
            pair[lab[i]][G[i]] += 1
        m = {c: max(v, key=v.get) for c, v in pair.items()}
        per = {}
        ok = 0
        for i in keep:
            good = (m.get(lab[i]) == G[i])
            ok += 1 if good else 0
            d = per.setdefault(G[i], [0, 0]); d[1] += 1; d[0] += 1 if good else 0
        bal = float(np.mean([d[0] / d[1] for d in per.values()])) if per else 0.0
        return (round(100.0 * ok / max(1, len(keep)), 1), round(100.0 * bal, 1),
                {g: round(100.0 * d[0] / d[1], 1) for g, d in sorted(per.items())})

    res = {}
    for nc in (3, 4, 5, 6, 7, 8):
        lab = list(fcluster(Z, nc, criterion="maxclust"))
        a1, b1, p1 = score(lab)
        a2, b2, p2 = score(smooth(lab))
        res["кластеров_%d" % nc] = {
            "как_есть": {"точность": a1, "сбаланс": b1, "по_людям": p1},
            "со_сглаживанием": {"точность": a2, "сбаланс": b2, "по_людям": p2},
        }
        note("%d кластеров: %.1f%% / сбал %.1f%%   после сглаживания %.1f%% / %.1f%%"
             % (nc, a1, b1, a2, b2))

    json.dump({"кодировщик": enc.backend, "кусков": len(keep), "результаты": res},
              io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    note("ГОТОВО")
except Exception:
    note("ОШИБКА:\n" + traceback.format_exc())
