# -*- coding: utf-8 -*-
import io, sys, os
sys.path.insert(0, r"C:\AI\Saika\build\ANAMORF-0.2.1\app")
os.environ.setdefault("SAIKA_DATA", r"C:\AI\Saika\build\ANAMORF-0.2.1")
out = io.open(r"C:\AI\Saika\_tools\plan_probe.txt", "w", encoding="utf-8")
try:
    from anamorf import system_control as sc, vramplan as vp
    free, total = sc.gpu_mem()
    out.write("free=%s total=%s\n" % (free, total))
    procs = sc.gpu_top_processes(64)
    out.write("процессов на карте: %d\n" % len(procs))
    for n, p, m in procs[:12]:
        out.write("  %s | pid %s | %s МБ\n" % (n, p, m))
    out.write("own_est(5.2) = %.2f ГБ\n" % vp.own_est_gb(5.2))
    out.write("total_gb(5.2) = %.2f ГБ\n" % vp.total_gb(5.2))
    out.write("plan(5.2) = %r\n" % (vp.plan(5.2),))
except Exception as e:
    import traceback
    out.write(traceback.format_exc())
out.close()
print("ok")
