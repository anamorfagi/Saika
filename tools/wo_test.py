# -*- coding: utf-8 -*-
"""Проверка разметки слов по тембру на живом куске ролика (06.09.2026).

Проверяю СВОЮ новую функцию до того, как её увидит владелец: сколько
владельцев она находит на куске с двумя кричащими женщинами, какие у них
частоты и как слова распределились. Если владелец один — значит признак
всё ещё слаб, и это надо сказать, а не показывать пустоту.
"""
import io, json, sys, wave
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import numpy as np
from anamorf.stt.manager import STTManager
from anamorf.stt import stream_tone as T

with wave.open(str(ROOT/"data"/"first30.wav"), "rb") as w:
    SR = w.getframerate(); A = np.frombuffer(w.readframes(w.getnframes()), np.int16)

stt = STTManager()
n, hop = int(3*SR), int(2*SR)
rows = []
for i in range(0, min(len(A), 20*SR), hop):
    c = A[i:i+n]
    if len(c) < SR//2: break
    r = stt.transcribe_segment(c) or []
    txt = (r[0].get("text") if r else "") or ""
    if not txt.strip(): continue
    wc = T.word_owners(c, SR, txt)
    hzs = sorted({h for _w, h, _c in wc})
    rows.append({"t": round(i/SR,1), "text": txt[:70],
                 "владельцев": len(hzs), "Гц": hzs,
                 "слова": [[w, h] for w, h, _c in wc][:10]})
    print("%5.1fс | владельцев %d %s | %s" % (rows[-1]["t"], len(hzs), hzs, txt[:60]))
io.open(ROOT/"data"/"wo_test.json","w",encoding="utf-8").write(json.dumps(rows,ensure_ascii=False,indent=1))
multi = [r for r in rows if r["владельцев"] > 1]
print("\nкусков всего %d, с двумя владельцами %d" % (len(rows), len(multi)))
for r in multi[:3]:
    print("  %.1fс:" % r["t"], " ".join("%s(%d)" % (w,h) for w,h in r["слова"]))
