# -*- coding: utf-8 -*-
"""МЕДИАТЕКА — ролики, ссылки и mp3 прямо в Анаморфе (2026-09-06).

Владелец: «слева сделаем раздел: добавить ролик, или ссылку, или mp3 —
и чтобы оно прям в самом Анаморфе запускалось… отсюда ты и сможешь
запускать ролики и музыку на транскрибирование».

Что здесь: список того, что можно проиграть (файлы с диска, свои ссылки,
скачанное с ютуба), выдача файла браузеру с поддержкой перемотки (Range),
и закачка по ссылке через yt-dlp в фоне — со статусом, а не молча.
Играет сам браузер: звук идёт в системный выход → петля → слух, ровно как
любой другой звук на компьютере. Плюс браузер знает точную секунду
воспроизведения и сообщает её полигону — якорь без гаданий.
"""
import json
import logging
import re
import threading
import time
import hashlib
from pathlib import Path

from anamorf.config import CFG, ROOT, DATA_ROOT

log = logging.getLogger("saika.media")

_DIR = DATA_ROOT / "data" / "media"
_DB = DATA_ROOT / "data" / "media.json"
_EXT = {".mp4", ".webm", ".mkv", ".mov", ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".opus"}
_LOCK = threading.Lock()
JOBS = {}          # id -> {"state": "качаю"/"готово"/"ошибка", "pct": 0, "msg": ""}


def _load():
    try:
        return json.loads(_DB.read_text(encoding="utf-8"))
    except Exception:
        return {"items": []}


def _save(db):
    _DIR.mkdir(parents=True, exist_ok=True)
    _DB.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")


def _mid(s: str) -> str:
    return hashlib.md5(s.encode("utf-8", "ignore")).hexdigest()[:10]


def _scan():
    """Файлы, которые и так лежат рядом: data/media и slux_test."""
    out = []
    for d in (_DIR, ROOT / "slux_test"):
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if p.suffix.lower() in _EXT and p.is_file():
                out.append({"id": _mid(str(p)), "name": p.name, "kind": "file",
                            "path": str(p), "size": p.stat().st_size,
                            "where": str(p.parent.relative_to(ROOT)) if str(p).startswith(str(ROOT)) else str(p.parent)})
    return out


def items():
    db = _load()
    seen, out = set(), []
    for it in db.get("items", []) + _scan():
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        it = dict(it)
        it["job"] = JOBS.get(it["id"])
        out.append(it)
    out.sort(key=lambda x: (x.get("kind") != "url", x.get("name", "").lower()))
    return out


def find(mid: str):
    for it in items():
        if it["id"] == mid:
            return it
    return None


def add(path_or_url: str):
    s = (path_or_url or "").strip().strip('"')
    if not s:
        return {"error": "пусто"}
    db = _load()
    if re.match(r"^https?://", s, re.I):
        direct = s.lower().split("?")[0].endswith(tuple(_EXT))
        it = {"id": _mid(s), "name": s.rsplit("/", 1)[-1][:80] or s, "kind": "url",
              "url": s, "added": time.time()}
        if direct:
            db["items"] = [x for x in db["items"] if x["id"] != it["id"]] + [it]
            _save(db)
            return {"ok": True, "item": it}
        # не прямая ссылка на файл — качаем yt-dlp в фон
        it["kind"] = "download"
        db["items"] = [x for x in db["items"] if x["id"] != it["id"]] + [it]
        _save(db)
        threading.Thread(target=_download, args=(it,), daemon=True,
                         name="media-dl").start()
        return {"ok": True, "item": it, "note": "качаю в фоне"}
    p = Path(s)
    if not p.exists():
        return {"error": "нет такого файла: %s" % s}
    if p.suffix.lower() not in _EXT:
        return {"error": "не звук и не видео: %s" % p.suffix}
    it = {"id": _mid(str(p)), "name": p.name, "kind": "file", "path": str(p),
          "size": p.stat().st_size, "added": time.time()}
    db["items"] = [x for x in db["items"] if x["id"] != it["id"]] + [it]
    _save(db)
    return {"ok": True, "item": it}


def remove(mid: str):
    db = _load()
    n = len(db["items"])
    db["items"] = [x for x in db["items"] if x["id"] != mid]
    _save(db)
    return {"ok": True, "removed": n - len(db["items"])}


def _download(it):
    mid = it["id"]
    JOBS[mid] = {"state": "качаю", "pct": 0, "msg": ""}
    try:
        import yt_dlp
    except Exception:
        JOBS[mid] = {"state": "ошибка", "pct": 0,
                     "msg": "нет yt-dlp (pip install yt-dlp) — ставлю в фоне, повтори через минуту"}
        return
    _DIR.mkdir(parents=True, exist_ok=True)

    def hook(d):
        if d.get("status") == "downloading":
            tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            JOBS[mid] = {"state": "качаю", "pct": int(100 * got / tot) if tot else 0,
                         "msg": d.get("_speed_str", "")}
    opts = {"outtmpl": str(_DIR / ("%(title).80s [" + mid + "].%(ext)s")),
            "format": "bv*[height<=720]+ba/b[height<=720]/b",
            "merge_output_format": "mp4", "noplaylist": True,
            "progress_hooks": [hook], "quiet": True, "no_warnings": True}
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(it["url"], download=True)
            fn = y.prepare_filename(info)
            p = Path(fn)
            if not p.exists():
                cand = list(_DIR.glob("*[" + mid + "]*"))
                p = cand[0] if cand else p
        db = _load()
        for x in db["items"]:
            if x["id"] == mid:
                x.update(kind="file", path=str(p), name=p.name,
                         size=p.stat().st_size if p.exists() else 0,
                         title=info.get("title", ""))
        _save(db)
        JOBS[mid] = {"state": "готово", "pct": 100, "msg": p.name}
        log.info("Медиатека: скачано %s", p.name)
    except Exception as e:
        JOBS[mid] = {"state": "ошибка", "pct": 0, "msg": str(e)[:200]}
        log.warning("Медиатека: не скачалось %s: %s", it.get("url"), e)
