import time, sys
from anamorf import hearing as H
print("model", type(H._model).__name__, "ready", H.STATE.get("ready"), "off", H.STATE.get("off"), "ts ago", round(time.time()-H.STATE.get("ts",0),1), "worker", H._worker and H._worker.is_alive(), "rms", H.STATE.get("rms"), "scale", H.STATE.get("scale"), "src", H.STATE.get("src"))
print("modules:", [k for k in sys.modules if k.endswith("hearing")])
print("_classify globals model:", type(H._classify.__globals__.get("_model")).__name__, H._classify.__globals__ is vars(H))
