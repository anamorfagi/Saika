# первые 30 с через ту же нарезку, что и живой системный канал: где начинаются куски
import wave, numpy as np, time
from anamorf.stt import neuro_vad
from anamorf.stt.manager import VadSegmenter
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
live = HEAR_REFS.get("sys_vad",{}).get("v")
v = VadSegmenter()
for k in ("rms_threshold","silence_ms","min_speech_ms","preroll_ms","max_segment_s","max_wall_s","carry_ms"):
    try:
        if live is not None and hasattr(live,k): setattr(v,k,getattr(live,k))
    except Exception as e: print("copy",k,e)
print("thr", v._eff_threshold(), "neuro", neuro_vad.enabled(), neuro_vad.STATE.get("ready"), "gate", CFG.get("stt.vad.neuro_gate_rms"), "on/off", CFG.get("stt.vad.neuro_on"), CFG.get("stt.vad.neuro_off"))
step=1600; t=0.0; segs=[]
while t*16000+step<=len(A):
    p=A[int(t*16000):int(t*16000)+step]
    pr=None
    try: pr=neuro_vad.prob(p)
    except Exception: pass
    seg=v.push(p)
    if t<3.0: print(f"{t:4.1f}s rms {float(np.sqrt(np.mean((p/32768.0)**2))):.4f} neuro {pr if pr is None else round(float(pr),2)} in_speech {v.in_speech}")
    if seg is not None: segs.append((round(t-len(seg)/16000,2), round(t,2), round(len(seg)/16000,2)))
    t+=0.1
print("куски (начало, конец, длина):", segs[:12])
