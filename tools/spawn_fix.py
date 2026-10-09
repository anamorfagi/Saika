import os, subprocess, sys, psutil
from pathlib import Path
ROOT = Path(r"C:\AI\Saika")
pid = None
for p in psutil.process_iter(["name","cmdline"]):
    try:
        cl = " ".join(p.info["cmdline"] or [])
        if "anamorf.main" in cl and "python" in (p.info["name"] or "").lower(): pid = p.pid
    except Exception: pass
print("saika pid", pid, "venv python", sys.executable)
(ROOT/"data"/"pip_fix.lock").write_text("wait", encoding="utf-8")
subprocess.Popen(["cmd", "/c", str(ROOT/"tools"/"pip_fix.cmd"), str(pid), sys.executable],
                 creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)
print("fix spawned")
