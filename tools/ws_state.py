import time
# сколько живых очередей вкладок и что в них
try:
    qs = _HEAR_QS
    print("hear queues:", {k: (v.qsize() if hasattr(v,'qsize') else v) for k,v in (qs.items() if hasattr(qs,'items') else [])})
except Exception as e: print("no _HEAR_QS", e)
for nm in ("WS_CLIENTS","_WS","CLIENTS","_OUTS","OUT_QUEUES","_ws_outs"):
    if nm in globals(): print(nm, type(globals()[nm]).__name__, len(globals()[nm]) if hasattr(globals()[nm],'__len__') else '')
import inspect
src = inspect.getsource(broadcast_event)
print(src[-900:])
