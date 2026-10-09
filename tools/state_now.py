import json, urllib.request, subprocess
def g(p):
    return json.load(urllib.request.urlopen("http://127.0.0.1:8765"+p, timeout=10))
m = g("/api/models")
print("models keys:", list(m.keys()))
print("loaded:", m.get("loaded"))
for k in ("current","selected","backend","model"):
    if k in m: print(k, m[k])
s = g("/api/system")
print("gpu:", {k:(round(v/2**30,2) if isinstance(v,(int,float)) and v>1e6 else v) for k,v in (s.get("gpu") or {}).items()})
print(subprocess.run(["tasklist","/FI","IMAGENAME eq llama-server.exe"],capture_output=True,text=True).stdout.strip().splitlines()[-1])
