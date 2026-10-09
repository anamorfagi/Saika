import wave, numpy as np, importlib
from anamorf.stt import beep; importlib.reload(beep)
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
print("first30:", beep.find(A,16000))
seg=A[int(13.8*16000):int(17.0*16000)]
print(beep.mark("Да набейте ебальники друг другу уже все бля", beep.find(seg,16000), 3.2, [("Да",1.56,1.64),("набейте",1.8,2.28),("ебальники",2.4,3.2)]))
print(beep.mark("Да набейте друг другу", beep.find(seg,16000), 3.2, [("Да",1.56,1.64),("набейте",1.8,2.28),("друг",3.1,3.2)]))
