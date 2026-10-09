import wave, numpy as np
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)/32768
SR=16000
segs=[(1.5,3.0,"ж 'Если бы ты свою'"),(3.7,5.3,"ж 'А ты своей'"),(6.6,8.1,"СНЕЙЛ смех"),(8.1,11.4,"СНЕЙЛ 'А ты свою пи!'"),(11.4,14.5,"ж 'Она... женщине'"),(13.8,16.9,"СНЕЙЛ 'Да набейте'"),(17.8,20.5,"ж 'Я такая вот'"),(22,25,"СНЕЙЛ норм"),(25,30,"СНЕЙЛ норм")]
def feats(x):
    n=1024; hop=256; spec=[]
    for i in range(0,len(x)-n,hop):
        w=x[i:i+n]*np.hanning(n); p=np.abs(np.fft.rfft(w))**2
        if p.sum()<1e-6: continue
        spec.append(p)
    P=np.mean(spec,0); hz=np.fft.rfftfreq(n,1/SR)
    cen=(P*hz).sum()/P.sum()
    hi=P[hz>=4000].sum()/P.sum(); lo=P[hz<200].sum()/P.sum()
    band = P[(hz>=6500)].sum()/P.sum()
    env=np.sqrt(np.convolve(x**2, np.ones(160)/160, "valid")); crest=env.max()/(env.mean()+1e-9)
    # «сухость»: автокорреляция огибающей на 30-80 мс (реверберация тянет хвост)
    e=env[::16]; e=e-e.mean(); ac=np.correlate(e,e,"full")[len(e)-1:]; ac/=ac[0]+1e-9
    tail=float(ac[30:80].mean())
    return cen,hi,lo,band,crest,tail
print("%-28s центроид  >4кГц   <200Гц  >6.5кГц  крест  хвост-ревер" % "")
for a,b,lab in segs:
    c,h,l,bd,cr,t=feats(A[int(a*SR):int(b*SR)])
    print("%-28s %6.0f   %.3f   %.3f   %.4f   %5.1f   %.2f" % (lab[:28],c,h,l,bd,cr,t))
