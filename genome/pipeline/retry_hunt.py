# -*- coding: utf-8 -*-
"""Переделать неудачное исследование: тот же персонаж, та же карточка, новый заход.

Движок сам читает прошлый прогон, разбирает, что не сработало, и заходит иначе.
Новый персонаж при этом не заводится — правится та же карточка.
"""
import json
import pathlib
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ЗДЕСЬ = pathlib.Path(__file__).resolve().parent
БАЗА = "http://127.0.0.1:8770"
ПРОГОН = sys.argv[1]
ПРОВАЙДЕР = sys.argv[2] if len(sys.argv) > 2 else "proxyapi"
МОДЕЛЬ = sys.argv[3] if len(sys.argv) > 3 else "deepseek/deepseek-v3.2"
ЖДАТЬ = int(sys.argv[4]) if len(sys.argv) > 4 else 900


def дай(путь):
    with urllib.request.urlopen(БАЗА + путь, timeout=30) as r:
        return json.loads(r.read())


def шли(путь, тело):
    req = urllib.request.Request(БАЗА + путь, data=json.dumps(тело).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def ключ(pid):
    for файл in (ЗДЕСЬ.parent / "api_keys.json", ЗДЕСЬ.parent.parent / "secrets.json"):
        if not файл.exists():
            continue
        try:
            d = json.loads(файл.read_text(encoding="utf-8"))
        except Exception:
            continue
        for место in (d, d.get("keys") or {}, d.get("llm") or {},
                      (d.get("llm") or {}).get("cloud_keys") or {}):
            зн = место.get(pid) if isinstance(место, dict) else None
            if isinstance(зн, dict):
                зн = зн.get("key") or зн.get("value")
            if isinstance(зн, str) and len(зн) > 12:
                return зн
    return ""


было = json.loads((ЗДЕСЬ.parent / "chars" / ПРОГОН / "state.json").read_text(encoding="utf-8"))
запрос = ((было.get("card") or {}).get("meta") or {}).get("research", {}).get("query", "")
print("переделываю:", ПРОГОН)
print("  прошлое состояние:", было.get("state"), "· улик", было.get("evidence_count"),
      "· источников", len(было.get("sources") or []))
print("  запрос:", запрос)

последняя = дай("/jobs/latest")
if последняя.get("active") and последняя.get("id"):
    шли("/jobs/%s/cancel" % последняя["id"], {})
    time.sleep(2)

cfg = {"provider": ПРОВАЙДЕР, "model": МОДЕЛЬ}
k = ключ(ПРОВАЙДЕР)
if k:
    cfg["key"] = k
начало = шли("/jobs", {"query": запрос, "origin": "", "retry": ПРОГОН, "cfg": cfg})
job = начало["id"]
print("запущено:", job, "· тот же идентификатор:", job == ПРОГОН)

видано, конец = 0, time.time() + ЖДАТЬ
while time.time() < конец:
    time.sleep(6)
    try:
        s = дай("/jobs/%s?after=%d" % (job, видано))
    except Exception as e:
        print("опрос не прошёл:", str(e)[:120]); continue
    for e in s.get("events", []):
        видано += 1
        строка = "%s · %s · %s" % (e.get("at", "")[11:19], e.get("stage", ""), e.get("message", ""))
        if e.get("replicas") is not None:
            строка += "  [реплик %s]" % e["replicas"]
        print(строка[:300])
    if s.get("done"):
        print("\nстало:", s.get("state"), "· источников", len(s.get("sources", [])),
              "· улик", s.get("evidence_count"))
        break
else:
    print("\n(ещё идёт)")
