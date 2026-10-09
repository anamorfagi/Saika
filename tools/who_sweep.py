# -*- coding: utf-8 -*-
"""Подбор порога похожести тембра ПО ЗАМЕРУ, а не на глаз.

На куске 10:00–13:00 ролика говорят несколько человек (ведущий, гостья,
её собеседники в студии). При нынешнем link_cos=0.45 они слились в один
кластер — отсюда «Голос 5» на всех подряд. Гоняем порог по сетке и
смотрим, где число людей перестаёт быть единицей и ещё не превращается
в кашу из обрывков.

Печатаем и распределение косинусов между соседними кусками: по нему
видно, есть ли вообще граница, или тембры в этой записи неразделимы
нашим кодировщиком."""
import io, os, sys, wave
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); os.chdir(str(ROOT))
import numpy as np
from anamorf.config import CFG
from anamorf.stt.manager import VadSegmenter
from anamorf.voiceprint.tracks import Tracks
from anamorf import voiceprint as vp

WAV = ROOT / "data" / "bench_1000_1300.wav"
with wave.open(str(WAV), "rb") as w:
    sr = w.getframerate(); pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)

vad = VadSegmenter(); segs = []; pos = 0; CH = int(sr*0.032); start = None
while pos < len(pcm):
    at = pos/float(sr)
    if start is None and getattr(vad, "in_speech", False): start = at
    sg = vad.push(pcm[pos:pos+CH]); pos += CH
    if sg is not None: segs.append((start if start is not None else at, sg)); start = None

# ОКНА ВНУТРИ КУСКА: кусок в 6 секунд может содержать двоих. Кодируем
# по 1.5 с с шагом 0.75 — так смена говорящего внутри куска видна.
V = []
for t, sg in segs:
    # ОКНО 2.5 с, А НЕ 1.5 (05.09). Первый прогон дал ноль кластеров на
    # всех порогах, и это была не «неразделимость», а моя ошибка: у
    # дорожек есть ручка rho_s (сейчас 2.0) — фраза короче неё НЕ
    # заводит кластер вовсе, только примыкает к очень похожему. Окна по
    # 1.5 с все до одного отсекались этим правилом. Берём 2.5 с.
    n = len(sg); W = int(sr*2.5); H = int(sr*1.0)
    if n < W:
        try: v,_ = vp.S.enc.encode(sg); V.append((t, n/float(sr), np.asarray(v,np.float32).ravel()))
        except Exception: pass
        continue
    for o in range(0, n-W+1, H):
        try:
            v,_ = vp.S.enc.encode(sg[o:o+W])
            V.append((t + o/float(sr), 2.5, np.asarray(v,np.float32).ravel()))
        except Exception: pass
print("окон тембра: %d (из %d кусков речи)" % (len(V), len(segs)))
X = np.stack([v/ (np.linalg.norm(v)+1e-9) for _,_,v in V])
C = X @ X.T
iu = np.triu_indices(len(X), 1)
d = np.sort(C[iu])
print("косинус между окнами: медиана %.2f · 10%% %.2f · 90%% %.2f · мин %.2f · макс %.2f"
      % (np.median(d), d[int(.1*len(d))], d[int(.9*len(d))], d[0], d[-1]))
print()
print(" порог | кластеров | людьми | самый большой")
for thr in (0.45, 0.55, 0.62, 0.68, 0.72, 0.76, 0.80, 0.84, 0.88):
    CFG.set("voiceprint.tracks.link_cos", thr)
    CFG.set("voiceprint.tracks.merge_cos", min(0.95, thr + 0.12))
    CFG.set("voiceprint.tracks.rho_s", 2.0)
    CFG.set("voiceprint.tracks.confirm_s", 6.0)
    CFG.set("voiceprint.tracks.confirm_n", 3)
    CFG.set("voiceprint.tracks.confirm_visits", 2)
    tr = Tracks(to_registry=False, tag="")
    for t, sec, v in V: tr.observe(v, sec, ts=t)
    named = [c for c in tr.clusters if c.name]
    big = max((c.sec for c in tr.clusters), default=0)
    print("  %.2f | %9d | %6d | %.0f с из %.0f"
          % (thr, len(tr.clusters), len(named), big, sum(c.sec for c in tr.clusters)))
