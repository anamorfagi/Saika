# -*- coding: utf-8 -*-
"""Через какой выход её микрофон реально нас услышит? Перебираем и меряем."""
import io, time, numpy as np
OUT = r"E:\Loading\_atlas_tmp\findout.txt"
def w(m):
    with io.open(OUT,"a",encoding="utf-8") as f: f.write(str(m)+"\n")
io.open(OUT,"w",encoding="utf-8").write("")
import sounddevice as sd
sr=16000
t=np.arange(int(1.2*sr))/sr
tone=(0.6*np.sin(2*np.pi*500*t)+0.3*np.sin(2*np.pi*1200*t)).astype(np.float32)
cands=[]
for i,d in enumerate(sd.query_devices()):
    if d.get("max_output_channels",0)<1: continue
    nm=d["name"]
    api=sd.query_hostapis(d["hostapi"])["name"]
    if api!="Windows DirectSound": continue
    if any(k in nm.lower() for k in ("realtek","speaker","динамик","cable input","headphone","наушник","galaxy","buds")):
        cands.append((i,nm))
w("кандидаты: %d"%len(cands))
base=None
try:
    r=sd.rec(int(1.0*sr),samplerate=sr,channels=1,dtype="float32"); sd.wait()
    base=float(np.sqrt((r**2).mean())); w("фон=%.5f"%base)
except Exception as e: w("фон не снят: %r"%e)
best=(None,0.0)
for i,nm in cands:
    try:
        rec=sd.rec(int(1.5*sr),samplerate=sr,channels=1,dtype="float32")
        sd.play(tone,sr,device=i); sd.wait()
        v=np.asarray(rec,dtype=np.float64).ravel()
        v=v[np.isfinite(v)]
        rms=float(np.sqrt((v**2).mean())) if v.size else 0.0
        w("[%3d] %-52s микрофон слышит RMS=%.5f"%(i,nm[:52],rms))
        if rms>best[1]: best=((i,nm),rms)
    except Exception as e:
        w("[%3d] %-52s не вышло: %r"%(i,nm[:52],e))
w("\nЛУЧШИЙ: %s (RMS %.5f)"%(best[0],best[1]))
