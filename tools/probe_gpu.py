# -*- coding: utf-8 -*-
"""Сколько видеопамяти занято и кем."""
import subprocess
r=subprocess.run(["nvidia-smi","--query-gpu=name,memory.total,memory.used,temperature.gpu,power.draw,power.limit",
                  "--format=csv,noheader"],capture_output=True,text=True,timeout=60)
print("КАРТА:", r.stdout.strip() or r.stderr[:200])
r2=subprocess.run(["nvidia-smi","--query-compute-apps=pid,process_name,used_memory",
                   "--format=csv,noheader"],capture_output=True,text=True,timeout=60)
print("--- кто занял память ---")
print(r2.stdout.strip() or "(никто)")
try:
    import torch
    print("--- torch ---")
    print("cuda:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("занято этим процессом: %.2f ГБ, зарезервировано %.2f ГБ"%(
            torch.cuda.memory_allocated()/2**30, torch.cuda.memory_reserved()/2**30))
except Exception as e:
    print("torch:", e)
