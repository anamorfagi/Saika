# -*- coding: utf-8 -*-
import io, subprocess
out = io.open(r"C:\AI\Saika\_tools\gpu.txt", "w", encoding="utf-8")
try:
    r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free",
                        "--format=csv,noheader"], capture_output=True, text=True, timeout=20)
    out.write("КАРТА: " + (r.stdout or r.stderr).strip() + "\n\n")
    r2 = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory,process_name",
                         "--format=csv,noheader"], capture_output=True, text=True, timeout=20)
    out.write("КТО ДЕРЖИТ ПАМЯТЬ:\n" + (r2.stdout or r2.stderr).strip() + "\n")
except Exception as e:
    out.write("nvidia-smi: %r\n" % e)
out.close()
print("ok")
