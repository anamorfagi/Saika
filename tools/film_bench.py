# Стенд фильма: несколько движков пишут одни и те же клипы стенда слуха
# (data/hear_bench/*.wav), результат копится в data/film_bench.jsonl.
# Запуск отдельным процессом (runpy), клипы берутся с начала фильма.
import json, re, sys, time, wave
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import numpy as np
SR = 16000
FILM_TS = 1788719840.0          # 22:37 — старт фильма
OUT = ROOT / "data" / "film_bench.jsonl"
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 400

done = {}
if OUT.exists():
    for ln in open(OUT, encoding="utf-8"):
        try:
            r = json.loads(ln); done[r["wav"]] = r
        except Exception:
            pass

idx = [json.loads(l) for l in open(ROOT / "data" / "hear_bench" / "index.jsonl", encoding="utf-8") if l.strip()]
idx = [r for r in idx if r.get("ts", 0) >= FILM_TS]
todo = [r for r in idx if r["wav"] not in done][:LIMIT]
print("клипов фильма", len(idx), "новых", len(todo), flush=True)
if not todo:
    sys.exit(0)

from anamorf.stt import frontend
from faster_whisper import WhisperModel
t0 = time.time()
wm = WhisperModel("mobiuslabsgmbh/faster-whisper-large-v3-turbo", device="cuda", compute_type="float16")
print("whisper-turbo %.1fs" % (time.time() - t0), flush=True)
try:
    import onnx_asr
    t0 = time.time(); pk = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3")
    print("parakeet %.1fs" % (time.time() - t0), flush=True)
except Exception as e:
    pk = None; print("parakeet нет:", e, flush=True)

def wh(seg, prompt=None, lang="ru"):
    t0 = time.perf_counter()
    segs, info = wm.transcribe(seg, language=lang, beam_size=5, vad_filter=False,
                               condition_on_previous_text=False, initial_prompt=prompt,
                               word_timestamps=True)
    words = []; txt = []
    for s in segs:
        txt.append(s.text)
        for w in (s.words or []):
            words.append([w.word.strip(), round(w.probability, 2)])
    return " ".join(t.strip() for t in txt).strip(), words, int(1000 * (time.perf_counter() - t0))

ctx = []   # последние слова для подсказки whisper
with open(OUT, "a", encoding="utf-8") as fo:
    for n, r in enumerate(todo):
        p = ROOT / "data" / "hear_bench" / r["wav"]
        try:
            with wave.open(str(p), "rb") as w:
                sr = w.getframerate(); a = np.frombuffer(w.readframes(w.getnframes()), np.int16)
        except Exception as e:
            print("skip", r["wav"], e); continue
        if sr != SR:
            k = SR / sr; a = a[(np.arange(int(a.size * k)) / k).astype(np.int64)]
        row = {"wav": r["wav"], "at": r.get("at"), "sec": r.get("sec"), "giga": r.get("text", ""), "giga_ms": r.get("ms")}
        try:
            prep = frontend.prepare(a, SR)
            f32 = np.asarray(prep, np.float32)
            if f32.dtype != np.float32 or np.abs(f32).max() > 1.5:
                f32 = f32.astype(np.float32) / 32768
        except Exception:
            f32 = a.astype(np.float32) / 32768
        raw = a.astype(np.float32) / 32768
        try:
            row["wt"], row["wt_w"], row["wt_ms"] = wh(f32)                       # turbo + фронтенд
            row["wt_raw"], _, row["wt_raw_ms"] = wh(raw)                        # turbo сырой
            prompt = " ".join(ctx[-40:]) if ctx else None
            row["wt_ctx"], _, row["wt_ctx_ms"] = wh(f32, prompt=prompt)         # turbo + контекст
        except Exception as e:
            row["wt_err"] = repr(e)
        if pk is not None:
            try:
                t0 = time.perf_counter(); row["pk"] = (pk.recognize(raw, language="ru") or "").strip()
                row["pk_ms"] = int(1000 * (time.perf_counter() - t0))
            except Exception as e:
                row["pk_err"] = repr(e)
        base = row.get("wt") or row.get("giga") or ""
        ctx += [w for w in base.split() if w]
        ctx = ctx[-60:]
        fo.write(json.dumps(row, ensure_ascii=False) + "\n"); fo.flush()
        if n % 20 == 0:
            print(n, r["wav"], "|", row.get("giga", "")[:40], "|", (row.get("wt") or "")[:40], "|", (row.get("pk") or "")[:40], flush=True)
print("готово", len(todo))
