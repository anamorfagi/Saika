# -*- coding: utf-8 -*-
import io, json, urllib.request
OUT = r"E:\Loading\_atlas_tmp\mics2.txt"
try:
    r = urllib.request.urlopen("http://127.0.0.1:8765/api/mic", timeout=8)
    d = json.loads(r.read().decode("utf-8"))
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("по умолчанию: %s\n" % d.get("device_default"))
        f.write("примечание: %s\n" % d.get("devices_note", "—"))
        devs = d.get("devices") or []
        f.write("ВСЕГО ВХОДОВ: %d\n" % len(devs))
        for x in devs:
            f.write("  %-46s %s\n" % (x.get("name"),
                    "← по умолчанию" if x.get("default") else ""))
except Exception as e:
    io.open(OUT, "w", encoding="utf-8").write("ошибка: %r" % e)
