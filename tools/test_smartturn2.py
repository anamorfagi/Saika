# -*- coding: utf-8 -*-
"""Smart Turn: проверка БЕЗ артефакта добивки нулями (2026-08-31).

Первая проверка провалилась наизнанку — обрезок получал 0.84, целый
сегмент 0.37. Разбор: наш VAD срезает хвостовую тишину, я добивал кусок
до восьми секунд ЦИФРОВЫМИ НУЛЯМИ, и у обрезка этих нулей было на треть
больше. Модель мерила длину тишины, а не законченность мысли — то есть
мерил я, а не она.

Здесь оба класса — ровно 8 секунд НАСТОЯЩЕГО звука, ни одного добитого
сэмпла, разница только в том, ГДЕ окно кончается:
  «мысль кончена»  — окно кончается там, где Silero увидел конец речи;
  «оборвано»       — окно кончается в середине речевого куска.
Если модель работает, разделение обязано быть видно на средних.
"""
import os, sys, wave, pathlib, time
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
MODEL = sys.argv[1] if len(sys.argv) > 1 else "smart-turn-v3.2-cpu.onnx"
SR, WIN = 16000, 8

from huggingface_hub import hf_hub_download
mp = hf_hub_download("pipecat-ai/smart-turn-v3", MODEL,
                     local_dir=str(ROOT / "models" / "smartturn"))
import onnxruntime as ort, librosa, torch
so = ort.SessionOptions(); so.log_severity_level = 3
sess = ort.InferenceSession(mp, so, providers=["CPUExecutionProvider"])
IN = sess.get_inputs()[0].name

_M = {}
def feats(x):
    x = np.asarray(x, np.float32)
    x = (x - x.mean()) / (x.std() + 1e-7)
    if 80 not in _M:
        _M[80] = librosa.filters.mel(sr=SR, n_fft=400, n_mels=80)
    st = librosa.stft(x, n_fft=400, hop_length=160, window="hann")
    ls = np.log10(np.maximum(_M[80] @ (np.abs(st[..., :-1]) ** 2), 1e-10))
    ls = np.maximum(ls, ls.max() - 8.0)
    return ((ls + 4.0) / 4.0).astype(np.float32)

def prob(seg):
    o = sess.run(None, {IN: np.expand_dims(feats(seg), 0)})
    v = float(np.ravel(o[0])[0])
    return v if 0.0 <= v <= 1.0 else float(1.0 / (1.0 + np.exp(-v)))

w = wave.open(str(ROOT / "data" / "snailkick.wav"), "rb")
a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0
w.close()
print("ролик: %.0fс" % (len(a) / SR))

from silero_vad import load_silero_vad, get_speech_timestamps
model = load_silero_vad()
ts = get_speech_timestamps(torch.from_numpy(a), model, sampling_rate=SR,
                           min_silence_duration_ms=300, min_speech_duration_ms=250)
print("речевых кусков по Silero:", len(ts))

need = WIN * SR
ends_done, ends_mid = [], []
for s in ts:
    e, st = s["end"], s["start"]
    if e - need >= 0:
        ends_done.append(e)                       # окно кончается КОНЦОМ речи
    mid = st + int((e - st) * 0.55)
    if (e - st) > 1.2 * SR and mid - need >= 0:
        ends_mid.append(mid)                      # окно кончается ПОСРЕДИ речи
print("окон «мысль кончена»: %d, «оборвано»: %d" % (len(ends_done), len(ends_mid)))

def run(ends):
    out, tm = [], []
    for e in ends[:80]:
        seg = a[e - need:e]
        t0 = time.time(); out.append(prob(seg)); tm.append((time.time() - t0) * 1000)
    return np.array(out), float(np.median(tm)) if tm else 0.0

pd, ms = run(ends_done)
pm, _ = run(ends_mid)
print("\n%-22s %8s %8s" % ("", "кончена", "оборвано"))
print("%-22s %8.3f %8.3f" % ("среднее", pd.mean(), pm.mean()))
print("%-22s %8.3f %8.3f" % ("медиана", np.median(pd), np.median(pm)))
print("%-22s %7.0f%% %7.0f%%" % ("доля > 0.5", 100*(pd > .5).mean(), 100*(pm > .5).mean()))
print("время на вызов: %.1f мс" % ms)
d = pd.mean() - pm.mean()
print("\nразрыв средних: %+.3f" % d)
print("ВЕРДИКТ:", "работает, берём" if d > 0.15 else
      ("СЛАБО — порог придётся калибровать" if d > 0.05 else "не различает — не берём"))
