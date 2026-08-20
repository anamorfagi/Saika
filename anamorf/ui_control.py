"""Сайка управляет собственным интерфейсом.

ЗАЧЕМ. Владелец: «прошу её взять модель поумнее — она находит её в списке и
переключает; или сама выбирает, если я не назвал конкретную». Без этого,
чтобы сменить мозги, надо встать с дивана и лезть мышкой в меню — ровно то,
от чего весь разговор голосом и затевался.

ПОЧЕМУ НЕ ПРОСТО «ПЕРЕКЛЮЧИ ПО ИМЕНИ». Моделей у владельца три десятка,
имена у них нечеловеческие (google/gemma-4-12b-qat), и голосом их не
произнести. Поэтому здесь два входа: точное имя, если назвали, и намерение
(«поумнее», «побыстрее», «со зрением») — тогда выбираем сами по тому, что
уже измерено: ручные оценки владельца, паспорт модели, скорость, влезает ли
в видеопамять.

ЧЕГО ЗДЕСЬ НЕТ. Ничего, что нельзя откатить одной фразой. Переключилась не
туда — «верни обратно», и всё. Поэтому смена модели относится к обратимым
действиям (риск 2 в anamorf/trust.py), а не к «сделать».
"""
from __future__ import annotations

import logging

from anamorf.config import CFG

log = logging.getLogger("saika.ui")

# что запомнили перед переключением — чтобы «верни как было» работало
_PREV: dict = {}


def _vram_free_mb() -> int:
    try:
        from anamorf import system_control
        free, _total = system_control.gpu_mem()
        return int(free)
    except Exception:
        return 0


def _catalog() -> list:
    """Модели с тем, что о них известно: оценка, скорость, вес, зрение."""
    from anamorf import ratings
    from anamorf.llm import manager as llm
    try:
        from anamorf.llm import passport
    except Exception:
        passport = None

    scores = ratings.llm_scores() or {}
    manual = ratings.manual_scores() or {}
    tps = ratings.llm_tps() or {}
    free_mb = _vram_free_mb()
    out = []
    for m in llm.list_models():
        name = m.get("name", "")
        if not name:
            continue
        size_mb = int((m.get("size") or 0) / 1048576)
        caps = m.get("caps") or {}
        p = {}
        if passport:
            try:
                p = passport.get(name) or {}
            except Exception:
                p = {}
        try:
            from anamorf import model_dossier as _dos
            _dos.ensure(name, m.get("backend", ""), caps, size_mb,
                        m.get("base_url", ""))
            rel = _dos.reliability(name)
            cost = _dos.cost_of(name, m.get("backend", ""),
                                m.get("base_url", ""))
            crank = _dos.COST_RANK.get(cost, 1)
        except Exception:
            rel, cost, crank = 5, "free", 0
        out.append({
            "name": name, "backend": m.get("backend", ""),
            "reliability": rel, "cost": cost, "cost_rank": crank,
            "size_mb": size_mb,
            "manual": int(manual.get(name) or 0),
            "auto": float(scores.get(name) or 0),
            "tps": float(tps.get(name) or 0),
            "vision": bool(caps.get("vision") or p.get("vision")),
            "cloud": m.get("backend") == "cloud",
            # влезет ли: облаку видеопамять не нужна, у локальной берём вес
            # файла с запасом на контекст (грубо, но честнее, чем ничего)
            "fits": (m.get("backend") == "cloud" or not size_mb
                     or not free_mb or size_mb * 1.2 <= free_mb),
        })
    return out


def _smart_key(m: dict) -> tuple:
    """Насколько модель стоит того, чтобы ей доверить задачу.

    2026-07-26: раньше первой шла скорость — и мелкая бодрая модель
    оказывалась «лучшей», хотя врала о выполненной работе. Теперь первая
    ось — НАДЁЖНОСТЬ из досье, а при равной надёжности предпочитаем
    дешёвую: платные это подстраховка, а не первый выбор.
    """
    return (m.get("reliability", 5), -m.get("cost_rank", 1),
            m["manual"], m["auto"], m["size_mb"])


def model_list() -> str:
    """Компактная сводка для модели — она по ней и выбирает."""
    items = _catalog()
    if not items:
        return "список моделей пуст — ни один движок не отвечает"
    cur = CFG.get("llm.model", "")
    items.sort(key=_smart_key, reverse=True)
    lines = []
    for m in items[:30]:
        bits = [m["name"], m["backend"],
                f"надёжность {m.get('reliability', 5)}/10"]
        if m.get("cost") == "paid":
            bits.append("ПЛАТНАЯ")
        elif m.get("cost") == "metered":
            bits.append("бесплатный тир")
        if m["manual"]:
            bits.append(f"оценка владельца {m['manual']}/10")
        if m["tps"]:
            bits.append(f"~{round(m['tps'])} ток/с")
        if m["size_mb"]:
            bits.append(f"{round(m['size_mb'] / 1024, 1)} ГБ")
        if m["vision"]:
            bits.append("со зрением")
        if not m["fits"]:
            bits.append("НЕ влезет в видеопамять")
        if m["name"] == cur:
            bits.append("← сейчас")
        lines.append(" · ".join(bits))
    return "\n".join(lines)


def _pick(want: str, items: list) -> dict | None:
    cur = CFG.get("llm.model", "")
    pool = [m for m in items if m["name"] != cur and m["fits"]]
    if not pool:
        return None
    if want == "faster":
        # без замера скорости судить не по чему — такие в конец
        pool.sort(key=lambda m: (m["tps"] or 0, -m["size_mb"]), reverse=True)
        return pool[0]
    if want == "vision":
        seeing = [m for m in pool if m["vision"]]
        if not seeing:
            return None
        seeing.sort(key=_smart_key, reverse=True)
        return seeing[0]
    pool.sort(key=_smart_key, reverse=True)
    return pool[0]


def _match(name: str, items: list) -> dict | None:
    q = (name or "").strip().lower()
    if not q:
        return None
    for m in items:                       # точное совпадение
        if m["name"].lower() == q:
            return m
    hits = [m for m in items if q in m["name"].lower()]
    if hits:
        hits.sort(key=_smart_key, reverse=True)
        return hits[0]
    # голосом имена коверкаются: «джемма 12», «квен кодер» — ищем по кускам
    words = [w for w in q.replace("/", " ").split() if len(w) > 2]
    if words:
        scored = [(m, sum(1 for w in words if w in m["name"].lower()))
                  for m in items]
        scored = [(m, n) for m, n in scored if n]
        if scored:
            scored.sort(key=lambda p: (-p[1], -_smart_key(p[0])[0]))
            return scored[0][0]
    return None


def model_switch(name: str = "", want: str = "") -> str:
    from anamorf.llm import manager as llm
    items = _catalog()
    if not items:
        return "не вижу ни одной модели — движки не отвечают"

    # «верни как было» — отдельный случай, без него откат сложнее просьбы
    if (name or "").strip().lower() in ("назад", "обратно", "как было",
                                        "previous", "back") and _PREV:
        name, want = _PREV.get("model", ""), ""

    m = _match(name, items) if name else None
    if m is None:
        m = _pick(want or "smarter", items)
    if m is None:
        if want == "vision":
            return ("Ни одна доступная модель не умеет смотреть на "
                    "картинки — переключаться не на что.")
        return ("Подходящей модели не нашла: либо это всё, что есть, либо "
                "остальные не влезают в видеопамять.")
    if m["name"] == CFG.get("llm.model", ""):
        return f"Уже на {m['name']} — переключаться некуда."

    _PREV.update(model=CFG.get("llm.model", ""),
                 backend=CFG.get("llm.backend", ""))
    try:
        if m["backend"] == "cloud":
            if not llm.use_cloud(m["name"]):
                return f"«{m['name']}» настроена не полностью — нет адреса."
        CFG.set("llm.backend", m["backend"])
        CFG.set("llm.model", m["name"])
    except Exception as e:
        log.exception("не смогла переключить модель")
        return f"не получилось переключиться: {e}"

    # прогрев в фоне: он может качать веса минутами, а ответить надо сейчас
    import threading
    threading.Thread(target=llm.switch_model,
                     args=(m["backend"], m["name"]), daemon=True).start()

    why = [f"надёжность {m.get('reliability', 5)}/10"]
    if m.get("cost") == "paid":
        why.append("платная — беру как подстраховку")
    if m["manual"]:
        why.append(f"твоя оценка {m['manual']}/10")
    if m["tps"]:
        why.append(f"~{round(m['tps'])} ток/с")
    if m["vision"]:
        why.append("со зрением")
    tail = (" (" + ", ".join(why) + ")") if why else ""
    return (f"Переключилась на {m['name']}{tail}. Греется — первый ответ "
            "может быть медленнее обычного. Скажешь «верни как было» — "
            f"вернусь на {_PREV['model'] or 'прежнюю'}.")
