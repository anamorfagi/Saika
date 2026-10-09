# -*- coding: utf-8 -*-
"""Что именно умеет T-one: полный разбор его API (06.09.2026).

Владелец: «нужно чтобы движок буквы писать начал буквально из звуков
микрофона в реальном времени». Модель потоковая, но отдаёт ли она
НЕЗАКОНЧЕННУЮ гипотезу (то, что сейчас произносится) или только готовые
фразы — это надо прочитать в коде, а не гадать."""
import io, inspect, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
O=[]
def say(*a):
    s=" ".join(str(x) for x in a); print(s); O.append(s)
    io.open(ROOT/"data"/"tone_api.txt","w",encoding="utf-8").write("\n".join(O))
import tone
say("tone:", Path(tone.__file__).parent)
say("экспорт:", [n for n in dir(tone) if not n.startswith("_")])
from tone import StreamingCTCPipeline as P
say("\nStreamingCTCPipeline:")
for n in dir(P):
    if n.startswith("_") and n != "__init__": continue
    v = getattr(P, n)
    if callable(v):
        try: say("   %s%s" % (n, inspect.signature(v)))
        except Exception: say("   %s(...)" % n)
    else: say("   %s = %r" % (n, v))
say("\n--- исходник pipeline.py ---")
src = (Path(tone.__file__).parent / "pipeline.py").read_text(encoding="utf-8")
say(src[:6000])
