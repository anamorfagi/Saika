"""ФАЙЛОВЫЙ ПУЛЬТ — ручки слуха, доступные снаружи без HTTP (2026-08-15).

ЗАЧЕМ. Владелец позвал ИИ-напарника крутить настройки ВМЕСТЕ с ним, в
живой сессии: «попробуй манипулировать крутилками и движками, начнём
тестировать вместе». У напарника (Cowork) нет хода в порт 8765 — песочница
не видит localhost машины, — зато папка проекта примонтирована ему на
запись. Значит канал управления — ФАЙЛ: напарник пишет data/knobs.json,
Сайка замечает изменение и применяет; ответ уезжает в data/knobs_ack.json,
а результаты опыта напарник читает из logs/ и data/hear_bench/.

БЕЗОПАСНОСТЬ ПО УСТРОЙСТВУ, а не по обещанию:
  - применяются ТОЛЬКО ключи из белого списка ниже — никакого exec, никаких
    произвольных путей; файл с чужими ключами честно отражается в ack как
    «пропущено»;
  - пульт можно выключить насовсем: knobs.enabled = false в config.json;
  - каждое применение — строкой в лог: владелец видит, кто что крутил.

Формат data/knobs.json:
    {"stt.vad.silence_ms": 450, "denoise.engine": "off", "stt.bench": true}
Просто словарь ключ-значение. Применяется один раз на каждое изменение
файла (по mtime); повторить то же — тронь файл заново.
"""
import json
import logging
import threading
import time

from anamorf.config import CFG, ROOT, DATA_ROOT

log = logging.getLogger("saika.knobs")

PATH = DATA_ROOT / "data" / "knobs.json"
ACK = DATA_ROOT / "data" / "knobs_ack.json"

# Белый список: что напарнику можно крутить. Всё — настройки слуха и
# звука; ни файлов, ни системы, ни сети отсюда не достать.
_ALLOWED_PREFIX = (
    "stt.", "denoise.", "hearing.", "beatbox.", "voiceprint.",
    "dialog.live_context", "transcript.",
)
# отдельные точечные ключи вне префиксов
# tts.engine / llm.off — режим стенда слуха (06.09.2026): пульт с «off»
# лежал молча «не в белом списке», а озвучка каждый перезапуск 105 с
# компилировалась на той же карте, где в это время шёл слух (3-6 с/фразу)
_ALLOWED_EXACT = ("tts.headphones", "tts.engine", "llm.off")


def _allowed(key: str) -> bool:
    return key in _ALLOWED_EXACT or any(
        key.startswith(p) for p in _ALLOWED_PREFIX)


def _apply(data: dict) -> dict:
    from anamorf.main import stt  # менеджер слуха: живые ручки VAD
    applied, skipped = {}, {}
    for k, v in data.items():
        if not isinstance(k, str) or not _allowed(k):
            skipped[k] = "не в белом списке"
            continue
        try:
            CFG.set(k, v)
            # живые ручки нарезки применяем сразу, не дожидаясь новой фразы
            if k.startswith("stt.vad."):
                attr = k.split(".")[-1]
                attr = "threshold" if attr == "rms_threshold" else attr
                if hasattr(stt.vad, attr):
                    setattr(stt.vad, attr, v)
            if k == "denoise.engine":
                from anamorf.denoise import DENOISE
                DENOISE.set_engine(str(v))
            if k == "stt.engine":
                stt.set_engine(str(v))
            # ═══ ГДЕ СЧИТАТЬ ОТПЕЧАТОК ГОЛОСА (2026-08-31) ═══
            # Замер по стадиям показал: разрез фразы по говорящим стоит
            # 2469мс против 828мс у самого распознавания. Причина не в
            # алгоритме — ECAPA считалась на ПРОЦЕССОРЕ
            # (voiceprint.device="cpu"), а turns.split кодирует по окну
            # на каждые 1.2 секунды. Модель весит ~20 МБ, на видеокарте
            # места не занимает.
            #
            # Смена этой ручки требует ПЕРЕСБОРКИ уже поднятого
            # кодировщика: сам по себе CFG.set не двигает модель между
            # устройствами. Собираем на месте — объект тот же, все
            # ссылки на него живые, ни одна фраза не теряется.
            if k in ("voiceprint.device", "voiceprint.encoder"):
                from anamorf import voiceprint as _vp
                _enc = getattr(_vp.S, "enc", None)
                if _enc is not None:
                    _enc._tried = False
                    _enc._retried = False
                    _enc._sb = None
                    _enc.backend, _enc.dim = "light", 68
                    _enc.warmup()
                    log.warning("Пульт: отпечаток голоса пересобран (%s=%s) "
                                "-> backend=%s dim=%s", k, v,
                                _enc.backend, _enc.dim)
            applied[k] = v
        except Exception as e:
            skipped[k] = str(e)[:80]
    return {"ok": True, "applied": applied, "skipped": skipped,
            "at": time.strftime("%H:%M:%S")}


STAMP = PATH.parent / "knobs_applied.json"


def _stamp_read():
    """Время пульта, который уже применяли. Нужно, чтобы старый слепок не воскресал."""
    try:
        return float(json.loads(STAMP.read_text("utf-8")).get("mtime", 0.0))
    except Exception:
        return 0.0


def _stamp_write(mt):
    try:
        STAMP.write_text(json.dumps({"mtime": mt, "at": time.strftime("%Y-%m-%d %H:%M:%S")},
                                    ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _loop():
    # 2026-09-18: было last = 0.0, поэтому наблюдатель применял пульт сразу после
    # старта, даже если файл не менялся неделями, и затирал выбор владельца.
    last = _stamp_read()
    while True:
        time.sleep(2.0)
        try:
            if not CFG.get("knobs.enabled", True):
                continue
            if not PATH.exists():
                continue
            mt = PATH.stat().st_mtime
            if mt <= last:
                continue
            last = mt
            _stamp_write(mt)
            data = json.loads(PATH.read_text("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("ожидаю словарь ключ-значение")
            res = _apply(data)
            log.info("Пульт: применено %s%s", res["applied"],
                     f", пропущено {res['skipped']}" if res["skipped"] else "")
            ACK.write_text(json.dumps(res, ensure_ascii=False, indent=1),
                           encoding="utf-8")
        except Exception as e:
            try:
                ACK.write_text(json.dumps(
                    {"ok": False, "error": str(e)[:200],
                     "at": time.strftime("%H:%M:%S")},
                    ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            log.warning("Пульт: файл не применился (%s)", e)


def apply_now() -> dict:
    """Применить пульт СЕЙЧАС, синхронно — до автопуска тяжёлых моделей.
    Живой случай 06.09.2026: «tts.engine: off» в пульте применялся через
    полторы минуты после старта, когда Qwen3-TTS уже 105 с компилировался
    на той же карте, и слух в это время шёл по 3-6 с на фразу."""
    try:
        if not PATH.exists():
            return {}
        mt = PATH.stat().st_mtime
        # 2026-09-18. Раньше этот проход был безусловным, и слепок пульта от
        # 06.09 при КАЖДОМ запуске перезаписывал конфиг: слух насильно в gigaam,
        # озвучка в off. Владелец выключал их перед выходом и находил включёнными.
        # Пульт — это «нажали кнопку», а не «состояние системы»: применяем только
        # то, что появилось после прошлого применения.
        if mt <= _stamp_read():
            log.info("Пульт: файл не менялся с прошлого применения (%s) — "
                     "настройки владельца не трогаю",
                     time.strftime("%d.%m %H:%M", time.localtime(mt)))
            return {}
        data = json.loads(PATH.read_text("utf-8"))
        if not isinstance(data, dict):
            return {}
        res = _apply(data)
        _stamp_write(mt)
        log.info("Пульт: применён до автопуска (%d ключей)",
                 len(res.get("applied") or {}))
        return res
    except Exception as e:
        log.warning("Пульт: ранний проход не удался (%s)", e)
        return {}


def start():
    threading.Thread(target=_loop, daemon=True, name="knobs").start()
    log.info("Пульт включён: слежу за %s (белый список: %s)",
             PATH, ", ".join(_ALLOWED_PREFIX))
