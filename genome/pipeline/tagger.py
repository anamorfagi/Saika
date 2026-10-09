#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tagger.py — теги внешности по картинке, офлайн: WD14 (SmilingWolf/wd-vit-tagger-v3, ONNX, ~330 МБ).
Модель скачивается один раз в models/wd-vit-tagger-v3/ (нужен интернет только для этого).
Выход: {"tags": {тег: вероятность}, "rating": ..., "chars": [...]} — вход для persona.py --tags.

  pip install onnxruntime pillow numpy
  python tagger.py face.jpg > tags.json          # порог 0.35 по умолчанию
  python tagger.py face.jpg --thr 0.3 --top 60
"""
import sys, json, argparse, pathlib, urllib.request, csv
HERE = pathlib.Path(__file__).parent; MD = HERE.parent / "models" / "wd-vit-tagger-v3"
REPO = "https://huggingface.co/SmilingWolf/wd-vit-tagger-v3/resolve/main/"
FILES = {"model.onnx": REPO + "model.onnx", "selected_tags.csv": REPO + "selected_tags.csv"}

def ensure_model(log=print):
    MD.mkdir(parents=True, exist_ok=True)
    for f, url in FILES.items():
        p = MD / f
        if p.exists() and p.stat().st_size > 1000: continue
        log(f"скачиваю {f} …")
        def hook(b, bs, total):
            if total > 0 and b % 200 == 0: log(f"  {b*bs/1e6:.0f} / {total/1e6:.0f} МБ")
        urllib.request.urlretrieve(url, p, hook)
    return MD / "model.onnx", MD / "selected_tags.csv"

def tag(image_path, thr=0.35, top=80, log=lambda *a: None):
    import numpy as np
    from PIL import Image
    import onnxruntime as ort
    model, csvp = ensure_model(log)
    sess = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0]; size = inp.shape[1] if isinstance(inp.shape[1], int) else 448
    im = Image.open(image_path).convert("RGBA"); bg = Image.new("RGBA", im.size, (255, 255, 255, 255)); im = Image.alpha_composite(bg, im).convert("RGB")
    w, h = im.size; s = max(w, h); sq = Image.new("RGB", (s, s), (255, 255, 255)); sq.paste(im, ((s - w) // 2, (s - h) // 2)); sq = sq.resize((size, size), Image.BICUBIC)
    x = np.asarray(sq, dtype=np.float32)[:, :, ::-1][None]   # WD14 ждёт BGR, NHWC, 0..255
    probs = sess.run(None, {inp.name: x})[0][0]
    rows = list(csv.DictReader(open(csvp, encoding="utf-8")))
    general = {}; rating = {}; chars = []
    for r, p in zip(rows, probs):
        name = r["name"].replace("_", " "); cat = int(r["category"])
        if cat == 9: rating[name] = round(float(p), 3)
        elif cat == 4 and p >= thr: chars.append(name)
        elif cat == 0 and p >= thr: general[name] = round(float(p), 3)
    general = dict(sorted(general.items(), key=lambda kv: -kv[1])[:top])
    return {"tags": general, "rating": max(rating, key=rating.get) if rating else None, "chars": chars, "model": "wd-vit-tagger-v3"}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("image"); ap.add_argument("--thr", type=float, default=0.35); ap.add_argument("--top", type=int, default=80)
    a = ap.parse_args()
    try:
        print(json.dumps(tag(a.image, a.thr, a.top, log=lambda *x: print(*x, file=sys.stderr)), ensure_ascii=False, indent=1))
    except ImportError as e:
        print(json.dumps({"error": f"нет библиотеки: {e}. pip install onnxruntime pillow numpy"}), file=sys.stdout); sys.exit(2)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False)); sys.exit(1)
