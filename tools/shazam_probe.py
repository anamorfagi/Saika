import asyncio, json, sys, time, wave, io
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
idx = [json.loads(l) for l in open(ROOT / "data" / "hear_bench" / "index.jsonl", encoding="utf-8") if l.strip()]
lo, hi = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("01:37:42", "01:38:06")
sel = [r for r in idx if lo <= r["at"] <= hi]
print("клипов", len(sel), [r["at"] for r in sel][:3])
parts = []
for r in sel:
    with wave.open(str(ROOT / "data" / "hear_bench" / r["wav"]), "rb") as w:
        sr = w.getframerate(); parts.append(np.frombuffer(w.readframes(w.getnframes()), np.int16))
a = np.concatenate(parts); print("секунд", len(a) / sr, "sr", sr)
buf = io.BytesIO()
with wave.open(buf, "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(a.tobytes())
from shazamio import Shazam
async def main():
    sh = Shazam()
    t0 = time.time()
    out = await sh.recognize(buf.getvalue())
    print("shazam %.1fs" % (time.time() - t0))
    tr = out.get("track") or {}
    print("title:", tr.get("title"), "| artist:", tr.get("subtitle"))
    m = (out.get("matches") or [{}])[0]
    print("offset", m.get("offset"), "matches", len(out.get("matches") or []))
    print(json.dumps({k: out[k] for k in out if k not in ("track",)}, ensure_ascii=False)[:400])
asyncio.run(main())
