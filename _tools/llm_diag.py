# -*- coding: utf-8 -*-
import io, json, urllib.request
OUT = r"E:\Loading\_atlas_tmp\llm.txt"
def w(m):
    with io.open(OUT,"a",encoding="utf-8") as f: f.write(str(m)+"\n")
io.open(OUT,"w",encoding="utf-8").write("")
def get(p):
    try:
        r=urllib.request.urlopen("http://127.0.0.1:8765"+p,timeout=8)
        return json.loads(r.read().decode("utf-8"))
    except Exception as e: return {"ОШИБКА":repr(e)[:200]}
d=get("/api/llm")
w("--- /api/llm ---"); w(json.dumps(d,ensure_ascii=False,indent=1)[:1800])
# что слушает на 1234
try:
    r=urllib.request.urlopen("http://127.0.0.1:1234/v1/models",timeout=6)
    m=json.loads(r.read().decode("utf-8"))
    w("\n--- локальный сервер 1234: модели ---")
    for x in (m.get("data") or [])[:10]: w("  "+str(x.get("id")))
except Exception as e:
    w("\nлокальный сервер 1234: %r"%e)
