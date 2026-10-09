print("clients:", len(EVENT_CLIENTS))
import threading; print([t.name for t in threading.enumerate() if t.name in ("hear","stt","ui-live","code-live")])
