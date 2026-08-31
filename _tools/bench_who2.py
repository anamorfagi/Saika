# -*- coding: utf-8 -*-
"""СТЕНД v2: развёртка параметров разбора «кто это сказал».

Цифра, за которую боремся, — СБАЛАНСИРОВАННАЯ точность при ИСТИННОМ числе
людей. Общая точность обманывает: на этой записи один человек говорит две
трети времени, и «всё сказал он» даёт 65% при нулевом понимании.
"""
import io, os, sys, json, time, wave, traceback
import numpy as np

APP = r"C:\AI\Saika\build\ANAMORF-0.2.1\app"
WAV = r"C:\AI\Saika\build\ANAMORF-0.1.2\data\eval_take.wav"
GT  = r"C:\AI\Saika\build\ANAMORF-0.1.2\data\bench\pyannote_result5.json"
OUT = r"E:\Loading\_atlas_tmp\bench2.json"
LOG = r"E:\Loading\_atlas_tmp\bench2.log"
def note(m):
    with io.open(LOG,"a",encoding="utf-8") as f:
        f.write("[%s] %s\n"%(time.strftime("%H:%M:%S"),m))
try:
    note("=== развёртка ===")
    sys.path.insert(0,APP); os.environ["HF_HUB_OFFLINE"]="1"
    from anamorf.config import CFG
    CFG.set("voiceprint.encoder","ecapa"); CFG.set("voiceprint.device","cpu")
    from anamorf.voiceprint.encoder import Encoder
    enc=Encoder(); enc.warmup()
    note("кодировщик %s dim=%s"%(enc.backend,enc.dim))

    w=wave.open(WAV,"rb"); sr=w.getframerate()
    a=np.frombuffer(w.readframes(w.getnframes()),dtype=np.int16); w.close()
    gt=json.load(open(GT,encoding="utf-8"))["segments"]
    def truth_at(t):
        for s in gt:
            if s["start"]<=t<s["end"]: return s["spk"]
        return None
    NSPK=len(set(s["spk"] for s in gt))
    af=a.astype(np.float32)/32768.0

    from scipy.cluster.hierarchy import linkage,fcluster
    from scipy.spatial.distance import pdist,squareform

    def embed(win_s,hop_s,pure_only):
        nw,nh=int(win_s*sr),int(hop_s*sr)
        E,T,G=[],[],[]
        for off in range(0,max(0,len(a)-nw),nh):
            seg=af[off:off+nw]
            if float(np.sqrt((seg*seg).mean()))<0.006: continue
            t0,t1=off/sr,(off+nw)/sr
            g0,g1=truth_at(t0+0.05),truth_at(t1-0.05)
            g=truth_at((t0+t1)/2)
            if g is None: continue
            # окно на стыке двух людей — это СМЕСЬ, а не чей-то голос.
            # ECAPA на смеси выдаёт вектор «между», который потом тянет
            # кластеры друг к другу. Для чистоты замера их можно убрать.
            if pure_only and not (g0==g1==g): continue
            try: v,f0=enc.encode(a[off:off+nw])
            except Exception: continue
            if v is None: continue
            E.append(np.asarray(v,dtype=np.float32)); T.append((t0,t1)); G.append(g)
        E=np.array(E); E=E/(np.linalg.norm(E,axis=1,keepdims=True)+1e-9)
        return E,T,G

    def score(lab,G):
        pair={}
        for i,g in enumerate(G):
            pair.setdefault(lab[i],{}).setdefault(g,0); pair[lab[i]][g]+=1
        m={c:max(v,key=v.get) for c,v in pair.items()}
        per={}; ok=0
        for i,g in enumerate(G):
            good=(m.get(lab[i])==g); ok+=1 if good else 0
            d=per.setdefault(g,[0,0]); d[1]+=1; d[0]+=1 if good else 0
        bal=float(np.mean([d[0]/d[1] for d in per.values()])) if per else 0.
        return round(100.*ok/max(1,len(G)),1), round(100.*bal,1)

    def viterbi(E,lab,K,stay):
        """Говорящий не скачет каждые полсекунды. Штрафуем смену метки —
        одиночные чужие куски внутри длинной реплики выправляются."""
        cent=np.array([E[[i for i in range(len(lab)) if lab[i]==c]].mean(0)
                       for c in range(1,K+1)])
        cent=cent/(np.linalg.norm(cent,axis=1,keepdims=True)+1e-9)
        em=E@cent.T
        n=len(E); dp=np.zeros((n,K)); bk=np.zeros((n,K),dtype=int)
        dp[0]=em[0]
        for i in range(1,n):
            for k in range(K):
                cand=dp[i-1]+np.where(np.arange(K)==k,stay,0.0)
                j=int(np.argmax(cand)); bk[i,k]=j; dp[i,k]=cand[j]+em[i,k]
        out=[0]*n; out[-1]=int(np.argmax(dp[-1]))
        for i in range(n-1,0,-1): out[i-1]=bk[i,out[i]]
        return [c+1 for c in out]

    res={}
    for win in (1.5,2.0,2.5,3.0):
      for pure in (False,True):
        E,T,G=embed(win,0.5,pure)
        if len(E)<40: continue
        D=pdist(E,metric="cosine")
        for meth in ("average","complete","ward"):
            Z=linkage(D,method=meth)
            lab=list(fcluster(Z,NSPK,criterion="maxclust"))
            a1,b1=score(lab,G)
            best=(a1,b1,0.0)
            for stay in (0.05,0.12,0.25):
                try: lv=viterbi(E,lab,NSPK,stay)
                except Exception: continue
                a2,b2=score(lv,G)
                if b2>best[1]: best=(a2,b2,stay)
            key="окно%.1f_%s_%s"%(win,meth,"чистые" if pure else "все")
            res[key]={"как_есть":[a1,b1],"после_сглаживания":[best[0],best[1]],
                      "штраф":best[2],"кусков":len(G)}
            note("%-30s  %5.1f/%5.1f  ->  %5.1f/%5.1f (штраф %.2f, n=%d)"
                 %(key,a1,b1,best[0],best[1],best[2],len(G)))
    json.dump({"людей":NSPK,"результаты":res},io.open(OUT,"w",encoding="utf-8"),
              ensure_ascii=False,indent=1)
    note("ГОТОВО")
except Exception:
    note("ОШИБКА:\n"+traceback.format_exc())
