"""Рейтинг компонентов по отзывчивости (скорости). Копим среднюю скорость
генерации по каждой LLM-модели и переводим в оценку 1..10 — UI по ней
раскладывает список так, чтобы самая шустрая была ближе к курсору.

Хранится в data/ratings.json (per-machine, в .gitignore) — у каждого ПК своя
статистика под своё железо.
"""
import json
import threading

from anamorf.config import ROOT

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
    return {m: _score(e.get("tps", 0)) for m, e in _load().items()
            if not m.startswith("tts:") and not m.startswith("manual:")}


# ---------------- ручные оценки владельца ----------------
# Раньше жили ТОЛЬКО в localStorage браузера (ui/index.html, manualScores) —
# пользователь тянет палочки, список в UI пересортировывается… а сервер про
# это ни сном ни духом, и автопуск при старте продолжал выбирать по одному
# лишь скоростному замеру. Реальная жалоба 2026-07-23: «поставил Huihui
# высшую оценку — а грузится всё равно не она». Теперь UI синхронизирует
# ручные оценки сюда (ключи "manual:<имя>"), и автопуск обязан их уважать:
# ручная оценка ПЕРЕБИВАЕТ авто-скоростную (та же семантика, что в UI).
# Имена общие для всех видов (LLM-модели, TTS/STT-движки) — как и в UI.

def set_manual(name: str, score):
    """score 1..10 или None (снять ручную оценку)."""
    if not name:
        return
    key = "manual:" + name
    with _lock:
        d = _load()
        if score is None:
            d.pop(key, None)
        else:
            d[key] = {"score": max(1, min(10, int(score)))}
        _save(d)


def merge_manual(scores: dict) -> dict:
    """Массовая синхронизация из UI (браузер присылает весь свой словарь).
    Браузер — источник правды (оценки ставят именно там), его значения
    перекрывают серверные. Возвращает итоговый словарь {имя: 1..10}."""
    with _lock:
        d = _load()
        for name, sc in (scores or {}).items():
            if not name:
                continue
            try:
                d["manual:" + name] = {"score": max(1, min(10, int(sc)))}
            except (TypeError, ValueError):
                continue
        _save(d)
        return {k[7:]: e.get("score", 0) for k, e in d.items()
                if k.startswith("manual:")}


def manual_scores() -> dict:
    """{имя: 1..10} — только ручные оценки."""
    return {k[7:]: e.get("score", 0) for k, e in _load().items()
            if k.startswith("manual:")}


def score_of(tps: float) -> int:
    """Публичный доступ к шкале ток/с -> 1..10 (для автопуска в main.py)."""
    return _score(tps)


# ---------------- рейтинг голосов (TTS) ----------------
# Метрика — скорость синтеза: секунд аудио за секунду работы движка
# (2.0 = синтезирует вдвое быстрее реального времени). Хранится в том же
# ratings.json под ключами "tts:<engine>", чтобы не путаться с LLM.

def record_tts(engine: str, speed: float):
    if not engine or not speed or speed <= 0:
        return
    key = "tts:" + engine
    with _lock:
        d = _load()
        e = d.get(key)
        if e:
            e["speed"] = round(e["speed"] * 0.7 + speed * 0.3, 2)
            e["n"] = e.get("n", 0) + 1
        else:
            e = {"speed": round(speed, 2), "n": 1}
        d[key] = e
        _save(d)


def tts_scores() -> dict:
    """{engine: 1..10 по скорости синтеза}. 1x реального времени ≈ 5."""
    out = {}
    for k, e in _load().items():
        if k.startswith("tts:"):
            spd = e.get("speed", 0)
            out[k[4:]] = int(round(min(10, max(1, spd * 5)))) if spd else 0
    return out


def best_tts(order, exclude=(), favorites=()):
    """Лучший запасной голос. Приоритет: «нравится» (favorites, в порядке
    списка) > скорость по замерам > порядок в конфиге. Дело ведь не только
    в скорости — любимый голос важнее шустрого."""
    pool = [n for n in order if n not in exclude]
    if not pool:
        return None
    scores = tts_scores()
    pool.sort(key=lambda n: -scores.get(n, 0))
    favs = [f for f in favorites if f in pool]
    pool.sort(key=lambda n: favs.index(n) if n in favs else len(favs) + 1)
    return pool[0]


def llm_tps() -> dict:
    return {m: e.get("tps", 0) for m, e in _load().items()
            if not m.startswith("tts:") and not m.startswith("manual:")}
