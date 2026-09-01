# -*- coding: utf-8 -*-
"""Поднимается ли определитель языка и сколько он думает (2026-09-01)."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from anamorf.stt import langid

print("грею определитель...")
t0 = time.monotonic()
m = langid._load()
print("поднялся за %.1fс: %s" % (time.monotonic()-t0, "да" if m else "НЕТ"))
if not m:
    print("причина:", langid.S.get("err")); raise SystemExit

x = (np.random.default_rng(0).normal(0, 0.05, 16000*2)).astype(np.float32)
for i in range(3):
    t0 = time.monotonic()
    lang, p = langid.detect(x, 16000)
    print("прогон %d: %s (%.2f) за %.0f мс"
          % (i+1, lang, p, (time.monotonic()-t0)*1000))
print("\nмаршрут: ru ->", langid.engine_for("ru"),
      "| en ->", langid.engine_for("en"),
      "| ja ->", langid.engine_for("ja"))
