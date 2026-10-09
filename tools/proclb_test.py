import subprocess, time, numpy as np, psutil, wave
EXE = r"C:\AI\Saika\tools\proclb\bin\proclb.exe"
pids = [p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == "discord.exe"]
print("discord pids:", pids)
if not pids: raise SystemExit
# корень дерева: тот Discord.exe, чей родитель — не Discord
def root(pids):
    for q in pids:
        try:
            pp = psutil.Process(q).parent()
            if pp is None or (pp.name() or "").lower() != "discord.exe": return q
        except Exception: pass
    return pids[0]
pid = root(pids); print("root pid", pid)
def grab(args, sec):
    p = subprocess.Popen([EXE] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    t0 = time.time(); chunks = []
    while time.time() - t0 < sec:
        d = p.stdout.read(3200)
        if not d: break
        chunks.append(d)
    p.kill(); err = p.stderr.read().decode("utf-8", "replace")[:200]
    a = np.frombuffer(b"".join(chunks), np.int16)
    return a, err
import threading
res = {}
def run(k, args):
    res[k] = grab(args, 12)
ts = [threading.Thread(target=run, args=("discord", [str(pid), "include"])), threading.Thread(target=run, args=("rest", [str(pid), "exclude"]))]
import json, urllib.request
r = urllib.request.Request("http://127.0.0.1:8765/api/media/cmd", data=json.dumps({"op":"play","pos":30,"len":10}).encode(), headers={"Content-Type":"application/json"})
print(json.load(urllib.request.urlopen(r, timeout=10))["sent"]["tab"])
[t.start() for t in ts]; [t.join() for t in ts]
for k, (a, err) in res.items():
    print("%-8s %s | %.1fс, rms %.4f peak %.3f" % (k, err.strip(), len(a)/16000, float(np.sqrt(np.mean((a/32768.0)**2))) if a.size else 0, float(np.abs(a).max()/32768.0) if a.size else 0))
    if a.size:
        w = wave.open(r"C:\AI\Saika\data\proclb_%s.wav" % k, "wb"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(a.tobytes()); w.close()
