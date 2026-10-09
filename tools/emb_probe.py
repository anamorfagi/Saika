import wave, numpy as np
from anamorf import voiceprint as vp
enc = vp.S.enc
with wave.open(r"C:\AI\Saika\data\snailkick.wav","rb") as w: B=np.frombuffer(w.readframes(w.getnframes()), np.int16)
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
SR=16000
def E(x): v,_=enc.encode(x); return v
snail_ref = E(A[22*SR:30*SR])                      # чистый Снейл из вступления
# женщины/эксперт из 22:00-25:00 — Ольга 0:12-0:19 по разметке (там Ольга говорит)
olga_ref = E(B[12*SR:19*SR])
segs=[(1.5,3.0,"ж"),(3.7,5.3,"ж"),(6.6,8.1,"Снейл смех"),(8.1,11.4,"Снейл пародия"),(11.4,14.5,"ж"),(13.8,16.9,"Снейл крик"),(17.8,20.5,"ж"),(22,25,"Снейл норм")]
print("cos к Снейлу-норм | к Ольге")
for s,e,lab in segs:
    v=E(A[int(s*SR):int(e*SR)])
    print("%5.1f-%5.1f  %.2f | %.2f   %s" % (s,e,float(np.dot(v,snail_ref)),float(np.dot(v,olga_ref)),lab))
