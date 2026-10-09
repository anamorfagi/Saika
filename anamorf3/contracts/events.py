"""События — единственный способ показать человеку, что происходит.

ЗАЧЕМ (2026-10-09): в старой Сайке интерфейс узнавал о состоянии из
десятка разных мест (опросы /api/*, ws-сообщения, логи), и картинка
расходилась с правдой. Здесь любой невидимый процесс (загрузка модели,
вызов инструмента, конец реплики) обязан выпустить событие, а интерфейс
рисует ТОЛЬКО события.

Имена типов — «область.что»: task.started, tool.result, model.loaded,
vram.snapshot, hear.final, voice.first_audio ... Полный список держим в
KNOWN_TYPES, неизвестный тип — ошибка в разработке, а не тихий мусор.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

KNOWN_TYPES = {
    # задачи (core)
    "task.started", "task.progress", "task.finished", "task.failed", "task.cancelled",
    # инструменты (core)
    "tool.call", "tool.result",
    # модели и память GPU (resources)
    "model.loading", "model.loaded", "model.unloading", "model.unloaded",
    "model.error", "vram.snapshot",
    # слух (hearing)
    "hear.speech_start", "hear.partial", "hear.final", "hear.turn_end",
    # голос (voice)
    "voice.start", "voice.first_audio", "voice.stop",
}


@dataclass
class Event:
    type: str                      # из KNOWN_TYPES
    source: str                    # "core" | "resources" | "hearing" | "voice" | "ui"
    data: dict[str, Any] = field(default_factory=dict)
    task_id: str | None = None     # к какой задаче относится (если относится)
    ts: float = field(default_factory=time.time)


class EventBus:
    """Простейшая шина в процессе: подписка по префиксу типа.
    Подписчик НЕ должен блокировать — тяжёлое уносит в свой поток."""

    def __init__(self) -> None:
        self._subs: list[tuple[str, Callable[[Event], None]]] = []
        self._lock = threading.Lock()

    def subscribe(self, prefix: str, fn: Callable[[Event], None]) -> None:
        with self._lock:
            self._subs.append((prefix, fn))

    def publish(self, ev: Event) -> None:
        if ev.type not in KNOWN_TYPES:
            raise ValueError(f"неизвестный тип события: {ev.type}")
        with self._lock:
            subs = list(self._subs)
        for prefix, fn in subs:
            if ev.type.startswith(prefix):
                try:
                    fn(ev)
                except Exception:
                    pass   # чужой подписчик не роняет шину
