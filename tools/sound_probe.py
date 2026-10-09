# что слышат уши (PANNs) на первых 20 с ролика, окно 1.0 с, шаг 0.5 с
import wave, numpy as np, time
from anamorf import hearing
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)/32768
m = hearing._model; L = hearing._labels
print("model", m is not None, "labels", len(L))
WIN=1.0; HOP=0.5
t=0.0; t0=time.time(); n=0
while t+WIN <= 20.0:
    ch = A[int(t*16000):int((t+WIN)*16000)]
    x = hearing._resample(ch)[None,:]
    cw,_ = m.inference(x); pr=np.asarray(cw[0]); n+=1
    idx = pr.argsort()[::-1][:4]
    tags = " · ".join(f"{L[i]} {pr[i]:.2f}" for i in idx)
    print(f"{t:5.1f}  {tags}")
    t += HOP
print("ms per window", round((time.time()-t0)*1000/n))
