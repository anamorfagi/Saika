import json, urllib.request
for p in ("/api/status","/app"):
    try:
        r=urllib.request.urlopen("http://127.0.0.1:8765"+p, timeout=10); b=r.read(); print(p, r.status, len(b))
    except Exception as e: print(p, "ERR", e)
