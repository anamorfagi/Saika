# -*- coding: utf-8 -*-
"""
[БЛОК СТЫКИ] Пробник всех провайдеров: что реально открывается с этой машины.

Проверка идёт в три ступени и на каждой пишет ЧЕСТНУЮ причину, а не «ошибка»:
  1) DNS      — резолвится ли имя (провал = блокировка на уровне DNS)
  2) TCP+TLS  — устанавливается ли соединение (сброс = блокировка по IP или DPI)
  3) HTTP     — что отвечает сам API. Код 401/403 БЕЗ ключа означает,
                что адрес доступен и ждёт ключ. Это зелёный результат.
Если ключ найден (secrets.json или аргумент), делается настоящий короткий запрос
к модели: тогда видно время ответа и то, что модель действительно отвечает.

Запуск:  python pipeline/probe.py            — все стыки
         python pipeline/probe.py --id deepseek proxyapi
         python pipeline/probe.py --json      — машинный вывод для студии
"""
import argparse, concurrent.futures as cf, json, pathlib, socket, ssl, sys, time
import urllib.error, urllib.parse, urllib.request

HERE = pathlib.Path(__file__).parent
CATALOG = json.loads((HERE / "providers.json").read_text(encoding="utf-8"))["providers"]
sys.path.insert(0, str(HERE))
from llm import find_key                                    # тот же поиск ключа, что и у следователя

# Кодов много, но человеку нужен один понятный ярлык и один цвет.
VERDICT = {
    "ok_key":    ("работает",            "ok"),
    "ok_open":   ("адрес доступен, нужен ключ", "open"),
    "geo":       ("отказ по региону",    "geo"),
    "dns":       ("имя не резолвится",   "block"),
    "tcp":       ("соединение не встаёт", "block"),
    "tls":       ("TLS сброшен",         "block"),
    "timeout":   ("нет ответа вовремя",  "block"),
    "bad_key":   ("ключ не принят",      "warn"),
    "http":      ("отвечает с ошибкой",  "warn"),
    "local":     ("локальный сервис не запущен", "warn"),
    "proxy":     ("местный прокси не пустил", "warn"),
}


def stage_dns(host):
    t0 = time.time()
    infos = socket.getaddrinfo(host, None)
    return round((time.time() - t0) * 1000), sorted({i[4][0] for i in infos})


# GigaChat подписан УЦ Минцифры: в системе Windows этого корня обычно нет, и честная
# проверка сертификата валится. llm.py это уже учитывает, пробник должен вести себя так же —
# иначе он рапортует «заблокирован» о стыке, который на деле работает.
SELF_SIGNED = ("gigachat.devices.sberbank.ru", "ngw.devices.sberbank.ru")


def stage_tls(host, port, timeout):
    t0 = time.time()
    ctx = ssl.create_default_context()
    if host in SELF_SIGNED:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as raw:
        if port == 443:
            with ctx.wrap_socket(raw, server_hostname=host):
                pass
    return round((time.time() - t0) * 1000)


def headers_for(p, key):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    a = p.get("auth", "bearer")
    if not key:
        return h
    if a == "bearer":   h["Authorization"] = ("Api-Key " if p["id"] == "yandex" else "Bearer ") + key
    elif a == "raw":    h["Authorization"] = key                 # GPTunneL: ключ без слова Bearer
    elif a == "x-api-key": h["x-api-key"] = key; h["anthropic-version"] = "2023-06-01"
    return h


def probe(p, timeout=12, ask=True):
    """Один стык. Возвращает словарь с кодом, ярлыком и настоящими миллисекундами."""
    r = {"id": p["id"], "name": p["name"], "grp": p.get("grp", "direct"), "base": p["base"],
         "ru_claim": p.get("ru", "?"), "free": bool(p.get("free")), "key_url": p.get("key_url", ""),
         "model": (p.get("models") or [""])[0], "has_key": False, "dns_ms": None, "tls_ms": None,
         "http_ms": None, "status": None, "code": "", "verdict": "", "level": "", "detail": ""}
    base = p["base"].rstrip("/")
    if not base or "{" in base:
        r.update(code="http", detail="в адресе есть подстановка — заполни вручную"); return finish(r)
    u = urllib.parse.urlsplit(base)
    host, port = u.hostname, u.port or (443 if u.scheme == "https" else 80)
    local = host in ("localhost", "127.0.0.1")

    try:
        r["dns_ms"], addrs = stage_dns(host)
        r["detail"] = "адрес " + addrs[0]
    except socket.gaierror as e:
        r.update(code="local" if local else "dns", detail=str(e)); return finish(r)
    try:
        r["tls_ms"] = stage_tls(host, port, timeout)
    except socket.timeout:
        r.update(code="timeout", detail=f"порт {port} молчит {timeout} с"); return finish(r)
    except ssl.SSLError as e:
        r.update(code="tls", detail=str(e)); return finish(r)
    except OSError as e:
        r.update(code="local" if local else "tcp", detail=str(e)); return finish(r)

    key = None
    if ask:
        try: key = find_key(p["id"]) or None
        except Exception: key = None
    r["has_key"] = bool(key)
    path = "/messages" if p.get("auth") == "x-api-key" else "/chat/completions"
    if p.get("auth") == "x-api-key":
        body = {"model": r["model"], "max_tokens": 5, "messages": [{"role": "user", "content": "ок"}]}
    else:
        body = {"model": r["model"], "max_tokens": 5, "messages": [{"role": "user", "content": "ок"}]}
    req = urllib.request.Request(base + path, data=json.dumps(body).encode("utf-8"),
                                 headers=headers_for(p, key), method="POST")
    ctx = None
    if host in SELF_SIGNED:
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read(4000)
        r["http_ms"] = round((time.time() - t0) * 1000); r["status"] = 200
        r.update(code="ok_key", detail="модель ответила")
        try:
            d = json.loads(raw)
            got = d.get("choices", [{}])[0].get("message", {}).get("content") or str(d.get("content", ""))[:60]
            if got: r["detail"] = "ответ: " + str(got).strip()[:60]
        except Exception: pass
    except urllib.error.HTTPError as e:
        r["http_ms"] = round((time.time() - t0) * 1000); r["status"] = e.code
        text = (e.read(600) or b"").decode("utf-8", "replace").strip().replace("\n", " ")
        low = text.lower()
        geo = any(w in low for w in ("country", "region", "territory", "not available in your",
                                     "unsupported_country", "недоступен", "юрисдикц"))
        if e.code in (401, 403) and not key:
            r.update(code="geo" if geo else "ok_open",
                     detail="регион отклонён" if geo else "ключ не передан — ровно этого и ждём")
        elif e.code in (401, 403):
            r.update(code="geo" if geo else "bad_key", detail=text[:160])
        elif e.code in (400, 404, 422):
            r.update(code="ok_open", detail=f"HTTP {e.code}: адрес живой, поправь имя модели · {text[:110]}")
        elif e.code == 429:
            r.update(code="ok_open", detail="лимит запросов — значит стык работает")
        else:
            r.update(code="http", detail=f"HTTP {e.code}: {text[:140]}")
    except socket.timeout:
        r.update(code="timeout", detail=f"ответа нет {timeout} с")
    except Exception as e:
        s = str(e)
        r.update(code="proxy" if "Tunnel connection failed" in s else "http", detail=s[:160])
    return finish(r)


def finish(r):
    label, level = VERDICT.get(r["code"], ("непонятный ответ", "warn"))
    r["verdict"], r["level"] = label, level
    return r


def probe_all(ids=None, timeout=12, workers=8, ask=True):
    rows = [p for p in CATALOG if p["id"] != "custom" and (not ids or p["id"] in ids)]
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(lambda p: probe(p, timeout, ask), rows))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", nargs="*"); ap.add_argument("--timeout", type=int, default=12)
    ap.add_argument("--json", action="store_true"); ap.add_argument("--nokey", action="store_true")
    a = ap.parse_args()
    rows = probe_all(a.id, a.timeout, ask=not a.nokey)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1)); sys.exit()
    mark = {"ok": "✓", "open": "○", "geo": "✗", "block": "✗", "warn": "!"}
    GRP = {"ru_agg": "РОССИЙСКИЕ АГРЕГАТОРЫ (без VPN)", "direct": "ПРЯМЫЕ ПРОВАЙДЕРЫ", "local": "СВОЁ ЖЕЛЕЗО"}
    for g in ("ru_agg", "direct", "local"):
        part = [r for r in rows if r["grp"] == g]
        if not part: continue
        print("\n" + GRP[g])
        for r in sorted(part, key=lambda x: ("ok", "open", "warn", "geo", "block").index(x["level"])):
            ms = f'{r["http_ms"] or r["tls_ms"] or 0:>5} мс'
            print(f'  {mark[r["level"]]} {r["name"]:<28} {ms}  {r["verdict"]:<28} {r["detail"][:70]}')
    live = [r for r in rows if r["level"] in ("ok", "open")]
    print(f'\nДоступно стыков: {len(live)} из {len(rows)}. С работающим ключом: {sum(1 for r in rows if r["code"]=="ok_key")}.')
    free = [r for r in live if r["free"] and not r["has_key"]]
    if free: print("Есть бесплатный тир, ключ ещё не заведён: " + ", ".join(r["name"] for r in free))
