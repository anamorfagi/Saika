import subprocess, wave, numpy as np
src=r"C:\AI\Saika\slux_test\snailkik_dnk\ДЯДЯ ОТЦА МАТЕРИ СЫНА _ СМОТРИМ ДНК.mp4"
out=r"C:\AI\Saika\data\first30_stereo.wav"
subprocess.run([r"C:\AI\Saika\tools\ffmpeg\bin\ffmpeg.exe","-y","-v","error","-i",src,"-t","30","-ac","2","-ar","16000","-f","wav",out],check=True)
with wave.open(out,"rb") as w: n=w.getnchannels(); A=np.frombuffer(w.readframes(w.getnframes()),np.int16).reshape(-1,n).astype(np.float32)/32768
print("channels",n, "shape",A.shape)
L,R=A[:,0],A[:,1]
print("L-R rms", float(np.sqrt(np.mean((L-R)**2))), "L rms", float(np.sqrt(np.mean(L**2))))
N=512;H=256;win=np.hanning(N);fq=np.fft.rfftfreq(N,1/16000)
tone=(fq>=930)&(fq<=1070); other=((fq>=90)&(fq<=850))|((fq>=1250)&(fq<=4000))
def en(x,t0,t1,m):
    e=[]
    for off in range(int(t0*16000),int(t1*16000)-N,H):
        sp=np.abs(np.fft.rfft(x[off:off+N]*win))**2; e.append(sp[m].sum())
    return float(np.mean(e))
for b0,b1 in ((9.312,9.696),(16.448,16.848),(18.56,18.784)):
    for nm,x in (("L",L),("R",R)):
        print(f"{b0}-{b1} {nm}: тон {en(x,b0,b1,tone):.3f} речь-под {en(x,b0,b1,other):.4f} речь-до {en(x,b0-0.5,b0-0.05,other):.3f}")
