import wave, numpy as np, importlib
from anamorf.stt import second; importlib.reload(second)
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
for a,b,first in ((0,2.6,"Те мо."),(0,6.2,"А  А ты своей."),(13.8,17.0,"Да набейте еб."),(10.8,14.0,"Алло, ты! Она не вй женщине, которая говорит.")):
    print(a,b, repr(first), "->", second.listen(stt, A[int(a*16000):int(b*16000)], 16000, first), second.STATE.get("ms"))
