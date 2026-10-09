import wave, numpy as np
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)/32768
N=512;H=256;win=np.hanning(N);fq=np.fft.rfftfreq(N,1/16000)
def spec_energy(t0,t1,mask):
    e=[]
    for off in range(int(t0*16000), int(t1*16000)-N, H):
        sp=np.abs(np.fft.rfft(A[off:off+N]*win))**2; e.append(sp[mask].sum())
    return float(np.mean(e)) if e else 0.0
for b0,b1 in ((9.312,9.696),(16.448,16.848),(18.56,18.784)):
    tone=(fq>=1000-70)&(fq<=1000+70); other=((fq>=90)&(fq<=850))|((fq>=1250)&(fq<=4000))
    under=spec_energy(b0,b1,other); before=spec_energy(b0-0.5,b0-0.05,other); after=spec_energy(b1+0.05,b1+0.5,other)
    print(f"beep {b0}-{b1}: речь под тоном {under:.5f}, до {before:.5f}, после {after:.5f}, доля {under/max(1e-9,(before+after)/2):.2f}, тон {spec_energy(b0,b1,tone):.4f}")
