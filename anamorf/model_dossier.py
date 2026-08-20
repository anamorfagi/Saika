"""Досье на модели: надёжность, цена, умения — то, чего нет в рейтинге.

ЗАЧЕМ. До сих пор модели ранжировались по ОДНОМУ числу — токенов в
секунду. Владелец точно поймал, где это врёт:

  «4b высоко в рейтинге только из-за того, что она хорошо отвечает и
   достаточно быстра без настроек. Но она крайне часто ошибалась или
   наоборот не делала под видом что сделала — то есть доверие к ней на
   самом деле низкое».

Скорость и надёжность — разные оси, и вторая важнее. Модель, которая
бодро отвечает «запустила Blender», ничего при этом не запустив, хуже
медленной и честной: первая создаёт иллюзию работы, а расхлёбывать
человеку.

ТРИ ОСИ, которые здесь ведутся:

  надёжность  1..10  делает ли она то, что говорит
  цена        free / paid / metered — жечь ли на ней бюджет
  умения      зрение, инструменты, русский, размер окна

НАДЁЖНОСТЬ КОПИТСЯ САМА. Главный сигнал — «сказала, что сделала, но не
сделала»: реплика содержит «запустила / открыла / свернула», а ни одного
инструмента за ход не вызвано. Это ловится точно и без участия человека.
Второй сигнал — ошибка инструмента. Третий — прямая жалоба владельца
(«ты ошиблась», «ты не сделала»). Ручная оценка владельца перебивает всё:
он живёт с этими моделями и видит то, чего не видит счётчик.

ПРО ДЕНЬГИ. Владелец: «деньги не безграничные, Kimi платная — она
подстраховка, а не первоочередная». Поэтому у каждой модели есть цена, а
у Сайки — правило: сначала бесплатные, платные когда задача действительно
не даётся или человек попросил сам.
"""
from __future__ import annotations

import json
import logging
import re
import time

from anamorf.config import CFG, ROOT

log = logging.getLogger("saika.dossier")

PATH = ROOT / "data" / "model_dossier.json"
_cache: dict = {}
_loaded = 0.0

# Цена по провайдеру. Не выдумываем тарифы (они меняются каждый месяц) —
# держим только категорию, потому что решение принимается именно по ней.
#   free    — свой компьютер или бесплатный тир без карты
#   metered — бесплатный тир есть, но он кончается
#   paid    — платит владелец за каждый запрос
COST_BY_HOST = (
    ("gigachat.devices.sberbank.ru", "metered"),
    ("api.giga.chat", "metered"),
    ("api.mistral.ai", "metered"),
    ("models.github.ai", "metered"),
    ("api.groq.com", "metered"),
    ("api.cerebras.ai", "metered"),
    ("generativelanguage.googleapis.com", "metered"),
    ("api.moonshot.ai", "paid"),
    ("api.openai.com", "paid"),
    ("api.anthropic.com", "paid"),
    ("api.deepseek.com", "paid"),
    ("openrouter.ai", "paid"),
)
COST_WORD = {"free": "бесплатно (свой ПК)",
             "metered": "бесплатный тир — кончается",
             "paid": "платная"}
COST_RANK = {"free": 0, "metered": 1, "paid": 2}

DEFAULT_RELIABILITY = 5


def _load() -> dict:
    global _cache, _loaded
    if _cache and time.time() - _loaded < 5:
        return _cache
    try:
        _cache = json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        _cache = {}
    _loaded = time.time()
    return _cache


def _save():
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(_cache, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except Exception as e:
        log.warning("досье не сохранилось: %s", e)


def cost_of(model: str, backend: str = "", base_url: str = "") -> str:
    if backend and backend != "cloud":
        return "free"
    manual = (_load().get(model) or {}).get("cost")
    if manual:
        return manual
    url = (base_url or CFG.get("llm.cloud.base_url", "") or "").lower()
    for host, kind in COST_BY_HOST:
        if host in url:
            return kind
    return "paid" if backend == "cloud" else "free"


# ─────────── ЗАВОДИМ ДОСЬЕ САМИ, КАК ТОЛЬКО МОДЕЛЬ ПОЯВИЛАСЬ ───────────
# Владелец: «раз уж досье, то оно должно быть автоматическим при появлении
# новой модели в списке». Иначе половина парка живёт на дефолтах, которых
# нет на диске, и никакая история по ним не копится.
#
# Стартовая надёжность — не выдумка: это то, что про модель уже известно
# ДО первого разговора. Облачная крупная начинает выше мелкой локальной,
# модель без рабочих инструментов — ниже всех, потому что обещать она
# может что угодно. Дальше цифра живёт своей жизнью и быстро перебивает
# любую догадку.
def _seed(name: str, backend: str, caps: dict, size_mb: int) -> dict:
    low = name.lower()
    if backend == "cloud":
        r = 6.0
    elif size_mb >= 20000:          # 20 ГБ+ — крупная локальная
        r = 5.5
    elif size_mb >= 7000:
        r = 5.0
    elif size_mb and size_mb < 4000:
        r = 4.0                     # совсем мелкая: бодрая, но врёт чаще
    else:
        r = 4.5
    if re.search(r"coder|code", low):
        r -= 0.3                    # кодовые модели плохо держат диалог
    if re.search(r"thinking|reason|-r1|qwq", low):
        r += 0.3
    return {"reliability": round(max(1.0, min(10.0, r)), 2),
            "manual": None, "lies": 0, "errors": 0, "wins": 0, "note": "",
            "first_seen": round(time.time()),
            "seeded": {"backend": backend, "size_mb": size_mb,
                       "vision": bool(caps.get("vision"))}}


def ensure(name: str, backend: str = "", caps: dict | None = None,
           size_mb: int = 0, base_url: str = "") -> dict:
    """Завести досье, если модели тут ещё не было. Возвращает запись."""
    if not name:
        return {}
    _load()
    if name in _cache:
        return get(name)
    rec = _seed(name, backend, caps or {}, int(size_mb or 0))
    rec["cost"] = cost_of(name, backend, base_url)
    _cache[name] = rec
    _save()
    log.info("Досье заведено: %s (надёжность %.1f, %s)", name,
             rec["reliability"], rec["cost"])
    return get(name)


def sync_all() -> int:
    """Пройтись по всему списку моделей и завести недостающие досье.
    Зовётся при старте и при каждом открытии списка в интерфейсе."""
    from anamorf.llm import manager as llm
    n = 0
    try:
        models = llm.list_models()
    except Exception as e:
        log.debug("список моделей недоступен: %s", e)
        return 0
    _load()
    for m in models:
        name = m.get("name", "")
        if name and name not in _cache:
            ensure(name, m.get("backend", ""), m.get("caps") or {},
                   int((m.get("size") or 0) / 1048576), m.get("base_url", ""))
            n += 1
    if n:
        log.info("Заведено новых досье: %d", n)
    return n


def get(model: str) -> dict:
    d = dict(_load().get(model) or {})
    d.setdefault("reliability", DEFAULT_RELIABILITY)
    d.setdefault("manual", None)
    d.setdefault("lies", 0)          # «сказала, что сделала» без вызова
    d.setdefault("errors", 0)
    d.setdefault("wins", 0)
    d.setdefault("note", "")
    return d


def reliability(model: str) -> int:
    """Итоговая надёжность 1..10. Ручная оценка владельца главнее всего."""
    d = get(model)
    if d.get("manual"):
        return max(1, min(10, int(d["manual"])))
    r = float(d.get("reliability", DEFAULT_RELIABILITY))
    if model in set(CFG.get("llm.tools_broken", [])):
        # у неё физически нет рук: обещать она может что угодно
        r = min(r, 3)
    return max(1, min(10, round(r)))


def set_manual(model: str, score) -> dict:
    _load()
    rec = _cache.setdefault(model, {})
    rec["manual"] = None if score in (None, "", 0) else max(1, min(10, int(score)))
    _save()
    return get(model)


def set_note(model: str, note: str) -> dict:
    _load()
    _cache.setdefault(model, {})["note"] = str(note or "")[:300]
    _save()
    return get(model)


def set_cost(model: str, cost: str) -> dict:
    _load()
    if cost not in COST_RANK:
        raise ValueError("цена бывает free, metered или paid")
    _cache.setdefault(model, {})["cost"] = cost
    _save()
    return get(model)


def _nudge(model: str, delta: float, why: str, counter: str | None = None):
    if not model:
        return
    _load()
    rec = _cache.setdefault(model, {})
    r = float(rec.get("reliability", DEFAULT_RELIABILITY))
    # к краям движемся всё медленнее: одна случайная промашка не должна
    # хоронить модель, а одна удача — отмывать её
    r = max(1.0, min(10.0, r + delta))
    rec["reliability"] = round(r, 2)
    if counter:
        rec[counter] = int(rec.get(counter, 0)) + 1
    rec["last"] = why[:120]
    _save()
    log.info("Надёжность %s: %+.2f -> %.2f (%s)", model, delta, r, why)


# ─────────────── «сказала, что сделала», но не сделала ───────────────
# Ровно тот случай, который назвал владелец. Ловится точно: реплика в
# прошедшем времени от первого лица про физическое действие, при том что за
# ход не вызвано НИ ОДНОГО инструмента. Ни одна честная модель так не
# скажет — ей нечем было это сделать.
_CLAIM = re.compile(
    r"\b(?:я\s+)?(?:уже\s+)?("
    r"запустил|открыл|закрыл|свернул|развернул|включил|выключил|"
    r"поставил|убавил|прибавил|сделал|создал|записал|сохранил|"
    r"переключил|нашл|скачал|удалил|перенес|переименовал"
    r")(?:а|о|и|ась|ась)?\b|"
    # НАСТОЯЩЕЕ ВРЕМЯ — ТОЖЕ ОТЧЁТ (2026-08-13, живой вечер: она весь
    # разговор обещала в процессе — «Открываю плейлист, дай мне секунду»,
    # «Ставлю на паузу», «Возобновляю воспроизведение» — и не вызывала
    # ничего. Детект ловил только прошедшее время, поэтому молчал, а
    # человек сидел и ждал. Для него «открываю» и «открыла» — одно и то
    # же обещание: он ждёт результата, а не спряжения.)
    r"\b(?:я\s+)?("
    r"открываю|запускаю|включаю|выключаю|закрываю|сворачиваю|разворачиваю|"
    r"ставлю\s+на\s+паузу|возобновляю|переключаю|перехожу|нажимаю|"
    r"убавляю|прибавляю|сохраняю|создаю|удаляю|переношу|листаю|"
    r"проматываю|прокручиваю|отправляю|печатаю|набираю|"
    # 2026-08-13, вторая порция с живого вечера
    r"перезапускаю|подключаюсь|подключаю|запоминаю|ищу|смотрю\s+что|"
    r"собираю|скачиваю|устанавливаю|проверяю|исправляю|чиню|меняю|"
    r"выгружаю|загружаю|захожу|выхожу|жму|кликаю|тащу"
    r")\b", re.I)
# Отмазки, после которых «сделала» — это не отчёт, а условие или отрицание
_NOT_CLAIM = re.compile(
    r"не\s+(?:могу|смогу|получилось|вышло|удалось|буду|стану)|"
    r"если\s+|могла\s+бы|хотел[аи]?\s+бы|попробую|давай\s+я|"
    r"нужно\s+|надо\s+|можно\s+", re.I)


def check_claim(model: str, reply: str, tool_used: bool) -> bool:
    """True, если модель приписала себе действие, которого не совершала."""
    if tool_used or not reply or not model:
        return False
    if not CFG.get("llm.catch_false_claims", True):
        return False
    text = reply[:600]
    if _NOT_CLAIM.search(text):
        return False
    if not _CLAIM.search(text):
        return False
    _nudge(model, -0.6, "сказала, что сделала, но инструмент не вызывала",
           "lies")
    return True


def record_error(model: str, why: str = ""):
    _nudge(model, -0.3, "ошибка инструмента: " + (why or "?"), "errors")


def record_complaint(model: str, why: str = ""):
    """Владелец сказал, что она не справилась. Самый весомый сигнал."""
    _nudge(model, -1.0, "жалоба владельца: " + (why or "?"), "errors")


def record_ok(model: str):
    """Ход прошёл чисто, инструменты сработали. Отыгрывается медленно."""
    _nudge(model, 0.08, "чистый ход", "wins")


# ─────────────────────── сводка для самой Сайки ───────────────────────
def _entries() -> list:
    """Все известные модели с досье, отсортированные по полезности."""
    from anamorf.llm import manager as llm
    out = []
    cur = CFG.get("llm.model", "")
    try:
        models = llm.list_models()
    except Exception:
        models = []
    for m in models:
        name = m.get("name", "")
        if not name:
            continue
        # новая модель в списке — досье заводится само, прямо здесь
        ensure(name, m.get("backend", ""), m.get("caps") or {},
               int((m.get("size") or 0) / 1048576), m.get("base_url", ""))
        d = get(name)
        out.append({
            "name": name, "backend": m.get("backend", ""),
            "reliability": reliability(name),
            "cost": cost_of(name, m.get("backend", ""), m.get("base_url", "")),
            "vision": bool((m.get("caps") or {}).get("vision")),
            "current": name == cur,
            "note": d.get("note", ""),
            "lies": d.get("lies", 0), "errors": d.get("errors", 0),
            "manual": d.get("manual"),
        })
    return out


def rank(prefer_cheap: bool | None = None) -> list:
    """Порядок, в котором стоит брать модели. Сначала надёжность, при
    равной — дешевле. Платные не первые, если владелец бережёт деньги."""
    if prefer_cheap is None:
        prefer_cheap = bool(CFG.get("llm.prefer_cheap", True))
    items = _entries()
    items.sort(key=lambda e: (
        -e["reliability"],
        COST_RANK.get(e["cost"], 1) if prefer_cheap else 0,
    ))
    return items


def digest(max_items: int = 5) -> str:
    """Короткая справка ДЛЯ САЙКИ: чем она сейчас думает и что есть в
    запасе. Без этого просьба «возьми модель поумнее» упирается в то, что
    она про свой же арсенал ничего не знает.

    Держим коротко намеренно: это уходит в каждый промпт, и длинная
    простыня стоила бы задержки на каждой фразе."""
    items = rank()
    if not items:
        return ""
    cur = next((e for e in items if e["current"]), None)
    lines = []
    if cur:
        lines.append(
            f"Сейчас ты думаешь моделью {cur['name']}: надёжность "
            f"{cur['reliability']} из 10, {COST_WORD.get(cur['cost'], '')}."
            + (f" {cur['note']}" if cur["note"] else ""))
    spare = [e for e in items if not e["current"]][:max_items]
    if spare:
        lines.append("В запасе (можешь переключиться сама через model_switch, "
                     "если задача не даётся): " + "; ".join(
                         f"{e['name']} — надёжность {e['reliability']}"
                         + (", платная" if e["cost"] == "paid" else "")
                         + (", со зрением" if e["vision"] else "")
                         for e in spare))
    if CFG.get("llm.prefer_cheap", True):
        lines.append("Деньги владельца не безграничные: платные модели "
                     "бери как подстраховку — когда бесплатная не справилась "
                     "или он попросил сам, а не по умолчанию.")
    lines.append("Никогда не пиши, что запустила, открыла или сделала "
                 "что-то на компьютере, если у тебя не было вызова "
                 "инструмента. Не смогла — так и скажи.")
    return "### Твои мозги и чем ты можешь думать\n" + "\n".join(lines)
