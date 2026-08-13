"""СЧЁТЧИК ОБЛАЧНЫХ ТОКЕНОВ — сколько она потратила и на что.

2026-08-13, просьба владельца: «нужно отслеживать количество ресурсов,
которые она тратит из онлайн-моделей, тех же токенов».

Повод не бухгалтерский, а инженерный. Пока облако зовётся раз в реплику и
только когда человек говорит — тратится ровно столько, сколько он видит.
Как только появятся фоновые подрядчики (разобрать картинку, прочитать
десяток сайтов), облако начнёт работать БЕЗ его ведома, и без счётчика
это будет тихая утечка денег. Бюджет нельзя соблюдать, не умея считать.

ЛОКАЛЬНЫЕ МОДЕЛИ ТОЖЕ СЧИТАЕМ, но отдельной строкой и без денег: их токены
ничего не стоят, зато показывают, где реально жуётся контекст. Именно по
этим числам сегодня нашли, что прогрев вытирал KV-кэш.

ЦЕН НЕТ В КОДЕ. Прайс провайдеров меняется чаще, чем этот файл, и
выдуманная цифра хуже её отсутствия: по ней принимают решения. Ставка
берётся из config (llm.pricing), а нет ставки — показываем только токены и
честно говорим, что цена неизвестна.
"""
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from server.config import CFG

log = logging.getLogger("saika.usage")

PATH = Path(__file__).resolve().parent.parent / "data" / "usage.json"
_lock = threading.Lock()
_mem: dict | None = None
KEEP_DAYS = 60


def _blank():
    return {"days": {}, "total": {"in": 0, "out": 0, "calls": 0}}


def _load() -> dict:
    global _mem
    if _mem is None:
        try:
            _mem = json.loads(PATH.read_text(encoding="utf-8"))
        except Exception:
            _mem = _blank()
        _mem.setdefault("days", {})
        _mem.setdefault("total", {"in": 0, "out": 0, "calls": 0})
    return _mem


def _save():
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(_mem, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except Exception as e:
        log.debug("счётчик не сохранился: %s", e)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _prune(d: dict):
    edge = (datetime.now() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    for k in [k for k in d["days"] if k < edge]:
        del d["days"][k]


def add(backend: str, model: str, usage: dict, why: str = "разговор"):
    """Записать расход. usage — как отдаёт провайдер (OpenAI-формат)."""
    if not usage:
        return
    try:
        tin = int(usage.get("prompt_tokens") or 0)
        tout = int(usage.get("completion_tokens") or 0)
    except Exception:
        return
    if not (tin or tout):
        return
    # кэшированный ввод у большинства провайдеров дешевле или бесплатен —
    # держим отдельно, иначе экономия от KV-кэша не видна в деньгах
    cached = 0
    det = usage.get("prompt_tokens_details") or {}
    try:
        cached = int(det.get("cached_tokens")
                     or usage.get("precached_prompt_tokens") or 0)
    except Exception:
        cached = 0
    reason = 0
    det2 = usage.get("completion_tokens_details") or {}
    try:
        reason = int(det2.get("reasoning_tokens") or 0)
    except Exception:
        reason = 0

    key = f"{backend}/{model}"
    with _lock:
        d = _load()
        day = d["days"].setdefault(_today(), {})
        rec = day.setdefault(key, {"in": 0, "out": 0, "cached": 0,
                                   "reasoning": 0, "calls": 0, "why": {}})
        rec["in"] += tin
        rec["out"] += tout
        rec["cached"] += cached
        rec["reasoning"] += reason
        rec["calls"] += 1
        rec["why"][why] = rec["why"].get(why, 0) + 1
        d["total"]["in"] += tin
        d["total"]["out"] += tout
        d["total"]["calls"] += 1
        d["ts"] = time.time()
        _prune(d)
        _save()


def _price(key: str):
    """Ставка за миллион токенов: {"in": …, "out": …} или None.
    Ищем по точному имени, потом по подстроке — «gpt-4o» покроет
    «gpt-4o-2026-05»."""
    table = CFG.get("llm.pricing", {}) or {}
    if key in table:
        return table[key]
    short = key.split("/")[-1]
    if short in table:
        return table[short]
    for k, v in table.items():
        if k and k in key:
            return v
    return None


def _money(key: str, rec: dict):
    p = _price(key)
    if not isinstance(p, dict):
        return None
    try:
        billable_in = max(0, rec["in"] - rec.get("cached", 0))
        return round(billable_in / 1e6 * float(p.get("in", 0))
                     + rec["out"] / 1e6 * float(p.get("out", 0)), 4)
    except Exception:
        return None


def report(days: int = 7) -> dict:
    """Для интерфейса и для неё самой: расход по моделям."""
    with _lock:
        d = _load()
        edge = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        acc: dict = {}
        for day, models in d["days"].items():
            if day < edge:
                continue
            for key, rec in models.items():
                a = acc.setdefault(key, {"in": 0, "out": 0, "cached": 0,
                                         "reasoning": 0, "calls": 0})
                for f in ("in", "out", "cached", "reasoning", "calls"):
                    a[f] += rec.get(f, 0)
        rows, money, unknown = [], 0.0, False
        for key, a in sorted(acc.items(), key=lambda kv: -kv[1]["in"]):
            cost = _money(key, a)
            cloud = key.startswith("cloud/")
            if cloud:
                if cost is None:
                    unknown = True
                else:
                    money += cost
            rows.append({"model": key, "cloud": cloud, **a, "cost": cost})
        today = d["days"].get(_today(), {})
        t_in = sum(r.get("in", 0) for k, r in today.items()
                   if k.startswith("cloud/"))
        t_out = sum(r.get("out", 0) for k, r in today.items()
                    if k.startswith("cloud/"))
        return {"days": days, "rows": rows,
                "cloud_cost": round(money, 4) if not unknown else None,
                "cost_unknown": unknown,
                "today_cloud": {"in": t_in, "out": t_out},
                "total": dict(d["total"])}


def today_cloud_tokens() -> int:
    """Сколько облачных токенов сожжено сегодня — для потолка."""
    with _lock:
        d = _load()
        day = d["days"].get(_today(), {})
        return sum(r.get("in", 0) + r.get("out", 0)
                   for k, r in day.items() if k.startswith("cloud/"))


def over_budget() -> bool:
    """Потолок на день (llm.cloud_daily_tokens, 0 = без потолка).
    Нужен именно фоновым задачам: человек видит свои реплики и сам
    остановится, а подрядчик в фоне — нет."""
    cap = int(CFG.get("llm.cloud_daily_tokens", 0) or 0)
    return bool(cap) and today_cloud_tokens() >= cap
