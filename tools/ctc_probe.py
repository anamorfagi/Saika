import os, time, wave, numpy as np, torch
from pathlib import Path
print("ckpts:", [p.name for p in (Path.home()/".cache"/"gigaam").glob("*.ckpt")])
import gigaam
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w:
    SR=w.getframerate(); A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
c=A[8*SR:11*SR]
def direct(m, pcm):
    wav=torch.from_numpy(pcm.astype(np.float32)/32768.0).to(m._device).to(m._dtype).unsqueeze(0)
    ln=torch.full([1], wav.shape[-1], device=m._device)
    with torch.inference_mode():
        enc, el = m.forward(wav, ln); return m._decode(enc, el, ln, False)[0][0]
for name in ("v3_e2e_ctc", "v3_e2e_rnnt"):
    try:
        t0=time.time(); m=gigaam.load_model(name); m=m.to("cuda") if hasattr(m,"to") else m
        print(name, "loaded %.1fs" % (time.time()-t0), "params MB", sum(p.numel()*p.element_size() for p in m.parameters())//2**20)
        direct(m,c)
        best=1e9
        for _ in range(5):
            t0=time.perf_counter(); r=direct(m,c); best=min(best,time.perf_counter()-t0)
        print("  %s: %.0f мс -> %s" % (name, best*1000, r[:90]))
        # 4 chunks of the 30s
        for k in range(0,30,5):
            seg=A[k*SR:(k+5)*SR]; t0=time.perf_counter(); r=direct(m,seg); print("   %2d-%2ds %4.0f мс  %s" % (k,k+5,(time.perf_counter()-t0)*1000, r[:100]))
        del m; torch.cuda.empty_cache()
    except Exception as e:
        print(name, "FAIL", repr(e)[:300])
