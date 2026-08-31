# -*- coding: utf-8 -*-
import io, json, urllib.request
OUT = r"E:\Loading\_atlas_tmp\llm2.txt"
def w(m):
    with io.open(OUT,"a",encoding="utf-8") as f: f.write(str(m)+"\n")
io.open(OUT,"w",encoding="utf-8").write("")
def ask(model):
    body=json.dumps({"model":model,"messages":[{"role":"user","content":"Скажи одно слово: работает"}],
                     "max_tokens":20,"temperature":0.2}).encode()
    req=urllib.request.Request("http://127.0.0.1:1234/v1/chat/completions",data=body,
                               headers={"Content-Type":"application/json"})
    try:
        r=urllib.request.urlopen(req,timeout=60)
        d=json.loads(r.read().decode("utf-8"))
        return "ОК: "+d["choices"][0]["message"]["content"][:80]
    except urllib.error.HTTPError as e:
        return "HTTP %s: %s"%(e.code,e.read().decode("utf-8","ignore")[:300])
    except Exception as e:
        return repr(e)[:200]
for m in ("qwen/qwen3.5-9b","google/gemma-4-e4b","openai/gpt-oss-20b",
          "qwen3-14b-abliterated","mistral-7b-grok"):
    w("%-32s %s" % (m, ask(m)))
# что настроено у Сайки
import sys; sys.path.insert(0,r"C:\AI\Saika\build\ANAMORF-0.2.1\app")
try:
    from anamorf.config import CFG
    w("\n--- настройки мозга ---")
    for k in ("llm.provider","llm.model","llm.base_url","llm.local_model",
              "llm.backend","llm.cloud","llm.enabled","llm.order"):
        w("  %s = %r" % (k, CFG.get(k)))
except Exception as e:
    w("конфиг: %r"%e)
