"""Живой стенд resources: настоящая модель, настоящие цифры.

    python -m anamorf3.resources.bench_live local     # поднять, 3 вопроса, выгрузить
    python -m anamorf3.resources.bench_live cloud

Пишет итог в logs/anamorf3_bench.jsonl (дописывает) и печатает его.
Что меряем: время подъёма, VRAM до/после подъёма и после выгрузки,
ttft и скорость на каждом вопросе, вызов инструмента целиком, отмену.
"""
import json
import sys
import time

from anamorf3.contracts import CancelToken, ChatRequest
from anamorf3.resources import make_port, gpu
from anamorf3.resources.settings import path

TOOLS = [{"type": "function", "function": {
    "name": "open_folder", "description": "Открыть папку в проводнике",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                   "required": ["path"]}}}]


def ask(port, text, tools=None, cancel_after=None):
    tok = CancelToken()
    req = ChatRequest(messages=[{"role": "system", "content": "Отвечай коротко, по-русски."},
                                {"role": "user", "content": text}],
                      tools=tools or [], max_tokens=200, temperature=0.2, mode=port.mode)
    out, calls, end, n = "", [], None, 0
    for ch in port.chat(req, tok):
        out += ch.text
        calls += ch.tool_calls
        n += bool(ch.text)
        if cancel_after and n >= cancel_after and not tok.cancelled:
            tok.cancel("стенд")
        if ch.done:
            end = ch
    u = end.usage
    t = u.get("timings") or {}
    return {"q": text, "answer": out[:160], "tool_calls": calls, "finish": u.get("finish_reason"),
            "error": u.get("error"), "ttft_ms": u.get("ttft_ms"), "total_ms": u.get("total_ms"),
            "model": end.model, "gen_tok_s": round(t.get("predicted_per_second", 0), 1) or None,
            "prompt_tok_s": round(t.get("prompt_per_second", 0), 1) or None}


def main(mode):
    port = make_port(mode)
    rep = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": mode}
    rep["vram_start_mb"] = gpu.settle_used_mb(2)
    t0 = time.monotonic()
    rep["q1"] = ask(port, "Скажи одной фразой, кто ты.")
    rep["first_answer_incl_load_s"] = round(time.monotonic() - t0, 1)
    rep["vram_loaded_mb"] = gpu.vram_mb()[0]
    rep["q2_warm"] = ask(port, "Сколько будет 17*23? Только число.")
    rep["q3_tool"] = ask(port, "Открой папку C:\\AI\\Saika", tools=TOOLS)
    rep["q4_cancel"] = ask(port, "Перечисли сто городов России через запятую.", cancel_after=3)
    rep["status"] = port.status()
    r = port.unload_all()
    rep["unload"] = r.__dict__
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    with open(path("logs/anamorf3_bench.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rep, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "local")
