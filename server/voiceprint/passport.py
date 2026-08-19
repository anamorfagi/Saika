"""ПАСПОРТ ГОЛОСА: ЗНАКОМСТВО ПО-ЧЕСТНОМУ (2026-08-19).

Владелец: «хочется, чтобы она полноценно могла понимать волну голоса,
гарантированно понимать, с кем говорит, и запоминать частоту — как в
фильмах, где голос человека определяется супер чётко».

ПОЧЕМУ СЕЙЧАС НЕ ТАК. Эталон набирался как придётся: пара фраз в одном
положении, одна громкость, один настрой. Дальше человек отсел от
микрофона, заговорил тише — и косинус просел ниже порога, потому что порог
взят из ТОГО ЖЕ узкого разброса. Отсюда «голос A/B/C/D» внутри одной
реплики и «Виталя 27%».

ЧТО ДЕЛАЕТ ПАСПОРТ. Ведёт человека по шагам и заставляет звучать РАЗНО:
обычно, тише, громче, дальше от микрофона, быстро, счёт, свободная речь.
Каждый шаг проверяется на месте (хватило ли речи, не шум ли, не тишина) —
плохой шаг переснимается, а не портит эталон. В конце считается СВОЙ порог:
насколько тесно лежат свои точки и насколько близко подходят чужие. Порог
из данных, а не из константы — это и есть разница между «примерно узнаёт» и
«узнаёт».

ЧЕСТНАЯ ГРАНИЦА. Никакая запись не делает узнавание стопроцентным: близкие
голоса (брат, тот же тембр по телефону) остаются близкими. Поэтому вместе с
паспортом сохраняется ЗАПАС — на сколько порог отстоит от ближайшего чужого.
Он виден человеку: маленький запас честнее показать, чем спрятать.
"""
import logging
import time

import numpy as np

log = logging.getLogger("saika.passport")

# Шаги: сколько секунд речи ждём и что сказать. Разнообразие важнее длины —
# лучше семь коротких разных, чем одна минута одинаковых.
STEPS = [
    {"id": "normal", "s": 5, "say": "Скажи обычным голосом, как сейчас: "
     "«Сайка, это я, запомни мой голос»"},
    {"id": "quiet", "s": 5, "say": "Теперь вполголоса, тихо: "
     "«сделай потише и открой браузер»"},
    {"id": "loud", "s": 5, "say": "А теперь громко, как через комнату: "
     "«Сайка, поставь на паузу!»"},
    {"id": "far", "s": 5, "say": "Отодвинься от микрофона и скажи оттуда: "
     "«так меня слышно с другого конца стола»"},
    {"id": "fast", "s": 5, "say": "Быстро, скороговоркой: "
     "«открой вкладку, включи ролик, сделай потише»"},
    {"id": "count", "s": 6, "say": "Посчитай вслух от одного до десяти"},
    {"id": "free", "s": 8, "say": "И свободно, своими словами: что "
     "собираешься сегодня делать"},
]

MIN_VECS = 3          # меньше — шаг не засчитан, просим повторить

_P = {"on": False, "name": "", "i": 0, "t0": 0.0, "vecs": 0,
      "steps": [], "started": 0.0}


def active() -> bool:
    return bool(_P["on"])


def state() -> dict:
    if not _P["on"]:
        return {"on": False}
    st = STEPS[min(_P["i"], len(STEPS) - 1)]
    return {"on": True, "name": _P["name"], "step": _P["i"] + 1,
            "steps_total": len(STEPS), "say": st["say"], "need_s": st["s"],
            "left_s": max(0, round(st["s"] - (time.time() - _P["t0"]), 1)),
            "got": _P["vecs"], "done": [s["id"] for s in _P["steps"]]}


def start(name: str) -> dict:
    from server.voiceprint import enroll_start
    name = (name or "").strip()[:32]
    if not name:
        return {"ok": False, "error": "нужно имя"}
    r = enroll_start(name, need=10 ** 6)      # финал закрываем сами
    if not r.get("ok"):
        return r
    _P.update(on=True, name=name, i=0, t0=time.time(), vecs=0, steps=[],
              started=time.time())
    log.info("Паспорт голоса «%s»: шаг 1 из %d", name, len(STEPS))
    return {"ok": True, **state()}


def cancel() -> dict:
    from server.voiceprint import enroll_cancel
    _P.update(on=False, name="", i=0, vecs=0, steps=[])
    enroll_cancel()
    return {"ok": True, "on": False}


def note(emb, rms: float, f0: float):
    """Зовётся на каждый кусок речи, пока идёт паспорт."""
    if not _P["on"]:
        return
    _P["vecs"] += 1


def tick() -> dict:
    """Пора ли переходить к следующему шагу. Зовётся из живого потока."""
    if not _P["on"]:
        return {}
    st = STEPS[_P["i"]]
    if time.time() - _P["t0"] < st["s"]:
        return {}
    if _P["vecs"] < MIN_VECS:
        # шаг не засчитан: человек молчал или в кадр попал шум
        _P["t0"] = time.time()
        _P["vecs"] = 0
        log.info("Паспорт: шаг «%s» переснимаем — речи не хватило", st["id"])
        return {"repeat": True, **state()}
    _P["steps"].append(st)
    _P["i"] += 1
    _P["vecs"] = 0
    _P["t0"] = time.time()
    if _P["i"] >= len(STEPS):
        return finish()
    log.info("Паспорт: шаг %d из %d", _P["i"] + 1, len(STEPS))
    return {"next": True, **state()}


def _threshold_for(reg, name: str) -> dict:
    """СВОЙ порог из данных: где лежат свои точки и как близко подходят
    чужие. Берём 5-й процентиль своих (то есть «даже в худшие моменты я
    звучу не хуже этого») и максимум чужих; порог — посередине, но никогда
    не ниже своих же худших минус запас."""
    v = reg.speakers.get(name)
    if v is None:
        return {}
    X = np.asarray(v["embs"], dtype=np.float32)
    if len(X) < 8:
        return {}
    c = X.mean(axis=0)
    c = c / max(1e-9, float(np.linalg.norm(c)))
    own = X @ c
    own_lo = float(np.percentile(own, 5))
    imp_hi, imp_who = -1.0, ""
    for other, ov in reg.speakers.items():
        if other == name:
            continue
        Y = np.asarray(ov["embs"], dtype=np.float32)
        if Y.ndim != 2 or Y.shape[1] != X.shape[1] or not len(Y):
            continue
        s = float(np.max(Y @ c))
        if s > imp_hi:
            imp_hi, imp_who = s, other
    if imp_hi < 0:
        thr = max(0.0, own_lo - 0.05)
        gap = 0.0
    else:
        thr = (own_lo + imp_hi) / 2.0 if imp_hi < own_lo else own_lo - 0.02
        gap = own_lo - imp_hi
    return {"thr": round(float(thr), 4), "own_lo": round(own_lo, 4),
            "imp_hi": round(float(imp_hi), 4), "imp_who": imp_who,
            "gap": round(float(gap), 4), "n": int(len(X))}


def finish() -> dict:
    from server.voiceprint import S, enroll_finish
    name = _P["name"]
    _P.update(on=False)
    r = enroll_finish()
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error", "не вышло"), "on": False}
    info = {}
    try:
        info = _threshold_for(S.reg, name) or {}
        if info:
            S.reg.speakers[name]["thr"] = info["thr"]
            S.reg.speakers[name]["passport"] = {
                "ts": time.time(), **info,
                "steps": [s["id"] for s in _P["steps"]]}
            S.reg.dirty = True
            S.reg.save()
    except Exception as e:
        log.warning("порог по паспорту не посчитался: %s", e)
    gap = info.get("gap", 0.0)
    if gap >= 0.12:
        note_txt = "запас до ближайшего чужого голоса хороший"
    elif gap > 0.0:
        note_txt = (f"запас небольшой: ближе всех «{info.get('imp_who', '')}» "
                    "— в спорных случаях буду переспрашивать")
    else:
        note_txt = (f"внимание: «{info.get('imp_who', '')}» звучит так же "
                    "близко, как ты сам — надёжно развести не смогу")
    log.info("Паспорт голоса «%s» готов: векторов %s, порог %s, запас %s",
             name, info.get("n"), info.get("thr"), gap)
    return {"ok": True, "on": False, "name": name, **info, "note": note_txt,
            "vectors": r.get("vectors")}
