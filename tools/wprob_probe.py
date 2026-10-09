import wave, numpy as np
from anamorf.stt import second, frontend as fe
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
print("cfg word_conf:", CFG.get("stt.engines.faster_whisper.word_conf"), CFG.get("stt.engines.faster_whisper",{}).get("word_conf"))
eng=stt._get("faster_whisper")
for a,b in ((0,6.2),(0,2.6),(13.8,17.0)):
    x=fe.prepare(A[int(a*16000):int(b*16000)],16000,CFG.get("stt.frontend",{}) or {})
    t=eng.transcribe(x,16000); print(a,b,repr(t)); print("   ", [(w["w"],w["p"]) for w in (eng.last_words or [])])
