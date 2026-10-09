# опрашивает /api/hear/tone 10 раз/с во время прогона 0-20 и пишет, когда меняется текст
import json, time, urllib.request, threading
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def get(p): return json.load(urllib.request.urlopen("http://127.0.0.1:8765"+p, timeout=5))
def post(p,b):
    r=urllib.request.Request("http://127.0.0.1:8765"+p, data=json.dumps(b).encode(), headers={"Content-Type":"application/json"}); return json.load(urllib.request.urlopen(r,timeout=20))
post("/api/chat/clear", {})
post("/api/media/cmd", {"op":"play","pos":0,"len":20})
t0=time.time(); last=""; log=[]
while time.time()-t0 < 24:
    try: d=get("/api/hear/tone")
    except Exception: time.sleep(0.1); continue
    t=(d.get("t") or "").strip()
    if t!=last:
        log.append((round(time.time()-t0,1), d.get("by") or "tone", d.get("giga_ms"), t[-90:])); last=t
    time.sleep(0.1)
for r in log: print("%5.1f %-4s %3s мс  %s" % r)
d=get("/api/hear/tone"); print("runs", d.get("giga_runs"))
