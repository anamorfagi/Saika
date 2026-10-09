# -*- coding: utf-8 -*-
"""Проверка: включает ли --context-shift переиспользование префикса.

Поднимает llama-server на ОТДЕЛЬНОМ порту, целиком на процессоре (-ngl 0)
и с крошечным окном, читает первые строки его лога и гасит. Видеопамять
не трогается вовсе — нас интересуют только сообщения при загрузке модели.
"""
import io
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = []


def say(*a):
    OUT.append(" ".join(str(x) for x in a))


def run(tag, extra):
    from anamorf.llm import llamacpp
    mp = llamacpp.find_model()
    log = ROOT / "data" / f"probe_{tag}.log"
    cmd = [str(llamacpp.binary()), "-m", mp, "--host", "127.0.0.1",
           "--port", "8779", "--ctx-size", "2048", "-ngl", "0",
           "--parallel", "1", "--jinja", "-fa", "on",
           "--cache-reuse", "256"] + extra
    say(f"--- {tag}: {' '.join(extra) or '(без доп. флагов)'}")
    f = io.open(log, "w", encoding="utf-8")
    p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        for _ in range(90):
            time.sleep(1)
            try:
                t = io.open(log, encoding="utf-8", errors="ignore").read()
            except Exception:
                t = ""
            if "model loaded" in t or "initializing, n_slots" in t:
                break
    finally:
        try:
            p.terminate()
            p.wait(timeout=20)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
        try:
            f.close()
        except Exception:
            pass
    t = io.open(log, encoding="utf-8", errors="ignore").read()
    hit = [l for l in t.splitlines()
           if "cache_reuse" in l or "context shift" in l.lower()
           or "context_shift" in l or "n_ctx_slot" in l or "kv_unified" in l]
    if hit:
        for l in hit:
            say("   " + l.strip()[:200])
    else:
        say("   (ни одной строки про кэш — сервер не дошёл до загрузки?)")
        say("   хвост: " + " | ".join(t.splitlines()[-3:])[:300])


try:
    run("plain", [])
    run("cshift", ["--context-shift"])
    run("cshift_kvu", ["--context-shift", "--kv-unified"])
except Exception:
    import traceback
    say(traceback.format_exc())
io.open(ROOT / "data" / "probe_flags.txt", "w",
        encoding="utf-8").write("\n".join(OUT))
