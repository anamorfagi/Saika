from anamorf import appsound
print(appsound.status())
import json
rows=[]
for ln in open(r"C:\AI\Saika\data\hear_bench\index.jsonl", encoding="utf-8").readlines()[-8:]:
    r=json.loads(ln); rows.append((r["at"], r.get("text","")[:60]))
print(rows)
