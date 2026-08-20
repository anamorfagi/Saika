"""Реестр способностей моделей — мозг оркестратора Сайки.

Оболочка Сайки — умный модуль управления всеми частями системы: она знает,
какая модель что умеет, и подстраивает сценарии под способности:
- модель без инструментов -> сервер сам ищет/оперирует файлами (main.py)
- модель без зрения -> честно говорит «не вижу» и одалживает глаза у
  vision-модели из парка (OCR картинки чужой моделью)
- умеет сама -> никакие скрипты-костыли не вмешиваются

Как выясняются способности (в порядке приоритета):
1. ОПЫТ — результат реальных вызовов (Ollama 400 на картинку -> зрения нет;
   успешный ответ с картинкой -> зрение есть; кривые tool_calls ->
   llm.tools_broken). Опыт записывается автоматически и главнее всего.
2. Эвристика по имени (llava/-vl/4.6v/gemma-4... -> скорее видит).
Хранилище: data/model_caps.json (per-machine).
"""
import json
import threading
import time

from anamorf.config import CFG, ROOT

import logging

log = logging.getLogger("saika.caps")

PATH = ROOT / "data" / "model_caps.json"
_lock = threading.Lock()

# скорее ВИДЯТ (мультимодальные семейства)
_VISION_HINTS = ("llava", "vision", "-vl", "vl-", "4.6v", "qwen2-vl",
                 "qwen2.5-vl", "minicpm-v", "moondream", "pixtral",
                 "gemma-3", "gemma-4", "glm-4v", "glm-4.6v", "internvl")
# заведомо БЕЗ зрения
# «mistral» убран из слепых (2026-08-15): Mistral Medium 3 мультимодален,
# а подсказка по подстроке записывала в слепые ВСЁ семейство — и Сайка ни
# разу не попробовала показать кадр своей же основной модели. Незнание
# лучше ложного знания: теперь попробует, опыт запишется сам (note()).
_TEXT_HINTS = ("llama3.2", "llama-3.2", "llama3.1", "llama-3.1",
               "phi-3", "qwen2.5:", "qwen2.5-instruct", "deepseek-r1")


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


def note(model: str, key: str, value):
    """Записать ОПЫТ: caps.note('llama3.2:latest', 'vision', False)."""
    if not model:
        return
    with _lock:
        d = _load()
        e = d.setdefault(model, {})
        if e.get(key) != value:
            e[key] = value
            e["ts"] = time.time()
            _save(d)


def vision(model: str):
    """True/False/None(неизвестно — пробуем, опыт запишется сам)."""
    if not model:
        return None
    exp = _load().get(model, {}).get("vision")
    if exp is not None:
        return exp
    low = model.lower()
    if any(h in low for h in _VISION_HINTS):
        return True
    if any(h in low for h in _TEXT_HINTS):
        return False
    return None


# МОДЕЛИ, КОТОРЫЕ «ВЫЗЫВАЮТ» ИНСТРУМЕНТЫ СЛОВАМИ (2026-08-19).
# GigaChat не умеет настоящих tool-calls и вместо отказа сочиняет отчёт:
# «Окно с элементами управления успешно создано», «Операция прошла
# успешно», «Перешла на вкладку Pintros» — при том, что ничего не
# происходило. Хуже того, как «самый умный из живых» он забирал себе
# агент-цикл и командовал руками: за один вечер запустил владельцу
# After Effects и лаунчер игры, которых тот не просил.
#
# Болтать он может сколько угодно — это его сильная сторона. Руки — нет.
# Вернуть можно: llm.trust_liars=true в конфиге.
_LIARS = ("gigachat",)


def tools_ok(model: str) -> bool:
    if model in set(CFG.get("llm.tools_broken", [])):
        return False
    if CFG.get("llm.trust_liars", False):
        return True
    return not any(h in (model or "").lower() for h in _LIARS)


def pick_vision_model(models: list, loaded=()):
    """Лучшая зрячая модель парка для «одолжить глаза» (OCR и т.п.).
    models: [{'backend':..., 'name':...}]. Предпочитаем уже загруженные."""
    # ОБЛАЧНЫЕ ЗРЯЧИЕ ТОЖЕ ГОДЯТСЯ (2026-08-14). Список кандидатов был
    # ограничен домашним парком — а у владельца зрячие модели живут в
    # облаке (qwen3-vl, gpt-4.1, gemini), и «одолжить глаза» было не у
    # кого: на просьбу посмотреть картинку она честно отвечала «разобрать
    # некому», имея под рукой сразу несколько зрячих. Сперва спрашиваем
    # реестр умений — он смотрит всю лестницу и сортирует по ЗРЕНИЮ, а не
    # по общему уму; не нашёл — работает старый разбор парка, как было.
    try:
        from anamorf.llm import skills as _sk
        best = _sk.best_for("vision", min_score=6)
        if best:
            return best["backend"], best["model"]
    except Exception as e:
        log.debug("реестр умений недоступен (%s) — беру из парка", e)
    cands = []
    for m in models:
        if m.get("backend") not in ("ollama", "lmstudio"):
            continue
        name = m.get("name", "")
        if "embed" in name.lower():
            continue
        v = vision(name)
        if v:
            cands.append((name not in set(loaded), m["backend"], name))
    if not cands:
        return None
    cands.sort()   # загруженные первыми
    _, backend, name = cands[0]
    return backend, name


def summary() -> dict:
    """Для UI/отладки: {model: {vision: ..., tools: ...}}."""
    d = _load()
    out = {}
    for m, e in d.items():
        out[m] = {"vision": e.get("vision"), "tools": tools_ok(m)}
    return out
