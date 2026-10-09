# -*- coding: utf-8 -*-
"""Проверка: соблюдает ли движок tool_choice=required (стенд: «сколько будет
17×23» -> 0 вызовов, ответ «39»). Результат -> data/core_required.txt"""
import io, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
from anamorf.core import engine, registry, persona
out = []
for choice in ("auto", "required"):
    for tools_n in ("calc", "all"):
        tools = registry.schemas() if tools_n == "all" else [registry.CALC]
        body = {"model": "x", "tool_choice": choice, "tools": tools, "id_slot": 1,
                "chat_template_kwargs": {"enable_thinking": False}, "max_tokens": 200,
                "messages": [{"role": "system", "content": persona.system_prompt()},
                             {"role": "user", "content": "сколько будет 17 умножить на 23?"}]}
        r = requests.post(engine.url() + "/v1/chat/completions", json=body, timeout=120)
        m = r.json()["choices"][0]["message"] if r.ok else {"err": r.text[:300]}
        out.append(f"{choice:9} tools={tools_n:4} -> calls={json.dumps(m.get('tool_calls'), ensure_ascii=False)[:160]} text={str(m.get('content'))[:80]!r} {m.get('err','')}")
io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "core_required.txt"), "w", encoding="utf-8").write("\n".join(out))
