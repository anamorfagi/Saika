import wave, numpy as np
from anamorf.stt import second
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
for a,b,first in ((0,2.9,"Можень сли бы ты."),(13.8,16.9,"Да набейте ебальникидруг…"),(8.1,11.4,"А ты свою пи! А ты свою!")):
    print(a,b, second.listen(stt, A[int(a*16000):int(b*16000)], 16000, first), second.STATE)
