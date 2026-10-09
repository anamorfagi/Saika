# -*- coding: utf-8 -*-
import io
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
O=[]
def say(*a):
    s=" ".join(str(x) for x in a); print(s); O.append(s)
    io.open(ROOT/"data"/"tone_api3.txt","w",encoding="utf-8").write("\n".join(O))
import tone
d = Path(tone.__file__).parent
say("--- decoder.py ---")
say((d/"decoder.py").read_text(encoding="utf-8")[:5000])
