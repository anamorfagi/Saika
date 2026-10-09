# Core v0 — implementation for independent review

Persistent SQLite sessions, task states, complete conversation turns and event journal.
ModelPort is injected; ModelRouter selects resources ports without cloud fallback
from explicit local mode. Tools validate arguments, keep one job per call id,
require scoped approval for mutations, and return evidence. Cancellation stops
built-in command process trees; interrupted tasks are not replayed at startup.

## Run checks

From C:/AI/Saika:

    .venv/Scripts/python.exe -m unittest discover -s anamorf3/core/tests -v

16 tests passed on 2026-10-09. Live cloud probe returned Mistral HTTP 429;
core recorded FAILED without task.finished. It does not prove cloud success.
Evidence is in logs/anamorf3_core_bench.jsonl (runtime file, not committed).

## Interface status

core/ui/index.html is a diagnostic prototype, not the approved product design.
core/ui/hear is an unchanged copy of C:/AI/Hear/ui (index.html, board.js,
fonts). Original source was not edited. Frontend integration awaits Claude's
DESIGN.md and agreed mockup. The copied Hear page is not yet served by a
compatible history/boards/WebSocket adapter.

core/api.py is the diagnostic HTTP server and defaults to UnconnectedModel.
ModelRouter is available for injected local/cloud ports, but has not yet been
wired to this CLI. CLI model-factory is intended for a no-argument factory;
resources.make_port requires a mode and cannot be passed directly.

## Review limitations

Cloud success and real local tasks through Core still need live validation.
Microphone, TTS, multimodal input and the production frontend adapter remain
unfinished. Tools use application path checks and explicit mutation approval;
this is not an operating-system sandbox. Registry jobs are retained in memory.
An uncooperative external handler cannot be forcibly stopped by a Python thread.
Task time limits are cooperative across synchronous ModelPort calls; transport
timeouts and cancellation must also be enforced by resources.