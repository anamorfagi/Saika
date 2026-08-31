"""«ПОДНЯТЬ ВСЁ» — один проход супервизора (2026-08-22).

Раньше поднять систему целиком можно было только руками: ткнуть слух,
дождаться, ткнуть мозги, посмотреть, влез ли голос. На 16 ГБ видеопамяти
gemma-4-e4b @ 32k + large-v3-turbo + клон-голос вместе НЕ ВЛЕЗАЮТ — и
человек узнавал об этом по молчанию, а не словами.

Этот проход делает то же самое, но по порядку и вслух:

  1. РУКИ и ОБРАЗ — бесплатные проверки, без видеопамяти.
  2. СЛУХ — без него команды не доедут вовсе, поэтому он первый из тяжёлых.
  3. МОЗГИ — локальная модель.
  4. ГОЛОС — последним: он единственный, кого не жалко понизить.

ДВА ЗАКОНА, ради которых он вообще написан:

* НЕ ВРАТЬ. Каждый шаг заканчивается ПРОВЕРКОЙ (`is_loaded()`), и вердикт
  собирается из результатов шагов, а не из намерений. «Подняла всё» имеет
  право появиться, только если всё действительно поднялось.
* НЕ КРУТИТЬСЯ ПО КРУГУ. У шага ровно одна попытка и одна попытка после
  освобождения памяти. Ступень разгрузки тратится один раз за проход.
  Кончились ступени — проход ОСТАНАВЛИВАЕТСЯ и честно говорит, что именно
  держит видеопамять и чем пожертвовать, а не ходит по второму разу.

Ступени берутся из `anamorf/triage.py` — те же, что у сторожа железа, и в
том же порядке (лишние движки -> лёгкий голос -> озвучка). МОЗГИ и ВСЁ
(ступени 4 и 5) здесь намеренно не трогаются: снимать то, что сам же
поднимаешь, — это и есть круг.
"""
from __future__ import annotations

import logging
import threading
import time

from anamorf.config import CFG

log = logging.getLogger("saika.bringup")

STATE = {"running": False, "steps": [], "verdict": "", "started": 0.0,
         "finished": 0.0}

# наружу: чем объявлять человеку (ставит main, чтобы не тащить сюда веб)
ANNOUNCE = {"fn": None}

_LIGHT_VOICES = ("silero", "piper", "edge")


def state() -> dict:
    d = dict(STATE)
    d["steps"] = list(STATE["steps"])
    return d


def _say(evt: dict):
    fn = ANNOUNCE.get("fn")
    if fn:
        try:
            fn(evt)
        except Exception as e:
            log.debug("объявить не вышло: %s", e)


def _step(key: str, title: str, ok: bool, why: str = "", note: str = ""):
    rec = {"key": key, "title": title, "ok": bool(ok), "why": why,
           "note": note, "ts": round(time.time(), 1)}
    STATE["steps"].append(rec)
    log.info("bringup %s: %s%s", key, "ok" if ok else "НЕ вышло",
             f" ({why})" if why else "")
    _say({"type": "bringup", "step": rec, "running": True})
    return rec


# ───────────────────────── освобождение памяти ───────────────────────
def _vram() -> dict:
    try:
        from anamorf.guard import _read_gpu
        return _read_gpu() or {}
    except Exception:
        return {}


def _free_mb() -> float:
    g = _vram()
    tot, used = float(g.get("vram_total_mb") or 0), float(g.get("vram_mb") or 0)
    return max(0.0, tot - used) if tot else 0.0


def _holders() -> str:
    """Кто сейчас держит видеопамять — чтобы вердикт называл имена."""
    who = []
    try:
        from anamorf.llm import manager as llm
        for m in llm.loaded_models():
            who.append(f"модель {m}")
    except Exception:
        pass
    try:
        from anamorf.main import stt, tts
        for n, e in (getattr(tts, "engines", {}) or {}).items():
            try:
                if n not in _LIGHT_VOICES and e.is_loaded():
                    who.append(f"голос {n}")
            except Exception:
                pass
        for n, e in (getattr(stt, "instances", {}) or {}).items():
            try:
                if e.is_loaded():
                    who.append(f"слух {n}")
            except Exception:
                pass
    except Exception:
        pass
    return ", ".join(who) if who else "не моя модель (чужой процесс)"


class _Ladder:
    """Ступени разгрузки, каждая — один раз за проход."""

    def __init__(self):
        from anamorf import triage
        self.steps = [("лишние движки", triage._drop_extra),
                      ("лёгкий голос", triage._light_voice),
                      ("озвучка", triage._drop_voice)]
        self.i = 0

    def free_one(self) -> str:
        """Опустить одну ступень. Возвращает её имя или '' — если кончились."""
        while self.i < len(self.steps):
            name, fn = self.steps[self.i]
            self.i += 1
            try:
                if fn() is not False:
                    return name
            except Exception as e:
                log.warning("ступень «%s» не сработала: %s", name, e)
        return ""


# ───────────────────────────────  шаги  ──────────────────────────────
def _up_hands() -> tuple[bool, str]:
    try:
        from anamorf import pc_control  # noqa: F401
        return True, ""
    except Exception as e:
        return False, f"модуль рук не поднялся: {e}"


def _up_face() -> tuple[bool, str]:
    if not CFG.get("avatar.enabled", True):
        return True, "выключен человеком"
    try:
        from anamorf.main import _avatar_model_path
        p = _avatar_model_path()
    except Exception as e:
        return False, str(e)
    return (True, p.name) if p.exists() else (False, f"нет файла модели: {p}")


def _up_hear(ladder: _Ladder) -> tuple[bool, str]:
    from anamorf.main import stt
    name = str(CFG.get("stt.engine", "") or "")
    if name in ("", "off", "none"):
        # автопуск и жёсткая разгрузка оставляют записку, каким слух был
        name = str(CFG.get("stt.engine_was", "") or "")
        if not name or name in ("off", "none"):
            return True, "выключен человеком"
        stt.set_engine(name)
    return _load_with_room("stt", name, ladder)


def _up_brain(ladder: _Ladder) -> tuple[bool, str]:
    if CFG.get("llm.off", False):
        return True, "выключены человеком"
    from anamorf.llm import manager as llm
    b, m = str(CFG.get("llm.backend", "")), str(CFG.get("llm.model", ""))
    if not b or not m:
        return False, "не выбраны бэкенд или модель"
    if not any(llm.backend_status().values()):
        return False, ("ни один бэкенд не отвечает — запусти Ollama или "
                       "LM Studio (Developer -> Start Server)")
    for attempt in (1, 2):
        try:
            llm.warmup(b, m)
        except Exception as e:
            log.info("bringup: прогрев мозгов не удался: %s", e)
        # ПРОВЕРКА: модель обязана быть в списке РЕАЛЬНО загруженных
        if m in (llm.loaded_models() or []):
            return True, m
        if attempt == 1:
            freed = ladder.free_one()
            if not freed:
                break
            _step("free", f"освободила: {freed}", True)
    return False, (f"«{m}» не встала в память (свободно "
                   f"{int(_free_mb())} МБ, держат: {_holders()})")


def _up_voice(ladder: _Ladder) -> tuple[bool, str]:
    from anamorf.main import tts
    name = str(CFG.get("tts.engine", "") or "")
    if name in ("", "off", "none"):
        return True, "выключен человеком"
    ok, why = _load_with_room("tts", name, ladder)
    if ok:
        return True, name
    # ПОНИЖЕНИЕ, А НЕ МОЛЧАНИЕ: свой голос не влез — берём лёгкий.
    have = list(getattr(tts, "engines", {}) or {})
    for light in [n for n in _LIGHT_VOICES if n in have and n != name]:
        ok2, _ = _load_with_room("tts", light, ladder, room=False)
        if ok2:
            try:
                tts.set_engine(light)
            except Exception:
                pass
            return False, (f"свой голос «{name}» не поднялся ({why}) — "
                           f"говорю лёгким «{light}»")
    return False, f"«{name}» не поднялся ({why}), и лёгкой замены нет"


def _load_with_room(kind: str, name: str, ladder: _Ladder,
                    room: bool = True) -> tuple[bool, str]:
    """Поднять движок; если не влез по памяти — освободить ОДНУ ступень и
    попробовать ещё РОВНО раз. Больше кругов нет."""
    from anamorf import repair
    ok, why = repair._try_load(kind, name)
    if ok:
        return True, ""
    if not room:
        return False, why
    from anamorf import diagnostics as dg
    cat = dg.classify(f"{kind}.{name}", why).get("category", "")
    if cat not in ("vram", "space", "unknown"):
        return False, why                      # память ни при чём — не тратим
    freed = ladder.free_one()
    if not freed:
        return False, (f"{why} (свободно {int(_free_mb())} МБ, "
                       f"держат: {_holders()})")
    _step("free", f"освободила: {freed}", True)
    ok, why2 = repair._try_load(kind, name)
    return (True, "") if ok else (False, why2 or why)


# ───────────────────────────────  проход  ────────────────────────────
def _pass():
    ladder = _Ladder()
    t0 = time.time()
    try:
        ok, why = _up_hands()
        _step("hands", "руки", ok, why)
        ok, why = _up_face()
        _step("face", "образ", ok, why if not ok else "", why if ok else "")
        ok, why = _up_hear(ladder)
        _step("hear", "слух", ok, "" if ok else why, why if ok else "")
        ok, why = _up_brain(ladder)
        _step("brain", "мозги", ok, "" if ok else why, why if ok else "")
        ok, why = _up_voice(ladder)
        _step("voice", "голос", ok, "" if ok else why, why if ok else "")
    except Exception as e:
        log.exception("проход «поднять всё» упал")
        _step("crash", "проход прерван", False, str(e))
    STATE["verdict"] = _verdict()
    STATE["finished"] = time.time()
    STATE["running"] = False
    log.info("bringup за %.1fс: %s", time.time() - t0, STATE["verdict"])
    _say({"type": "bringup", "running": False, "verdict": STATE["verdict"],
          "steps": list(STATE["steps"])})
    try:
        from anamorf import repairs
        if all(s["ok"] for s in STATE["steps"]):
            repairs.note_healthy()
    except Exception:
        pass


def _verdict() -> str:
    """Вердикт СОБИРАЕТСЯ ИЗ ШАГОВ. Никаких «всё готово» из головы."""
    real = [s for s in STATE["steps"] if s["key"] != "free"]
    bad = [s for s in real if not s["ok"]]
    if not real:
        return "Проход не сделал ни одного шага — это поломка самого прохода."
    if not bad:
        names = ", ".join(s["title"] for s in real)
        return f"Подняла всё: {names}. Проверено загрузкой, не на словах."
    good = ", ".join(s["title"] for s in real if s["ok"]) or "ничего"
    lines = [f"Подняла: {good}. НЕ поднялось:"]
    for s in bad:
        lines.append(f"• {s['title']} — {s['why']}")
    lines.append("Больше кругов делать не буду: дальше нужно решение — "
                 "что снять с видеокарты или чем пожертвовать.")
    return "\n".join(lines)


def start() -> dict:
    """Запустить проход в фоне. Второй запуск поверх идущего — не запускать."""
    if STATE["running"]:
        return {"ok": False, "why": "проход уже идёт", **state()}
    STATE.update(running=True, steps=[], verdict="", started=time.time(),
                 finished=0.0)
    threading.Thread(target=_pass, daemon=True, name="bringup").start()
    return {"ok": True, **state()}


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

