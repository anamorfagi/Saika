# -*- coding: utf-8 -*-
"""ФОКУС ПО ГАРМОНИКАМ: две женщины орут разом (8-11.5 с ролика ДНК).
Идея владельца: «вычленить их слова из каши относительно частот и собрать
в две дорожки». У каждого голоса своя высота F0 и гармоники k*F0 — берём
СТФТ, в каждом кадре ищем две высоты (гребёнки, не кратные друг другу),
делаем маску вокруг гармоник каждой и слушаем две дорожки движком."""
import wave, numpy as np, re, time
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
SR=16000
def norm(t): return [x for x in re.findall(r"[а-яё]+", t.lower()) if len(x)>1]
REF = norm("ты свою пи А ты свою ты они женщине, которая позвонили он Она не забыла")
def hits(txt):
    w=norm(txt); r=list(REF); n=0
    for x in w:
        if x in r: r.remove(x); n+=1
    return n, len(w)
eng = stt.instances[stt.current_name]
def ask(x16):
    return eng._transcribe_direct(np.clip(x16,-32767,32767).astype(np.int16)) or ""

N=1024; H=256; win=np.hanning(N).astype(np.float32); fq=np.fft.rfftfreq(N,1/SR)
def stft(x):
    fr=[x[i:i+N]*win for i in range(0,len(x)-N,H)]
    return np.fft.rfft(np.stack(fr),axis=1)
def istft(S,n):
    y=np.zeros(n,np.float32); wsum=np.zeros(n,np.float32)
    for k,fr in enumerate(np.fft.irfft(S,axis=1)):
        i=k*H; y[i:i+N]+=fr*win; wsum[i:i+N]+=win**2
    return y/np.maximum(wsum,1e-3)
def comb_score(mag, f0):
    # сумма энергии на гармониках k*f0 (до 4 кГц) с узкой полосой
    s=0.0
    for k in range(1,int(4000/f0)+1):
        b=(fq>=k*f0*0.97)&(fq<=k*f0*1.03); s+=mag[b].max() if b.any() else 0
    return s/ (int(4000/f0)+1)
def two_pitches(mag):
    cands=np.arange(90,420,4.0)
    sc=np.array([comb_score(mag,f) for f in cands])
    i=int(sc.argmax()); f1=cands[i]
    # вторая — не кратная первой (не октава, не та же)
    ok=np.array([not (abs(f/f1-1)<0.12 or abs(f/f1-2)<0.12 or abs(f1/f-2)<0.12) for f in cands])
    sc2=np.where(ok,sc,-1); j=int(sc2.argmax()); f2=cands[j]
    return (f1,sc[i]),(f2,sc2[j])
def mask_for(f0, width=0.06):
    m=np.zeros(len(fq),np.float32)
    for k in range(1,int(5000/f0)+1):
        b=(fq>=k*f0*(1-width))&(fq<=k*f0*(1+width)); m[b]=1.0
    m[fq<90]=0.3
    return m

for a,b,lab in ((7.9,11.6,"8-11.6"),(10.8,14.0,"10.8-14 девушка+мужик"),(4.2,6.2,"4.2-6.2 две девушки"),):
    x=A[int(a*SR):int(b*SR)].astype(np.float32)
    base=ask(x); print(f"[{lab}] смесь: {hits(base)} {base!r}")
    S=stft(x); mag=np.abs(S)
    trk1=[];trk2=[]
    M1=np.zeros_like(mag);M2=np.zeros_like(mag)
    prev=None
    for t in range(mag.shape[0]):
        (f1,s1),(f2,s2)=two_pitches(mag[t])
        # непрерывность: дорожка 1 — ближе к прошлой f1
        if prev is not None and abs(f2-prev[0])<abs(f1-prev[0]): f1,f2,s1,s2=f2,f1,s2,s1
        prev=(f1,f2); trk1.append(f1); trk2.append(f2)
        M1[t]=mask_for(f1); M2[t]=mask_for(f2)
    # где маски пересекаются — делим по силе гребёнки
    both=(M1>0)&(M2>0); M1b=M1.copy(); M2b=M2.copy(); M1b[both]=0.5; M2b[both]=0.5
    y1=istft(S*M1b,len(x)); y2=istft(S*M2b,len(x))
    t1=ask(y1*1.5); t2=ask(y2*1.5)
    print(f"  дорожка1 F0~{np.median(trk1):.0f} Гц: {hits(t1)} {t1!r}")
    print(f"  дорожка2 F0~{np.median(trk2):.0f} Гц: {hits(t2)} {t2!r}")
    h=hits(t1)[0]+hits(t2)[0]; print(f"  вместе {h} из {len(REF)} слов эталона (смесь {hits(base)[0]})")
    # вариант «фокус на одну высоту»: узкая маска только 1 дорожки без делёжки
    y1s=istft(S*M1,len(x)); y2s=istft(S*M2,len(x))
    print("  жёстко:", hits(ask(y1s*1.5)), repr(ask(y1s*1.5)), "|", hits(ask(y2s*1.5)), repr(ask(y2s*1.5)))
