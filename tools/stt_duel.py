# -*- coding: utf-8 -*-
"""Очная ставка движков на одном и том же куске (06.09.2026).

Владелец: «в приложении транскрибация офигенная, даже на улице — сделай
такую же, выпили всё и найди такие же технологии».

Прежде чем что-то выпиливать, надо ЗАМЕРИТЬ. Гоняем один и тот же кусок
ролика через оба движка, что стоят в проекте, по одной и той же нарезке,
и сверяем с ютуб-транскрибом. Решение принимаем по цифрам: точность и
скорость, а не по ощущению.

Печатаем, ЧЕМ мерили — этот урок уже стоил нам одного неверного вывода."""
import io, json, os, sys, time, wave
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); os.chdir(str(ROOT))
import numpy as np
from anamorf.config import CFG
from anamorf.stt.manager import VadSegmenter, STTManager

WAV = ROOT / "data" / "bench_1000_1300.wav"
with wave.open(str(WAV), "rb") as w:
    sr = w.getframerate(); pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)

# одна нарезка на всех — иначе сравниваем не движки, а нарезки
vad = VadSegmenter(); segs=[]; pos=0; CH=int(sr*0.032); start=None
while pos < len(pcm):
    at = pos/float(sr)
    if start is None and getattr(vad,"in_speech",False): start = at
    sg = vad.push(pcm[pos:pos+CH]); pos += CH
    if sg is not None: segs.append((start if start is not None else at, sg)); start=None
print("кусков: %d, длины: медиана %.1fс, макс %.1fс"
      % (len(segs), sorted(len(s)/sr for _,s in segs)[len(segs)//2],
         max(len(s)/sr for _,s in segs)))

for eng in ("gigaam", "faster_whisper"):
    CFG.set("stt.engine", eng)
    m = STTManager(); m.src_hint = "sys"; m.queue_hint = 0
    try:
        m.load_engine(eng)
    except Exception as e:
        print(eng, "не поднялся:", repr(e)[:140]); continue
    rows=[]; t0=time.monotonic()
    for t, sg in segs:
        try:
            r = m.transcribe_segment(sg) or []
        except Exception as e:
            r = []
        rows.append({"t": round(t,2), "text": (r[0].get("text") if r else "") or "",
                     "engine": (r[0].get("engine") if r else "")})
    took = time.monotonic()-t0
    out = ROOT/"data"/("duel_%s.jsonl" % eng)
    io.open(out,"w",encoding="utf-8").write(
        "\n".join(json.dumps(x,ensure_ascii=False) for x in rows))
    words = sum(len(x["text"].split()) for x in rows)
    print("%-16s слов %4d · за %5.1fс на 180с звука (%.2fx) · записано %s"
          % (eng, words, took, took/180.0, out.name))
