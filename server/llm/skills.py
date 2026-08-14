"""ПАСПОРТ УМЕНИЙ МОДЕЛИ: что она умеет и насколько хорошо (2026-08-14).

ПРОСЬБА ВЛАДЕЛЬЦА, дословно:

    «она должна не втупую переключать модели, а точно знать, что она может
     с помощью какой модели делать, какая лучше в той или иной задаче.
     нужно делать при установке моделей краткое описание и добавление
     меток у модели — её мультимодальные возможности и насколько хорош их
     рейтинг, чтобы Сайка могла юзать нужный элемент во время её ответа
     одновременно или сама смотрела, если чего-то недоступно»

ПОЧЕМУ ЭТО ОТДЕЛЬНЫЙ МОДУЛЬ, А НЕ ЕЩЁ ОДНО ПОЛЕ В BRAINS. Про каждую модель
у нас уже копится знание, но оно РАЗБРОСАНО и отвечает на разные вопросы:

    brains.RANK        — насколько умная (одно число, «ум вообще»)
    passport.py        — живая ли, скорость, окно, родные ли tool-вызовы
                         (это ЗАМЕРЫ, добываются пробой на этой машине)
    capabilities.py    — видит ли картинки (наблюдение + подсказки в имени)
    ratings.py         — ток/с и ручные палочки владельца

Ни один из них не отвечает на вопрос «кому отдать ЭТУ задачу». «Ум 8» не
говорит, умеет ли она смотреть; «видит картинки» не говорит, стоит ли ей
доверить длинный документ. Здесь всё сводится в ОДНУ карточку на модель:
короткое человеческое описание, метки умений и оценка 1..10 по каждому.

ОТКУДА БЕРУТСЯ ОЦЕНКИ, по убыванию доверия:
  1. ЗАМЕР на этой машине (паспорт, наблюдения capabilities) — факт.
  2. РУЧНАЯ оценка владельца — его слово о его же машине.
  3. ТАБЛИЦА СЕМЕЙСТВ ниже — общее знание про породу модели.
Догадка НИКОГДА не перебивает замер: если пробой выяснено, что родных
tool-вызовов нет, никакая таблица этого не отменит.

ЧЕГО ЗДЕСЬ НЕТ. Мы не выдумываем цифры бенчмарков, которых не мерили.
Оценка — это грубая полка (1..10), пригодная ровно для одного решения:
кому отдать задачу. Врать точностью до десятых тут некому и незачем.
"""
from __future__ import annotations

import logging

from server.config import CFG

log = logging.getLogger("saika.skills")

# УМЕНИЯ. Список намеренно короткий: каждое должно ОТВЕЧАТЬ НА ВОПРОС
# «кому отдать эту задачу», иначе метке здесь не место.
SKILLS = {
    "vision":  "смотреть на картинки и экран",
    "tools":   "вызывать инструменты (руки)",
    "code":    "код и разметка",
    "russian": "живой русский язык",
    "long":    "длинный контекст, большие документы",
    "fast":    "отвечать мгновенно (голосовой режим)",
    "smart":   "рассуждать, планировать, разбираться",
}

# ТАБЛИЦА СЕМЕЙСТВ. Подстрока в имени -> (описание, {умение: оценка}).
# Порядок важен, как в RANK: частное имя выше общего. Оценки тут —
# ОБЩЕЕ ЗНАНИЕ О ПОРОДЕ, а не замер; замер всегда сильнее (см. card()).
FAMILY = [
    ("qwen3-vl", ("Qwen VL — зрячая: разбирает скриншоты, схемы, текст на "
                  "картинке", {"vision": 9, "russian": 7, "code": 7})),
    ("qwen2-vl", ("Qwen2 VL — зрячая", {"vision": 8, "russian": 6})),
    ("qwen3-coder", ("Qwen Coder — заточена под код",
                     {"code": 9, "russian": 6})),
    ("qwen", ("Qwen — крепкий универсал, хорошо знает русский",
              {"russian": 8, "code": 7, "tools": 7})),
    ("llava", ("LLaVA — только смотреть, разговор слабый",
               {"vision": 7, "russian": 3, "smart": 3})),
    ("gemma", ("Gemma — быстрая и лёгкая, для коротких ответов",
               {"fast": 8, "russian": 6})),
    ("gpt-oss", ("GPT-OSS — рассуждает вслух, tool-вызовы в своём формате",
                 {"smart": 7, "tools": 5})),
    ("gpt-4.1-mini", ("GPT-4.1 mini — быстрая и зрячая",
                      {"vision": 8, "fast": 7, "code": 7})),
    ("gpt-4.1", ("GPT-4.1 — сильный универсал, видит картинки",
                 {"vision": 9, "code": 9, "smart": 9, "tools": 9})),
    ("gpt-5", ("GPT-5 — сильнейший универсал",
               {"vision": 9, "code": 10, "smart": 10, "tools": 9})),
    ("claude", ("Claude — длинные тексты и аккуратные руки",
                {"code": 9, "smart": 10, "long": 10, "tools": 9})),
    ("gemini", ("Gemini — зрячая, очень длинный контекст",
                {"vision": 9, "long": 10, "smart": 8})),
    ("llama-3.2-11b-vision", ("Llama 3.2 Vision (Cloudflare) — зрячая, "
                              "бесплатная на своём аккаунте CF",
                              {"vision": 7, "fast": 6})),
    ("mistral-medium", ("Mistral Medium 3 — универсал, ПОНИМАЕТ КАРТИНКИ",
                        {"russian": 7, "tools": 7, "vision": 7})),
    ("mistral-small", ("Mistral Small — быстрая, звёзд с неба не хватает",
                       {"fast": 7, "russian": 6})),
    ("mistral", ("Mistral — универсал", {"russian": 6, "tools": 7})),
    ("gigachat", ("GigaChat — лучший русский из доступных, руки слабее",
                  {"russian": 10, "tools": 5, "smart": 7})),
    ("deepseek", ("DeepSeek — сильна в коде и рассуждении",
                  {"code": 9, "smart": 9})),
    ("kimi", ("Kimi — очень длинный контекст",
              {"long": 10, "smart": 8})),
    ("llama-3.3-70b", ("Llama 3.3 70B — крепкий универсал без зрения",
                       {"vision": 0, "smart": 8, "code": 7})),
    ("llama", ("Llama — универсал", {"smart": 6})),
    ("minimax", ("MiniMax — универсал", {"smart": 7})),
    ("glm", ("GLM — универсал, неплохой код", {"code": 8, "smart": 7})),
    ("nemotron", ("Nemotron — рассуждение", {"smart": 8})),
]

# слова в имени, по которым видно скорость/размер
_FAST_HINTS = ("flash", "mini", "lite", "turbo", "instant", "e2b", "e4b",
               "1b", "2b", "3b", "4b")
_BIG_HINTS = ("70b", "72b", "120b", "397b", "max", "large", "ultra", "pro")


def _family(model: str):
    low = (model or "").lower()
    for pat, val in FAMILY:
        if pat in low:
            return val
    return ("", {})


def _clamp(x) -> int:
    try:
        return max(0, min(10, int(round(float(x)))))
    except (TypeError, ValueError):
        return 0


def card(model: str, backend: str = "") -> dict:
    """Всё, что мы знаем про эту модель, одной карточкой.

    Возвращает {model, backend, desc, tags, skills:{...}, why:{...}} —
    where `why` говорит, ОТКУДА взялась каждая оценка: «замер», «владелец»
    или «порода». Без этого человек не может спорить с числом."""
    low = (model or "").lower()
    desc, fam = _family(model)
    sk: dict = {}
    why: dict = {}

    def put(name, val, src):
        v = _clamp(val)
        if v <= 0:
            return
        # замер сильнее породы, слово владельца сильнее породы, но не
        # сильнее замера: он оценивает «нравится», а не «умеет»
        rank = {"порода": 0, "владелец": 1, "замер": 2}
        if name in sk and rank[why[name]] > rank[src]:
            return
        sk[name], why[name] = v, src

    for k, v in fam.items():
        put(k, v, "порода")

    # ── общий ум из лестницы: он же основа для smart и подпорка остальному
    try:
        from server.llm import brains
        r = brains.rank_of(model, backend)
        sk["smart"], why["smart"] = _clamp(r), "порода"
        for k in ("code", "russian", "tools", "long"):
            if k not in sk:
                put(k, max(1, r - 2), "порода")
    except Exception as e:
        log.debug("ранг для карточки не взялся: %s", e)

    # ── ЗАМЕРЫ. Они перебивают всё, потому что это факт про эту машину
    try:
        from server import capabilities as caps
        v = caps.vision(model)
        if v is True:
            put("vision", max(7, sk.get("vision", 0)), "замер")
        elif v is False:
            sk["vision"], why["vision"] = 0, "замер"
    except Exception:
        pass
    try:
        from server.llm import passport as _pp
        p = _pp.get(model) or {}
        if p.get("tools_native") is True:
            put("tools", max(8, sk.get("tools", 0)), "замер")
        elif p.get("tools_native") is False:
            # вызовы утекают текстом — руками пользоваться можно, но плохо
            sk["tools"], why["tools"] = min(4, sk.get("tools", 4)), "замер"
        cc = p.get("context_chars")
        if cc:
            put("long", 3 if cc < 8000 else 5 if cc < 20000 else 8, "замер")
        tps = p.get("tps") or 0
        if tps:
            put("fast", 3 if tps < 10 else 6 if tps < 30 else 9, "замер")
    except Exception:
        pass
    try:
        from server import ratings
        tps = (ratings.llm_tps() or {}).get(model, 0)
        if tps:
            put("fast", ratings.score_of(tps), "замер")
        # РУЧНАЯ ОЦЕНКА НЕ ИДЁТ В «УМ» НАПРЯМУЮ (2026-08-14, стенд поймал:
        # у gemma-4-e4b стояла ручная девятка — и карточка объявила
        # четырёхмиллиардную модель умнее GPT-4.1. Это ровно та ошибка, от
        # которой уже защищён brains.rank_of: палочки владельца значат «моя
        # рабочая лошадка», а не «умнее облака». Ум берём оттуда, где он
        # уже усреднён с таблицей; сюда ручная оценка попадает как отметка
        # ПРЕДПОЧТЕНИЯ и только если модель иначе вообще без оценки.)
        man = (ratings.manual_scores() or {}).get(model)
        if man and "fast" not in why:
            put("fast", man, "владелец")
    except Exception:
        pass

    # ── подсказки из самого имени, если ничего другого нет
    if "fast" not in sk:
        put("fast", 8 if any(h in low for h in _FAST_HINTS) else 5, "порода")
    if "long" not in sk:
        put("long", 8 if any(h in low for h in _BIG_HINTS) else 5, "порода")
    if "vision" not in sk:
        sk["vision"], why["vision"] = 0, "порода"

    tags = sorted(k for k, v in sk.items() if v >= 7)
    if not desc:
        best = max(sk.items(), key=lambda kv: kv[1])[0] if sk else ""
        desc = ("сильна в: " + SKILLS.get(best, best)) if best else "неизвестна"
    return {"model": model, "backend": backend, "desc": desc,
            "tags": tags, "skills": sk, "why": why}


def best_for(skill: str, min_score: int = 6, exclude=()) -> dict | None:
    """Кому отдать задачу этого рода. None — некому.

    Берём из живой лестницы (там уже отфильтрованы больные и платные) и
    сортируем по УМЕНИЮ, а не по общему уму: для «посмотреть на картинку»
    зрячая четвёрка полезнее слепой десятки."""
    try:
        from server.llm import brains
        cands = brains.ladder()
    except Exception as e:
        log.debug("лестница для best_for недоступна: %s", e)
        return None
    skip = {tuple(x) for x in (exclude or ())}
    best, bs = None, 0
    for c in cands:
        if (c["backend"], c["model"]) in skip:
            continue
        sc = card(c["model"], c["backend"])["skills"].get(skill, 0)
        if sc > bs:
            best, bs = c, sc
    if best is None or bs < min_score:
        return None
    out = dict(best)
    out["skill_score"] = bs
    return out


def block() -> str:
    """Короткая строка для промпта: что она может и чьими руками.

    Владелец: «чтобы Сайка могла юзать нужный элемент во время её ответа
    ИЛИ САМА СМОТРЕЛА, если чего-то недоступно». Для этого она должна
    знать не только «я не умею», но и «умеет вот кто» — иначе честное «не
    вижу» превращается в тупик вместо следующего шага."""
    if not CFG.get("skills.block", True):
        return ""
    try:
        from server.llm import brains
        b, m = brains.current()
    except Exception:
        return ""
    me = card(m, b)
    lines = ["### Что ты умеешь ПРЯМО СЕЙЧАС (факт, не догадка)",
             f"- сейчас за рулём: {m} — {me['desc']}"]
    for key, human in SKILLS.items():
        mine = me["skills"].get(key, 0)
        if mine >= 6:
            continue                      # своё умение — молча пользуйся
        helper = best_for(key, min_score=max(6, mine + 2),
                          exclude=[(b, m)])
        if helper:
            lines.append(
                f"- {human}: сама слабо ({mine}/10), но это умеет "
                f"{helper['model']} ({helper['skill_score']}/10) — система "
                "подключит её сама, обещать человеку не надо, просто делай")
        elif mine <= 1:
            lines.append(f"- {human}: не умеешь ни ты, ни парк — скажи честно")
    return "\n".join(lines) if len(lines) > 2 else ""
