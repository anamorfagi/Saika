# -*- coding: utf-8 -*-
"""Что живая система думает про голоса ПРЯМО СЕЙЧАС."""
import io, json, time, urllib.request, traceback
OUT = r"E:\Loading\_atlas_tmp\diag_voice.txt"
def w(m):
    with io.open(OUT, "a", encoding="utf-8") as f: f.write(m + "\n")
def get(path):
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8765" + path, timeout=6)
        return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ОШИБКА": repr(e)[:200]}
try:
    io.open(OUT, "w", encoding="utf-8").write("=== %s ===\n" % time.strftime("%H:%M:%S"))
    vp = get("/api/voiceprint")
    w("--- /api/voiceprint ---")
    w(json.dumps(vp, ensure_ascii=False, indent=1)[:2600])
    st = get("/status")
    w("--- /status (выжимка) ---")
    for k in ("stt", "stt_engine", "listening", "listen", "mic", "hearing",
              "speaker", "speakers", "vp", "voice", "engine", "rec"):
        if k in st: w("  %s = %s" % (k, str(st[k])[:300]))
    w("  ключи статуса: %s" % ", ".join(list(st.keys())[:40]))
    pts = get("/api/voiceprint/points")
    n = pts.get("points") or pts.get("pts") or []
    w("--- точек в облаке: %s ---" % (len(n) if hasattr(n, "__len__") else n))
except Exception:
    w("ИСКЛЮЧЕНИЕ:\n" + traceback.format_exc())
