import wave, numpy as np, torch
with wave.open(r"C:\AI\Saika\data\first30.wav","rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
eng = stt.instances[stt.current_name]; m = eng.model; dec=m.decoding; tok=dec.tokenizer
print("charwise", tok.charwise, "id_to_str sample", [tok.id_to_str(i) for i in (97,18,49,34,35,87,4,41,25,3,13,45,1,2)])
seg=A[int(13.8*16000):int(17.0*16000)]
x=torch.from_numpy(seg.astype(np.float32)/32768).to(m._device).to(m._dtype).unsqueeze(0); ln=torch.full([1],x.shape[-1],device=m._device)
with torch.inference_mode():
    enc, el = m.forward(x, ln); lp = m.head(enc)
    ids = lp[0].argmax(-1).tolist()
fps = len(ids)/ (len(seg)/16000)
words=[]; cur=None; prev=None
for f,i in enumerate(ids):
    if i==dec.blank_id or i==prev: prev=i; continue
    prev=i; s=tok.id_to_str(i)
    if s.startswith("▁") or s==" " or cur is None:
        if cur: words.append(cur)
        cur=[s.replace("▁",""), f/fps, (f+1)/fps]
    else:
        cur[0]+=s; cur[2]=(f+1)/fps
if cur: words.append(cur)
print("fps", fps, "words", [(w, round(a,2), round(b,2)) for w,a,b in words])
