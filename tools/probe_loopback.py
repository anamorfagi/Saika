# -*- coding: utf-8 -*-
"""ГДЕ НА САМОМ ДЕЛЕ ЗВУК (2026-09-01).

Захват петли выбирал устройство по имени динамика по умолчанию и на этом
успокаивался. Если человек слушает через другой выход (Voicemeeter,
второй звуковой интерфейс), петля молча пишет тишину: индикация слуха
горит, а фраз нет ни одной. Догадками это не лечится — надо измерить.

Слушаем каждую петлю по секунде и печатаем громкость. Где не тишина —
там и звук.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import soundcard as sc

SR = 16000
print("Играй ролик, пока идёт замер.\n")
try:
    print("динамик по умолчанию:", sc.default_speaker().name, "\n")
except Exception as e:
    print("динамик по умолчанию не определился:", e, "\n")

rows = []
for m in sc.all_microphones(include_loopback=True):
    if not getattr(m, "isloopback", False):
        continue
    try:
        with m.recorder(samplerate=SR, channels=1, blocksize=1600) as r:
            a = r.record(numframes=SR)          # ровно секунда
        x = np.asarray(a, dtype=np.float32).ravel()
        rms = float(np.sqrt(np.mean(x * x)) + 1e-12)
        db = 20 * np.log10(rms) if rms > 1e-9 else -120.0
        peak = float(np.max(np.abs(x))) if x.size else 0.0
        rows.append((db, peak, m.name))
    except Exception as e:
        rows.append((-999.0, 0.0, m.name + "  [не открылась: %s]" % str(e)[:60]))

rows.sort(reverse=True)
print("%-9s %-7s %s" % ("гром,дБ", "пик", "устройство"))
for db, peak, name in rows:
    mark = "  <-- ЗДЕСЬ ЗВУК" if db > -60 else ("  тишина" if db > -900 else "")
    print("%-9s %-7.3f %s%s" % ("%.1f" % db if db > -900 else "  —",
                                peak, name, mark))
alive = [r for r in rows if r[0] > -60]
print("\nитог:", ("звук на «%s»" % alive[0][2]) if alive
      else "НИ НА ОДНОЙ ПЕТЛЕ ЗВУКА НЕТ — ролик молчит или выход другой")
