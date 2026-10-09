# -*- coding: utf-8 -*-
"""Облачка как их построит вкладка — из data/events.jsonl, без скриншотов.
Правила те же, что в ui/app.html: развод слов по владельцу (words_col),
корзина тона ±3.5 полутона, склейка по дорожке/корзине, смех — последнему
говорившему. Сверка с who_0_20.txt: сколько слов ушло в правильный голос."""
import json, re, math, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
rows = [json.loads(l) for l in (ROOT/"data"/"events.jsonl").read_text("utf-8").splitlines() if l.strip()]
# берём хвост после последнего chat_clear
cut = max((i for i, r in enumerate(rows) if r.get("type") == "chat_clear"), default=-1)
rows = rows[cut+1:]
def norm(t): return [x for x in re.findall(r"[а-яё]+", (t or "").lower()) if len(x) > 1]
LAUGH = re.compile(r"^[\s\-!.,…]*(ха|хе|хи|хах|ахах)[а-яa-z\-!.,… ]*$", re.I)
class Bucket:
    def __init__(s, st, hz, n): s.st=st; s.hz=hz; s.name=f"голос {hz} Гц"; s.id=n
buckets=[]
def bucket(hz):
    st = 12*math.log2(max(hz,1)/110)
    best=None; bd=1e9
    for b in buckets:
        d=abs(st-b.st)
        if d<bd: best,bd=b,d
    if best and bd<=3.5:
        best.st += 0.08*(st-best.st); return best
    b=Bucket(st, round(hz), len(buckets)); buckets.append(b); return b
bubbles=[]   # {"key","name","texts":[], "ts"}
trk={}
last=None
def put(key, name, text, ts, bkey):
    global last
    if last and (last["key"]==key and ts-last["ts"]<15 or (bkey and last.get("bkey")==bkey and ts-last["ts"]<6)):
        last["texts"].append(text); last["ts"]=ts; return
    last={"key":key,"name":name,"texts":[text],"ts":ts,"bkey":bkey}; bubbles.append(last)
for r in rows:
    if r.get("type")!="stt": continue
    ts=r["_ts"]
    parts=[r]
    wc=r.get("words_col")
    if wc and len(wc)>=2:
        groups={}
        for w,hz,c in wc: groups.setdefault(hz,[]).append(w)
        if len(groups)>=2:
            gs=sorted(groups.items(), key=lambda kv:-len(kv[1]))
            secper=(r.get("sec") or 0)/len(wc)
            gs=[g for n,g in enumerate(gs) if n==0 or (len(g[1])>=2 and len(g[1])*secper>=0.4)]
            parts=[] if len(gs)>=2 else [r]
            for n,(hz,ws) in (enumerate(gs) if len(gs)>=2 else []):
                p=dict(r); p["text"]=" ".join(ws); p["tone_hz"]=hz
                if n: p["track_id"]=""; p["speaker"]=""
                parts.append(p)
    for p in parts:
        text=p.get("text") or ""
        if LAUGH.match(text) and len(text)<24 and last and ts-last["ts"]<4:
            last["texts"].append("["+text+"]"); last["ts"]=ts; continue
        who = p.get("speaker") if p.get("speaker") and (p.get("speaker_conf") is None or p.get("speaker_conf")>=.25) else ""
        hz=p.get("tone_hz"); app=p.get("app") or ""
        appk=":"+app if app else ""
        if (not who or p.get("speaker_weak")) and hz:
            tid=p.get("track_id") or p.get("track_pending")
            b=bucket(hz)
            if tid:
                key="trk"+str(tid)+appk; name=trk.setdefault(key,b).name
            else:
                key="v"+str(b.id)+appk; name=b.name
            put(key,name,text,ts,"v"+str(b.id)+appk)
        else:
            put(who or "услышала", who or "услышала", text, ts, "")
print(f"событий stt: {sum(1 for r in rows if r.get('type')=='stt')}, облачков: {len(bubbles)}, корзин тона: {len(buckets)}")
for b in bubbles:
    print(f"  [{b['name']}]  " + " | ".join(b["texts"]))
# сверка с разметкой владельца
gt=[]
for ln in (ROOT/"slux_test"/"snailkik_dnk"/"who_0_20.txt").read_text("utf-8").splitlines():
    if ln.startswith("#") or "|" not in ln: continue
    who,txt=ln.split("|",1); txt=txt.split("#")[0]
    gt.append((who.strip(), norm(re.sub(r"\[[^\]]*\]","",txt))))
# каждое слово облачка -> какому голосу разметки оно принадлежит (по вхождению слова)
word_owner={}
for who,ws in gt:
    for w in ws: word_owner.setdefault(w,set()).add(who)
print("\nСВЕРКА: облачко -> голоса разметки, к которым относятся его слова")
mixed=0; total=0
for b in bubbles:
    ws=norm(" ".join(b["texts"])); owners={}
    for w in ws:
        for o in word_owner.get(w,()): owners[o]=owners.get(o,0)+1
    if not owners: continue
    total+=1
    top=max(owners.values()); others=sum(owners.values())-top
    if len(owners)>1 and others>=2: mixed+=1
    print(f"  {b['name']:>16}: {owners}  {'СМЕШАНО' if len(owners)>1 and others>=2 else ''}")
print(f"\nоблачков со словами эталона {total}, смешанных (>=2 чужих слов) {mixed}; голосов в разметке 4, корзин у нас {len(buckets)}")
