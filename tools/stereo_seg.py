import subprocess, numpy as np
VID = r"C:\AI\Saika\slux_test\snailkik_dnk\ДЯДЯ ОТЦА МАТЕРИ СЫНА _ СМОТРИМ ДНК.mp4"
raw = subprocess.run(["ffmpeg","-v","quiet","-i",VID,"-t","30","-f","s16le","-ac","2","-ar","16000","-"], capture_output=True).stdout
a = np.frombuffer(raw, np.int16).reshape(-1,2).astype(np.float32)/32768
print("stereo samples", a.shape)
segs=[(1.5,3.0,"ж"),(3.7,5.3,"ж"),(6.6,8.1,"Снейл смех"),(8.1,11.4,"Снейл пародия"),(11.4,14.5,"ж"),(13.8,16.9,"Снейл крик"),(17.8,20.5,"ж"),(22,25,"Снейл норм"),(25,30,"Снейл норм")]
for s,e,lab in segs:
    x=a[int(s*16000):int(e*16000)]; L,R=x[:,0],x[:,1]
    rl=np.sqrt((L**2).mean()); rr=np.sqrt((R**2).mean())
    corr=float(np.corrcoef(L,R)[0,1]); side=np.sqrt(((L-R)**2).mean())/ (np.sqrt(((L+R)**2).mean())+1e-9)
    print("%5.1f-%5.1f  L/R %.2f  corr %.3f  side/mid %.3f   %s" % (s,e, rl/(rr+1e-9), corr, side, lab))
