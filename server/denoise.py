"""ШУМОДАВ — отдельная подсистема со сменными движками (2026-07-28).

ПОЧЕМУ ОТДЕЛЬНАЯ ПОДСИСТЕМА, А НЕ ГАЛОЧКА. Раньше шумоподавление в проекте
было ровно одно: браузерное `noiseSuppression: true` в getUserMedia. Оно
чёрный ящик — не настраивается, не измеряется, в разных сборках Chrome ведёт
себя по-разному, и понять «работает или нет» можно только на ощущениях. При
этом шум решает многое: на нём VAD ловит ложные фразы, whisper дорисовывает
галлюцинации, а отпечаток голоса рисует точку, когда человек молчит. Значит,
это такая же полноправная технология, как слух и голос, — со своим выбором
движка, своими настройками и своим стендом для замеров.

ЧЕМ ЭТО ЧЕСТНЕЕ ГАЛОЧКИ. Все движки живут за одним интерфейсом
`process(pcm16) -> pcm16` и меряются одной линейкой: tools/denoise_bench.py
гоняет одну и ту же запись через всех и печатает, сколько миллисекунд на
секунду звука стоит каждый, сколько давит шума и НЕ СЪЕДАЕТ ЛИ ГОЛОС. Второе
важнее первого: шумодав, который «чистит» так, что STT перестаёт узнавать
слова, хуже чем никакого.

ДВИЖКИ (от дешёвых к дорогим):
  off        — ничего не делаем, честная база отсчёта
  gate       — ворота по шумовому полу: тише порога = тишина. Копейки по
               цене, зато молчание становится настоящим молчанием
  spectral   — вычитание спектра шума (классика). Хорош на ровном гуле:
               вентилятор, кулер, наводка 50 Гц
  wiener     — винер по решению-направлению (Ephraim-Malah). Дороже
               вычитания, но не даёт «музыкального шума» — того самого
               бульканья, которым славится грубое вычитание
  noisereduce— библиотека, нестационарный режим. Считается пачками, для
               живого потока тяжеловата, зато полезна как ориентир качества
  rnnoise    — маленькая рекуррентная сеть (48кГц, кадры по 10мс)
  deepfilter — DeepFilterNet: лучшее качество из доступного локально, но и
               самый дорогой; тянет torch

ШУМОВОЙ ПРОФИЛЬ УЧИТСЯ САМ, на кадрах без речи. Просить человека «помолчите
десять секунд для калибровки» — плохая идея: комната меняется (включился
кондиционер, приехал сосед с перфоратором), профиль обязан ехать следом.

ПРО ЗАДЕРЖКУ. Все спектральные движки работают окнами по 32мс с перекрытием,
то есть добавляют в путь слуха ~32мс постоянной задержки. На фоне выстраданных
0.6с ответа это ничто (LATENCY.md), но в бюджет это записано осознанно, а не
«само получилось».
"""
import logging
import threading
import time

import numpy as np

from server.config import CFG

log = logging.getLogger("saika.denoise")

SR = 16000
NFFT = 512          # 32мс окно
HOP = 128           # 8мс шаг, перекрытие 75% — гладкая склейка без щелчков

ENGINES = ("off", "gate", "spectral", "wiener", "noisereduce",
           "rnnoise", "deepfilter")


# ───────────────────────────── потоковый STFT ─────────────────────────────
class _Stream:
    """STFT/ISTFT с перекрытием для НЕПРЕРЫВНОГО потока произвольных кусков.

    Обычный оффлайн-STFT тут не годится: чанки приходят по 100мс, и если
    обрабатывать каждый отдельно, на стыках будут щелчки. Держим хвост
    предыдущего чанка и складываем перекрытием (overlap-add), поэтому выход
    непрерывен, а цена — постоянная задержка в одно окно."""

    def __init__(self):
        self.win = np.hanning(NFFT).astype(np.float32)
        # нормировка окна под overlap-add с шагом HOP
        s = np.zeros(NFFT, np.float32)
        for i in range(0, NFFT, HOP):
            s += np.roll(self.win ** 2, i)
        self.wnorm = float(np.mean(s)) or 1.0
        self.reset()

    def reset(self):
        self.inbuf = np.zeros(0, np.float32)
        self.tail = np.zeros(NFFT, np.float32)

    def run(self, x: np.ndarray, gain_fn):
        """gain_fn(mag, phase) -> усиление на каждую частотную корзину."""
        self.inbuf = np.concatenate([self.inbuf, x.astype(np.float32)])
        out = np.zeros(len(self.inbuf) + NFFT, np.float32)
        used = 0
        pos = 0
        while pos + NFFT <= len(self.inbuf):
            fr = self.inbuf[pos:pos + NFFT] * self.win
            spec = np.fft.rfft(fr, NFFT)
            mag = np.abs(spec)
            g = gain_fn(mag)
            rec = np.fft.irfft(spec * g, NFFT).astype(np.float32) * self.win
            out[pos:pos + NFFT] += rec
            pos += HOP
            used = pos
        out[:NFFT] += self.tail
        ready = out[:used] if used else np.zeros(0, np.float32)
        self.tail = out[used:used + NFFT].copy()
        self.inbuf = self.inbuf[used:]
        return (ready / self.wnorm).astype(np.float32)


# ───────────────────────────── шумовой профиль ────────────────────────────
class _Profile:
    """САМООБУЧАЮЩАЯСЯ ОЦЕНКА ШУМА — минимальная статистика (Martin).

    Идея, которая снимает главную головную боль всех шумодавов: чтобы выучить
    шум, обычно надо знать, где НЕ речь; чтобы понять, где не речь, надо знать
    шум. Замкнутый круг, и в него мы уже вляпались дважды (см. ниже).

    Минимальная статистика этот круг разрывает: никакого решения «речь / не
    речь» не принимается вообще. В каждой частотной корзине держим МИНИМУМ за
    последние полторы секунды. Человек не тянет одну ноту полторы секунды
    подряд, а гул кулера — тянет; значит минимум в каждой корзине и есть шум,
    что бы поверх него ни происходило. Умножаем на поправку (минимум всегда
    занижает среднее колеблющейся величины) — и профиль готов.

    Скользящий минимум считаем по подокнам, а не перебором всего буфера: за
    кадр это O(корзин), а не O(корзин × кадров). При 125 кадрах в секунду
    разница между «незаметно» и «греет процессор».

    ДВЕ ЗАПИСАННЫЕ ГРАБЛИ (2026-07-28, обе поймал стенд, не ухо):
    1. Сначала речь ловили по средней энергии кадра против медленного пола.
       Пол рос на 2% за кадр — при 125 кадрах в секунду это удвоение за треть
       секунды. Пол догонял речь, речь переставала быть речью, профиль вбирал
       ГОЛОС, и движок исправно вычитал из голоса голос: шум −22 дБ, речь
       тоже −22 дБ.
    2. Потом ловили по доле корзин выше шума. Лучше, но профиль всё равно
       обновлялся во время речи и уползал вверх на 60% за пять секунд.
    Оба раза чинить пытались порогом. Порог тут не при чём — не должно быть
    решения, которое можно ошибиться."""

    SUBS = 6            # подокон в скользящем минимуме
    SUBLEN = 32         # кадров в подокне  ->  окно ≈ 1.5с при 125 кадрах/с

    def __init__(self):
        self.noise = None
        self.floor = 0.0
        self.speech = False
        self.learned = 0
        self._subs = []
        self._cur = None
        self._sm = None
        self._n = 0

    def update(self, mag: np.ndarray):
        # СГЛАЖИВАЕМ ПЕРЕД МИНИМУМОМ. Минимум сырого спектра за полторы
        # секунды — это минимум из двух сотен случайных величин, он занижает
        # реальный уровень шума в разы. Итог был виден на стенде: движок
        # считал, что шума почти нет, и «давил» его на полтора децибела.
        # Сглаженная периодограмма колеблется куда меньше, и её минимум уже
        # близок к правде.
        if self._sm is None:
            self._sm = mag.copy()
        else:
            self._sm = (0.85 * self._sm + 0.15 * mag).astype(np.float32)
        sm = self._sm
        if self._cur is None:
            self._cur = sm.copy()
        else:
            np.minimum(self._cur, sm, out=self._cur)
        self._n += 1
        if self._n >= self.SUBLEN:
            self._subs.append(self._cur)
            if len(self._subs) > self.SUBS:
                self._subs.pop(0)
            self._cur = sm.copy()
            self._n = 0

        m = self._cur if not self._subs else np.minimum.reduce(
            self._subs + [self._cur])
        bias = float(CFG.get("denoise.min_bias", 2.2))
        est = (m * bias).astype(np.float32)
        # мягко подтягиваем наружу отдаваемый профиль: скачки минимума на
        # границе подокна иначе слышны ступенькой
        self.noise = est if self.noise is None else (
            0.85 * self.noise + 0.15 * est).astype(np.float32)
        self.learned += 1

        e = float(np.mean(mag))
        self.floor = 0.9 * self.floor + 0.1 * e if self.floor else e
        # флаг «сейчас речь» нужен только для показаний в интерфейсе —
        # на сам профиль он больше НЕ влияет, и в этом весь смысл
        self.speech = e > float(np.mean(self.noise)) * float(
            CFG.get("denoise.speech_ratio", 1.8))
        return self.noise


# ────────────────────────────── сами движки ───────────────────────────────
class _Base:
    name = "off"
    needs = ""            # что доустановить, если не встало

    def __init__(self):
        self.ok = True
        self.error = ""

    def process(self, x: np.ndarray) -> np.ndarray:   # float32 [-1..1] @16к
        return x

    def reset(self):
        pass

    def profile(self):
        """Что движок СЧИТАЕТ шумом прямо сейчас — наружу, для интерфейса.
        Показать выученный профиль важнее, чем кажется: пока его не видно,
        «самообучающийся шумодав» ничем не отличается от обещания."""
        return None


class _Gate(_Base):
    """Ворота по шумовому полу. Не «чистит» голос — вырезает паузы.

    ЗАЧЕМ ОТДЕЛЬНЫМ ДВИЖКОМ, если это примитив: половина жалоб на шум — это
    не «голос звучит грязно», а «когда я молчу, оно всё равно что-то слышит
    и рисует». Ворота решают ровно эту половину за микросекунды."""
    name = "gate"

    def __init__(self):
        super().__init__()
        self.floor = 0.0
        self.g = 0.0
        self.hold = 0

    def process(self, x):
        # считаем ПОКАДРОВО (по 5мс), а не одним числом на весь чанк: чанк
        # 100мс — это целый слог, и гейт на его границе слышно щелчком
        step = 80
        n = len(x)
        if n == 0:
            return x
        g = np.empty(n, np.float32)
        for i in range(0, n, step):
            seg = x[i:i + step]
            rms = float(np.sqrt(np.mean(seg * seg)))
            if self.floor == 0:
                self.floor = rms
            elif rms < self.floor:
                self.floor = 0.95 * self.floor + 0.05 * rms
            else:
                self.floor *= 1.0004
            # ПОРОГ ОТНОСИТЕЛЬНО МИНИМУМА, А НЕ СРЕДНЕГО. floor тут — это
            # минимум за последние секунды, а типичная пауза шумит примерно
            # вдвое громче своего минимума. Поэтому множитель ~4: при 2.6
            # треть кадров паузы перепрыгивала порог, удержание постоянно
            # перезапускалось, и ворота не закрывались вообще (стенд: −0.2 дБ).
            thr = max(self.floor * float(CFG.get("denoise.gate_ratio", 4.0)),
                      float(CFG.get("denoise.gate_min", 0.004)))
            # УДЕРЖАНИЕ. Между словами внутри фразы есть паузы по 100-200мс;
            # без удержания ворота захлопываются в них и режут фразу на
            # куски. Держим открытым ещё N миллисекунд после последнего
            # звука — и только потом закрываемся, уже быстро.
            if rms > thr:
                self.hold = int(float(CFG.get("denoise.gate_hold_ms", 220))
                                * SR / 1000 / step)
            elif self.hold > 0:
                self.hold -= 1
            want = 1.0 if (rms > thr or self.hold > 0) else 0.0
            # открывается быстро (иначе съедено начало слова: «…ривет»),
            # закрывается плавно, но уже без прежней вязкости
            self.g += (want - self.g) * (0.85 if want > self.g else 0.06)
            g[i:i + len(seg)] = self.g
        return (x * g).astype(np.float32)


class _Spectral(_Base):
    """Вычитание спектра шума с полом. Классика, дёшево, слышно сразу."""
    name = "spectral"

    def __init__(self):
        super().__init__()
        self.st = _Stream()
        self.pr = _Profile()

    def reset(self):
        self.st.reset()
        self.pr = _Profile()

    def _gain(self, mag):
        n = self.pr.update(mag)
        over = float(CFG.get("denoise.over", 1.8))     # насколько «с запасом»
        floor = float(CFG.get("denoise.floor", 0.08))  # спектральный пол
        g = (mag - over * n) / np.maximum(mag, 1e-9)
        return np.clip(g, floor, 1.0).astype(np.float32)

    def process(self, x):
        return self.st.run(x, self._gain)

    def profile(self):
        return self.pr.noise, self.pr.learned


class _Wiener(_Base):
    """Винер по решению-направлению (Ephraim-Malah).

    Отличие от вычитания в одном: априорное отношение сигнал/шум берётся не
    из текущего кадра, а сглаживается по предыдущему. Именно это убирает
    «музыкальный шум» — бульканье случайных призвуков, которым грубое
    вычитание портит тишину сильнее, чем сам шум."""
    name = "wiener"

    def __init__(self):
        super().__init__()
        self.st = _Stream()
        self.pr = _Profile()
        self.prev = None

    def reset(self):
        self.st.reset()
        self.pr = _Profile()
        self.prev = None

    def _gain(self, mag):
        n = np.maximum(self.pr.update(mag), 1e-9)
        post = (mag ** 2) / (n ** 2)                     # апостериорное ОСШ
        alpha = float(CFG.get("denoise.dd_alpha", 0.96))
        if self.prev is None:
            prio = np.maximum(post - 1.0, 0.0)
        else:
            prio = alpha * self.prev + (1 - alpha) * np.maximum(post - 1.0, 0.0)
        g = prio / (1.0 + prio)
        self.prev = (g ** 2) * post
        floor = float(CFG.get("denoise.floor", 0.08))
        return np.clip(g, floor, 1.0).astype(np.float32)

    def process(self, x):
        return self.st.run(x, self._gain)

    def profile(self):
        return self.pr.noise, self.pr.learned


class _NoiseReduce(_Base):
    name = "noisereduce"
    needs = "поставится сама при следующем запуске start.bat"

    def __init__(self):
        super().__init__()
        self._retry_after = 0.0
        self._short_told = False   # про no-op на коротком куске говорим раз
        try:
            import noisereduce as nr
            self.nr = nr
        except Exception as e:
            self.ok, self.error = False, str(e)[:160]
            # ГОНКА ИМПОРТА — НЕ ПРИГОВОР НА ВЕСЬ СЕАНС (2026-08-15, живой
            # лог: «cannot import name minkowski from partially initialized
            # module scipy.spatial.distance (most likely due to a circular
            # import)». Пакет СТОИТ — просто два потока параллельного
            # автопуска импортировали scipy одновременно, и один застал
            # другого на полпути. Раньше это означало «весь вечер на
            # запасном wiener»: шумодав хуже — GigaAM слышит кашу — владелец
            # получает «Поторо» вместо своей фразы и «распознаватель пишет
            # полную ахинею». Гонка рассасывается за секунды: пробуем
            # импорт ещё раз, когда все уже загрузились.)
            import time as _t
            self._retry_after = _t.time() + 15

    def process(self, x):
        if not self.ok and self._retry_after:
            import time as _t
            if _t.time() >= self._retry_after:
                self._retry_after = 0.0
                try:
                    import noisereduce as nr
                    self.nr = nr
                    self.ok, self.error = True, ""
                    log.info("Шумодав noisereduce ожил со второй попытки — "
                             "гонка импорта scipy рассосалась")
                except Exception as e:
                    self.error = str(e)[:160]
        # МОЛЧАЛИВЫЙ NO-OP — ХУЖЕ ОТКЛЮЧЁННОГО ДВИЖКА (2026-08-15, найдено
        # по живому логу владельца). Браузерный воркер шлёт куски по 1600
        # сэмплов (100мс), а порог входа здесь — 2000 (SR//8). То есть
        # noisereduce, выбранный в панели и числившийся рабочим, не обработал
        # НИ ОДНОГО куска: звук проходил насквозь, панель показывала «всё
        # хорошо», а человек искал причину каши в распознавании. Отказ обязан
        # быть слышен: пишем причину в error (её видит панель) и один раз в
        # лог. Настоящее место этого движка — не поток, а собранная фраза,
        # см. SEGMENT в конце файла.
        if self.ok and len(x) < SR // 8:
            if not getattr(self, "_short_told", False):
                self._short_told = True
                log.warning(
                    "Шумодав noisereduce: кусок %dмс короче его рабочего "
                    "минимума 125мс — В ПОТОКЕ ОН НЕ ДЕЛАЕТ НИЧЕГО. Для "
                    "потока бери wiener/spectral, а noisereduce ставь на "
                    "фразу: denoise.segment_engine",
                    round(len(x) * 1000 / SR))
            self.error = (f"в потоке не работает: кусок "
                          f"{round(len(x) * 1000 / SR)}мс короче минимума "
                          f"125мс — его место на фразе "
                          f"(denoise.segment_engine)")
            return x
        if not self.ok:
            return x
        try:
            return self.nr.reduce_noise(
                y=x, sr=SR, stationary=bool(CFG.get("denoise.nr_stationary", False)),
                prop_decrease=float(CFG.get("denoise.nr_prop", 0.85))
            ).astype(np.float32)
        except Exception as e:
            self.error = str(e)[:160]
            return x


class _RNNoise(_Base):
    """RNNoise: маленькая рекуррентная сеть, кадры по 10мс на 48кГц.

    Резэмпл 16к -> 48к -> 16к делаем линейно: сеть обучена на 48к, кормить её
    16к «как есть» бессмысленно, а честный полифазный ресемплер тут не нужен —
    вход и выход всё равно возвращаются на 16к."""
    name = "rnnoise"
    needs = "поставится сама при следующем запуске start.bat"

    def __init__(self):
        super().__init__()
        self.den = None
        try:
            try:
                from pyrnnoise import RNNoise
                self.den = RNNoise(48000)
                self.kind = "pyrnnoise"
            except Exception:
                from rnnoise_wrapper import RNNoise as RW
                self.den = RW()
                self.kind = "rnnoise-wrapper"
        except Exception as e:
            self.ok, self.error = False, str(e)[:160]
        self.rest = np.zeros(0, np.float32)

    def process(self, x):
        if not self.ok:
            return x
        try:
            up = _resample(x, SR, 48000)
            up = np.concatenate([self.rest, up])
            n = (len(up) // 480) * 480
            self.rest = up[n:]
            if n == 0:
                return np.zeros(0, np.float32)
            block = up[:n]
            pcm = np.clip(block * 32768.0, -32768, 32767).astype(np.int16)
            if self.kind == "pyrnnoise":
                out = np.concatenate([
                    np.asarray(f, np.int16)
                    for _, f in self.den.process_chunk(pcm)]) if hasattr(
                        self.den, "process_chunk") else pcm
            else:
                out = np.frombuffer(self.den.filter(pcm.tobytes()), np.int16)
            return _resample(out.astype(np.float32) / 32768.0, 48000, SR)
        except Exception as e:
            self.error = str(e)[:160]
            self.ok = False
            return x


class _DeepFilter(_Base):
    """DeepFilterNet — лучшее локальное качество, самая высокая цена."""
    name = "deepfilter"
    needs = "поставится сама при следующем запуске start.bat (~200 МБ)"

    def __init__(self):
        super().__init__()
        self.model = None
        try:
            import torch
            torch.set_num_threads(1)      # не отбирать ядра у слуха и LLM
            # ЖЁСТКО НА ПРОЦЕССОР (2026-07-28). init_df() по умолчанию
            # хватает CUDA, если она есть, — а это торчёвый контекст плюс
            # модель, до гигабайта VRAM ради шумодава. VRAM — самое дорогое
            # на этой машине: её делят мозги и слух. Сетка маленькая, на
            # CPU успевает с запасом. Трогать CUDA_VISIBLE_DEVICES нельзя —
            # переменная общая на процесс, а CUDA нужна GigaAM.
            from df.enhance import init_df
            try:
                self.model, self.state, _ = init_df(device="cpu")
            except TypeError:               # старые версии без параметра
                self.model, self.state, _ = init_df()
                try:
                    self.model = self.model.to("cpu")
                except Exception:
                    pass
            self.torch = torch
            self.sr = self.state.sr()
        except Exception as e:
            self.ok, self.error = False, str(e)[:160]

    def process(self, x):
        if not self.ok or len(x) < SR // 8:
            return x
        try:
            from df.enhance import enhance
            up = _resample(x, SR, self.sr)
            t = self.torch.from_numpy(up).unsqueeze(0)
            with self.torch.no_grad():
                y = enhance(self.model, self.state, t)
            return _resample(y.squeeze().cpu().numpy().astype(np.float32),
                             self.sr, SR)
        except Exception as e:
            self.error = str(e)[:160]
            return x


def _resample(x, a, b):
    if a == b or len(x) < 2:
        return np.asarray(x, np.float32)
    n = int(round(len(x) * b / float(a)))
    return np.interp(np.linspace(0, len(x) - 1, n),
                     np.arange(len(x)), x).astype(np.float32)


_CLASSES = {"off": _Base, "gate": _Gate, "spectral": _Spectral,
            "wiener": _Wiener, "noisereduce": _NoiseReduce,
            "rnnoise": _RNNoise, "deepfilter": _DeepFilter}


def make(name: str):
    """Собрать движок по имени. Не встал — возвращаем его же, но с ok=False
    и текстом ошибки: интерфейсу нужно показать ПОЧЕМУ, а не просто спрятать
    пункт из списка."""
    cls = _CLASSES.get(name, _Base)
    try:
        eng = cls()
    except Exception as e:
        eng = _Base()
        eng.ok, eng.error, eng.name = False, str(e)[:160], name
    eng.name = name
    return eng


# ──────────────────────────── живой шумодав ───────────────────────────────
class Denoiser:
    """Один экземпляр на процесс, зовётся из конвейера слуха."""

    # ДВА МЕСТА, ГДЕ ЧИСТИТЬ ЗВУК, И ОНИ РАЗНЫЕ (2026-08-15).
    # Поток (100мс куски) — дёшево и непрерывно, годится для гейта и
    # спектральных движков с перекрытием. Фраза (собранный сегмент перед
    # распознаванием) — там, где нестационарная оценка шума наконец имеет с
    # чем работать: у неё есть и речь, и тишина вокруг неё. Один и тот же
    # класс обслуживает оба, отличается только ключ конфига.
    def __init__(self, key: str = "denoise.engine", label: str = "Шумодав"):
        self.key = key
        self.label = label
        self._lock = threading.Lock()
        self._eng = None
        self._name = ""
        self._want_seen = None
        self.wanted = ""
        self.blocked = ""
        self.ms = 0.0            # скользящее «сколько мс на 100мс звука»
        self.frames = 0
        # СКОЛЬКО ОН РЕАЛЬНО СНИМАЕТ. Спектр в браузере рисуется из сырого
        # микрофона — то есть ДО шумодава, — поэтому увидеть его работу в
        # картинке нельзя в принципе. Нужно число: во сколько раз тише стал
        # звук после обработки. Оно же сразу показывает и перегиб: если
        # давит на 20 дБ, значит ест речь, а не шум.
        self.cut_db = 0.0

    # ЗАПАСНОЙ ПОРЯДОК (2026-07-28). Выбранный движок мог не встать —
    # и тогда шумодав молча пропускал звук как есть. Снаружи это выглядело
    # как «переключаю движки, а результат один и тот же»: он и был один —
    # никакой. Теперь неработающий движок уступает место лучшему рабочему,
    # а интерфейс честно говорит, кто выбран и кто на самом деле трудится.
    FALLBACK = ["deepfilter", "rnnoise", "noisereduce", "wiener", "spectral",
                "gate", "off"]

    def _ensure(self):
        # ПОД ЗАМКОМ (2026-08-14, живой лог владельца: две одинаковые
        # строки «Шумодав: движок noisereduce» в одну и ту же
        # миллисекунду). Замок у объекта был, а сюда его не поставили —
        # и два потока (микрофон и браузерный путь) поднимали движок
        # одновременно: двойная загрузка, двойная запись в лог и лишний
        # экземпляр модели в памяти.
        with self._lock:
            return self._ensure_locked()

    def _ensure_locked(self):
        want = str(CFG.get(self.key, "off"))
        if want not in ENGINES:
            want = "off"
        self.wanted = want
        if want != self._want_seen or self._eng is None:
            self._want_seen = want
            self._eng, self._name = make(want), want
            if self._eng.ok:
                log.info("%s: движок «%s»", self.label, want)
            else:
                log.warning("%s «%s» не встал: %s (%s)", self.label, want,
                            self._eng.error, self._eng.needs)
                self.blocked = f"{want}: {self._eng.error}"
                # спускаемся по списку начиная СТРОГО ниже выбранного, чтобы
                # не подсунуть то же самое и не зациклиться
                start = (self.FALLBACK.index(want) + 1
                         if want in self.FALLBACK else 0)
                for alt in self.FALLBACK[start:]:
                    if alt == want or alt not in ENGINES:
                        continue
                    e = make(alt)
                    if e.ok:
                        self._eng, self._name = e, alt
                        log.info("%s: вместо «%s» работает «%s»",
                                 self.label, want, alt)
                        break
        if self._eng.ok:
            self.blocked = "" if self._name == self.wanted else self.blocked
        return self._eng

    def process(self, pcm16: np.ndarray) -> np.ndarray:
        """int16 @16кГц -> int16 @16кГц. Возвращает ВХОД без изменений при
        любой ошибке: шумодав не имеет права оставить Сайку без слуха."""
        eng = self._ensure()
        if eng.name == "off" or not eng.ok:
            return pcm16
        try:
            t0 = time.monotonic()
            x = np.asarray(pcm16, np.float32) / 32768.0
            with self._lock:
                y = eng.process(x)
            dt = (time.monotonic() - t0) * 1000.0
            self.ms = dt if self.frames == 0 else self.ms * 0.9 + dt * 0.1
            self.frames += 1
            try:
                a = float(np.sqrt(np.mean(x ** 2)))
                b = float(np.sqrt(np.mean(np.asarray(y, np.float32) ** 2)))
                if a > 1e-5:
                    d = 20.0 * np.log10(max(b, 1e-9) / a)
                    self.cut_db = round(self.cut_db * 0.95 + d * 0.05, 2)
            except Exception:
                pass
            if len(y) == 0:
                return pcm16
            if len(y) < len(x):          # у поточных движков есть разгон
                y = np.pad(y, (len(x) - len(y), 0))
            return np.clip(y[-len(x):] * 32768.0, -32768, 32767).astype(np.int16)
        except Exception as e:
            log.warning("Шумодав споткнулся (%s) — пропускаю звук как есть", e)
            eng.ok = False
            eng.error = str(e)[:160]
            return pcm16

    def process_whole(self, pcm16: np.ndarray) -> np.ndarray:
        """ЦЕЛАЯ ФРАЗА, а не кусок потока (2026-08-15).

        Отличий от process() два, и оба существенные:
        1. движок получает сегмент ЦЕЛИКОМ — нестационарной оценке шума
           наконец есть с чем работать, у неё в руках и речь, и тишина
           вокруг неё. Ради этого второй проход и заведён;
        2. никакого дополнения нулями слева: у сегмента нет «разгона», и
           если движок вернул короче — это его беда, берём вход как есть.
           В потоке левый паддинг спасает непрерывность, здесь он вставил
           бы тишину в начало фразы, то есть съел бы первое слово.

        Потоковые движки перед фразой сбрасываются: их внутренний хвост
        принадлежит предыдущему куску и к этой фразе отношения не имеет."""
        eng = self._ensure()
        if eng.name == "off" or not eng.ok:
            return pcm16
        try:
            x = np.asarray(pcm16, np.float32) / 32768.0
            with self._lock:
                try:
                    eng.reset()
                except Exception:
                    pass
                y = np.asarray(eng.process(x), np.float32)
            if len(y) < len(x) * 0.8:
                # движок отдал заметно меньше, чем взял (разгон окна,
                # внутренняя задержка) — честнее вернуть исходную фразу,
                # чем обрезанную: обрезанное начало это потерянное слово
                log.debug("%s: вернул %d из %d сэмплов — беру фразу как есть",
                          self.label, len(y), len(x))
                return pcm16
            if len(y) < len(x):
                # спектральный движок держит одно окно (32мс) в хвосте.
                # Дописываем недостающее ИЗ ОРИГИНАЛА, а не нулями: на конце
                # фразы живёт последний согласный, и тишина вместо него —
                # это съеденное слово, ровно то, что мы тут и чиним.
                y = np.concatenate([y, x[len(y):]])
            self.frames += 1
            try:
                a = float(np.sqrt(np.mean(x ** 2)))
                b = float(np.sqrt(np.mean(y ** 2)))
                if a > 1e-5:
                    d = 20.0 * np.log10(max(b, 1e-9) / a)
                    self.cut_db = round(self.cut_db * 0.8 + d * 0.2, 2)
            except Exception:
                pass
            return np.clip(y[:len(x)] * 32768.0, -32768, 32767).astype(np.int16)
        except Exception as e:
            log.warning("%s споткнулся на фразе (%s) — беру звук как есть",
                        self.label, e)
            eng.ok = False
            eng.error = str(e)[:160]
            return pcm16

    def profile(self, bands: int = 40):
        """Выученный спектр шума для интерфейса: bands полос, 0..1.

        Это и есть ответ на «а он вообще учится?». Видно ГОРБЫ — гул кулера
        внизу, шипение вверху, наводка 50Гц узким пиком — и видно, что при
        смене комнаты картинка переезжает."""
        eng = self._ensure()
        pr = eng.profile() if hasattr(eng, "profile") else None
        if not pr or pr[0] is None:
            return {"bands": [], "learned": 0, "hz": []}
        noise, learned = pr
        n = np.asarray(noise, np.float32)
        # логарифм по частоте: шум комнаты живёт внизу, линейная шкала
        # отдала бы ему одну десятую картинки
        lo, hi = 1, len(n) - 1
        edges = np.unique(np.round(
            lo * np.power(hi / lo, np.linspace(0, 1, bands + 1))).astype(int))
        vals, hz = [], []
        for i in range(len(edges) - 1):
            a, b = edges[i], max(edges[i] + 1, edges[i + 1])
            vals.append(float(np.mean(n[a:b])))
            hz.append(int((a + b) / 2 * SR / NFFT))
        v = np.asarray(vals, np.float32)
        db = 20 * np.log10(np.maximum(v, 1e-9))
        top = float(db.max()) if len(db) else 0.0
        out = np.clip((db - (top - 45.0)) / 45.0, 0.0, 1.0)   # окно 45 дБ
        return {"bands": [round(float(x), 3) for x in out],
                "learned": int(learned), "hz": hz}

    def relearn(self):
        """Забыть профиль и начать слушать комнату заново."""
        with self._lock:
            if self._eng is not None:
                self._eng.reset()
        return self.status()

    def set_engine(self, name: str):
        if name not in ENGINES:
            return {"ok": False, "error": "неизвестный движок"}
        CFG.set(self.key, name)
        with self._lock:
            self._eng = None
            self._name = ""
            self._want_seen = None
            self.blocked = ""
            self.cut_db = 0.0
        self._ensure()
        return self.status()

    def status(self):
        eng = self._ensure()
        return {
            "engine": self._name,
            "wanted": self.wanted or self._name,
            "blocked": self.blocked,
            "cut_db": round(self.cut_db, 1),
            "engines": list(ENGINES),
            "ok": bool(eng.ok),
            "error": eng.error,
            "needs": eng.needs,
            "ms_per_100ms": round(self.ms, 2),
            "frames": self.frames,
            "params": {
                "over": CFG.get("denoise.over", 1.8),
                "floor": CFG.get("denoise.floor", 0.08),
                "gate_ratio": CFG.get("denoise.gate_ratio", 4.0),
                "gate_min": CFG.get("denoise.gate_min", 0.004),
            },
        }


DENOISE = Denoiser()

# ВТОРОЙ ПРОХОД — НА ФРАЗЕ, РЯДОМ С ПЕРВЫМ, А НЕ ВМЕСТО НЕГО (2026-08-15).
# Потоковый шумодав остаётся ровно таким, каким был: он кормит отпечаток
# голоса, VAD и уши, и трогать его нельзя. А перед самим распознаванием
# добавлен отдельный, необязательный проход по СОБРАННОЙ фразе — там дорогие
# и точные движки (noisereduce, deepfilter) работают так, как задуманы их
# авторами, и стоят они раз в фразу, а не сто раз в секунду.
# По умолчанию «off»: пока не измерено стендом (server/hear_bench.py), что
# он помогает распознаванию, включать его нечестно.
SEGMENT = Denoiser(key="denoise.segment_engine", label="Шумодав фразы")
