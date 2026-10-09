# -*- coding: utf-8 -*-
"""Фронтенд (компрессор/лимитер) — помогает или вредит? GigaAM и whisper, сырой vs prepare."""
import wave, numpy as np, re, time
from pathlib import Path
ROOT=Path(r"C:\AI\Saika"); SR=16000
def norm(t): return [x for x in re.findall(r"[а-яё]+", (t or "").lower()) if len(x)>1]
def refwords(off, dur):
    ref={}
    for ln in open(ROOT/"slux_test"/"snailkik_dnk"/"transkrib.txt", encoding="utf-8"):
        m=re.match(r"(\d+):(\d\d)", ln)
        if not m: continue
        t=int(m.group(1))*60+int(m.group(2))-off
        if 0<=t<dur: ref.setdefault(int(t//10), []).extend(norm(re.sub(r"\[[^\]]*\]"," ",re.sub(r"^\S+\s*(минут\w*\s*\d*\s*)?секунд\w*","",ln))))
    return ref
from anamorf.stt import frontend as fe
FC=CFG.get("stt.frontend",{}) or {}
eng=stt.instances[stt.current_name]
wh=stt._get("faster_whisper")
def giga(x): return eng._transcribe_direct(np.clip(x,-32767,32767).astype(np.int16)) or ""
def whis(x): return wh.transcribe(np.clip(x,-32767,32767).astype(np.int16), SR) or ""
def bench(A, off, dur, label, fn, prep):
    ref=refwords(off, dur); got={}; tt=0; t=0.0; n=0
    while t+2.5<=dur:
        seg=A[int(t*SR):int((t+2.5)*SR)]
        x=fe.prepare(seg, SR, FC) if prep else seg
        t0=time.perf_counter(); txt=fn(x); tt+=time.perf_counter()-t0; n+=1
        got.setdefault(int(t//10), set()).update(norm(txt)); t+=1.25
    hit=miss=0
    for b,r in ref.items():
        g=got.get(b,set())|got.get(b-1,set())|got.get(b+1,set()); h=sum(1 for w in r if w in g); hit+=h; miss+=len(r)-h
    print("%-28s %-8s %-9s найдено %3d/%3d = %5.1f%%  %4.0f мс/кусок" % (label, fn.__name__, "prepare" if prep else "сырой", hit, hit+miss, 100*hit/max(1,hit+miss), 1000*tt/max(1,n)))
with wave.open(str(ROOT/"data"/"first30.wav"),"rb") as w: A=np.frombuffer(w.readframes(w.getnframes()), np.int16)
with wave.open(str(ROOT/"data"/"snailkick.wav"),"rb") as w: B=np.frombuffer(w.readframes(w.getnframes()), np.int16)
for fn in (giga, whis):
    for prep in (False, True):
        bench(A, 0, 22, "начало 0-22", fn, prep)
        bench(B, 22*60, 90, "диалог 22:00-23:30", fn, prep)

# СОЮЗ ДВУХ УШЕЙ: объединение слов giga(сырой) + whisper(prepare) на тех же кусках
def bench2(A, off, dur, label):
    ref=refwords(off, dur); got={}; t=0.0
    while t+2.5<=dur:
        seg=A[int(t*SR):int((t+2.5)*SR)]
        ws=set(norm(giga(seg)))|set(norm(whis(fe.prepare(seg, SR, FC))))
        got.setdefault(int(t//10), set()).update(ws); t+=1.25
    hit=miss=0
    for b,r in ref.items():
        g=got.get(b,set())|got.get(b-1,set())|got.get(b+1,set()); h=sum(1 for w in r if w in g); hit+=h; miss+=len(r)-h
    print("%-28s СОЮЗ giga+whisper       найдено %3d/%3d = %5.1f%%" % (label, hit, hit+miss, 100*hit/max(1,hit+miss)))
bench2(A, 0, 22, "начало 0-22")
bench2(B, 22*60, 90, "диалог 22:00-23:30")
