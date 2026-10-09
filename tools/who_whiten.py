# -*- coding: utf-8 -*-
"""Почему голоса не разделяются — и лечится ли это вычитанием общего.

Замер на куске 10:00–13:00: косинус между ЛЮБЫМИ двумя окнами тембра
0.92 в медиане, минимум 0.63. То есть отпечатки всех говорящих лежат в
одном тесном конусе, и никакой порог их не разделит: при 0.84 всё ещё
один человек, при 0.88 уже начинает крошиться на обрывки.

Это ровно та же болезнь, что была у карты звуков (docs/АТЛАС_ЗВУКА.md,
причина 3): у всех записей одного канала общая форма, и пока она внутри
описания, различие между источниками тонет. Там помогло вычитание
среднего по всем звукам — различие выросло с 0.21 до 1.01, впятеро.

Проверяем то же самое на отпечатках голоса: вычитаем средний вектор
записи и нормируем заново. Если конус раскроется — это и есть лечение
«всё один Голос 5»."""
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
vad = VadSegmenter(); segs=[]; pos=0; CH=int(sr*0.032); start=None
while pos < len(pcm):
    at = pos/float(sr)
    if start is None and getattr(vad,"in_speech",False): start = at
    sg = vad.push(pcm[pos:pos+CH]); pos += CH
    if sg is not None: segs.append((start if start is not None else at, sg)); start=None

V, T = [], []
for t, sg in segs:
    n=len(sg); W=int(sr*2.5); H=int(sr*1.0)
    rng = range(0, max(1, n-W+1), H) if n>=W else [0]
    for o in rng:
        try:
            v,_ = vp.S.enc.encode(sg[o:o+W] if n>=W else sg)
            V.append(np.asarray(v,np.float32).ravel()); T.append(t+o/float(sr))
        except Exception: pass
X = np.stack(V); X /= (np.linalg.norm(X,axis=1,keepdims=True)+1e-9)
print("окон: %d, размерность %d" % X.shape)

def spread(M, tag):
    M = M/(np.linalg.norm(M,axis=1,keepdims=True)+1e-9)
    C = M@M.T; iu=np.triu_indices(len(M),1); d=np.sort(C[iu])
    print("%-28s медиана %.3f · 10%% %.3f · мин %.3f · разброс(90-10) %.3f"
          % (tag, np.median(d), d[int(.1*len(d))], d[0],
             d[int(.9*len(d))]-d[int(.1*len(d))]))
    return M

A = spread(X, "как есть")
B = spread(X - X.mean(0, keepdims=True), "минус среднее записи")
# мягкое отбеливание по главным осям (степень 0.6) — как в атласе
Xc = X - X.mean(0, keepdims=True)
U,S,Vt = np.linalg.svd(Xc, full_matrices=False)
Sw = np.where(S>1e-6, S**0.6, S)
C = spread((U*Sw)@Vt, "минус среднее + отбеливание")

print()
print(" порог | кластеров | людьми  (на отбелённых отпечатках)")
for thr in (0.30, 0.40, 0.50, 0.60, 0.70, 0.80):
    CFG.set("voiceprint.tracks.link_cos", thr)
    CFG.set("voiceprint.tracks.merge_cos", min(0.95, thr+0.12))
    CFG.set("voiceprint.tracks.rho_s", 2.0)
    CFG.set("voiceprint.tracks.confirm_s", 6.0)
    CFG.set("voiceprint.tracks.confirm_n", 3)
    CFG.set("voiceprint.tracks.confirm_visits", 2)
    tr = Tracks(to_registry=False, tag="")
    for i in range(len(C)): tr.observe(C[i], 2.5, ts=T[i])
    named=[c for c in tr.clusters if c.name]
    sizes = sorted((round(c.sec) for c in tr.clusters), reverse=True)[:6]
    print("  %.2f | %9d | %6d | крупнейшие: %s" % (thr, len(tr.clusters), len(named), sizes))
