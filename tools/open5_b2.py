# -*- coding: utf-8 -*-
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
seg=A[0:int(6.2*SR)]
from anamorf.stt import second
pk=second._parakeet()
def para(x):
    x=np.asarray(x,np.float32); x=x/32768.0 if np.max(np.abs(x))>1.5 else x
    return pk.recognize(x, sample_rate=SR) if hasattr(pk,"recognize") else str(pk(x))
t0=time.time(); t=para(seg); print(f"parakeet сырой: {hits(t)}/{len(REF)} {int((time.time()-t0)*1000)} мс {t!r}")
from anamorf.stt import frontend as fe
p=fe.prepare(seg, SR, CFG.get("stt.frontend",{}) or {})
t=para(p); print(f"parakeet + frontend: {hits(t)}/{len(REF)} {t!r}")
for a,b in ((0,3.0),(2.6,6.2)):
    t=para(A[int(a*SR):int(b*SR)]); print(f"parakeet {a}-{b}: {hits(t)} {t!r}")
# whisper turbo через менеджер
try:
    t0=time.time(); w=stt._get("faster_whisper"); w.load() if getattr(w,"model",None) is None else None
    print("whisper загрузка", int((time.time()-t0)*1000),"мс")
    t0=time.time(); t=w.transcribe(seg, SR); print(f"whisper-turbo сырой: {hits(t)}/{len(REF)} {int((time.time()-t0)*1000)} мс {t!r}")
    t=w.transcribe(p, SR); print(f"whisper-turbo + frontend: {hits(t)}/{len(REF)} {t!r}")
except Exception as e: print("whisper:", repr(e)[:200])
