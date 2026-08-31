# -*- coding: utf-8 -*-
"""СТЕНД v3: сколько людей в разговоре — система должна решать САМА.

В бою числа говорящих никто не сообщает. Ищем порог по дендрограмме
(ward), при котором число кластеров совпадает с правдой, и проверяем,
насколько он устойчив.
"""
import io, os, sys, json, time, wave, traceback
import numpy as np
APP=r"C:\AI\Saika\build\ANAMORF-0.2.1\app"
WAV=r"C:\AI\Saika\build\ANAMORF-0.1.2\data\eval_take.wav"
GT =r"C:\AI\Saika\build\ANAMORF-0.1.2\data\bench\pyannote_result5.json"
OUT=r"E:\Loading\_atlas_tmp\bench3.json"
LOG=r"E:\Loading\_atlas_tmp\bench3.log"
def note(m):
    with io.open(LOG,"a",encoding="utf-8") as f:
        f.write("[%s] %s\n"%(time.strftime("%H:%M:%S"),m))
try:
    note("=== авто-число людей ===")
    sys.path.insert(0,APP); os.environ["HF_HUB_OFFLINE"]="1"
    from anamorf.config import CFG
    CFG.set("voiceprint.encoder","ecapa"); CFG.set("voiceprint.device","cpu")
    from anamorf.voiceprint.encoder import Encoder
    enc=Encoder(); enc.warmup(); note("кодировщик %s"%enc.backend)
    w=wave.open(WAV,"rb"); sr=w.getframerate()
    a=np.frombuffer(w.readframes(w.getnframes()),dtype=np.int16); w.close()
    gt=json.load(open(GT,encoding="utf-8"))["segments"]
    def truth_at(t):
        for s in gt:
            if s["start"]<=t<s["end"]: return s["spk"]
        return None
    NSPK=len(set(s["spk"] for s in gt))
    af=a.astype(np.float32)/32768.0
    WIN,HOP=2.0,0.5; nw,nh=int(WIN*sr),int(HOP*sr)
    E,G=[],[]
    for off in range(0,max(0,len(a)-nw),nh):
        seg=af[off:off+nw]
        if float(np.sqrt((seg*seg).mean()))<0.006: continue
        g=truth_at((off+nw/2)/sr)
        if g is None: continue
        try: v,f0=enc.encode(a[off:off+nw])
        except Exception: continue
        if v is None: continue
        E.append(np.asarray(v,dtype=np.float32)); G.append(g)
    E=np.array(E); E=E/(np.linalg.norm(E,axis=1,keepdims=True)+1e-9)
    note("кусков %d, людей на самом деле %d"%(len(G),NSPK))
    from scipy.cluster.hierarchy import linkage,fcluster
    from scipy.spatial.distance import pdist
    Z=linkage(pdist(E,metric="cosine"),method="ward")
    def score(lab):
        pair={}
        for i,g in enumerate(G):
            pair.setdefault(lab[i],{}).setdefault(g,0); pair[lab[i]][g]+=1
        m={c:max(v,key=v.get) for c,v in pair.items()}
        per={}; ok=0
        for i,g in enumerate(G):
            good=(m.get(lab[i])==g); ok+=1 if good else 0
            d=per.setdefault(g,[0,0]); d[1]+=1; d[0]+=1 if good else 0
        return (round(100.*ok/len(G),1),
                round(100.*float(np.mean([d[0]/d[1] for d in per.values()])),1))
    def viterbi(lab,K,stay=0.15):
        cs=sorted(set(lab)); idx={c:i for i,c in enumerate(cs)}
        cent=np.array([E[[i for i in range(len(lab)) if lab[i]==c]].mean(0) for c in cs])
        cent=cent/(np.linalg.norm(cent,axis=1,keepdims=True)+1e-9)
        em=E@cent.T; K=len(cs); n=len(E)
        dp=np.zeros((n,K)); bk=np.zeros((n,K),dtype=int); dp[0]=em[0]
        for i in range(1,n):
            for k in range(K):
                cand=dp[i-1]+np.where(np.arange(K)==k,stay,0.)
                j=int(np.argmax(cand)); bk[i,k]=j; dp[i,k]=cand[j]+em[i,k]
        out=[0]*n; out[-1]=int(np.argmax(dp[-1]))
        for i in range(n-1,0,-1): out[i-1]=bk[i,out[i]]
        return [cs[c] for c in out]
    res={}
    for t in [round(x,2) for x in np.arange(0.6,3.01,0.1)]:
        lab=list(fcluster(Z,t,criterion="distance"))
        k=len(set(lab))
        if k<1 or k>25: continue
        a1,b1=score(lab)
        lv=viterbi(lab,k); a2,b2=score(lv)
        res["t=%.2f"%t]={"кластеров":k,"как_есть":[a1,b1],"сглажено":[a2,b2]}
        note("порог %.2f -> людей %2d   %5.1f/%5.1f  ->  %5.1f/%5.1f%s"
             %(t,k,a1,b1,a2,b2,"   <== верное число" if k==NSPK else ""))
    json.dump({"истинных_людей":NSPK,"результаты":res},
              io.open(OUT,"w",encoding="utf-8"),ensure_ascii=False,indent=1)
    note("ГОТОВО")
except Exception:
    note("ОШИБКА:\n"+traceback.format_exc())
