# -*- coding: utf-8 -*-
"""КАКОЙ УРОВЕНЬ У МИКРОФОНА НА САМОМ ДЕЛЕ (2026-09-01).

В подписях фраз мелькает «звук был тихий (rms 0.0052)» при пороге
0.006 — то есть речь идёт по краю ворот VAD, и часть фраз их не
открывает. Начало реплики теряется ещё до движка.

Пишем 6 секунд с выбранного входа и печатаем, что там: тишина, край
или нормальный уровень. Говори, пока идёт замер.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, sounddevice as sd
from anamorf.config import CFG
from anamorf.voice_local import _re_dev, LocalVoiceLoop

want = _re_dev.sub("", str(CFG.get("mic.device") or "")).strip()
dev = LocalVoiceLoop._pick_device(sd, want)
thr = float(CFG.get("stt.vad.rms_threshold", 0.012) or 0.012)
gate = float(CFG.get("stt.vad.neuro_gate_rms", 0.0025) or 0.0025)
print("вход: %r -> %s" % (want, dev))
print("порог речи (rms_threshold): %.4f" % thr)
print("ворота нейро-VAD:           %.4f\n" % gate)
print("ГОВОРИ 6 секунд...\n")

SR = 16000
frames = []
with sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                    device=dev, blocksize=int(SR*0.1)) as st:
    for _ in range(60):
        a, _of = st.read(int(SR*0.1))
        frames.append(np.asarray(a, np.float32).ravel())

x = np.concatenate(frames)
w = int(SR*0.1)
rms = np.array([float(np.sqrt(np.mean(x[i:i+w]**2)+1e-12))
                for i in range(0, len(x)-w, w)])
loud = rms[rms > gate]
print("%-26s %.4f" % ("пик (rms по 100мс)", float(rms.max())))
print("%-26s %.4f" % ("средний по громким", float(loud.mean()) if loud.size else 0))
print("%-26s %.4f" % ("медиана (фон)", float(np.median(rms))))
print("%-26s %d из %d" % ("кадров выше порога", int((rms > thr).sum()), len(rms)))
print("%-26s %.1f дБ" % ("пик в децибелах",
      20*np.log10(float(rms.max())+1e-12)))

peak = float(rms.max())
print()
if peak < gate:
    print("ИТОГ: тишина. Вход не тот или Voicemeeter не гонит сигнал.")
elif peak < thr*1.5:
    print("ИТОГ: голос ЕДВА перешагивает порог (%.4f против %.4f)." % (peak, thr))
    print("      Именно поэтому теряются начала фраз.")
    print("      Надо либо поднять усиление входа, либо опустить порог.")
    print("      Рекомендую порог: %.4f" % max(peak*0.35, 0.0015))
else:
    print("ИТОГ: уровень нормальный, запас %.1fx над порогом." % (peak/thr))
