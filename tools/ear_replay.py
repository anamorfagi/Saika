import wave, numpy as np, time
from anamorf import hearing as H
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)/32768
H._active.clear(); H._last_sent=None; H.STATE["src"]="replay"
t=0.0
while t+1.0<=20.0:
    ch=A[int(t*16000):int((t+1.0)*16000)]
    tags,sp=H._classify(ch); H.STATE["speech"]=sp
    hum=H._human_events(tags)
    H._feed_sounds(H._spectral_veto(tags,ch), float(np.sqrt(np.mean(ch**2))))
    ev=H.pop_sounds()
    for e in ev: print(f"{t:5.1f} rms {float(np.sqrt(np.mean(ch**2))):.3f} hum {hum} ON {[(x['ru'],x['p'],x['kind']) for x in e['on']]} OFF {e['off']}")
    t+=0.5
    # linger в реальном времени — имитируем: сдвигаем last назад
    for v in H._active.values(): v["last"]-=0.5
H._active.clear(); H._last_sent=None
