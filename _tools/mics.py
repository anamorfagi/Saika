# -*- coding: utf-8 -*-
"""Какие входы видит система и что выбрано сейчас."""
import io, json, urllib.request
OUT = r"E:\Loading\_atlas_tmp\mics.txt"
def w(m):
    with io.open(OUT, "a", encoding="utf-8") as f: f.write(m + "\n")
io.open(OUT, "w", encoding="utf-8").write("")
try:
    r = urllib.request.urlopen("http://127.0.0.1:8765/api/mic", timeout=6)
    d = json.loads(r.read().decode("utf-8"))
    w("ВЫБРАН: %s" % json.dumps(d.get("current") or d.get("device") or "?", ensure_ascii=False))
    for k, v in d.items():
        if k in ("devices", "list", "inputs"):
            for i, dev in enumerate(v if isinstance(v, list) else []):
                w("  [%d] %s" % (i, json.dumps(dev, ensure_ascii=False)[:200]))
        else:
            w("%s = %s" % (k, str(v)[:200]))
except Exception as e:
    w("ошибка API: %r" % e)
try:
    import sounddevice as sd
    w("\n--- все устройства (sounddevice) ---")
    for i, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) > 0:
            w("  вход [%d] %s (каналов %d)" % (i, dev["name"], dev["max_input_channels"]))
    w("--- выходы ---")
    for i, dev in enumerate(sd.query_devices()):
        if dev.get("max_output_channels", 0) > 0:
            w("  выход [%d] %s" % (i, dev["name"]))
except Exception as e:
    w("sounddevice: %r" % e)
