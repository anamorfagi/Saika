# -*- coding: utf-8 -*-
"""Проверка фильтра: пускает ли он «машину» на клавиатурный треск."""
import io, sys, numpy as np
sys.path.insert(0, r"C:\AI\Saika\build\ANAMORF-0.2.1\app")
OUT = r"E:\Loading\_atlas_tmp\veto.txt"
from anamorf import hearing as H
sr = 16000
rng = np.random.default_rng(3)

def keyboard(dur=2.0):
    """щелчки: короткие широкополосные всплески с паузами"""
    x = np.zeros(int(dur * sr), dtype=np.float32)
    for t in np.arange(0.05, dur - 0.05, 0.12):
        i = int(t * sr); L = int(0.012 * sr)
        x[i:i + L] += (rng.standard_normal(L) * np.exp(-np.linspace(0, 6, L))).astype(np.float32)
    return x * 0.5

def car(dur=2.0):
    """гул: низкие частоты, ровный по времени"""
    t = np.arange(int(dur * sr)) / sr
    x = (0.5 * np.sin(2 * np.pi * 90 * t) + 0.3 * np.sin(2 * np.pi * 150 * t)
         + 0.15 * np.sin(2 * np.pi * 220 * t))
    x += 0.04 * rng.standard_normal(x.size)
    return x.astype(np.float32) * 0.5

fake = [("Vehicle", 0.62), ("Car", 0.41), ("Computer keyboard", 0.33)]
with io.open(OUT, "w", encoding="utf-8") as f:
    for nm, sig in (("КЛАВИАТУРА", keyboard()), ("МАШИНА (гул)", car())):
        out = H._spectral_veto(list(fake), sig)
        kept = [n for n, _ in out]
        f.write("%-14s -> метки после фильтра: %s\n" % (nm, kept))
        f.write("                 уличное пропущено: %s\n" %
                ("ДА" if any(k in " ".join(kept).lower()
                             for k in ("vehicle", "car")) else "НЕТ"))
