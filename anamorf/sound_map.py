"""КАРТА ЗВУКОВ — кластеризация звуковых источников дома (2026-08-15).

ГЛАВНАЯ ЦЕЛЬ ВЛАДЕЛЬЦА, дословно: «получить лучшую передовую технологию
определения и кластеризации звуков». Определение к вечеру собрано
(PANNs + CLAP + битбокс + кора); это — вторая половина: КЛАСТЕРИЗАЦИЯ.

ИДЕЯ ТА ЖЕ, ЧТО У КАРТЫ ГОЛОСОВ, и это не совпадение — так устроено и у
мозга: незнакомый звук сначала «какой-то стук», но повторившись десять
раз из одного места с одним спектром, он становится ИСТОЧНИКОМ — «дверь
шкафа», «мой кулер», «клавиатура Анаморфа». PANNs на каждом окне уже
считает эмбеддинг (2048 чисел, до сих пор выбрасывался!) — это отпечаток
ЗВУКА, как ECAPA — отпечаток голоса. Кластеризуем онлайн:

  окно звука -> эмбеддинг -> ближайший центроид
      косинус > порога  -> тот же источник: счётчик++, центроид доучивается
      иначе             -> новый источник, имя от того, что слышат уши
                           в этот момент («стук?», «музыка?»)

Никакого UMAP/HDBSCAN на лету — онлайн-центроиды дешевле и живут вечно;
проекция для красивой картинки делается по запросу (/api/soundmap).
Источники переживают перезапуск (data/sound_map.json), владелец может
переименовать («это мой кулер») — имя закрепляется.
"""
import json
import logging
import threading
import time

import numpy as np

from anamorf.config import CFG, ROOT

log = logging.getLogger("saika.soundmap")

PATH = ROOT / "data" / "sound_map.json"
MAX_SOURCES = 64

_lock = threading.Lock()
_sources = None      # [{name, emb(list), n, last, tags{ru:n}}]


def _load():
    global _sources
    if _sources is not None:
        return
    try:
        raw = json.loads(PATH.read_text("utf-8"))
        _sources = raw if isinstance(raw, list) else []
    except Exception:
        _sources = []


def _save():
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(_sources, ensure_ascii=False),
                        encoding="utf-8")
    except Exception as e:
        log.debug("карта звуков не сохранилась: %s", e)


def _cos(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def hear(emb, tag_ru: str = "", speechy: float = 0.0):
    """Окно звука: эмбеддинг PANNs + главная метка ушей в этот момент.
    Речь в карту НЕ кладём — у речи своя карта (голоса)."""
    if not CFG.get("soundmap.enabled", True):
        return None
    if speechy >= float(CFG.get("soundmap.speech_veto", 0.35)):
        return None
    try:
        e = np.asarray(emb, dtype=np.float32).ravel()
        if e.size < 8:
            return None
        with _lock:
            _load()
            thr = float(CFG.get("soundmap.cos", 0.60))
            best, bs = None, -1.0
            for srcs in _sources:
                c = _cos(e, np.asarray(srcs["emb"], np.float32))
                if c > bs:
                    best, bs = srcs, c
            now = time.time()
            if best is not None and bs >= thr:
                # тот же источник: доучиваем центроид скользящим средним
                w = min(0.15, 3.0 / (best["n"] + 1))
                c0 = np.asarray(best["emb"], np.float32)
                best["emb"] = ((1 - w) * c0 + w * e).tolist()
                best["n"] += 1
                best["last"] = now
                if tag_ru:
                    best.setdefault("tags", {})
                    best["tags"][tag_ru] = best["tags"].get(tag_ru, 0) + 1
                    # автоимя уточняется, пока владелец не закрепил своё
                    if not best.get("pinned") and best["n"] % 10 == 0:
                        top = max(best["tags"], key=best["tags"].get)
                        best["name"] = f"{top}?"
                if best["n"] % 25 == 0:
                    _save()
                return best["name"]
            # новый источник
            if len(_sources) >= MAX_SOURCES:
                # вытесняем самый редкий и старый — как забывает мозг
                _sources.sort(key=lambda s_: (s_["n"], s_["last"]))
                _sources.pop(0)
            name = f"{tag_ru}?" if tag_ru else "звук?"
            _sources.append({"name": name, "emb": e.tolist(), "n": 1,
                             "last": now,
                             "tags": ({tag_ru: 1} if tag_ru else {})})
            _save()
            log.info("Карта звуков: новый источник «%s» (всего %d)",
                     name, len(_sources))
            return name
    except Exception as e2:
        log.debug("карта звуков споткнулась: %s", e2)
        return None


def rename(old: str, new: str) -> dict:
    with _lock:
        _load()
        for s_ in _sources:
            if s_["name"] == old:
                s_["name"] = (new or "").strip()[:40] or old
                s_["pinned"] = True
                _save()
                return {"ok": True}
    return {"ok": False, "error": "нет такого источника"}


def forget(name: str) -> dict:
    global _sources
    with _lock:
        _load()
        n0 = len(_sources)
        _sources = [s_ for s_ in _sources if s_["name"] != name]
        if len(_sources) != n0:
            _save()
            return {"ok": True}
    return {"ok": False, "error": "нет такого источника"}


def status() -> dict:
    with _lock:
        _load()
        now = time.time()
        out = []
        for s_ in sorted(_sources, key=lambda x: -x["n"]):
            top = sorted((s_.get("tags") or {}).items(),
                         key=lambda kv: -kv[1])[:3]
            out.append({"name": s_["name"], "n": s_["n"],
                        "ago_s": round(now - s_["last"]),
                        "tags": [k for k, _v in top],
                        "pinned": bool(s_.get("pinned"))})
        return {"sources": out, "total": len(_sources)}
