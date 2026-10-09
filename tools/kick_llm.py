"""Снять зависший llama-server: слот занят навсегда, генерация не доходит.

Штатный ensure_running этого не видит: /health отвечает «ok», значит для
него сервер здоров. Здоровье процесса и способность генерировать — разные
вещи, и различать их приходится снаружи.
"""
import subprocess
import time
import urllib.request

def alive():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8771/health", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False

print("до:", "жив" if alive() else "нет")
subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"],
               capture_output=True, timeout=20)
for _ in range(12):
    if not alive():
        break
    time.sleep(0.5)
print("после:", "жив" if alive() else "снят")
