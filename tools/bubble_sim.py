# -*- coding: utf-8 -*-
import sys, io; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
"""Таймлайн облачек по журналу событий: как вкладка ключует реплики (спектр+канал+дорожка+логика) и что сказала модель по смыслу."""
import json, time, math, sys
rows=[json.loads(l) for l in open("data/events.jsonl",encoding="utf-8") if l.strip()]
now=time.time(); span=float(sys.argv[1]) if len(sys.argv)>1 else 240
ev=[r for r in rows if now-r.get("_ts",0)<span]
who={r["pid"]:(r.get("who"),r.get("name")) for r in ev if r.get("type")=="stt_who"}
B=[]; TRKV={}; APPLAST={}; GLUE={"key":None,"at":0,"app":"","tid":"","last":""}
def sx_of(r):
    hz=r.get("tone_hz") or 0
    return 'м' if hz<165 else (r.get("sex") if r.get("sex_sure") else '?')
def bucket(hz,sx,vtl):
    st=12*math.log2(max(hz,1)/110); best=None; bd=1e9
    for v in B:
        d=min(abs(st-v["st"]),abs(st-12-v["st"])+1.5,abs(st+12-v["st"])+1.5)/3.5
        if vtl and v["vtl"]: d=0.6*d+0.4*abs(vtl-v["vtl"])/1.2
        if sx!='?' and v["sex"]!='?' and sx!=v["sex"]: d+=2
        if d<bd: best,bd=v,d
    if best and bd<=1.0:
        best["st"]+=0.08*(st-best["st"])
        if vtl: best["vtl"]=best["vtl"]+0.1*(vtl-best["vtl"]) if best["vtl"] else vtl
        return best
    v={"st":st,"vtl":vtl or 0,"sex":sx,"key":"v%d"%len(B),"name":"голос %d Гц"%round(hz)}; B.append(v); return v
out=[]
for r in ev:
    if r.get("type")!="stt": continue
    text=r.get("text") or ""; ts=r["_ts"]*1000; hz=r.get("tone_hz") or 0; app=r.get("app") or ""
    letters="".join(ch for ch in text.lower() if 'а'<=ch<='я' or ch=='ё')
    import re
    if letters and ((len(set(letters))<=2 and (re.search(r"([а-яё])\1{2,}",text,re.I) or len(letters)<=1)) or (len(set(letters))<=3 and len(letters)>=5 and re.search(r"([а-яё])\1{3,}",text,re.I))):
        out.append((ts,"~",text[:40],hz,r.get("vtl_cm"),who.get(r["pid"]))); continue
    if re.match(r"^[\s\-!.,…]*(ха|хе|хи|хах|ахах)[а-яa-z\-!.,… ]*$",text,re.I) and len(text)<24 and GLUE["key"] and ts-GLUE["at"]<4000:
        out.append((ts,"смех→"+GLUE["key"],text[:40],hz,r.get("vtl_cm"),who.get(r["pid"]))); GLUE["at"]=ts; continue
    sx=sx_of(r); tid=r.get("track_id") or r.get("track_pending"); appk=":"+app if app else ""
    ckey=None; vb=None
    al=APPLAST.get(app)
    if app and not tid and al and ts-al["at"]<8000: ckey=al["key"]; vb=al["vb"]; al["at"]=ts
    if ckey is None:
        tvb=TRKV.get(str(tid)+appk) if tid else None
        if tvb and sx!='?' and tvb["sex"]!='?' and tvb["sex"]!=sx: tvb=None
        if tvb: vb=tvb; ckey=vb["key"]+appk
        else:
            vb=bucket(hz,sx,r.get("vtl_cm")); ckey=vb["key"]+appk
            if tid: TRKV.setdefault(str(tid)+appk, vb)
    # логика слов
    prev=GLUE["last"]; fresh=GLUE["key"] and ts-GLUE["at"]<3000
    cont=fresh and prev and not re.search(r"[.!?…]$",prev) and re.match(r"^(\.\.\.|…|[а-яёa-z])",text.strip())
    nw=len(text.split()); answer=fresh and prev.endswith("?") and nw<=3
    logic=""
    if cont and ckey!=GLUE["key"]: ckey=GLUE["key"]; logic="продолж"
    elif answer and ckey==GLUE["key"]: GLUE["at"]=0; logic="ответ"
    glued = GLUE["key"]==ckey and ts-GLUE["at"]<15000 or (app and GLUE["app"]==app and ts-GLUE["at"]<6000 and (not tid or not GLUE["tid"] or str(tid)==str(GLUE["tid"])))
    mark = ("  +" if glued else "NEW") 
    out.append((ts,mark+" "+ckey+(" "+logic if logic else ""),text[:44],hz,r.get("vtl_cm"),who.get(r["pid"])))
    if not glued: GLUE["key"]=ckey; GLUE["app"]=app; GLUE["tid"]=str(tid) if tid else ""
    GLUE["at"]=ts; GLUE["last"]=text.strip()
    if app: APPLAST[app]={"key":ckey,"vb":vb,"at":ts}
t0=out[0][0] if out else 0
for ts,k,txt,hz,vtl,w in out:
    print("%6.1f %-22s %4s %5s %-8s | %s" % ((ts-t0)/1000, k, hz, vtl, (w[0] or "")+(("/"+w[1]) if w and w[1] else "") if w else "", txt))
print("корзин:", len(B), [ (v["key"],v["sex"],round(v["vtl"],1)) for v in B])
