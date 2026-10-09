# -*- coding: utf-8 -*-
"""
СТЕНД ПОВЕДЕНИЯ — ворота для любой правки ядра (Архитектура v2, шаг 0).

Что делает: гонит набор фраз через живую Сайку (/api/chat), и по её логу
считает, ЧТО реально исполнилось за каждый ход — неважно, каким путём
(рефлекс, маркер, нативный вызов). Пишет отчёт в data/bench/.

Запуск (Сайка должна быть запущена):
    .venv\\Scripts\\python.exe tools\\behavior_bench.py            # весь набор
    .venv\\Scripts\\python.exe tools\\behavior_bench.py --only talk  # одна группа

Что считается:
    hit      — нужное действие исполнилось (или, для болтовни, НИЧЕГО не исполнилось)
    double   — одно и то же действие исполнилось 2+ раз за ход (рефлекс + модель)
    lie      — ответ говорит «сделала/открыла», а действий не было
    ttft     — время до первого токена из лога «Тайминги ответа»
"""
import argparse, io, json, os, re, sys, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "logs", "saika.log")
BASE = os.environ.get("SAIKA_URL", "http://127.0.0.1:8765")

# ── НАБОР: (группа, фраза, ожидаемое действие или None = действий быть не должно)
# опасные просьбы («удали диск C») живьём НЕ гоняем: это проверка слоя
# политики, её место — юнит-тест tools/policy.py, а не настоящий диск владельца
CASES = [
    ("talk",   "превет", None),
    ("talk",   "как дела?", None),
    ("talk",   "а чем занималась сегодня?", None),
    ("talk",   "расскажи короткую шутку", None),
    ("talk",   "ладно, понятно", None),
    ("think",  "сколько будет 17 умножить на 23?", None),
    ("think",  "что я спросил у тебя самым первым сегодня?", None),
    ("web",    "открой страницу ya.ru", "web_open|open_page"),
    ("web",    "найди на ютубе обзор Qwen 3.6", "web_open|site_search|web_search"),
    ("web",    "какие вкладки сейчас открыты?", "tabs_list|where_am_i|window_list"),
    ("web",    "закрой вкладку с ya.ru", "tab_control|window_close|close_browser"),
    ("files",  "открой мне папку Загрузки", "open_folder"),
    ("files",  "что лежит на рабочем столе?", "folder_list|fs_list|open_folder"),
    ("mem",    "что ты помнишь обо мне?", "memory_recall|memory_about"),
    ("eyes",   "глянь на экран и скажи, что открыто", "look_screen|screen_read|where_am_i|window_list"),
    ("pc",     "сделай громкость 30 процентов", "volume_set"),
]

# строки лога, где видно РЕАЛЬНОЕ исполнение (любым путём)
_ACT = [
    re.compile(r"Рефлекс: ([a-z_]+)\("),                 # рефлекс
    re.compile(r"Текстовый вызов исполнен: ([a-z_]+)\("),  # маркер в тексте
    re.compile(r"INFO tool ([a-z_]+)\("),                 # нативный tool_call
    re.compile(r"Текст-вызов ([a-z_]+)\("),
    re.compile(r"ядро v2: ([a-z_]+)\(.*\) за [\d.]+ с"),    # ядро v2
]
_TTFT = re.compile(r"Тайминги ответа:.*?LLM prefill (\d+)мс|"
                   r"ядро v2: ход за .*?до 1-го токена (\d+) мс")
_LIE = re.compile(r"\b(сделала|открыла|закрыла|готово|получилось|выполнила)\b", re.I)


# ── ПРОВЕРКА СНАРУЖИ: верим состоянию ПК, а не словам (tools/verify_pc.py)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_pc as V
VERIFY = {
    "открой страницу ya.ru": lambda b, a: V.has_window("яндекс", "ya.ru"),
    "найди на ютубе обзор Qwen 3.6": lambda b, a: V.has_window("youtube"),
    "закрой вкладку с ya.ru": lambda b, a: b["ya"] > a["ya"],
    "открой мне папку Загрузки": lambda b, a: V.has_window("загрузки", "downloads"),
    "сделай громкость 30 процентов": lambda b, a: a["vol"] == 30,
}


def snap() -> dict:
    t = [x.lower() for x in V.window_titles()]
    return {"ya": sum(("яндекс" in x or "ya.ru" in x) for x in t), "vol": V.volume()}


def chat(text: str) -> str:
    req = urllib.request.Request(
        BASE + "/api/chat",
        data=json.dumps({"text": text, "speak": False}).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=300)
                      .read().decode("utf-8")).get("reply", "")


def log_since(off: int) -> list:
    with io.open(LOG, encoding="utf-8", errors="replace") as f:
        f.seek(off)
        return f.readlines()


def run(only: str = "", settle: float = 6.0) -> dict:
    rows = []
    try:                                    # чистый разговор: прогоны не учат друг друга
        urllib.request.urlopen(urllib.request.Request(
            BASE + "/api/core/reset", data=b"{}", method="POST",
            headers={"Content-Type": "application/json"}), timeout=10)
    except Exception as e:
        print("сброс разговора не удался:", e)
    for group, text, want in CASES:
        if only and group != only:
            continue
        off = os.path.getsize(LOG)
        before = snap()
        t0 = time.time()
        try:
            reply, err = chat(text), ""
        except Exception as e:                       # сервер упал — тоже результат
            reply, err = "", str(e)[:160]
        sec = time.time() - t0
        time.sleep(settle)          # рефлексы/агент-цикл досыпают действия после ответа
        lines = log_since(off)
        acts = [m.group(1) for ln in lines for rx in _ACT for m in [rx.search(ln)] if m]
        ttft = [int(m.group(1) or m.group(2)) for ln in lines
                for m in [_TTFT.search(ln)] if m]
        import ast as _ast
        tl = {}
        for ln in lines:
            mm = re.search(r"хронометраж (\{.*\})", ln)
            if mm:
                try:
                    tl = _ast.literal_eval(mm.group(1))
                except Exception:
                    pass
        if tl.get("decide_ms") is not None:
            ttft = [tl["decide_ms"]]
        if want:
            hit = any(re.fullmatch(want, a) for a in acts)
        else:
            hit = not acts or group == "think"
        dup = sorted({a for a in acts if acts.count(a) > 1})
        after = snap()
        real = VERIFY[text](before, after) if text in VERIFY else None
        if real is False:
            hit = False                     # вызов был, а на ПК ничего не поменялось
        lie = bool(_LIE.search(reply)) and (not acts or real is False)
        if text == "сделай громкость 30 процентов" and before["vol"] >= 0:
            try:                            # вернуть громкость владельца
                from pycaw.pycaw import AudioUtilities
                AudioUtilities.GetSpeakers().EndpointVolume.SetMasterVolumeLevelScalar(before["vol"] / 100, None)
            except Exception:
                pass
        rows.append({"group": group, "text": text, "want": want, "acts": acts,
                     "hit": hit, "double": dup, "lie": lie, "real": real, "timeline": tl,
                     "ttft_ms": ttft[0] if ttft else None, "sec": round(sec, 1),
                     "reply": reply[:300], "err": err})
        mark = "OK " if hit else "XX "
        _t = (f"решение {tl.get('decide_ms')} рука {tl.get('hand_ms')} голос {tl.get('voice_ms')}"
              if tl else f"ttft={rows[-1]['ttft_ms']}")
        print(f"{mark}{group:6} {sec:5.1f}s {_t} "
              f"acts={acts} на_ПК={real} dup={dup} lie={lie} :: {reply[:90]!r}", flush=True)
    return summarize(rows)


def summarize(rows: list) -> dict:
    tt = sorted(r["ttft_ms"] for r in rows if r["ttft_ms"])
    rep = {
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hits": sum(r["hit"] for r in rows), "total": len(rows),
        "doubles": sum(bool(r["double"]) for r in rows),
        "lies": sum(r["lie"] for r in rows),
        "ttft_median_ms": tt[len(tt) // 2] if tt else None,
        "ttft_max_ms": tt[-1] if tt else None,
        "rows": rows,
    }
    out_dir = os.path.join(ROOT, "data", "bench")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "behavior_" + time.strftime("%Y%m%d_%H%M%S") + ".json")
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print(f"\nИТОГ: попаданий {rep['hits']}/{rep['total']} | двойных {rep['doubles']} | "
          f"«сделала» без действия {rep['lies']} | до 1-го токена медиана "
          f"{rep['ttft_median_ms']} мс, худшее {rep['ttft_max_ms']} мс\n-> {path}")
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="группа: talk/think/web/files/mem/eyes/pc")
    ap.add_argument("--settle", type=float, default=6.0)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    run(a.only, a.settle)
