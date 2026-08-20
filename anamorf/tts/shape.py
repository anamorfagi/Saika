"""ФОРМА ГОЛОСА: темп и высота поверх ЛЮБОГО движка (2026-08-13).

Владелец: «останется только голоса намутить и проработать голосовую
систему, чтобы нужный тон, тембр, скорость получать».

Движков у нас семь, и каждый умеет своё: Qwen3 понимает инструкцию про
эмоцию, Edge принимает rate=, Piper и Silero не принимают ничего. Городить
семь разных путей — значит получить семь разных результатов на одну и ту
же просьбу «говори помедленнее». Поэтому темп и высота делаются ПОСЛЕ
синтеза, над готовым PCM: один код, одинаковое поведение у всех движков,
включая те, что появятся потом.

Как это работает, без магии:
  ТЕМП   — фазовая склейка внахлёст (OLA): режем звук на окна, кладём их
           плотнее или реже и сшиваем перекрытием. Длительность меняется,
           высота остаётся. Окно ~46 мс, перекрытие 50%.
  ВЫСОТА — растянуть по времени в обратную сторону, а потом пересемплить:
           получается сдвиг тона без изменения длительности. Отсюда и
           тембр: +2..3 полутона делают голос звонче, -2..3 — глубже.

Только numpy — новых зависимостей нет, значит нечему не установиться.
"""
import logging

import numpy as np

log = logging.getLogger("saika.voice.shape")

_WIN_S = 0.046          # окно OLA, секунды
_EPS = 1e-6


def _ola(x: np.ndarray, rate: float, sr: int) -> np.ndarray:
    """Растянуть/сжать во времени в `rate` раз, высоту не трогая (WSOLA).

    Простая склейка внахлёст (без поиска) на замере уводила высоту: чистые
    180 Гц после растяжения показывали 188, а +3 полутона давали 223 вместо
    214. Причина известная — окна кладутся встык по фазе как попало, периоды
    рвутся, спектр плывёт. Поэтому перед укладкой каждого окна ищем сдвиг в
    пределах ±четверти окна, при котором оно ЛУЧШЕ ВСЕГО совпадает с уже
    записанным хвостом. Речь квазипериодична, поиск попадает почти в период,
    и склейка перестаёт слышаться."""
    if abs(rate - 1.0) < 0.01 or x.size < 64:
        return x
    win = max(128, int(_WIN_S * sr) // 2 * 2)
    hop_out = win // 2
    hop_in = max(1, int(round(hop_out * rate)))
    tol = win // 4                      # где искать лучшую склейку
    w = np.hanning(win).astype(np.float32)
    n_out = int(len(x) / max(rate, _EPS)) + 2 * win
    out = np.zeros(n_out, dtype=np.float32)
    norm = np.zeros(n_out, dtype=np.float32)
    # ИДЕАЛЬНАЯ позиция чтения считается отдельно от фактической: поиск
    # лучшей склейки сдвигает окно на ±tol, и если складывать эти сдвиги в
    # тот же счётчик, они копятся. На замере это давало «темп 1.3» вместо
    # 0.77с целых 0.71с — почти 9% мимо. Поиск влияет только на то, ОТКУДА
    # взять окно, а шаг по времени всегда ровный.
    ideal = 0.0
    pos_out = 0
    while ideal + win + tol < len(x) and pos_out + win < n_out:
        pos_in = int(ideal)
        if pos_out > 0 and pos_in > tol:
            ref = out[pos_out:pos_out + hop_out]
            lo = max(0, pos_in - tol)
            hi = min(len(x) - win, pos_in + tol)
            if hi > lo:
                cand = np.lib.stride_tricks.sliding_window_view(
                    x[lo:hi + hop_out], hop_out)
                pos_in = lo + int(np.argmax(cand @ ref))
        seg = x[pos_in:pos_in + win] * w
        out[pos_out:pos_out + win] += seg
        norm[pos_out:pos_out + win] += w
        ideal += hop_in
        pos_out += hop_out
    out = out[:pos_out + win]
    norm = norm[:pos_out + win]
    return out / np.maximum(norm, 1e-3)


def _resample(x: np.ndarray, factor: float) -> np.ndarray:
    """Линейная пересемплировка: длина делится на factor, тон умножается."""
    if abs(factor - 1.0) < 0.01 or x.size < 4:
        return x
    n = max(1, int(len(x) / factor))
    idx = np.linspace(0, len(x) - 1, n).astype(np.float32)
    return np.interp(idx, np.arange(len(x), dtype=np.float32), x).astype(np.float32)


def apply(pcm_bytes: bytes, sr: int, speed: float = 1.0,
          semitones: float = 0.0) -> bytes:
    """Придать куску звука нужные темп и высоту.

    speed      1.0 — как есть, 1.2 — на пятую быстрее, 0.85 — медленнее
    semitones  сдвиг тона: +2 звонче, -2 глубже (тембр персонажа)
    """
    if (abs(speed - 1.0) < 0.01 and abs(semitones) < 0.05) or not pcm_bytes:
        return pcm_bytes
    try:
        x = np.frombuffer(pcm_bytes, dtype=np.float32).copy()
        if x.size < 64:
            return pcm_bytes
        if abs(semitones) >= 0.05:
            f = float(2.0 ** (semitones / 12.0))
            # СНАЧАЛА пересемплить (тон ×f, длительность /f), ПОТОМ вернуть
            # длительность склейкой. Порядок здесь не косметический: если
            # поменять шаги местами, длина уезжает в f², а тон — в другую
            # сторону (поймано замером: +3 полутона давали 1.42с вместо
            # 1.00с и голос НИЖЕ вместо выше).
            x = _ola(_resample(x, f), 1.0 / f, sr)
        if abs(speed - 1.0) >= 0.01:
            x = _ola(x, float(speed), sr)
        return np.clip(x, -1.0, 1.0).astype(np.float32).tobytes()
    except Exception as e:          # звук важнее красоты: отдаём как было
        log.debug("форма голоса не применилась: %s", e)
        return pcm_bytes


def settings() -> tuple[float, float]:
    """Что стоит сейчас: (темп, полутона). Костюм персонажа пишет сюда же."""
    from anamorf.config import CFG
    try:
        speed = float(CFG.get("tts.speed", 1.0) or 1.0)
    except Exception:
        speed = 1.0
    try:
        semi = float(CFG.get("tts.pitch", 0.0) or 0.0)
    except Exception:
        semi = 0.0
    # рамки здравого смысла: за ними речь перестаёт быть речью
    return max(0.5, min(2.0, speed)), max(-8.0, min(8.0, semi))
