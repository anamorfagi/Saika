# -*- coding: utf-8 -*-
"""ЧТО РЕАЛЬНО ДОШЛО ДО ЛЕНТЫ — против эталона ютуба (22:00–25:00).
Берём реплики из data/hear_bench/index.jsonl за время реплея snailkick.wav,
кладём каждую на секунду ролика (ts − начало реплея − движок − длительность)
и считаем по 10-с бинам, как tools/bench3.py. Это цифра «что видит Виталя»,
а bench3 — «что умеет движок». Разница между ними — потери в конвейере."""
import json, re, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
OFF = 22*60; DUR = 180
def norm(t): return [x for x in re.findall(r"[а-яё]+", t.lower()) if len(x) > 1]
ref = {}
for ln in open(ROOT/"slux_test"/"snailkik_dnk"/"transkrib.txt", encoding="utf-8"):
    m = re.match(r"(\d+):(\d\d)", ln)
    if not m: continue
    t = int(m.group(1))*60 + int(m.group(2)) - OFF
    if 0 <= t < DUR:
        ref.setdefault(int(t//10), []).extend(norm(re.sub(r"^\S+\s*(минут\w*\s*\d*\s*)?секунд\w*", "", ln)))
start = float(open(ROOT/"data"/"replay_start.txt").read().strip())
rows = []
for ln in open(ROOT/"data"/"hear_bench"/"index.jsonl", encoding="utf-8"):
    try: r = json.loads(ln)
    except Exception: continue
    if start <= r["ts"] <= start + DUR + 15:
        end = r["ts"] - start - r.get("ms", 0)/1000.0
        rows.append((end - r.get("sec", 0), end, r.get("text", ""), r.get("ms", 0), r.get("sec", 0)))
got = {}; lat = []
for a, b, txt, ms, sec in rows:
    got.setdefault(int(max(a, 0)//10), set()).update(norm(txt)); lat.append(ms)
hit = miss = extra = 0; per = []
for bb in sorted(set(ref) | set(got)):
    r = ref.get(bb, []); g = got.get(bb, set()); gg = g | got.get(bb-1, set()) | got.get(bb+1, set())
    h = sum(1 for w in r if w in gg); hit += h; miss += len(r) - h
    rr = set(r) | set(ref.get(bb-1, [])) | set(ref.get(bb+1, [])); extra += sum(1 for w in g if w not in rr)
    per.append((bb, h, len(r)))
print("реплик в ленте: %d, звука в них %.0fс из %dс; движок медиана %d мс, макс %d мс" % (len(rows), sum(r[4] for r in rows), DUR, sorted(lat)[len(lat)//2] if lat else -1, max(lat) if lat else -1))
print("ЛЕНТА: найдено %d/%d = %.1f%%, лишних %d" % (hit, hit+miss, 100*hit/max(1, hit+miss), extra))
print("по 10-с отрезкам: " + "  ".join("%d:%d/%d" % (b*10, h, n) for b, h, n in per if n))
for a, b, txt, ms, sec in rows[:200]:
    print("  %6.1f-%6.1f  %4dмс  %s" % (a, b, ms, txt[:110]))
