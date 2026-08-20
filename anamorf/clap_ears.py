"""СВОИ МЕТКИ ЗВУКОВ — CLAP, zero-shot (2026-08-15).

ПОВОД, живой и смешной: владелец битбоксит в микрофон, а уши (PANNs)
отвечают словарём AudioSet — губная трель у них «собака 44%», трещётка
языком «машина 46%», горловая бочка «музыка 74%». Словарь фиксированный,
527 классов, вокальной перкуссии в нём нет и не будет.

CLAP (LAION) решает это по-другому: он выучил ОБЩЕЕ пространство звука и
текста, и метки задаются словами в момент запроса. «Звук бочки горлом»,
«губная трель», «трещётка языком» — просто строки; свои добавляются в
config -> hearing.clap.labels без всякого дообучения.

МЕСТО В КОНВЕЙЕРЕ. Это ВТОРОЕ мнение поверх PANNs, а не замена: PANNs
дёшев и широк (весь бытовой мир), CLAP точен там, где словаря не хватает.
Когда CLAP уверен (балл выше порога), его метка встаёт ПЕРВОЙ в картину
звука; не уверен — картина остаётся как была. Модель тяжёлая (сотни МБ,
качается с HF при первом включении через ensure_features), поэтому:
  - грузится лениво и в фоне, под общим TORCH_GATE;
  - считается не чаще раза в clap_every_s и только когда есть звук;
  - нет пакета laion_clap — модуль молча спит, уши живут на PANNs.

ЧЕСТНОЕ ПРЕДУПРЕЖДЕНИЕ В КОДЕ: этот модуль писался на стенде без доступа
к весам модели (закрытая песочница), то есть НЕ прогонялся с настоящим
CLAP. Все вызовы обёрнуты так, чтобы любой его отказ не тронул слух.
"""
import logging
import threading
import time

import numpy as np

from anamorf.config import CFG

log = logging.getLogger("saika.clap")

SR_IN = 16000
SR_CLAP = 48000        # CLAP обучен на 48 кГц
WINDOW_S = 2.0

STATE = {"ready": False, "off": False, "why": "", "tags": [], "ts": 0.0}

_model = None
_label_embs = None
_labels = []
_lock = threading.Lock()
_load_started = False

# Метки по умолчанию. en — промпт для модели (английский: на нём CLAP
# учился и слышит лучше всего), ru — как показать человеку, ono — «как
# звучит». Свои добавляются в config: hearing.clap.labels = [{en,ru,ono}].
_DEFAULT_LABELS = [
    {"en": "beatbox kick drum made with the throat",
     "ru": "горловая бочка", "ono": "бум"},
    {"en": "lip roll trill sound, vibrating lips",
     "ru": "губная трель", "ono": "брррр"},
    {"en": "tongue clicking ratchet roll sound",
     "ru": "трещётка", "ono": "тррр"},
    {"en": "vocal hi-hat, short tss sounds with the mouth",
     "ru": "ротовой хай-хэт", "ono": "тс-тс"},
    {"en": "vocal snare drum imitation, beatbox snare",
     "ru": "ротовой малый барабан", "ono": "пф"},
    {"en": "long hissing shhh sound", "ru": "шипение", "ono": "тсссс"},
    {"en": "human whistling a tone", "ru": "свист", "ono": "фьюить"},
    {"en": "a person speaking", "ru": "речь", "ono": ""},
    {"en": "music playing from speakers", "ru": "музыка", "ono": ""},
    {"en": "typing on a mechanical keyboard",
     "ru": "клавиатура", "ono": "тук-тук"},
]


def enabled() -> bool:
    return bool(CFG.get("hearing.clap.enabled", True)) and not STATE["off"]


def _load():
    global _model, _label_embs, _labels
    try:
        import laion_clap
        from anamorf.torch_gate import TORCH_GATE
        with TORCH_GATE:
            m = laion_clap.CLAP_Module(enable_fusion=False)
            m.load_ckpt()          # веса приедут с HF при первом запуске
        raw = CFG.get("hearing.clap.labels", None) or _DEFAULT_LABELS
        labels = [dict(x) for x in raw if x.get("en")]
        embs = m.get_text_embedding([x["en"] for x in labels],
                                    use_tensor=False)
        embs = np.asarray(embs, dtype=np.float32)
        embs /= (np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9)
        with _lock:
            _model, _label_embs, _labels = m, embs, labels
        STATE["ready"] = True
        log.info("CLAP-уши: подняты, меток %d — звуки без класса в "
                 "AudioSet теперь называются своими словами", len(labels))
    except ImportError:
        STATE["off"] = True
        log.info("CLAP-уши: пакет laion_clap не установлен — живём на "
                 "PANNs (поставится сам при следующем start.bat)")
    except Exception as e:
        STATE["off"] = True
        STATE["why"] = str(e)[:160]
        log.warning("CLAP-уши не поднялись (%s) — живём на PANNs",
                    STATE["why"])


def warm():
    global _load_started
    if STATE["ready"] or STATE["off"] or _load_started:
        return
    _load_started = True
    threading.Thread(target=_load, daemon=True, name="clap-ears").start()


def classify(chunk_16k: np.ndarray):
    """-> [(ru, en, ono, score)] по убыванию или []. Дорого (сотни мс на
    CPU) — зовущий сам решает, как часто; здесь только счёт."""
    if not enabled() or not STATE["ready"]:
        return []
    try:
        x = np.asarray(chunk_16k, dtype=np.float32)
        if x.size < SR_IN:          # меньше секунды — не о чем говорить
            return []
        n = int(len(x) * SR_CLAP / SR_IN)
        x48 = np.interp(np.linspace(0, len(x) - 1, n),
                        np.arange(len(x)), x).astype(np.float32)
        with _lock:
            emb = _model.get_audio_embedding_from_data(
                x=x48[None, :], use_tensor=False)
            embs, labels = _label_embs, _labels
        emb = np.asarray(emb, dtype=np.float32)[0]
        emb /= (np.linalg.norm(emb) + 1e-9)
        sims = embs @ emb
        # softmax с температурой: баллы читаются как доли уверенности
        e = np.exp((sims - sims.max()) / 0.07)
        probs = e / e.sum()
        order = np.argsort(-probs)
        out = []
        for i in order[:3]:
            out.append((labels[i].get("ru", labels[i]["en"]),
                        labels[i]["en"], labels[i].get("ono", ""),
                        float(probs[i])))
        STATE["tags"], STATE["ts"] = out, time.time()
        return out
    except Exception as e:
        STATE["fails"] = STATE.get("fails", 0) + 1
        if STATE["fails"] >= 3:
            STATE["off"] = True
            log.warning("CLAP-уши: три ошибки подряд (%s) — выключаюсь",
                        str(e)[:120])
        return []


def status() -> dict:
    return {"ready": STATE["ready"], "off": STATE["off"],
            "why": STATE["why"],
            "tags": [(r, round(p, 2)) for r, _e, _o, p in STATE["tags"]]}
