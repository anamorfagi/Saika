# -*- coding: utf-8 -*-
"""ТРИ МИНУТЫ РОЛИКА (22:00–25:00) ПРОТИВ ЭТАЛОНА ЮТУБА — ПО ВАРИАНТАМ ДВИЖКА.
Для каждого 10-с отрезка: доля слов эталона, найденных в тексте (recall),
и доля лишних слов. Варианты: CTC на смеси, RNNT на смеси, CTC + SepFormer."""
import re, sys, time, wave
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import numpy as np, torch
sys.path.insert(0, str(ROOT/"third_party"/"GigaAM"))
import gigaam
SR = 16000; OFF = 22*60
with wave.open(str(ROOT/"data"/"snailkick.wav"), "rb") as w:
    assert w.getframerate() == SR; A = np.frombuffer(w.readframes(w.getnframes()), np.int16)
DUR = len(A)/SR
def norm(t): return [x for x in re.findall(r"[а-яё]+", t.lower()) if len(x) > 1]
ref = {}   # 10-с бин -> слова
for ln in open(ROOT/"slux_test"/"snailkik_dnk"/"transkrib.txt", encoding="utf-8"):
    m = re.match(r"(\d+):(\d\d)", ln)
    if not m: continue
    t = int(m.group(1))*60 + int(m.group(2)) - OFF
    if 0 <= t < DUR:
        ref.setdefault(int(t//10), []).extend(norm(re.sub(r"^\S+\s*(минут\w*\s*\d*\s*)?секунд\w*", "", ln)))
allref = [w for b in ref.values() for w in b]
print("эталон: %.0f с, %d слов" % (DUR, len(allref)))
models = {}
def asr(name, pcm):
    m = models[name]
    wav = torch.from_numpy(pcm.astype(np.float32)/32768.0).to(m._device).unsqueeze(0)
    ln = torch.full([1], wav.shape[-1], device=m._device)
    with torch.inference_mode():
        enc, el = m.forward(wav, ln); return m._decode(enc, el, ln, False)[0][0]
from speechbrain.inference.separation import SepformerSeparation
sep = SepformerSeparation.from_hparams(source="speechbrain/sepformer-whamr16k", savedir=str(ROOT/"models"/"sepformer"), run_opts={"device": "cuda"})
def unmix(pcm):
    x = pcm.astype(np.float32)/32768.0; pk = float(np.abs(x).max()) or 1.0
    with torch.no_grad(): est = sep.separate_batch(torch.tensor(x/pk)[None, :].cuda())
    est = est[0].cpu().numpy(); outs = []
    for k in range(est.shape[-1]):
        t = est[:, k]; mx = float(np.abs(t).max()) or 1.0
        outs.append(np.clip(t/mx*pk*32768, -32768, 32767).astype(np.int16))
    return outs
WIN, HOP = 3.0, 1.5
def run(variant):
    got = {}; tt = 0.0; t = 0.0
    while t + WIN <= DUR:
        seg = A[int(t*SR):int((t+WIN)*SR)]; t0 = time.perf_counter()
        if variant == "ctc": txt = asr("ctc", seg)
        elif variant == "rnnt": txt = asr("rnnt", seg)
        else:
            txt = asr("ctc", seg) + " " + " ".join(asr("ctc", x) for x in unmix(seg))
        tt += time.perf_counter()-t0
        got.setdefault(int(t//10), set()).update(norm(txt))
        t += HOP
    hit = miss = extra = 0
    per = []
    for b in sorted(set(ref) | set(got)):
        r = ref.get(b, []); g = got.get(b, set())
        # соседние бины тоже считаем — окно 3с может уехать на границу
        gg = g | got.get(b-1, set()) | got.get(b+1, set())
        h = sum(1 for w in r if w in gg); hit += h; miss += len(r)-h
        rr = set(r) | set(ref.get(b-1, [])) | set(ref.get(b+1, []))
        extra += sum(1 for w in g if w not in rr)
        per.append((b, h, len(r)))
    return hit, miss, extra, tt, per
for name, mn in (("ctc", "v3_e2e_ctc"), ("rnnt", "v3_e2e_rnnt")):
    models[name] = gigaam.load_model(mn); asr(name, A[:SR*3])
unmix(A[:SR*3])
res = {}
for v in ("ctc", "rnnt", "ctc+sep"):
    hit, miss, extra, tt, per = run(v); res[v] = per
    print("%-8s найдено %d/%d = %.1f%%  лишних %d  время %.1fс на %.0fс звука (%.2fx)" % (v, hit, hit+miss, 100*hit/(hit+miss), extra, tt, DUR, tt/DUR))
print("по 10-с отрезкам (найдено/эталон): бин  ctc  rnnt  ctc+sep")
for i, (b, h, n) in enumerate(res["ctc"]):
    print("  %3d-%3dс  %2d/%-2d  %2d/%-2d  %2d/%-2d" % (b*10, b*10+10, h, n, res["rnnt"][i][1], n, res["ctc+sep"][i][1], n))
