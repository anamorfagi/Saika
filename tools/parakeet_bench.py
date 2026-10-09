import re, sys, time, wave
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
import numpy as np
import onnx_asr, onnxruntime as ort
print("ort providers:", ort.get_available_providers())
t0=time.time()
model = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3")
print("parakeet загружен %.1fs" % (time.time()-t0))
SR=16000
def norm(t): return [x for x in re.findall(r"[а-яё]+", t.lower()) if len(x)>1]
def refwords(off, dur):
    ref={}
    for ln in open(ROOT/"slux_test"/"snailkik_dnk"/"transkrib.txt", encoding="utf-8"):
        m=re.match(r"(\d+):(\d\d)", ln)
        if not m: continue
        t=int(m.group(1))*60+int(m.group(2))-off
        if 0<=t<dur: ref.setdefault(int(t//10), []).extend(norm(re.sub(r"\[[^\]]*\]"," ",re.sub(r"^\S+\s*(минут\w*\s*\d*\s*)?секунд\w*","",ln))))
    return ref
def bench(A, off, dur, label):
    ref=refwords(off, dur); got={}; tt=0; t=0.0
    while t+3<=dur:
        seg=A[int(t*SR):int((t+3)*SR)].astype(np.float32)/32768
        t0=time.perf_counter(); txt=model.recognize(seg, language="ru") or ""; tt+=time.perf_counter()-t0
        got.setdefault(int(t//10), set()).update(norm(txt)); t+=1.5
    hit=miss=0
    for b,r in ref.items():
        g=got.get(b,set())|got.get(b-1,set())|got.get(b+1,set()); h=sum(1 for w in r if w in g); hit+=h; miss+=len(r)-h
    print("%s: найдено %d/%d = %.1f%%, %.0f мс на 3с-кусок" % (label, hit, hit+miss, 100*hit/max(1,hit+miss), 1000*tt/max(1,int(dur/1.5))))
with wave.open(str(ROOT/"data"/"first30.wav"),"rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
bench(A, 0, 22, "начало 0-22 (крик)")
for t in (0,3,6,9,12,15,18):
    print("  %2d: %s" % (t, (model.recognize(A[t*SR:(t+3)*SR].astype(np.float32)/32768, language="ru") or "")[:90]))
with wave.open(str(ROOT/"data"/"snailkick.wav"),"rb") as w: B=np.frombuffer(w.readframes(w.getnframes()), np.int16)
bench(B, 22*60, 180, "диалог 22:00-25:00")
