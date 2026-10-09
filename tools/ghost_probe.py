# -*- coding: utf-8 -*-
"""Откуда «Нихуя»/«Сйас»: что на самом деле в этих кусках — по всем ушам."""
import wave, numpy as np
from anamorf import hearing as H
from anamorf.stt import second, frontend as fe
eng=stt.instances[stt.current_name]; wh=stt._get("faster_whisper")
for name in ("20260906_222642_00616.wav","20260906_222642_00617.wav","20260906_222638_00614.wav"):
    p=r"C:\AI\Saika\data\hear_bench\%s"%name
    with wave.open(p,"rb") as w: A=np.frombuffer(w.readframes(w.getnframes()),np.int16); sr=w.getframerate()
    x=A.astype(np.float32)/32768
    print("==",name,"sec",round(len(A)/sr,2),"rms",round(float(np.sqrt(np.mean(x**2))),4))
    t=eng._transcribe_direct(A); 
    from anamorf.stt import engines as E
    print("  gigaam:", repr(t), [(w[0],w[3]) for w in (E.LAST_WORDS.words or [])])
    try:
        tw=wh.transcribe(A,sr,language="auto"); print("  whisper auto:", repr(tw), "lang", wh.last_lang, round(wh.last_lang_p or 0,2), [(w["w"],w["p"]) for w in (wh.last_words or [])][:8])
    except Exception as e: print("  whisper:", e)
    # уши по окнам 1 с
    for t0 in np.arange(0, max(0.5,len(A)/sr-0.9), 0.5):
        ch=x[int(t0*sr):int((t0+1.0)*sr)]
        tags,sp=H._classify(ch); print("   уши %.1f: речь %.2f  %s" % (t0, sp, " · ".join("%s %.2f"%(n,pp) for n,pp in tags[:4])))
