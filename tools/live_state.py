import time, threading
print("LIVE_GIGA:", {k:v for k,v in LIVE_GIGA.items() if k!="words"})
sv = HEAR_REFS.get("sys_vad") or {}
print("sys vad:", sv.get("v") is not None, "apps:", list((sv.get("apps") or {}).keys()))
for k,v in (sv.get("apps") or {}).items(): print(" ", k, "in_speech", getattr(v,"in_speech",None), "speech_samples", getattr(v,"speech_samples",None), "buf", len(getattr(v,"buffer",[]) or []))
print("threads:", [t.name for t in threading.enumerate() if "live" in t.name or "warm" in t.name])
print("cfg live_giga:", CFG.get("stt.live_giga"), CFG.get("stt.live_giga_every_s"))
