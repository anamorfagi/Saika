import json, wave, numpy as np
from pathlib import Path
from anamorf.stt import second
rows=[json.loads(l) for l in open(r"C:\AI\Saika\data\hear_bench\index.jsonl",encoding="utf-8") if l.strip()][-12:]
for r in rows:
    p=Path(r"C:\AI\Saika\data\hear_bench")/r["wav"]
    if not p.exists(): continue
    with wave.open(str(p),"rb") as w: A=np.frombuffer(w.readframes(w.getnframes()),np.int16)
    res=second.listen(stt, A, 16000, r.get("text") or "")
    print(r["at"], r.get("sec"), repr(r.get("text"))[:45], "->", res, [(w,p_) for w,p_ in (second.STATE.get("wprob") or [])][:12])
