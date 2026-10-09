"""Результат инструмента — структура, а не текст.

ЗАЧЕМ (2026-10-09, аудит Codex п.6): старое ядро считало вызов успешным,
если ответ НЕ начинается с шаблона отказа. «Нет слова-отказа» ≠ «сделано».
Здесь успех — явное поле, а доказательство — в evidence (путь и размер
файла, код возврата команды, заголовок открытого окна ...).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolStatus(str, Enum):
    DONE = "done"            # сделано, есть evidence
    FAILED = "failed"        # не сделано, в error — почему
    RUNNING = "running"      # ещё идёт (таймаут ожидания ≠ провал), повторять НЕЛЬЗЯ
    CANCELLED = "cancelled"  # остановлено по CancelToken
    NEEDS_CONFIRM = "needs_confirm"  # опасное действие ждёт «да» человека


@dataclass
class ToolResult:
    status: ToolStatus
    text: str = ""                                 # что увидит модель
    data: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status is ToolStatus.DONE
