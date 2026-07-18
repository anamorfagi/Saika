"""Дев-доска Сайки: живая карта разработки (что готово, что в работе, что
багует, что в планах, идеи) + лог событий.

Хранится в РЕПО (devboard.json в корне, tracked) — значит синкается через git
между ПК и её может прочитать другая нейронка, которой отдали проект. При
каждом сохранении рядом генерится DEVBOARD.md — человеко/ИИ-читаемая версия.

Часть отметок ставит система сама (баги/починки из report_problem — считаем,
что «часто ломается»), часть — человек вручную из панели в интерфейсе.
"""
import json
import threading
import uuid
from datetime import datetime

from server.config import ROOT

PATH = ROOT / "devboard.json"
MD = ROOT / "DEVBOARD.md"
_lock = threading.RLock()

# колонки доски: ключ -> заголовок
COLS = [("doing", "🔄 В работе"), ("bugs", "🐞 Баги / чинится"),
        ("planned", "📋 В планах"), ("ideas", "💡 Идеи"),
        ("done", "✅ Готово")]
COL_KEYS = {k for k, _ in COLS}


def _now(minutes=True):
    return datetime.now().isoformat(timespec="minutes" if minutes else "seconds")


def _load():
    if PATH.exists():
        try:
            d = json.loads(PATH.read_text(encoding="utf-8"))
            d.setdefault("items", [])
            d.setdefault("log", [])
            d.setdefault("bugs", {})
            return d
        except Exception:
            pass
    return {"updated": "", "items": [], "log": [], "bugs": {}}


def _save(d):
    d["updated"] = _now(minutes=False)
    PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        MD.write_text(_render_md(d), encoding="utf-8")
    except Exception:
        pass


def get():
    with _lock:
        return _load()


def add_item(col, text, note=""):
    if col not in COL_KEYS or not (text or "").strip():
        return _load()
    with _lock:
        d = _load()
        d["items"].append({"id": uuid.uuid4().hex[:8], "col": col,
                           "text": text.strip(), "note": note.strip(),
                           "auto": False, "ts": _now()})
        _save(d)
        return d


def update_item(iid, **kw):
    with _lock:
        d = _load()
        for it in d["items"]:
            if it["id"] == iid:
                for k in ("col", "text", "note"):
                    if k in kw and kw[k] is not None:
                        it[k] = kw[k]
        _save(d)
        return d


def delete_item(iid):
    with _lock:
        d = _load()
        d["items"] = [it for it in d["items"] if it["id"] != iid]
        _save(d)
        return d


def note_problem(component, human, action, fixed=False):
    """Авто-отметка из report_problem: копим частоту багов по компоненту и
    пишем в лог человеческим языком."""
    with _lock:
        d = _load()
        b = d["bugs"].setdefault(
            component, {"text": human or component, "count": 0,
                        "resolved": True, "last": ""})
        if fixed:
            b["resolved"] = True
        else:
            b["count"] += 1
            b["resolved"] = False
            if human:
                b["text"] = human
        b["last"] = _now()
        d["log"].append({"ts": _now(minutes=False),
                         "text": ("✓ " if fixed else "⚠ ") + component + ": "
                                 + (action or human or ""),
                         "kind": "fix" if fixed else "problem"})
        del d["log"][:-200]
        _save(d)


def summary_for_llm(max_items=6):
    """Короткая сводка доски для системного промпта Сайки — чтобы она была в
    курсе своей истории разработки и могла ответить, чем сейчас занимаемся."""
    d = _load()

    def names(col, n):
        return [it["text"] for it in d["items"] if it["col"] == col][:n]

    parts = []
    doing = names("doing", max_items)
    if doing:
        parts.append("сейчас в работе: " + "; ".join(doing))
    hot = [f"{c} ×{b['count']}" for c, b in sorted(
        d.get("bugs", {}).items(), key=lambda x: -x[1]["count"])
        if b["count"] > 0 and not b["resolved"]][:5]
    if hot:
        parts.append("часто ломается: " + ", ".join(hot))
    planned = names("planned", max_items)
    if planned:
        parts.append("в планах: " + "; ".join(planned))
    ideas = names("ideas", 4)
    if ideas:
        parts.append("идеи: " + "; ".join(ideas))
    done_ct = len([it for it in d["items"] if it["col"] == "done"])
    parts.append(f"уже готово пунктов: {done_ct}")
    return " | ".join(parts)


def _render_md(d):
    out = ["# Дев-доска Сайки", "",
           f"_обновлено: {d.get('updated', '')}_", ""]
    for key, title in COLS:
        items = [it for it in d["items"] if it["col"] == key]
        out.append(f"## {title}")
        if not items:
            out.append("_(пусто)_")
        for it in items:
            line = f"- {it['text']}"
            if it.get("note"):
                line += f" — {it['note']}"
            out.append(line)
        out.append("")
    # авто: что часто ломается
    hot = sorted(((c, b) for c, b in d.get("bugs", {}).items() if b["count"] > 0),
                 key=lambda x: -x[1]["count"])
    if hot:
        out.append("## 🔥 Часто ломается (авто)")
        for c, b in hot:
            mark = "✓ починено" if b["resolved"] else "не починено"
            out.append(f"- **{c}** ×{b['count']} — {mark}. {b['text']}")
        out.append("")
    # последние события
    out.append("## 🧾 Последние события")
    for e in d.get("log", [])[-15:][::-1]:
        out.append(f"- `{e['ts']}` {e['text']}")
    return "\n".join(out)
