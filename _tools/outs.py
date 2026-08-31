import io
OUT = r"E:\Loading\_atlas_tmp\outs.txt"
def w(m):
    with io.open(OUT,"a",encoding="utf-8") as f: f.write(m+"\n")
io.open(OUT,"w",encoding="utf-8").write("")
try:
    import sounddevice as sd
    seen=set()
    for i,d in enumerate(sd.query_devices()):
        if d.get("max_output_channels",0)>0:
            nm=d["name"]
            if nm in seen: continue
            seen.add(nm)
            w("выход [%d] %s | api=%s" % (i,nm,sd.query_hostapis(d["hostapi"])["name"]))
except Exception as e:
    w("ошибка %r"%e)
