"""Воркер LocalLM — «своя» LLM Сайки без Ollama/LM Studio.

Модель (по умолчанию t-tech/T-lite-it-2.1, 8B Qwen3-файнтюн с лучшим русским
в классе) живёт прямо в проекте: веса — models/hf, инференс — transformers
в 4 битах (nf4, ~5.5 ГБ VRAM), стриминг — TextIteratorStreamer.

Протокол — OpenAI-совместимый, ровно тот диалект, который уже умеет
server/llm/manager.py (_stream_openai): менеджеру всё равно, LM Studio на
том конце или мы.
  GET  /health                  {"ok":true,"model_loaded":bool,"error":str|null}
  GET  /v1/models               {"data":[{"id": "<model>"}]}
  POST /v1/chat/completions     stream=true -> SSE-чанки c choices[0].delta
  POST /admin/unload            выгрузить модель из VRAM (для keep_only_one)

Ограничение v1 (сознательное): tools в запросе ИГНОРИРУЮТСЯ молча — без
400, чтобы менеджер не считал это ошибкой. Родной tool-calling у Qwen3-шаблона
есть, подключим отдельным заходом, когда обкатаем базовый чат.

Живёт в .venv_locallm (setup/install_locallm.py): свежие transformers +
accelerate + bitsandbytes, torch/fastapi/uvicorn — из основного .venv через
main_env.pth (паттерн Voxtral/DreamPC).

Запускается сервером по требованию (server/llm/locallm.py), вручную:
  .venv_locallm\\Scripts\\python.exe workers\\locallm_worker.py --port 8770
"""
import argparse
import json
import logging
import os
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")

# main_env.pth подтягивает torchaudio/torchvision основного venv — текстовой
# модели они не нужны, а их битые .pyd роняли импорт transformers (см.
# workers/dreampc_worker.py, та же шапка, и known_issues.md «торч/CUDA-DLL»).
sys.modules["torchaudio"] = None
sys.modules["torchvision"] = None

import torch  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, StreamingResponse  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(),
              logging.FileHandler(ROOT / "logs" / "locallm_worker.log",
                                  encoding="utf-8")])
log = logging.getLogger("locallm_worker")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # только локальные запросы
    allow_methods=["*"], allow_headers=["*"])

MODEL_REPO = "t-tech/T-lite-it-2.1"
MAX_NEW_TOKENS_DEFAULT = 2048

_model = None
_tokenizer = None
_error = None
_ready = threading.Event()
_infer_lock = threading.Lock()
_load_lock = threading.Lock()


def _configure_hf_endpoint():
    """Авто-выбор зеркала/офлайна перед КАЖДОЙ попыткой загрузки — ожившая
    сеть/VPN подхватывается без перезапуска воркера (копия логики
    dreampc_worker.py, там подробные комментарии про снятые константы)."""
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
        os.environ.pop("HF_ENDPOINT", None)
        log.info("huggingface.co и hf-mirror.com недоступны — офлайн-режим "
                 "(нужна уже скачанная модель в models/hf)")

    offline = bool(os.environ.get("HF_HUB_OFFLINE"))
    endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co")
    hub = sys.modules.get("huggingface_hub")
    if hub is not None:
        try:
            hub.constants.HF_HUB_OFFLINE = offline
            hub.constants.ENDPOINT = endpoint
        except Exception:
            pass
    tfh = sys.modules.get("transformers.utils.hub")
    if tfh is not None and hasattr(tfh, "_is_offline_mode"):
        try:
            tfh._is_offline_mode = offline
        except Exception:
            pass


def _try_load():
    """(Пере)пытается загрузить модель. Идемпотентно и потокобезопасно;
    после неудачи (сеть моргнула) следующая попытка пробует заново, а не
    отдаёт вечно закэшированную ошибку."""
    global _model, _tokenizer, _error
    if _model is not None:
        return
    with _load_lock:
        if _model is not None:
            return
        _error = None
        try:
            if not torch.cuda.is_available():
                raise RuntimeError(
                    "torch не видит CUDA в .venv_locallm — отказываюсь "
                    "грузить 8B-модель на CPU (забьёт ОЗУ). Скорее всего, "
                    "pip притащил CPU-only torch поверх main_env.pth — "
                    "переустанови окружение: python setup/install_locallm.py "
                    "--remove, затем установка заново.")
            _configure_hf_endpoint()
            from transformers import (AutoModelForCausalLM, AutoTokenizer,
                                      BitsAndBytesConfig)
            from _hf_progress import DownloadProgressLogger
            log.info("Загружаю %s (первый раз — скачивание весов ~16 ГБ bf16 "
                     "в models/hf; в VRAM ложится в 4 битах ~5.5 ГБ)…",
                     MODEL_REPO)
            with DownloadProgressLogger(log, ROOT / "models" / "hf", MODEL_REPO,
                                         label=MODEL_REPO):
                tok = AutoTokenizer.from_pretrained(MODEL_REPO)
                bnb = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_compute_dtype=torch.bfloat16,
                    bnb_4bit_use_double_quant=True,
                )
                model = AutoModelForCausalLM.from_pretrained(
                    MODEL_REPO,
                    quantization_config=bnb,
                    dtype=torch.bfloat16,
                    device_map="auto",
                )
            model.eval()
            _tokenizer = tok
            _model = model  # последним — до этого момента «не готова»
            log.info("Модель готова (device=%s)",
                     next(_model.parameters()).device)
        except Exception as e:
            _error = str(e)
            log.exception("Не удалось загрузить модель")
        finally:
            _ready.set()


def _unload():
    """Выгружает модель из VRAM (пара к manager.unload_model)."""
    global _model, _tokenizer
    with _load_lock:
        _model = None
        _tokenizer = None
        _ready.clear()
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    log.info("Модель выгружена из памяти")


# ---------------------- подготовка сообщений ----------------------
def _sanitize_messages(messages):
    """OpenAI-сообщения -> вид, который переварит chat_template Qwen3.

    - content-списки (мультимодальный формат с картинками) сплющиваем в
      текст: у этой модели нет зрения, шлём только текстовые куски;
    - роль tool превращаем в user-сообщение с пометкой (tools в v1 не
      поддерживаем, но менеджер может дослать историю с такими ролями —
      не падать же из-за этого);
    - незнакомые роли -> user."""
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
            # ассистентский ход «вызвала инструмент» без текста — шаблону
            # без tools такое не скормить, заменяем текстовой заглушкой
            content = content or "(вызов инструмента)"
        if role not in ("system", "user", "assistant"):
            role = "user"
        out.append({"role": role, "content": content})
    # system только первым — как в gguf-воркере (шаблон Qwen), см. коммент там
    sys_parts = [m["content"] for m in out if m["role"] == "system" and m["content"]]
    rest = [m for m in out if m["role"] != "system"]
    if sys_parts:
        return [{"role": "system", "content": "\n\n".join(sys_parts)}] + rest
    return rest


# ---------------------- OpenAI-совместимые ручки ----------------------
@app.get("/health")
def health():
    return {"ok": True, "model_loaded": _model is not None, "error": _error}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": MODEL_REPO, "object": "model",
                                        "owned_by": "saika"}]}


@app.post("/admin/unload")
def admin_unload():
    _unload()
    return {"ok": True}


def _chunk(rid, created, delta, finish=None):
    return ("data: " + json.dumps({
        "id": rid, "object": "chat.completion.chunk", "created": created,
        "model": MODEL_REPO,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }, ensure_ascii=False) + "\n\n")


def _generate_stream(messages, temperature, max_new_tokens, enable_thinking):
    """SSE-генератор OpenAI-чанков."""
    rid = "chatcmpl-" + uuid.uuid4().hex[:12]
    created = int(time.time())

    _ready.wait(timeout=1800)
    if _model is None:
        _try_load()  # первая попытка могла упасть из-за сети — пробуем тут
    if _error:
        yield _chunk(rid, created, {"content": f"[ошибка LocalLM: {_error}]"},
                     "stop")
        yield "data: [DONE]\n\n"
        return
    if not _infer_lock.acquire(blocking=False):
        yield _chunk(rid, created,
                     {"content": "[LocalLM уже занята генерацией]"}, "stop")
        yield "data: [DONE]\n\n"
        return
    try:
        from transformers import TextIteratorStreamer
        msgs = _sanitize_messages(messages)
        try:
            text_in = _tokenizer.apply_chat_template(
                msgs, add_generation_prompt=True, tokenize=False,
                enable_thinking=enable_thinking)
        except TypeError:
            # шаблон без параметра enable_thinking (не-Qwen модель)
            text_in = _tokenizer.apply_chat_template(
                msgs, add_generation_prompt=True, tokenize=False)
        enc = _tokenizer([text_in], return_tensors="pt").to(_model.device)

        streamer = TextIteratorStreamer(
            _tokenizer, skip_prompt=True, skip_special_tokens=True)
        gen_kwargs = dict(
            **enc, streamer=streamer,
            max_new_tokens=max_new_tokens,
            do_sample=temperature > 0,
            pad_token_id=_tokenizer.pad_token_id or _tokenizer.eos_token_id,
        )
        if temperature > 0:
            gen_kwargs["temperature"] = float(temperature)
            gen_kwargs["top_p"] = 0.95
        err_box = {}

        def _run():
            try:
                with torch.no_grad():
                    _model.generate(**gen_kwargs)
            except Exception as e:  # ошибку доносим в основной поток
                err_box["e"] = e
                try:
                    streamer.end()
                except Exception:
                    pass

        t = threading.Thread(target=_run, daemon=True)
        t0 = time.monotonic()
        t.start()

        yield _chunk(rid, created, {"role": "assistant"})
        n_chars = 0
        # Раздумья Qwen3 (<think>…</think>) при enable_thinking=False шаблон
        # не генерит вовсе; при включённых — отдаём как есть, серверная
        # сторона уже умеет их прятать (как с другими think-моделями).
        for piece in streamer:
            if not piece:
                continue
            n_chars += len(piece)
            yield _chunk(rid, created, {"content": piece})
        t.join(timeout=5)
        if err_box.get("e") is not None and n_chars == 0:
            yield _chunk(rid, created,
                         {"content": f"[ошибка генерации: {err_box['e']}]"})
        elapsed = max(time.monotonic() - t0, 0.001)
        log.info("Ответ: ~%d символов за %.1fс", n_chars, elapsed)
        yield _chunk(rid, created, {}, "stop")
        yield "data: [DONE]\n\n"
    except Exception as e:
        log.exception("Ошибка генерации")
        yield _chunk(rid, created, {"content": f"[ошибка LocalLM: {e}]"},
                     "stop")
        yield "data: [DONE]\n\n"
    finally:
        _infer_lock.release()


@app.post("/v1/chat/completions")
def chat_completions(payload: dict):
    messages = payload.get("messages") or []
    temperature = float(payload.get("temperature", 0.8))
    max_new_tokens = int(payload.get("max_tokens")
                         or payload.get("max_completion_tokens")
                         or MAX_NEW_TOKENS_DEFAULT)
    # менеджер шлёт chat_template_kwargs={"enable_thinking": False}, когда
    # тумблер 💭 выключен — понимаем его так же, как llama.cpp/LM Studio
    ctk = payload.get("chat_template_kwargs") or {}
    enable_thinking = bool(ctk.get("enable_thinking", True))
    # tools игнорируем молча (см. докстринг модуля) — это не ошибка

    if payload.get("stream", False):
        return StreamingResponse(
            _generate_stream(messages, temperature, max_new_tokens,
                             enable_thinking),
            media_type="text/event-stream")

    # не-стримовый режим (на всякий случай — менеджер всегда стримит)
    text = ""
    for chunk in _generate_stream(messages, temperature, max_new_tokens,
                                  enable_thinking):
        if chunk.startswith("data: ") and "[DONE]" not in chunk:
            try:
                delta = json.loads(chunk[6:])["choices"][0]["delta"]
                text += delta.get("content") or ""
            except Exception:
                pass
    return JSONResponse({
        "id": "chatcmpl-" + uuid.uuid4().hex[:12],
        "object": "chat.completion", "created": int(time.time()),
        "model": MODEL_REPO,
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": text}}],
    })


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--model", default=MODEL_REPO)
    ap.add_argument("--max-new-tokens", type=int, default=MAX_NEW_TOKENS_DEFAULT)
    args = ap.parse_args()
    MODEL_REPO = args.model
    MAX_NEW_TOKENS_DEFAULT = args.max_new_tokens
    (ROOT / "logs").mkdir(exist_ok=True)
    log.info("LocalLM воркер: модель=%s, порт=%s", MODEL_REPO, args.port)
    threading.Thread(target=_try_load, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
