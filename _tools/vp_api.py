# -*- coding: utf-8 -*-
import io, json, urllib.request
out = io.open(r"C:\AI\Saika\_tools\vp_api.txt", "w", encoding="utf-8")
for port in (8765,):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/voiceprint" % port, timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
        sp = d.get("speakers")
        out.write("порт %d: тип speakers=%s, всего=%s\n" % (port, type(sp).__name__, len(sp or [])))
        if isinstance(sp, dict):
            for k, v in list(sp.items())[:20]:
                out.write("  %s: heard=%s color=%s plo=%s phi=%s\n" %
                          (k, v.get("heard"), v.get("color"), v.get("pitch_lo"), v.get("pitch_hi")))
        break
    except Exception as e:
        out.write("порт %d: %r\n" % (port, e))
out.close()
print("ok")
