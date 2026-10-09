# -*- coding: utf-8 -*-
"""ПОЛИГОН СЛУХА — режим обучения на ролике с управлением плеером (2026-09-06).

Просьба владельца дословно: «режим управления плеером для тест-режимов, где
мы обучаем систему и пишем алгоритмы, чтобы каждый запуск я видел, как
происходит, как ролик перематывается на нужный участок при запуске
следующего отрезка… и я всё видеть, слышать и смогу сразу писать фидбек».

Что делает:
  • play(start, length): запускает MPC-HC на ролике с нужной секунды — звук
    идёт через колонки и петлю, то есть слух работает ровно как в бою, и
    человек СЛЫШИТ то же, что слышит она. Момент запуска — якорь.
  • status(): что сейчас — играет ли, на какой секунде ролика, сколько
    реплик уже дошло до ленты, и по окончании отрезка — счёт.
  • score(): сверка ленты (data/hear_bench/index.jsonl) с расшифровкой
    ютуба по секундам ролика: найдено/пропущено/лишнее, потерянные слова
    по десяткам секунд. Та же арифметика, что в tools/live_score.py.

Плеер: MPC-HC умеет «/start мс /play» из командной строки; при повторном
запуске с новыми параметрами он перематывает то же окно (настройка
«открывать следующий файл в том же окне» у него по умолчанию включена).
"""
import json
import logging
import re
import subprocess
import threading
import time
from pathlib import Path

from anamorf.config import CFG, ROOT, DATA_ROOT

log = logging.getLogger("saika.polygon")

_LOCK = threading.Lock()
RUN = {"id": 0, "on": False, "anchor": 0.0, "start": 0, "len": 0,
       "score": None, "ended": 0.0, "err": "", "ref": "", "media": ""}

PRESETS = [
    {"name": "Начало: крик двух женщин", "start": 0, "len": 22,
     "note": "самое мясо — наложение голосов, ютуб сам тут пишет кашу"},
    {"name": "Вступление Снейла", "start": 22, "len": 40,
     "note": "один голос, чисто — проверка, что всё слово в слово"},
    {"name": "Диалог с Ольгой", "start": 22 * 60, "len": 60,
     "note": "гость, эксперт, ведущий — смена голосов, перебивания"},
    {"name": "Диалог с Ольгой, 3 минуты", "start": 22 * 60, "len": 180,
     "note": "длинный прогон: видно, копится ли отставание"},
]


def _video():
    p = CFG.get("polygon.video", "")
    if p:
        return Path(p)
    d = ROOT / "slux_test" / "snailkik_dnk"
    for x in d.glob("*.mp4"):
        return x
    return d / "video.mp4"


def _player():
    for p in (CFG.get("polygon.player", ""),
              r"C:\Program Files\MPC-HC\mpc-hc64.exe",
              r"C:\Program Files (x86)\MPC-HC\mpc-hc.exe"):
        if p and Path(p).exists():
            return Path(p)
    return None


def _norm(t):
    return [x for x in re.findall(r"[а-яё]+", (t or "").lower()) if len(x) > 1]


def _ref_path(ref=None):
    """Расшифровка: та, что задана для текущего прогона (лежит рядом с
    медиафайлом как transkrib.txt), иначе — ролик ДНК по умолчанию."""
    p = Path(ref or RUN.get("ref") or "")
    if p.is_file():
        return p
    return ROOT / "slux_test" / "snailkik_dnk" / "transkrib.txt"


def ref_for(media_path: str) -> str:
    try:
        d = Path(media_path).parent
        for name in ("transkrib.txt", "transcript.txt", "ref.txt"):
            if (d / name).is_file():
                return str(d / name)
    except Exception:
        pass
    return ""


def _reference(start, length, ref=None):
    """Слова расшифровки ютуба по секундам ролика: {сек: [слова]}."""
    out = {}
    p = _ref_path(ref)
    if not p.exists():
        return out
    for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"(\d+):(\d\d)", ln)
        if not m:
            continue
        t = int(m.group(1)) * 60 + int(m.group(2))
        if start <= t < start + length:
            txt = re.sub(r"^\S+\s*(минут\w*\s*\d*\s*)?секунд\w*", "", ln)
            txt = re.sub(r"\[[^\]]*\]", " ", txt)   # [смех], [крик] — не слова
            out.setdefault(t, []).extend(_norm(txt))
    return out


def reference_text(start, length, ref=None):
    """Строки расшифровки как есть — человеку читать, не считать."""
    out = []
    p = _ref_path(ref)
    if not p.exists():
        return out
    for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"(\d+):(\d\d)", ln)
        if not m:
            continue
        t = int(m.group(1)) * 60 + int(m.group(2))
        if start <= t < start + length:
            txt = re.sub(r"^\S+\s*(минут\w*\s*\d*\s*)?секунд\w*", "", ln).strip()
            out.append({"t": t, "text": txt})
    return out


def _feed(anchor, start, length, tail=12.0):
    """Реплики ленты за отрезок, положенные на секунды ролика.

    С 06.09.2026 — из журнала событий вкладки (data/events.jsonl), то есть
    ровно то, что видит человек, ВКЛЮЧАЯ правки второго уха (stt_fix):
    стенд слуха раньше считал только первое чтение и не видел, что
    облачко дописалось."""
    rows = []
    ev = DATA_ROOT / "data" / "events.jsonl"
    if ev.exists():
        try:
            fixes = {}
            base = []
            with ev.open(encoding="utf-8", errors="ignore") as fh:
                for ln in fh:
                    try:
                        r = json.loads(ln)
                    except Exception:
                        continue
                    ts = float(r.get("_ts", 0))
                    if ts < anchor - 1 or ts > anchor + length + tail:
                        continue
                    if r.get("type") == "stt":
                        base.append(r)
                    elif r.get("type") == "stt_fix" and r.get("pid") is not None:
                        fixes[r.get("pid")] = r.get("text", "")
            for r in base:
                ts = float(r.get("_ts", 0))
                end = ts - anchor - float(r.get("stt_ms", 0)) / 1000.0
                a = end - float(r.get("sec", 0))
                txt = fixes.get(r.get("pid"), r.get("text", ""))
                rows.append({"a": round(start + a, 1), "b": round(start + end, 1),
                             "text": txt, "ms": r.get("stt_ms", 0),
                             "fixed": r.get("pid") in fixes})
            if rows:
                return rows
        except Exception:
            rows = []
    p = DATA_ROOT / "data" / "hear_bench" / "index.jsonl"
    if not p.exists():
        return rows
    with p.open(encoding="utf-8", errors="ignore") as fh:
        for ln in fh:
            try:
                r = json.loads(ln)
            except Exception:
                continue
            ts = float(r.get("ts", 0))
            if anchor <= ts <= anchor + length + tail:
                end = ts - anchor - float(r.get("ms", 0)) / 1000.0
                a = end - float(r.get("sec", 0))
                rows.append({"a": round(start + a, 1), "b": round(start + end, 1),
                             "text": r.get("text", ""), "ms": r.get("ms", 0)})
    return rows


def score(anchor=None, start=None, length=None):
    anchor = RUN["anchor"] if anchor is None else anchor
    start = RUN["start"] if start is None else start
    length = RUN["len"] if length is None else length
    # строка расшифровки живёт ~7 с: если отрезок оборвали, последнюю
    # строку, которая почти не прозвучала, в счёт не берём
    ref = _reference(start, max(1, length - 4))
    rows = _feed(anchor, start, length)
    got = {}
    for r in rows:
        b = int(max(r["a"], start) // 10)
        got.setdefault(b, set()).update(_norm(r["text"]))
    refb = {}
    for t, ws in ref.items():
        refb.setdefault(int(t // 10), []).extend(ws)
    hit = miss = extra = 0
    bins = []
    for b in sorted(set(refb) | set(got)):
        rw = refb.get(b, [])
        g = got.get(b, set())
        gg = g | got.get(b - 1, set()) | got.get(b + 1, set())
        lost = [w for w in rw if w not in gg]
        h = len(rw) - len(lost)
        rr = set(rw) | set(refb.get(b - 1, [])) | set(refb.get(b + 1, []))
        ex = [w for w in g if w not in rr]
        hit += h
        miss += len(lost)
        extra += len(ex)
        bins.append({"t": b * 10, "hit": h, "ref": len(rw),
                     "lost": " ".join(lost), "extra": " ".join(ex)})
    total = hit + miss
    return {"found": hit, "ref": total,
            "pct": round(100.0 * hit / total, 1) if total else None,
            "extra": extra, "phrases": len(rows),
            "lag_ms": (sorted(int(r["ms"]) for r in rows)[len(rows) // 2]
                       if rows else None),
            "bins": bins, "rows": rows[-60:]}


def play(start, length):
    exe = _player()
    vid = _video()
    if exe is None:
        return {"error": "MPC-HC не найден (polygon.player в config)"}
    if not vid.exists():
        return {"error": "ролик не найден: %s" % vid}
    with _LOCK:
        RUN["id"] += 1
        RUN.update(on=True, anchor=time.time(), start=int(start),
                   len=int(length), score=None, ended=0.0, err="")
        try:
            subprocess.Popen([str(exe), str(vid), "/start",
                              str(int(start) * 1000), "/play"],
                             close_fds=True)
        except Exception as e:
            RUN.update(on=False, err=str(e))
            return {"error": "плеер не запустился: %s" % e}
        # тот же якорь, что читают tools/hear_align.py и живые скрипты
        try:
            (DATA_ROOT / "data" / "play_anchor.txt").write_text(
                "ЯКОРЬ ts=%.3f видео_сек=%d" % (RUN["anchor"], int(start)),
                encoding="utf-8")
        except Exception:
            pass
        log.info("Полигон: отрезок %d + %d с, плеер запущен", start, length)
        threading.Thread(target=_watch, args=(RUN["id"],), daemon=True,
                         name="polygon").start()
        return {"ok": True, "id": RUN["id"], "anchor": RUN["anchor"]}


def mark(pos, length=0, media="", ref=""):
    """Якорь от встроенного плеера: браузер сказал «играю с секунды pos».
    Длина 0 — до паузы/конца; счёт считается по stop()."""
    with _LOCK:
        RUN["id"] += 1
        RUN.update(on=True, anchor=time.time(), start=int(pos),
                   len=int(length) if length else 36000, score=None,
                   ended=0.0, err="", media=media, ref=ref or ref_for(media))
        try:
            (DATA_ROOT / "data" / "play_anchor.txt").write_text(
                "ЯКОРЬ ts=%.3f видео_сек=%d" % (RUN["anchor"], int(pos)),
                encoding="utf-8")
        except Exception:
            pass
        log.info("Полигон: плеер играет %s с %d с", media or "?", int(pos))
        return {"ok": True, "id": RUN["id"], "has_ref": bool(RUN["ref"]) or
                _ref_path().exists()}


def _watch(run_id):
    """Досидеть до конца отрезка, дать движку дописать хвост, посчитать."""
    while RUN["id"] == run_id and RUN["on"]:
        if time.time() - RUN["anchor"] >= RUN["len"] + 6.0:
            stop(run_id)
            return
        time.sleep(0.5)


def stop(run_id=None):
    with _LOCK:
        if run_id is not None and RUN["id"] != run_id:
            return RUN["score"]
        if not RUN["on"]:
            return RUN["score"]
        RUN["on"] = False
        RUN["ended"] = time.time()
        # пауза внешнему плееру — только если играл он, а не браузер
        if not RUN.get("media"):
            try:
                exe = _player()
                if exe is not None:
                    subprocess.Popen([str(exe), "/pause"], close_fds=True)
            except Exception:
                pass
        # округляем, не режем: 19.9 с → 20, иначе последняя строка эталона
        # выпадала из счёта как «недоговорённая» (живой случай 06.09)
        RUN["len"] = max(1, int(round(time.time() - RUN["anchor"])))
    try:
        RUN["score"] = score()
        log.info("Полигон: отрезок %d+%d с — найдено %s%% (%s из %s), "
                 "лишних %s, реплик %s", RUN["start"], RUN["len"],
                 RUN["score"]["pct"], RUN["score"]["found"],
                 RUN["score"]["ref"], RUN["score"]["extra"],
                 RUN["score"]["phrases"])
    except Exception as e:
        RUN["err"] = str(e)
        log.warning("Полигон: счёт не сошёлся: %s", e)
    return RUN["score"]


def status():
    now = time.time()
    el = (now - RUN["anchor"]) if RUN["anchor"] else 0.0
    out = {"on": RUN["on"], "id": RUN["id"], "start": RUN["start"],
           "len": RUN["len"], "elapsed": round(el, 1),
           "pos": round(RUN["start"] + el, 1) if RUN["on"] else None,
           "score": RUN["score"], "err": RUN["err"],
           "player": bool(_player()), "video": _video().name,
           "presets": PRESETS}
    out["has_ref"] = _ref_path().exists()
    if RUN["on"]:
        try:
            RUN_len, RUN["len"] = RUN["len"], max(1, int(el))
            out["live"] = score()
            RUN["len"] = RUN_len
        except Exception:
            pass
    return out

# ═══ РАЗМЕТКА ВЛАДЕЛЬЦА — ЭТАЛОН, К КОТОРОМУ ИДЁМ (06.09.2026) ═══════════
# Владелец: «дай возможность выделить цветом голос человека… дописать
# недостающие слова… так ты получишь максимально точную разметку, к
# которой нужно программно прийти». Лежит рядом с расшифровкой как
# markup.json: {"lines": {"<t>": [{"w": слово, "v": голос, "add": true}]}}
def markup_path(ref=None):
    return _ref_path(ref).with_name("markup.json")


def markup_get(ref=None):
    p = markup_path(ref)
    try:
        return json.loads(p.read_text("utf-8")) if p.exists() else {"lines": {}, "voices": {}}
    except Exception:
        return {"lines": {}, "voices": {}}


def markup_set(data: dict, ref=None):
    p = markup_path(ref)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    n = sum(len(v) for v in (data.get("lines") or {}).values())
    return {"ok": True, "path": str(p), "words": n}
