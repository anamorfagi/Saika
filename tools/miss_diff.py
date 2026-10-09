# какие слова эталона потерялись в ленте, но нашлись офлайн-движком (по 10-с бинам)
import json, re, sys, wave
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/"third_party"/"GigaAM"))
import numpy as np, torch, gigaam
OFF=22*60; DUR=180; SR=16000
def norm(t): return [x for x in re.findall(r"[а-яё]+", t.lower()) if len(x) > 1]
ref={}
for ln in open(ROOT/"slux_test"/"snailkik_dnk"/"transkrib.txt", encoding="utf-8"):
    m=re.match(r"(\d+):(\d\d)", ln)
    if not m: continue
    t=int(m.group(1))*60+int(m.group(2))-OFF
    if 0<=t<DUR: ref.setdefault(int(t//10), []).extend(norm(re.sub(r"^\S+\s*(минут\w*\s*\d*\s*)?секунд\w*", "", ln)))
start=float(open(ROOT/"data"/"replay_start.txt").read().strip())
feed={}
for ln in open(ROOT/"data"/"hear_bench"/"index.jsonl", encoding="utf-8"):
    r=json.loads(ln)
    if start<=r["ts"]<=start+DUR+15:
        end=r["ts"]-start-r.get("ms",0)/1000.0; a=end-r.get("sec",0)
        feed.setdefault(int(max(a,0)//10), set()).update(norm(r.get("text","")))
with wave.open(str(ROOT/"data"/"snailkick.wav"),"rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
m=gigaam.load_model("v3_e2e_ctc")
def asr(pcm):
    wav=torch.from_numpy(pcm.astype(np.float32)/32768.0).to(m._device).unsqueeze(0); ln=torch.full([1],wav.shape[-1],device=m._device)
    with torch.inference_mode(): enc,el=m.forward(wav,ln); return m._decode(enc,el,ln,False)[0][0]
off={}; t=0.0
while t+3<=DUR:
    off.setdefault(int(t//10), set()).update(norm(asr(A[int(t*SR):int((t+3)*SR)]))); t+=1.5
def near(d,b): return d.get(b,set())|d.get(b-1,set())|d.get(b+1,set())
for b in sorted(ref):
    r=ref[b]; f=near(feed,b); o=near(off,b)
    lost=[w for w in r if w not in f and w in o]; both=[w for w in r if w not in f and w not in o]
    if lost or both: print("%3d-%3dс  потеряла лента, а движок нашёл: %s || не нашёл никто: %s" % (b*10,b*10+10, " ".join(lost), " ".join(both)))
