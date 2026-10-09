#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hardsub_ocr.py — транскрипт из вшитых (hard) субтитров: видео → кадры полосы субтитров (fps 2) → tesseract rus → строки [m:ss] текст.
Дубли подряд склеиваются, мусор без кириллицы отбрасывается, короткие вспышки (<1 кадр) — тоже.
  python hardsub_ocr.py видео.mp4 --out transcript.txt [--fps 2] [--band 0.80] [--lang rus]
Нужны: ffmpeg, tesseract + языковой пакет (tesseract-ocr-rus), pillow, pytesseract.
"""
import sys, os, re, argparse, subprocess, pathlib, tempfile, json
from concurrent.futures import ProcessPoolExecutor
def ocr_one(args):
    path, lang, thr = args
    from PIL import Image, ImageOps
    import pytesseract
    im = Image.open(path).convert("L"); im = ImageOps.autocontrast(im); im = im.resize((im.width * 2, im.height * 2))
    bw = im.point(lambda x: 255 if x > thr else 0)
    d = pytesseract.image_to_data(bw, lang=lang, config="--psm 6", output_type=pytesseract.Output.DICT)
    words = [(w, float(c)) for w, c in zip(d["text"], d["conf"]) if w.strip() and float(c) > 40]
    text = " ".join(w for w, _ in words); conf = sum(c for _, c in words) / len(words) if words else 0
    return text, conf
def clean(s):
    s = re.sub(r"[|_—\-]{2,}", " ", s); s = re.sub(r"\s+", " ", s).strip(" .-—|_`'\"")
    cyr = len(re.findall(r"[А-Яа-яЁё]", s)); return s if cyr >= max(3, 0.5 * len(re.sub(r"\s", "", s))) else ""
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("video"); ap.add_argument("--out", required=True); ap.add_argument("--fps", type=float, default=2); ap.add_argument("--band", type=float, default=0.80, help="верх полосы субтитров, доля высоты")
    ap.add_argument("--lang", default="rus"); ap.add_argument("--thr", type=int, default=200); ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    a = ap.parse_args(); tmp = pathlib.Path(tempfile.mkdtemp(prefix="hardsub_"))
    subprocess.run(["ffmpeg", "-v", "error", "-i", a.video, "-vf", f"fps={a.fps},crop=iw:ih*{1-a.band:.3f}:0:ih*{a.band:.3f}", "-q:v", "3", str(tmp / "f%06d.jpg")], check=True)
    frames = sorted(tmp.glob("f*.jpg")); print(f"кадров {len(frames)}", file=sys.stderr)
    with ProcessPoolExecutor(a.jobs) as ex: res = list(ex.map(ocr_one, [(str(f), a.lang, a.thr) for f in frames], chunksize=8))
    lines = []; cur = None
    for i, (text, conf) in enumerate(res):
        t = i / a.fps; s = clean(text)
        if cur and s and (s == cur["text"] or (len(s) > 8 and (s in cur["text"] or cur["text"] in s))):
            cur["end"] = t; cur["n"] += 1
            if conf > cur["conf"]: cur["text"], cur["conf"] = (s if len(s) >= len(cur["text"]) else cur["text"]), conf
            continue
        if cur and cur["n"] >= 2: lines.append(cur)
        cur = {"start": t, "end": t, "text": s, "conf": conf, "n": 1} if s else None
    if cur and cur["n"] >= 2: lines.append(cur)
    out = pathlib.Path(a.out)
    out.write_text("\n".join(f"[{int(l['start'])//60}:{int(l['start'])%60:02d}] {l['text']}" for l in lines), encoding="utf-8")
    out.with_suffix(".jsonl").write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines), encoding="utf-8")
    print(f"строк {len(lines)}, средняя уверенность OCR {sum(l['conf'] for l in lines)/max(1,len(lines)):.0f} → {out}", file=sys.stderr)
    for f in frames: f.unlink()
if __name__ == "__main__": main()
