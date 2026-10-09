# -*- coding: utf-8 -*-
"""Прогнать конвейер слуха по файлу и записать, ЧТО и КОГДА он услышал.

Владелец: «сравни сам, что он написал и на какой минуте это».
Живой лог для этого не годится: там время стенное, а не время ролика,
и куда именно доехал плеер — неизвестно. Поэтому берём файл с точно
известным началом (кусок 10:00–13:00) и гоняем ТОТ ЖЕ путь: нарезка
VadSegmenter + движок через STTManager. Каждой реплике проставляем
время ОТ НАЧАЛА КУСКА — по нему потом и сверяем с эталоном.

Отдельный процесс: живую Сайку не трогаем, её очередь не занимаем."""
import io, json, os, sys, time, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

WAV = ROOT / "data" / (sys.argv[1] if len(sys.argv) > 1 else "bench_1000_1300.wav")
OUT = ROOT / "data" / (WAV.stem + "_heard.jsonl")

import numpy as np
from anamorf.config import CFG
from anamorf.stt.manager import VadSegmenter, STTManager

with wave.open(str(WAV), "rb") as w:
    sr = w.getframerate()
    pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
print("файл %s: %.1f с, %d Гц" % (WAV.name, len(pcm)/sr, sr))

vad = VadSegmenter()
stt = STTManager()
stt.src_hint = "sys"          # тот же канал, что у ролика
stt.queue_hint = 0
print("движок:", stt.current_name)

CH = int(sr * 0.032)          # 32 мс — как в живом цикле
rows, t0 = [], time.monotonic()
pos = 0
seg_start = None
while pos < len(pcm):
    chunk = pcm[pos:pos+CH]
    at = pos / float(sr)
    if seg_start is None and getattr(vad, "in_speech", False):
        seg_start = at
    seg = vad.push(chunk)
    pos += CH
    if seg is None:
        continue
    st = seg_start if seg_start is not None else max(0.0, at - len(seg)/float(sr))
    seg_start = None
    t1 = time.monotonic()
    try:
        res = stt.transcribe_segment(seg) or []
    except Exception as e:
        res = []
        print("движок споткнулся:", repr(e)[:120])
    ms = (time.monotonic() - t1) * 1000
    txt = (res[0].get("text") if res else "") or ""
    rows.append({"t": round(st, 2), "dur": round(len(seg)/float(sr), 2),
                 "ms": round(ms), "engine": (res[0].get("engine") if res else ""),
                 "cut": getattr(vad, "last_cut", ""), "text": txt})
    if len(rows) % 10 == 0:
        print("  ...%d реплик, дошли до %.0f с" % (len(rows), st))

for r in (stt.flush() or []):
    if r.get("text"):
        rows.append({"t": round(len(pcm)/float(sr), 2), "dur": 0, "ms": 0,
                     "engine": r.get("engine", ""), "cut": "flush",
                     "text": r["text"]})

took = time.monotonic() - t0
io.open(OUT, "w", encoding="utf-8").write(
    "\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
print("реплик: %d  за %.0f с на %.0f с звука (%.2fx реального времени)"
      % (len(rows), took, len(pcm)/sr, took / (len(pcm)/sr)))
print("записано:", OUT)
