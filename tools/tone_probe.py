# -*- coding: utf-8 -*-
"""Разведка T-one: встанет ли потоковый движок на эту машину (06.09.2026).

Владелец: «выпиливай все движки, ищи самый качественный и моментальный,
мне нужен максимальный реалтайм, чтобы он буквально мог писать буквы».

T-one (T-Bank, Apache 2.0) — единственная на сегодня открытая русская
модель с НАСТОЯЩИМ потоковым режимом: Conformer-CTC, 71 млн параметров,
кусок 300 мс. Не «нарезать на кусочки и звать движок», а потоковый
декодер с состоянием — буквы появляются по ходу речи.

Ставим осторожно: сначала проверяем, что ставится и запускается, и
только потом трогаем рабочий слух. KenLM (который на Windows требует
компилятор) НЕ обязателен — без него работает жадное декодирование."""
import io, os, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
O=[]
def say(*a):
    s=" ".join(str(x) for x in a); print(s); O.append(s)
    io.open(ROOT/"data"/"tone_probe.txt","w",encoding="utf-8").write("\n".join(O))

PY = sys.executable
say("питон:", PY)
say("платформа:", sys.platform)

def run(*cmd, t=900):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=t)
        return r.returncode, (r.stdout or "")[-1500:], (r.stderr or "")[-1500:]
    except Exception as e:
        return -1, "", repr(e)[:300]

say("\n[1] проверяю, стоит ли уже")
rc, o, e = run(PY, "-c", "import tone; print('tone', getattr(tone,'__version__','?'))")
if rc == 0:
    say("   уже стоит:", o.strip())
else:
    say("   нет:", (e or o).strip()[:200])
    say("\n[2] ставлю tone (без kenlm — он тут не обязателен)")
    rc, o, e = run(PY, "-m", "pip", "install", "--no-input", "tone")
    say("   код возврата:", rc)
    say("   хвост:", (o or e).strip()[-700:])

say("\n[3] onnxruntime на месте?")
rc, o, e = run(PY, "-c", "import onnxruntime as r; print(r.__version__, r.get_available_providers())")
say("  ", (o or e).strip()[:250])

say("\n[4] пробую поднять потоковый конвейер и прогнать наш кусок")
code = r'''
import sys, wave, time
import numpy as np
sys.path.insert(0, r"%s")
from tone import StreamingCTCPipeline
p = StreamingCTCPipeline.from_hugging_face()
CH = int(getattr(p, "CHUNK_SIZE", 2400))
SR = int(getattr(p, "SAMPLE_RATE", 8000))
print("модель ждёт куски по", CH, "отсчётов при", SR, "Гц =", round(CH/SR*1000), "мс")
w = wave.open(r"%s", "rb")
sr = w.getframerate(); pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)
print("файл:", sr, "Гц,", round(len(pcm)/sr,1), "с")
if sr != SR:
    # линейный пересчёт частоты: модель телефонная, ей нужно 8 кГц
    n = int(len(pcm) * SR / sr)
    idx = (np.arange(n) * (sr / SR)).astype(np.int64)
    pcm = pcm[np.clip(idx, 0, len(pcm)-1)]
    print("пересчитала в", SR, "Гц ->", round(len(pcm)/SR,1), "с")
SEC = 30
state=None; t0=time.monotonic(); said=[]
for i in range(0, min(len(pcm), SR*SEC) - CH + 1, CH):
    ph, state = p.forward(pcm[i:i+CH].astype(np.int32), state)
    for x in (ph or []):
        said.append(str(getattr(x, "text", x)))
try:
    ph = p.finalize(state)
    for x in (ph or []): said.append(str(getattr(x, "text", x)))
except Exception:
    pass
took = time.monotonic()-t0
print("за %%.1f с обработано %%d с звука (%%.2fx реального времени)" %% (took, SEC, took/SEC))
print("реплик:", len(said))
print("услышано:", " | ".join(said)[:900])
''' % (str(ROOT), str(ROOT / "data" / "bench_1000_1300.wav"))

rc, o, e = run(PY, "-c", code, t=1200)
say("   код возврата:", rc)
say("   ВЫВОД: " + o.strip()[-900:])
say("   ОШИБКА: " + e.strip()[-1500:])
