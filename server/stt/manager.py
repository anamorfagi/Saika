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

log = logging.getLogger("saika.stt")


class VadSegmenter:
    """Простой энергетический VAD: копим речь, отдаём сегмент после тишины."""

    def __init__(self):
        vad = CFG.get("stt.vad", {})
        self.threshold = vad.get("rms_threshold", 0.012)
        self.silence_ms = vad.get("silence_ms", 700)
        self.min_speech_ms = vad.get("min_speech_ms", 300)
        self.max_segment_s = vad.get("max_segment_s", 25)
        self.sr = CFG.get("stt.sample_rate", 16000)
        self.reset()

    def reset(self):
        self.buffer = []
        self.in_speech = False
        self.silence_samples = 0
        self.speech_samples = 0

    def push(self, pcm16: np.ndarray):
        """Вернёт np.int16-сегмент когда фраза закончилась, иначе None."""
        rms = float(np.sqrt(np.mean((pcm16.astype(np.float32) / 32768.0) ** 2)))
        is_voice = rms > self.threshold

        if is_voice:
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
        self.last_error = {}  # name -> текст последней ошибки (для UI)
        self.vad = VadSegmenter()
        self.lock = threading.Lock()
        self.on_problem = on_problem  # callback(component, error, action)

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
                    # работаем на запасном — сообщим один раз
                    self._notify(name)
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
        except Exception as e:
            self.health[name] = "broken"
            self.last_error[name] = str(e)
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
        self.last_error[name] = str(error)
        log.error("STT %s сломался: %s", name, error)
        if self.on_problem:
            self.on_problem("stt." + name, str(error),
                            "переключаюсь на следующий движок, чиню в фоне")
        threading.Thread(target=self._repair, args=(name,), daemon=True).start()

    def _notify(self, active):
        if self.on_problem:
            self.on_problem("stt", f"основной движок недоступен",
                            f"работаю на {active}")

    def _repair(self, name):
        """Фоновая попытка починить: выгрузить и загрузить заново."""
        time.sleep(2)
        try:
            engine = self._get(name)
            engine.unload()
            engine.load()
            self.health[name] = "ok"
            self.last_error.pop(name, None)
            log.info("STT %s восстановлен", name)
            if self.on_problem:
                self.on_problem("stt." + name, "", "движок восстановлен")
        except Exception as e:
            self.last_error[name] = str(e)
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
                "errors": self.last_error}
