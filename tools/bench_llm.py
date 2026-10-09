# -*- coding: utf-8 -*-
"""Честный замер скорости движка, без шума Сайки (05.09.2026).

llama-bench считает prefill (pp) и генерацию (tg) сам, своим процессом.
Нужен, чтобы отделить «модель медленная» от «ей не дают видеокарту»."""
import io
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = []


def say(*a):
    OUT.append(" ".join(str(x) for x in a))


try:
    from anamorf.llm import llamacpp
    from anamorf import system_control as sc
    mp = llamacpp.find_model()
    exe = Path(llamacpp.binary()).parent / "llama-bench.exe"
    free, total = sc.gpu_mem()
    say("перед замером: свободно %s из %s МБ" % (free, total))
    say("модель: %s" % mp)
    say("")
    for tag, extra in (
            ("f16 без флага fa", ["-ngl", "999"]),
            ("f16 + fa", ["-ngl", "999", "-fa", "1"]),
            ("q8/q8 + fa", ["-ngl", "999", "-ctk", "q8_0", "-ctv", "q8_0",
                            "-fa", "1"]),
            ("q8/q4 + fa", ["-ngl", "999", "-ctk", "q8_0", "-ctv", "q4_0",
                            "-fa", "1"]),
            ("q8/q8 без fa", ["-ngl", "999", "-ctk", "q8_0", "-ctv", "q8_0"]),
    ):
        cmd = [str(exe), "-m", mp, "-p", "2048", "-n", "64", "-r", "1"] + extra
        say("--- %s: %s" % (tag, " ".join(extra)))
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=420,
                               creationflags=getattr(subprocess,
                                                     "CREATE_NO_WINDOW", 0))
            for line in (r.stdout or "").splitlines():
                if "|" in line and ("pp" in line or "tg" in line
                                    or "model" in line):
                    say("   " + line.strip()[:180])
            if r.returncode:
                say("   код %s; stderr: %s" % (r.returncode,
                                               (r.stderr or "")[-400:]))
        except Exception as e:
            say("   не вышло: %r" % e)
        say("")
    free2, _ = sc.gpu_mem()
    say("после замера: свободно %s МБ" % free2)
except Exception:
    import traceback
    say(traceback.format_exc())

io.open(ROOT / "data" / "bench_llm.txt", "w",
        encoding="utf-8").write("\n".join(OUT))
