"""Рейтинг компонентов по отзывчивости (скорости). Копим среднюю скорость
генерации по каждой LLM-модели и переводим в оценку 1..10 — UI по ней
раскладывает список так, чтобы самая шустрая была ближе к курсору.

Хранится в data/ratings.json (per-machine, в .gitignore) — у каждого ПК своя
статистика под своё железо.
"""
import json
import threading

from server.config import ROOT

PATH = ROOT / "data" / "ratings.json"
_lock = threading.Lock()


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


def record_llm(model: str, tps: float):
    """Записать замер скорости (ток/с) активной модели после ответа.
    Экспоненциальное скользящее среднее — свежие замеры весомее."""
    if not model or not tps or tps <= 0:
        return
    with _lock:
        d = _load()
        e = d.get(model)
        if e:
            e["tps"] = round(e["tps"] * 0.7 + tps * 0.3, 1)
            e["n"] = e.get("n", 0) + 1
        else:
            e = {"tps": round(tps, 1), "n": 1}
        d[model] = e
        _save(d)


def _score(tps: float) -> int:
    """ток/с -> 1..10. ~8 т/с и ниже = 1-2 (туго), 80+ = 10 (шустро)."""
    if not tps or tps <= 0:
        return 0
    return int(round(min(10, max(1, tps / 8))))


def llm_scores() -> dict:
    """{model: оценка 1..10}. Незамеренные — 0 (UI покажет «—», уедут наверх)."""
    return {m: _score(e.get("tps", 0)) for m, e in _load().items()}


def llm_tps() -> dict:
    return {m: e.get("tps", 0) for m, e in _load().items()}
