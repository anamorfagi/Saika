"""КАРТОЧКИ ПЕРСОНАЖЕЙ — костюмы, а не подмена личности (2026-08-13).

Владелец: «попробовать замутить карточки персонажей разных из игр, аниме,
фильмов… останется только голоса намутить и проработать голосовую систему,
чтобы нужный тон, тембр, скорость получать».

УСТРОЙСТВО. Карточка — это КОСТЮМ поверх Сайки, а не другая Сайка. Под
костюмом остаётся она: её память, её отношение к Виталию, её руки и её
предохранители. Это не осторожность ради осторожности — это чтобы «сними
костюм» работало мгновенно и без побочных эффектов, и чтобы персонаж не
утаскивал за собой доступ к файлам и клавиатуре с чужой мотивацией.

ЧТО В КАРТОЧКЕ:
    id       короткое имя файла
    name     как зовут
    source   откуда (игра/аниме/фильм) — контекст, а не обязанность
    persona  кто это: характер, мотивация, отношение к собеседнику
    speech   КАК говорит: длина фраз, лексика, ритм, словечки
    taboo    чего этот персонаж не делает никогда
    voice    {engine, ref, speed, pitch, tone} — голосовая часть
    nsfw     разрешена ли грубая лексика в её речи

ГОЛОС отдельным блоком не случайно: половина узнаваемости персонажа — это
тембр и темп, а не слова. Движок и образец подставляются при надевании
костюма и возвращаются на место при снятии — Сайкин собственный голос не
теряется никогда.
"""
import json
import logging
from pathlib import Path

from anamorf.config import CFG, resolve

log = logging.getLogger("saika.cards")

_ACTIVE = {"id": "", "restore": {}}


def _dir() -> Path:
    d = resolve("characters")
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_cards() -> list[dict]:
    out = []
    for f in sorted(_dir().glob("*.json")):
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
            c["id"] = c.get("id") or f.stem
            out.append(c)
        except Exception as e:
            log.warning("карточка %s не читается: %s", f.name, e)
    return out


def get(cid: str) -> dict:
    f = _dir() / f"{(cid or '').strip()}.json"
    if not f.exists():
        for c in list_cards():
            if c.get("name", "").lower() == (cid or "").lower():
                return c
        return {}
    try:
        c = json.loads(f.read_text(encoding="utf-8"))
        c["id"] = c.get("id") or f.stem
        return c
    except Exception:
        return {}


def save(card: dict) -> str:
    cid = (card.get("id") or card.get("name") or "").strip().lower()
    cid = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in cid)
    if not cid:
        raise ValueError("у карточки нет имени")
    card["id"] = cid
    (_dir() / f"{cid}.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Карточка сохранена: %s", cid)
    return cid


def active() -> dict:
    return get(_ACTIVE["id"]) if _ACTIVE["id"] else {}


def _apply_voice(v: dict):
    """Подставить голос персонажа, запомнив свой — чтобы вернуть."""
    if not v:
        return
    from anamorf.tts import extra as _ex
    keys = ["tts.engine", "tts.voice_ref_wav", "tts.voice_ref",
            "tts.speed", "tts.pitch", "tts.tone"]
    if not _ACTIVE["restore"]:
        _ACTIVE["restore"] = {k: CFG.get(k) for k in keys}
    eng = v.get("engine") or CFG.get("tts.engine")
    if eng:
        CFG.set("tts.engine", eng)
    ref = v.get("ref") or ""
    if ref:
        try:
            _ex.set_voice(eng, ref)
        except Exception as e:
            log.warning("голос «%s» не встал: %s", ref, e)
    if v.get("speed"):
        CFG.set("tts.speed", float(v["speed"]))
    if v.get("pitch") is not None:
        CFG.set("tts.pitch", float(v["pitch"]))
    if v.get("tone"):
        CFG.set("tts.tone", str(v["tone"]))


def _restore_voice():
    for k, val in (_ACTIVE["restore"] or {}).items():
        try:
            CFG.set(k, val)
        except Exception:
            pass
    _ACTIVE["restore"] = {}


def wear(cid: str) -> str:
    c = get(cid)
    if not c:
        have = ", ".join(x["id"] for x in list_cards()) or "ни одной"
        return f"Карточки «{cid}» нет. Есть: {have}."
    if _ACTIVE["id"]:
        _restore_voice()
    _ACTIVE["id"] = c["id"]
    _apply_voice(c.get("voice") or {})
    src = f" ({c['source']})" if c.get("source") else ""
    return f"надела костюм: {c.get('name', c['id'])}{src}"


def off() -> str:
    if not _ACTIVE["id"]:
        return "костюма и так нет — это я"
    was = _ACTIVE["id"]
    _restore_voice()
    _ACTIVE["id"] = ""
    return f"сняла костюм «{was}», вернулась к себе"


def block() -> str:
    """Костюм для промпта. Пусто — значит Сайка как она есть."""
    c = active()
    if not c:
        return ""
    p = [f"### Костюм: {c.get('name', c['id'])}"
         + (f" — {c['source']}" if c.get("source") else "")]
    p.append("Ты ИГРАЕШЬ этого персонажа поверх себя. Под костюмом ты "
             "остаёшься собой: твоя память, твои руки, твои границы и твоё "
             "отношение к Виталию не меняются. Костюм задаёт манеру и "
             "реакции, а не то, кому ты служишь. Попросят «сними костюм» — "
             "снимаешь сразу.")
    if c.get("persona"):
        p.append("КТО ЭТО: " + c["persona"])
    if c.get("speech"):
        p.append("КАК ГОВОРИТ: " + c["speech"])
    if c.get("taboo"):
        p.append("НИКОГДА: " + c["taboo"])
    if c.get("nsfw"):
        p.append("Резкая лексика этому персонажу идёт — используй её, если "
                 "она к месту, а не в каждой фразе. Грубость направлена "
                 "на ситуацию, не на человека.")
    return "\n".join(p)


# ─────────── карточка, сочинённая самой системой ───────────
_MAKE_PROMPT = """Составь карточку персонажа для ролевой системы.
Персонаж: {who}

Ответь ТОЛЬКО JSON, без пояснений и без markdown-заборов:
{{"id": "короткое-латиницей", "name": "имя", "source": "откуда родом",
 "persona": "кто это: характер, мотивация, отношение к собеседнику — 3-5 предложений",
 "speech": "КАК говорит: длина фраз, лексика, ритм, характерные словечки — 2-3 предложения",
 "taboo": "чего этот персонаж не делает никогда — 1 предложение",
 "nsfw": false}}
Пиши по-русски. persona и speech — это то, что отличает ЭТОГО персонажа от
любого другого; общие слова вроде «добрый и смелый» бесполезны."""


def make(who: str) -> str:
    """Сочинить карточку сильнейшим доступным мозгом и положить в папку.

    Сочиняет НЕ автор системы, а сама Сайка: список персонажей бесконечен,
    зашивать его в код бессмысленно, а мелкая локальная модель на такой
    задаче выдаёт кашу — поэтому берём верх лестницы мозгов."""
    from anamorf.llm import brains, manager
    who = (who or "").strip()
    if not who:
        return "кого сделать?"
    step = brains.next_brain() or {}
    backend = step.get("backend") or CFG.get("llm.backend", "")
    model = step.get("model") or CFG.get("llm.model", "")
    raw = manager.ask_specific(
        backend, model,
        [{"role": "user", "content": _MAKE_PROMPT.format(who=who)}],
        max_len=3000)
    txt = (raw or "").strip()
    if "```" in txt:
        txt = txt.split("```")[1].lstrip("json").strip()
    i, j = txt.find("{"), txt.rfind("}")
    if i < 0 or j < 0:
        return f"мозг {model} вернул не JSON: {txt[:120]}"
    try:
        card = json.loads(txt[i:j + 1])
    except Exception as e:
        return f"карточка не разобралась ({e}): {txt[:120]}"
    card.setdefault("voice", {})
    cid = save(card)
    return (f"карточка «{card.get('name', cid)}» готова (сочинил {model}). "
            f"Надеть: костюм {cid}")


# ── ЖИВАЯ ИНЪЕКЦИЯ (2026-08-23, владелец: «я должен видеть изменения
# вживую, без долбаных ручных перезапусков»). Этот блок — дверь, через
# которую живое обновление кода попадает в УЖЕ РАБОТАЮЩИЙ процесс, где
# сторож кода не был запущен (моя же ошибка: срезал строку запуска).
# Механика: модуль лениво импортируется ручкой API при первом обращении —
# страница интерфейса после своей автоперезагрузки дёргает ручку, и этот
# код исполняется ВНУТРИ живого процесса. Никаких перезапусков.
# Блок безвреден при любом повторе (_saika_live_boot на sys) и остаётся
# на будущее как страховка: если сторож когда-нибудь снова умрёт, первый
# же заход в эту ручку его поднимет.
def _live_boot():
    import sys as _s
    if getattr(_s, "_saika_live_boot", False):
        return
    _s._saika_live_boot = True
    import logging
    import threading
    _lg = logging.getLogger("saika.live")
    try:
        from anamorf import live as _lv        # свежий, прямо с диска
        # 1) перечитать модули, менявшиеся, пока сторож был мёртв.
        #    Список явный: у config и ему подобных перечитывание раздваивает
        #    живое состояние, их не трогаем.
        for _n in ("anamorf.persona", "anamorf.reflex", "anamorf.pc_control",
                   "anamorf.highlight", "anamorf.highlight_win",
                   "anamorf.llm.manager", "anamorf.llm.llamacpp",
                   "anamorf.llm.tools", "anamorf.llm.brains",
                   "anamorf.tts.manager", "anamorf.self_control",
                   "anamorf.trust", "anamorf.orb", "anamorf.desk_avatar",
                   "anamorf.diagnostics"):
            try:
                ok, note = _lv.reload_module(_n)
                if ok and _n in _s.modules:
                    _lg.warning("Живая инъекция: %s — %s", _n, note)
            except Exception as _e:
                _lg.warning("Живая инъекция: %s не перечитался: %s", _n, _e)
        # 2) главный модуль — хирургией по определениям. Снимка «как было»
        #    нет, значит live применит все определения заново: объекты те
        #    же, маршруты пересаживаются, состояние не трогается.
        _mn = None
        for _cand in ("anamorf.main", "main", "__main__"):
            _m = _s.modules.get(_cand)
            if _m is not None and hasattr(_m, "_code_watch"):
                _mn, _mm = _cand, _m
                break
        if _mn:
            try:
                if hasattr(_mm, "__live_src__"):
                    del _mm.__live_src__
                done, bad = _lv.patch_module(_mn, _mm.__file__)
                _lg.warning("Живая инъекция: main — применено %d определений"
                            ", не доехало: %s", len(done),
                            "; ".join(bad)[:160] or "ничего")
            except Exception as _e:
                _lg.warning("Живая инъекция: main не пропатчился: %s", _e)
            # 3) поднять сторожа кода — дальше он живёт сам
            try:
                if not getattr(_s, "_saika_once_code_watch", False):
                    _s._saika_once_code_watch = True
                    threading.Thread(target=_mm._code_watch, daemon=True,
                                     name="code-live").start()
                    _lg.warning("Живая инъекция: сторож кода ЗАПУЩЕН — "
                                "дальше правки едут сами")
            except Exception as _e:
                _lg.warning("Живая инъекция: сторож не поднялся: %s", _e)
        try:
            _mm.broadcast_event({"type": "baymax", "mood": "ok",
                                 "text": "Живое обновление кода въехало без "
                                         "перезапуска — дальше правки "
                                         "подхватываются сами."})
        except Exception:
            pass
    except Exception as _e:
        _lg.warning("Живая инъекция сорвалась: %s", _e)


_live_boot()

