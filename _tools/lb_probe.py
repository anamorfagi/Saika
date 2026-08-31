import io, inspect, subprocess, sys
OUT=r"E:\Loading\_atlas_tmp\lb.txt"
def w(m):
    with io.open(OUT,"a",encoding="utf-8") as f: f.write(str(m)+"\n")
io.open(OUT,"w",encoding="utf-8").write("")
import sounddevice as sd
try: w("WasapiSettings: %s" % inspect.signature(sd.WasapiSettings.__init__))
except Exception as e: w("сигнатура: %r"%e)
w("--- ставлю soundcard ---")
try:
    r=subprocess.run([sys.executable,"-m","pip","install","--quiet","soundcard"],
                     capture_output=True,text=True,timeout=300,
                     creationflags=0x08000000)
    w("rc=%s %s"%(r.returncode,(r.stderr or "")[-300:]))
except Exception as e: w("pip: %r"%e)
try:
    import soundcard as sc
    w("soundcard ОК, версия %s"%getattr(sc,"__version__","?"))
    for m in sc.all_microphones(include_loopback=True):
        w("   вход: %s | loopback=%s"%(m.name,getattr(m,"isloopback",None)))
except Exception as e:
    w("soundcard: %r"%e)
