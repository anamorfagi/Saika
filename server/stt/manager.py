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
        self.max_segment_s = vad.get("max_segment_s", 25)
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
    @property
    def current_name(self):
        return CFG.get("stt.engine", "faster_whisper")

    def set_engine(self, name):
        if name not in ALL_ENGINES:
            raise ValueError(f"Нет такого движка: {name}")
        CFG.set("stt.engine", name)
        self.vad.reset()

    def _get(self, name):
        if name not in self.instances:
            self.instances[name] = ALL_ENGINES[name]()
        return self.instances[name]

    def _healthy_chain(self):
        order = CFG.get("stt.fallback_order", list(ALL_ENGINES))
        current = self.current_name
        chain = [current] + [n for n in order if n != current]
        return [n for n in chain if self.health.get(n) != "broken"]

    # ---------- пайплайн ----------
    def process_chunk(self, pcm16: np.ndarray) -> list[dict]:
        """Вернёт [{'text':..., 'engine':...}] за готовые фразы."""
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
                return results
            except Exception as e:
                self._mark_broken(name, e)
        return results

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
        return out

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

    def status(self):
        loaded = {}
        for name in ALL_ENGINES:
            eng = self.instances.get(name)
            try:
                loaded[name] = bool(eng and eng.is_loaded())
            except Exception:
                loaded[name] = False
        return {"current": self.current_name, "health": self.health,
                "engines": list(ALL_ENGINES), "loaded": loaded,
                "errors": self.last_error, "diag": self.last_diag}
