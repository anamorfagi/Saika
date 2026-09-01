# -*- coding: utf-8 -*-
"""ЧЕСТНАЯ ПРОВЕРКА Smart Turn на наших сегментах (2026-08-31).

Первый тест был кривой: я резал произвольные 6-секундные окна из ролика,
а они почти никогда не заканчиваются на настоящей границе мысли — модель
честно ставила 0.012 и была права. Правильная проверка: брать РЕАЛЬНЫЕ
сегменты нашего VAD (они кончаются там, где человек замолчал) и сравнивать
их с теми же сегментами, обрезанными посреди речи.

Если модель работает, разделение должно быть видно на средних, а не на
отдельных примерах.
"""
import os, sys, json, wave, pathlib, time
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
DST = ROOT / "models" / "smartturn"
MODEL = sys.argv[1] if len(sys.argv) > 1 else "smart-turn-v3.2-cpu.onnx"

from huggingface_hub import hf_hub_download
p = hf_hub_download("pipecat-ai/smart-turn-v3", MODEL, local_dir=str(DST))
print("модель:", MODEL, os.path.getsize(p) // 1024, "КБ")

import onnxruntime as ort, librosa
so = ort.SessionOptions(); so.log_severity_level = 3
sess = ort.InferenceSession(p, so, providers=["CPUExecutionProvider"])
IN = sess.get_inputs()[0].name
print("вход:", [(i.name, i.shape) for i in sess.get_inputs()],
      "выход:", [(o.name, o.shape) for o in sess.get_outputs()])

_MEL = {}
def feats(x, sr=16000, n_mels=80, n_fft=400, hop=160, chunk_s=8):
    need = chunk_s * sr
    x = np.asarray(x, np.float32)
    m, s = float(x.mean()), float(x.std())
    x = (x - m) / (s + 1e-7)
    x = x[-need:] if len(x) >= need else np.pad(x, (0, need - len(x)))
    if n_mels not in _MEL:
        _MEL[n_mels] = librosa.filters.mel(sr=sr, n_fft=n_fft, n_mels=n_mels)
    st = librosa.stft(x, n_fft=n_fft, hop_length=hop, window="hann")
    mag = (np.abs(st[..., :-1]) ** 2).astype(np.float32)
    ls = np.log10(np.maximum(_MEL[n_mels] @ mag, 1e-10))
    ls = np.maximum(ls, ls.max() - 8.0)
    return ((ls + 4.0) / 4.0).astype(np.float32)

def prob(seg, sr=16000):
    o = sess.run(None, {IN: np.expand_dims(feats(seg, sr), 0)})
    v = float(np.ravel(o[0])[0])
    return v if 0.0 <= v <= 1.0 else 1.0 / (1.0 + np.exp(-v))   # логит -> сигмоида

BD = ROOT / "data" / "hear_bench"
rows = [json.loads(l) for l in open(BD / "index.jsonl", encoding="utf-8") if l.strip()]
rows = [r for r in rows if (BD / r["wav"]).exists() and r.get("sec", 0) >= 1.5][-60:]
print("сегментов для проверки:", len(rows))

full, cut, ms = [], [], []
for r in rows:
    w = wave.open(str(BD / r["wav"]), "rb"); sr = w.getframerate()
    a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0
    w.close()
    t0 = time.time(); pf = prob(a, sr); ms.append((time.time() - t0) * 1000)
    pc = prob(a[:int(len(a) * 0.65)], sr)
    full.append(pf); cut.append(pc)

full, cut = np.array(full), np.array(cut)
print("\n%-28s %7s %7s" % ("", "целый", "обрез"))
print("%-28s %7.3f %7.3f" % ("среднее", full.mean(), cut.mean()))
print("%-28s %7.3f %7.3f" % ("медиана", np.median(full), np.median(cut)))
print("%-28s %7.0f%% %6.0f%%" % ("доля > 0.5", 100*(full > .5).mean(), 100*(cut > .5).mean()))
print("время на вызов: %.1f мс (медиана)" % np.median(ms))
sep = (full > cut).mean()
print("\nсегмент целый оценён выше обрезанного в %.0f%% случаев" % (100*sep))
print("ВЕРДИКТ:", "работает" if (full.mean() - cut.mean() > 0.15 and sep > 0.6)
      else "разделения нет — не пускаем в конвейер")
print("\nпримеры (целый / обрез / текст):")
for r, pf, pc in list(zip(rows, full, cut))[:12]:
    print("  %.3f  %.3f  %s" % (pf, pc, (r.get("text") or "")[:60]))
