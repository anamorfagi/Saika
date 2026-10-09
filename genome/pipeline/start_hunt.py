# -*- coding: utf-8 -*-
"""Запустить исследование самому и показать, что реально произошло.

Отдельный скрипт, потому что владелец не должен нажимать кнопку в студии
ради проверки моей же правки. Здесь: снять зависшую работу, поставить новую,
дождаться первых событий и напечатать их — чтобы было видно, что делает
модель, а не «запущено, проверьте сами».
"""
import json
import sys
import time
import pathlib
import urllib.request

ЗДЕСЬ = pathlib.Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
БАЗА = "http://127.0.0.1:8770"
ЗАПРОС = sys.argv[1] if len(sys.argv) > 1 else "ии система карен в костюме человека паука"
ПРОВАЙДЕР = sys.argv[2] if len(sys.argv) > 2 else "proxyapi"
МОДЕЛЬ = sys.argv[3] if len(sys.argv) > 3 else "deepseek/deepseek-v3.2"


def дай(путь):
    with urllib.request.urlopen(БАЗА + путь, timeout=30) as r:
        return json.loads(r.read())


def шли(путь, тело):
    req = urllib.request.Request(БАЗА + путь, data=json.dumps(тело).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def ключ_провайдера(pid):
    """Взять ключ оттуда же, откуда его берёт вкладка «API» студии.

    Клиент по умолчанию читает secrets.json, а ключи, вписанные в студии,
    ложатся в genome/api_keys.json. Из-за этого запуск шёл со старым ключом
    и получал 401, хотя в интерфейсе стоял свежий. Ключ нигде не печатается.
    """
    import pathlib
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
                print("ключ взят из", файл.name)
                return зн
    print("ключ для", pid, "не найден — пойдёт тот, что знает клиент")
    return ""


print("сервер:", дай("/health"))

# Снять предыдущую работу, если она висит: иначе сервер ответит 409.
последняя = дай("/jobs/latest")
if последняя.get("active") and последняя.get("id"):
    try:
        шли("/jobs/%s/cancel" % последняя["id"], {})
        print("остановлена прежняя работа", последняя["id"])
        time.sleep(2)
    except Exception as e:
        print("не снялась:", str(e)[:200])

cfg = {"provider": ПРОВАЙДЕР, "model": МОДЕЛЬ}
ключ = ключ_провайдера(ПРОВАЙДЕР)
if ключ:
    cfg["key"] = ключ
начало = шли("/jobs", {"query": ЗАПРОС, "origin": "", "cfg": cfg})
job = начало["id"]
print("запущено:", job, "·", ПРОВАЙДЕР, МОДЕЛЬ)

видано = 0
конец = time.time() + int(sys.argv[4]) if len(sys.argv) > 4 else time.time() + 420
while time.time() < конец:
    time.sleep(6)
    try:
        s = дай("/jobs/%s?after=%d" % (job, видано))
    except Exception as e:
        print("опрос не прошёл:", str(e)[:160]); continue
    for e in s.get("events", []):
        видано += 1
        строка = "%s · %s · %s" % (e.get("at", "")[11:19], e.get("stage", ""), e.get("message", ""))
        if e.get("replicas") is not None:
            строка += "  [реплик %s]" % e["replicas"]
        print(строка[:400])
    if s.get("done"):
        print("\nсостояние:", s.get("state"), "· источников", len(s.get("sources", [])),
              "· улик", s.get("evidence_count"))
        break
else:
    print("\n(ещё идёт — это не ошибка)")
