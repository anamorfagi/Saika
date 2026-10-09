# -*- coding: utf-8 -*-
"""Запустить ролик для экзамена слуха (05.09.2026). Путь известен точно —
никаких «похожих файлов»."""
import io, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
O = []
def say(*a): O.append(" ".join(str(x) for x in a))
WAV = ROOT / "data" / "snailkick.wav"
MP4 = (ROOT / "slux_test" / "snailkik_dnk" /
       "ДЯДЯ ОТЦА МАТЕРИ СЫНА _ СМОТРИМ ДНК.mp4")
target = WAV if WAV.exists() else MP4
try:
    os.startfile(str(target))
    say("играю: %s" % target)
except Exception as e:
    say("не запустилось: %r" % e)
io.open(ROOT / "data" / "play_video.txt", "w", encoding="utf-8").write("\n".join(O))
