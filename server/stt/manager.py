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

from server.config import CFG
from server.stt.engines import ALL_ENGINES
from server import diagnostics

log = logging.getLogger("saika.stt")

# ---------------- фильтр whisper-галлюцинаций (2026-07-25) ----------------
# Whisper-семейство (особенно whispercpp/medium на CPU) на тишине, дыхании
# и шуме уверенно «слышит» типовые фразы из своих обучающих субтитров:
# «Смотрите на наш канал!», «Спасибо за внимание», «*смех*», «Продолжение
# следует» и т.п. Сайка отвечала на них как на реальную речь — реальный
# эпизод в чате 2026-07-25 13:04. Фильтруем ДО отправки в диалог; список
# расширяем в config -> stt.junk_phrases.
_JUNK_DEFAULT = [
    "смотрите на наш канал", "подписывайтесь на канал", "подпишись на канал",
    "спасибо за внимание", "спасибо за просмотр", "до новых встреч",
    "продолжение следует", "субтитры сделал", "субтитры создавал",
    "редактор субтитров", "корректор", "добро пожаловать на канал",
    "ставьте лайки", "с вами был", "всем пока",
]


def _is_junk(text: str) -> bool:
    low = (text or "").lower().strip(" .,!?…*«»\"'-")
    if not low:
        return True
    # реплики целиком в звёздочках/скобках — «*смех*», «(музыка)»
    raw = (text or "").strip()
    if raw and raw[0] in "*([" and raw[-1] in "*)]":
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
        self.silence_ms = vad.get("silence_ms", 700)
        self.min_speech_ms = vad.get("min_speech_ms", 300)
        # ПРЕДЕЛ КУСКА — 12с, а не 25 (2026-07-29, разбор рабочего дня
        # владельца). Разговор ОДНОГО человека сам режется паузами, и предел
        # не срабатывает почти никогда. А в комнате, где говорят несколько,
        # пауз нет вовсе: сегмент дорастает до предела, GigaAM видит кусок
        # длиннее двадцати секунд, лезет в longform — и в логе появляются
        # «распознала за 17.7с», «20.1с», «23.1с». Всё это время очередь
        # копится, а текст на экране стоит. Двенадцать секунд: longform не
        # трогаем никогда, задержка сверху ограничена, а фраза рвётся редко —
        # пауза в 700мс между предложениями всё-таки случается.
        self.max_segment_s = vad.get("max_segment_s", 12)
        self.preroll_ms = vad.get("preroll_ms", 240)
        self.adaptive = vad.get("adaptive", True)
        self.sr = CFG.get("stt.sample_rate", 16000)
        self.noise_floor = 0.0     # EMA шумового пола (живёт через reset)
        self.reset()

    def reset(self):
        self.buffer = []
        self.preroll = []          # последние чанки ДО начала речи
        self.preroll_samples = 0
        self.in_speech = False
        self.silence_samples = 0
        self.speech_samples = 0

    def _eff_threshold(self):
        if not self.adaptive:
            return self.threshold
        # пол шума * 2.5 + небольшой запас; конфигный порог — нижняя планка
        return max(self.threshold, self.noise_floor * 2.5 + 0.004)

    def push(self, pcm16: np.ndarray):
        """Вернёт np.int16-сегмент когда фраза закончилась, иначе None."""
        rms = float(np.sqrt(np.mean((pcm16.astype(np.float32) / 32768.0) ** 2)))
        thr = self._eff_threshold()
        # гистерезис: подняться над порогом сложнее, чем удержаться
        is_voice = rms > (thr * 0.6 if self.in_speech else thr)

        if not self.in_speech and not is_voice:
            # обновляем шумовой пол ТОЛЬКО на чистой тишине (медленная EMA);
            # чанк, взявший порог, в пол не считаем — иначе тихий голос
            # у границы постепенно задирал бы порог сам себе
            self.noise_floor = (0.95 * self.noise_floor + 0.05 * rms
                                if self.noise_floor > 0 else rms)
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

        end_by_silence = (self.in_speech and
                          self.silence_samples >= self.sr * self.silence_ms / 1000)
        end_by_length = (self.in_speech and
                         self.speech_samples >= self.sr * self.max_segment_s)

        if end_by_silence or end_by_length:
            segment = np.concatenate(self.buffer) if self.buffer else None
            long_enough = self.speech_samples >= self.sr * self.min_speech_ms / 1000
            self.reset()
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
            # или silero_te (см. server/torch_gate.py — «Duplicate
            # registration» из живого лога 2026-07-28)
            from server.torch_gate import TORCH_GATE
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
    # в СВОЁМ потоке (см. server/main.py). Горячий цикл больше не ждёт
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
        for name in self._healthy_chain():
            try:
                with self.lock:
                    text = self._get(name).transcribe(segment, sr)
                results = [{"text": text, "engine": name}] if text else []
                if name != self.current_name:
                    if self._notified_fallback != name:
                        self._notify(name)
                        self._notified_fallback = name
                else:
                    self._notified_fallback = None
                self.health[name] = "ok"
                return self._drop_junk(results)
            except Exception as e:
                self._mark_broken(name, e)
        return []

    def process_chunk(self, pcm16: np.ndarray) -> list[dict]:
        """Вернёт [{'text':..., 'engine':...}] за готовые фразы."""
        # состояние «ничего не выбрано» (2026-07-25): после жёсткой разгрузки
        # слух ВЫКЛЮЧЕН совсем — без этого первая же фраза лениво подгружала
        # текущий движок обратно, и кнопка выглядела неработающей
        if self.current_name in self.OFF:
            return []
        sr = CFG.get("stt.sample_rate", 16000)
        results = []
        for name in self._healthy_chain():
            engine = self._get(name)
            try:
                if engine.kind == "streaming":
                    for text in engine.feed(pcm16, sr):
                        results.append({"text": text, "engine": name})
                else:
                    segment = self.vad.push(pcm16)
                    if segment is not None:
                        with self.lock:
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
                from server import ai_consult
                from server.main import broadcast_event
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
