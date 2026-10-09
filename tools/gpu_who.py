"""Кто именно занимает видеопамять. Без догадок — список от драйвера."""
import subprocess

q = ("nvidia-smi", "--query-compute-apps=pid,used_memory,process_name",
     "--format=csv,noheader,nounits")
try:
    out = subprocess.run(q, capture_output=True, text=True, timeout=20).stdout.strip()
except Exception as e:
    raise SystemExit(f"nvidia-smi не отозвалась: {e}")

rows = []
for line in out.splitlines():
    parts = [p.strip() for p in line.split(",")]
    if len(parts) >= 3:
        rows.append((int(parts[1]), parts[0], parts[2]))
rows.sort(reverse=True)
total = 0
for mb, pid, name in rows:
    total += mb
    print(f"{mb:6d} МБ  pid {pid:>7}  {name}")
print(f"------ занято процессами: {total} МБ ({total/1024:.1f} ГБ)")

g = subprocess.run(("nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
                    "--format=csv,noheader,nounits"), capture_output=True, text=True, timeout=20)
print("карта всего:", g.stdout.strip())
