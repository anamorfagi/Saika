# -*- coding: utf-8 -*-
"""Прогнать отрезок ролика ЧЕРЕЗ ВСТРОЕННЫЙ ПЛЕЕР (владелец видит и слышит).
Отрезок — в data/run_seg.txt: «старт_сек длина_сек». Печатает счёт."""
import json, time, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
try:
    st, ln = ROOT.joinpath("data", "run_seg.txt").read_text().split()[:2]
    st, ln = float(st), float(ln)
except Exception:
    st, ln = 22 * 60, 60
def post(p, b):
    r = urllib.request.Request("http://127.0.0.1:8765" + p, data=json.dumps(b).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=20))
def get(p):
    return json.load(urllib.request.urlopen("http://127.0.0.1:8765" + p, timeout=20))
post("/api/chat/clear", {})
print(post("/api/media/cmd", {"op": "play", "pos": st, "len": ln}))
t0 = time.time()
time.sleep(ln + 9)
d = get("/api/polygon")
sc = d.get("score") or d.get("live")
if not sc:
    print("счёта нет:", {k: d[k] for k in ("on", "start", "len", "err")}); raise SystemExit
print("ОТРЕЗОК %d+%d с: найдено %s%% (%s из %s), лишних %s, реплик %s, движок %s мс" % (st, ln, sc["pct"], sc["found"], sc["ref"], sc["extra"], sc["phrases"], sc["lag_ms"]))
for b in sc["bins"]:
    if b["ref"] or b["extra"]:
        print("  %4d с  %2d/%-2d %s%s" % (b["t"], b["hit"], b["ref"], ("  потеряно: " + b["lost"]) if b["lost"] else "", ("  лишнее: " + b["extra"]) if b["extra"] else ""))
