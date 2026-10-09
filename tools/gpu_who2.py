# -*- coding: utf-8 -*-
"""Кто на самом деле держит видеопамять (05.09.2026).

nvidia-smi на Windows отвечает «[N/A]» без прав администратора. Диспетчер
задач при этом цифры показывает — значит они есть: их отдаёт счётчик
производительности «GPU Process Memory». Здесь мы их и берём."""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = []


def say(*a):
    OUT.append(" ".join(str(x) for x in a))


try:
    from anamorf import system_control as sc
    free, total = sc.gpu_mem()
    say("карта: свободно %s из %s МБ (занято %s)"
        % (free, total, (total - free) if (free and total) else "?"))
    m = sc._gpu_mem_by_pid_windows()
    say("счётчик отдал процессов: %d" % len(m))
    try:
        import psutil
        rows = []
        for pid, mb in m.items():
            try:
                nm = psutil.Process(int(pid)).name()
            except Exception:
                nm = "?"
            rows.append((mb, pid, nm))
        rows.sort(reverse=True)
        say("")
        say("%-8s %-8s %s" % ("МБ", "pid", "процесс"))
        for mb, pid, nm in rows[:25]:
            say("%-8d %-8s %s" % (mb, pid, nm))
        say("")
        say("итого по счётчику: %d МБ" % sum(m.values()))
    except Exception as e:
        say("psutil не дал имён: %s" % e)
        say(str(sorted(m.items(), key=lambda x: -x[1])[:20]))
    say("")
    say("а что видит gpu_top_processes:")
    for nm, pid, mb in sc.gpu_top_processes(12):
        say("   %-8s %-7s %s" % (mb, pid, nm))
except Exception:
    import traceback
    say(traceback.format_exc())

io.open(ROOT / "data" / "gpu_who2.txt", "w",
        encoding="utf-8").write("\n".join(OUT))
