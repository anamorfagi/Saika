import json, urllib.request
d=json.load(urllib.request.urlopen("http://127.0.0.1:8765/api/polygon", timeout=10))
sc=d.get("score") or {}
for r in sc.get("rows", []): print("%6.1f-%6.1f %5dмс  %s" % (r["a"], r["b"], r["ms"], r["text"]))
