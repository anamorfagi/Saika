"""Жив ли llama-server и отвечает ли он вообще.

Проверяем три вещи по отдельности, потому что «мозги готовы» в интерфейсе
означает лишь «процесс на порту откликнулся», а не «генерация идёт»:
  1) /health — поднят ли сервер;
  2) /slots — не занят ли слот навсегда зависшим запросом;
  3) короткая генерация с жёстким таймаутом — доходит ли ХОТЬ ОДИН токен.
"""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8771"


def get(path, timeout=5):
    t0 = time.time()
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return r.status, r.read(400).decode("utf-8", "replace"), time.time() - t0
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", time.time() - t0


for p in ("/health", "/slots", "/props"):
    s, b, dt = get(p)
    print(f"{p}: {s} за {dt:.1f}с -> {b[:220]}")

body = json.dumps({"model": "x", "messages": [{"role": "user", "content": "скажи одно слово"}],
                   "max_tokens": 8, "stream": False}).encode()
req = urllib.request.Request(BASE + "/v1/chat/completions", data=body,
                             headers={"Content-Type": "application/json"})
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=45) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    txt = d["choices"][0]["message"]["content"]
    print(f"генерация: ОК за {time.time()-t0:.1f}с -> {txt!r}")
except Exception as e:
    print(f"генерация: НЕ ДОШЛА за {time.time()-t0:.1f}с -> {type(e).__name__}: {e}")
