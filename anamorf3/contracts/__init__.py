"""Контракты между модулями anamorf3. ОБЩАЯ зона: правки только по
согласию обоих исполнителей (см. contracts/CHANGELOG.md).

Правило для всех типов здесь: только стандартная библиотека, никаких
импортов из core/resources/hearing/voice — контракт ни от кого не зависит.
"""
from .events import Event, EventBus
from .tools import ToolResult, ToolStatus
from .tasks import CancelToken, TaskState
from .models import ChatRequest, ChatChunk, ModelPort, ResourceReport
from .speech import Utterance, SpeechPort

__all__ = ["Event", "EventBus", "ToolResult", "ToolStatus", "CancelToken",
           "TaskState", "ChatRequest", "ChatChunk", "ModelPort",
           "ResourceReport", "Utterance", "SpeechPort"]
