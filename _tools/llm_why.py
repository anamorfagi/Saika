# -*- coding: utf-8 -*-
"""Почему мозг молчит: спрашиваем каждый путь по отдельности."""
import io, sys, json, traceback
sys.path.insert(0, r"C:\AI\Saika\build\ANAMORF-0.2.1\app")
OUT = r"E:\Loading\_atlas_tmp\llmwhy.txt"
def w(m):
    with io.open(OUT,"a",encoding="utf-8") as f: f.write(str(m)+"\n")
io.open(OUT,"w",encoding="utf-8").write("")
try:
    from anamorf.config import CFG
    from anamorf.llm import llamacpp
    w("llamacpp.base_url() = %r" % llamacpp.base_url())
    for k in ("llm.backend","llm.model","llm.lmstudio_url","llm.llamacpp_url",
              "llm.port","llamacpp.port","llm.cloud"):
        w("  %s = %r" % (k, CFG.get(k)))
    from anamorf.llm import manager as M
    w("\n--- пробую chat_once ---")
    try:
        from anamorf import llm as L
        r = L.chat_once([{"role":"user","content":"скажи: работает"}])
        w("chat_once -> %r" % (str(r)[:400],))
    except Exception:
        w("chat_once упал:\n"+traceback.format_exc()[:1200])
except Exception:
    w("ОШИБКА:\n"+traceback.format_exc()[:2000])
