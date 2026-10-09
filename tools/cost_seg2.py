import time, wave, numpy as np, cProfile, pstats, io
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w:
    SR=w.getframerate(); A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
stt.src_hint="sys"
for a,b in ((8,11),(10,15),(15,20)):
    c=A[a*SR:b*SR]; stt.transcribe_segment(c)
    ts=[]
    for _ in range(4):
        t0=time.perf_counter(); r=stt.transcribe_segment(c); ts.append((time.perf_counter()-t0)*1000)
    print("%d-%ds: %s мс -> %s" % (a,b, [int(t) for t in ts], str(r)[:120]))
c=A[10*SR:15*SR]
pr=cProfile.Profile(); pr.enable()
for _ in range(3): stt.transcribe_segment(c)
pr.disable(); s=io.StringIO(); pstats.Stats(pr,stream=s).sort_stats("cumulative").print_stats(18); print(s.getvalue()[:4000])
