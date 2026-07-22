"""Воркер LocalLM (движок llama.cpp) — быстрый путь без transformers.

В отличие от workers/locallm_worker.py (transformers+bitsandbytes), тут
инференс — компилированный llama.cpp через биндинг llama-cpp-python:
GGUF-квант целиком в VRAM (n_gpu_layers=-1), генерация на C++ CUDA-ядрах.
Это тот же класс движка, что у LM Studio под капотом — отсюда и кратный
прирост ток/с по сравнению с transformers-путём.

Протокол — тот же контракт, что у v1-воркера (менеджер их не различает):
  GET  /health                  {"ok":true,"model_loaded":bool,"error":str|null}
  GET  /v1/models               {"data":[{"id": "<model>"}]}
  POST /v1/chat/completions     stream=true -> SSE-чанки OpenAI-формата
  POST /admin/unload            выгрузить модель, освободить VRAM

Удобство llama-cpp-python: Llama.create_chat_completion(stream=True) САМ
отдаёт словари в форме OpenAI-чанков (id/object/choices[0].delta.content) —
почти не нужно ничего домысливать, в отличие от ручной сборки в
transformers-версии воркера.

Живёт в .venv_locallm_gguf (setup/install_locallm_gguf.py) — БЕЗ torch,
самостоятельный венв.

Запуск вручную:
  .venv_locallm_gguf\\Scripts\\python.exe workers\\locallm_worker_gguf.py --port 8770
"""
import argparse
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(),
              logging.FileHandler(ROOT / "logs" / "locallm_gguf_worker.log",
                                  encoding="utf-8")])
log = logging.getLogger("locallm_gguf_worker")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

MODEL_REPO = "mradermacher/Huihui-Qwen3.5-9B-abliterated-i1-GGUF"
QUANT = "Q4_K_M"
N_CTX_DEFAULT = 8192

_model = None
_model_path = None
_error = None
_ready = threading.Event()
_infer_lock = threading.Lock()
_load_lock = threading.Lock()


def _configure_hf_endpoint():
    """Копия логики из dreampc_worker.py/locallm_worker.py — авто-зеркало/
    офлайн перед КАЖДОЙ попыткой скачивания."""
    import socket

    def reachable(host):
        try:
            socket.create_connection((host, 443), timeout=3).close()
            return True
        except OSError:
            return False

    if reachable("huggingface.co"):
        os.environ.pop("HF_ENDPOINT", None)
        os.environ.pop("HF_HUB_OFFLINE", None)
    elif reachable("hf-mirror.com"):
        os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        os.environ.pop("HF_HUB_OFFLINE", None)
        log.info("huggingface.co недоступен — использую зеркало hf-mirror.com")
    else:
        os.environ["HF_HUB_OFFLINE"] = "1"
        log.info("huggingface.co и hf-mirror.com недоступны — офлайн-режим "
                 "(нужен уже скачанный GGUF-файл)")


def _find_gguf_path() -> str:
    """Ищет уже скачанный GGUF нужного кванта в HF-кэше; если нет — качает.
    Как и install_locallm_gguf.py, матчит по СУФФИКСУ имени (не точному
    файлу) — у разных квантователей имена чуть отличаются."""
    from huggingface_hub import list_repo_files, hf_hub_download
    from _hf_progress import DownloadProgressLogger
    _configure_hf_endpoint()
    files = [f for f in list_repo_files(MODEL_REPO) if f.lower().endswith(".gguf")]
    cands = [f for f in files if QUANT.lower() in f.lower()]
    if not cands:
        raise RuntimeError(
            f"В {MODEL_REPO} нет файла с '{QUANT}' в имени. Доступные "
            f"кванты: {files}. Поправь locallm_gguf.quant в config.json.")
    fname = sorted(cands, key=len)[0]
    log.info("Модель: %s / %s (если ещё не скачана — качаю, обычно 4-7 ГБ "
              "для Q4/Q5)", MODEL_REPO, fname)
    with DownloadProgressLogger(log, ROOT / "models" / "hf", MODEL_REPO,
                                 label=f"{MODEL_REPO} ({fname})"):
        return hf_hub_download(MODEL_REPO, fname)


def _try_load():
    """(Пере)пытается загрузить модель — идемпотентно, потокобезопасно,
    ретраится при следующем вызове после сетевой неудачи (паттерн
    dreampc_worker.py/locallm_worker.py, не повторяю все комментарии)."""
    global _model, _model_path, _error
    if _model is not None:
        return
    with _load_lock:
        if _model is not None:
            return
        _error = None
        try:
            # venv БЕЗ torch - некому неявно подключить CUDA-DLL. llama_cpp
            # зовёт ctypes.CDLL с winmode=0 (отключает add_dll_directory,
            # откатывает на поиск через PATH) - подмешиваем PATH И
            # add_dll_directory на всякий случай (проверено эмпирически:
            # одного add_dll_directory было мало).
            if os.name == "nt":
                dirs = []
                for pkg in ("nvidia/cuda_runtime/bin", "nvidia/cublas/bin"):
                    d = os.path.join(sys.prefix, "Lib", "site-packages",
                                     *pkg.split("/"))
                    if os.path.isdir(d):
                        dirs.append(d)
                        try:
                            os.add_dll_directory(d)
                        except Exception:
                            pass
                if dirs:
                    os.environ["PATH"] = (os.pathsep.join(dirs) + os.pathsep
                                          + os.environ.get("PATH", ""))
            from llama_cpp import Llama
            path = _find_gguf_path()
            log.info("Загружаю %s в VRAM (n_gpu_layers=-1, n_ctx=%s)…",
                     path, N_CTX_DEFAULT)
            model = Llama(
                model_path=path,
                n_gpu_layers=-1,       # весь офлоад на GPU
                n_ctx=N_CTX_DEFAULT,
                flash_attn=True,       # игнорируется, если сборка без флеша
                verbose=False,
            )
            try:
                offloaded = llama_cpp_gpu_check()
            except Exception:
                offloaded = None
            _model_path = path
            _model = model  # последним — до этого момента «не готова»
            log.info("Модель готова (%s, gpu_offload=%s)", path, offloaded)
        except Exception as e:
            _error = str(e)
            log.exception("Не удалось загрузить модель")
        finally:
            _ready.set()


def llama_cpp_gpu_check():
    import llama_cpp
    return llama_cpp.llama_supports_gpu_offload()


def _unload():
    global _model, _model_path
    with _load_lock:
        _model = None
        _model_path = None
        _ready.clear()
    import gc
    gc.collect()
    log.info("Модель выгружена из памяти")


@app.get("/health")
def health():
    return {"ok": True, "model_loaded": _model is not None, "error": _error}


@app.get("/v1/models")
def models():
    return {"object": "list",
            "data": [{"id": MODEL_REPO, "object": "model", "owned_by": "saika"}]}


@app.post("/admin/unload")
def admin_unload():
    _unload()
    return {"ok": True}


def _sanitize_messages(messages):
    """Тот же список правок, что в transformers-версии воркера: content-
    списки сплющиваем в текст, роль tool превращаем в user-заметку, странные
    роли -> user (tools в v1 всё равно молча игнорируем)."""
    out = []
    for m in messages or []:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                p.get("text", "") for p in content
                if isinstance(p, dict) and p.get("type") == "text").strip()
        content = content or ""
        if role == "tool":
            name = m.get("name", "tool")
            role, content = "user", f"[результат инструмента {name}]\n{content}"
        elif role == "assistant" and m.get("tool_calls"):
            content = content or "(вызов инструмента)"
        if role not in ("system", "user", "assistant"):
            role = "user"
        out.append({"role": role, "content": content})
    return out


def _stream(messages, temperature, max_tokens):
    _ready.wait(timeout=1800)
    if _model is None:
        _try_load()
    if _error:
        yield ("data: " + json.dumps({
            "choices": [{"index": 0,
                        "delta": {"content": f"[ошибка LocalLM: {_error}]"},
                        "finish_reason": "stop"}]}, ensure_ascii=False)
              + "\n\n")
        yield "data: [DONE]\n\n"
        return
    if not _infer_lock.acquire(blocking=False):
        yield ("data: " + json.dumps({
            "choices": [{"index": 0,
                        "delta": {"content": "[LocalLM уже занята генерацией]"},
                        "finish_reason": "stop"}]}, ensure_ascii=False)
              + "\n\n")
        yield "data: [DONE]\n\n"
        return
    try:
        msgs = _sanitize_messages(messages)
        t0 = time.monotonic()
        n_chars = 0
        # create_chat_completion сам применяет встроенный в GGUF chat-шаблон
        # (llama.cpp понимает jinja-шаблон, зашитый в метаданные модели) и
        # при stream=True возвращает готовые OpenAI-чанки — просто ретранслируем
        for chunk in _model.create_chat_completion(
                messages=msgs, stream=True,
                temperature=temperature, max_tokens=max_tokens):
            delta = chunk.get("choices", [{}])[0].get("delta", {})
            n_chars += len(delta.get("content") or "")
            yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
        elapsed = max(time.monotonic() - t0, 0.001)
        log.info("Ответ: ~%d символов за %.1fс (~%.1f ток/с при ~4 симв/ток)",
                 n_chars, elapsed, (n_chars / 4) / elapsed)
        yield "data: [DONE]\n\n"
    except Exception as e:
        log.exception("Ошибка генерации")
        yield ("data: " + json.dumps({
            "choices": [{"index": 0, "delta": {"content": f"[ошибка: {e}]"},
                        "finish_reason": "stop"}]}, ensure_ascii=False)
              + "\n\n")
        yield "data: [DONE]\n\n"
    finally:
        _infer_lock.release()


@app.post("/v1/chat/completions")
def chat_completions(payload: dict):
    messages = payload.get("messages") or []
    temperature = float(payload.get("temperature", 0.8))
    max_tokens = int(payload.get("max_tokens")
                     or payload.get("max_completion_tokens") or 2048)
    if payload.get("stream", False):
        return StreamingResponse(_stream(messages, temperature, max_tokens),
                                 media_type="text/event-stream")
    text = ""
    for chunk in _stream(messages, temperature, max_tokens):
        if chunk.startswith("data: ") and "[DONE]" not in chunk:
            try:
                text += json.loads(chunk[6:])["choices"][0]["delta"].get(
                    "content") or ""
            except Exception:
                pass
    return JSONResponse({
        "object": "chat.completion", "created": int(time.time()),
        "model": MODEL_REPO,
        "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": text}}]})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--repo", default=MODEL_REPO)
    ap.add_argument("--quant", default=QUANT)
    ap.add_argument("--n-ctx", type=int, default=N_CTX_DEFAULT)
    args = ap.parse_args()
    MODEL_REPO = args.repo
    QUANT = args.quant
    N_CTX_DEFAULT = args.n_ctx
    (ROOT / "logs").mkdir(exist_ok=True)
    log.info("LocalLM (llama.cpp) воркер: %s / %s, порт=%s, n_ctx=%s",
             MODEL_REPO, QUANT, args.port, N_CTX_DEFAULT)
    threading.Thread(target=_try_load, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
