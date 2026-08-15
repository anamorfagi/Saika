"""БИТБОКС-ТРАНСКРИБ — перкуссия буквами, в реальном времени (2026-08-15).

ВЫЗОВ ВЛАДЕЛЬЦА, дословно: «щас это было похоже на прууу ккх тся тся пу
ккх — хер ты таким транскрибом за мной поспеешь. Но если разработаешь
алгоритм и не будешь игнорить мои запросы на изучение вопроса — возможно,
у тебя получится. Чекни, какие звуки бывают и какая у них частота».

Чекнул (источники в переписке 15.08). У вокальной перкуссии сигнатуры
разнесены по спектру и времени так удачно, что хватает ПРАВИЛ:

  бочка «пу/бум»   — выдох-взрыв, энергия НИЖЕ ~250 Гц, короче ~180мс;
  хэт «тс»         — шумовой щелчок ВЫШЕ ~4 кГц, короче ~120мс;
  снейр «ккх/пф»   — шумовой удар в середине-верхе (1-6 кГц), 100-300мс;
  губная трель     — вибрация губ ~20-35 Гц: огибающая ДРОЖИТ с этой
  «брррр»            частотой поверх низкого тона;
  трещётка «тррр»  — та же дрожь 20-35 Гц, но щелчки высокочастотные;
  шипение «тсссс»  — долгий ровный шум сверху;
  бас горлом «умм» — долгий звонкий тон ниже ~130 Гц.

Значит различаем по четырём осям: длительность, куда легла энергия
(низ/середина/верх), есть ли модуляция огибающей 15-45 Гц (трель!) и
звонкость (периодичность). Никакого обучения: каждый порог можно назвать
вслух и покрутить в конфиге.

МЕСТО В КОНВЕЙЕРЕ. Кормится из горячего цикла слуха сырыми кусками по
100мс, вся математика — numpy на огибающей, доли миллисекунды. Когда
событий-ударов набирается ≥3 за 2.5 секунды — это ритм, а не случайный
стук: включается «битбокс-режим», и последовательность звуков уезжает
живой строкой в чат: «🥁 пу тс ккх тс-тс брррр». Молчит — режим гаснет.
"""
import logging
import time
from collections import deque

import numpy as np

from server.config import CFG

log = logging.getLogger("saika.beatbox")

SR = 16000
HOP = 64                     # огибающая с шагом 4мс

_events = deque(maxlen=24)   # (ts, ono)
_state = {"in_ev": False, "frames": [], "quiet": 0, "pre": deque(maxlen=6),
          "last_seq": ""}
QUIET_CLOSE = 10             # 10 кадров по 4мс = 40мс тишины -> конец удара


def _features(x):
    """Оси классификации одного события."""
    n = len(x)
    dur = n / SR
    spec = np.abs(np.fft.rfft(x * np.hanning(n)))
    fr = np.fft.rfftfreq(n, 1.0 / SR)
    tot = float(spec.sum()) + 1e-9
    low = float(spec[fr < 250].sum()) / tot
    mid = float(spec[(fr >= 250) & (fr < 2500)].sum()) / tot
    high = float(spec[fr >= 4000].sum()) / tot
    # дрожь огибающей 15-45 Гц — почерк трели (губы/язык бьются с этой
    # частотой; у одиночного удара в этой полосе пика нет)
    env = np.abs(x)
    m = len(env) // HOP
    trill = 0.0
    if m >= 16:
        e = env[:m * HOP].reshape(m, HOP).mean(1)
        e = e - e.mean()
        es = np.abs(np.fft.rfft(e * np.hanning(m)))
        ef = np.fft.rfftfreq(m, HOP / SR)
        band = es[(ef >= 15) & (ef <= 45)]
        rest = es[(ef >= 3) & (ef < 15)].sum() + es[(ef > 45)].sum() + 1e-9
        if band.size:
            trill = float(band.max() / (rest / max(1, es.size)))
    # звонкость: периодичность 70-300 Гц
    voiced, f0 = False, 0.0
    if n >= 800:
        w = x[:min(n, 1600)]
        ac = np.correlate(w, w, "full")[len(w) - 1:]
        lo, hi = int(SR / 300), int(SR / 70)
        if hi < len(ac):
            k = lo + int(np.argmax(ac[lo:hi]))
            if ac[k] > 0.35 * ac[0]:
                voiced, f0 = True, SR / k
    return dur, low, mid, high, trill, voiced, f0


def _classify(x):
    dur, low, mid, high, trill, voiced, f0 = _features(x)
    t_thr = float(CFG.get("beatbox.trill_peak", 6.0))
    if trill >= t_thr and dur >= 0.25:
        return "тррр" if high >= 0.35 else "брррр"
    if dur < 0.20 and low >= 0.45:
        return "пу"
    if dur < 0.14 and high >= 0.45:
        return "тс"
    if dur < 0.35 and high >= 0.30 and mid >= 0.20 and not voiced:
        return "ккх"
    if dur >= 0.30 and high >= 0.45 and not voiced:
        return "тсссс"
    if dur >= 0.30 and voiced and f0 and f0 < 130:
        return "умм"
    return ""


def _is_rhythm(ev) -> bool:
    """═══ РИТМ — ЭТО РОВНОСТЬ, А НЕ ПРОСТО ТРИ УДАРА (2026-08-16) ═══

    Владелец: «клавиатура вряд ли похожа на мои звуки битбокса». Правило
    «≥3 события за 2.5с» ловило любую серию щелчков — а по спектру
    одиночный щелчок клавиши и хай-хэт неразличимы, я это уже признавал.
    Разница не в звуке удара, а в РАССТАНОВКЕ ударов во времени:

      битбокс  — человек держит темп, промежутки почти равны;
      клавиши  — промежутки скачут в разы: «мысль-очередь-пробел-пауза».

    Считаем разброс промежутков (коэффициент вариации: сигма/среднее).
    У ровного бита он около нуля, у печати уверенно выше половины. Порог
    в конфиге; и отдельно требуем, чтобы удары не были однообразными —
    десять одинаковых «тс» подряд это стук, а не рисунок."""
    ts = [t for t, _o in ev]
    if len(ts) < 3:
        return False
    gaps = [b - a for a, b in zip(ts, ts[1:]) if b > a]
    if len(gaps) < 2:
        return False
    mean = sum(gaps) / len(gaps)
    if mean <= 0:
        return False
    var = sum((g - mean) ** 2 for g in gaps) / len(gaps)
    cv = (var ** 0.5) / mean
    if cv > float(CFG.get("beatbox.jitter_max", 0.45)):
        return False
    # рисунок, а не морзянка: хотя бы два разных звука на серию
    if len({o for _t, o in ev}) < 2:
        return False
    return True


def feed(pcm16: np.ndarray):
    """Кусок 100мс из горячего цикла. Возвращает свежую последовательность
    строки битбокса, если она ИЗМЕНИЛАСЬ, иначе None."""
    if not CFG.get("beatbox.enabled", True):
        return None
    x = np.asarray(pcm16, dtype=np.float32).ravel() / 32768.0
    now = time.time()

    env = np.abs(x)
    m = max(1, len(env) // HOP)
    e = env[:m * HOP].reshape(m, HOP).mean(1)
    floor = float(CFG.get("beatbox.floor", 0.006))
    loud = e.max() if len(e) else 0.0

    # ПО КАДРАМ 4МС, А НЕ ПО КУСКАМ 100МС (2026-08-15, два урока стенда
    # подряд). Урок 1: индексы в скользящем буфере уезжают — копим сэмплы
    # напрямую. Урок 2: паузы между ударами битбокса 60-120мс, короче
    # куска, — события слипались («тс тс пу» превращалось в одно длинное).
    # Конец удара — это 40мс тишины НА КАДРАХ, где бы они ни лежали
    # относительно границ куска.
    frames = x[:m * HOP].reshape(m, HOP)
    for fi in range(m):
        fe = float(e[fi])
        fr_ = frames[fi]
        if not _state["in_ev"]:
            if fe >= floor * 3:
                _state["in_ev"] = True
                _state["frames"] = list(_state["pre"]) + [fr_]
                _state["quiet"] = 0
            else:
                _state["pre"].append(fr_)
        else:
            _state["frames"].append(fr_)
            _state["quiet"] = _state["quiet"] + 1 if fe < floor else 0
            total = len(_state["frames"]) * HOP
            # потолок события — ручка (2026-08-15, живой тест: владелец
            # тянул «тсссс» дольше секунды, жёсткий потолок резал звук на
            # три события). Трель и шипение легально живут секундами.
            _cap = int(float(CFG.get("beatbox.max_event_s", 3.0)) * SR)
            if _state["quiet"] >= QUIET_CLOSE or total > _cap:
                seg = np.concatenate(
                    _state["frames"][:-_state["quiet"] or None])
                _state.update(in_ev=False, frames=[], quiet=0)
                _state["pre"].clear()
                if len(seg) >= 480:                 # хотя бы 30мс
                    ono = _classify(seg)
                    if ono:
                        _events.append((now, ono))
    # битбокс-режим: ≥3 событий за 2.5с — это ритм, а не случайный стук
    while _events and now - _events[0][0] > 6.0:
        _events.popleft()
    recent = [(t, o) for t, o in _events if now - t <= 2.5]
    seq = ""
    if len(recent) >= 3 and _is_rhythm(recent):
        seq = " ".join(o for _t, o in list(_events)[-10:])
    if seq != _state["last_seq"]:
        _state["last_seq"] = seq
        return seq                                  # '' = режим погас
    return None


def reset():
    """Полный сброс: после рефакторинга на кадры сюда забыли добавить
    frames/quiet/pre — недособранный удар переживал reset и склеивался
    с первым ударом следующего захода."""
    _events.clear()
    _state["pre"].clear()
    _state.update(in_ev=False, frames=[], quiet=0, last_seq="")
