import wave, numpy as np, time, logging
from anamorf.stt import second
print(second.STATE)
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
got=[]
second.listen_async(stt, A[0:int(2.6*16000)], 16000, {"pid": 999, "text": "Где мо деньг? если бы…", "src":"sys"}, lambda e: got.append(e))
time.sleep(3); print("async ->", got)
