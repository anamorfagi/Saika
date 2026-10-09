# -*- coding: utf-8 -*-
"""Откуда 10 ток/с вместо 26 в агент-цикле: тот же ход в 4 режимах
(инструменты да/нет × стрим да/нет). Данные — в data/core_speed.txt"""
import io, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
from anamorf.core import persona, registry, engine

sys_text = persona.system_prompt("Виталий") + "\n\n" + registry.index_text()
msgs = [{"role": "system", "content": sys_text},
        {"role": "user", "content": "Расскажи в трёх предложениях, чем ты занята сегодня."}]
res = []
for label, tools, stream, extra in [
        ("инстр=нет стрим=нет", False, False, {}),
        ("инстр=да  стрим=нет", True, False, {}),
        ("инстр=нет стрим=да ", False, True, {}),
        ("инстр=да  стрим=да ", True, True, {}),
        ("инстр=да  стрим=да  parse_tool_calls=false", True, True, {"parse_tool_calls": False})]:
    body = {"model": "x", "messages": msgs, "max_tokens": 80, "temperature": 0.7,
            "cache_prompt": True, "stream": stream,
            "chat_template_kwargs": {"enable_thinking": False}, **extra}
    if tools:
        body["tools"] = registry.schemas()
    t0 = time.time(); n = 0; first = None
    if stream:
        with requests.post(engine.url() + "/v1/chat/completions", json=body, stream=True, timeout=120) as r:
            for ln in r.iter_lines():
                if ln.startswith(b"data: ") and ln[6:] != b"[DONE]":
                    d = json.loads(ln[6:])
                    if (d.get("choices") or [{}])[0].get("delta", {}).get("content"):
                        n += 1; first = first or time.time()
        dt = time.time() - (first or t0)
        res.append(f"{label:45} первый кусок {((first or t0)-t0)*1000:.0f} мс | {n} кусков за {dt:.1f} с = {n/max(dt,0.01):.1f}/с")
    else:
        r = requests.post(engine.url() + "/v1/chat/completions", json=body, timeout=120).json()
        t = r.get("timings", {})
        res.append(f"{label:45} prompt {t.get('prompt_n')} ток {t.get('prompt_ms',0):.0f} мс | {t.get('predicted_per_second',0):.1f} ток/с")
io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "core_speed.txt"),
        "w", encoding="utf-8").write("\n".join(res))
