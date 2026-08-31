# -*- coding: utf-8 -*-
"""Освободить видеокарту от чужой LM Studio и поднять ЕЁ собственный мозг."""
import io, json, time, urllib.request
OUT = r"E:\Loading\_atlas_tmp\brainfix.txt"
def w(m):
    with io.open(OUT,"a",encoding="utf-8") as f: f.write(str(m)+"\n")
io.open(OUT,"w",encoding="utf-8").write("")
def post(path, body):
    d=json.dumps(body).encode()
    r=urllib.request.Request("http://127.0.0.1:8765"+path,data=d,
                             headers={"Content-Type":"application/json"})
    try:
        return json.loads(urllib.request.urlopen(r,timeout=240).read().decode())
    except Exception as e:
        return {"ОШИБКА":repr(e)[:250]}
w("1) выгружаю чужую модель из LM Studio")
for m in ("mistral-7b-grok","qwen3-14b-abliterated"):
    w("   %s -> %s" % (m, json.dumps(post("/api/llm/model",
        {"backend":"lmstudio","name":m,"action":"unload"}),ensure_ascii=False)[:200]))
time.sleep(3)
w("2) поднимаю её llama.cpp с Qwen3.5-9B (оценка владельца 10)")
w("   -> %s" % json.dumps(post("/api/llm/model",
    {"backend":"llamacpp","name":"Qwen3.5-9B-Q4_K_M","action":"load"}),ensure_ascii=False)[:400])
