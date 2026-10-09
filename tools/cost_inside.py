import time, wave, numpy as np, torch
from anamorf.stt import engines as E
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w:
    SR=w.getframerate(); A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
c=A[8*SR:11*SR]
eng=stt.instances["gigaam"]; m=eng.model
def t(label, fn, n=5):
    best=1e9; out=None
    for _ in range(n):
        t0=time.perf_counter(); out=fn(); best=min(best,time.perf_counter()-t0)
    print("  %-36s %6.0f мс" % (label, best*1000)); return out
def direct(pcm):
    wav=torch.from_numpy(pcm.astype(np.float32)/32768.0).to(m._device).to(m._dtype).unsqueeze(0)
    ln=torch.full([1], wav.shape[-1], device=m._device)
    with torch.inference_mode():
        enc, el = m.forward(wav, ln)
        return m._decode(enc, el, ln, False)[0][0]
print("SR", SR, "device", m._device)
eng.transcribe(c, SR); direct(c)
r1=t("engine.transcribe (файл)", lambda: eng.transcribe(c, SR))
r2=t("прямо из памяти", lambda: direct(c))
t("  forward только", lambda: m.forward(torch.from_numpy(c.astype(np.float32)/32768.0).to(m._device).unsqueeze(0), torch.full([1], c.size, device=m._device)))
t("весь transcribe_segment", lambda: stt.transcribe_segment(c))
print("файл:", r1[:80]); print("память:", r2[:80])
