import io
OUT=r"E:\Loading\_atlas_tmp\audlibs.txt"
def w(m):
    with io.open(OUT,"a",encoding="utf-8") as f: f.write(str(m)+"\n")
io.open(OUT,"w",encoding="utf-8").write("")
import sounddevice as sd
w("sounddevice %s | portaudio %s" % (sd.__version__, sd.get_portaudio_version()))
for mod in ("soundcard","pyaudiowpatch","pyaudio"):
    try:
        __import__(mod); w("%s: ЕСТЬ" % mod)
    except Exception as e:
        w("%s: нет" % mod)
