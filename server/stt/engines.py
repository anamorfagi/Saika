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
            try:
                result = self.model.transcribe(path)
            except Exception as e:
                # длинный сегмент (2026-07-23: «Too long wav file, use
                # 'transcribe_longform' method») — не роняем движок, а
                # честно распознаём длинной дорожкой и склеиваем куски
                if "long" not in str(e).lower():
                    raise
                try:
                    chunks = self.model.transcribe_longform(path)
                except Exception as e2:
                    # ГРАБЛИ 2026-07-28 (живой случай, час на поиск).
                    # transcribe_longform тянет pyannote — отдельный пакет,
                    # которого в сборке нет. Итог был такой: длинный кусок ->
                    # ImportError -> движок помечается сломанным -> слух
                    # падает на faster_whisper (5.8с на фразу) -> через пять
                    # секунд «восстановлен» -> и так по кругу каждые полминуты.
                    # В интерфейсе это выглядело как «транскриптор не
                    # справляется», хотя дело было в одной ненайденной
                    # библиотеке.
                    # Чиним без зависимости: режем сами. Куски по 20 секунд
                    # честнее, чем ничего, и точно короче предела движка.
                    log.info("GigaAM: длинный кусок, а longform недоступен "
                             "(%s) — режу сам по 20с", str(e2)[:80])
                    return self._by_pieces(pcm16, sample_rate)
                parts = []
                for c in (chunks or []):
                    t = (c.get("transcription") if isinstance(c, dict)
                         else getattr(c, "transcription",
                                      getattr(c, "text", str(c))))
                    if t:
                        parts.append(str(t).strip())
                return " ".join(parts).strip()
            # v3 может вернуть объект с .text или строку
            return getattr(result, "text", result if isinstance(result, str) else str(result)).strip()
        finally:
            Path(path).unlink(missing_ok=True)

    def _by_pieces(self, pcm16, sample_rate, seconds=20):
        """Разрезать длинную запись самим и склеить расшифровку.

        Нужен, когда движок отказывается брать длинный кусок, а его штатная
        «длинная дорожка» недоступна. Режем с нахлёстом в полсекунды: без
        него слово на стыке теряется целиком, с ним оно попадает в один из
        кусков полностью."""
        import numpy as _np
        step = int(seconds * sample_rate)
        over = int(0.5 * sample_rate)
        parts = []
        i = 0
        while i < len(pcm16):
            piece = pcm16[max(0, i - over):i + step]
            p2 = _to_wav_tempfile(_np.asarray(piece), sample_rate)
            try:
                r = self.model.transcribe(p2)
                t = getattr(r, "text", r if isinstance(r, str) else str(r))
                if t:
                    parts.append(str(t).strip())
            except Exception as e:
                log.warning("GigaAM: кусок не разобрался (%s)", str(e)[:80])
            finally:
                Path(p2).unlink(missing_ok=True)
            i += step
        return " ".join(x for x in parts if x).strip()

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
        name = cfg.get("model", "medium")
        # ПРЕДПОЛЁТНАЯ ПРОВЕРКА ФАЙЛА — обязательна. Живой инцидент
        # 2026-07-23: ggml-medium.bin оказался пустышкой 0 байт (закачка
        # когда-то сорвалась), pywhispercpp проверяет только «файл есть»,
        # whisper_init говорит "invalid model data (bad magic)", НЕ бросает
        # исключение — и transcribe по нулевому контексту убивает ВЕСЬ
        # процесс Сайки access violation'ом (-1073741819), без traceback.
        # Битый файл сносим — Model() скачает заново; если и после закачки
        # магия не сошлась — честный RuntimeError, менеджер уйдёт на
        # запасной движок вместо смерти сервера.
        bin_path = models_dir / f"ggml-{name}.bin"

        def _magic_ok():
            try:
                with open(bin_path, "rb") as f:
                    return f.read(4) == b"lmgg"  # 0x67676d6c (ggml, LE)
            except OSError:
                return False

        if bin_path.exists() and (bin_path.stat().st_size < 1_000_000
                                  or not _magic_ok()):
            log.warning("whispercpp: %s битый (размер %s байт) — удаляю, "
                        "скачаю заново", bin_path.name,
                        bin_path.stat().st_size)
            bin_path.unlink()
        model = Model(name, models_dir=str(models_dir),
                      n_threads=cfg.get("n_threads", 8))
        if bin_path.exists() and not _magic_ok():
            raise RuntimeError(
                f"whispercpp: файл модели {bin_path.name} битый и после "
                f"перекачки (магия ggml не сошлась) — не рискую нативным "
                f"крашем, движок помечается сломанным")
        self.model = model

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
            # T-one требует dtype int32 («Incorrect dtype of 'audio_chunk':
            # expected np.int32, but got int16», 2026-07-25) — буфер держим
            # компактным int16, конвертируем только кадр на входе в пайплайн
            new_phrases, self.state = self.pipeline.forward(
                frame.astype(np.int32), self.state)
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
                new_phrases, self.state = self.pipeline.forward(
                    frame.astype(np.int32), self.state)
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
        result = self.pipeline.forward_offline(pcm16.astype(np.int32))
        if isinstance(result, list):
            return " ".join(getattr(p, "text", str(p)) for p in result).strip()
        return getattr(result, "text", str(result)).strip()

    def unload(self):
        self.pipeline = None
        self.state = None

    def is_loaded(self):
        return self.pipeline is not None


class CloudWhisperEngine(STTEngine):
    """☁ Облачный слух через ЛЮБОЙ OpenAI-совместимый /audio/transcriptions
    (2026-07-23). Сегмент в 2-5с речи транскрибируется за ~200-500мс + пинг —
    сопоставимо с локальным GigaAM, но БЕЗ ЕДИНОГО мегабайта VRAM (важно для
    UE-проекта: GPU целиком уходит рендеру и LLM).

    Провайдер настраивается в config -> stt.engines.groq_whisper:
      base_url      https://api.groq.com/openai/v1 (дефолт; Groq в РФ может
                    блокаться — тогда впиши РФ-агрегатор, напр.
                    https://api.proxyapi.ru/openai/v1 или
                    https://api.aitunnel.ru/v1 — оплата рублями)
      model         whisper-large-v3-turbo (у агрегаторов обычно whisper-1)
      key_provider  из какого слота ☁-ключей брать ключ (groq/openai/custom…)
    Ключ — secrets.json -> llm.cloud_keys[key_provider], запасной вариант —
    старый общий слот cloud_api_key. Нет сети/ключа — менеджер сам уйдёт на
    локальный движок по fallback_order."""
    name = "groq_whisper"   # id оставлен прежним (конфиги/рейтинги)
    kind = "buffered"

    def __init__(self):
        self.model = None   # is_loaded: "загружен" = ключ найден и проверен

    def _cfg(self) -> dict:
        return CFG.get("stt.engines.groq_whisper", {}) or {}

    def _key(self) -> str:
        import json as _json
        from server.config import ROOT
        try:
            s = _json.loads((ROOT / "secrets.json").read_text(encoding="utf-8"))
            lm = s.get("llm", {}) or {}
            prov = self._cfg().get("key_provider", "groq")
            return ((lm.get("cloud_keys", {}) or {}).get(prov, "")
                    or lm.get("cloud_api_key", ""))
        except Exception:
            return ""

    def load(self):
        if self.model:
            return
        if not self._key():
            raise RuntimeError(
                "нет ключа для облачного слуха — вбей ключ провайдера в "
                "☁-настройках (по умолчанию слот Groq) или задай "
                "stt.engines.groq_whisper.key_provider")
        self.model = self._cfg().get("model", "whisper-large-v3-turbo")

    def transcribe(self, pcm16, sample_rate):
        self.load()
        import io
        import requests
        import soundfile as sf
        base = (self._cfg().get("base_url",
                                "https://api.groq.com/openai/v1")).rstrip("/")
        buf = io.BytesIO()
        sf.write(buf, pcm16, sample_rate, format="WAV")
        buf.seek(0)
        r = requests.post(
            base + "/audio/transcriptions",
            headers={"Authorization": "Bearer " + self._key()},
            files={"file": ("speech.wav", buf, "audio/wav")},
            data={"model": self.model,
                  "language": CFG.get("stt.language", "ru"),
                  "temperature": "0"},
            timeout=20)
        r.raise_for_status()
        return (r.json().get("text") or "").strip()

    def unload(self):
        self.model = None


ALL_ENGINES = {
    "faster_whisper": FasterWhisperEngine,
    "gigaam": GigaAMEngine,
    "vosk": VoskEngine,
    "whispercpp": WhisperCppEngine,
    "tone": ToneEngine,
    "voxtral": VoxtralEngine,
    "groq_whisper": CloudWhisperEngine,
}
