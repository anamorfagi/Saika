"""ДИАГНОСТИКА РЕСУРСОВ ИЗНУТРИ (ядро v2).

Сайка запускается от администратора, снаружи её не профилировать
(py-spy: «отказано в доступе»). Поэтому замер — изнутри процесса:
CPU каждого потока за окно N секунд + кто из детей процесса сколько ест.
GET /api/diag/threads?sec=3
"""
import threading
import time


def threads(sec: float = 3.0) -> dict:
    import psutil
    p = psutil.Process()
    names = {t.native_id: t.name for t in threading.enumerate()}
    a = {t.id: t.user_time + t.system_time for t in p.threads()}
    c0 = time.time()
    time.sleep(sec)
    b = {t.id: t.user_time + t.system_time for t in p.threads()}
    dt = time.time() - c0
    rows = []
    for tid, v in b.items():
        used = v - a.get(tid, v)
        if used > 0.005:
            rows.append({"thread": names.get(tid, f"native-{tid}"),
                         "cpu_pct_of_core": round(100 * used / dt, 1)})
    rows.sort(key=lambda r: -r["cpu_pct_of_core"])
    kids = []
    for ch in p.children(recursive=True):
        try:
            kids.append({"pid": ch.pid, "name": ch.name(),
                         "cpu_pct": ch.cpu_percent(0.5),
                         "rss_gb": round(ch.memory_info().rss / 2**30, 2)})
        except Exception:
            pass
    return {"process_cpu_cores": round(sum(r["cpu_pct_of_core"] for r in rows) / 100, 2),
            "rss_gb": round(p.memory_info().rss / 2**30, 2),
            "threads": rows[:25], "children": kids}
