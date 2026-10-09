# -*- coding: utf-8 -*-
"""[БЛОК ПРОВЕРКА] Живой запрос в /api/chat студии — с той же машины, где она работает.

Зачем: из облака до localhost студии не достучаться, а «наверное, работает» — не отчёт.
Скрипт шлёт настоящее сообщение и печатает каждое пришедшее событие, так что видно,
поднялся ли маршрут, нашёлся ли ключ и ответила ли модель.

Запуск: python pipeline/chat_smoke.py [текст]
"""
import json
import sys
import urllib.request

# Консоль на Windows живёт в cp1251, и один символ вне неё (стрелка, тире, кавычка-ёлочка)
# роняет весь скрипт UnicodeEncodeError — падает не печать, а вся работа. Поэтому вывод
# переводится в utf-8 с заменой непечатаемого: отчёт может потерять символ, но не смысл.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ПОРТ = 8765
текст = " ".join(sys.argv[1:]) or "Ответь одним словом: работает"
тело = json.dumps({"messages": [{"role": "user", "content": текст}]}, ensure_ascii=False).encode("utf-8")
req = urllib.request.Request(f"http://127.0.0.1:{ПОРТ}/api/chat", data=тело,
                             headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=240) as r:
        print("HTTP", r.status, r.headers.get("Content-Type"))
        for строка in r:
            строка = строка.decode("utf-8", "replace").strip()
            if not строка:
                continue
            try:
                e = json.loads(строка)
            except ValueError:
                print("НЕ JSON:", строка[:300]); continue
            print(f"[{e.get('t')}]", str(e.get("text") or e.get("name") or "")[:400])
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read()[:400])
except Exception as e:
    print("НЕ ДОСТУЧАЛСЯ:", e)
