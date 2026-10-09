# Сравнение стратегий сведения двух ушей (GigaAM + whisper) по стенду фильма.
# Судья — parakeet (независим от обоих): согласие difflib по словам.
import json, re, sys, difflib, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
B = [json.loads(l) for l in open(ROOT / "data" / "film_bench.jsonl", encoding="utf-8") if l.strip()]
E = [json.loads(l) for l in open(ROOT / "data" / "events.jsonl", encoding="utf-8") if l.strip()]
def norm(t):
    t = (t or "").lower().replace("ё", "е")
    t = re.sub(r"([а-яa-z])\1{2,}", r"\1", t)
    return [w for w in re.findall(r"[а-яa-z0-9$]+", t) if len(w) > 1]
def key(w): return re.sub(r"[^а-яёa-z]", "", w.lower())
# уверенность слов GigaAM — из журнала (words[].p), по совпадению текста
gconf = {}
for e in E:
    if e.get("type") == "stt" and e.get("words"):
        gconf[(e.get("heard_raw") or e.get("text") or "").strip()] = {key(w["w"]): w.get("p") for w in e["words"] if w.get("p") is not None}
        gconf[(e.get("text") or "").strip()] = gconf[(e.get("heard_raw") or e.get("text") or "").strip()]

def rover(base, other, wprob, bconf, take_p=0.7, mode="conf", margin=0.05):
    bt, ot = base.split(), other.split()
    probs = {}
    for w, p in (wprob or []):
        k = key(w)
        if k: probs[k] = max(p, probs.get(k, 0.0))
    def wp(w):
        ps = [probs.get(x, 0.0) for x in re.findall(r"[а-яёa-z]+", w.lower())]
        return sum(ps) / len(ps) if ps else 0.0
    def bp(w):
        v = bconf.get(key(w)); return 0.5 if v is None else v
    if not ot: return base
    if not bt: return other if (sum(wp(w) for w in ot) / len(ot)) >= 0.6 else base
    sm = difflib.SequenceMatcher(a=[key(w) for w in bt], b=[key(w) for w in ot], autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal": out.extend(bt[i1:i2])
        elif tag == "insert":
            ins = ot[j1:j2]
            if mode == "conf": ins = [w for w in ins if wp(w) >= take_p]
            out.extend(ins)
        elif tag == "delete":
            mine = bt[i1:i2]
            if mode == "conf": mine = [w for w in mine if bp(w) >= 0.5]
            out.extend(mine)
        else:
            mine, theirs = bt[i1:i2], ot[j1:j2]
            mp = sum(bp(w) for w in mine) / len(mine); tp = sum(wp(w) for w in theirs) / len(theirs)
            out.extend(theirs if tp > mp + margin else mine)
    return " ".join(out)

strat = collections.defaultdict(list)
n = 0
for r in B:
    pk = norm(r.get("pk"))
    if not pk or r.get("pk_err"): continue
    g, w = r.get("giga") or "", r.get("wt") or ""
    if not norm(g) and not norm(w): continue
    n += 1
    bc = gconf.get(g.strip(), {})
    wp = r.get("wt_w") or []
    avg = (sum(p for _w, p in wp) / len(wp)) if wp else 0.0
    cands = {
        "giga": g, "whisper": w,
        "take≥0.7": w if (avg >= 0.7 and norm(w)) else g,
        "take≥0.8": w if (avg >= 0.8 and norm(w)) else g,
        "rover-conf": rover(g, w, wp, bc, 0.7, "conf"),
        "rover-all": rover(g, w, wp, bc, 0.7, "all"),
        "rover-m0": rover(g, w, wp, bc, 0.7, "conf", 0.0),
        "rover-m-10": rover(g, w, wp, bc, 0.7, "conf", -0.10),
        "rover-m-20": rover(g, w, wp, bc, 0.7, "conf", -0.20),
    }
    for k, t in cands.items():
        strat[k].append(difflib.SequenceMatcher(None, norm(t), pk).ratio())
print("кусков с судьёй (parakeet):", n, "| с уверенностью GigaAM:", sum(1 for r in B if gconf.get((r.get('giga') or '').strip())))
for k, v in strat.items():
    print("%-11s согласие с parakeet %.3f" % (k, sum(v) / len(v)))
