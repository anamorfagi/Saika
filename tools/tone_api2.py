# -*- coding: utf-8 -*-
import io, inspect
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
O=[]
def say(*a):
    s=" ".join(str(x) for x in a); print(s); O.append(s)
    io.open(ROOT/"data"/"tone_api2.txt","w",encoding="utf-8").write("\n".join(O))
import tone
from tone import GreedyCTCDecoder, StreamingCTCModel, StreamingLogprobSplitter, StreamingCTCPipeline
for cls in (StreamingCTCModel, StreamingLogprobSplitter, GreedyCTCDecoder):
    say("== %s ==" % cls.__name__)
    for n in dir(cls):
        if n.startswith("_") and n != "__init__": continue
        v = getattr(cls, n)
        if callable(v):
            try: say("   %s%s" % (n, inspect.signature(v)))
            except Exception: say("   %s(...)" % n)
        else: say("   %s = %r" % (n, str(v)[:80]))
    say("")
d = Path(tone.__file__).parent
say("--- pipeline.forward ---")
src = (d/"pipeline.py").read_text(encoding="utf-8")
i = src.index("def forward(")
say(src[i-200:i+2200])
