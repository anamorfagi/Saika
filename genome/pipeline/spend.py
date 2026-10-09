# -*- coding: utf-8 -*-
"""spend.py — кошелёк персонажа: сколько на него уже потрачено по ВСЕМ запускам и сколько ещё можно.

---- учебный блок ----
Раньше потолок был на один прогон, и автопилот мог запустить несколько прогонов + проверки — каждый со своим
потолком, и персонаж в сумме съедал сотни рублей. Теперь у персонажа один кошелёк (chars/<id>/spend.jsonl):
каждый запуск (анализ, проверка, автопилот, промпт) дописывает строку «поиск X ₽, работа Y ₽», а перед
каждым вызовом модели проверяется остаток: поиск ≤ budget_search_rub, работа ≤ budget_work_rub (prices.json).
"""
import json, pathlib, time

ROOT = pathlib.Path(__file__).resolve().parent.parent


def потолки():
    try:
        p = json.loads((pathlib.Path(__file__).parent / "prices.json").read_text(encoding="utf-8"))
    except Exception:
        p = {}
    return float(p.get("budget_search_rub", 25)), float(p.get("budget_work_rub", 25))


def потрачено(ид):
    """(поиск, работа) — сумма по всем завершённым запускам персонажа."""
    f = ROOT / "chars" / ид / "spend.jsonl"
    п = р = 0.0
    if f.exists():
        for x in f.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(x); п += float(d.get("поиск", 0)); р += float(d.get("работа", 0))
            except Exception:
                pass
    return round(п, 2), round(р, 2)


def записать(ид, что, поиск, работа, модель=""):
    f = ROOT / "chars" / ид / "spend.jsonl"; f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as w:
        w.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M"), "что": что, "поиск": round(поиск, 2),
                            "работа": round(работа, 2), "модель": модель}, ensure_ascii=False) + "\n")


def остаток(ид):
    пп, пр = потолки(); п, р = потрачено(ид)
    return max(0.0, пп - п), max(0.0, пр - р)
