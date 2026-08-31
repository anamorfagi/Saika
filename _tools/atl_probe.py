import time, json, sys
import anamorf.main as M
r={}
A=M._ATLAS
th=A.get("sys_th")
r["sys_on"]=bool(A.get("sys_on"))
r["th_alive"]=bool(th and th.is_alive())
r["err"]=str(A.get("sys_err2",""))
i0=A.get("idx",0); n0=len(A.get("acc",[]))
time.sleep(3.0)
r["idx0"]=i0; r["idx1"]=A.get("idx",0); r["dframes"]=A.get("idx",0)-i0
r["acc"]=len(A.get("acc",[]))
try:
    cl=M.CLIENTS
    r["ws_clients"]=len(cl)
except Exception as e:
    r["ws_err"]=repr(e)
    for nm in dir(M):
        if "client" in nm.lower() or "WS" in nm:
            r.setdefault("cand",[]).append(nm)
open(r"C:\AI\Saika\_tools\atl_probe.json","w",encoding="utf-8").write(json.dumps(r,ensure_ascii=False))
