"""Базовый интерфейс STT-движка.

Два типа движков:
- buffered: получают целый сегмент речи (после VAD) и возвращают текст
- streaming: принимают PCM-чанки на лету и сами выдают фразы
"""
import numpy as np


class STTEngine:
    name = "base"
    kind = "buffered"  # или "streaming"

    def load(self):
        """Ленивая загрузка модели. Бросает исключение если движок неисправен."""
        raise NotImplementedError

    def unload(self):
        pass

    def is_loaded(self) -> bool:
        """Модель сейчас в памяти? По умолчанию смотрим self.model."""
        return getattr(self, "model", None) is not None

    # --- buffered ---
    def transcribe(self, pcm16: np.ndarray, sample_rate: int) -> str:
        """pcm16: int16 mono."""
        raise NotImplementedError

    # --- streaming ---
    def feed(self, pcm16: np.ndarray, sample_rate: int) -> list[str]:
        """Принять чанк, вернуть список готовых фраз (может быть пустым)."""
        raise NotImplementedError

    def flush(self) -> list[str]:
        """Завершить поток, вернуть остаток."""
        return []


def pcm16_to_float(pcm16: np.ndarray) -> np.ndarray:
    return pcm16.astype(np.float32) / 32768.0
