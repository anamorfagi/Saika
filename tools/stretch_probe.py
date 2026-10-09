import wave, numpy as np, time
from anamorf.stt import engines as E
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
eng = stt.instances[stt.current_name]
for a,b in ((0,2.6),(7.9,10.5),(0.5,3.0)):
    seg=A[int(a*16000):int(b*16000)]
    t0=time.time(); txt=eng._transcribe_direct(seg); ms=round((time.time()-t0)*1000)
    print(a,b,ms,"ms", repr(txt), getattr(E.LAST_WORDS,"words",None))
    t0=time.time(); r=stt.transcribe_segment(seg); print("  via manager", round((time.time()-t0)*1000),"ms", [(x.get("text"),x.get("engine")) for x in (r or [])])
