"""ПОДГОТОВКА ЗВУКА ПЕРЕД ДВИЖКОМ — «мастеринг» фразы для распознавания.

ЗАДАЧА ВЛАДЕЛЬЦА, дословно: «нужно убрать неточности, попробовать даже
от говёного микро или тихого звука получать, подстраивать звуковые волны
так, чтобы транскрибация была максимально качественной».

ГЛАВНОЕ, ЧТО НАДО ПОНЯТЬ ПРО ДВИЖКИ. Акустическая модель обучалась на
звуке ОПРЕДЕЛЁННОЙ громкости — датасеты нормализуют. Приходит фраза
вчетверо тише обучающей — и внутренние признаки (мел-спектр, нормировка
по кадру) уезжают в область, где модель почти не видела примеров. Это не
«плохо слышно», это ВНЕ РАСПРЕДЕЛЕНИЯ, и лечится не шумодавом, а
приведением уровня к привычному. Отсюда же и «пишет случайные слова»:
на непривычном входе декодер идёт по самым вероятным путям языка, а не
по звуку.

ЧТО ДЕЛАЕМ, ПО ПОРЯДКУ (каждый шаг — из практики звукорежиссуры, и у
каждого понятная причина):

  1. УБИРАЕМ ПОСТОЯННОЕ СМЕЩЕНИЕ. Дешёвые платы дают ненулевое среднее.
     Оно съедает динамический диапазон и сдвигает всю нормировку.

  2. СРЕЗАЕМ НИЗ ДО 70 Гц. Голос начинается с 80-85 Гц у мужчины. Ниже —
     только гул стола, вентилятор, стук по столу и наводка 50 Гц. Этот
     мусор часто ГРОМЧЕ голоса и, если его не убрать, именно он задаёт
     нормировку: голос после неё окажется тихим.

  3. ЛЁГКАЯ КОМПРЕССИЯ. Живая речь скачет на 20-30 дБ между ударным
     слогом и безударным окончанием. Тихие окончания — это как раз
     падежи и согласные на конце, то есть то, что чаще всего и
     «дописывается наугад». Мягко поджимаем громкое, чтобы окончания
     поднялись вместе с общим уровнем. Ратио 2:1 — это «почти незаметно»
     по меркам звукорежиссуры, но для движка разница большая.

  4. ПРИВОДИМ К ЦЕЛЕВОЙ ГРОМКОСТИ. Считаем RMS по РЕЧЕВЫМ кадрам (не по
     всей фразе с паузами — иначе длинная пауза занизит оценку) и
     выводим на -20 dBFS. Усиление ограничено: шум усиливать незачем.

  5. ОГРАНИЧИТЕЛЬ НА 0.95. Клиппинг для движка хуже тишины: срезанная
     синусоида даёт широкий спектр гармоник, и согласные превращаются
     в треск (это мы уже видели на живом звуке владельца).

  6. ПОДУШКИ ТИШИНЫ ПО КРАЯМ. Потоковые модели (RNNT) на первом кадре
     ещё «разгоняются», и первый звук фразы часто теряется. Сто
     миллисекунд тишины впереди дают модели войти в режим до того, как
     начнётся речь.

ЧЕСТНОСТЬ. Всё это — обработка, а обработка может и навредить. Поэтому
здесь же живёт РЕЖИМ СРАВНЕНИЯ: стенд может прогнать один и тот же кусок
дважды, сырым и обработанным, и записать оба текста рядом. Решает не моя
вера в компрессор, а два столбика в data/hear_bench.
"""
import logging

import numpy as np

log = logging.getLogger("saika.frontend")

SR = 16000


def _highpass(x, sr, fc=70.0):
    """Однополюсный ФВЧ. Дёшево и ровно настолько, насколько надо: нам не
    нужен крутой срез, нам нужно убрать постоянный гул."""
    a = float(np.exp(-2.0 * np.pi * fc / sr))
    y = np.empty_like(x)
    # y[n] = a*(y[n-1] + x[n] - x[n-1])
    prev_x = 0.0
    prev_y = 0.0
    # векторизовать однополюсный рекурсивный фильтр нельзя, но numpy-цикл
    # на 100к отсчётов — это миллисекунды; для фразы приемлемо
    for i in range(len(x)):
        cur = x[i]
        prev_y = a * (prev_y + cur - prev_x)
        prev_x = cur
        y[i] = prev_y
    return y


def _highpass_fft(x, sr, fc=70.0):
    """То же самое, но через спектр — на длинных кусках заметно быстрее."""
    n = len(x)
    nfft = 1 << int(np.ceil(np.log2(n)))
    sp = np.fft.rfft(x, nfft)
    fr = np.fft.rfftfreq(nfft, 1.0 / sr)
    # плавный скат, чтобы не звенело: полное подавление до fc/2, полный
    # пропуск от fc, между ними косинусный переход
    g = np.ones_like(fr)
    lo, hi = fc * 0.5, fc
    m = (fr < lo)
    g[m] = 0.0
    m = (fr >= lo) & (fr < hi)
    g[m] = 0.5 - 0.5 * np.cos(np.pi * (fr[m] - lo) / (hi - lo))
    return np.fft.irfft(sp * g, nfft)[:n]


def _speech_rms(x, sr):
    """RMS по кадрам, где есть речь. Пауза в оценку громкости не идёт —
    иначе длинная тишина в конце фразы занизит уровень и мы задерём
    усиление до шума."""
    win = int(sr * 0.02)
    if win < 8 or len(x) < win * 3:
        return float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    m = len(x) // win
    fr = np.sqrt((x[:m * win].reshape(m, win) ** 2).mean(1))
    peak = float(fr.max()) if fr.size else 0.0
    if peak <= 0:
        return 0.0
    live = fr[fr >= peak * 0.2]
    return float(np.sqrt(np.mean(live ** 2))) if live.size else peak


def _compress(x, sr, thr_db=-24.0, ratio=2.0, atk_ms=5.0, rel_ms=80.0):
    """Мягкая компрессия по огибающей, поблочно.

    Считаем в логарифме — так это и делают в звуке: и ухо, и признаки
    движка логарифмичны. Огибающую берём по блокам в 5мс, а не по
    сэмплам: слух разницы не слышит, а цикл по сотне тысяч отсчётов из
    питона стоил бы больше, чем всё остальное вместе взятое."""
    if ratio <= 1.0 or x.size < 64:
        return x
    blk = max(8, int(sr * atk_ms / 1000.0))
    m = x.size // blk
    if m < 3:
        return x
    env = np.abs(x[:m * blk].reshape(m, blk)).max(1)
    # релиз: экспоненциальное «спадание» огибающей между блоками
    a = float(np.exp(-blk / (sr * rel_ms / 1000.0)))
    sm = np.empty_like(env)
    acc = 0.0
    for i in range(m):
        v = env[i]
        acc = v if v > acc else acc * a + v * (1 - a)
        sm[i] = acc
    db = 20.0 * np.log10(np.maximum(sm, 1e-6))
    over = np.maximum(0.0, db - thr_db)
    gain = 10.0 ** ((-over * (1.0 - 1.0 / ratio)) / 20.0)
    # растягиваем поблочный коэффициент на отсчёты с интерполяцией, чтобы
    # на стыках блоков не щёлкало
    idx = (np.arange(x.size) / blk).clip(0, m - 1)
    g = np.interp(idx, np.arange(m), gain).astype(np.float32)
    return x * g


def _limiter(x, sr, ceiling=0.97, rel_ms=60.0):
    """Look-ahead лимитер. Прежний «ограничитель» делил ВСЮ фразу, если
    один сэмпл вылез за потолок: единичный щелчок (плевок в микрофон,
    взрывной согласный) ронял громкость всей реплики и сводил на нет
    усиление, которое только что поставил AGC. Здесь коэффициент считается
    поблочно (1мс): тише становится только ВОКРУГ пика, а ровная речь
    остаётся на целевом уровне. Атака мгновенная (чтобы пик не пролез),
    отпуск плавный (чтобы не «дышало»), плюс на блок вперёд — начать
    придавливать ДО пика, а не на нём."""
    n = x.size
    if n < 64:
        p = float(np.max(np.abs(x))) if n else 0.0
        return x * (ceiling / p) if p > ceiling else x
    blk = max(8, int(sr * 0.001))
    m = n // blk
    if m < 3:
        p = float(np.max(np.abs(x)))
        return x * (ceiling / p) if p > ceiling else x
    peak = np.abs(x[:m * blk].reshape(m, blk)).max(1)
    target = np.minimum(1.0, ceiling / np.maximum(peak, 1e-9))
    look = np.minimum(target, np.roll(target, 1))
    look[0] = target[0]
    a_rel = float(np.exp(-blk / (sr * max(rel_ms, 1.0) / 1000.0)))
    g = np.empty(m, np.float32)
    cur = 1.0
    for i in range(m):
        t = float(look[i])
        cur = t if t < cur else cur * a_rel + t * (1.0 - a_rel)
        g[i] = cur
    idx = (np.arange(n) / blk).clip(0, m - 1)
    gs = np.interp(idx, np.arange(m), g).astype(np.float32)
    y = x[:n] * gs
    pk = float(np.max(np.abs(y))) if y.size else 0.0
    if pk > 0.999:                       # страховка от выбросов интерполяции
        y = y * (0.999 / pk)
    return y


def prepare(pcm16, sr: int = SR, cfg=None) -> np.ndarray:
    """Фраза -> фраза, приведённая к виду, привычному для движка."""
    c = cfg or {}
    x = np.asarray(pcm16, dtype=np.float32).ravel()
    if x.size < 16:
        return np.asarray(pcm16, dtype=np.int16)
    x = x / 32768.0
    # 1. постоянное смещение
    x = x - float(np.mean(x))
    # 2. низ
    try:
        if float(c.get("hp_hz", 70.0)) > 0:
            x = _highpass_fft(x, sr, float(c.get("hp_hz", 70.0)))
    except Exception as e:
        log.debug("ФВЧ пропущен: %s", e)
    # 3. компрессия
    try:
        if float(c.get("comp_ratio", 2.0)) > 1.0:
            x = _compress(x, sr, float(c.get("comp_thr_db", -24.0)),
                          float(c.get("comp_ratio", 2.0)))
    except Exception as e:
        log.debug("компрессор пропущен: %s", e)
    # 4. целевая громкость
    tgt_db = float(c.get("target_dbfs", -20.0))
    max_gain_db = float(c.get("max_gain_db", 30.0))
    rms = _speech_rms(x, sr)
    if rms > 1e-6:
        need = tgt_db - 20.0 * np.log10(rms)
        need = float(np.clip(need, -12.0, max_gain_db))
        x = x * (10.0 ** (need / 20.0))
    # 5. ограничитель — look-ahead лимитером, а не делением всей фразы:
    #    тише только ВОКРУГ пика, ровная речь держит целевую громкость,
    #    поэтому усиление из шага 4 доезжает до движка, а не срезается
    #    первым же щелчком.
    try:
        x = _limiter(x, sr, float(c.get("limit_ceiling", 0.97)),
                     float(c.get("limit_rel_ms", 60.0)))
    except Exception as e:
        log.debug("лимитер пропущен: %s", e)
        peak = float(np.max(np.abs(x))) if x.size else 0.0
        if peak > 0.97:
            x = x * (0.97 / peak)
    # 6. подушки тишины
    pad = int(sr * float(c.get("pad_ms", 100.0)) / 1000.0)
    if pad > 0:
        x = np.concatenate([np.zeros(pad, np.float32), x,
                            np.zeros(pad, np.float32)])
    return np.clip(x * 32768.0, -32768, 32767).astype(np.int16)


def condition(pcm16, sr: int = SR, ch: str = "mic", cfg=None):
    """СТУПЕНЬ 0 — кондиционирование ЗАХВАТА на потоке (кусок ~100мс).

    Зачем: выравнивание громкости в prepare() стоит ПЕРЕД движком STT, а
    ворота VAD и кодировщик голоса ECAPA видят СЫРОЙ звук. На тихом входе
    (−46 dBFS) ворота бракуют речь, а эмбеддинги «плывут» и люди не
    разделяются. Поднимаем уровень ЗДЕСЬ, единожды, до всех потребителей.

    Дёшево: DC + однополюсный HPF + медленный AGC по речевому RMS с
    потолком усиления. Состояние (бегущее усиление) — на самой функции, по
    каналу, поэтому переживает живую перепрошивку. Только БУСТ тихого и
    лёгкий поджим громкого; шум в тишине не разгоняем — AGC адаптируется
    лишь когда в куске есть энергия."""
    c = cfg or {}
    if not c.get("enabled", True):
        return pcm16
    x = np.asarray(pcm16, dtype=np.float32).ravel()
    if x.size < 8:
        return pcm16
    x = x / 32768.0
    x = x - float(np.mean(x))
    try:
        fc = float(c.get("hp_hz", 70.0))
        if fc > 0:
            x = _highpass_fft(x, sr, fc)
    except Exception:
        pass
    st = condition.__dict__.setdefault("state", {})
    g = float(st.get(ch, 1.0))
    raw = float(np.sqrt(np.mean(x * x))) if x.size else 0.0
    floor = float(c.get("floor", 0.0012))
    if raw > floor:
        rms = _speech_rms(x, sr)
        if rms > 1e-6:
            tgt = 10.0 ** (float(c.get("target_dbfs", -22.0)) / 20.0)
            maxg = 10.0 ** (float(c.get("max_gain_db", 20.0)) / 20.0)
            want = float(np.clip(tgt / rms, 0.7, maxg))
            a = 0.35 if want < g else 0.12      # атака быстрее отпуска
            g = g * (1.0 - a) + want * a
            st[ch] = g
    y = x * g
    pk = float(np.max(np.abs(y))) if y.size else 0.0
    if pk > 0.97:                                # мягкий потолок от всплеска
        y = y * (0.97 / pk)
    return np.clip(y * 32768.0, -32768, 32767).astype(np.int16)


def report(pcm16, sr: int = SR) -> dict:
    """Что было со звуком до обработки — для стенда и панели."""
    x = np.asarray(pcm16, np.float32).ravel() / 32768.0
    if not x.size:
        return {}
    rms = _speech_rms(x, sr)
    peak = float(np.max(np.abs(x)))
    return {"rms_dbfs": round(20.0 * np.log10(max(rms, 1e-6)), 1),
            "peak": round(peak, 3),
            "clip_pct": round(float(np.mean(np.abs(x) >= 0.995)) * 100, 3),
            "dc": round(float(np.mean(x)), 5)}
