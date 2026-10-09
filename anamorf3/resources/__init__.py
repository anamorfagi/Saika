"""anamorf3/resources — владелец моделей и видеопамяти. Хозяин: Claude.

Публичный вход для ядра и стенда — ОДНА функция:

    from anamorf3.resources import make_port
    port = make_port("local")        # или "cloud"; "auto" в v0 нет
    for ch in port.chat(ChatRequest(messages=[...]), CancelToken()): ...
    port.status()                    # что загружено, VRAM, цифры последнего ответа
    port.unload_all()                # ResourceReport с VRAM до/после и выжившими

Правила для ядра:
  * процессы моделей ядро не стартует и не убивает — только через порт;
  * ошибка приходит последним ChatChunk(done=True) с usage.finish_reason="error"
    и usage.error — исключений из chat() нет;
  * в последнем куске всегда: finish_reason (stop|tool_calls|length|cancelled|error),
    ttft_ms, total_ms, mode, реальное имя model; у локальной ещё usage.timings.
"""
from __future__ import annotations

from anamorf3.contracts import EventBus

from . import settings as _S


def make_port(mode: str, bus: EventBus | None = None, override: dict | None = None):
    s = _S.load(override)
    if mode == "local":
        from .port import LocalPort
        return LocalPort(s, bus)
    if mode == "cloud":
        from .port import CloudPort
        return CloudPort(s, bus)
    raise ValueError(f"режим {mode!r} не поддержан: local или cloud (выбирает человек)")


__all__ = ["make_port"]
