import json, urllib.request
d=json.load(urllib.request.urlopen("http://127.0.0.1:8765/api/polygon", timeout=10))
print({k:v for k,v in d.items() if k!="presets"}); print(len(d["presets"]), "пресетов")
r=json.load(urllib.request.urlopen("http://127.0.0.1:8765/api/polygon/ref?start=22&len=20", timeout=10)); print(r["lines"][:2])
