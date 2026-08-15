"""НЕЙРОННЫЙ ДЕТЕКТОР РЕЧИ — Silero VAD (2026-08-15).

ЗАЧЕМ, дословно от владельца: «нужно сделать полноценный апгрейд слуха,
чтобы не писать ахинею… чтобы гарантированно получала из звуков даже "п",
"ссс" транскриб». Разбор дня показал: движки (GigaAM, whisper) получали
КАШУ, потому что фразы им резал энергетический VAD — порог по громкости.
Для порога по громкости щелчок клавиши, хлопок двери и слог «п» — одно и
то же: громко. Отсюда и фантомное «Да.» на печатание, и съеденные тихие
начала слов, и куски щелчков, на которых GigaAM честно галлюцинирует.

Так это решают большие: перед распознавателем стоит нейронный детектор
речи. Silero VAD — фактический стандарт индустрии: 1.2 МБ, ~300 тысяч
параметров, миллисекунда на кусок НА ПРОЦЕССОРЕ, обучен на тысячах часов
в сотне языков. Он отвечает не «громко ли», а «похоже ли на человеческую
речь» — и именно этот ответ должен решать, где начинается и кончается
фраза, и стоит ли считать отпечаток голоса.

КАК ВСТРОЕН — ПО ПРАВИЛУ «НОВОЕ РЯДОМ» (CLAUDE.md). Энергетический VAD
остаётся на месте целиком: он держит нарезку, предролл, гистерезис и
пределы длины. Нейронка подменяет в нём ровно ОДНО решение — «этот кусок
звука голос или нет». Не загрузилась (нет сети до github, битый кэш) —
решение молча возвращается к громкости, слух не теряется ни на секунду.

МЕХАНИКА. Модель ест куски ровно по 512 сэмплов при 16 кГц и держит
внутреннее состояние (это стриминговая RNN). Браузер шлёт по 1600 —
копим хвост между вызовами и скармливаем по 512, наружу отдаём максимум
вероятности за кусок: для решения «есть ли речь в этих 100мс» максимум
честнее среднего — слог может занять треть куска.
"""
import logging
import threading
import time

import numpy as np

from server.config import CFG

log = logging.getLogger("saika.vad")

SR = 16000
WIN = 512                    # кадр silero-vad при 16 кГц (жёстко из модели)

STATE = {"ready": False, "off": False, "why": "", "prob": 0.0, "ts": 0.0}

_model = None
_lock = threading.Lock()
_tail = np.zeros(0, dtype=np.float32)
_load_started = False
_last_try = 0.0


def enabled() -> bool:
    return str(CFG.get("stt.vad.engine", "silero")) == "silero" \
        and not STATE["off"]


def _load():
    """Загрузка в фоне. Первый torch.hub.load может качать с github —
    сетевая загрузка не имеет права стоять на пути звука (урок silero_te,
    2026-07-28: точно такая же загрузка повесила распознавание на 2.5
    минуты). Пока модель не готова, VAD живёт на громкости."""
    global _model
    try:
        # под общим замком: параллельное ленивое поднятие двух торчёвых
        # моделей роняет вторую (server/torch_gate.py)
        from server.torch_gate import TORCH_GATE
        with TORCH_GATE:
            import torch
            torch.set_num_threads(1)
            # ДВА ПУТИ ЗАГРУЗКИ, надёжный первым (проверено стендом
            # 2026-08-15): pip-пакет silero-vad несёт веса В СЕБЕ и не
            # ходит в сеть вообще (ставится ensure_features при следующем
            # start.bat). Нет пакета — torch.hub с github, как silero_te.
            model = None
            # ONNX ПЕРВЫМ (2026-08-15, живая панель владельца: «нарезка
            # 41.03 мс» на 100мс куска — торчёвый jit под нагрузкой (рядом
            # молотит шумодав и GigaAM) ел почти половину бюджета реального
            # времени, и очередь слуха доросла до 23. ONNX-рантайм гоняет
            # ту же модель за доли миллисекунды на кадр.)
            try:
                from silero_vad import load_silero_vad
                try:
                    model = load_silero_vad(onnx=True)
                    log.info("Нейро-VAD: модель из pip-пакета, ONNX — "
                             "самый быстрый путь")
                except Exception:
                    model = load_silero_vad(onnx=False)
                    log.info("Нейро-VAD: модель из pip-пакета silero-vad "
                             "(torch; поставь onnxruntime — будет быстрее)")
            except ImportError:
                pass
            if model is None:
                model, _utils = torch.hub.load(
                    repo_or_dir="snakers4/silero-vad", model="silero_vad",
                    trust_repo=True, onnx=False)
        model.reset_states()
        # проверка живой секундой тишины: модель обязана ответить числом
        probe = model(torch.zeros(1, WIN), SR).item()
        if not (0.0 <= probe <= 1.0):
            raise RuntimeError(f"странный ответ на пробнике: {probe}")
        _model = model
        STATE["ready"] = True
        log.info("Нейро-VAD: silero-vad поднят (CPU, кадр %dмс) — речь "
                 "теперь отличается от щелчков нейронкой, а не громкостью",
                 round(WIN * 1000 / SR))
    except Exception as e:
        STATE["why"] = str(e)[:160]
        log.warning("Нейро-VAD не поднялся (%s) — нарезка живёт на "
                    "громкости, попробую ещё раз через 10 минут", STATE["why"])


def warm():
    """Пнуть фоновую загрузку. Зовётся из конвейера — дёшево и не ждёт."""
    global _load_started, _last_try
    if STATE["ready"] or STATE["off"]:
        return
    now = time.time()
    if _load_started and now - _last_try < 600:
        return
    _load_started, _last_try = True, now
    threading.Thread(target=_load, daemon=True, name="silero-vad").start()


def prob(pcm16: np.ndarray):
    """Вероятность речи в куске (0..1) или None, если нейронка не готова.

    Кусок любой длины: остаток короче кадра копится до следующего вызова,
    поэтому границы кусков браузера на ответ не влияют."""
    global _tail
    if not enabled():
        return None
    if not STATE["ready"]:
        warm()
        return None
    try:
        import torch
        x = np.asarray(pcm16, dtype=np.float32).ravel() / 32768.0
        with _lock:
            buf = np.concatenate([_tail, x])
            best = 0.0
            n = 0
            while len(buf) >= WIN:
                frame, buf = buf[:WIN], buf[WIN:]
                p = float(_model(torch.from_numpy(frame).unsqueeze(0),
                                 SR).item())
                best = max(best, p)
                n += 1
            _tail = buf
        if n == 0:
            # кадр ещё не набрался — отдаём прошлое значение, оно свежее
            # 100мс и для гистерезиса этого достаточно
            return STATE["prob"] if time.time() - STATE["ts"] < 0.5 else None
        STATE["prob"], STATE["ts"] = best, time.time()
        return best
    except Exception as e:
        # одна ошибка — не приговор, но третья подряд значит «модель
        # больна»: выключаемся до перезапуска, слух едет на громкости
        STATE["fails"] = STATE.get("fails", 0) + 1
        if STATE["fails"] >= 3:
            STATE["off"] = True
            log.warning("Нейро-VAD: три ошибки подряд (%s) — выключаюсь, "
                        "нарезка на громкости", str(e)[:120])
        return None


def reset():
    """Конец фразы: сбросить состояние рекуррентной модели, чтобы хвост
    прошлой фразы не тянулся в решение по следующей."""
    global _tail
    try:
        with _lock:
            _tail = np.zeros(0, dtype=np.float32)
            if _model is not None:
                _model.reset_states()
    except Exception:
        pass


def status() -> dict:
    return {"engine": "silero" if enabled() else "energy",
            "ready": STATE["ready"], "off": STATE["off"],
            "why": STATE["why"], "prob": round(STATE["prob"], 3)}
