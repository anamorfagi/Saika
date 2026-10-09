# -*- coding: utf-8 -*-
"""Первые 6 с ролика: речь под музыкой. Кто что слышит и что помогает."""
import wave, numpy as np, re, time
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
SR=16000
REF=[x for x in re.findall(r"[а-яё]+","много денег-то было если бы ты свою распласкивала а ты а ты своюсь бы".lower()) if len(x)>1]
def norm(t): return [x for x in re.findall(r"[а-яё]+",(t or "").lower()) if len(x)>1]
def hits(t):
    r=list(REF); n=0
    for x in norm(t):
        if x in r: r.remove(x); n+=1
    return n
eng=stt.instances[stt.current_name]
def giga(x): return eng._transcribe_direct(np.clip(x,-32767,32767).astype(np.int16)) or ""
seg=A[0:int(6.2*SR)]
print("rms", round(float(np.sqrt(np.mean((seg/32768.0)**2))),4), "peak", round(float(np.max(np.abs(seg))/32768),3))
t0=time.time(); t=giga(seg); print(f"giga сырой: {hits(t)}/{len(REF)}  {int((time.time()-t0)*1000)} мс  {t!r}")
from anamorf.stt import frontend as fe
p=fe.prepare(seg, SR, CFG.get("stt.frontend",{}) or {})
t=giga(p); print(f"giga + frontend: {hits(t)}/{len(REF)}  {t!r}")
for g in (2.0, 4.0):
    t=giga(seg.astype(np.float32)*g); print(f"giga x{g}: {hits(t)}/{len(REF)}  {t!r}")
# кусками, как нарезка
for a,b in ((0,2.6),(2.6,4.6),(4.6,6.2),(0,3.5),(3.5,6.2)):
    t=giga(A[int(a*SR):int(b*SR)]); print(f"giga {a}-{b}: {hits(t)}  {t!r}")
# второе ухо
try:
    from anamorf.stt import second
    t0=time.time(); r=second.listen(stt, seg, SR, "") ; print(f"второе ухо (parakeet): {hits(r or '')}/{len(REF)}  {int((time.time()-t0)*1000)} мс  {r!r}  {second.STATE.get('why','')}")
except Exception as e: print("второе ухо:", e)
# подавление музыки: noisereduce с профилем музыки из чистого куска (5.6-6.2?) — проверим есть ли чисто-музыкальный кусок
try:
    import noisereduce as nr
    x=seg.astype(np.float32)/32768
    y=nr.reduce_noise(y=x, sr=SR, stationary=False, prop_decrease=0.8)
    t=giga(y*32768); print(f"giga + noisereduce: {hits(t)}/{len(REF)}  {t!r}")
except Exception as e: print("noisereduce:", e)
