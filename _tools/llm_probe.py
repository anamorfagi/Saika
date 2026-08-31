# -*- coding: utf-8 -*-
"""Одна короткая проба мозга: поднялся ли llama-server с рабочим окном."""
import io, time, urllib.request
out = io.open(r"C:\AI\Saika\_tools\llm_probe.txt", "w", encoding="utf-8")
t0 = time.time()
try:
    req = urllib.request.Request(
        "http://127.0.0.1:8765/api/chat_text",
        data="Ответь одним словом: работает".encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=180) as r:
        out.write("ОТВЕТ за %.1fс: %s\n" % (time.time() - t0,
                                            r.read().decode("utf-8", "ignore")[:400]))
except Exception as e:
    out.write("ОШИБКА за %.1fс: %r\n" % (time.time() - t0, e))
out.close()
print("ok")
