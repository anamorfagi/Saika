# -*- coding: utf-8 -*-
"""КАКОЙ ЭТО ЯЗЫК — ДО РАСШИФРОВКИ (2026-09-01).

ПОВОД. Владелец говорит «What\'s your name», GigaAM пишет «Вот чя наив».
Движок знает только русский и честно укладывает чужую речь в русскую
фонетику. Заметить это ПОСЛЕ, по виду текста, не выходит: слов ровно
столько, сколько было сказано, плотность нормальная — просто слова не
те. Пробовали ловить по плотности, не сработало ни разу.

Значит спрашивать надо раньше: сначала «какой это язык», потом уже кому
отдавать кусок.

ЧЕМ. Крошечный whisper (tiny, 39M против 800M у основного) умеет
определять язык одним проходом энкодера — это десятки миллисекунд и
меньше сотни мегабайт видеопамяти. Расшифровывать им ничего не надо,
только назвать язык. Держать ради этого большую модель в памяти было бы
расточительством: у нас её и так впритык.

ЧЕСТНОСТЬ. Модель отдаёт уверенность. Низкая уверенность — не повод
угадывать: возвращаем None, и вызывающий работает как раньше, по
основному движку. Молчать честнее, чем врать.
"""
import logging
import threading

import numpy as np

from anamorf.config import CFG

log = logging.getLogger("saika.langid")

_LOCK = threading.Lock()
S = {"model": None, "tried": False, "err": ""}


def _load():
    if S["model"] is not None or S["tried"]:
        return S["model"]
    S["tried"] = True
    try:
        from anamorf.torch_gate import TORCH_GATE
        with TORCH_GATE:
            from faster_whisper import WhisperModel
            import torch
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            name = CFG.get("stt.langid.model", "tiny")
            S["model"] = WhisperModel(
                name, device=dev,
                compute_type="int8_float16" if dev == "cuda" else "int8",
                download_root=str(CFG.get("paths.models", "models")) or None)
            log.info("Определитель языка: whisper-%s на %s", name, dev)
    except Exception as e:
        S["err"] = str(e)[:160]
        log.warning("Определитель языка не поднялся: %s", S["err"])
    return S["model"]


# ═══ КОРОТКАЯ ПАМЯТЬ ЯЗЫКА (2026-09-01) ═══
# Человек не меняет язык на каждом слове. Если последние секунды шла
# уверенная английская речь, короткое «yeah» — тоже английское, хотя на
# полусекунде определитель честно скажет «не знаю».
#
# Это и есть то, о чём просил владелец: «научить систему слушать все свои
# алгоритмы, чтобы они общались между собой». Определитель, не уверенный
# в одиночку, спрашивает у недавнего прошлого.
#
# Память короткая нарочно: разговор может переключиться, и держаться за
# язык минутной давности — та же ошибка, только наоборот.
_RECENT = []          # [(время, язык, уверенность)]


def _remember(lang, p):
    import time as _t
    _RECENT.append((_t.time(), lang, p))
    del _RECENT[:-12]


def recent(sec=None):
    """Каким языком говорили только что. -> (язык, уверенность) или (None, 0)."""
    import time as _t
    sec = float(sec if sec is not None
                else CFG.get("stt.langid.memory_s", 12.0) or 12.0)
    now = _t.time()
    fresh = [(l, p) for t, l, p in _RECENT if now - t <= sec]
    if not fresh:
        return None, 0.0
    by = {}
    for l, p in fresh:
        by[l] = by.get(l, 0.0) + p
    lang = max(by, key=by.get)
    return lang, by[lang] / max(len(fresh), 1)


def detect(pcm16, sr=16000):
    """-> (язык, уверенность) или (None, 0.0), если не уверены.

    Кусок короче секунды не спрашиваем: на нём определитель гадает.
    """
    if not CFG.get("stt.langid.enabled", True):
        return None, 0.0
    try:
        x = np.asarray(pcm16, dtype=np.float32)
        if x.dtype != np.float32 or x.max() > 1.5:
            x = x.astype(np.float32) / 32768.0
        sec = len(x) / float(sr or 16000)
        # КОРОТКИЙ КУСОК СПРАШИВАЕТ У ПАМЯТИ. Сам определитель на
        # полусекунде гадает, а недавнее прошлое знает точно.
        if sec < float(CFG.get("stt.langid.min_s", 0.6) or 0.6):
            rl, rp = recent()
            if rl and rp >= float(CFG.get("stt.langid.memory_p", 0.7) or 0.7):
                return rl, round(rp * 0.9, 2)
            return None, 0.0
        m = _load()
        if m is None:
            return None, 0.0
        with _LOCK:
            lang, p, _all = m.detect_language(audio=x)
        need = float(CFG.get("stt.langid.min_p", 0.6) or 0.6)
        if not lang or p < need:
            # не уверены сами — спросим, чем говорили только что
            rl, rp = recent()
            if rl and rp >= float(CFG.get("stt.langid.memory_p", 0.7) or 0.7):
                log.debug("язык: сам не уверен (%.2f), беру недавний «%s»",
                          p or 0.0, rl)
                return rl, round(rp * 0.85, 2)
            return None, float(p or 0.0)
        _remember(str(lang), float(p))
        return str(lang), float(p)
    except Exception as e:
        log.debug("определение языка: %s", e)
        return None, 0.0


def engine_for(lang):
    """Кому отдать кусок на этом языке."""
    ru_first = CFG.get("stt.langid.ru_engine", "gigaam")
    other = CFG.get("stt.langid.other_engine", "faster_whisper")
    ru_like = set(CFG.get("stt.langid.ru_like", ["ru"]) or ["ru"])
    return ru_first if (lang in ru_like) else other
