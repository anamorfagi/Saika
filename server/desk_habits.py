"""ПРИВЫЧКИ РАБОЧЕГО СТОЛА — заметить раскладку и предложить пресет.

ИДЕЯ ВЛАДЕЛЬЦА, дословно (2026-08-18):

    «можно ещё дать Сайке понимание, когда она смотрит на то, какие проги в
     среднем всегда открыты на экранах, если она увидит это как паттерн,
     увидит, как окна на экранах в каком расположении человек ставит — она
     могла бы через несколько сессий спросить, выведя в чат окно: создать
     рабочий пресет окон? Или, например, видит, как окна расположены в
     режиме игры — также в чате показывает создать игровой режим»

ПОЧЕМУ ЭТО НЕ «ЕЩЁ ОДНА ФИЧА». Расставлять окна руками — работа, которую
человек делает каждый день заново и никогда не считает работой. Он и не
попросит её автоматизировать: чтобы попросить, надо сначала заметить, что
ты это делаешь. Заметить может Сайка — она и так каждый ход видит стол.

ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ ОБХОДА ДИСКОВ. Тем же, чем память на места: мы
ничего не выведываем и не сканируем. Стол она и так видит на каждом шаге —
здесь только СЧЁТЧИК того, что уже прошло у неё перед глазами.

ТРИ ПРАВИЛА, ЧТОБЫ НЕ СТАТЬ НАЗОЙЛИВОЙ:
  * три встречи минимум. Одно совпадение — случайность, два — совпадение;
  * предложение ОДИН раз. Отказался — про это сочетание больше не спрашиваем;
  * мелочь не считается. Окно меньше 15% экрана в раскладку не входит:
    человек расставляет крупное, а не блокнот в углу.

ИГРОВОЙ РЕЖИМ УЗНАЁМ ПО ФОРМЕ, А НЕ ПО ИМЕНИ. Полноэкранное окно, всё
остальное свёрнуто — это игра или кино на любом ПК, и список игр для этого
знать не нужно. Список имён устарел бы на следующей установке.
"""
import json
import logging
import time
from pathlib import Path

from server.config import ROOT

log = logging.getLogger("saika.habits")

STORE = ROOT / "data" / "desk_habits.json"

MIN_TIMES = 3          # сколько раз увидеть, чтобы предложить
MIN_AREA = 0.15        # доля экрана, ниже которой окно в раскладку не идёт
GAP_S = 180.0          # не чаще раза в три минуты — это наблюдение, не опрос
MAX_WINS = 6           # длиннее раскладки человек всё равно не держит

_last_note = {"ts": 0.0}


def _load() -> dict:
    try:
        d = json.loads(STORE.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            d.setdefault("seen", {})
            d.setdefault("offered", {})
            d.setdefault("presets", {})
            return d
    except Exception:
        pass
    return {"seen": {}, "offered": {}, "presets": {}}


def _save(d: dict):
    try:
        STORE.parent.mkdir(exist_ok=True)
        STORE.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    except Exception as e:
        log.debug("привычки стола не записались: %s", e)


def _zone(w: dict, mon: dict) -> str:
    """Куда человек поставил окно, СЛОВАМИ. Пиксели тут вредны: подвинул на
    десять точек — и это уже «другая» раскладка, которая никогда не
    накопит три встречи. Человек мыслит половинами и углами, ими и меряем."""
    if w.get("maximized"):
        return "весь экран"
    ml, mt, mr, mb = mon["work"]
    mw, mh = max(1, mr - ml), max(1, mb - mt)
    x, y = w.get("x", ml), w.get("y", mt)
    ww, wh = max(1, w.get("w", mw)), max(1, w.get("h", mh))
    # почти во весь экран, но без флага maximized — так ведут себя игры
    if ww >= mw * 0.95 and wh >= mh * 0.95:
        return "весь экран"
    cx = (x + ww / 2 - ml) / mw
    cy = (y + wh / 2 - mt) / mh
    gx = "лево" if cx < 0.38 else ("право" if cx > 0.62 else "середина")
    gy = "верх" if cy < 0.38 else ("низ" if cy > 0.62 else "середина")
    if gx == "середина" and gy == "середина":
        return "центр"
    if gy == "середина":
        return gx
    if gx == "середина":
        return gy
    return f"{gy}-{gx}"


def snapshot() -> list:
    """Крупные видимые окна: что, где, как стоит. Свои окна не считаем —
    интерфейс Сайки открыт всегда и в привычку не входит."""
    try:
        from server import pc_control as pc
    except Exception:
        return []
    try:
        mons = {d["num"]: d for d in pc._mon_info()}
        out = []
        for w in pc.windows(include_minimized=False):
            if pc._is_self_window(w):
                continue
            mon = mons.get(w.get("monitor") or 0)
            if not mon:
                continue
            ml, mt, mr, mb = mon["work"]
            area = (w.get("w", 0) * w.get("h", 0)) / \
                   max(1, (mr - ml) * (mb - mt))
            if area < MIN_AREA:
                continue
            out.append({"proc": (w.get("proc") or w.get("cls") or "?").lower(),
                        "title": (w.get("title") or "")[:60],
                        "monitor": w.get("monitor") or 0,
                        "zone": _zone(w, mon),
                        "area": round(area, 2)})
        out.sort(key=lambda i: (i["monitor"], i["zone"]))
        return out[:MAX_WINS]
    except Exception as e:
        log.debug("снимок стола не вышел: %s", e)
        return []


def _sig(snap: list) -> str:
    return "|".join(f"{i['proc']}@{i['monitor']}@{i['zone']}" for i in snap)


def kind_of(snap: list) -> str:
    """«игра» или «работа» — по форме раскладки, не по именам программ."""
    if len(snap) == 1 and snap[0]["zone"] == "весь экран":
        return "игра"
    return "работа"


def note() -> None:
    """Посчитать текущую раскладку. Зовётся из screen_map — то есть ровно
    тогда, когда стол и так осмотрен; своего опроса системы тут нет."""
    now = time.time()
    if now - _last_note["ts"] < GAP_S:
        return
    _last_note["ts"] = now
    snap = snapshot()
    if len(snap) < 2 and kind_of(snap) != "игра":
        return                      # одно окно — это не раскладка
    sig = _sig(snap)
    if not sig:
        return
    d = _load()
    rec = d["seen"].get(sig) or {"n": 0, "first": now}
    rec["n"] = int(rec.get("n", 0)) + 1
    rec["last"] = now
    rec["layout"] = snap
    rec["kind"] = kind_of(snap)
    d["seen"][sig] = rec
    # память не должна пухнуть: держим полсотни самых частых
    if len(d["seen"]) > 50:
        keep = sorted(d["seen"].items(), key=lambda kv: -kv[1].get("n", 0))[:50]
        d["seen"] = dict(keep)
    _save(d)


def suggest() -> dict | None:
    """Созревшая привычка, про которую ещё не спрашивали. Или None."""
    d = _load()
    best = None
    for sig, rec in d["seen"].items():
        if rec.get("n", 0) < MIN_TIMES or sig in d["offered"]:
            continue
        if best is None or rec["n"] > best[1]["n"]:
            best = (sig, rec)
    if not best:
        return None
    sig, rec = best
    return {"sig": sig, "n": rec["n"], "kind": rec.get("kind", "работа"),
            "layout": rec.get("layout", [])}


def mark_offered(sig: str, answer: str = "") -> None:
    """Спросили — больше не спрашиваем. Даже если человек промолчал:
    повторять вопрос, на который не ответили, — это назойливость."""
    d = _load()
    d["offered"][sig] = {"ts": time.time(), "answer": answer}
    _save(d)


def hint() -> str:
    """Строчка для промпта. Пусто, если предлагать нечего."""
    s = suggest()
    if not s:
        return ""
    what = "игровой режим" if s["kind"] == "игра" else "рабочий пресет окон"
    items = ", ".join(f"{i['proc']} ({i['zone']}, экран {i['monitor']})"
                      for i in s["layout"][:4])
    return (f"Ты уже {s['n']} раз(а) видела одну и ту же раскладку: {items}. "
            f"Предложи человеку ОДИН раз сохранить её как {what} — своими "
            "словами, коротко. Согласится — позови desk_preset_save с именем, "
            "которое он назовёт (или «работа»/«игра»). Откажется или "
            "переведёт тему — больше про эту раскладку не заговаривай.")


# ── пресеты ───────────────────────────────────────────────────────────
def presets() -> list:
    d = _load()
    return [{"name": k, "kind": v.get("kind", "работа"),
             "windows": len(v.get("layout", []))}
            for k, v in d["presets"].items()]


def save_preset(name: str = "") -> str:
    snap = snapshot()
    if not snap:
        return "Сейчас на экранах нечего запоминать — крупных окон не вижу."
    name = (name or "").strip().lower() or kind_of(snap)
    d = _load()
    d["presets"][name] = {"layout": snap, "kind": kind_of(snap),
                          "ts": time.time()}
    # привычку, из которой вырос пресет, больше не предлагаем
    d["offered"][_sig(snap)] = {"ts": time.time(), "answer": "сохранили"}
    _save(d)
    items = ", ".join(f"{i['proc']} — {i['zone']}, экран {i['monitor']}"
                      for i in snap)
    return (f"Запомнила раскладку «{name}»: {items}. "
            f"Скажешь «включи {name}» — расставлю так же.")


def apply_preset(name: str = "") -> str:
    """Расставить окна по сохранённой раскладке. Чего нет на экране — то
    честно перечисляем, а не делаем вид, что расставили всё."""
    d = _load()
    name = (name or "").strip().lower()
    rec = d["presets"].get(name)
    if not rec:
        have = ", ".join(d["presets"]) or "ни одного"
        return f"Пресета «{name}» нет. Есть: {have}."
    from server import pc_control as pc
    _ZONE_POS = {"весь экран": "", "лево": "left", "право": "right",
                 "верх": "top", "низ": "bottom", "центр": "center",
                 "верх-лево": "topleft", "верх-право": "topright",
                 "низ-лево": "bottomleft", "низ-право": "bottomright",
                 "середина": "center"}
    done, missing = [], []
    for it in rec.get("layout", []):
        w = pc._match(it["proc"])
        if not w:
            missing.append(it["proc"])
            continue
        try:
            if it["zone"] == "весь экран":
                if it["monitor"]:
                    pc.window_place(it["proc"], "center",
                                    monitor=int(it["monitor"]))
                pc.window_maximize(it["proc"])
            else:
                pos = _ZONE_POS.get(it["zone"], "center")
                half = pos in ("left", "right")
                pc.window_place(it["proc"], pos,
                                width=50 if half else 0,
                                height=100 if half else 0,
                                monitor=int(it["monitor"] or 0))
            done.append(w["title"][:30])
        except Exception as e:
            log.debug("окно %s не встало: %s", it["proc"], e)
            missing.append(it["proc"])
    if not done:
        return (f"Пресет «{name}» есть, но ни одного его окна сейчас не "
                f"открыто: не вижу {', '.join(missing)}. Скажи человеку "
                "честно — расставлять нечего.")
    msg = f"Расставила по пресету «{name}»: {', '.join(done)}."
    if missing:
        msg += f" Не нашла на экране: {', '.join(missing)} — их не открывала."
    return msg
