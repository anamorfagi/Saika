import wave, numpy as np, re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
w=wave.open(str(ROOT/"data"/"probe_start.wav"),"rb"); a=np.frombuffer(w.readframes(w.getnframes()),np.int16).astype(np.float32)/32768
sr=w.getframerate(); print("длина %.1fс sr %d" % (len(a)/sr, sr))
# огибающая по 100 мс
n=int(sr*0.1); env=[float(np.sqrt(np.mean(a[i:i+n]**2))) for i in range(0,len(a)-n,n)]
first=next((i for i,e in enumerate(env) if e>0.01), None)
anchor=float(re.search(r"ts=([\d.]+)", (ROOT/"data"/"play_anchor.txt").read_text()).group(1))
t0=float((ROOT/"data"/"rec_t0.txt").read_text())
print("запись началась ~%.1fс до якоря; звук в петле появился на %.1fс записи" % (anchor-t0, (first or 0)*0.1))
print("огибающая 0.1с:", " ".join("%.2f"%e for e in env[:80]))
