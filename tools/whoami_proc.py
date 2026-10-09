# -*- coding: utf-8 -*-
"""Кто сейчас на порту 8765 и живы ли его потоки (05.09.2026)."""
import io, os, sys, time, json
from pathlib import Path
from urllib import request
ROOT = Path(__file__).resolve().parents[1]
O=[]
def say(*a): print(" ".join(str(x) for x in a)); O.append(" ".join(str(x) for x in a))
try:
    import psutil
    me = os.getpid()
    for p in psutil.process_iter(["pid","name","create_time","cmdline"]):
        cl = " ".join(p.info.get("cmdline") or [])[:120]
        if "python" in (p.info.get("name") or "").lower() and ("main" in cl or "anamorf" in cl or "saika" in cl.lower()):
            say("pid %-7d поднят %s  %s" % (p.info["pid"],
                time.strftime("%H:%M:%S", time.localtime(p.info["create_time"])), cl))
except Exception as e:
    say("psutil:", repr(e)[:120])
try:
    with request.urlopen("http://127.0.0.1:8765/api/status", timeout=10) as r:
        d = json.loads(r.read().decode("utf-8"))
    say("сервер отвечает, ключей в статусе:", len(d))
    say("boot:", d.get("boot"), " uptime:", d.get("uptime"))
except Exception as e:
    say("сервер:", repr(e)[:150])
say("время сейчас:", time.strftime("%H:%M:%S"))
io.open(ROOT/"data"/"whoami.txt","w",encoding="utf-8").write("\n".join(O))
