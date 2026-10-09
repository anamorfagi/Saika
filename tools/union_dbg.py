import wave, numpy as np, importlib, difflib, re
from anamorf.stt import second; importlib.reload(second)
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
seg=A[0:int(2.6*16000)]
r=second.listen(stt, seg, 16000, "Те мо.")
print(r, second.STATE.get("wprob"))
print(second._union("Те мо.", "Где много денег-то было, если бы ты союз? Ну!", second.STATE.get("wprob"), 0.75))
