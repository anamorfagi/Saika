# -*- coding: utf-8 -*-
"""ПОЧЕМУ ПЕРВЫЕ 30 СЕКУНД ПРОВАЛЕНЫ — опыт, а не рассуждение (06.09.2026).

Владелец: «первый кусок 20 секунд, там мясо, ни одного диалога система не
определила». Замер это подтвердил: найдено 8.9% слов эталона.

Куски при этом были нормальной длины (5-6 с звука), а слов из них выходило
3-8. Значит теряет не нарезка, а разбор. Проверяем ЧЕМ ИМЕННО, прогоняя
один и тот же звук четырьмя способами и сверяя каждый с эталоном:

  1. целиком 30 с        — как услышал бы движок без нарезки;
  2. окнами по 6 с       — как режет сейчас;
  3. окнами по 3 с       — мельче: помогает ли короткое окно на ору;
  4. окнами по 3 с с перекрытием 1 с — не теряются ли слова на швах.

Победитель показывает, куда двигаться, и цифру, от которой считать.
"""
import io, json, re, subprocess, sys, time, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
VID = ROOT / "slux_test" / "snailkik_dnk" / "ДЯДЯ ОТЦА МАТЕРИ СЫНА _ СМОТРИМ ДНК.mp4"
WAV = ROOT / "data" / "first30.wav"
REF = ROOT / "slux_test" / "snailkik_dnk" / "transkrib.txt"
DUR = 30

import numpy as np

def ffmpeg():
    for c in ("ffmpeg", str(ROOT / "bin" / "ffmpeg.exe")):
        try:
            subprocess.run([c, "-version"], capture_output=True, timeout=10)
            return c
        except Exception:
            continue
    return None

if not WAV.exists():
    fe = ffmpeg()
    if not fe:
        print("нет ffmpeg — не из чего доставать звук"); sys.exit(1)
    subprocess.run([fe, "-y", "-ss", "0", "-t", str(DUR), "-i", str(VID),
                    "-ac", "1", "-ar", "16000", str(WAV)],
                   capture_output=True, timeout=180)
if not WAV.exists():
    print("не удалось достать звук"); sys.exit(1)

with wave.open(str(WAV), "rb") as w:
    SR = w.getframerate()
    A = np.frombuffer(w.readframes(w.getnframes()), np.int16)
print("звук:", len(A) / SR, "с,", SR, "Гц")

_H = re.compile(r'^(?:(\d+):)?(\d{1,2}):(\d{2})'); _S = re.compile(r'секунд[а-я]*')
_W = re.compile(r'[^\w\s]+', re.UNICODE)
wrds = lambda t: [x for x in _W.sub(' ', (t or '').lower()).replace('ё','е').split() if x]

ref = []
for ln in io.open(REF, encoding='utf-8', errors='replace'):
    m = _H.match(ln)
    if not m: continue
    t = int(m.group(1) or 0)*3600 + int(m.group(2))*60 + int(m.group(3))
    if t > DUR + 5: break
    k = _S.search(ln)
    if k: ref += wrds(ln[k.end():])
print("слов в эталоне за", DUR, "с:", len(ref))

from anamorf.stt.manager import STTManager
stt = STTManager()

def run(chunks, name):
    t0 = time.monotonic(); out = []
    for c in chunks:
        try:
            r = stt.transcribe_segment(c) or []
            if r: out.append(r[0].get("text") or "")
        except Exception as e:
            out.append("")
    got = wrds(" ".join(out))
    from collections import Counter
    cb = Counter(got); hit = 0
    for w in ref:
        if cb[w] > 0: cb[w] -= 1; hit += 1
    cg = Counter(ref); extra = 0
    for w in got:
        if cg[w] > 0: cg[w] -= 1
        else: extra += 1
    sec = time.monotonic() - t0
    print("%-26s слов %3d | найдено %5.1f%% | лишнего %5.1f%% | %.1f с"
          % (name, len(got), 100.0*hit/max(1,len(ref)), 100.0*extra/max(1,len(got)), sec))
    return {"name": name, "words": len(got), "found": hit/max(1,len(ref)),
            "extra": extra/max(1,len(got)), "sec": round(sec,1),
            "text": " ".join(out)[:400]}

def win(n, hop=None):
    n = int(n*SR); hop = int((hop or 0)*SR) or n
    return [A[i:i+n] for i in range(0, len(A), hop) if len(A[i:i+n]) > SR//2]

res = [run([A], "целиком 30 с"),
       run(win(6), "окнами по 6 с"),
       run(win(3), "окнами по 3 с"),
       run(win(3, 2), "по 3 с с перекрытием 1 с")]
io.open(ROOT/"data"/"first30.json","w",encoding="utf-8").write(
    json.dumps(res, ensure_ascii=False, indent=1))
best = max(res, key=lambda r: r["found"])
print("\nЛУЧШИЙ:", best["name"], "— найдено %.1f%%" % (100*best["found"]))
print("его текст:", best["text"][:300])
