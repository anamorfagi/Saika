import wave, numpy as np
from anamorf.stt import stream_tone as T
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w:
    SR=w.getframerate(); A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
segs=[(1.5,3.0,"ж? 'Если бы ты свою'"),(3.7,5.3,"ж 'А ты своей'"),(6.6,8.1,"Снейл смех 'Ха-ха'"),(8.1,11.4,"Снейл пародия 'А ты свою пи!'"),(11.4,14.5,"ж 'Она... женщине, которая говорила'"),(13.8,16.9,"Снейл 'Да набейте ебальники'"),(17.8,20.5,"ж 'Я такая вот'"),(22,25,"Снейл норм 'Надо бы наверное ДНК'"),(25,30,"Снейл норм 'узнать почему ты не смотришь'")]
for a,b,lab in segs:
    seg=A[int(a*SR):int(b*SR)]
    vtl,share=T.vocal_tract(seg,SR); c=T.classify(seg,SR,"probe")
    print("%5.1f-%5.1f  тракт %5.1f см (кадров %.0f%%)  f0 %s Гц  -> %s   %s" % (a,b,vtl,share*100,c.get("tone_hz"),c.get("sex","?"),lab))
