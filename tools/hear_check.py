# -*- coding: utf-8 -*-
"""Проверка слуха после правок 05.09: призраки голосов, состояние
конвейера, запуск куска ролика 10:00-13:00 для замера.

Запускается через управляющий канал (runpy) — то есть отдельным
процессом на той же машине, поэтому до сервера ходит по http, а не
лезет в его память."""
import io, os, json, sys, time
from pathlib import Path
from urllib import request

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8765"
O = []
def say(*a): print(" ".join(str(x) for x in a)); O.append(" ".join(str(x) for x in a))

def api(path, post=False):
    try:
        req = request.Request(BASE + path, method="POST" if post else "GET")
        with request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": repr(e)}

DO = set(sys.argv[1:]) or {"ghosts", "hear"}

if "ghosts" in DO:
    d = api("/api/voiceprint/purge_ghosts?dry=1", post=True)
    say("ПРИЗРАКИ (только показать):", json.dumps(d, ensure_ascii=False)[:900])
if "purge" in DO:
    d = api("/api/voiceprint/purge_ghosts", post=True)
    say("ПРИЗРАКИ УБРАНЫ:", json.dumps(d, ensure_ascii=False)[:900])
if "hear" in DO:
    say("СЛУХ:", json.dumps(api("/api/hear"), ensure_ascii=False)[:600])
    say("СЦЕНА:", json.dumps(api("/api/hearing/scene"), ensure_ascii=False)[:600])
if "play" in DO:
    mp4 = ROOT / "slux_test" / "snailkik_dnk" / "ДЯДЯ ОТЦА МАТЕРИ СЫНА _ СМОТРИМ ДНК.mp4"
    wav = ROOT / "data" / "bench_1000_1300.wav"
    t = wav if wav.exists() else mp4
    try:
        os.startfile(str(t)); say("играю:", t.name)
    except Exception as e:
        say("не запустилось:", repr(e))

io.open(ROOT / "data" / "hear_check.txt", "w", encoding="utf-8").write("\n".join(O))
