# -*- coding: utf-8 -*-
"""ДВЕ ЖЕНЩИНЫ КРИЧАТ РАЗОМ — РАЗВОДИМ ПО ТОНУ И ЧИТАЕМ ПОРОЗНЬ.

Владелец: «там два человека, две девушки одновременно друг на друга
кричат, у них разный тон и свои слова; сделай так, чтобы система
справилась». И добавил важное: в расшифровке с ютуба там тоже не всё —
то есть эталон в этом месте занижен, и превзойти его не стыдно.

Идея не в разделении источников (оно дорогое, мерили — 5.6× реального
времени). Идея в МАРШРУТИЗАЦИИ: кадр в 30 мс почти всегда принадлежит
одному голосу, даже когда люди перебивают друг друга. Считаем тон
каждого кадра, делим кадры на две группы по высоте и собираем два
звуковых трека: свои кадры как есть, чужие — тишиной. Тайминг цел,
каждый трек читается движком отдельно.

Сравниваем три способа на одном звуке:
    смесь как есть            — что сейчас;
    две дорожки по тону       — предлагаемое;
    объединение их текстов    — сколько всего слов удалось вытащить.
"""
import io, json, re, sys, time, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np

WAV = ROOT / "data" / "first30.wav"
REF = ROOT / "slux_test" / "snailkik_dnk" / "transkrib.txt"

with wave.open(str(WAV), "rb") as w:
    SR = w.getframerate()
    A = np.frombuffer(w.readframes(w.getnframes()), np.int16)

from anamorf.stt.stream_tone import _f0_and_tilt, _WIN
from anamorf.stt.manager import STTManager

_H = re.compile(r'^(?:(\d+):)?(\d{1,2}):(\d{2})'); _S = re.compile(r'секунд[а-я]*')
_W = re.compile(r'[^\w\s]+', re.UNICODE)
wrds = lambda t: [x for x in _W.sub(' ', (t or '').lower()).replace('ё','е').split() if x]

ref = []
for ln in io.open(REF, encoding='utf-8', errors='replace'):
    m = _H.match(ln)
    if not m: continue
    t = int(m.group(1) or 0)*3600 + int(m.group(2))*60 + int(m.group(3))
    if t > 35: break
    k = _S.search(ln)
    if k: ref += wrds(ln[k.end():])

def score(texts, name, sec):
    from collections import Counter
    got = wrds(" ".join(texts))
    cb = Counter(got); hit = 0
    for w in ref:
        if cb[w] > 0: cb[w] -= 1; hit += 1
    cg = Counter(ref); extra = 0
    for w in got:
        if cg[w] > 0: cg[w] -= 1
        else: extra += 1
    print("%-30s слов %3d | найдено %5.1f%% | лишнего %5.1f%% | %.1f с"
          % (name, len(got), 100.0*hit/max(1,len(ref)), 100.0*extra/max(1,len(got)), sec))
    return {"name": name, "words": len(got), "found": hit/max(1,len(ref)),
            "extra": extra/max(1,len(got)), "text": " ".join(texts)[:500]}

# ── тон по кадрам и раздел на две группы ──────────────────────────────
nf = len(A) // _WIN
f0 = np.zeros(nf); 
for i in range(nf):
    v, _t, _r, _d = _f0_and_tilt(A[i*_WIN:(i+1)*_WIN])
    f0[i] = v
voiced = f0 > 0
print("кадров всего %d, с высотой %d (%.0f%%)" % (nf, voiced.sum(), 100.0*voiced.sum()/max(1,nf)))
st = np.zeros(nf); st[voiced] = 12*np.log2(f0[voiced]/110.0)
# ДВЕ ГРУППЫ ПО ВЫСОТЕ: простое k-средних на полутонах, два центра.
# Полутона, а не герцы: разница «на слух» одинакова у низкого и высокого.
v = st[voiced]
if len(v) > 8:
    lo, hi = np.percentile(v, 20), np.percentile(v, 80)
    for _ in range(25):
        d1, d2 = np.abs(v-lo), np.abs(v-hi)
        g1, g2 = v[d1 <= d2], v[d1 > d2]
        if len(g1): lo = g1.mean()
        if len(g2): hi = g2.mean()
    print("центры групп: %.0f Гц и %.0f Гц (разница %.1f полутона)"
          % (110*2**(lo/12), 110*2**(hi/12), abs(hi-lo)))
    lab = np.zeros(nf, np.int8); lab[voiced] = np.where(np.abs(v-lo) <= np.abs(v-hi), 1, 2)
else:
    lab = np.zeros(nf, np.int8); lo = hi = 0

def track(which):
    b = np.zeros_like(A)
    for i in range(nf):
        if lab[i] == which:
            b[i*_WIN:(i+1)*_WIN] = A[i*_WIN:(i+1)*_WIN]
    return b

stt = STTManager()
def read(a, win=3.0, hop=2.0):
    n, h = int(win*SR), int(hop*SR); out = []
    for i in range(0, len(a), h):
        c = a[i:i+n]
        if len(c) < SR//2: break
        if float(np.abs(c).max()) < 200: continue
        try:
            r = stt.transcribe_segment(c) or []
            if r: out.append(r[0].get("text") or "")
        except Exception: pass
    return out

res = []
t0 = time.monotonic(); mix = read(A); res.append(score(mix, "смесь как есть", time.monotonic()-t0))
t0 = time.monotonic(); t1 = read(track(1)); s1 = time.monotonic()-t0
t0 = time.monotonic(); t2 = read(track(2)); s2 = time.monotonic()-t0
res.append(score(t1, "дорожка 1 (ниже по тону)", s1))
res.append(score(t2, "дорожка 2 (выше по тону)", s2))
res.append(score(t1+t2, "две дорожки вместе", s1+s2))
io.open(ROOT/"data"/"split30.json","w",encoding="utf-8").write(json.dumps(res,ensure_ascii=False,indent=1))
print("\nдорожка 1:", " ".join(t1)[:200])
print("дорожка 2:", " ".join(t2)[:200])
