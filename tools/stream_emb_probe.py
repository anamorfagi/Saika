# потоковый отпечаток: окно W с, шаг 0.25 с, первые 20 с ролика; кластеры по косинусу
import wave, numpy as np, time
from anamorf import voiceprint as vp
enc = vp.S.enc
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
def cos(a,b): return float(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)+1e-9))
for W in (1.0, 1.5):
  for thr in (0.35, 0.45):
      ts=[]; chunks=[]
      t=0.0
      while t+W<=20.0:
          ch=A[int(t*16000):int((t+W)*16000)]
          if np.sqrt(np.mean((ch/32768.0)**2))>0.02: ts.append(t); chunks.append(ch)
          t+=0.25
      t0=time.time(); E=enc.encode_many(chunks); ms=(time.time()-t0)*1000/len(chunks)
      E=[np.asarray(e[0] if isinstance(e,(tuple,list)) else e).ravel() for e in E]
      # онлайн-кластеризация: примкнуть к центроиду если cos >= thr
      cents=[]; lab=[]
      for e in E:
          best=-1;bi=-1
          for i,c in enumerate(cents):
              s=cos(e,c/ (np.linalg.norm(c)+1e-9))
              if s>best: best,bi=s,i
          if bi>=0 and best>=thr: cents[bi]=cents[bi]+e; lab.append(bi)
          else: cents.append(e.copy()); lab.append(len(cents)-1)
      line="".join(str(l) if l<10 else "+" for l in lab)
      print(f"W={W}s thr={thr}  {ms:.1f} мс/окно  окон {len(E)}  кластеров {len(cents)}")
      print("  t:  "+" ".join(f"{int(x):>1d}" if x==int(x) and int(x)%2==0 else " " for x in ts))
      print("  id: "+" ".join(str(l) for l in lab))
