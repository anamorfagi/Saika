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

from anamorf.config import CFG, ROOT, DATA_ROOT

try:
    import logging
    log = logging.getLogger("saika.passport")
except Exception:  # pragma: no cover
    log = None

PATH = DATA_ROOT / "data" / "model_passports.json"
VERSION = 2  # v2 (2026-07-23): + проба формата tool-вызовов (tools_native)
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
    from anamorf.llm import manager  # лениво: не завязываться при импорте
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


def _wait_quiet(backend: str, model: str, max_wait: int = 300) -> bool:
    """Ждать, пока живой чат отпустит бэкенд/модель (manager.is_busy).
    True — дождались тишины; False — потолок вышел, а модель всё ещё занята
    (проба этот шаг пропускает/прерывает, а не лезет в драку за модель)."""
    try:
        from anamorf.llm import manager as _mgr
    except Exception:
        return True
    waited = 0
    while _mgr.is_busy(backend, model) and waited < max_wait:
        time.sleep(3)
        waited += 3
    return not _mgr.is_busy(backend, model)


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
        # живой диалог мог возобновиться МЕЖДУ попытками (пользователь
        # снова заговорил, пока проба перебирала бюджеты) — не лезем
        # драться за ту же модель, ждём тишины ещё раз перед каждым шагом
        if not _wait_quiet(backend, model):
            break
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

    # 3) tools: родной ли function calling у СВЯЗКИ модель+бэкенд.
    # У каждой модели своя выучка формата вызова (OpenAI tool_calls /
    # Harmony «to=web_search json{...}» у gpt-oss / голый JSON у llama3.2),
    # и часть бэкендов её шаблон не переводит в нормальные tool_calls —
    # тогда «вызов» утекает текстом в чат. Прощупываем и записываем.
    _wait_quiet(backend, model)  # снова могли не успеть — та же осторожность
    try:
        p["tools_native"] = _probe_tools(backend, model)
    except Exception:
        p["tools_native"] = None
    return p


_TOOLS_PROBE_SCHEMA = [{
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Поиск в интернете по текстовому запросу",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}}]

# маркеры «вызова текстом»: Harmony (gpt-oss), спецтокены, голый JSON
_PSEUDO_MARKERS = ("to=", "<|", "call:", '"name"')


def _probe_tools(backend: str, model: str):
    """True — модель вернула нормальные tool_calls; False — написала вызов
    ТЕКСТОМ (утёк бы в чат); None — не определить (ответила просто словами,
    без попытки вызова — тоже нормально)."""
    from anamorf.llm import manager
    msgs = [{"role": "system",
             "content": ("Ты голосовой ассистент с инструментами. Если "
                         "нужен свежий факт из интернета — вызови "
                         "web_search.")},
            {"role": "user",
             "content": "Загугли, какая завтра погода в Самаре."}]
    if backend == "ollama":
        r = requests.post(manager._ollama_url() + "/api/chat",
                          json={"model": model, "messages": msgs,
                                "stream": False,
                                "tools": _TOOLS_PROBE_SCHEMA,
                                "options": {"num_predict": 200}},
                          timeout=120)
        r.raise_for_status()
        m = r.json().get("message") or {}
        if m.get("tool_calls"):
            return True
        text = (m.get("content") or "").lower()
    else:  # lmstudio / locallm — OpenAI-диалект
        url = (manager._locallm_url() if backend == "locallm"
               else manager._lmstudio_url())
        payload = {"model": model, "messages": msgs, "stream": False,
                   "max_tokens": 200, "tools": _TOOLS_PROBE_SCHEMA,
                   "chat_template_kwargs": {"enable_thinking": False}}
        r = requests.post(url + "/v1/chat/completions", json=payload,
                          timeout=120)
        r.raise_for_status()
        ch = (r.json().get("choices") or [{}])[0]
        m = ch.get("message") or {}
        if m.get("tool_calls"):
            return True
        text = (m.get("content") or "").lower()
    if any(k in text for k in _PSEUDO_MARKERS):
        return False
    return None


def _apply_tools_verdict(model: str, native):
    """Подстройка конвейера под вердикт пробы: «безрукие» модели — в
    llm.tools_broken (сервер сам ищет за них, см. main.py), а модели с
    подтверждённым родным форматом — ИЗ чёрного списка (самолечение:
    вдруг попала туда из-за старого бага шаблона)."""
    broken = set(CFG.get("llm.tools_broken", []))
    if native is False and model not in broken:
        broken.add(model)
        CFG.set("llm.tools_broken", sorted(broken))
        if log:
            log.warning("Паспорт %s: пишет tool-вызовы ТЕКСТОМ — добавила "
                        "в tools_broken, искать за неё будет сервер", model)
    elif native is True and model in broken:
        broken.discard(model)
        CFG.set("llm.tools_broken", sorted(broken))
        if log:
            log.info("Паспорт %s: родной function calling подтверждён — "
                     "убрала из tools_broken", model)


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
            # 2026-07-23: 180с фиксированной паузы было НЕДОСТАТОЧНО, если
            # пользователь как раз в эти минуты живо тестирует свежепереключённую
            # модель (обычный случай!) — проба стартовала ПРЯМО поверх живого
            # диалога и дралась с ним за одну и ту же модель в Ollama/LM Studio
            # (лог: «думала 76.3с»/«думала 253.2с» на gemma4:26b, ping_s=40.8
            # у gemma4:12b — ровно во время проб). Теперь ждём НАСТОЯЩЕЙ тишины
            # (manager.is_busy метится живым чат-стримом на каждый токен), а не
            # просто истечения таймера — с потолком ожидания в 30 минут.
            _wait_quiet(backend, model, max_wait=1800)
            if get(model) is not None:  # пока ждали — кто-то уже прощупал
                return
            if log:
                log.info("Паспорт: прощупываю %s/%s…", backend, model)
            p = _probe(backend, model)
            with _lock:
                d = _load()
                d[model] = p
                _save(d)
            _apply_tools_verdict(model, p.get("tools_native"))
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
