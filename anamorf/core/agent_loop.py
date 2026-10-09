"""АГЕНТ-ЦИКЛ ЯДРА v2 — одна «рука» вместо четырёх.

    модель ─┬─ текст ───────────────────────────────> ответ человеку (конец)
            └─ tool_calls ─> политика ─> исполнитель ─> результат ─> модель ...

Как у агента Claude: вызов — это структура (JSON), а не текст, который
потом вырезают регулярками; результат ВСЕГДА возвращается модели, и
только она решает, что сказать. Отсюда нет «Сделала», когда ничего не
сделано, и нет двойных действий: больше никто не жмёт за её спиной.
"""
import json
import logging
import re
import time

import requests

from anamorf.core import engine, registry

log = logging.getLogger("saika.core.loop")
MAX_STEPS = 6


# КОМАНДА = ВЫЗОВ, ЗАКРЕПЛЕНО КОДОМ. Регулярка здесь ничего не исполняет
# (не рефлекс!) — она только говорит движку «на этом шаге ответ обязан
# быть вызовом инструмента» (tool_choice=required). Какой инструмент и с
# чем — решает модель. Так «Открыла ya.ru» без вызова становится
# невозможным физически, а не запрещённым словами в промпте.
_COMMAND = re.compile(
    r"^\W*(сайка\W+)?(сколько\s+будет|посчитай|открой|закрой|включи|выключи|найди|поищи|загугли|запусти|"
    r"сверни|разверни|переключи|поставь|сделай\s+(громк|тише|погромч)|громкость|"
    r"убавь|прибавь|покажи\s+(экран|вкладк|папк)|перейди|зайди|глянь|посмотри\s+на\s+экран|"
    r"какие\s+(вкладк|окна|программ)|что\s+(сейчас\s+)?(на\s+экране|открыто|лежит|в\s+папке)|"
    r"что\s+(ты\s+)?помнишь|вспомни|пауза|останови|продолжи\s+видео)", re.I)


def needs_tool(user_text: str) -> bool:
    return bool(_COMMAND.search(user_text or ""))


# ВЫЗОВ, ПРОТЁКШИЙ ТЕКСТОМ (стенд 09.10, v2g: в чат ушло
# «<tool_call>\n<function=window_focus>…»). Qwen иногда пишет вызов в своём
# XML-виде прямо в content — парсер llama.cpp его не узнаёт. Человеку такое
# показывать нельзя; а если инструменты на этом шаге разрешены — это
# настоящий вызов, и мы его исполняем.
_LEAK_START = ("<tool_call", "<function=")
_LEAK_FN = re.compile(r"<function=([\w.-]+)>(.*?)(?:</function>|$)", re.S)
_LEAK_PAR = re.compile(r"<parameter=([\w-]+)>\s*(.*?)\s*</parameter>", re.S)


def _parse_leak(text: str) -> list:
    out = []
    for i, m in enumerate(_LEAK_FN.finditer(text)):
        args = {}
        for k, v in _LEAK_PAR.findall(m.group(2)):
            try:
                args[k] = json.loads(v)
            except Exception:
                args[k] = v
        out.append({"id": f"leak_{i}", "name": m.group(1),
                    "args": json.dumps(args, ensure_ascii=False)})
    return out


def strip_leak(text: str) -> str:
    for s in _LEAK_START:
        j = text.find(s)
        if j >= 0:
            text = text[:j]
    return text.rstrip()


class _Gate:
    """Пропускает текст в чат, но придерживает всё, что может оказаться
    началом протёкшего вызова; как только он узнан — дальше молчит."""

    def __init__(self, emit):
        self.emit, self.buf, self.leaked = emit, "", False

    def feed(self, s: str):
        if self.leaked:
            return
        self.buf += s
        while self.buf:
            j = self.buf.find("<")
            if j < 0:
                self.emit(self.buf)
                self.buf = ""
                return
            if j:
                self.emit(self.buf[:j])
                self.buf = self.buf[j:]
            if any(self.buf.startswith(p) for p in _LEAK_START):
                self.leaked, self.buf = True, ""
                return
            if any(p.startswith(self.buf) for p in _LEAK_START):
                return                    # ещё не ясно — ждём следующий кусок
            self.emit(self.buf[0])
            self.buf = self.buf[1:]

    def flush(self):
        if self.buf and not self.leaked:
            self.emit(self.buf)
        self.buf = ""


def _stream(messages: list, tools: list, on_text, stop, temperature: float,
            tool_choice: str = "auto", max_tokens: int = 700, prose_cap: int = 0):
    """Один запрос к движку со стримом. Возвращает (text, tool_calls, stats)."""
    gate = _Gate(on_text)
    on_text = gate.feed
    body = {"model": "saika-core", "messages": messages, "tools": tools,
            "tool_choice": tool_choice, "id_slot": 0,
            "stream": True, "temperature": temperature, "top_p": 0.95,
            "cache_prompt": True, "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
            "timings_per_token": False}
    t0 = time.monotonic()
    first = None
    text, calls, timings = [], {}, {}
    with requests.post(engine.url() + "/v1/chat/completions", json=body,
                       stream=True, timeout=(5, 300)) as r:
        r.raise_for_status()
        for raw in r.iter_lines(decode_unicode=False):
            if stop is not None and stop.is_set():
                break
            if not raw or not raw.startswith(b"data: "):
                continue
            data = raw[6:]
            if data == b"[DONE]":
                break
            ev = json.loads(data.decode("utf-8"))
            if ev.get("timings"):
                timings = ev["timings"]
            ch = (ev.get("choices") or [{}])[0]
            d = ch.get("delta") or {}
            if d.get("content"):
                if first is None:
                    first = time.monotonic()
                text.append(d["content"])
                on_text(d["content"])
                # ШАГ-КОМАНДА ПОНЁС ПРОЗУ (стенд v2h: «391. В уме я не считаю…»
                # 160 токенов = 5 с впустую). Вызов приходит в tool_calls, а не
                # в content; 60 знаков текста без вызова — уже ясно, что это
                # проза: обрываем и идём на повтор с напоминанием.
                if prose_cap and not calls and not gate.leaked \
                        and sum(map(len, text)) > prose_cap:
                    log.info("ядро v2: шаг-команда пишет прозу — обрываю на %d знаках",
                             prose_cap)
                    break
                # ЗАЦИКЛИВАНИЕ (стенд 09.10, 18:13: «[жест:good]» ×1000, 87 с).
                # Одна и та же строка 4 раза подряд — обрываем генерацию.
                if "\n" in d["content"]:
                    lines = [x.strip() for x in "".join(text).split("\n") if x.strip()]
                    if len(lines) >= 4 and len(set(lines[-4:])) == 1:
                        log.warning("ядро v2: зацикливание на %r — обрываю", lines[-1][:40])
                        break
            for tc in d.get("tool_calls") or []:
                if first is None:
                    first = time.monotonic()
                i = tc.get("index", 0)
                c = calls.setdefault(i, {"id": tc.get("id") or f"call_{i}",
                                         "name": "", "args": ""})
                f = tc.get("function") or {}
                c["name"] += f.get("name") or ""
                c["args"] += f.get("arguments") or ""
    gate.flush()
    stats = {"ttft_ms": int(((first or time.monotonic()) - t0) * 1000),
             "prompt_n": timings.get("prompt_n"), "cache_n": timings.get("cache_n"),
             "gen_tps": round(timings.get("predicted_per_second") or 0, 1)}
    full = "".join(text)
    out_calls = [calls[k] for k in sorted(calls)]
    if gate.leaked:
        leak = _parse_leak(full)
        log.warning("ядро v2: вызов протёк текстом (%s) — %s",
                    ", ".join(c["name"] for c in leak) or "не разобран",
                    "исполняю" if (leak and tool_choice != "none" and not out_calls)
                    else "вырезаю")
        if leak and tool_choice != "none" and not out_calls:
            out_calls = leak
        full = strip_leak(full)
    return full, out_calls, stats


def run(messages: list, user_text: str, on_text, on_tool, stop=None,
        temperature: float = 0.7) -> dict:
    """Крутить модель до финального текста.

    on_text(delta)                 — кусок ответа (в чат/голос)
    on_tool(name, args, result)    — исполненный вызов (для UI-строки)
    Возвращает {"text", "steps", "tools", "stats", "new": [сообщения хода]}.

    КОМАНДА БЕЗ ВЫЗОВА НЕ ПРОХОДИТ (стенд 09.10, 18:00): даже с
    tool_choice=required модель Qwen3.6 сперва ПИШЕТ текст («треста
    девять», «Открыла YouTube»), а вызов — после или никогда. Поэтому на
    шаге-команде текст не стримится, а придерживается: пришёл вызов — текст
    до него выбрасываем (он писался вслепую, до результата); не пришёл —
    один повтор с напоминанием, и только если и он пуст — отдаём как есть.
    """
    tools = registry.schemas()
    msgs = list(messages)
    base = len(msgs)
    used, stats_all, final = [], [], ""
    seen, by_name = {}, {}
    force = needs_tool(user_text)
    retried = False
    step = 0
    while step < MAX_STEPS:
        held = force and step == 0
        sink = [] if held else None
        emit = sink.append if held else on_text
        choice = "required" if held else "auto"
        # шаг-команда: вызов короткий; если модель понесла прозу — режем на
        # 160 токенах и идём на повтор (было: 700 токенов прозы = 23 с)
        # первый заход — обрываем прозу на 60 знаках; повтор — даём 160
        # токенов (если и он без вызова, этот текст и станет ответом)
        text, calls, st = _stream(msgs, tools, emit, stop, temperature, choice,
                                  160 if held else 700,
                                  prose_cap=60 if (held and not retried) else 0)
        stats_all.append(st)
        log.info("ядро v2: шаг %d — до 1-го токена %s мс, промпт %s (из кэша %s), "
                 "%s ток/с, вызовов %d%s", step + 1, st["ttft_ms"], st["prompt_n"],
                 st["cache_n"], st["gen_tps"], len(calls),
                 " (придержан)" if held else "")
        if held and not calls and not retried and not (stop and stop.is_set()):
            retried = True
            log.info("ядро v2: команда без вызова — повтор с напоминанием: %r", text[:80])
            msgs = msgs + [{"role": "assistant", "content": text or "…"},
                           {"role": "user", "content":
                            "(система: это была команда. Не описывай действие — "
                            "вызови подходящий инструмент прямо сейчас, ответ скажешь по результату.)"}]
            continue                     # тот же шаг ещё раз
        if not calls or (stop is not None and stop.is_set()):
            if held and text:
                on_text(text)            # повтор не помог — честно отдаём текст
            final = text
            break
        text = "" if held else text      # текст «вслепую» до вызова — в мусор
        msgs.append({"role": "assistant", "content": text or "",
                     "tool_calls": [{"id": c["id"], "type": "function",
                                     "function": {"name": c["name"],
                                                  "arguments": c["args"] or "{}"}}
                                    for c in calls]})
        for c in calls:
            try:
                args = json.loads(c["args"] or "{}")
            except Exception:
                args = {}
            key = c["name"] + json.dumps(args, ensure_ascii=False, sort_keys=True)
            seen[key] = seen.get(key, 0) + 1
            by_name[c["name"]] = by_name.get(c["name"], 0) + 1
            t0 = time.monotonic()
            if seen[key] > 2:
                res = ("тот же вызов уже был дважды с тем же результатом — "
                       "не повторяй, скажи человеку как есть")
            elif by_name[c["name"]] > 3:
                # стенд v2g: window_focus ×4 с разными словами подряд
                res = (f"{c['name']} за этот ход уже 3 раза — хватит перебирать. "
                       "Скажи человеку, что получилось и что нет.")
            else:
                res = registry.execute(c["name"], args, user_text)
                log.info("ядро v2: %s(%s) за %.1f с -> %s", c["name"],
                         json.dumps(args, ensure_ascii=False)[:120],
                         time.monotonic() - t0, res[:160].replace("\n", " "))
            used.append({"name": c["name"], "args": args, "result": res[:300]})
            on_tool(c["name"], args, res, int((time.monotonic() - t0) * 1000))
            msgs.append({"role": "tool", "tool_call_id": c["id"],
                         "content": res[:1500]})
        step += 1
    else:
        # ШАГИ КОНЧИЛИСЬ — НО ОТВЕТ ОБЯЗАН БЫТЬ (стенд: 6 вызовов folder_list
        # и пустой ответ). Последний заход без инструментов: скажи, что нашла.
        try:
            text, _c, st = _stream(
                msgs + [{"role": "user", "content":
                         "(система: инструменты на этот ход кончились. Ответь "
                         "человеку словами: что сделано и что не вышло.)"}],
                tools, on_text, stop, temperature, "none", 400)
            stats_all.append(st)
            final = text
        except Exception as e:
            log.warning("ядро v2: финальный ответ не сложился: %s", e)
        final = final or "Застряла на этой задаче — слишком много шагов. Скажи, как продолжить."
    # что останется в стенограмме сеанса: без «повтора с напоминанием»
    new = [m for m in msgs[base:] if not str(m.get("content", "")).startswith("(система:")]
    if retried and new and new[0].get("role") == "assistant" and not new[0].get("tool_calls"):
        new = new[1:]
    new.append({"role": "assistant", "content": final.strip() or "…"})
    return {"text": final.strip(), "steps": len(stats_all), "tools": used,
            "stats": stats_all, "new": new}
