# -*- coding: utf-8 -*-
"""Стерео ли приходит петля системного звука? (06.09.2026)

Прежде чем строить разделение по панораме, надо знать, есть ли она
вообще. Меряем: сколько каналов отдаёт петля, насколько они различаются
и есть ли между ними задержка. Если каналы идентичны — панорамы нет, и
весь замысел с пространственным разделением отпадает; лучше узнать это
за десять секунд, чем после дня работы.
"""
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import numpy as np, soundcard as sc

SR = 48000
cands = [m for m in sc.all_microphones(include_loopback=True)
         if getattr(m, "isloopback", False)]
print("петель:", len(cands))
for m in cands:
    try:
        with m.recorder(samplerate=SR, channels=2, blocksize=2048) as r:
            a = r.record(numframes=int(SR * 1.5))
    except Exception as e:
        print("  %-38s НЕ ОТДАЁТ (%s)" % (m.name[:38], str(e)[:40])); continue
    a = np.asarray(a, np.float32)
    if a.ndim == 1 or a.shape[1] < 2:
        print("  %-38s моно" % m.name[:38]); continue
    L, R = a[:, 0], a[:, 1]
    rms = lambda x: float(np.sqrt(np.mean(x * x)) + 1e-12)
    if rms(L) < 1e-5 and rms(R) < 1e-5:
        print("  %-38s тишина" % m.name[:38]); continue
    d = L - R
    corr = float(np.dot(L, R) / ((np.linalg.norm(L) or 1) * (np.linalg.norm(R) or 1)))
    print("  %-38s L %.4f R %.4f | разница %.4f (%.1f%% от L) | схожесть %.4f"
          % (m.name[:38], rms(L), rms(R), rms(d), 100 * rms(d) / max(1e-9, rms(L)), corr))
