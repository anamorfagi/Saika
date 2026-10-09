import time
from anamorf.config import CFG
CFG.set("stt.engines.gigaam.model", "v3_e2e_ctc")
t0=time.time()
stt.unload_engine("gigaam"); stt.load_engine("gigaam")
print("перезагрузила gigaam за %.1fs, model=%s" % (time.time()-t0, type(stt.instances["gigaam"].model).__name__), stt.instances["gigaam"].model.__class__.__module__)
print("head:", type(stt.instances["gigaam"].model.head).__name__)
