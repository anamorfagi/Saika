import json, time, urllib.request
from anamorf import appsound
def post(p, b):
    r = urllib.request.Request("http://127.0.0.1:8765" + p, data=json.dumps(b).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=10))
print(post("/api/media/cmd", {"op": "play", "pos": 30, "len": 8}))
for i in range(20):
    time.sleep(0.5)
    print("%4.1fs apps=%s loud_ago=%.1f" % (i*0.5, {k: round(v,2) for k,v in appsound.STATE["apps"].items()}, time.time()-_ATLAS.get("sys_loud_ts", 0)))
