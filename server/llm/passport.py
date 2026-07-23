"""Паспорт модели — авто-профилирование при первом знакомстве.

Зачем: каждая модель ломается ПО-СВОЕМУ, и до 2026-07-23 система узнавала
об этом через боль пользователя: glm-4.6v/gemma-12b молча отдавали 0 токенов
(контекст LM Studio меньше нашего промпта), Huihui лила размышления в чат,
у части моделей нечитаемый формат tool_calls. Каждый случай чинился руками.
Паспорт делает это системой: после прогрева модель прощупывается короткими
пробами, результат сохраняется в data/model_passports.json (per-machine,
data/ в .gitignore), и конвейер подстраивается под возможности модели сам.

Пробы (все — не-стримовые вызовы с жёстким max_tokens, суммарно секунды):
  ping        отвечает ли вообще; замер ttft/ток/с на коротком запросе
  big_prompt  боевой размер системного промпта (llm.context_chars):
              пустой ответ = молчаливое переполнение окна (класс багов
              «0 токенов»); тогда бинарно спускаемся 12000→8000→5000→3000
              и запоминаем НАИБОЛЬШИЙ рабочий бюджет → context_chars
  think_leak  просим с enable_thinking=false; если в ответе <think> или
              англоязычная «Thinking»-простыня — модель игнорирует флаг

Использование паспорта:
  - main.py: бюджет обрезки истории = passport.context_chars_for(model)
    (если проба нашла меньший рабочий, чем llm.context_chars);
  - manager._stream_openai: если llm.think=false, llm.target_response_s>0 и
    в паспорте есть ток/с — шлём max_tokens под целевое время ответа;
  - /api/models отдаёт паспорта в UI.

Пробуем только локальные бэкенды (ollama/lmstudio/locallm) — облако не
трогаем (сеть/деньги). Прогон один раз на модель (probed_at в паспорте);
перепрощупать: passport.reprobe(model) или удалить запись из json.
"""
import json
import threading
import time

import requests

from server.config import CFG, ROOT

try:
    import logging
    log = logging.getLogger("saika.passport")
except Exception:  # pragma: no cover
    log = None

PATH = ROOT / "data" / "model_passports.json"
VERSION = 1  # поднять при изменении набора проб — паспорта перепрощупаются
_lock = threading.Lock()
_probing = set()  # модели, которые щупаются прямо сейчас (не дублировать)

_FILLER = ("Это служебный наполнитель для проверки окна контекста модели. "
           "Он имитирует реальный системный промпт с персоной и правилами. ")


def _load() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d: dict):
    try:
        PATH.parent.mkdir(exist_ok=True)
        PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except Exception:
        pass


def get(model: str) -> dict | None:
    p = _load().get(model)
    if p and p.get("version") == VERSION:
        return p
    return None


def all_passports() -> dict:
    return {m: p for m, p in _load().items() if p.get("version") == VERSION}


def context_chars_for(model: str) -> int | None:
    """Рабочий бюджет контекста из паспорта.
    None = проба не нашла проблем (большой промпт прошёл) — бери из конфига.
    Число = используй именно его.

    2026-07-23: раньше проверяли только context_chars, а он бывает None в
    ДВУХ противоположных случаях — «всё ок, большой промпт прошёл» И «модель
    молчит даже на самом маленьком проверенном размере (3000 симв.)». Из-за
    этого паспорт правильно ловил класс багов «0 токенов» (big_prompt_ok:
    false), но main.py его сигнал терял и слал полноразмерный промпт СНОВА —
    ровно та же немая генерация по кругу (qwen3-4b-thinking-2507,
    qwen3.5-9b в LM Studio: минуты «0 токенов», прерван stop_event=False).
    Теперь big_prompt_ok — главный флаг: не осилела совсем -> аварийный
    потолок вместо «лимита нет»."""
    p = get(model)
    if not p:
        return None
    if p.get("big_prompt_ok"):
        return None
    if p.get("context_chars"):
        return int(p["context_chars"])
    # big_prompt_ok=False и рабочего размера не нашли вообще (молчит даже на
    # минимальном проверенном бюджете) — не отпускаем без лимита, иначе
    # каждый заход снова убьёт генерацию тем же переполнением
    return int(CFG.get("llm.context_chars_floor", 2000))


def tps_for(model: str) -> float | None:
    p = get(model)
    return p.get("tps") if p else None


# ---------------- сами пробы ----------------

def _ask(backend: str, model: str, system: str, user: str,
         max_tokens: int = 48, timeout: int = 120) -> tuple[str, float]:
    """Не-стримовый вызов бэкенда с жёстким max_tokens.
    Возвращает (текст, секунд). Пустой текст — тоже результат (это и ловим)."""
    from server.llm import manager  # лениво: не завязываться при импорте
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": user}]
    t0 = time.monotonic()
    if backend == "ollama":
        r = requests.post(manager._ollama_url() + "/api/chat",
                          json={"model": model, "messages": msgs,
                                "stream": False,
                                "options": {"num_predict": max_tokens}},
                          timeout=timeout)
        r.raise_for_status()
        text = (r.json().get("message") or {}).get("content", "") or ""
    else:  # lmstudio / locallm — OpenAI-диалект
        url = (manager._locallm_url() if backend == "locallm"
               else manager._lmstudio_url())
        payload = {"model": model, "messages": msgs, "stream": False,
                   "max_tokens": max_tokens,
                   # просим шаблон не думать — и проверяем, послушалась ли
                   "chat_template_kwargs": {"enable_thinking": False}}
        r = requests.post(url + "/v1/chat/completions", json=payload,
                          timeout=timeout)
        r.raise_for_status()
        ch = (r.json().get("choices") or [{}])[0]
        text = ((ch.get("message") or {}).get("content") or "")
    return text.strip(), max(time.monotonic() - t0, 0.001)


def _probe(backend: str, model: str) -> dict:
    p = {"version": VERSION, "backend": backend,
         "probed_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    # 1) ping: жива? скорость?
    text, dt = _ask(backend, model, "Отвечай одним коротким словом.",
                    "Скажи: готова", max_tokens=24)
    p["alive"] = bool(text)
    p["ping_s"] = round(dt, 2)
    if text:
        p["tps"] = round((len(text) / 4) / dt, 1)  # грубо, ~4 симв/ток

    # think_leak по ответу ping (мы просили enable_thinking=false)
    low = text.lower()
    p["think_leak"] = ("<think>" in low or low.startswith("thinking")
                       or "thinking process" in low)

    # 2) big_prompt: боевой размер системного промпта. Пустой ответ при
    # живом ping = молчаливое переполнение окна (класс багов «0 токенов»).
    target = int(CFG.get("llm.context_chars", 12000))
    budgets = sorted({target, 8000, 5000, 3000}, reverse=True)
    working = None
    for b in budgets:
        filler = (_FILLER * (b // len(_FILLER) + 1))[:b - 300]
        sys_prompt = ("Ты голосовой ассистент. Отвечай одним коротким "
                      "словом.\n\n" + filler)
        try:
            text, _ = _ask(backend, model, sys_prompt, "Скажи: слышу",
                           max_tokens=24, timeout=180)
        except Exception:
            text = ""
        if text:
            working = b
            break
    p["context_chars"] = None if working == budgets[0] else working
    p["big_prompt_ok"] = working == budgets[0]
    if working is None:
        # даже 3000 молчит — модель/бэкенд нездоровы, паспорт это фиксирует
        p["big_prompt_ok"] = False
    return p


def ensure_async(backend: str, model: str):
    """Запустить пробы в фоне, если паспорта ещё нет. Зовётся из warmup()."""
    if backend == "cloud" or not model:
        return
    if get(model) is not None or model in _probing:
        return

    def run():
        _probing.add(model)
        try:
            # НЕ лезем в горячие минуты старта: сразу после прогрева на GPU
            # толкучка (torch.compile TTS, холодные кэши), а пробы ещё и
            # сбрасывают KV-кэш модели — первые ответы пользователю тормозят
            # (инцидент 2026-07-23 02:11-02:14: prefill по 15-18с, пока TTS
            # компилировалась; к 02:16 — ответы за 1-2с). Паспорт — дело
            # не срочное: ждём тишины.
            time.sleep(180)
            if get(model) is not None:  # пока ждали — кто-то уже прощупал
                return
            if log:
                log.info("Паспорт: прощупываю %s/%s…", backend, model)
            p = _probe(backend, model)
            with _lock:
                d = _load()
                d[model] = p
                _save(d)
            if log:
                if not p.get("big_prompt_ok"):
                    log.warning(
                        "Паспорт %s: МОЛЧИТ на большом промпте (класс багов "
                        "«0 токенов»). Рабочий бюджет: %s символов — история "
                        "будет резаться под него. Если это LM Studio — "
                        "подними там Context Length до 8-16k, и станет "
                        "просторнее.", model, p.get("context_chars"))
                log.info("Паспорт %s: %s", model,
                         json.dumps(p, ensure_ascii=False))
        except Exception as e:
            if log:
                log.warning("Паспорт %s: пробы не удались (%s) — попробую "
                            "при следующем прогреве", model, e)
        finally:
            _probing.discard(model)

    threading.Thread(target=run, daemon=True).start()


def reprobe(model: str):
    """Стереть паспорт — при следующем прогреве модель прощупается заново."""
    with _lock:
        d = _load()
        d.pop(model, None)
        _save(d)
