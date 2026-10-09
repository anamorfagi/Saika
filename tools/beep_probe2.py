import wave, numpy as np
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)/32768
N=512;H=256;win=np.hanning(N).astype(np.float32);fq=np.fft.rfftfreq(N,1/16000);band=(fq>=500)&(fq<=3200)
def stats(t0,t1):
    vals=[]
    for off in range(int(t0*16000), int(t1*16000)-N, H):
        sp=np.abs(np.fft.rfft(A[off:off+N]*win))**2; tot=sp[fq>=80].sum()+1e-12
        i=int(np.argmax(sp*band)); pk=sp[max(0,i-2):i+3].sum()/tot
        # чистота: пик против ±1 бин узко, и против гармоник
        nar=sp[max(0,i-1):i+2].sum()/tot
        h2=sp[max(0,2*i-2):2*i+3].sum()/tot if 2*i+3<len(sp) else 0
        h05=sp[max(0,i//2-2):i//2+3].sum()/tot
        vals.append((round(pk,2),round(nar,2),round(h2,2),round(h05,2),fq[i]))
    return vals
for a,b,lab in ((0.16,0.45,"speech500"),(1.12,1.25,"speech"),(9.31,9.70,"BEEP"),(16.45,16.85,"BEEP"),(18.56,18.8,"BEEP"),(3.33,3.46,"sp906"),(12.94,13.06,"sp625"),(14.97,15.09,"sp1468")):
    v=stats(a,b); print(lab, a,b, "pk", np.median([x[0] for x in v]), "nar", np.median([x[1] for x in v]), "h2", np.median([x[2] for x in v]), "h05", np.median([x[3] for x in v]), "hz", sorted(set(x[4] for x in v)))
