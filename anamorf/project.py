"""РАБОЧИЙ СЕАНС: «давай сделаем новый проект» и всё, что из этого следует.

Владелец 05.09.2026, дословно про то, как это должно выглядеть:

    «вспомни, как Тони Старк работал с Джарвисом… "давай создадим
     секретный проект, создай новый файл, будем работать над принципиально
     новым продуктом" — то есть мы слушаем и одновременно создаём папку
     проекта, попутно Сайка спрашивает: где будем работать, что возьмём за
     основу… я в блендере сижу, начинаю моделить, прошу закинуть реф на
     задний фон — она параллельно мне в блендер закидывает реф под мою
     сетку… такая совместная фул-работа, где она помогает многие операции
     делать, не позволяя мне лишний раз ползать за файлами или копаться в
     браузере»

═══ ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ, А НЕ ЕЩЁ ОДИН ИНСТРУМЕНТ ═══

Инструменты у неё уже есть: открыть папку, скачать файл, найти в сети,
запустить программу. Чего не было — ОБЩЕГО ПРЕДМЕТА РАЗГОВОРА. Каждый
вызов начинался с нуля и заканчивался вопросом «куда положить». Человек
при этом сидит в блендере и не хочет отвечать на этот вопрос двадцать раз
за вечер: он один раз сказал, над чем работаем, и дальше всё падает туда
само.

Сеанс — это и есть общий предмет: имя, папка, что делаем, чем вдохновля-
емся, какие программы в деле. После `start()` слова «скачай вот это»,
«кинь реф на фон», «сохрани блендер» перестают требовать адреса.

═══ ГДЕ ЛЕЖИТ ПАПКА ═══

Владелец на прямой вопрос ответил: «там, где скажу — мы же её как раз
учим ходить по системе, по папкам вперёд-назад, сразу в нужную или
вернуться в проводник».

Поэтому НЕТ зашитого корня «Работы». Место называется словами при
создании («на диске D», «в моих проектах», «туда же, где вчера») и
разбирается её же памятью мест (file_hands.place_*), которая копит, куда
он реально ходит. Не назвал вовсе — берём последнее место, где заводили
проект; нет и его — честно спрашиваем, а не кладём наугад.

Правило про «когда человека нет рядом» — оттуда же: файл кладётся В ПАПКУ
ТЕКУЩЕГО ПРОЕКТА, рядом с тем, из чего он сделан, и она говорит, куда
положила. Не на рабочий стол: туда попадает только то, что специально
попросили.

═══ ЧЕГО ЗДЕСЬ НЕТ ═══

Здесь нет ни одного действия с внешним миром: ни скачиваний, ни блендера,
ни браузера. Только состояние и раскладка папок. Действия живут в своих
модулях и спрашивают у сеанса адрес — так сеанс невозможно сломать
падением скачивания, а скачивание не зависит от того, заведён ли проект.
"""
import json
import logging
import re
import threading
import time
from pathlib import Path

from anamorf.config import CFG, DATA_ROOT

log = logging.getLogger("saika.project")

STATE = DATA_ROOT / "data" / "project.json"
_LOCK = threading.Lock()

# раскладка папки проекта. Названия по-русски намеренно: человек ходит
# сюда проводником, и «refs» ему ничего не говорит.
LAYOUT = ("рефы", "блендер", "экспорт", "исходники")


def _slug(name: str) -> str:
    """Имя папки из фразы. Кириллицу НЕ транслитерируем: он читает эти
    папки глазами, и «Персонаж под UE5» понятнее, чем «personazh-pod-ue5»."""
    t = re.sub(r"[<>:\"/\\|?*\n\r\t]+", " ", (name or "").strip())
    t = re.sub(r"\s+", " ", t).strip(" .")
    return t[:60] or ("Проект " + time.strftime("%d.%m %H-%M"))


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d: dict):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    except Exception as e:
        log.warning("сеанс не записался: %s", e)


def current() -> dict:
    """Текущий проект или пустой словарь. Пустой — это нормально: до
    первого «давай сделаем» никакого проекта и нет."""
    d = _load()
    cur = d.get("current") or {}
    if cur.get("dir") and not Path(cur["dir"]).exists():
        # папку унесли или переименовали руками — врать про неё нельзя
        log.warning("Папка проекта «%s» исчезла: %s", cur.get("name"),
                    cur.get("dir"))
        cur["missing"] = True
    return cur


def where_last() -> str:
    """Где заводили прошлый проект — умолчание, если место не назвали."""
    return str(_load().get("last_root") or "")


def resolve_place(place: str) -> str:
    """Слова про место -> путь на диске.

    Порядок намеренно такой: сначала её память мест (туда попадает то,
    куда человек РЕАЛЬНО ходит), потом прямой путь, потом прошлый корень.
    Ничего не выдумываем: не нашли — вернём пустую строку, и вызывающий
    обязан спросить, а не положить наугад."""
    p = (place or "").strip().strip('"«»')
    if not p:
        return where_last()
    # прямой путь человек тоже называет: «в D:\Работы»
    try:
        cand = Path(p)
        if cand.is_absolute() and cand.exists():
            return str(cand)
    except Exception:
        pass
    try:
        from anamorf import file_hands as _fh
        places = _fh._places_load() or {}
        key = p.lower()
        # точное имя места, потом вхождение: он говорит «в проектах», а
        # место записано как «мои проекты»
        got = ""
        if key in places:
            got = _fh._place_path(places[key])
        if not got:
            for nm, v in places.items():
                if key in nm or nm in key:
                    got = _fh._place_path(v)
                    if got:
                        break
        if got and Path(got).exists():
            return str(Path(got))
    except Exception as e:
        log.debug("память мест не ответила: %s", e)
    # «здесь», «в этой папке» — там, где он сейчас ходит проводником
    if re.search(r"\b(здесь|тут|в этой папке|сюда)\b", p, re.I):
        # «здесь» — это папка, открытая у него в проводнике ПРЯМО СЕЙЧАС.
        # pc_control.here() читает её у живого окна Explorer, а не гадает.
        try:
            from anamorf import pc_control as _pc
            cwd = _pc.here()
            if cwd and Path(cwd).is_dir():
                return str(Path(cwd))
        except Exception as e:
            log.debug("проводник не сказал, где он: %s", e)
    return ""


def start(name: str, goal: str = "", place: str = "",
          apps: list = None) -> dict:
    """Завести проект. Возвращает {ok, dir, ask} — где ask непустой,
    когда место назвать не смогли и надо спросить человека."""
    root = resolve_place(place)
    if not root:
        return {"ok": False, "ask": (
            "Где заводим папку? Скажи место — «на диске D», «в моих "
            "проектах», «туда же, где прошлый» — или открой нужную папку "
            "в проводнике и скажи «здесь».")}
    nm = _slug(name)
    d = Path(root) / nm
    try:
        for sub in LAYOUT:
            (d / sub).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"ok": False, "ask": "",
                "error": "не смогла создать папку %s: %s" % (d, e)}
    cur = {"name": nm, "dir": str(d), "goal": (goal or "").strip(),
           "apps": list(apps or []), "started": time.time(),
           "refs": [], "notes": []}
    with _LOCK:
        st = _load()
        st.setdefault("history", []).insert(0, {"name": nm, "dir": str(d),
                                                "ts": time.time()})
        st["history"] = st["history"][:30]
        st["current"] = cur
        st["last_root"] = str(root)
        _save(st)
    # место, где он заводит проекты, запоминаем как место — в следующий раз
    # хватит слова «туда же»
    try:
        from anamorf import file_hands as _fh
        _fh.place_seen("проекты", str(root))
    except Exception:
        pass
    log.info("Проект «%s» заведён: %s", nm, d)
    return {"ok": True, "dir": str(d), "name": nm, "ask": ""}


def folder(kind: str = "") -> str:
    """Папка проекта или её подпапка. Пустая строка — проекта нет."""
    cur = current()
    if not cur.get("dir"):
        return ""
    d = Path(cur["dir"])
    if kind:
        for sub in LAYOUT:
            if kind.lower() in sub:
                d = d / sub
                break
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return str(d)


def add_ref(path: str, source: str = "", why: str = ""):
    """Записать референс в дневник проекта. Файл уже лежит на диске —
    сюда попадает только след: откуда взяли и зачем."""
    with _LOCK:
        st = _load()
        cur = st.get("current") or {}
        if not cur:
            return
        cur.setdefault("refs", []).append(
            {"file": str(path), "from": source[:300], "why": why[:160],
             "ts": round(time.time(), 1)})
        cur["refs"] = cur["refs"][-300:]
        st["current"] = cur
        _save(st)


def note(text: str):
    with _LOCK:
        st = _load()
        cur = st.get("current") or {}
        if not cur:
            return
        cur.setdefault("notes", []).append(
            {"t": str(text)[:400], "ts": round(time.time(), 1)})
        cur["notes"] = cur["notes"][-200:]
        st["current"] = cur
        _save(st)


def close():
    with _LOCK:
        st = _load()
        st["current"] = {}
        _save(st)


def for_llm() -> str:
    """Строка в промпт. Появляется, только когда проект есть: без него
    это ноль полезного и двести токенов расхода."""
    cur = current()
    if not cur.get("name"):
        return ""
    parts = ["Работаем над «%s»" % cur["name"]]
    if cur.get("goal"):
        parts.append(cur["goal"][:120])
    parts.append("папка: %s" % cur.get("dir", ""))
    n = len(cur.get("refs") or [])
    if n:
        parts.append("собрано референсов: %d" % n)
    if cur.get("missing"):
        parts.append("ВНИМАНИЕ: папки на месте нет — её унесли или "
                     "переименовали, скажи об этом человеку")
    return ("Проект: " + "; ".join(parts) +
            ". Файлы по этой работе клади СЮДА, адрес не переспрашивай.")
