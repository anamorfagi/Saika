# -*- coding: utf-8 -*-
"""Сколько РАЗНЫХ людей в куске — замер, а не догадка.

Владелец: «ты транскриб с ютуба из файла можешь сам определиться,
сколько примерно спикеров говорит». По тексту — нет: ютубовский
транскриб без разметки, там нет ни имён, ни реплик. А вот по ЗВУКУ
можно: тот же кодировщик тембра, что в живом слухе, и та же
кластеризация. Заодно это честная проверка поднятой планки —
подтверждается ли на трёх минутах ровно столько людей, сколько их
слышно ухом.

Считаем ДВАЖДЫ: со старыми порогами и с новыми. Разница и есть ответ
на «ебать он голосов тут нахуячил»."""
import io, json, os, sys, wave
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); os.chdir(str(ROOT))
import numpy as np
from anamorf.config import CFG
from anamorf.stt.manager import VadSegmenter
from anamorf.voiceprint.tracks import Tracks
from anamorf import voiceprint as vp

WAV = ROOT / "data" / "bench_1000_1300.wav"
with wave.open(str(WAV), "rb") as w:
    sr = w.getframerate()
    pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)

vad = VadSegmenter()
segs, pos, CH = [], 0, int(sr*0.032)
start = None
while pos < len(pcm):
    at = pos/float(sr)
    if start is None and getattr(vad, "in_speech", False): start = at
    s = vad.push(pcm[pos:pos+CH]); pos += CH
    if s is not None:
        segs.append((start if start is not None else at, s)); start = None
print("кусков речи: %d, суммарно %.0f с" % (len(segs), sum(len(s)/sr for _,s in segs)))

vecs = []
bad = 0
for t, sg in segs:
    try:
        v, _f0 = vp.S.enc.encode(sg)     # тот же кодировщик, что в живом слухе
    except Exception as e:
        bad += 1
        if bad == 1: print("кодировщик споткнулся:", repr(e)[:160])
        v = None
    if v is not None:
        vecs.append((t, len(sg)/float(sr), np.asarray(v, np.float32).ravel()))
print("отпечатков снято: %d" % len(vecs))

def run(tag, **knobs):
    for k, val in knobs.items(): CFG.set("voiceprint.tracks." + k, val)
    tr = Tracks(to_registry=False, tag="")
    for t, sec, v in vecs:
        tr.observe(v, sec, ts=t)
    named = [c for c in tr.clusters if c.name]
    print("\n%s" % tag)
    print("  кластеров всего: %d, объявлено людьми: %d" % (len(tr.clusters), len(named)))
    for c in sorted(tr.clusters, key=lambda x: -x.sec)[:12]:
        print("    #%-3d %5.1f с речи · %2d реплик · %d заход(ов) %s"
              % (c.id, c.sec, c.n, getattr(c, "visits", 1),
                 "-> " + c.name if c.name else ""))

run("СТАРЫЕ пороги (было): 3 с речи, 2 реплики, заходы не считались",
    confirm_s=3.0, confirm_n=2, confirm_visits=1, visit_gap_s=20.0)
run("НОВЫЕ пороги (стало): 6 с речи, 3 реплики, 2 разных захода",
    confirm_s=6.0, confirm_n=3, confirm_visits=2, visit_gap_s=20.0)
