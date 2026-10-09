import time, numpy as np, torch
t0=time.time()
pcm, sr = tts.preview(None, "Проверка голоса после переезда на карту.")
a=np.frombuffer(pcm, dtype=np.int16) if isinstance(pcm,(bytes,bytearray)) else np.asarray(pcm)
print("tts ok: %.1fs, %.2fs audio, sr %s, peak %d" % (time.time()-t0, a.size/float(sr), sr, int(np.abs(a).max()) if a.size else -1))
print("alloc", round(torch.cuda.memory_allocated()/2**30,2), "reserved", round(torch.cuda.memory_reserved()/2**30,2))
print("python_who:", _python_who(34504))
