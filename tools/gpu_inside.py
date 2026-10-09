TRIM=1
import gc, torch, sys
G=lambda b: round(b/2**30,2)
print("alloc", G(torch.cuda.memory_allocated()), "reserved", G(torch.cuda.memory_reserved()), "max", G(torch.cuda.max_memory_allocated()))
f,t=torch.cuda.mem_get_info(); print("device used", G(t-f))
if len(sys.argv)>99: pass
if TRIM:
    gc.collect(); torch.cuda.empty_cache()
    f,t=torch.cuda.mem_get_info(); print("after empty_cache: alloc", G(torch.cuda.memory_allocated()), "reserved", G(torch.cuda.memory_reserved()), "device used", G(t-f))
def _isM(o):
    try: return isinstance(o, torch.nn.Module)
    except Exception: return False
allm=[o for o in gc.get_objects() if _isM(o)]
objs=[o for o in allm if type(o).__name__=="GigaAMASR"]
print("GigaAMASR instances:", len(objs))
for o in objs:
    n=sum(p.numel()*p.element_size() for p in o.parameters())//2**20
    refs=[type(r).__name__ for r in gc.get_referrers(o) if not isinstance(r,(list,tuple))][:8]
    print("  ", n, "MB dtype", next(o.parameters()).dtype, "refs:", refs)
dps=[o for o in allm if isinstance(o, torch.nn.DataParallel)]
for o in dps:
    print("DataParallel wraps", type(o.module).__name__, sum(p.numel()*p.element_size() for p in o.parameters())//2**20, "MB")
try:
    print("stt instances:", {k: type(v).__name__ for k,v in stt.instances.items()})
except Exception as e: print("stt?", e)
import threading
print("threads:", threading.active_count())
for th in threading.enumerate(): print("  ", th.name)
