# -*- coding: utf-8 -*-
"""Снять СТАРОГО сторожа: он крутится с прежним кодом и воскрешает прогу."""
import io, os
out = io.open(r"C:\AI\Saika\_tools\wd_kill.txt", "w", encoding="utf-8")
killed = []
try:
    import psutil
    me = os.getpid()
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if p.info["pid"] == me:
                continue
            cl = " ".join(p.info.get("cmdline") or []).lower()
            if "watchdog_saika" in cl:
                out.write("нашёл сторожа: pid %s | %s\n" % (p.info["pid"], cl[:160]))
                p.kill()
                killed.append(p.info["pid"])
        except Exception as e:
            out.write("  пропуск pid %s: %r\n" % (p.info.get("pid"), e))
except Exception as e:
    out.write("psutil: %r\n" % e)
out.write("снято сторожей: %d %s\n" % (len(killed), killed))
out.close()
print("ok")
