import time, wave, numpy as np, cProfile, pstats, io
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w:
    SR=w.getframerate(); A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
c=A[8*SR:11*SR]
stt.src_hint="sys"
stt.transcribe_segment(c)
best=1e9
for _ in range(4):
    t0=time.perf_counter(); r=stt.transcribe_segment(c); best=min(best,time.perf_counter()-t0)
print("transcribe_segment best %.0f мс; результат: %s" % (best*1000, str(r)[:200]))
pr=cProfile.Profile(); pr.enable()
for _ in range(3): stt.transcribe_segment(c)
pr.disable(); s=io.StringIO(); pstats.Stats(pr,stream=s).sort_stats("cumulative").print_stats(28); print(s.getvalue()[:6000])
