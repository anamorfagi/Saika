"""STT-менеджер: VAD-сегментация, выбор движка, автофоллбэк при поломке.

Браузер шлёт PCM int16 16kHz. Менеджер:
- для streaming-движков (vosk, tone) — кормит чанки напрямую
- для buffered (whisper'ы, gigaam) — режет речь по тишине (RMS VAD) и
  транскрибирует сегмент целиком
Если движок бросил исключение — помечается unhealthy, берётся следующий
из fallback_order, а «доктор» в фоне пытается починить сломанный.
"""
import logging
import threading
import time

import numpy as np

from anamorf.config import CFG
from anamorf.stt.engines import ALL_ENGINES
from anamorf import diagnostics

log = logging.getLogger("saika.stt")

# ---------------- фильтр whisper-галлюцинаций (2026-07-25) ----------------
# Whisper-семейство (особенно whispercpp/medium на CPU) на тишине, дыхании
# и шуме уверенно «слышит» типовые фразы из своих обучающих субтитров:
# «Смотрите на наш канал!», «Спасибо за внимание», «*смех*», «Продолжение
# следует» и т.п. Сайка отвечала на них как на реальную речь — реальный
# эпизод в чате 2026-07-25 13:04. Фильтруем ДО отправки в диалог; список
# расширяем в config -> stt.junk_phrases.
# ШТАМПЫ ИЗ СУБТИТРОВ — то, что Whisper выдаёт на тишину. Список не
# выдуман: это самые частые концовки русских ютуб-роликов, на которых его
# учили. Пополнен 2026-07-29 по живому улову владельца («Спасибо»,
# «Смотрите продолжение в следующей серии» на шорох).
_JUNK_DEFAULT = [
    "смотрите на наш канал", "подписывайтесь на канал", "подпишись на канал",
    "спасибо за внимание", "спасибо за просмотр", "до новых встреч",
    "продолжение следует", "субтитры сделал", "субтитры создавал",
    "редактор субтитров", "корректор", "добро пожаловать на канал",
    "ставьте лайки", "с вами был", "всем пока",
    "смотрите продолжение", "в следующей серии", "продолжение в следующей",
    "смотрите продолжение в следующей серии",
    "спасибо за просмотр видео", "не забудьте подписаться",
    "ставьте лайк", "нажмите на колокольчик", "до встречи в следующем",
    "перевод и озвучка", "субтитры и перевод",
]

# ОДИНОКОЕ «СПАСИБО» И ЕМУ ПОДОБНЫЕ. Отдельно от штампов, потому что
# правило другое: фраза должна совпасть ЦЕЛИКОМ. «Спасибо» посреди
# разговора — нормальное слово, а «Спасибо.» отдельной репликой на шорох —
# самая частая галлюцинация Whisper. Точность здесь важнее полноты: одно
# потерянное настоящее «спасибо» дешевле, чем ежедневный мусор в памяти.
_JUNK_EXACT = [
    "спасибо", "спасибо.", "спасибо!", "продолжение следует",
    "субтитры", "музыка", "аплодисменты", "смех", "тишина",
    "ммм", "угу", "апчхи",
]


def _is_junk(text: str) -> bool:
    low = (text or "").lower().strip(" .,!?…*«»\"'-")
    if not low:
        return True
    # реплики целиком в звёздочках/скобках — «*смех*», «(музыка)»
    raw = (text or "").strip()
    if raw and raw[0] in "*([" and raw[-1] in "*)]":
        return True
    # точное совпадение — только для движков, которые этим болеют
    if low in [x.strip(" .,!?…") for x in _JUNK_EXACT]:
        return True
    junk = CFG.get("stt.junk_phrases", []) or []
    for phrase in list(junk) + _JUNK_DEFAULT:
        p = str(phrase).lower().strip()
        # галлюцинация = фраза-штамп и почти ничего кроме неё
        if p and p in low and len(low) <= len(p) + 12:
            return True
    return False


class VadSegmenter:
    """Энергетический VAD с адаптацией под шумный микрофон (2026-07-23).

    Микрофон без аудиокарты/фантомного питания даёт постоянный шумовой фон,
    и жёсткий порог из конфига либо режет тихий голос, либо ловит помехи.
    Три доработки:
    - АДАПТИВНЫЙ ПОРОГ: следим за шумовым полом (EMA RMS вне речи), порог =
      max(конфигный, пол*2.5 + запас). Конфигный rms_threshold — это МИНИМУМ,
      вверх порог подстраивается сам.
    - ГИСТЕРЕЗИС: войти в речь — выше порога, выйти — ниже 0.6*порога.
      Дрожание уровня на границе не рвёт фразу на куски.
    - ПРЕДРОЛЛ: кольцевой буфер ~240мс ДО срабатывания порога уходит в
      сегмент — начало первого слова больше не съедается (тихая атака
      «с», «п», «э-э» раньше не долетала до распознавания)."""

    def __init__(self):
        vad = CFG.get("stt.vad", {})
        self.threshold = vad.get("rms_threshold", 0.012)
        self._silence_ms = vad.get("silence_ms", 700)
        self._min_speech_ms = vad.get("min_speech_ms", 300)
        # ПРЕДЕЛ КУСКА — 12с, а не 25 (2026-07-29, разбор рабочего дня
        # владельца). Разговор ОДНОГО человека сам режется паузами, и предел
        # не срабатывает почти никогда. А в комнате, где говорят несколько,
        # пауз нет вовсе: сегмент дорастает до предела, GigaAM видит кусок
        # длиннее двадцати секунд, лезет в longform — и в логе появляются
        # «распознала за 17.7с», «20.1с», «23.1с». Всё это время очередь
        # копится, а текст на экране стоит. Двенадцать секунд: longform не
        # трогаем никогда, задержка сверху ограничена, а фраза рвётся редко —
        # пауза в 700мс между предложениями всё-таки случается.
        self._max_segment_s = vad.get("max_segment_s", 12)
        self.preroll_ms = vad.get("preroll_ms", 240)
        self.adaptive = vad.get("adaptive", True)
        self.sr = CFG.get("stt.sample_rate", 16000)
        self.noise_floor = 0.0     # EMA шумового пола (живёт через reset)
        # чем закончился прошлый кусок: "pause" — человек сам замолчал,
        # "length" — упёрлись в потолок и разрезали посреди мысли
        self.last_cut = ""
        self.reset()

    # ═══ РУЧКИ НАРЕЗКИ ЖИВЫЕ, А НЕ СЛЕПОК ПРИ РОЖДЕНИИ (2026-08-31) ═══
    #
    # Две беды разом, обе поймал владелец по своему же скриншоту: фразы
    # шли по 15-16 секунд, движок отставал на 23 секунды, хотя потолок
    # стоял 10.
    #
    # Первая: значения читались ОДИН РАЗ в __init__. Сегментатор живёт
    # всё время работы, значит любая правка ручки доезжала до него
    # только после переподключения — то есть на словах применялась, а на
    # деле нет. Ровно та же ловушка, что была с порогом склейки голосов.
    #
    # Вторая: панель и файл-канал кладут числа СТРОКАМИ ('900'), а тут
    # они сравниваются с числами. Python на этом бросает TypeError,
    # исключение гасится выше по стеку, и нарезка молча уходит в
    # запасное поведение. Снаружи это выглядит как «настройка не
    # работает», без единой строки в журнале.
    #
    # Поэтому ручки стали свойствами: читаем свежее значение и всегда
    # приводим к числу, а не надеемся, что его положили правильным.
    @staticmethod
    def _num(v, d):
        try:
            return type(d)(v)
        except (TypeError, ValueError):
            return d

    def _knob(self, name, own, d):
        v = CFG.get("stt.vad." + name, None)
        if v is None:
            v = own
        return self._num(v, d)

    def __live_after__(self):
        """Достроить себя после живой правки кода (2026-08-31).

        Экземпляр переживает правку вместе с состоянием — это правильно,
        но полей, появившихся В ЭТОЙ правке, у него нет. Здесь ровно так
        и вышло: ручки стали свойствами `_silence_ms` и прочими, а живой
        сегментатор помнил старые имена. Свойство лезло за несуществующим
        полем, падало, и нарезка вставала — при живом звуке ноль фраз."""
        for name, d in (("silence_ms", 700), ("min_speech_ms", 300),
                        ("max_segment_s", 12)):
            if not hasattr(self, "_" + name):
                setattr(self, "_" + name,
                        self.__dict__.pop(name, None) or d)

    # СЕТТЕРЫ ОБЯЗАТЕЛЬНЫ. Режим наблюдения (кино, звук с компьютера)
    # переставляет эти ручки прямо присваиванием — а свойство без
    # сеттера на присваивание бросает AttributeError. Ошибка ушла в
    # общий except, нарезка встала, и прогон дал РОВНО НОЛЬ фраз при
    # живом звуке: черновик работал, а фраз не было ни одной.
    @property
    def silence_ms(self):
        return self._knob("silence_ms",
                          getattr(self, "_silence_ms", 700), 700)

    @silence_ms.setter
    def silence_ms(self, v):
        self._silence_ms = self._num(v, 700)

    @property
    def min_speech_ms(self):
        return self._knob("min_speech_ms",
                          getattr(self, "_min_speech_ms", 300), 300)

    @min_speech_ms.setter
    def min_speech_ms(self, v):
        self._min_speech_ms = self._num(v, 300)

    @property
    def max_segment_s(self):
        return self._knob("max_segment_s",
                          getattr(self, "_max_segment_s", 12), 12)

    @max_segment_s.setter
    def max_segment_s(self, v):
        self._max_segment_s = self._num(v, 12)

    def reset(self):
        self._nf_warm, self._nf_n = None, 0   # разогрев замера фона заново
        self.buffer = []
        self.preroll = []          # последние чанки ДО начала речи
        self.preroll_samples = 0
        self.in_speech = False
        self.silence_samples = 0
        self.speech_samples = 0

    def _eff_threshold(self):
        # КОГДА РЕШАЕТ НЕЙРОНКА, ПОРОГ НЕ РАСТЁТ (2026-08-15). Адаптация
        # придумана для энергетического VAD: шумно — поднимай планку. При
        # нейронной нарезке это только мешает — планка задирается от игры
        # фоном и душит тихую речь на входе в конвейер.
        try:
            from anamorf.stt import neuro_vad
            if neuro_vad.enabled() and neuro_vad.STATE.get("ready"):
                return self.threshold
        except Exception:
            pass
        if not self.adaptive:
            return self.threshold
        # пол шума * 2.5 + небольшой запас; конфигный порог — нижняя планка.
        # ПОТОЛОК ОБЯЗАТЕЛЕН: даже если фон намерили неверно, адаптация не
        # имеет права задрать планку настолько, чтобы проглотить обычную
        # речь. Четыре базовых порога — это уже очень шумная комната.
        adaptive = self.noise_floor * 2.5 + 0.004
        return max(self.threshold, min(adaptive, self.threshold * 4.0))

    # ═══ САМОПИСЕЦ НАРЕЗКИ (2026-09-01) ═══
    # Владелец: «сказал „таак, проверка, как ты пишешь" — написал только
    # вторую часть», «первые фразы ролика вообще не писались». Гадать,
    # где именно теряется начало, мы уже пробовали — и гипотеза не
    # подтвердилась стендом. Поэтому пишем правду покадрово: громкость,
    # решение нейронки, действующий порог и что с кадром сделали.
    # Кольцо на 600 кадров — это минута при кадре 100мс.
    TRACE = []
    TRACE_MAX = 600

    def _trace(self, rms, thr, prob, is_voice, why):
        try:
            if not CFG.get("stt.vad.trace", False):
                return
            VadSegmenter.TRACE.append({
                "t": round(time.time(), 2), "rms": round(rms, 5),
                "thr": round(thr, 5),
                "p": None if prob is None else round(prob, 3),
                "voice": bool(is_voice), "in": bool(self.in_speech),
                "why": why})
            del VadSegmenter.TRACE[:-VadSegmenter.TRACE_MAX]
        except Exception:
            pass

    def push(self, pcm16: np.ndarray):
        """Вернёт np.int16-сегмент когда фраза закончилась, иначе None."""
        rms = float(np.sqrt(np.mean((pcm16.astype(np.float32) / 32768.0) ** 2)))
        thr = self._eff_threshold()
        # гистерезис: подняться над порогом сложнее, чем удержаться
        is_voice = rms > (thr * 0.6 if self.in_speech else thr)
        _why = "по громкости" 
        # ═══ НЕЙРОННОЕ РЕШЕНИЕ «РЕЧЬ ЛИ ЭТО» (2026-08-15) ═══
        # Порог по громкости не отличает слог от щелчка клавиши — отсюда
        # фантомные фразы на печатание и каша в движке. Когда silero-vad
        # готов, решение принимает он: вход в речь — вероятность выше
        # порога, удержание — выше пониженного (тот же гистерезис). Пока
        # нейронка грузится или упала — работаем по громкости, как всегда.
        # Тонкость: совсем тихий звук (ниже трети порога) нейронке даже не
        # показываем — она обучена находить речь и в шёпоте, но комнатное
        # эхо телевизора за стеной нам фразами резать не нужно.
        self.speech_prob = None
        try:
            from anamorf.stt import neuro_vad
            # ═══ ВОРОТА ПЕРЕД НЕЙРОНКОЙ — АБСОЛЮТНЫЕ, А НЕ ОТ ПОРОГА ═══
            # (2026-08-15, живой прокол, найден по панели владельца:
            # «уровень 82 / порог 41», и половина фраз не слышна вовсе.
            # Ворота стояли на `rms > thr * 0.3`, то есть от АДАПТИВНОГО
            # порога — а он задирается от игры и битбокса фоном. При
            # thr=0.041 нейронку не спрашивали ни о чём тише 0.012, и вся
            # тихая речь умирала ДО того, как её слышала нейронка. Смысл
            # апгрейда был ровно обратный: решает нейронка, а не громкость.
            # Ворота остаются только чтобы не гонять модель на мёртвой
            # тишине — абсолютный пол, к порогу не привязан.)
            if neuro_vad.enabled():
                gate = float(CFG.get("stt.vad.neuro_gate_rms", 0.0025))
                if rms > gate:
                    p = neuro_vad.prob(pcm16)
                    if p is not None:
                        self.speech_prob = p
                        on = float(CFG.get("stt.vad.neuro_on", 0.5))
                        off = float(CFG.get("stt.vad.neuro_off", 0.35))
                        # ═══ ГРОМКОСТЬ И НЕЙРОНКА РЕШАЮТ ВМЕСТЕ ═══
                        # (2026-09-01, по замеру самописца)
                        #
                        # Самописец показал ровно, где терялось начало
                        # фразы: кадры rms 0.069 и 0.048 — то есть в
                        # десять раз громче порога — приходили с
                        # уверенностью 0.305 и 0.337 при пороге входа
                        # 0.42, и их не пускали. Это не тихая речь.
                        # Просто атака слова — то место, где silero
                        # менее всего уверена: гласная ещё не
                        # развернулась. Владелец видел это как «сказал
                        # „таак, проверка" — написал только вторую
                        # часть» и «первые фразы ролика не писались».
                        #
                        # Правило теперь такое: входим в речь либо по
                        # уверенности, либо когда нейронка колеблется,
                        # НО звук заведомо громкий. Тихий сомнительный
                        # кадр по-прежнему не пройдёт — а значит шум
                        # словами не станет: в том же замере ни один
                        # кадр не был пропущен при низкой вероятности.
                        if self.in_speech:
                            is_voice = p >= off
                            _why = "нейронка (держим)"
                        elif p >= on:
                            is_voice = True
                            _why = "нейронка"
                        else:
                            _loud = float(CFG.get(
                                "stt.vad.loud_enter_x", 4.0) or 4.0)
                            _soft = float(CFG.get(
                                "stt.vad.neuro_on_loud", 0.0) or 0.0) \
                                or on * 0.6
                            is_voice = (p >= _soft and rms >= thr * _loud)
                            _why = ("громко+нейронка" if is_voice
                                    else "нейронка")
                else:
                    # мёртвая тишина: нейронку не будим
                    self.speech_prob = 0.0
                    is_voice = False
                    _why = "тише шлагбаума %.4f" % gate
        except Exception:
            pass
        self._trace(rms, thr, getattr(self, "speech_prob", None),
                    is_voice, _why)

        if not self.in_speech and not is_voice:
            # обновляем шумовой пол ТОЛЬКО на чистой тишине (медленная EMA);
            # чанк, взявший порог, в пол не считаем — иначе тихий голос
            # у границы постепенно задирал бы порог сам себе
            # ═══ ПЕРВЫЙ КАДР НЕ НАЗНАЧАЕТ ФОН (2026-09-01) ═══
            #
            # Было: `... if self.noise_floor > 0 else rms` — то есть самый
            # первый кадр целиком объявлялся уровнем шума. Если в этот
            # момент уже звучала речь или только что заиграл ролик, фоном
            # объявлялась САМА РЕЧЬ, порог прыгал на «фон × 2.5» — выше
            # говорящего — и глох весь вход. Опускался он потом медленно и
            # только на тишине.
            #
            # Владелец видел это дважды и описал точнее любого лога:
            # «первые фразы ролика вообще не писались», «сказал „таак,
            # проверка, как ты пишешь" — написал только вторую часть».
            #
            # Теперь фон набирается по МИНИМУМУ первой секунды, а не по
            # первому кадру: громкое начало больше не может назначить сам
            # себя тишиной.
            if self.noise_floor <= 0:
                _w = getattr(self, "_nf_warm", None)
                self._nf_warm = rms if _w is None else min(_w, rms)
                self._nf_n = getattr(self, "_nf_n", 0) + 1
                if self._nf_n >= 10:            # ~1с по кадрам 100мс
                    self.noise_floor = self._nf_warm
            else:
                self.noise_floor = 0.95 * self.noise_floor + 0.05 * rms
            # копим предролл (кольцо ~preroll_ms)
            self.preroll.append(pcm16)
            self.preroll_samples += len(pcm16)
            cap = int(self.sr * self.preroll_ms / 1000)
            while self.preroll_samples > cap and len(self.preroll) > 1:
                self.preroll_samples -= len(self.preroll.pop(0))

        if is_voice:
            if not self.in_speech:
                # старт речи: предролл — в начало сегмента
                self.buffer = list(self.preroll)
                self.preroll, self.preroll_samples = [], 0
            self.in_speech = True
            self.silence_samples = 0
            self.speech_samples += len(pcm16)
        elif self.in_speech:
            self.silence_samples += len(pcm16)

        if self.in_speech:
            self.buffer.append(pcm16)

        # ═══ ГРАНИЦА ПО ПАУЗЕ, А НЕ ПО СЕКУНДОМЕРУ (2026-08-16) ═══
        # Владелец, дословно: «можешь деление делать не по времени, а
        # детектить предложения». Дословно предложения слышит только текст
        # (там знаки препинания), но ЗВУК умеет главное: не рвать речь
        # там, где человек не молчал.
        #
        # Было: молчание 420мс закрывает кусок, а если его не случилось —
        # жёсткий нож ровно на потолке (8с в прослушке). Стример дышит
        # между фразами 150-250мс, до 420 не дотягивает никогда — и нож
        # падал по секундомеру, всегда посреди слова.
        #
        # Стало: чем длиннее кусок, тем меньшей паузы хватает, чтобы его
        # закрыть. От soft_cut_from (половина потолка) требование плавно
        # съезжает с silence_ms до soft_gap_ms. Человек, говорящий одним
        # духом, всё равно упрётся в потолок — но упрётся он ПОСЛЕ того,
        # как будут перебраны все настоящие паузы, и нож придётся на самую
        # глубокую из них, а не на случайную миллисекунду.
        need_ms = self.silence_ms
        try:
            soft_from = self.max_segment_s * float(
                CFG.get("stt.vad.soft_cut_from", 0.5))
            soft_gap = float(CFG.get("stt.vad.soft_gap_ms", 100))
            spoken_s = self.speech_samples / float(self.sr)
            if self.in_speech and spoken_s > soft_from and soft_gap < need_ms:
                frac = min(1.0, (spoken_s - soft_from)
                           / max(0.1, self.max_segment_s - soft_from))
                need_ms = self.silence_ms + (soft_gap - self.silence_ms) * frac
        except Exception:
            need_ms = self.silence_ms
        end_by_silence = (self.in_speech and
                          self.silence_samples >= self.sr * need_ms / 1000)
        end_by_length = (self.in_speech and
                         self.speech_samples >= self.sr * self.max_segment_s)

        if end_by_silence or end_by_length:
            segment = np.concatenate(self.buffer) if self.buffer else None
            long_enough = self.speech_samples >= self.sr * self.min_speech_ms / 1000
            # ПРИЧИНА РЕЗА едет наружу: по ней склеиваются оборванные
            # посреди мысли куски (см. GLUE в main.py). Три случая:
            #   pause  — человек домолчал полные silence_ms: мысль кончена;
            #   short  — закрыли по укороченной (рампой) паузе: он просто
            #            вдохнул между словами, мысль продолжается;
            #   length — нож по потолку, оборвано где попало.
            full_gap = self.sr * self.silence_ms / 1000
            if end_by_silence and self.silence_samples >= full_gap:
                self.last_cut = "pause"
            elif end_by_silence:
                self.last_cut = "short"
            else:
                self.last_cut = "length"
            self.reset()
            try:
                from anamorf.stt import neuro_vad
                neuro_vad.reset()   # хвост прошлой фразы не влияет на новую
            except Exception:
                pass
            if segment is not None and long_enough:
                return segment
        return None


class STTManager:
    def __init__(self, on_problem=None):
        self.instances = {}
        self.health = {name: "unknown" for name in ALL_ENGINES}
        self.last_error = {}  # name -> человеческая причина последней ошибки (UI)
        self.last_diag = {}   # name -> полный разбор diagnostics.classify
        self.vad = VadSegmenter()
        self.lock = threading.Lock()
        self.on_problem = on_problem  # callback(component, error, action)
        # 2026-07-23: раньше _notify звался НА КАЖДЫЙ чанк, пока основной
        # движок сломан (комментарий в process_chunk обещал "сообщим один
        # раз", а по факту — нет) — при потоковом STT это десятки вызовов в
        # секунду, а каждый тянет за собой полную перезапись devboard.json
        # (note_problem -> _save) и рассылку по всем websocket — забивало
        # лог ("оч тыбсто строки летели") и грузило диск/память на ровном
        # месте. Помним, на кого уже уведомили, и не повторяем, пока не
        # вернулись на основной (тогда сброс — следующая поломка уведомит
        # заново).
        self._notified_fallback = None

    # ---------- выбор движка ----------
    # БЕЗ СЛУХА (2026-07-27, просьба владельца: быстрые тестовые пуски).
    # Само состояние «слух выключен» существовало и раньше (см. set_engine и
    # process_chunk ниже), но выбрать его в интерфейсе было НЕЛЬЗЯ — пункта
    # в списке движков не было, он появлялся только после жёсткой разгрузки.
    # Теперь это обычный пункт: GigaAM и Whisper — это гигабайты VRAM и
    # секунды прогрева, при отладке мозгов они не нужны.
    OFF = ("", "none", "off")

    @property
    def current_name(self):
        return CFG.get("stt.engine", "off")

    def set_engine(self, name):
        if name in self.OFF:              # «ничего не выбрано» — слух выкл
            CFG.set("stt.engine", "off")
            self.vad.reset()
            return
        if name not in ALL_ENGINES:
            raise ValueError(f"Нет такого движка: {name}")
        prev = self.current_name
        CFG.set("stt.engine", name)
        self.vad.reset()
        # РУЧНОЙ ВЫБОР = НОВЫЙ ШАНС (2026-07-25): раньше клик по сломанному
        # движку внешне «ничего не делал» — health='broken' молча выкидывал
        # его из _healthy_chain, и слух продолжал жить на запасном без
        # какого-либо объяснения. Человек кликнул осознанно — сбрасываем
        # чёрную метку и греем движок в фоне; если он всё ещё мёртв, первая
        # же фраза честно пометит его заново и сообщит причину.
        if self.health.get(name) == "broken":
            self.health[name] = "unknown"
            self.last_error.pop(name, None)
            self.last_diag.pop(name, None)
        self._notified_fallback = None
        threading.Thread(target=self._warm, args=(name, prev),
                         daemon=True).start()

    def _warm(self, name, prev=None):
        """Фоновый прогрев выбранного движка + АВТОВЫГРУЗКА прежнего
        (2026-07-25, просьба владельца: не держать два слуха в памяти —
        каждый Whisper/GigaAM это гигабайты ОЗУ/VRAM). Ошибки прогрева
        уйдут обычным путём через load_engine."""
        if prev and prev != name:
            try:
                with self.lock:   # не выдёргивать модель посреди транскрипции
                    self.unload_engine(prev)
                log.info("STT: прежний движок %s выгружен из памяти "
                         "(смена на %s)", prev, name)
            except Exception as e:
                log.warning("STT: не выгрузился прежний движок %s: %s",
                            prev, e)
        try:
            self.load_engine(name)
        except Exception as e:
            log.info("STT %s: прогрев после выбора не удался: %s", name, e)

    def _get(self, name):
        if name not in self.instances:
            # загрузка движка — секунды и торчёвые импорты; под общим
            # замком, чтобы не столкнуться с параллельной загрузкой TTS
            # или silero_te (см. anamorf/torch_gate.py — «Duplicate
            # registration» из живого лога 2026-07-28)
            from anamorf.torch_gate import TORCH_GATE
            with TORCH_GATE:
                if name not in self.instances:
                    self.instances[name] = ALL_ENGINES[name]()
        return self.instances[name]

    def _healthy_chain(self):
        order = CFG.get("stt.fallback_order", list(ALL_ENGINES))
        current = self.current_name
        chain = [current] + [n for n in order if n != current]
        return [n for n in chain if self.health.get(n) != "broken"]

    # ---------- пайплайн ----------
    # РАЗДЕЛЕНИЕ НАРЕЗКИ И РАСПОЗНАВАНИЯ (2026-07-28).
    #
    # process_chunk делает две работы разной цены в одном вызове: дешёвую
    # (VAD решает, кончилась ли фраза — микросекунды) и дорогую (движок
    # думает над готовым куском — больше секунды). Пока они вместе, поток
    # слуха на каждой фразе замирает, а звук в это время идёт: очередь
    # набирается, и дальше одно из двух — либо ронять звук и терять слова,
    # либо копить и отставать. Владелец увидел ровно это: «уронила 3258
    # чанков» и «транскриб отстал на 20 секунд». Это не настройка, это
    # устройство: одна очередь на две работы с разницей в тысячу раз.
    #
    # Поэтому здесь появились два отдельных входа. cut() зовётся на каждый
    # чанк и стоит копейки, transcribe_segment() — только на готовую фразу,
    # в СВОЁМ потоке (см. anamorf/main.py). Горячий цикл больше не ждёт
    # движок, ронять звук не нужно, а текст просто приходит чуть позже.
    #
    # process_chunk остался нетронутым: им пользуются потоковые движки
    # (Vosk), которым нарезка не нужна вовсе.
    def cut(self, pcm16: np.ndarray):
        """Только нарезка. -> готовый сегмент np.int16 или None."""
        if self.current_name in self.OFF:
            return None
        return self.vad.push(pcm16)

    def is_streaming(self) -> bool:
        if self.current_name in self.OFF:
            return False
        try:
            return self._get(self.current_name).kind == "streaming"
        except Exception:
            return False

    def peek(self, min_s: float = 2.0, max_s: float = 14.0):
        """Снимок НЕЗАКОНЧЕННОЙ фразы для скользящей нормализации (2026-07-28).

        Пока человек говорит, VAD копит буфер и молчит. Обычный путь ждёт
        конца фразы — отсюда «текст приходит кусками». Снимок позволяет
        точному движку перечитывать фразу ПО ХОДУ: каждые пару секунд весь
        накопленный кусок распознаётся заново и подменяет черновик уже
        правильными словами. Ровно так это ощущается у больших сервисов:
        слова сразу, красота догоняет.

        Хвост длиннее max_s не отдаём: перечитывать полминуты каждые две
        секунды — квадратичная цена, а начало фразы всё равно уже показано."""
        if self.current_name in self.OFF:
            return None
        v = self.vad
        if not v.in_speech or not v.buffer:
            return None
        if v.speech_samples < v.sr * min_s:
            return None
        try:
            snap = np.concatenate(list(v.buffer))
            return snap[-int(v.sr * max_s):]
        except Exception:
            return None

    def transcribe_segment(self, segment: np.ndarray) -> list[dict]:
        """Распознать готовую фразу цепочкой движков. Может думать секунды —
        поэтому зовётся из отдельного потока, а не из потока слуха."""
        # ГРАБЛИ 2026-07-28, поймал владелец: «выгрузить всё» не сработало.
        # Разгрузка ставила движок в «none», но фразы, уже лежавшие в
        # очереди распознавания, шли сюда, здесь проверки «выключено» НЕ
        # БЫЛО — и запасная цепочка лениво поднимала GigaAM обратно.
        # Кнопка отрабатывала честно, а через секунду всё висело в памяти
        # снова. Проверка обязана быть в КАЖДОМ входе, а не только в
        # process_chunk.
        if self.current_name in self.OFF:
            return []
        if segment is None or not len(segment):
            return []
        sr = CFG.get("stt.sample_rate", 16000)
        # ═══ СНАЧАЛА ЯЗЫК, ПОТОМ ДВИЖОК (2026-09-01) ═══
        # Раньше кусок всегда шёл в GigaAM, а тот знает только русский:
        # «What's your name» превращалось в «Вот чя наив». Заметить это
        # по виду текста нельзя — слов ровно столько, сколько сказано.
        # Поэтому спрашиваем крошечный определитель ДО расшифровки и
        # отдаём кусок тому, кто этот язык знает. Не уверен — молчит, и
        # тогда работаем как раньше.
        _chain = list(self._healthy_chain())
        _lang, _lang_p = None, 0.0
        try:
            from anamorf.stt import langid as _lid
            _lang, _lang_p = _lid.detect(segment, sr)
            if _lang:
                _want = _lid.engine_for(_lang)
                if _want and _chain and _want != _chain[0]:
                    _chain = [_want] + [c for c in _chain if c != _want]
                    log.info("Слух: язык «%s» (%.0f%%) — отдаю движку %s",
                             _lang, _lang_p * 100, _want)
        except Exception as _le:
            log.debug("маршрут по языку: %s", _le)
        for name in _chain:
            try:
                with self.lock:
                    eng = self._get(name)
                    text = eng.transcribe(segment, sr)
                results = [{"text": text, "engine": name}] if text else []
                if results and _lang:
                    results[0]["lang"] = _lang
                    results[0]["lang_p"] = round(_lang_p, 2)
                # пословная уверенность, если движок её посчитал (whisper):
                # интерфейс подсветит слова, которые прозвучали нечётко
                _wrds = getattr(eng, "last_words", None)
                if results and _wrds:
                    results[0]["words"] = _wrds
                if name != self.current_name:
                    if self._notified_fallback != name:
                        self._notify(name)
                        self._notified_fallback = name
                else:
                    self._notified_fallback = None
                self.health[name] = "ok"
                results = self._second_opinion(results, segment, sr, name)
                return self._drop_junk(results)
            except Exception as e:
                self._mark_broken(name, e)
        return []

    # ═══ ВТОРОЕ МНЕНИЕ ПО ПОДОЗРЕНИЮ (2026-09-01) ═══
    #
    # Владелец сказал «How are you» — в ленте появилось «Ха.». Это не
    # ошибка распознавания, это чужой язык: GigaAM знает только русский
    # и честно укладывает английскую речь в русскую фонетику. Ни один
    # порог такого не лечит.
    #
    # Держать многоязычный whisper поднятым всегда — дорого: он съест
    # видеопамять, которой и так впритык. Поэтому спрашиваем его ТОЛЬКО
    # по подозрению: звучало долго, а на выходе горстка букв. У русской
    # речи плотность 2-6 слов в секунду; пол-слова в секунду означает,
    # что движок не понял язык.
    #
    # Whisper при language=None определяет язык сам и сразу
    # расшифровывает — один проход. Определённый язык кладём в реплику:
    # по нему интерфейс поставит метку, а маршрутизатор дальше решит,
    # кому отдавать следующие куски этого голоса.
    def _second_opinion(self, results, segment, sr, used):
        try:
            if not CFG.get("stt.multilang", True):
                return results
            if used == "faster_whisper":
                return results
            sec = len(segment) / float(sr or 16000)
            if sec < float(CFG.get("stt.multilang_min_s", 0.8) or 0.8):
                return results
            txt = (results[0].get("text") if results else "") or ""
            words = len([w for w in txt.split() if w.strip(".,!?…-")])
            dens = words / max(sec, 0.1)
            thr = float(CFG.get("stt.multilang_density", 1.0) or 1.0)
            if dens >= thr:
                return results          # похоже на нормальную русскую речь
            eng = self._get("faster_whisper")
            with self.lock:
                alt = eng.transcribe(segment, sr)
            if not alt or not alt.strip():
                return results
            lang = getattr(eng, "last_lang", None)
            lp = float(getattr(eng, "last_lang_p", 0.0) or 0.0)
            aw = len([w for w in alt.split() if w.strip(".,!?…-")])
            if aw <= words:
                return results          # лучше не стало — не трогаем
            log.info("Слух: «%s» звучало %.1fс, а слов %d — переспросила "
                     "многоязычным: «%s» (язык %s, уверенность %.0f%%)",
                     txt[:32], sec, words, alt[:48], lang or "?", lp * 100)
            out = [{"text": alt, "engine": "faster_whisper",
                    "lang": lang, "lang_p": round(lp, 2),
                    "was": txt, "was_engine": used}]
            _w = getattr(eng, "last_words", None)
            if _w:
                out[0]["words"] = _w
            return out
        except Exception as e:
            log.debug("второе мнение: %s", e)
            return results

    def process_chunk(self, pcm16: np.ndarray) -> list[dict]:
        """Вернёт [{'text':..., 'engine':...}] за готовые фразы."""
        # состояние «ничего не выбрано» (2026-07-25): после жёсткой разгрузки
        # слух ВЫКЛЮЧЕН совсем — без этого первая же фраза лениво подгружала
        # текущий движок обратно, и кнопка выглядела неработающей
        if self.current_name in self.OFF:
            return []
        sr = CFG.get("stt.sample_rate", 16000)
        results = []
        from anamorf import stage
        for name in self._healthy_chain():
            engine = self._get(name)
            try:
                # МЕТКИ ЧЁРНОГО ЯЩИКА (2026-08-14). Тут живут чужие
                # C-библиотеки (Vosk/Kaldi, torch у GigaAM), и обвал внутри
                # них питон не ловит вообще. Метка на диске — единственный
                # способ узнать, кто именно умер: файл пережил падение,
                # значит вышли не отсюда.
                if engine.kind == "streaming":
                    with stage.step(f"слух: {name}.feed"):
                        for text in engine.feed(pcm16, sr):
                            results.append({"text": text, "engine": name})
                else:
                    segment = self.vad.push(pcm16)
                    if segment is not None:
                        with self.lock, stage.step(f"слух: {name}.transcribe"):
                            text = engine.transcribe(segment, sr)
                        if text:
                            results.append({"text": text, "engine": name})
                if name != self.current_name:
                    # работаем на запасном — сообщим ОДИН раз за эпизод
                    # (не на каждый чанк, см. коммент в __init__)
                    if self._notified_fallback != name:
                        self._notify(name)
                        self._notified_fallback = name
                else:
                    self._notified_fallback = None
                self.health[name] = "ok"
                return self._drop_junk(results)
            except Exception as e:
                self._mark_broken(name, e)
        return self._drop_junk(results)

    @staticmethod
    def _drop_junk(results):
        kept = []
        for r in results:
            if _is_junk(r.get("text", "")):
                log.info("STT: отфильтрована галлюцинация %s: %r",
                         r.get("engine"), r.get("text"))
            else:
                kept.append(r)
        return kept

    def flush(self) -> list[dict]:
        name = self.current_name
        engine = self.instances.get(name)
        out = []
        if engine and engine.kind == "streaming":
            try:
                out = [{"text": t, "engine": name} for t in engine.flush()]
            except Exception as e:
                self._mark_broken(name, e)
        else:
            # добить недоговорённый сегмент из VAD
            if self.vad.buffer:
                segment = np.concatenate(self.vad.buffer)
                self.vad.reset()
                sr = CFG.get("stt.sample_rate", 16000)
                for n in self._healthy_chain():
                    try:
                        text = self._get(n).transcribe(segment, sr)
                        if text:
                            out.append({"text": text, "engine": n})
                        break
                    except Exception as e:
                        self._mark_broken(n, e)
        return self._drop_junk(out)

    # ---------- ручная загрузка/выгрузка (кнопки в UI) ----------
    def load_engine(self, name):
        if name not in ALL_ENGINES:
            raise ValueError(f"Нет такого движка: {name}")
        engine = self._get(name)
        try:
            engine.load()
            self.health[name] = "ok"
            self.last_error.pop(name, None)
            self.last_diag.pop(name, None)
        except Exception as e:
            self.health[name] = "broken"
            diag = diagnostics.classify("stt." + name, str(e))
            self.last_error[name] = diag["human"]
            self.last_diag[name] = diag
            if self.on_problem:
                self.on_problem("stt." + name, diag["human"], diag["action"], diag)
            raise

    def unload_engine(self, name):
        engine = self.instances.get(name)
        if engine:
            engine.unload()
        self.last_error.pop(name, None)
        if self.health.get(name) == "broken":
            self.health[name] = "unknown"

    # ---------- здоровье и самопочинка ----------
    def _mark_broken(self, name, error):
        self.health[name] = "broken"
        diag = diagnostics.classify("stt." + name, str(error))
        # в UI кладём человеческую причину, а не сырой стек-трейс
        self.last_error[name] = diag["human"]
        self.last_diag[name] = diag
        log.error("STT %s сломался [%s]: %s", name, diag["category"], error)
        if self.on_problem:
            self.on_problem("stt." + name, diag["human"], diag["action"], diag)
        threading.Thread(target=self._repair, args=(name, diag),
                         daemon=True).start()

    def _notify(self, active):
        if self.on_problem:
            self.on_problem("stt", f"основной движок недоступен",
                            f"работаю на {active}")

    def _repair(self, name, diag=None):
        """Фоновая попытка починить, с учётом категории проблемы:
        - network/space/offline — перезагрузка не поможет (нет сети/памяти),
          не долбим впустую: движок остаётся на запасном, ждём условий;
        - corrupt — сносим битый кэш, движок при следующей загрузке докачает
          (у gigaam снос встроен в engine.load, тут общий случай);
        - остальное — обычная попытка выгрузить/загрузить заново."""
        cat = (diag or {}).get("category", "unknown")
        if cat in ("loading", "network", "space", "offline"):
            # чинить нечего до восстановления условий — просто фиксируем причину
            log.info("STT %s: причина '%s' — жду условий, не переустанавливаю",
                     name, cat)
            return
        time.sleep(2)
        try:
            engine = self._get(name)
            engine.unload()
            engine.load()
            self.health[name] = "ok"
            self.last_error.pop(name, None)
            self.last_diag.pop(name, None)
            log.info("STT %s восстановлен", name)
            if self.on_problem:
                self.on_problem("stt." + name, "", "движок восстановлен")
        except Exception as e:
            d = diagnostics.classify("stt." + name, str(e))
            self.last_error[name] = d["human"]
            log.warning("STT %s: починка не удалась (%s)", name, e)
            # ЭСКАЛАЦИЯ (2026-07-25): шаблонная перезагрузка не помогла —
            # Беймакс не сдаётся, а зовёт консилиум (ai_consult, облачная
            # модель разбирает симптом + хвост лога и говорит, что делать).
            # У consult свой кулдаун и проверка ключа — вызов дешёвый.
            try:
                from anamorf import ai_consult
                from anamorf.main import broadcast_event
                ai_consult.consult_async(
                    f"STT-движок «{name}» не запускается, самопочинка не "
                    f"помогла. Ошибка: {e}", broadcast_event)
            except Exception as ce:
                log.debug("консилиум по stt.%s не позвался: %s", name, ce)

    def status(self):
        loaded = {}
        for name in ALL_ENGINES:
            eng = self.instances.get(name)
            try:
                loaded[name] = bool(eng and eng.is_loaded())
            except Exception:
                loaded[name] = False
        return {"current": self.current_name, "health": self.health,
                "engines": ["off"] + list(ALL_ENGINES), "loaded": loaded,
                "errors": self.last_error, "diag": self.last_diag}
