"""СМОТРИТЕЛЬ ЗАКАЗА: выбранное человеком загружено ВСЕГДА (2026-08-23).

Владелец: «делай так, чтобы все эти модели загружались гарантированно и
не отваливались».

До этого выбранные компоненты поднимались по случаю: мозг — когда
приходила реплика, голос — когда было что сказать, слух — при старте. А
падали они по расписанию чужих проблем: сторож памяти, краш сервера,
чья-то выгрузка. Восстановление везде было СВОЁ и по своему поводу.

Смотритель — одно место с одним правилом: раз в полминуты сверить, что
РЕАЛЬНО живо, с тем, что ЧЕЛОВЕК ВЫБРАЛ, и молча поднять упавшее. Порядок
фиксированный — мозг, слух, голос: без мозга она немая, без слуха глухая,
голос страдает последним и чинится первым, когда остальное живо.

Чего смотритель НЕ делает:
  * не спорит со сторожем железа: если тот сейчас тушит пожар (уровень
    лестницы поднят и память в красной зоне) — ждём, пожар главнее;
  * не дёргает ничего посреди разговора: перезапуск мозга обрезал бы
    реплику на полуслове;
  * не долбит сломанное: у каждого компонента свой откат — не поднялось,
    следующая попытка через всё большую паузу (до 10 минут), и о
    повторном провале говорится один раз, а не каждые полминуты.
"""
import logging
import re
import threading
import time

from anamorf.config import CFG

log = logging.getLogger("saika.keeper")

_ST = {"on": False, "next": {}, "fail": {}, "said": {}}
_TICK_S = 25
_BACKOFF0 = 60


def _norm(x):
    return re.sub(r"[^a-z0-9]+", "", str(x or "").lower())


def _cooled(key: str) -> bool:
    return time.time() >= _ST["next"].get(key, 0)


def _failed(key: str, why: str):
    n = _ST["fail"].get(key, 0) + 1
    _ST["fail"][key] = n
    wait = min(_BACKOFF0 * (2 ** (n - 1)), 600)
    _ST["next"][key] = time.time() + wait
    log.warning("Смотритель: %s не поднялся (%s) — попытка %d, следующая "
                "через %dс", key, why[:120], n, wait)


def _ok(key: str):
    _ST["fail"].pop(key, None)
    _ST["next"].pop(key, None)


def _fire_ok():
    """Можно ли сейчас что-то поднимать."""
    try:
        from anamorf import triage
        st = triage.state() or {}
        if int(st.get("level", 0)) >= 2:
            return False                     # сторож тушит пожар — ждём
    except Exception:
        pass
    try:
        from anamorf import main as _m
        if _m._talk_busy():
            return False                     # идёт разговор — не режем
    except Exception:
        pass
    return True


def _check_brain():
    if str(CFG.get("llm.backend", "")) != "llamacpp":
        return
    want = str(CFG.get("llm.model", "") or "")
    if not want or CFG.get("llm.off", False):
        return
    try:
        from anamorf.llm import llamacpp as lc
        import requests
        r = requests.get(lc.base_url() + "/v1/models", timeout=1.5)
        served = ""
        if r.ok:
            data = (r.json() or {}).get("data") or []
            if data:
                from pathlib import Path
                served = Path(str(data[0].get("id") or "")).stem
        alive = bool(served) and (_norm(served) in _norm(want)
                                  or _norm(want) in _norm(served))
    except Exception:
        alive = False
    if alive:
        _ok("brain")
        return
    if not _cooled("brain"):
        return
    log.warning("Смотритель: мозг «%s» не на порту — поднимаю", want)
    try:
        from anamorf.llm import manager as mgr
        if mgr.switch_model("llamacpp", want).get("ok"):
            _ok("brain")
            log.info("Смотритель: мозг «%s» снова в строю", want)
        else:
            _failed("brain", "прогрев не удался")
    except Exception as e:
        _failed("brain", str(e))


def _stt_mgr():
    """anamorf.stt — ПАКЕТ (папка с manager.py, engines.py...), а движками
    владеет ЖИВОЙ экземпляр STTManager из главного модуля (main.py:736).
    Смотритель стучался в пакет и получал «module 'anamorf.stt' has no
    attribute 'set_engine'» — 15 попыток подряд, слух всё это время лежал,
    а вместе с ним молчали и транскриб, и дорожки голосов. Для TTS этот же
    случай уже разобран ниже — здесь тот же приём (27.08.2026)."""
    import sys as _s
    for nm in ("__main__", "anamorf.main"):
        m = _s.modules.get(nm)
        t = getattr(m, "stt", None) if m else None
        if t is not None and hasattr(t, "set_engine"):
            return t
    return None


def _check_stt():
    want = str(CFG.get("stt.engine", "") or "")
    if want in ("", "none", "off"):
        return                               # выключено человеком — закон
    stt = _stt_mgr()
    if stt is None:
        return                               # main ещё не поднялся
    try:
        cur = str(getattr(stt, "current_name", "") or "")
        healthy = stt.health.get(want) != "broken" \
            if hasattr(stt, "health") else True
        if cur == want and healthy:
            _ok("stt")
            return
    except Exception:
        pass
    if not _cooled("stt"):
        return
    log.warning("Смотритель: слух «%s» не активен — поднимаю", want)
    try:
        stt.set_engine(want)
        _ok("stt")
        log.info("Смотритель: слух «%s» снова в строю", want)
    except Exception as e:
        _failed("stt", str(e))


def _check_tts():
    want = str(CFG.get("tts.engine", "") or "")
    if want in ("", "none", "off") or not CFG.get("tts.enabled", True):
        return
    try:
        from anamorf import triage
        if (triage.ST or {}).get("clone_was"):
            return          # сторож сам подменил голос и сам вернёт
    except Exception:
        pass
    # anamorf.tts — ПАКЕТ, а движками владеет ЖИВОЙ экземпляр TTSManager
    # в главном модуле (поймано 15:05:18: «module anamorf.tts has no
    # attribute set_engine» — смотритель стучался в пакет, а не в него)
    def _mgr():
        import sys as _s
        for nm in ("__main__", "anamorf.main"):
            m = _s.modules.get(nm)
            t = getattr(m, "tts", None) if m else None
            if t is not None and hasattr(t, "set_engine"):
                return t
        return None
    tts = _mgr()
    if tts is None:
        return                                # main ещё не поднялся
    try:
        eng = (getattr(tts, "engines", {}) or {}).get(want)
        broken = (getattr(tts, "health", {}) or {}).get(want) == "broken"
        if eng is not None and not broken:
            _ok("tts")
            return
    except Exception:
        pass
    if not _cooled("tts"):
        return
    log.warning("Смотритель: голос «%s» сломан или отсутствует — чиню", want)
    try:
        try:
            getattr(tts, "health", {}).pop(want, None)   # снять клеймо
        except Exception:
            pass
        tts.set_engine(want)
        _ok("tts")
        log.info("Смотритель: голос «%s» снова в строю", want)
    except Exception as e:
        _failed("tts", str(e))


def _loop():
    log.info("Смотритель заказа запущен: слежу, чтобы выбранное было "
             "загружено (мозг -> слух -> голос, шаг %dс)", _TICK_S)
    while True:
        time.sleep(_TICK_S)
        try:
            if not CFG.get("keeper.enabled", True):
                continue
            if not _fire_ok():
                continue
            _check_brain()
            _check_stt()
            _check_tts()
        except Exception as e:
            log.debug("смотритель споткнулся: %s", e)


def start():
    """Идемпотентный запуск. Зовётся из /api/ready — та ручка, которую
    интерфейс дёргает постоянно: где бы ни умер прежний поток, первый же
    опрос поднимет нового."""
    if _ST["on"]:
        return
    _ST["on"] = True
    threading.Thread(target=_loop, daemon=True, name="keeper").start()
