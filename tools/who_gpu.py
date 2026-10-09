# -*- coding: utf-8 -*-
"""КТО НА КАРТЕ — ПРЯМО СЕЙЧАС, БЕЗ МОИХ ТОЛКОВАНИЙ (06.09.2026).
Три независимых источника: список процессов Windows (есть ли llama-server
вообще), драйвер CUDA (сколько физически занято), список процессов с
графической памятью от nvidia-smi."""
import subprocess, sys
def sh(c):
    try: return subprocess.run(c, capture_output=True, text=True, timeout=20, shell=True).stdout.strip()
    except Exception as e: return "нет: %r" % e
print("== llama-server в процессах Windows ==")
out = sh('tasklist /FI "IMAGENAME eq llama-server.exe" /FO CSV')
print(out if "llama" in out.lower() else "НЕТ ТАКОГО ПРОЦЕССА")
print("== все процессы с 'llama' или 'ollama' ==")
print(sh('tasklist /FO CSV | findstr /I "llama ollama lmstudio"') or "нет")
print("== CUDA: физически на карте ==")
try:
    import torch
    f,t = torch.cuda.mem_get_info(0)
    print("занято %.2f ГБ из %.2f, свободно %.2f ГБ" % ((t-f)/2**30, t/2**30, f/2**30))
except Exception as e: print("torch:", e)
print("== nvidia-smi, процессы на карте ==")
print(sh("nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader"))
