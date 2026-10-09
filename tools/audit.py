# Самопроверка ленты по журналу (последние N реплик): повторы на стыках,
# повторы внутри фразы, доля «ухо/срок», распределение косинуса Зубарева,
# части разреза, песни. Запуск: python3 tools/audit.py [N]
import json, re, sys, difflib, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 300
L = [json.loads(l) for l in open(ROOT / "data" / "events.jsonl", encoding="utf-8").read().splitlines()[-N * 3:] if l.strip()]
S = [e for e in L if e.get("type") == "stt" and e.get("text")][-N:]
def norm(t): return re.findall(r"[а-яёa-z0-9]+", (t or "").lower().replace("ё", "е"))
inner = cross = 0; ex_cross = []; ex_inner = []
for i, e in enumerate(S):
    w = norm(e["text"])
    tri = [tuple(w[j:j + 3]) for j in range(len(w) - 2)]
    if len(tri) != len(set(tri)):
        inner += 1; ex_inner.append((e["pid"], e["text"][:70]))
    if i:
        pw = norm(S[i - 1]["text"])
        for k in range(min(4, len(pw), len(w)), 1, -1):
            if difflib.SequenceMatcher(None, " ".join(pw[-k:]), " ".join(w[:k])).ratio() >= 0.75:
                cross += 1; ex_cross.append((S[i - 1]["pid"], e["pid"], S[i - 1]["text"][-30:], e["text"][:30])); break
fl = collections.Counter(e.get("_flush") for e in S)
fixed = sum(1 for e in S if e.get("fixed_by"))
zs = [e.get("speaker_sim") for e in S if e.get("speaker") == "зубарев" and e.get("speaker_sim") is not None]
os_ = [e.get("speaker_sim") for e in S if e.get("speaker") != "зубарев" and e.get("speaker_sim") is not None]
def med(v): v = sorted(v); return v[len(v) // 2] if v else None
parts = sum(1 for e in S if e.get("part"))
songs = sum(1 for e in S if e.get("song"))
trimmed = sum(1 for e in S if e.get("trimmed"))
print("реплик %d | стыки-повторы %d (%.1f%%) | повторы внутри %d | срезано стыков %d" % (len(S), cross, 100 * cross / max(1, len(S)), inner, trimmed))
print("выпуск: %s | сведено вторым ухом %d (%.0f%%)" % (dict(fl), fixed, 100 * fixed / max(1, len(S))))
print("зубарев: %d реплик, медиана cos %s, мин %s | чужие: %d, медиана %s, макс %s, выше 0.40: %d" % (
    len(zs), med(zs), min(zs) if zs else None, len(os_), med(os_), max(os_) if os_ else None, sum(1 for x in os_ if x >= 0.40)))
print("частей разреза %d | песен %d" % (parts, songs))
for x in ex_cross[-5:]: print("  стык", x)
for x in ex_inner[-3:]: print("  внутри", x)
