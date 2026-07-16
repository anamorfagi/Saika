"""Шесть STT-движков под русский язык.

1. faster_whisper — Whisper large-v3-turbo на CTranslate2 (GPU, лучший баланс)
2. gigaam        — GigaAM v3 e2e RNNT от Сбера (SOTA для русского, с пунктуацией)
3. vosk          — лёгкий офлайн-стриминг Kaldi (CPU, мгновенный)
4. whispercpp    — whisper.cpp через pywhispercpp (CPU/GPU, ggml)
5. tone          — T-one от Т-Банка (стриминг, телефония; опционален на Windows)
6. voxtral       — Voxtral Mini 4B Realtime от Mistral (нативно-потоковая
                   архитектура, русский в 13 языках). Работает как внешний
                   процесс в своём .venv_voxtral (см. server/stt/external.py):
                   его transformers>=5.2 конфликтует с Qwen3-TTS (==4.57.3).
                   Выбор в UI без установленного окружения сам откроет
                   окно установщика (setup/install_voxtral.bat).

Каждый движок ленив: модель грузится при первом использовании.
Ошибка загрузки => менеджер переключается на следующий по fallback_order.
"""
import json
import logging
import tempfile
from pathlib import Path

import numpy as np

from server.config import CFG, resolve
from server.stt.base import STTEngine, pcm16_to_float
from server.stt.external import ExternalEngine

log = logging.getLogger("saika.stt")


def _to_wav_tempfile(pcm16: np.ndarray, sample_rate: int) -> str:
    """Некоторые движки принимают только путь к файлу."""
    import soundfile as sf

    f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(f.name, pcm16, sample_rate)
    return f.name


class FasterWhisperEngine(STTEngine):
    name = "faster_whisper"
    kind = "buffered"

    def __init__(self):
        self.model = None

    def load(self):
        if self.model:
            return
        from faster_whisper import WhisperModel

        cfg = CFG.get("stt.engines.faster_whisper", {})
        device = cfg.get("device", "auto")
        compute = cfg.get("compute_type", "auto")
        try:
            self.model = WhisperModel(cfg.get("model", "large-v3-turbo"),
                                      device=device, compute_type=compute)
        except Exception:
            # GPU не завёлся — тихо падаем на CPU int8
            log.warning("faster-whisper: GPU недоступен, переключаюсь на CPU int8")
            self.model = WhisperModel(cfg.get("model", "large-v3-turbo"),
                                      device="cpu", compute_type="int8")

    def transcribe(self, pcm16, sample_rate):
        self.load()
        audio = pcm16_to_float(pcm16)
        kw = dict(language=CFG.get("stt.language", "ru"),
                  beam_size=1, vad_filter=True,
                  condition_on_previous_text=False)
        try:
            segments, _ = self.model.transcribe(audio, **kw)
            return " ".join(s.text.strip() for s in segments).strip()
        except Exception as e:
            # CUDA-ошибки (cublas64_12.dll и т.п.) вылезают при инференсе,
            # а не при загрузке — пересоздаём модель на CPU и повторяем
            log.warning("faster-whisper: инференс упал (%s) — CPU int8", e)
            from faster_whisper import WhisperModel
            cfg = CFG.get("stt.engines.faster_whisper", {})
            self.model = WhisperModel(cfg.get("model", "large-v3-turbo"),
                                      device="cpu", compute_type="int8")
            segments, _ = self.model.transcribe(audio, **kw)
            return " ".join(s.text.strip() for s in segments).strip()

    def unload(self):
        self.model = None


class VoxtralEngine(ExternalEngine):
    """Voxtral Mini 4B Realtime (Mistral, Apache 2.0) — экспериментальный.

    Нативно-потоковый ASR с каузальным аудио-энкодером, WER на русском
    (FLEURS) ~6% при задержке 480 мс. Работает воркером в отдельном
    .venv_voxtral (workers/voxtral_worker.py) — конфликт transformers
    с Qwen3-TTS решён изоляцией окружений. Здесь buffered-режим
    (generate по VAD-сегментам); истинный стриминг — только через vLLM,
    которого нет под Windows.
    """
    name = "voxtral"


class GigaAMEngine(STTEngine):
    name = "gigaam"
    kind = "buffered"

    def __init__(self):
        self.model = None

    def load(self):
        if self.model:
            return
        import gigaam

        model_name = CFG.get("stt.engines.gigaam.model", "v3_e2e_rnnt")
        try:
            self.model = gigaam.load_model(model_name)
        except Exception as e:
            # частично скачанный чекпоинт бьётся по контрольной сумме
            # («Model checksum failed»). gigaam сам не перекачивает — сносим
            # битый .ckpt из кэша (~/.cache/gigaam) и грузим заново.
            if "checksum" not in str(e).lower():
                raise
            from pathlib import Path
            ckpt = Path.home() / ".cache" / "gigaam" / f"{model_name}.ckpt"
            log.warning("GigaAM: битый чекпоинт (%s) — удаляю %s и качаю заново",
                        e, ckpt)
            try:
                ckpt.unlink(missing_ok=True)
            except Exception as del_err:
                log.warning("GigaAM: не смог удалить %s: %s", ckpt, del_err)
            self.model = gigaam.load_model(model_name)

    def transcribe(self, pcm16, sample_rate):
        self.load()
        path = _to_wav_tempfile(pcm16, sample_rate)
        try:
            result = self.model.transcribe(path)
            # v3 может вернуть объект с .text или строку
            return getattr(result, "text", result if isinstance(result, str) else str(result)).strip()
        finally:
            Path(path).unlink(missing_ok=True)

    def unload(self):
        self.model = None


class VoskEngine(STTEngine):
    name = "vosk"
    kind = "streaming"

    def __init__(self):
        self.model = None
        self.rec = None

    def load(self):
        if self.model:
            return
        from vosk import Model, KaldiRecognizer

        model_dir = resolve(CFG.get("stt.engines.vosk.model_dir"))
        if not model_dir.exists():
            raise FileNotFoundError(
                f"Модель Vosk не найдена: {model_dir}. Запусти setup/first_run.py")
        self.model = Model(str(model_dir))
        self._KaldiRecognizer = KaldiRecognizer
        self._new_rec()

    def _new_rec(self):
        self.rec = self._KaldiRecognizer(self.model, CFG.get("stt.sample_rate", 16000))

    def feed(self, pcm16, sample_rate):
        self.load()
        phrases = []
        if self.rec.AcceptWaveform(pcm16.tobytes()):
            text = json.loads(self.rec.Result()).get("text", "").strip()
            if text:
                phrases.append(text)
        return phrases

    def flush(self):
        if not self.rec:
            return []
        text = json.loads(self.rec.FinalResult()).get("text", "").strip()
        self._new_rec()
        return [text] if text else []

    # buffered-совместимость (менеджер может звать transcribe на сегменте)
    def transcribe(self, pcm16, sample_rate):
        self.load()
        self._new_rec()
        self.rec.AcceptWaveform(pcm16.tobytes())
        return json.loads(self.rec.FinalResult()).get("text", "").strip()

    def unload(self):
        self.model = None
        self.rec = None


class WhisperCppEngine(STTEngine):
    name = "whispercpp"
    kind = "buffered"

    def __init__(self):
        self.model = None

    def load(self):
        if self.model:
            return
        from pywhispercpp.model import Model

        cfg = CFG.get("stt.engines.whispercpp", {})
        # модели ggml — в папке проекта, не в AppData (переносимость)
        models_dir = resolve("models/whispercpp")
        models_dir.mkdir(parents=True, exist_ok=True)
        self.model = Model(cfg.get("model", "medium"),
                           models_dir=str(models_dir),
                           n_threads=cfg.get("n_threads", 8))

    def transcribe(self, pcm16, sample_rate):
        self.load()
        segments = self.model.transcribe(
            pcm16_to_float(pcm16), language=CFG.get("stt.language", "ru"))
        return " ".join(s.text.strip() for s in segments).strip()

    def unload(self):
        self.model = None


class ToneEngine(STTEngine):
    name = "tone"
    kind = "streaming"
    # T-one требует кадры РОВНО по 2400 сэмплов (300 мс @ 8кГц у пайплайна,
    # 150 мс @ 16кГц у нас). Браузер шлёт произвольные чанки (~1600), отсюда
    # была ошибка «Shape of 'audio_chunk' must be (2400,), but got (1634,)».
    # Копим PCM и отдаём пайплайну ровными кадрами.
    FRAME = 2400

    def __init__(self):
        self.pipeline = None
        self.state = None
        self._buf = np.empty(0, dtype=np.int16)

    def load(self):
        if self.pipeline:
            return
        from tone import StreamingCTCPipeline

        self.pipeline = StreamingCTCPipeline.from_hugging_face()
        self.state = None
        self._buf = np.empty(0, dtype=np.int16)

    def feed(self, pcm16, sample_rate):
        self.load()
        self._buf = np.concatenate([self._buf, pcm16.astype(np.int16)])
        phrases = []
        while len(self._buf) >= self.FRAME:
            frame = self._buf[:self.FRAME]
            self._buf = self._buf[self.FRAME:]
            new_phrases, self.state = self.pipeline.forward(frame, self.state)
            phrases += [getattr(p, "text", str(p)).strip()
                        for p in (new_phrases or []) if p]
        return phrases

    def flush(self):
        if not self.pipeline:
            return []
        phrases = []
        # добиваем неполный остаток, дополнив тишиной до целого кадра
        if len(self._buf) > 0:
            pad = self.FRAME - (len(self._buf) % self.FRAME)
            if pad != self.FRAME:
                self._buf = np.concatenate(
                    [self._buf, np.zeros(pad, dtype=np.int16)])
            while len(self._buf) >= self.FRAME:
                frame = self._buf[:self.FRAME]
                self._buf = self._buf[self.FRAME:]
                new_phrases, self.state = self.pipeline.forward(frame, self.state)
                phrases += [getattr(p, "text", str(p)).strip()
                            for p in (new_phrases or []) if p]
        self._buf = np.empty(0, dtype=np.int16)
        new_phrases, _ = self.pipeline.finalize(self.state)
        self.state = None
        phrases += [getattr(p, "text", str(p)).strip()
                    for p in (new_phrases or []) if p]
        return phrases

    def transcribe(self, pcm16, sample_rate):
        self.load()
        self.state = None
        result = self.pipeline.forward_offline(pcm16)
        if isinstance(result, list):
            return " ".join(getattr(p, "text", str(p)) for p in result).strip()
        return getattr(result, "text", str(result)).strip()

    def unload(self):
        self.pipeline = None
        self.state = None

    def is_loaded(self):
        return self.pipeline is not None


ALL_ENGINES = {
    "faster_whisper": FasterWhisperEngine,
    "gigaam": GigaAMEngine,
    "vosk": VoskEngine,
    "whispercpp": WhisperCppEngine,
    "tone": ToneEngine,
    "voxtral": VoxtralEngine,
}
