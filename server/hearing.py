"""УХО: что именно звучит вокруг — метки звуков, а не слова.

2026-08-13, живой отказ владельца: «клацанье клавиатуры система всё так же
записывает в голос». И правда — в карте голосов завёлся «Голос 4»: 153
срабатывания, 103-400 Гц. Это не человек, это клавиатура получила профиль.

ДВЕ РАЗНЫЕ ЗАДАЧИ, которые до сих пор путались:
  1. ЧЕЙ голос — этим занят voiceprint (эмбеддинги ECAPA);
  2. ЗВУК ЛИ ЭТО ВООБЩЕ ГОЛОС — а этим не занимался никто. Отпечаток
     честно считался от чего угодно: щелчка, стука, музыки. Отсюда и
     фантомные «голоса» в карте.

Здесь второе. Классификатор AudioSet отвечает на вопрос «что звучит»
(527 классов: речь, клавиатура, музыка, лай, посуда). Из его ответа берём:
  - ПРЕДОХРАНИТЕЛЬ: нет речи в кадре — voiceprint не трогаем;
  - КОНТЕКСТ: метки того, что слышно, уходят в промпт как ФОН, который
    Сайка МОЖЕТ использовать в разговоре. Не как запрос и не как команда:
    «слышу клавиатуру» — это не «прокомментируй клавиатуру».

ПОЧЕМУ PANNs, А НЕ YAMNet (отступление от плана в HEARING.md). YAMNet тянет
TensorFlow — второй фреймворк глубокого обучения в венв, где уже стоит
torch. Этот венв и так хрупкий (см. FORBIDDEN_PKG в setup/ai_doctor.py:
одна переустановка torch чуть не снесла CUDA всему проекту). panns_inference
работает на уже установленном torch и добавляет только веса.

ПОЧЕМУ ПО УМОЛЧАНИЮ CPU. Видеопамять — самый дефицитный ресурс машины
(13 из 16 ГБ заняты, клон-голосу не хватает), а процессор простаивает на
20%. CNN14 на пару секунд звука — десятки миллисекунд на CPU, и раз в
секунду это незаметно. Ключ hearing.device, если захочется на видеокарту.

ЗВУК НЕ ХРАНИМ — как и в earlog. Только метки.
"""
import logging
import threading
import time

import numpy as np

from server.config import CFG

log = logging.getLogger("saika.ears")

SR_IN = 16000          # микрофон
SR_MODEL = 32000       # PANNs обучены на 32 кГц
WINDOW_S = 2.0         # окно классификации
EVERY_S = 1.0          # как часто прогонять

STATE = {
    "ready": False,        # модель загружена
    "off": False,          # выключено или не установлено — работаем без ушей
    "tags": [],            # [(имя, вероятность)] последнего окна
    "speech": 0.0,         # уверенность, что в кадре РЕЧЬ
    "ts": 0.0,             # когда посчитано
}

_buf = np.zeros(0, dtype=np.float32)
_lock = threading.Lock()
_worker = None
_model = None
_labels: list = []

# классы AudioSet, означающие «это голос человека». Пение сюда НЕ входит
# осознанно: подпевающий телевизор не должен заводить профиль в карте.
_SPEECH = ("speech", "conversation", "narration", "monologue",
           "male speech", "female speech", "child speech", "babbling",
           "speech synthesizer")

# по-русски — только то, что реально бывает у компьютера. Остальное
# отдаём английской меткой: честнее, чем выдумывать перевод.
_RU = {
    "computer keyboard": "клавиатура", "typing": "печатает",
    "keyboard (musical)": "синтезатор", "mouse": "мышь",
    "mouse click": "щелчок мыши", "click": "щелчок",
    "music": "музыка", "singing": "пение", "musical instrument": "инструмент",
    "speech": "речь", "conversation": "разговор", "laughter": "смех",
    "cough": "кашель", "sneeze": "чих", "breathing": "дыхание",
    "sigh": "вздох", "whistling": "свист", "humming": "мычит мотив",
    "dog": "собака", "bark": "лай", "cat": "кошка", "meow": "мяу",
    "bird": "птица", "vehicle": "машина", "car": "машина",
    "siren": "сирена", "door": "дверь", "knock": "стук",
    "telephone": "телефон", "telephone bell ringing": "звонок телефона",
    "alarm": "будильник", "water": "вода", "dishes, pots, and pans": "посуда",
    "cutlery, silverware": "посуда", "chewing, mastication": "жуёт",
    "drinking, sipping": "пьёт", "television": "телевизор",
    "radio": "радио", "fan": "вентилятор", "air conditioning": "кондиционер",
    "printer": "принтер", "silence": "тишина", "white noise": "шум",
    "static": "шум", "wind": "ветер", "rain": "дождь", "thunder": "гром",
    "applause": "аплодисменты", "footsteps": "шаги", "clapping": "хлопки",
    "writing": "пишет", "scissors": "ножницы", "tools": "инструмент",
    "drill": "дрель", "sawing": "пила", "hammer": "молоток",
}


def enabled() -> bool:
    return bool(CFG.get("hearing.enabled", True)) and not STATE["off"]


def _ru(label: str) -> str:
    low = label.lower()
    if low in _RU:
        return _RU[low]
    for k, v in _RU.items():
        if k in low:
            return v
    return label


def _load():
    """Ленивая загрузка: модель поднимается при первом звуке, а не на старте —
    старт и так длинный, а уши нужны только когда кто-то шумит."""
    global _model, _labels
    try:
        from panns_inference import AudioTagging, labels
        dev = str(CFG.get("hearing.device", "cpu"))
        _model = AudioTagging(checkpoint_path=None, device=dev)
        _labels = list(labels)
        STATE["ready"] = True
        log.info("Уши: PANNs загружены (%s, %d классов)", dev, len(_labels))
    except ImportError:
        STATE["off"] = True
        log.info("Уши: panns_inference не установлен — работаю без меток "
                 "звуков (ставится сам при следующем запуске)")
    except Exception as e:
        STATE["off"] = True
        log.warning("Уши: не поднялись (%s) — работаю без меток звуков", e)


def _resample(a: np.ndarray) -> np.ndarray:
    """16 -> 32 кГц линейной интерполяцией. Для классификатора событий
    этого достаточно: он смотрит на форму спектра, а не на тембр."""
    n = int(len(a) * SR_MODEL / SR_IN)
    if n < 2:
        return a
    return np.interp(np.linspace(0, len(a) - 1, n),
                     np.arange(len(a)), a).astype(np.float32)


def _classify(chunk: np.ndarray):
    x = _resample(chunk)[None, :]
    clipwise, _ = _model.inference(x)
    probs = np.asarray(clipwise[0])
    idx = probs.argsort()[::-1][:6]
    tags = [(_labels[i], float(probs[i])) for i in idx
            if probs[i] >= float(CFG.get("hearing.min_conf", 0.12))]
    speech = 0.0
    for name, p in ((_labels[i].lower(), float(probs[i]))
                    for i in probs.argsort()[::-1][:25]):
        if any(k in name for k in _SPEECH):
            speech = max(speech, p)
    return tags, speech


def _loop():
    _load()
    if STATE["off"]:
        return
    need = int(WINDOW_S * SR_IN)
    while True:
        time.sleep(EVERY_S)
        if not enabled():
            continue
        with _lock:
            if len(_buf) < need // 2:
                continue
            chunk = _buf[-need:].copy()
        try:
            tags, speech = _classify(chunk)
            STATE.update(tags=tags, speech=speech, ts=time.time())
        except Exception as e:
            log.debug("уши споткнулись: %s", e)


def feed(pcm):
    """Кормить из того же места, что и voiceprint — из аудиоцикла."""
    global _buf, _worker
    if not enabled():
        return
    try:
        a = np.asarray(pcm, dtype=np.float32).ravel()
    except Exception:
        return
    if not a.size:
        return
    with _lock:
        _buf = np.concatenate([_buf, a])[-int(WINDOW_S * SR_IN * 1.5):]
    if _worker is None:
        _worker = threading.Thread(target=_loop, daemon=True, name="ears")
        _worker.start()


def speech_ok() -> bool:
    """ПРЕДОХРАНИТЕЛЬ ДЛЯ КАРТЫ ГОЛОСОВ: похоже ли, что сейчас говорит
    человек. Отвечаем ДА, когда ушей нет или они молчат дольше трёх секунд —
    правило «не уверен, значит не мешай»: лучше лишний отпечаток, чем
    молча потерять живую речь."""
    if not enabled() or not STATE["ready"]:
        return True
    if time.time() - STATE["ts"] > 3.0:
        return True
    return STATE["speech"] >= float(CFG.get("hearing.speech_min", 0.15))


def now() -> list:
    """Что слышно прямо сейчас: [(имя по-русски, вероятность)]."""
    if not STATE["ready"] or time.time() - STATE["ts"] > 8.0:
        return []
    out, seen = [], set()
    for name, p in STATE["tags"]:
        ru = _ru(name)
        if ru in seen:
            continue
        seen.add(ru)
        out.append((ru, p))
    return out[:3]


def context_line() -> str:
    """Строка для промпта. Формулировка важна: это ФОН, а не обращение.
    Раньше подобные вещи модель принимала за задание и начинала их
    комментировать — здесь прямо сказано, что реагировать не обязательно."""
    tags = now()
    if not tags:
        return ""
    body = ", ".join(t for t, _ in tags)
    return ("Фоном сейчас слышно: " + body + ". Это просто обстановка "
            "вокруг, а не обращение к тебе и не задание. Можешь опереться "
            "на это, если к слову придётся, — а можешь не заметить, как "
            "человек не замечает гула холодильника.")
