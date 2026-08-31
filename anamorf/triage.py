"""СТУПЕНИ РАЗГРУЗКИ: ГАСИТЬ ПО ОДНОМУ, А НЕ ВСЁ СРАЗУ (2026-08-19).

Владелец, после того как защита железа снесла ей и слух, и голос, и мозги
посреди разговора: «я бы предложил, если реально не хватает памяти и
происходит жёсткая загрузка — вырубать озвучку временно, но чтобы слух и
мозги оставались живы, чтобы выполнять команды было возможно. Если что-то
странное с системой — детектить нагрузку или нагрев и отключать мозги,
если сильный порог проходит. Как только система видит, что всё
стабилизировалось — делает сама разогрев обратно, чтобы восстановить свою
работу».

Ровно это здесь и сделано. Порядок жертв — от наименее нужного к самому
нужному:

  1. ЛИШНИЕ ДВИЖКИ — вторая локальная модель, запасной воркер. Их никто не
     звал, они просто занимают память.
  2. ТЯЖЁЛЫЙ ГОЛОС -> ЛЁГКИЙ. Клон-голос (Qwen3, ~2 ГБ видеопамяти) —
     самый жирный кусок из «необязательных», но молчание за него платить
     не надо: Silero и Piper поют на процессоре. Голос станет чужим —
     зато он останется.
  3. ОЗВУЧКА СОВСЕМ. Без голоса она читается в чате и продолжает
     РАБОТАТЬ РУКАМИ; без слуха — нет.
  4. МОЗГИ (локальная LLM) — команды всё ещё исполняются: рефлексы работают
     без модели, а разговор может уйти в облако.
  5. ВСЁ — последняя мера, та самая жёсткая разгрузка. Сюда доходим,
     только если четыре предыдущие ступени не спасли.

ВОЗВРАТ. Когда железо спокойно дольше calm_s, ступени сдаются обратно по
одной, с паузой: сперва мозги (без них она глупеет), потом озвучка, потом
её собственный голос. Человеку сообщается сам факт, без причитаний.

ПОЧЕМУ С ГИСТЕРЕЗИСОМ. Порог, по которому гасят, и порог, по которому
возвращают, — разные. Иначе система дышит: выгрузила, VRAM упал, загрузила,
VRAM вырос, выгрузила… За такую «заботу» человек справедливо материт.
"""
import logging
import time

from anamorf.config import CFG

log = logging.getLogger("saika.triage")

ST = {"level": 0, "ts": 0.0, "calm_since": 0.0,
      "tts_was": "", "clone_was": "", "llm_was": ("", ""), "last_note": ""}

STEPS = {1: "лишние движки", 2: "лёгкий голос", 3: "озвучка",
         4: "мозги", 5: "всё"}
LAST = max(STEPS)

# Кто «тяжёлый»: тот, кто держит видеопамять. Список тот же, что в
# tts/manager.py (_HEAVY), продублирован намеренно — тянуть модуль голоса
# ради константы значит поднимать его при первом же замере сторожа.
_HEAVY_VOICES = ("qwen3", "omni", "xtts", "f5")
# Кто «лёгкий»: процессорные движки. Порядок = предпочтение.
_LIGHT_VOICES = ("silero", "piper", "edge")

# наружу: чем объявлять человеку (ставит main, чтобы не тащить сюда веб)
ANNOUNCE = {"fn": None}


def state() -> dict:
    return {"level": ST["level"], "step": STEPS.get(ST["level"], "всё живо"),
            "since": int(time.time() - ST["ts"]) if ST["level"] else 0}


def _say(text: str):
    log.info("%s", text)
    fn = ANNOUNCE.get("fn")
    if fn:
        try:
            fn(text)
        except Exception as e:
            log.debug("объявить не вышло: %s", e)


def _vram_frac(g: dict) -> float:
    tot = float(g.get("vram_total_mb") or 0)
    return (float(g.get("vram_mb") or 0) / tot) if tot else 0.0


# ─────────────────────────── ступени вниз ───────────────────────────
def _drop_extra() -> bool:
    from anamorf.llm import manager as mgr
    b, m = CFG.get("llm.backend", ""), CFG.get("llm.model", "")
    failed = mgr.unload_others(b, m)
    _say("Память на пределе — выгрузила лишние движки. Голос, слух и "
         "мозги работают." + (f" Не поддались: {failed}" if failed else ""))
    return True


def _light_voice() -> bool:
    """Клон-голос -> лёгкий движок на процессоре. Тише, но не молча.

    Владелец 19.08: «вырубать озвучку временно, но чтобы слух и мозги
    оставались живы». Оказалось, что и озвучку целиком рубить рано:
    видеопамять держит не «озвучка», а именно тяжёлый клон. Лёгкий движок
    её не занимает вовсе — значит, эта ступень освобождает почти столько
    же, а разговор остаётся голосовым.
    """
    from anamorf import tts
    cur = str(CFG.get("tts.engine", "") or "")
    if cur in ("", "off", "none"):
        log.info("Ступень «лёгкий голос» пропущена: голоса и так нет")
        return False
    heavy = [n for n in (getattr(tts, "engines", {}) or {})
             if any(h in n.lower() for h in _HEAVY_VOICES)]
    light = [n for n in _LIGHT_VOICES
             if n in (getattr(tts, "engines", {}) or {})]
    if cur not in heavy or not light:
        log.info("Ступень «лёгкий голос» пропущена: текущий голос «%s» "
                 "и так лёгкий либо замены нет", cur)
        return False
    ST["clone_was"] = cur
    for name in heavy:
        try:
            tts.unload_engine(name)
        except Exception as e:
            log.debug("тяжёлый голос %s не выгрузился: %s", name, e)
    try:
        CFG.set("tts.engine", light[0])
    except Exception as e:
        log.debug("лёгкий голос не встал: %s", e)
        return False
    _say(f"Памяти в обрез — сняла свой голос и говорю пока лёгким "
         f"({light[0]}). Слышу, думаю и работаю руками как обычно. "
         "Верну свой, когда станет полегче.")
    return True


def _drop_voice() -> bool:
    from anamorf import tts
    ST["tts_was"] = str(CFG.get("tts.engine", "") or "")
    # ГАСИТЬ НЕЧЕГО — НЕ СЧИТАЕМ ЭТО СТУПЕНЬЮ (2026-08-19, живой лог:
    # «выключила ОЗВУЧКУ (выгружено движков: 0)» — голос уже был выключен
    # прошлой разгрузкой, а ступень засчиталась и съела ход. Пустой шаг
    # только оттягивает настоящую помощь.)
    if not (getattr(tts, "engines", {}) or {}) and \
            str(CFG.get("tts.engine", "")) in ("", "off", "none"):
        log.info("Ступень «озвучка» пропущена: гасить нечего")
        return False
    n = 0
    for name in list(getattr(tts, "engines", {}) or {}):
        try:
            tts.unload_engine(name)
            n += 1
        except Exception as e:
            log.debug("голос %s не выгрузился: %s", name, e)
    try:
        # ЗАПИСКА, КТО ИМЕННО ВЫКЛЮЧИЛ ГОЛОС (2026-08-22). Ключ
        # `tts.engine` живёт в конфиге, то есть НА ДИСКЕ: выключив озвучку
        # под нехватку памяти, мы выключали её и на все будущие запуски.
        # Наутро автопуск читал «off», спокойно писал «озвучка выключена в
        # настройках — не гружу» и молчал, а человек видел живые движки в
        # панели и не понимал, почему ему не отвечают. Ровно та же ошибка,
        # что когда-то была с `tts.enabled`, и лечится как у слуха:
        # оставляем `engine_was`, и автопуск вернёт голос сам.
        if ST["tts_was"] and ST["tts_was"] not in ("", "off", "none"):
            CFG.set("tts.engine_was", ST["tts_was"])
        CFG.set("tts.engine", "off")
    except Exception as e:
        log.debug("движок голоса не переключился: %s", e)
    # НОЛЬ ВЫГРУЖЕННЫХ — НЕ ПОБЕДА (2026-08-22, живой лог: «временно
    # выключила ОЗВУЧКУ (выгружено движков: 0)» — то есть ступень
    # отчиталась о работе, не сделав ничего, и съела ход. Следующим шагом
    # лестница пошла снимать мозги, чего делать было не нужно.)
    if not n:
        log.info("Ступень «озвучка» пропущена: выгружать было нечего")
        return False
    _say("Железо на пределе — временно выключила ОЗВУЧКУ (выгружено "
         f"движков: {n}). Слышу и работаю руками как обычно, отвечаю "
         "текстом. Верну голос сама, когда станет полегче.")
    return True


def _drop_brains() -> bool:
    from anamorf.llm import manager as mgr

    # НЕ СНИМАТЬ ТО, ЧЕМ НЕЧЕМ ЗАМЕНИТЬ (2026-08-22, живой каскад: сторож
    # выгрузил локальные мозги «разговор — облаком, если оно есть», а
    # облака не было — ключ в сборку не приехал. Дальше посыпалось всё:
    # «Ни одна LLM не ответила», «не задан API-ключ», и человек остался с
    # интерфейсом, который бодро рапортует о разгрузке, и без единого
    # ответа.)
    #
    # Оговорка «если оно есть» и должна быть УСЛОВИЕМ, а не утешением в
    # тексте. Нет живого облака с ключом — эта ступень бессмысленна:
    # памяти она освободит немного, а разговор убьёт целиком.
    try:
        cloud_ok = bool(CFG.get("llm.cloud.enabled", False)) and \
            bool(mgr.cloud_key_for(str(CFG.get("llm.cloud.provider", ""))))
    except Exception:
        cloud_ok = False
    if not cloud_ok:
        log.info("Ступень «мозги» пропущена: облака с ключом нет, "
                 "снимать локальную модель — значит остаться без ответов")
        return False

    ST["llm_was"] = (str(CFG.get("llm.backend", "")),
                     str(CFG.get("llm.model", "")))
    try:
        mgr.unload_others("", "")          # пустая пара -> выгрузить все
    except Exception as e:
        log.debug("мозги не выгрузились: %s", e)
    _say("Железо всё ещё на пределе — выгрузила локальные МОЗГИ. Команды "
         "исполняю рефлексами, разговор — облаком, если оно есть. Верну "
         "модель сама, когда станет полегче.")
    return True


def _drop_all() -> bool:
    # запоминаем слух, чтобы вернуть именно его, а не «какой-нибудь»
    try:
        CFG.set("stt.engine_was", str(CFG.get("stt.engine", "") or ""))
    except Exception:
        pass
    try:
        from anamorf.main import _panic_body
        _panic_body()
    except Exception as e:
        log.warning("полная разгрузка не удалась: %s", e)
        return False
    return True


DOWN = {1: _drop_extra, 2: _light_voice, 3: _drop_voice,
        4: _drop_brains, 5: _drop_all}


# ─────────────────────────── ступени вверх ──────────────────────────
def _back_brains() -> bool:
    b, m = ST.get("llm_was") or ("", "")
    if not b or not m:
        return True
    try:
        from anamorf.llm import manager as mgr
        mgr.warmup(b, m)
        _say(f"Железо успокоилось — вернула мозги ({m}).")
    except Exception as e:
        log.debug("мозги не вернулись: %s", e)
        return False
    ST["llm_was"] = ("", "")
    return True


def _back_voice() -> bool:
    was = ST.get("tts_was") or ""
    if not was or was == "off":
        return True
    try:
        CFG.set("tts.engine", was)
        _say(f"Железо успокоилось — вернула голос ({was}).")
    except Exception as e:
        log.debug("голос не вернулся: %s", e)
        return False
    ST["tts_was"] = ""
    return True


def _back_hearing() -> bool:
    """Возврат с самой нижней ступени: жёсткая разгрузка глушит слух и
    узнавание голоса до ручного выбора — здесь мы их включаем сами, иначе
    «восстановилась» означало бы «молчит, но с памятью»."""
    try:
        from anamorf import voiceprint
        voiceprint.set_enabled(True)
    except Exception as e:
        log.debug("узнавание голоса не вернулось: %s", e)
    was = str(CFG.get("stt.engine_was", "") or "")
    try:
        from anamorf import stt
        if was and was != "none":
            stt.set_engine(was)
    except Exception as e:
        log.debug("слух не вернулся: %s", e)
    _say("Железо успокоилось — включаю слух обратно.")
    return True


def _back_clone() -> bool:
    """Вернуть СВОЙ голос — последним, когда всё остальное уже вернулось."""
    was = ST.get("clone_was") or ""
    if not was:
        return True
    try:
        CFG.set("tts.engine", was)
        _say(f"Железо успокоилось — вернула свой голос ({was}).")
    except Exception as e:
        log.debug("свой голос не вернулся: %s", e)
        return False
    ST["clone_was"] = ""
    return True


UP = {5: _back_hearing, 4: _back_brains, 3: _back_voice,
      2: _back_clone, 1: lambda: True}


# ─────────────────────────────── логика ─────────────────────────────
def tick(g: dict):
    """Зовётся сторожем железа на каждый замер."""
    if not CFG.get("guard.triage", True) or not g:
        return
    frac = _vram_frac(g)
    temp = float(g.get("temp") or 0)
    hot = temp >= float(CFG.get("guard.temp_warn", 78))
    crit_v = float(CFG.get("guard.vram_crit", 0.96))
    warn_v = float(CFG.get("guard.vram_warn", 0.90))
    calm_v = float(CFG.get("guard.vram_calm", 0.75))
    calm_t = float(CFG.get("guard.temp_calm", 70))
    calm_s = float(CFG.get("guard.calm_s", 45))
    step_s = float(CFG.get("guard.step_s", 12))

    now = time.time()
    if now - ST["ts"] < step_s:
        return                              # даём железу отдышаться

    if frac >= crit_v or temp >= float(CFG.get("guard.temp_crit", 85)):
        _down(now)
        return
    if (frac >= warn_v or hot) and ST["level"] < 2:
        # По предупреждению доходим только до «лёгкого голоса»: обе первые
        # ступени человек не замечает, а молчание — замечает.
        _down(now)
        return
    if frac <= calm_v and temp <= calm_t:
        if not ST["calm_since"]:
            ST["calm_since"] = now
        elif now - ST["calm_since"] >= calm_s and ST["level"] > 0:
            _up(now)
    else:
        ST["calm_since"] = 0.0


def _down(now: float):
    # ВЫБОР ЧЕЛОВЕКА — НЕ РАЗМЕННАЯ МОНЕТА (2026-08-23, живой разнос:
    # лестница дошла до «жёсткой разгрузки» и снесла ВСЁ выбранное — слух,
    # клон-голос, мозги. Владелец: «что я поставил, то и должно быть
    # выбрано»). Правило: свои степени свободы система тратит какие
    # угодно — лишние движки, подмена клона на лёгкий голос, — но ступени,
    # которые ВЫКЛЮЧАЮТ выбранное человеком (голос совсем, мозги, всё
    # разом), в автоматике запрещены. Не хватает памяти даже после
    # ступени 2 — это не повод молча раздеть систему, это повод честно
    # сказать: «выбранное вместе не влезает, реши сам». Кто осознанно
    # хочет старое поведение — guard.hard_ladder: true.
    cap = LAST if CFG.get("guard.hard_ladder", False) else 2
    if ST["level"] >= cap:
        if ST["level"] == 2 and not ST.get("said_full"):
            ST["said_full"] = True
            try:
                from anamorf import vramplan
                from anamorf.llm import llamacpp as _lc
                from pathlib import Path as _P
                mp = _lc.find_model()
                gb = _P(mp).stat().st_size / (1 << 30) if mp else 0
                note = vramplan.plan(gb)["note"] if gb else ""
            except Exception:
                note = ""
            _say("Память всё ещё на пределе, но выбранное тобой я не "
                 "трогаю — держу как есть. " + (f"Расклад: {note}. " if note
                 else "") + "Если начнёт падать — выбери сам: модель "
                 "полегче или лёгкий голос насовсем.")
        return
    if ST["level"] >= LAST:
        return
    ST["level"] += 1
    ST["ts"], ST["calm_since"] = now, 0.0
    fn = DOWN.get(ST["level"])
    if fn:
        try:
            if fn() is False and ST["level"] < LAST:
                # шаг оказался пустым — сразу пробуем следующий, иначе
                # железу придётся ждать ещё один круг сторожа
                ST["ts"] = now - float(CFG.get("guard.step_s", 12)) - 1
                _down(now)
        except Exception as e:
            log.warning("ступень %s не сработала: %s", ST["level"], e)


def _up(now: float):
    ST.pop("said_full", None)
    fn = UP.get(ST["level"])
    ST["ts"] = now
    ST["calm_since"] = now                  # следующая ступень — не раньше
    try:
        if fn:
            fn()
    except Exception as e:
        log.warning("возврат со ступени %s: %s", ST["level"], e)
    ST["level"] -= 1
    if ST["level"] <= 0:
        ST["level"] = 0
        _say("Всё вернулось на место: память свободна, работаю в полную силу.")
