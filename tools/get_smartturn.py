# -*- coding: utf-8 -*-
"""Скачать Smart Turn v3 и ПРОВЕРИТЬ его на живом русском (2026-08-31).

Зачем отдельным скриптом, а не внутри слуха: качает с HF (секунды-минуты),
и главное — надо УБЕДИТЬСЯ, что модель вообще отличает законченную мысль
от оборванной НА НАШЕМ ЯЗЫКЕ И НАШЕМ ЗВУКЕ, прежде чем пускать её резать
фразы. Проверка честная: берём кусок из ролика, скармливаем целиком и
обрезанным на 60% (посреди слова). Если вероятность на обрезке не ниже —
модель нам не подходит, и лучше узнать это здесь.

Запуск: .venv\\Scripts\\python.exe tools\\get_smartturn.py
"""
import os, sys, time, pathlib, wave
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
DST = ROOT / "models" / "smartturn"
DST.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))

REPO = "pipecat-ai/smart-turn-v3"
CANDIDATES = ["smart-turn-v3.0-int8-dynamic.onnx", "smart-turn-v3.0.onnx",
              "smart-turn-v3-int8.onnx", "smart-turn-v3.onnx", "model.onnx"]

def fetch():
    from huggingface_hub import list_repo_files, hf_hub_download
    files = [f for f in list_repo_files(REPO) if f.endswith(".onnx")]
    print("onnx в репо:", files)
    pick = None
    for c in CANDIDATES:
        if c in files:
            pick = c
            break
    if pick is None and files:
        # предпочитаем int8, он вчетверо меньше
        files.sort(key=lambda f: (0 if "int8" in f else 1, len(f)))
        pick = files[0]
    if pick is None:
        raise RuntimeError("в репо нет .onnx")
    p = hf_hub_download(REPO, pick, local_dir=str(DST))
    print("скачано:", pick, os.path.getsize(p) // 1024, "КБ")
    return p

# ── лог-мел Whisper без transformers (в venv он подбитый: у qwen3 падает
# импорт AutoConfig). Фильтры Whisper — это ровно librosa.filters.mel
# с htk=False/norm=slaney, так в самом whisper и сгенерированы.
_MEL = {}
def logmel(x, sr=16000, n_mels=80, n_fft=400, hop=160, chunk_s=8):
    import librosa
    need = chunk_s * sr
    x = np.asarray(x, np.float32)
    # do_normalize=True у WhisperFeatureExtractor — нуль-среднее, единичная
    # дисперсия ПО СЫРОЙ ВОЛНЕ, до мела
    m, s = float(x.mean()), float(x.std())
    x = (x - m) / (s + 1e-7)
    x = x[-need:] if len(x) >= need else np.pad(x, (0, need - len(x)))
    if n_mels not in _MEL:
        _MEL[n_mels] = librosa.filters.mel(sr=sr, n_fft=n_fft, n_mels=n_mels)
    st = librosa.stft(x, n_fft=n_fft, hop_length=hop, window="hann")
    mag = (np.abs(st[..., :-1]) ** 2).astype(np.float32)
    mel = _MEL[n_mels] @ mag
    ls = np.log10(np.maximum(mel, 1e-10))
    ls = np.maximum(ls, ls.max() - 8.0)
    return ((ls + 4.0) / 4.0).astype(np.float32)

def main():
    path = fetch()
    import onnxruntime as ort
    so = ort.SessionOptions(); so.log_severity_level = 3
    sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
    ins = sess.get_inputs()
    print("вход:", [(i.name, i.shape, i.type) for i in ins])
    print("выход:", [(o.name, o.shape) for o in sess.get_outputs()])

    w = wave.open(str(ROOT / "data" / "snailkick.wav"), "rb")
    sr = w.getframerate()
    a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0
    w.close()
    print("тестовый звук: %.0fс @%dГц" % (len(a) / sr, sr))

    name = ins[0].name
    def prob(seg):
        f = logmel(seg, sr)
        t0 = time.time()
        out = sess.run(None, {name: np.expand_dims(f, 0)})
        return float(np.ravel(out[0])[0]), (time.time() - t0) * 1000

    # три окна по 6с из разных мест ролика: целиком и обрезанные на 60%
    print("\n%-22s %8s %8s %8s" % ("окно", "целое", "обрезок", "мс"))
    for start in (30, 60, 95, 130):
        seg = a[int(start * sr):int((start + 6) * sr)]
        if len(seg) < sr:
            continue
        pf, ms = prob(seg)
        pc, _ = prob(seg[:int(len(seg) * 0.6)])
        print("%-22s %8.3f %8.3f %8.1f" % ("с %dс" % start, pf, pc, ms))
    print("\nЖДЁМ: «целое» заметно выше «обрезка». Если нет — модель на нашем"
          " звуке не работает, дальше её не пускаем.")

main()
