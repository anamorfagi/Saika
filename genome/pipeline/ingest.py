#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest.py — приёмник материалов: папка с чем угодно → corpus/ с текстом [m:ss] и sources.json. Один вход для следователя.
Что понимает:
  видео (mp4/mkv/avi/webm): дорожка субтитров → ffmpeg → текст; нет дорожки → вшитые субтитры → hardsub_ocr.py (tesseract); нет и их → аудио → faster-whisper (если стоит)
  аудио (mp3/m4a/wav/ogg): faster-whisper → текст; prosody.py → просодия
  субтитры (srt/vtt/ass): → текст с метками
  текст (txt/md/jsonl/json): как есть
  документы (pdf/epub/docx): pdftotext / pandoc, если стоят
  картинки (jpg/png/webp): tagger.py → теги внешности; первая — аватар
  python ingest.py <папка> --out chars/<id> [--lang rus] [--no-ocr] [--no-asr]
"""
import sys, re, json, argparse, pathlib, subprocess, shutil, datetime
HERE = pathlib.Path(__file__).parent
V = {".mp4", ".mkv", ".avi", ".webm", ".mov"}; A = {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac"}; S = {".srt", ".vtt", ".ass", ".ssa"}
T = {".txt", ".md", ".jsonl", ".json"}; D = {".pdf", ".epub", ".docx"}; I = {".jpg", ".jpeg", ".png", ".webp"}
def say(stage, msg, **kw): d = {"stage": stage, "msg": msg}; d.update(kw); print(json.dumps(d, ensure_ascii=False), flush=True)
def run(cmd, **kw): return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", **kw)
def ts(sec): sec = int(sec); return f"[{sec//60}:{sec%60:02d}]"
def sub_to_txt(path: pathlib.Path):
    raw = path.read_text(encoding="utf-8", errors="ignore"); out = []; last = ""
    if path.suffix in (".ass", ".ssa"):
        for l in raw.splitlines():
            if not l.startswith("Dialogue:"): continue
            p = l.split(",", 9); h, m, s = p[1].split(":"); text = re.sub(r"\{[^}]*\}", "", p[9]).replace("\\N", " ").strip()
            if text and text != last: out.append(f"{ts(int(h)*3600+int(m)*60+float(s))} {text}"); last = text
    else:
        for block in re.split(r"\n\s*\n", raw):
            m = re.search(r"(\d+):(\d+):(\d+)[.,]\d+\s*-->", block)
            if not m: continue
            t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            text = " ".join(re.sub(r"<[^>]+>", "", l).strip() for l in block.splitlines() if "-->" not in l and not l.strip().isdigit()).strip()
            if text and text != last: out.append(f"{ts(t)} {text}"); last = text
    return "\n".join(out)
def video_subs(video: pathlib.Path, dst: pathlib.Path):
    pr = run(["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries", "stream=index:stream_tags=language", "-of", "json", str(video)])
    try: streams = json.loads(pr.stdout).get("streams", [])
    except Exception: streams = []
    if not streams: return None
    pick = next((s for s in streams if (s.get("tags") or {}).get("language", "").startswith("ru")), streams[0])
    tmp = dst.with_suffix(".srt"); r = run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-map", f"0:{pick['index']}", str(tmp)])
    if r.returncode != 0 or not tmp.exists(): return None
    txt = sub_to_txt(tmp); tmp.unlink(); dst.write_text(txt, encoding="utf-8"); return "дорожка субтитров"
def asr(audio: pathlib.Path, dst: pathlib.Path, lang):
    try: from faster_whisper import WhisperModel
    except ImportError: return None
    m = WhisperModel("small", device="cpu", compute_type="int8"); segs, _ = m.transcribe(str(audio), language=lang[:2], vad_filter=True)
    dst.write_text("\n".join(f"{ts(s.start)} {s.text.strip()}" for s in segs), encoding="utf-8"); return "faster-whisper"
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("folder"); ap.add_argument("--out", required=True); ap.add_argument("--lang", default="rus")
    ap.add_argument("--no-ocr", action="store_true"); ap.add_argument("--no-asr", action="store_true"); ap.add_argument("--fps", type=float, default=2)
    a = ap.parse_args(); src = pathlib.Path(a.folder); out = pathlib.Path(a.out); (out / "corpus").mkdir(parents=True, exist_ok=True); (out / "photos").mkdir(exist_ok=True)
    files = sorted(p for p in src.rglob("*") if p.is_file()); rec = {"folder": str(src), "started": datetime.datetime.now().isoformat(timespec="minutes"), "texts": [], "photos": [], "audio": [], "notes": []}
    say("ingest", f"файлов: {len(files)}")
    for i, p in enumerate(files):
        ext = p.suffix.lower(); dst = out / "corpus" / (re.sub(r"[^\w\-]+", "_", p.stem)[:60] + ".txt"); how = None
        try:
            if ext in S: dst.write_text(sub_to_txt(p), encoding="utf-8"); how = "субтитры " + ext
            elif ext in T: shutil.copy(p, dst); how = "текст"
            elif ext in V:
                how = video_subs(p, dst)
                if not how and not a.no_ocr and shutil.which("tesseract"):
                    say("ingest", f"{p.name}: дорожки субтитров нет — OCR вшитых ({a.fps} к/с)…")
                    r = run([sys.executable, str(HERE / "hardsub_ocr.py"), str(p), "--out", str(dst), "--fps", str(a.fps), "--lang", a.lang], timeout=3600)
                    if dst.exists() and dst.stat().st_size > 200: how = "OCR вшитых субтитров"
                    else: rec["notes"].append(f"{p.name}: OCR не дал текста ({r.stderr[-120:]})")
                if not how and not a.no_asr:
                    wav = out / "corpus" / (dst.stem + ".m4a"); run(["ffmpeg", "-v", "error", "-y", "-i", str(p), "-vn", "-ac", "1", "-b:a", "64k", str(wav)])
                    how = asr(wav, dst, a.lang) if wav.exists() else None
                    if how: rec["audio"].append(str(wav.name))
                    elif wav.exists(): rec["notes"].append(f"{p.name}: транскрипта нет (faster-whisper не установлен), аудио сохранено")
            elif ext in A:
                how = asr(p, dst, a.lang) if not a.no_asr else None; rec["audio"].append(p.name)
                if (HERE / "prosody.py").exists():
                    r = run([sys.executable, str(HERE / "prosody.py"), str(p)], timeout=900); (out / (dst.stem + ".prosody.json")).write_text(r.stdout or r.stderr, encoding="utf-8")
                if not how: rec["notes"].append(f"{p.name}: faster-whisper не установлен — только просодия")
            elif ext in D:
                if ext == ".pdf" and shutil.which("pdftotext"): run(["pdftotext", "-layout", str(p), str(dst)]); how = "pdftotext"
                elif shutil.which("pandoc"): run(["pandoc", str(p), "-t", "plain", "-o", str(dst)]); how = "pandoc"
                else: rec["notes"].append(f"{p.name}: нужен pdftotext/pandoc")
            elif ext in I:
                shutil.copy(p, out / "photos" / p.name); rec["photos"].append(p.name)
                if (HERE / "tagger.py").exists() and len(rec["photos"]) <= 3:
                    r = run([sys.executable, str(HERE / "tagger.py"), str(p)], timeout=900); (out / (p.stem + ".tags.json")).write_text(r.stdout or r.stderr, encoding="utf-8")
                continue
            else: continue
        except Exception as e: rec["notes"].append(f"{p.name}: {e}"); continue
        if how and dst.exists(): rec["texts"].append({"file": dst.name, "from": p.name, "how": how, "chars": dst.stat().st_size}); say("ingest", f"{p.name} → {how}, {dst.stat().st_size//1000}k", progress=(i+1)/len(files))
    with open(out / "corpus.txt", "w", encoding="utf-8") as f:
        for t in rec["texts"]: f.write(f"\n\n## {t['from']} [{t['how']}]\n\n" + (out / "corpus" / t["file"]).read_text(encoding="utf-8", errors="ignore"))
    rec["corpus_chars"] = (out / "corpus.txt").stat().st_size; json.dump(rec, open(out / "sources.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    say("done", f"текстов {len(rec['texts'])}, аудио {len(rec['audio'])}, фото {len(rec['photos'])}; корпус {rec['corpus_chars']//1000}k → {out}", ok=True, corpus=str(out / "corpus.txt"), notes=rec["notes"])
if __name__ == "__main__": main()
