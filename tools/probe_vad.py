# -*- coding: utf-8 -*-
"""ПРОВЕРКА: съедает ли нарезка начало (2026-09-01).

Собираем сегментатор и кормим его звуком, который НАЧИНАЕТСЯ СРАЗУ с
речи — как когда человек уже говорит или только что заиграл ролик.
Смотрим, доходит ли до нас первая фраза.
"""
import io, ast, types, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

src = io.open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'anamorf', 'stt', 'manager.py'),
    encoding='utf-8').read()
cls = [n for n in ast.parse(src).body
       if isinstance(n, ast.ClassDef) and n.name == 'VadSegmenter'][0]
mod = ast.Module(body=[cls], type_ignores=[]); ast.fix_missing_locations(mod)

KN = {"stt.vad": {"rms_threshold": 0.006, "silence_ms": 600,
                  "min_speech_ms": 420, "max_segment_s": 8,
                  "preroll_ms": 400, "adaptive": True},
      "stt.sample_rate": 16000}
g = {"CFG": types.SimpleNamespace(get=lambda k, d=None: KN.get(k, d)),
     "np": np, "log": types.SimpleNamespace(debug=lambda *a, **k: None,
                                            info=lambda *a, **k: None,
                                            warning=lambda *a, **k: None)}
exec(compile(mod, 'vad', 'exec'), g)

SR = 16000
def tone(sec, amp):                 # грубая имитация речи: шум с огибающей
    n = int(SR*sec)
    x = np.random.default_rng(0).normal(0, amp, n)
    env = 0.5 + 0.5*np.sin(np.linspace(0, sec*2*np.pi*4, n))
    return (x*env*32767).astype(np.int16)

def run(name, chunks):
    V = g['VadSegmenter']()
    got, first = [], None
    for i, c in enumerate(chunks):
        seg = V.push(c)
        if seg is not None:
            got.append(len(seg)/SR)
            if first is None:
                first = i*0.1
    print("%-34s фраз %d, первая на %s, длины %s"
          % (name, len(got),
             ("%.1fс" % first) if first is not None else "—",
             ", ".join("%.1f" % x for x in got[:4]) or "—"))
    return len(got)

frame = int(SR*0.1)
def split(x):
    return [x[i:i+frame] for i in range(0, len(x)-frame, frame)]

speech = tone(2.0, 0.03)            # обычная речь
sil    = (np.zeros(int(SR*1.2))).astype(np.int16)

print("порог 0.0060, адаптация включена\n")
# 1) речь начинается СРАЗУ, без тишины впереди — тот самый случай
run("речь с первого кадра", split(np.concatenate([speech, sil, speech])))
# 2) как надо: сначала тишина, потом речь
run("сначала тишина, потом речь", split(np.concatenate([sil, speech, sil, speech])))
