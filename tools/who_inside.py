import gc, torch
print("EVENT_CLIENTS:", len(EVENT_CLIENTS))
try:
    print("WS_CLIENTS:", {k: v for k, v in globals().items() if k.startswith("WS_") and isinstance(v,(dict,set,list))})
except Exception as e: print(e)
def _isM(o):
    try: return isinstance(o, torch.nn.Module)
    except Exception: return False
engs=[o for o in gc.get_objects() if type(o).__name__=="GigaAMEngine"]
print("GigaAMEngine objs:", len(engs))
for e in engs:
    for r in gc.get_referrers(e):
        if isinstance(r, dict):
            ks=[k for k,v in r.items() if v is e][:3]
            owner=[type(o).__name__ for o in gc.get_referrers(r) if not isinstance(o,(list,tuple,dict))][:4]
            print("  held in dict keys", ks, "dict owned by", owner, "id", id(r))
print("stt.instances id", id(stt.instances), "stt type", type(stt).__name__)
mgrs=[o for o in gc.get_objects() if type(o).__name__==type(stt).__name__]
print("STT managers:", len(mgrs))
for m in mgrs:
    print("  ", id(m), "current", getattr(m,"current_name",None), "refs", [type(r).__name__ for r in gc.get_referrers(m) if not isinstance(r,(list,tuple))][:5])
