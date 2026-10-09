"""ПИЩАЛКА ЦЕНЗУРЫ — ГДЕ СЛОВО ЗАПИКАЛИ (06.09.2026).

Владелец: «транскриб должен полностью всё писать, и даже больше: он
должен понимать, где в моменте слово запикали, проставить точки в этом
моменте и прописать серым словом, еле заметным, что запикали».

Пищалка — самый простой звук на свете: один чистый тон (обычно 1 кГц),
который держится 100-500 мс без дрожания. Ни у речи, ни у музыки такого
нет: у голоса частота плывёт и есть гармоники, у музыки — аккорды.
Ищем по кадрам 32 мс: если почти вся энергия кадра сидит в одной узкой
полосе 500-3000 Гц (тональность) и эта частота не меняется 4+ кадра
подряд — это пик. Возвращаем отрезки в секундах от начала куска.

Живой замер: уши (PANNs) на том же месте дают «Beep, bleep 0.44» — две
независимые проверки одного факта.
"""
import numpy as np

_N = 512          # окно 32 мс при 16 кГц
_HOP = 256        # шаг 16 мс


def find(pcm16, sr: int = 16000, min_ms: int = 150, tonal: float = 0.93,
         lo: float = 500.0, hi: float = 3200.0):
    """-> [(t0, t1, hz)] — отрезки чистого тона в секундах от начала."""
    try:
        x = np.asarray(pcm16, dtype=np.float32).ravel()
        if x.size < _N * 4:
            return []
        if np.max(np.abs(x)) > 1.5:
            x = x / 32768.0
        if sr != 16000:
            n = int(x.size * 16000 / sr)
            x = np.interp(np.linspace(0, x.size - 1, n), np.arange(x.size), x)
        win = np.hanning(_N).astype(np.float32)
        fq = np.fft.rfftfreq(_N, 1.0 / 16000)
        band = (fq >= lo) & (fq <= hi)
        frames = []      # (tonal, hz, loud)
        for off in range(0, x.size - _N, _HOP):
            sp = np.abs(np.fft.rfft(x[off:off + _N] * win)) ** 2
            tot = float(sp[fq >= 80].sum()) + 1e-12
            loud = float(np.sqrt(np.mean(x[off:off + _N] ** 2)))
            i = int(np.argmax(sp * band))
            # ЧИСТОТА: энергия в ±1 бин (±31 Гц) вокруг пика против всего
            # спектра. Замер на ролике ДНК: пищалка — 1.00, самая звонкая
            # гласная речи — 0.84. Порог 0.93 сидит между ними.
            pk = float(sp[max(0, i - 1):i + 2].sum())
            frames.append((pk / tot, float(fq[i]), loud))
        out = []
        # ВЫРЕЗАННЫЙ ЗВУК (владелец, 06.09.2026: «обычно звук запикивают,
        # или резко убирают звук, или подставляют заглушку»). Резко убранный
        # звук — это провал огибающей до нуля с отвесными краями посреди
        # речи: 80-600 мс тишины, а по обе стороны — громко. Естественная
        # пауза так не выглядит: у неё края пологие и уровень не нулевой.
        louds = [f[2] for f in frames]
        _mute_lvl = 0.0015
        k = 0
        while k < len(frames):
            if louds[k] >= _mute_lvl:
                k += 1
                continue
            j = k
            while j < len(frames) and louds[j] < _mute_lvl:
                j += 1
            dur = (j - k) * _HOP / 16000
            if (0.08 <= dur <= 0.6 and k >= 2 and j + 1 < len(frames)
                    and louds[k - 1] > 0.02 and louds[min(len(frames) - 1, j)] > 0.02):
                out.append((round(k * _HOP / 16000, 3),
                            round((j * _HOP + _N) / 16000, 3), 0.0))
            k = max(j, k + 1)
        need = max(2, int(min_ms / 16))
        i = 0
        while i < len(frames):
            t, hz, loud = frames[i]
            if t < tonal or loud < 0.004:
                i += 1
                continue
            j = i + 1
            while j < len(frames):
                t2, hz2, loud2 = frames[j]
                if t2 < tonal * 0.85 or loud2 < 0.004 or abs(hz2 - hz) > 35.0:
                    break
                j += 1
            if j - i >= need:
                out.append((round(i * _HOP / 16000, 3),
                            round((j * _HOP + _N) / 16000, 3),
                            round(float(np.median([f[1] for f in frames[i:j]])), 1)))
            i = max(j, i + 1)
        return out
    except Exception:
        return []


def mark(text: str, beeps, sec: float, times=None):
    """-> (текст, [{t0,t1,hz,at,guess}]).

    Точек в тексте больше нет (владелец, 06.09.2026: «убирай точки… просто
    пиши тёмным текстом место, где запикали»). Слово, накрытое пиком или
    вырезом, остаётся в строке как движок его услышал, а интерфейс красит
    его серым по индексу at. Если движок на этом месте не услышал ничего —
    вставляем слово «запикано» (тоже серым): место должно быть видно.
    hz == 0 — вырезанная тишина, не пик."""
    words = (text or "").split()
    info = []
    if not beeps:
        return text or "", info
    ins = {}
    for b0, b1, hz in beeps:
        mid = (b0 + b1) / 2
        idx, guess = None, ""
        if times:
            for k, (w, w0, w1, *_c) in enumerate(times):
                if w0 <= b1 and w1 >= b0:
                    idx, guess = k, w
                    break
            if idx is None:
                for k, (w, w0, w1, *_c) in enumerate(times):
                    if w0 > mid:
                        idx = k
                        break
                if idx is None:
                    idx = len(times)
                if idx > 0 and b0 - times[idx - 1][2] < 0.25:
                    idx, guess = idx - 1, times[idx - 1][0]
            if guess:
                aw = guess.strip(".,!?").lower()
                for k, w in enumerate(words):
                    if w.strip(".,!?…").lower() == aw:
                        idx = k
                        break
                else:
                    guess = ""
            if not guess:
                idx = min(len(words), idx)
        else:
            idx = int(round(mid / max(sec, 0.1) * len(words)))
        idx = max(0, min(len(words), idx))
        if not guess:
            ins[idx] = ins.get(idx, 0) + 1
        info.append({"t0": b0, "t1": b1, "hz": hz, "guess": guess.strip(".,!?"),
                     "at": idx, "kind": "mute" if not hz else "beep"})
    if ins:
        out = []
        shift = 0
        for k, w in enumerate(words):
            for _ in range(ins.get(k, 0)):
                out.append("запикано")
            out.append(w)
        for _ in range(ins.get(len(words), 0)):
            out.append("запикано")
        # индексы вставленных слов — по новой строке
        words2 = out
        for e in info:
            if not e["guess"]:
                for k, w in enumerate(words2):
                    if w == "запикано" and not any(x.get("at2") == k for x in info):
                        e["at2"] = k
                        break
            else:
                aw = e["guess"].lower()
                for k, w in enumerate(words2):
                    if w.strip(".,!?").lower() == aw:
                        e["at2"] = k
                        break
        for e in info:
            e["at"] = e.pop("at2", e["at"])
        return " ".join(out), info
    return " ".join(words), info


def mark_text(text, beeps, sec, times=None):
    return mark(text, beeps, sec, times)[0]
