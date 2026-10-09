"""Задачи и отмена.

ЗАЧЕМ (2026-10-09, аудит Codex п.4): старый registry.execute ждал поток
60 с и бросал его живым — модель получала «не ответил» и запускала то же
действие второй раз. Здесь у задачи всегда есть состояние, а у
долгого действия — токен отмены, который оно обязано проверять.
"""
from __future__ import annotations

import threading
from enum import Enum


class TaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CancelToken:
    def __init__(self) -> None:
        self._ev = threading.Event()
        self.reason = ""

    def cancel(self, reason: str = "") -> None:
        self.reason = reason
        self._ev.set()

    @property
    def cancelled(self) -> bool:
        return self._ev.is_set()

    def wait(self, timeout: float) -> bool:
        """Спать до отмены или таймаута. True — отменили."""
        return self._ev.wait(timeout)
