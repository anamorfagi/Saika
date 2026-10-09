import json, urllib.request
def get(p): return json.load(urllib.request.urlopen("http://127.0.0.1:8765"+p, timeout=10))
def post(p,b):
    r=urllib.request.Request("http://127.0.0.1:8765"+p, data=json.dumps(b).encode(), headers={"Content-Type":"application/json"}); return json.load(urllib.request.urlopen(r,timeout=10))
print("get:", get("/api/polygon/markup"))
print("post:", post("/api/polygon/markup", {"lines":{"0":[{"w":"много","v":"ж1"},{"w":"денег-то","v":"ж1"}]},"voices":{}}))
print("get2:", get("/api/polygon/markup"))
print("reset:", post("/api/polygon/markup", {"lines":{},"voices":{}}))
