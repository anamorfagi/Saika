# -*- coding: utf-8 -*-
"""Проверить, переключается ли мозг с первого нажатия (тем же путём, что кнопка)."""
import io, json, time, urllib.request
B = "http://127.0.0.1:8765"
out = io.open(r"C:\AI\Saika\_tools\llm_pick.txt", "w", encoding="utf-8")

def post(path, obj):
    r = urllib.request.Request(B + path, data=json.dumps(obj).encode("utf-8"),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=120) as f:
        return f.read().decode("utf-8", "ignore")

def get(path):
    with urllib.request.urlopen(B + path, timeout=30) as f:
        return json.loads(f.read().decode("utf-8", "ignore"))

try:
    st = get("/api/models")
    out.write("до: выбрана=%s загружены=%s\n" % (
        (get("/api/status") or {}).get("llm", {}), st.get("loaded")))
except Exception as e:
    out.write("статус: %r\n" % e)
try:
    out.write("клик: %s\n" % post("/api/select",
              {"kind": "model", "value": "Qwen3.5-9B-Q4_K_M",
               "backend": "llamacpp"}))
except Exception as e:
    out.write("клик упал: %r\n" % e)
for i in range(12):
    time.sleep(10)
    try:
        st = get("/api/models")
        cur = (get("/api/status") or {}).get("llm", {})
        out.write("+%3dс выбрана=%s загружены=%s\n" % ((i+1)*10, cur, st.get("loaded")))
        if "Qwen3.5-9B-Q4_K_M" in (st.get("loaded") or []):
            out.write("ЗАГРУЗИЛАСЬ\n"); break
    except Exception as e:
        out.write("+%3dс ошибка %r\n" % ((i+1)*10, e))
out.close()
print("ok")
