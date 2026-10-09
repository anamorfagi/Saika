# -*- coding: utf-8 -*-
"""Сколько РЕАЛЬНО стоит один кусок потока и что можно ускорить.

Владелец: «300 мс нужно в 100 раз быстрее, чтобы звук за 30 мс уже
вписался в транскриб». Прежде чем обещать — меряем: сколько занимает
один прогон, какая часть задержки от модели, а какая от нашего кода."""
import io, sys, time, wave
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
O=[]
def say(*a):
    s=" ".join(str(x) for x in a); print(s); O.append(s)
    io.open(ROOT/"data"/"tone_bench.txt","w",encoding="utf-8").write("\n".join(O))

from anamorf.stt.stream_tone import ToneStream, CHUNK, SR, FRAME_S, LABELS
s = ToneStream("bench"); s.load()

w = wave.open(str(ROOT/"data"/"bench_1000_1300.wav"), "rb")
sr = w.getframerate(); pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
a8 = s._to8k(pcm)
say("звук: %d Гц -> %d Гц, %.0f с" % (sr, SR, len(a8)/SR))

# прогрев
st=None
for i in range(3):
    _, st = s._model.forward(a8[i*CHUNK:(i+1)*CHUNK].astype(np.int32)[None,:,None], st)

N=60; st=None; ts=[]
for i in range(N):
    c = a8[i*CHUNK:(i+1)*CHUNK].astype(np.int32)
    if len(c) < CHUNK: break
    t0=time.perf_counter(); lp, st = s._model.forward(c[None,:,None], st); ts.append((time.perf_counter()-t0)*1000)
ts.sort()
say("\nодин кусок 300 мс: медиана %.1f мс, худший %.1f мс" % (ts[len(ts)//2], ts[-1]))
say("то есть на 300 мс звука уходит %.1f%% времени — запас в %.0f раз"
    % (ts[len(ts)//2]/300*100, 300/max(ts[len(ts)//2],0.01)))
say("кадров в куске: %d (по %d мс)" % (len(np.asarray(lp).reshape(-1, 35)), int(FRAME_S*1000)))

say("\nСКОЛЬЗЯЩЕЕ ОКНО: тот же кусок, но шагом 30 мс вместо 300")
say("цена = 10 прогонов на те же 300 мс звука: %.1f мс из 300 (%.0f%%)"
    % (ts[len(ts)//2]*10, ts[len(ts)//2]*10/300*100))

# проверка растяжки
say("\nРАСТЯЖКА: ищу в куске тянутые гласные")
s2 = ToneStream("bench2"); s2._model = s._model
seen=set()
for i in range(0, min(len(a8), SR*90)-CHUNK+1, CHUNK):
    t = s2.feed(pcm[i*2:(i+CHUNK)*2])
    if t and t != "" and t not in seen:
        seen.add(t)
for t in list(seen)[-3:]:
    say("   " + t[-160:])
