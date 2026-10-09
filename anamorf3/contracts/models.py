"""Доступ к моделям — ТОЛЬКО через ModelPort (хозяин: resources/).

ЗАЧЕМ (2026-10-09, аудит Codex п.5): ядро v2 само поднимало свой
llama-server, а выгрузка и выход гасили старый менеджер — движок ядра
оставался в видеопамяти. Здесь у моделей один владелец: ядро просит
ответ, а какой движок, где он живёт и когда выгружается — решает
resources. Ядро никогда не стартует процессы моделей само.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Literal, Protocol

from .tasks import CancelToken

Mode = Literal["local", "cloud", "auto"]


@dataclass
class ChatRequest:
    messages: list[dict[str, Any]]          # формат OpenAI chat
    tools: list[dict[str, Any]] = field(default_factory=list)
    mode: Mode = "auto"                     # локально / облако / решает resources
    role: str = "main"                      # "main" | "fast" | "vision" — профиль, не имя модели
    max_tokens: int = 1024
    temperature: float | None = None
    task_id: str | None = None


@dataclass
class ChatChunk:
    text: str = ""                          # кусок ответа
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # полные, не обрывки
    done: bool = False
    usage: dict[str, Any] = field(default_factory=dict)   # токены, prefill_ms, ttft_ms
    model: str = ""                         # кто реально ответил — для честного показа


@dataclass
class ResourceReport:
    """Отчёт с цифрами — доказательство, а не слова."""
    action: str                             # "unload_all" | "load" | ...
    ok: bool
    vram_before_mb: int | None = None
    vram_after_mb: int | None = None
    killed: list[str] = field(default_factory=list)
    survivors: list[str] = field(default_factory=list)   # кто НЕ умер — честно
    detail: str = ""


class ModelPort(Protocol):
    def chat(self, req: ChatRequest, cancel: CancelToken) -> Iterator[ChatChunk]: ...
    def unload_all(self) -> ResourceReport: ...
    def status(self) -> dict[str, Any]: ...   # что загружено, сколько VRAM, кем
