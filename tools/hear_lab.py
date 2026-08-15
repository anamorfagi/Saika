"""СТЕНД СЛУХА НА ФАЙЛАХ И РОЛИКАХ — офлайн-прогон всего конвейера.

(2026-08-15, задача владельца: «сделать среду для запуска ролика с ютуба и
проверять, как система распознаёт голоса реальных людей, пока не
получится».)

Берёт аудио (файл или ссылку на YouTube, если стоит yt-dlp), прогоняет его
ЧЕРЕЗ ТОТ ЖЕ КОД, что слышит микрофон — кусками по 100мс, как шлёт браузер:
нарезка (энергия ПРОТИВ нейронки silero), разрез по смене голоса, движки
распознавания — и собирает html-отчёт: волна, кто что написал, где
границы фраз и голосов. По нему видно не «кажется лучше», а что именно
изменилось.

Запуск (из корня проекта, в его venv):
    .venv\\Scripts\\python tools\\hear_lab.py path\\to\\audio.wav
    .venv\\Scripts\\python tools\\hear_lab.py https://youtu.be/XXXX
    ... --engines gigaam,faster_whisper   (по умолчанию оба)
    ... --ref "эталонный текст"           (посчитает WER)

Сервер Сайки для этого НЕ нужен и не мешает: стенд грузит свои копии
движков. На время прогона видеопамять делится с работающей Сайкой — для
чистоты замера её лучше закрыть.
"""
import argparse
import difflib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402


def load_audio(src: str):
    """Файл или ютуб-ссылка -> int16 mono 16k."""
    import soundfile as sf
    p = Path(src)
    if not p.exists() and src.startswith(("http://", "https://")):
        out = ROOT / "data" / "hear_lab"
        out.mkdir(parents=True, exist_ok=True)
        wav = out / "yt_input.wav"
        print("Качаю звук ролика (yt-dlp)…")
        subprocess.run(["yt-dlp", "-x", "--audio-format", "wav",
                        "-o", str(wav.with_suffix("")) + ".%(ext)s",
                        "--no-playlist", src], check=True)
        p = wav
    x, sr = sf.read(str(p), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if sr != 16000:
        n = int(len(x) * 16000 / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n),
                      np.arange(len(x)), x).astype(np.float32)
    return np.clip(x * 32767, -32768, 32767).astype(np.int16)


def segment(pcm: np.ndarray, vad_engine: str):
    """Нарезка тем же VadSegmenter, кусками по 100мс, как в бою."""
    from server.config import CFG
    from server.stt.manager import VadSegmenter
    from server.stt import neuro_vad
    CFG.set("stt.vad.engine", vad_engine)
    if vad_engine == "silero":
        neuro_vad.warm()
        for _ in range(100):
            if neuro_vad.STATE["ready"] or neuro_vad.STATE["off"]:
                break
            time.sleep(0.2)
        if not neuro_vad.STATE["ready"]:
            print("  silero-vad не поднялся:", neuro_vad.STATE["why"])
            return None
        neuro_vad.reset()
    v = VadSegmenter()
    segs = []
    pos = 0
    for i in range(0, len(pcm) - 1600, 1600):
        s = v.push(pcm[i:i + 1600])
        if s is not None:
            segs.append((i + 1600 - len(s), s))
    if v.buffer:
        s = np.concatenate(v.buffer)
        segs.append((len(pcm) - len(s), s))
    return segs


def wer(ref: str, hyp: str) -> float:
    r, h = ref.lower().split(), hyp.lower().split()
    sm = difflib.SequenceMatcher(a=r, b=h)
    hits = sum(m.size for m in sm.get_matching_blocks())
    return round(100.0 * (1 - hits / max(1, len(r))), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="файл или ссылка на YouTube")
    ap.add_argument("--engines", default="gigaam,faster_whisper")
    ap.add_argument("--ref", default="", help="эталонный текст для WER")
    args = ap.parse_args()

    pcm = load_audio(args.src)
    print(f"Звук: {len(pcm)/16000:.1f}с")

    from server.stt.engines import ALL_ENGINES
    from server.stt import turns
    engines = {}
    for name in args.engines.split(","):
        name = name.strip()
        if name not in ALL_ENGINES:
            print("нет движка", name)
            continue
        print("Грею", name, "…")
        engines[name] = ALL_ENGINES[name]()
        engines[name].load()

    rows = []
    for vad in ("energy", "silero"):
        segs = segment(pcm, vad)
        if segs is None:
            continue
        print(f"\n═ Нарезка «{vad}»: {len(segs)} фраз ═")
        for start, s in segs:
            t0 = start / 16000
            parts = turns.split(s, 16000)
            for pt in parts:
                a = s[pt["start"]:pt["end"]]
                row = {"vad": vad, "t": round(t0 + pt["start"] / 16000, 1),
                       "sec": round(len(a) / 16000, 1),
                       "crowd": pt["crowd"], "texts": {}}
                for name, eng in engines.items():
                    tt = time.monotonic()
                    try:
                        txt = eng.transcribe(a, 16000) or ""
                    except Exception as e:
                        txt = f"[ошибка: {e}]"
                    row["texts"][name] = (txt,
                                          round((time.monotonic() - tt) * 1000))
                rows.append(row)
                mark = " ⚠несколько голосов" if pt["crowd"] else ""
                print(f"  {row['t']:6.1f}с ({row['sec']:.1f}с){mark}")
                for name, (txt, ms) in row["texts"].items():
                    print(f"      {name:16} {ms:5}мс  {txt[:70]}")

    if args.ref:
        print("\n═ WER против эталона ═")
        for vad in ("energy", "silero"):
            for name in engines:
                hyp = " ".join(r["texts"].get(name, ("",))[0]
                               for r in rows if r["vad"] == vad)
                print(f"  {vad:7} + {name:16} WER {wer(args.ref, hyp)}%")

    out = ROOT / "data" / "hear_lab" / f"lab_{time.strftime('%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")
    print("\nПодробности:", out)


if __name__ == "__main__":
    main()
