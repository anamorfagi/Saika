"""Отпечаток голоса: звук -> вектор (2026-07-28).

ЗАЧЕМ. Распознавание ГОЛОСА (кто говорит) — задача отдельная от распознавания
РЕЧИ (что сказано). Решается она не текстом, а геометрией: кусок звука
превращается в вектор фиксированной длины, и «тот же человек» = «вектор рядом»
по косинусу. Дальше этот же вектор можно спроецировать в 2D и показать
человеку — см. projector.py.

ДВА ДВИЖКА, и это не перестраховка ради перестраховки:
- ECAPA-TDNN (SpeechBrain, 192 измерения) — нормальное качество, но тянет
  torch и ~80МБ весов с HuggingFace при первом запуске. У Сайки torch и так
  стоит (GigaAM), так что обычно берётся он.
- ЛЁГКИЙ (чистый numpy, 68 измерений) — MFCC-статистики + форма спектра +
  высота тона. Кластеры грязнее, НО: работает сразу, без скачиваний, без
  видеопамяти, и картинка на экране живая с первой же фразы. Это фолбэк на
  случай «нет сети / нет speechbrain / файрвол» и режим для слабых машин.

ВАЖНО ПРО ВИДЕОПАМЯТЬ: ECAPA считаем на CPU и в ОДИН поток (torch любит
захватить все ядра). Причина та же, что в LATENCY.md: видеопамять и ядра
делятся с LLM/TTS/STT, и модуль-развлечение не имеет права отъедать у слуха.
"""
import logging
import threading

import numpy as np

from server.config import CFG, ROOT

log = logging.getLogger("saika.voiceprint")

SR = 16000

# ---------------------------------------------------------------- лёгкий путь
# Мел-фильтры считаются один раз на набор параметров и живут в кэше: на
# каждый чанк их пересчитывать — это 90% времени лёгкого энкодера.
_MEL_CACHE: dict = {}


def _hz_to_mel(f):
    return 2595.0 * np.log10(1.0 + f / 700.0)


def _mel_to_hz(m):
    return 700.0 * (10.0 ** (m / 2595.0) - 1.0)


def _mel_filterbank(sr=SR, n_fft=512, n_mels=40, fmin=40.0, fmax=7600.0):
    key = (sr, n_fft, n_mels, fmin, fmax)
    fb = _MEL_CACHE.get(key)
    if fb is not None:
        return fb
    n_bins = n_fft // 2 + 1
    pts = _mel_to_hz(np.linspace(_hz_to_mel(fmin), _hz_to_mel(fmax), n_mels + 2))
    bins = np.floor((n_fft + 1) * pts / sr).astype(int)
    bins = np.clip(bins, 0, n_bins - 1)
    fb = np.zeros((n_mels, n_bins), dtype=np.float32)
    for i in range(n_mels):
        lo, mid, hi = bins[i], bins[i + 1], bins[i + 2]
        if mid > lo:
            fb[i, lo:mid] = np.linspace(0, 1, mid - lo, endpoint=False)
        if hi > mid:
            fb[i, mid:hi] = np.linspace(1, 0, hi - mid, endpoint=False)
    _MEL_CACHE[key] = fb
    return fb


def _dct_matrix(n_out, n_in):
    key = ("dct", n_out, n_in)
    m = _MEL_CACHE.get(key)
    if m is not None:
        return m
    k = np.arange(n_out)[:, None]
    n = np.arange(n_in)[None, :]
    m = np.cos(np.pi * k * (2 * n + 1) / (2 * n_in)).astype(np.float32)
    m *= np.sqrt(2.0 / n_in)
    _MEL_CACHE[key] = m
    return m


def _frames(x, win=400, hop=160):
    """Нарезка на окна БЕЗ копирования (stride_tricks)."""
    if len(x) < win:
        x = np.pad(x, (0, win - len(x)))
    n = 1 + (len(x) - win) // hop
    return np.lib.stride_tricks.as_strided(
        x, shape=(n, win), strides=(x.strides[0] * hop, x.strides[0])).copy()


def _pitch(x, sr=SR):
    """Высота тона по автокорреляции -> (медиана в Гц, доля озвонченных
    кадров). Не для точности — для картинки: шёпот/крик/простуда видны на
    глаз, и это то, ради чего человек начинает играть с визуализацией."""
    win, hop = 1024, 512
    if len(x) < win:
        return 0.0, 0.0
    fr = _frames(x, win, hop)
    lo, hi = int(sr / 400), int(sr / 60)      # 60..400 Гц
    vals, total = [], 0
    for f in fr:
        f = f - f.mean()
        if float(np.dot(f, f)) < 1e-6:
            continue
        total += 1
        ac = np.correlate(f, f, mode="full")[win - 1:]
        seg = ac[lo:hi]
        if len(seg) < 4:
            continue
        i = int(np.argmax(seg))
        if seg[i] / (ac[0] + 1e-9) > 0.35:     # похоже на вокализованный кадр
            vals.append(sr / (lo + i))
    voiced = len(vals) / max(1, total)
    return (float(np.median(vals)) if vals else 0.0), float(voiced)


def _light_features(x, sr=SR):
    """68 чисел: MFCC (среднее/разброс/дельта) + форма спектра + тон."""
    x = np.asarray(x, dtype=np.float32)
    if len(x) < sr // 10:
        x = np.pad(x, (0, sr // 10 - len(x)))
    # предыскажение: поднимает верх, там больше индивидуального
    x = np.append(x[0], x[1:] - 0.97 * x[:-1])

    fr = _frames(x, 400, 160) * np.hamming(400).astype(np.float32)
    spec = np.abs(np.fft.rfft(fr, n=512)).astype(np.float32)
    power = spec ** 2
    mel = power @ _mel_filterbank(sr).T
    logmel = np.log(mel + 1e-8)

    mfcc = logmel @ _dct_matrix(21, logmel.shape[1]).T
    mfcc = mfcc[:, 1:21]                       # c0 = громкость, личность не несёт
    d = np.diff(mfcc, axis=0) if len(mfcc) > 1 else np.zeros((1, 20), np.float32)

    freqs = np.linspace(0, sr / 2, spec.shape[1]).astype(np.float32)
    p = power / (power.sum(axis=1, keepdims=True) + 1e-9)
    centroid = float((p * freqs).sum(axis=1).mean())
    bandwidth = float(np.sqrt((p * (freqs - centroid) ** 2).sum(axis=1)).mean())
    cum = np.cumsum(p, axis=1)
    rolloff = float(freqs[np.argmax(cum >= 0.85, axis=1)].mean())
    flat = float(np.exp(np.log(power + 1e-9).mean(axis=1)).mean()
                 / (power.mean(axis=1).mean() + 1e-9))
    zcr = float((np.diff(np.sign(fr), axis=1) != 0).mean())
    slope = float(np.polyfit(np.arange(logmel.shape[1]),
                             logmel.mean(axis=0), 1)[0])
    f0, voiced = _pitch(x, sr)

    v = np.concatenate([
        mfcc.mean(axis=0), mfcc.std(axis=0), np.abs(d).mean(axis=0),
        np.array([centroid / 4000.0, bandwidth / 2000.0, rolloff / 8000.0,
                  flat * 10.0, zcr * 10.0, slope, np.log1p(f0) / 6.0,
                  voiced], np.float32),
    ]).astype(np.float32)
    return np.nan_to_num(v, nan=0.0, posinf=0.0, neginf=0.0), f0


# ----------------------------------------------------------------- фасад
class Encoder:
    """Один объект на процесс. encode() потокобезопасен настолько, насколько
    это нужно: считает всегда один рабочий поток voiceprint."""

    def __init__(self):
        self.backend = "light"
        self.dim = 68
        self._sb = None
        self._torch = None
        self._tried = False
        self._lock = threading.Lock()
        self.last_error = ""

    # --- тяжёлый движок поднимается лениво и молча падает в лёгкий
    def warmup(self):
        want = CFG.get("voiceprint.encoder", "auto")
        if want == "light" or self._tried:
            return self.backend
        self._tried = True
        try:
            # под общим замком: на старте ECAPA, Vosk и TTS поднимаются
            # одновременно, и параллельный импорт внутренностей torch
            # роняет второго с «Duplicate registration» (см. torch_gate.py,
            # поймано живым логом 2026-07-28 — падал qwen3)
            from server.torch_gate import TORCH_GATE
            with TORCH_GATE:
                import torch
                torch.set_num_threads(1)  # не отбирать ядра у слуха и LLM
                try:
                    from speechbrain.inference.speaker import EncoderClassifier
                except Exception:         # speechbrain < 1.0
                    from speechbrain.pretrained import EncoderClassifier
                savedir = ROOT / "models" / "ecapa"
                savedir.mkdir(parents=True, exist_ok=True)
                self._sb = EncoderClassifier.from_hparams(
                    source="speechbrain/spkrec-ecapa-voxceleb",
                    savedir=str(savedir), run_opts={"device": "cpu"})
            self._torch = torch
            self.backend, self.dim = "ecapa", 192
            log.info("Отпечаток голоса: ECAPA-TDNN на CPU, 192 измерения")
        except Exception as e:
            self.last_error = str(e)[:200]
            log.info("Отпечаток голоса: ECAPA недоступна (%s) — "
                     "работаю на лёгких признаках", self.last_error)
        return self.backend

    def encode(self, pcm16: np.ndarray):
        """int16 моно 16кГц -> (вектор единичной длины, высота тона в Гц)."""
        x = np.asarray(pcm16, dtype=np.float32) / 32768.0
        if self._sb is not None:
            try:
                with self._lock:
                    t = self._torch.from_numpy(x).unsqueeze(0)
                    with self._torch.no_grad():
                        emb = self._sb.encode_batch(t).squeeze().cpu().numpy()
                v = np.asarray(emb, dtype=np.float32).ravel()
                f0, _ = _pitch(x)                   # тон всё равно нужен для UI
                return _unit(v), f0
            except Exception as e:
                # один сбой не должен гасить модуль: падаем в лёгкий путь
                log.warning("ECAPA споткнулась (%s) — лёгкие признаки", e)
                self._sb = None
                self.backend, self.dim = "light", 68
        v, f0 = _light_features(x)
        return _unit(v), f0


def _unit(v):
    n = float(np.linalg.norm(v))
    return (v / n).astype(np.float32) if n > 1e-9 else v.astype(np.float32)


def cosine(a, b):
    return float(np.dot(a, b))          # оба вектора уже единичной длины

# ─────────────────────── это вообще голос или нет? ───────────────────────
def speechiness(x, sr=SR):
    """0..1 — насколько кусок похож на РЕЧЬ, а не на щелчок, стук или шип.

    ЗАЧЕМ. Модуль отпечатка ловил речь простым порогом громкости, и любой
    клац мышкой, стук по столу или скрип стула превращался в «незнакомый
    голос»: точка прыгала на карту, попадала в облако и портила статистику.
    Громкость про это ничего не знает — щелчок громкий. А вот СТРОЕНИЕ звука
    знает: у речи есть основной тон и гармоники, она длится десятые доли
    секунды и её спектр далёк от ровного.

    Смотрим четыре вещи, каждая ловит свой класс ошибок:
      тон       — доля вокализованных кадров (автокорреляция). У щелчка и
                  шипения тона нет вообще
      ровность  — спектральная плоскость. Шум ровный, голос горбатый
      низ       — доля энергии в 80..1000 Гц, где живут основной тон и первая
                  форманта. У клацанья вся энергия наверху
      длитель.  — какую часть окна звук вообще присутствует. Щелчок это
                  10-20 мс из 1200, даже если он громкий

    Возвращает (оценка, из_чего_сложилась) — второе показываем в интерфейсе,
    иначе «не голос» выглядит как каприз."""
    x = np.asarray(x, dtype=np.float32)
    if x.dtype != np.float32 or np.max(np.abs(x)) > 2.0:
        x = x.astype(np.float32) / 32768.0
    if len(x) < sr // 8:
        return 0.0, {}

    f0, voiced = _pitch(x, sr)
    fr = _frames(x, 400, 160) * np.hamming(400).astype(np.float32)
    power = (np.abs(np.fft.rfft(fr, n=512)) ** 2).astype(np.float32) + 1e-10

    # ровность спектра: 0 — чистый тон, 1 — белый шум
    flat = float(np.mean(np.exp(np.mean(np.log(power), axis=1))
                         / np.mean(power, axis=1)))
    freqs = np.linspace(0, sr / 2, power.shape[1])
    band = (freqs >= 80) & (freqs <= 1000)
    low = float(np.mean(power[:, band].sum(axis=1) / power.sum(axis=1)))

    e = power.sum(axis=1)
    active = float(np.mean(e > e.max() * 0.06)) if len(e) else 0.0

    parts = {
        "tone": round(min(1.0, voiced / 0.30), 3),
        "shape": round(min(1.0, max(0.0, (0.35 - flat) / 0.30)), 3),
        "low": round(min(1.0, low / 0.45), 3),
        "hold": round(min(1.0, active / 0.45), 3),
        "f0": int(f0),
    }
    # МИНИМУМ, А НЕ СРЕДНЕЕ: голос обязан пройти по ВСЕМ четырём признакам.
    # На среднем громкий щелчок с ровной длинной реверберацией легко набирал
    # проходной балл за счёт двух признаков из четырёх.
    score = min(parts["tone"], parts["shape"], parts["low"], parts["hold"])
    return float(score), parts


def mel_profile(x, bands=40, sr=SR):
    """Усреднённый лог-мел кусочка, 0..1 — «как этот звук выглядит».

    Нужен журналу слуха: по нему звуки собираются в группы («вот эти сорок
    раз — один и тот же щелчок») и рисуются в отчёте. Мел, а не линейный
    спектр, потому что группировать надо так, как слышит ухо: разница между
    100 и 200 Гц важнее, чем между 6000 и 6100."""
    x = np.asarray(x, dtype=np.float32)
    if np.max(np.abs(x)) > 2.0:
        x = x / 32768.0
    if len(x) < 512:
        x = np.pad(x, (0, 512 - len(x)))
    fr = _frames(x, 400, 160) * np.hamming(400).astype(np.float32)
    power = np.abs(np.fft.rfft(fr, n=512)).astype(np.float32) ** 2
    mel = power @ _mel_filterbank(sr, 512, bands).T
    v = np.log(mel.mean(axis=0) + 1e-9)
    v = (v - v.min()) / max(1e-6, float(v.max() - v.min()))
    return np.nan_to_num(v, nan=0.0).astype(np.float32)
