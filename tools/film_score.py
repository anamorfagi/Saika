# Оценка движков без эталона: слова, которые слышат ДВА других независимых
# движка, — «точно сказанные»; доля таких слов у движка = полнота; слова,
# которых нет ни у кого другого, — «отсебятина».
import json, re, sys, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
L = [json.loads(l) for l in open(ROOT / "data" / "film_bench.jsonl", encoding="utf-8") if l.strip()]
def norm(t):
    t = (t or "").lower().replace("ё", "е")
    t = re.sub(r"([а-яa-z])\1{2,}", r"\1", t)
    return [w for w in re.findall(r"[а-яa-z0-9$]+", t) if len(w) > 1]
ENG = ["giga", "wt", "wt_raw", "wt_ctx", "pk"]
IND = {"giga": ["wt", "pk"], "wt": ["giga", "pk"], "wt_raw": ["giga", "pk"], "wt_ctx": ["giga", "pk"], "pk": ["giga", "wt"]}
stat = {e: collections.Counter() for e in ENG}
for r in L:
    W = {e: norm(r.get(e)) for e in ENG}
    S = {e: set(W[e]) for e in ENG}
    for e in ENG:
        others = IND[e]
        sure = S[others[0]] & S[others[1]]
        anyother = set().union(*[S[o] for o in ENG if o != e and not (o.startswith("wt") and e.startswith("wt"))])
        stat[e]["sure"] += len(sure)
        stat[e]["hit"] += len(sure & S[e])
        stat[e]["words"] += len(W[e])
        stat[e]["alone"] += sum(1 for w in W[e] if w not in anyother)
        stat[e]["empty"] += int(not W[e])
print("клипов", len(L))
print("%-8s %6s %7s %7s %6s" % ("движок", "слов", "полнота", "отсебя", "пусто"))
for e in ENG:
    s = stat[e]
    print("%-8s %6d %6.1f%% %6.1f%% %5d" % (e, s["words"], 100 * s["hit"] / max(1, s["sure"]), 100 * s["alone"] / max(1, s["words"]), s["empty"]))
# парное согласие (difflib по словам)
import difflib
pairs = [("giga", "wt"), ("giga", "pk"), ("wt", "pk"), ("wt", "wt_ctx"), ("wt", "wt_raw")]
for a, b in pairs:
    rs = [difflib.SequenceMatcher(None, norm(r.get(a)), norm(r.get(b))).ratio() for r in L if norm(r.get(a)) and norm(r.get(b))]
    print("согласие %s~%s: %.2f (n=%d)" % (a, b, sum(rs) / max(1, len(rs)), len(rs)))
