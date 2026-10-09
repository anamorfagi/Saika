import re, sys, time, wave
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import numpy as np
SR=16000
with wave.open(str(ROOT/"data"/"first30.wav"),"rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
def norm(t): return [x for x in re.findall(r"[а-яё]+", t.lower()) if len(x)>1]
ref=[]
for ln in open(ROOT/"slux_test"/"snailkik_dnk"/"transkrib.txt", encoding="utf-8"):
    m=re.match(r"(\d+):(\d\d)", ln)
    if not m: continue
    t=int(m.group(1))*60+int(m.group(2))
    if t<22: ref+=norm(re.sub(r"\[[^\]]*\]"," ",re.sub(r"^\S+\s*секунд\w*","",ln)))
rs=set(ref); print("эталон 0-22:", len(rs), "уникальных")
from faster_whisper import WhisperModel
t0=time.time()
m=WhisperModel("mobiuslabsgmbh/faster-whisper-large-v3-turbo", device="cuda", compute_type="float16")
print("whisper загружен %.1fs" % (time.time()-t0))
found=set(); tt=0; texts=[]
for t in np.arange(0, 20, 1.5):
    seg=A[int(t*SR):int((t+3)*SR)].astype(np.float32)/32768
    t0=time.time()
    segs,_=m.transcribe(seg, language="ru", beam_size=1, vad_filter=False, condition_on_previous_text=False)
    txt=" ".join(s.text for s in segs); tt+=time.time()-t0
    texts.append((t,txt.strip())); found|=set(norm(txt))&rs
print("whisper-turbo 3с/1.5с: найдено %d/%d = %.1f%%, время %.2fс на 3с-кусок" % (len(found), len(rs), 100*len(found)/len(rs), tt/len(texts)))
for t,x in texts: print("  %4.1f  %s" % (t, x[:90]))
# целиком 0-22 одним куском
t0=time.time(); segs,_=m.transcribe(A[:22*SR].astype(np.float32)/32768, language="ru", beam_size=5, vad_filter=False)
full=" ".join(s.text for s in segs); print("целиком 22с (%.1fс): найдено %.1f%%: %s" % (time.time()-t0, 100*len(set(norm(full))&rs)/len(rs), full[:300]))
