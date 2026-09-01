# -*- coding: utf-8 -*-
"""ПОРОГ СКЛЕЙКИ — ПО ДАННЫМ, А НЕ НА ГЛАЗ (2026-08-31).

Живой прогон снейлкика показал: почти каждая реплика заводила новый
кластер, косинусы легли в 0.18..0.44 при пороге link_cos=0.45. Порог
достался от ECAPA, а у ReDimNet2 пространство другое — и число, взятое
из чужой статьи, здесь просто не работает.

Считаем сами: режем ролик на реплики, кодируем каждую обеими головами,
смотрим РАСПРЕДЕЛЕНИЕ косинусов и во что превращается число людей при
разных порогах. Правильный порог — в провале между двумя горбами
(«тот же человек» и «другой»), а по числу кластеров он виден как полка:
участок, где ответ перестаёт скакать от каждой сотой.
"""
import sys, os, json, wave
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

WAV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "snailkick.wav")

def load():
    w = wave.open(WAV, "rb")
    sr, ch = w.getframerate(), w.getnchannels()
    a = np.frombuffer(w.readframes(w.getnframes()), np.int16); w.close()
    if ch > 1: a = a[::ch]
    if sr != 16000:
        n = int(len(a) * 16000 / sr)
        a = np.interp(np.linspace(0, len(a)-1, n), np.arange(len(a)), a).astype(np.int16)
    return a

def segments(a):
    """Нарезка по речи — тем же silero, что и в проге."""
    # энергия по 30мс кадрам: для калибровки порога склейки нам важны не
    # идеальные границы, а чистые куски одного голоса — их энергия даёт
    fr = 480
    e = np.array([float(np.abs(a[i:i+fr]).mean()) for i in range(0, len(a)-fr, fr)])
    thr = max(np.percentile(e, 35) * 2.2, 120.0)
    on = e > thr
    segs, i = [], 0
    while i < len(on):
        if not on[i]: i += 1; continue
        j = i
        gap = 0
        while j < len(on) and gap < 8:      # склеиваем паузы < 240мс
            if on[j]: gap = 0
            else: gap += 1
            j += 1
        s, t = i*fr, min(j*fr, len(a))
        if (t - s) / 16000.0 >= 1.0:
            segs.append((s, t))
        i = j
    return segs

def encode_all(backend, segs, a):
    from anamorf.voiceprint.encoder import Encoder
    e = Encoder(); e.force = backend
    got = e.warmup()
    if got != backend:
        return None, "поднялся %s вместо %s" % (got, backend)
    V = []
    for s, t in segs:
        v, _ = e.encode(a[s:t])
        V.append(np.asarray(v, np.float32))
    return np.stack(V), got

def greedy(V, secs, link, merge=0.60, rho=0.8):
    """Та же логика, что в tracks.py: примкнуть или завести новый."""
    cen, wt = [], []
    ids = []
    for i in range(len(V)):
        best, bi = -2.0, -1
        for k, c in enumerate(cen):
            d = float(np.dot(V[i], c / max(np.linalg.norm(c), 1e-9)))
            if d > best: best, bi = d, k
        if bi >= 0 and best >= link:
            ids.append(bi)
            if secs[i] >= rho:
                cen[bi] = cen[bi] * wt[bi] + V[i] * secs[i]
                wt[bi] += secs[i]
                cen[bi] /= max(np.linalg.norm(cen[bi]), 1e-9)
        else:
            cen.append(V[i].copy()); wt.append(max(secs[i], 0.1))
            ids.append(len(cen)-1)
    return ids, len(cen)

def report(name, V, secs):
    n = len(V)
    C = V @ V.T
    off = C[np.triu_indices(n, 1)]
    print("\n===== %s =====" % name)
    print("реплик %d, косинусы между разными репликами:" % n)
    for p in (5, 25, 50, 75, 90, 95, 99):
        print("   %2d%%  %.3f" % (p, float(np.percentile(off, p))))
    print("   макс %.3f" % float(off.max()))
    print("\n порог -> сколько людей насчитала")
    prev = None
    for link in [round(0.20 + 0.025*i, 3) for i in range(21)]:
        _ids, k = greedy(V, secs, link)
        mark = "  <-- полка" if prev is not None and k == prev else ""
        print("   %.3f  %2d%s" % (link, k, mark))
        prev = k

def main():
    a = load()
    segs = segments(a)
    secs = [(t-s)/16000.0 for s, t in segs]
    print("звук %.1fс, реплик %d, суммарно речи %.1fс"
          % (len(a)/16000.0, len(segs), sum(secs)))
    for be in ("redimnet", "ecapa"):
        V, note = encode_all(be, segs, a)
        if V is None:
            print("\n===== %s ===== не поднялась: %s" % (be, note)); continue
        report(be, V, secs)

main()
