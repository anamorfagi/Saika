"""Слух -> ядро и ядро -> голос (хозяин обоих: hearing/ и voice/)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Protocol

from .tasks import CancelToken


@dataclass
class Utterance:
    """Законченная реплика, которую слух отдаёт ядру."""
    text: str
    speaker: str = "unknown"      # id говорящего
    is_owner: bool = False        # голос владельца подтверждён
    lang: str = "ru"
    t_start: float = 0.0
    t_end: float = 0.0
    confidence: float = 1.0


class SpeechPort(Protocol):
    def say(self, text: Iterator[str], cancel: CancelToken, task_id: str | None = None) -> None:
        """Озвучивать поток текста по мере поступления; cancel — перебили."""
    def stop(self) -> None: ...
