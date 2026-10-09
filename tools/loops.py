import soundcard as sc, numpy as np, time
print("default speaker:", sc.default_speaker().name)
mics=[m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
for m in mics:
    try:
        with m.recorder(samplerate=16000, channels=1) as r:
            x=np.concatenate([np.asarray(r.record(numframes=1600)).ravel() for _ in range(8)])
        print("%-60s peak %.4f rms %.4f" % (m.name[:60], float(np.abs(x).max()), float(np.sqrt(np.mean(x**2)))))
    except Exception as e: print(m.name[:60], "ERR", str(e)[:80])
