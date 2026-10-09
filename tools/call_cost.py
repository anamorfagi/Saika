# -*- coding: utf-8 -*-
"""КУДА УХОДИТ ВРЕМЯ ОДНОГО ВЫЗОВА ДВИЖКА (06.09.2026).

Замер на видеокарте: 6 кусков по 6 с — 2.1 с, а 10 кусков по 3 с — 7.5 с.
Меньше звука, больше времени. Значит дорог не разбор, а ВЫЗОВ: что-то
фиксированное на каждый кусок. Здесь вызов разобран по частям на одном
и том же трёхсекундном куске, прогретом заранее.
"""
import sys, time, wave
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import numpy as np
from anamorf.config import CFG
from anamorf.stt.manager import STTManager
from anamorf.stt import engines as E

with wave.open(str(ROOT/"data"/"first30.wav"), "rb") as w:
    SR = w.getframerate(); A = np.frombuffer(w.readframes(w.getnframes()), np.int16)
c = A[8*SR:11*SR]                                  # 3 с из середины ора

stt = STTManager()
print("hearing.device =", CFG.get("hearing.device"))
stt.transcribe_segment(c)                          # прогрев
eng = None
for name, inst in stt.instances.items():
    if "giga" in name.lower(): eng = inst
print("движок:", type(eng).__name__ if eng else "не найден")

def t(label, fn, n=5):
    best = 1e9
    for _ in range(n):
        t0 = time.perf_counter(); fn(); best = min(best, time.perf_counter() - t0)
    print("  %-34s %6.0f мс (лучший из %d)" % (label, best*1000, n))

t("весь transcribe_segment (3 с)", lambda: stt.transcribe_segment(c))
if eng is not None:
    t("  только запись временного wav", lambda: E._to_wav_tempfile(c, SR))
    p = E._to_wav_tempfile(c, SR)
    t("  только model.transcribe(путь)", lambda: eng.model.transcribe(p))
    try:
        import torch
        dev = next(eng.model.parameters()).device if hasattr(eng.model, "parameters") else "?"
        print("  веса модели лежат на:", dev)
    except Exception as ex:
        print("  устройство весов не спросить:", repr(ex)[:80])
