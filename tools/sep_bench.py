# -*- coding: utf-8 -*-
"""РАЗВОД ГОЛОСОВ + CTC ПРОТИВ ЧИСТОГО CTC НА ОРУЩЕМ НАЧАЛЕ РОЛИКА (06.09.2026).
Меряем: долю слов эталона (ютуб, 0–22 с), найденных (а) движком на смеси,
(б) движком на двух дорожках SepFormer, (в) объединением. И цену развода."""
import re, sys, time, wave
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import numpy as np, torch
sys.path.insert(0, str(ROOT/"third_party"/"GigaAM"))
import gigaam
SR = 16000
with wave.open(str(ROOT/"data"/"first30.wav"), "rb") as w:
    assert w.getframerate() == SR; A = np.frombuffer(w.readframes(w.getnframes()), np.int16)
def norm(t): return [x for x in re.findall(r"[а-яё]+", t.lower()) if len(x) > 1]
ref = []
for ln in open(ROOT/"slux_test"/"snailkik_dnk"/"transkrib.txt", encoding="utf-8"):
    m = re.match(r"(\d+):(\d\d)", ln)
    if not m: continue
    t = int(m.group(1))*60 + int(m.group(2))
    if t < 22: ref += norm(re.sub(r"^\S+\s*секунд\w*", "", ln))
ref_set = set(ref); print("эталон 0–22с:", len(ref), "слов,", len(ref_set), "уникальных")
m = gigaam.load_model("v3_e2e_ctc")
def asr(pcm):
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
unmix(A[:SR*3]); asr(A[:SR*3])
WIN, HOP = 3.0, 1.5
found_mix, found_sep, tsep = set(), set(), []
rows = []
t = 0.0
while t + WIN <= 22.0:
    seg = A[int(t*SR):int((t+WIN)*SR)]
    tm = asr(seg); wm = set(norm(tm)) & ref_set; found_mix |= wm
    t0 = time.perf_counter(); tr = unmix(seg); tsep.append(time.perf_counter()-t0)
    ts = [asr(x) for x in tr]; ws = set()
    for x in ts: ws |= set(norm(x)) & ref_set
    found_sep |= ws
    rows.append((t, tm, ts, len(wm), len(ws)))
    t += HOP
for t, tm, ts, a, b in rows:
    print("%4.1fс смесь(%d): %s" % (t, a, tm[:70]))
    for k, x in enumerate(ts): print("       дор%d(%s): %s" % (k+1, "+" if b > a else " ", x[:70]))
print("НАЙДЕНО уникальных слов эталона: смесь %d/%d = %.1f%%, развод %d/%d = %.1f%%, вместе %.1f%%"
      % (len(found_mix), len(ref_set), 100*len(found_mix)/len(ref_set), len(found_sep), len(ref_set), 100*len(found_sep)/len(ref_set), 100*len(found_mix|found_sep)/len(ref_set)))
print("SepFormer на 3с: медиана %.0f мс, макс %.0f мс (GPU)" % (np.median(tsep)*1000, max(tsep)*1000))
print("VRAM sepformer+ctc: %.2f ГБ" % (torch.cuda.memory_allocated()/2**30))
