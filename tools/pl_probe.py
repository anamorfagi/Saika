# Проба раздельного захвата (ступень 1 «Слуховой сцены», 07.09.2026):
# Windows умеет отдавать звук ОДНОГО процесса (WASAPI process loopback,
# Win10 2004+). Проверяем на живом Discord: 8 с «только Discord» и 8 с
# «всё, кроме Discord» → data/pl_probe/*.wav + сводка data/pl_probe.txt.
# Запуск: runpy (отдельный процесс, не внутри Сайки).
import os, sys, time, json, subprocess, wave, struct
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "pl_probe"; OUT.mkdir(parents=True, exist_ok=True)
REP = ROOT / "data" / "pl_probe.txt"
lines = []
def say(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); lines.append(s)
    REP.write_text("\n".join(lines), encoding="utf-8")

say("python", sys.version.split()[0], "| платформа", sys.platform)
try:
    import process_audio_capture as pac
except Exception:
    say("ставлю process-audio-capture …")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "process-audio-capture"], capture_output=True, text=True)
    say("pip:", (r.stdout + r.stderr)[-400:])
    import process_audio_capture as pac
say("модуль:", pac.__file__)
PAC = pac.ProcessAudioCapture
say("поддержка ОС:", PAC.is_supported() if hasattr(PAC, "is_supported") else "?")
say("API:", [n for n in dir(PAC) if not n.startswith("_")])
# кто сейчас звучит
procs = []
try:
    fn = getattr(pac, "enumerate_audio_processes", None) or getattr(PAC, "enumerate_audio_processes", None)
    procs = list(fn()) if fn else []
except Exception as e:
    say("enumerate:", e)
say("звучащие процессы:", procs[:20])
def find(name):
    for p in procs:
        s = json.dumps(p, default=str, ensure_ascii=False).lower()
        if name in s:
            try:
                return int(p["pid"]) if isinstance(p, dict) else int(getattr(p, "pid", p[0]))
            except Exception:
                pass
    return None
pid = find("discord")
say("Discord pid:", pid)
if pid is None:
    say("Discord не звучит — беру первый звучащий процесс")
    try:
        p0 = procs[0]; pid = int(p0["pid"]) if isinstance(p0, dict) else int(getattr(p0, "pid", p0[0]))
    except Exception:
        say("процессов нет — стоп"); sys.exit(0)

def grab(path, mode, sec=8):
    lv = []
    kw = dict(pid=pid, output_path=str(path), level_callback=lambda d: lv.append(d))
    # режим: include / exclude — имя параметра выясняем по сигнатуре
    import inspect
    sig = inspect.signature(PAC.__init__).parameters
    say("параметры конструктора:", list(sig))
    for k in ("mode", "loopback_mode", "exclude", "include_tree"):
        if k in sig:
            if k == "exclude": kw[k] = (mode == "exclude")
            elif k == "include_tree": kw[k] = (mode == "include")
            else:
                for cand in (getattr(pac, "PAC_MODE_EXCLUDE" if mode == "exclude" else "PAC_MODE_INCLUDE", None),
                             mode.upper(), mode, 1 if mode == "exclude" else 0):
                    if cand is not None: kw[k] = cand; break
            break
    t0 = time.time()
    with PAC(**kw) as cap:
        cap.start()
        time.sleep(sec)
    dt = time.time() - t0
    try:
        with wave.open(str(path), "rb") as w:
            n, sr, ch, sw = w.getnframes(), w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(min(n, sr * 8))
        # RMS по секундам (float32 или int16)
        import numpy as np
        a = np.frombuffer(raw, np.float32 if sw == 4 else np.int16).astype(np.float32)
        if sw == 2: a /= 32768
        a = a.reshape(-1, ch).mean(1)
        rms = [round(float(np.sqrt(np.mean(a[i * sr:(i + 1) * sr] ** 2)) + 1e-9), 4) for i in range(min(8, a.size // sr))]
        say("%s: %.1f с записи, %d Гц, %d кан., %d байт/отсчёт, RMS по секундам %s, уровни cb %d (медиана %s)" % (
            mode, n / sr, sr, ch, sw, rms, len(lv), sorted(lv)[len(lv) // 2] if lv else None))
    except Exception as e:
        say(mode, "разбор wav:", e, "| размер", path.stat().st_size if path.exists() else 0)

grab(OUT / "discord_include.wav", "include")
grab(OUT / "discord_exclude.wav", "exclude")
say("готово")
