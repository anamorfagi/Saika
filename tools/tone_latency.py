# -*- coding: utf-8 -*-
"""ЧЕРЕЗ СКОЛЬКО ПОСЛЕ ЗВУКА ПОЯВЛЯЕТСЯ БУКВА (06.09.2026).

Владелец: «когда ты мне такое пишешь, я вспоминаю, что таких технологий
недавно вообще не существовало. Если нет, а задача требует — значит
нужно сделать либо найти способ схитрить».

Он прав, и спорить не о чем. Поэтому вместо рассуждений — измерение.
Гоняем файл кусками по 30 мс, как это делает живой цикл, и на каждом
шаге спрашиваем: сколько звука уже скормлено и сколько букв уже
написано. Разница между позицией последней буквы и позицией головы
звука — и есть настоящая задержка показа."""
import io, sys, time, wave
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
O=[]
def say(*a):
    s=" ".join(str(x) for x in a); print(s); O.append(s)
    io.open(ROOT/"data"/"tone_latency.txt","w",encoding="utf-8").write("\n".join(O))

from anamorf.stt.stream_tone import ToneStream, SR_IN
s = ToneStream("lat"); s.load()
w = wave.open(str(ROOT/"data"/"bench_1000_1300.wav"), "rb")
sr = w.getframerate(); pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16)

HOP = int(SR_IN * 0.03)     # 30 мс — шаг живого цикла
grew = []                   # (позиция звука, сколько букв стало)
prev_len = 0
t_cpu = 0.0
SECS = 45
for i in range(0, min(len(pcm), SR_IN*SECS) - HOP, HOP):
    at = i / SR_IN
    t0 = time.perf_counter()
    txt = s.feed(pcm[i:i+HOP])
    if txt is None:
        txt = s.preview()
    t_cpu += time.perf_counter() - t0
    cur = s.text or ""
    if len(cur) > prev_len:
        grew.append((at, len(cur) - prev_len))
        prev_len = len(cur)

say("прогон: %d с звука, шагом 30 мс" % SECS)
say("процессорного времени: %.1f с на %d с звука (%.0f%% одного ядра)"
    % (t_cpu, SECS, t_cpu/SECS*100))
say("моментов, когда текст ВЫРОС: %d" % len(grew))
if len(grew) > 2:
    gaps = [grew[i+1][0]-grew[i][0] for i in range(len(grew)-1)]
    gaps.sort()
    say("между появлениями букв: медиана %.0f мс, 90%% быстрее %.0f мс"
        % (gaps[len(gaps)//2]*1000, gaps[int(len(gaps)*0.9)]*1000))
    say("то есть текст прирастает примерно %.0f раз в секунду" % (1/max(gaps[len(gaps)//2],1e-3)))
say("\nпервые двадцать приростов (секунда звука -> сколько букв добавилось):")
say("   " + "  ".join("%.2f:+%d" % g for g in grew[:20]))
say("\nчто написано к концу прогона:")
say("   " + (s.text or "")[-300:])
say("\nготовый текст (строгий порог растяжки):")
say("   " + s.close()[-300:])
