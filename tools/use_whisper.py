import time
from anamorf.config import CFG
CFG.set("stt.engines.faster_whisper.vad_filter", False); CFG.set("stt.engines.faster_whisper.word_conf", False)
t0=time.time(); stt.set_engine("faster_whisper"); print("движок:", stt.current_name, "за %.1fs" % (time.time()-t0), "здоровье", stt.health.get("faster_whisper"))
import wave, numpy as np
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
stt.src_hint="sys"; c=A[8*16000:11*16000]
stt.transcribe_segment(c); t0=time.perf_counter(); r=stt.transcribe_segment(c); print("%.0f мс -> %s" % ((time.perf_counter()-t0)*1000, r))
