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

from server.config import CFG, ROOT

log = logging.getLogger("saika.knobs")

PATH = ROOT / "data" / "knobs.json"
ACK = ROOT / "data" / "knobs_ack.json"

# Белый список: что напарнику можно крутить. Всё — настройки слуха и
# звука; ни файлов, ни системы, ни сети отсюда не достать.
_ALLOWED_PREFIX = (
    "stt.", "denoise.", "hearing.", "beatbox.", "voiceprint.vad_min",
    "dialog.live_context", "transcript.",
)
# отдельные точечные ключи вне префиксов
_ALLOWED_EXACT = ("tts.headphones",)


def _allowed(key: str) -> bool:
    return key in _ALLOWED_EXACT or any(
        key.startswith(p) for p in _ALLOWED_PREFIX)


def _apply(data: dict) -> dict:
    from server.main import stt  # менеджер слуха: живые ручки VAD
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
                from server.denoise import DENOISE
                DENOISE.set_engine(str(v))
            if k == "stt.engine":
                stt.set_engine(str(v))
            applied[k] = v
        except Exception as e:
            skipped[k] = str(e)[:80]
    return {"ok": True, "applied": applied, "skipped": skipped,
            "at": time.strftime("%H:%M:%S")}


def _loop():
    last = 0.0
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


def start():
    threading.Thread(target=_loop, daemon=True, name="knobs").start()
    log.info("Пульт включён: слежу за %s (белый список: %s)",
             PATH, ", ".join(_ALLOWED_PREFIX))
