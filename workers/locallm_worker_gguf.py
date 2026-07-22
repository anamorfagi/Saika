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
MAX_TOKENS_CAP = 2048  # locallm.max_new_tokens из config.json (см. спавнер)

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
    # Шаблон Qwen в llama.cpp жёстко требует system ТОЛЬКО первым сообщением
    # ("System message must be at the beginning", живой инцидент 2026-07-23:
    # Сайка докидывает «живой контекст» отдельными system-сообщениями посреди
    # диалога — каждый ответ падал этой ошибкой). Склеиваем ВСЕ system в одно
    # первое, порядок остальных сообщений не трогаем.
    sys_parts = [m["content"] for m in out if m["role"] == "system" and m["content"]]
    rest = [m for m in out if m["role"] != "system"]
    if sys_parts:
        return [{"role": "system", "content": "\n\n".join(sys_parts)}] + rest
    return rest


def _filter_think(chunks):
    """Вырезает <think>…</think> из потока OpenAI-чанков. Нужен, когда
    размышления выключены (тумблер 💭), а модель всё равно думает: у Qwen
    тег <think> браузер глотает как неизвестный HTML-элемент, и «мысли»
    вываливаются в чат простым текстом (живой инцидент 2026-07-23 — вместо
    короткого ответа пришло 546 токенов Thinking Process на английском).
    Токены придерживаются ровно настолько, чтобы тег, разрезанный между
    чанками, не просочился."""
    buf, in_think, opened = "", False, False
    proto = None
    for chunk in chunks:
        delta = chunk.get("choices", [{}])[0].get("delta", {})
        tok = delta.get("content")
        if not tok:
            yield chunk
            continue
        proto = chunk
        buf += tok
        out = ""
        while buf:
            if in_think:
                i = buf.find("</think>")
                if i < 0:
                    buf = buf[-len("</think>"):]
                    break
                buf, in_think = buf[i + len("</think>"):], False
                buf = buf.lstrip("\n")  # пустые строки после мыслей не нужны
            else:
                i = buf.find("<think>")
                if i < 0:
                    keep = 0  # возможное начало тега в хвосте — придержать
                    for k in range(min(len("<think>") - 1, len(buf)), 0, -1):
                        if buf.endswith("<think>"[:k]):
                            keep = k
                            break
                    cut = len(buf) - keep
                    out, buf = out + buf[:cut], buf[cut:]
                    break
                out, buf, in_think = out + buf[:i], buf[i + len("<think>"):], True
                opened = True
        if out:
            d = {**chunk,
                 "choices": [{**chunk["choices"][0],
                              "delta": {**delta, "content": out}}]}
            yield d
    if buf and not in_think and proto is not None:  # добить хвост-недотег
        d0 = proto["choices"][0]
        yield {**proto, "choices": [{**d0, "delta": {**d0.get("delta", {}),
                                                     "content": buf}}]}


def _render_prompt(msgs, enable_thinking):
    """Рендерим chat-шаблон из метаданных GGUF САМИ (jinja2), чтобы прокинуть
    enable_thinking. Разбор инцидента 2026-07-23: у Qwen3.5-шаблона generation
    prompt ЗАКАНЧИВАЕТСЯ на '<think>\n' — модель начинает генерить уже ВНУТРИ
    блока размышлений, открывающий тег в вывод не попадает вообще, и фильтр
    по '<think>' в потоке бессилен. Зато при enable_thinking=false шаблон сам
    подставляет пустой блок '<think>\n\n</think>\n\n' — модель отвечает сразу.
    create_chat_completion в llama-cpp-python прокинуть этот параметр не умеет
    (в отличие от LM Studio) — потому рендерим сами и зовём create_completion.
    /no_think-выключатель у Qwen3.5 не работает (проверено там же).
    Вернёт None, если шаблона нет — вызывающий откатится на старый путь."""
    tpl = (getattr(_model, "metadata", None) or {}).get("tokenizer.chat_template")
    if not tpl:
        return None
    import jinja2

    def raise_exception(msg):
        raise ValueError(msg)

    env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
    return env.from_string(tpl).render(
        messages=msgs, add_generation_prompt=True,
        enable_thinking=bool(enable_thinking), tools=None,
        raise_exception=raise_exception)


def _completion_as_chat(raw):
    """Чанки create_completion (text) -> форма chat-чанков (delta.content)."""
    for c in raw:
        ch = c.get("choices", [{}])[0]
        txt = ch.get("text", "")
        yield {"id": c.get("id", ""), "object": "chat.completion.chunk",
               "created": c.get("created", 0), "model": MODEL_REPO,
               "choices": [{"index": 0,
                            "delta": ({"content": txt} if txt else {}),
                            "finish_reason": ch.get("finish_reason")}]}


def _swallow_thinking(chunks):
    """Для ВКЛЮЧЁННЫХ размышлений: промпт кончается '<think>\n', так что всё
    до '</think>' — мысли. Глотаем их (в чат не идут — ровно как LM Studio,
    который отдаёт их отдельным полем, а Сайка его игнорирует), наружу — только
    ответ. На каждый проглоченный кусок отдаём None-сентинел: _stream
    превращает его в SSE-комментарий (keep-alive). Без этого во время долгого
    думания в сокет не пишется НИЧЕГО — и если Сайка бросила запрос (юзер
    сказал новое, «перезапускаю с учётом»), воркер не замечает обрыва и жуёт
    GPU до конца лимита, блокируя следующий запрос (инцидент 2026-07-23:
    «модель не отвечает» — вечный цикл перезапусков поверх зомби-генерации).
    Если мысли съели ВЕСЬ лимит и '</think>' так и не пришёл — честное
    короткое сообщение вместо тишины (и вместо вывала сырых мыслей)."""
    buf, passed, emitted = "", False, False
    proto = None
    for chunk in chunks:
        delta = chunk.get("choices", [{}])[0].get("delta", {})
        tok = delta.get("content")
        if not tok:
            yield chunk
            continue
        if passed:
            if not emitted:  # ведущие \n после </think> — в мусор
                tok = tok.lstrip("\n")
                if not tok:
                    continue
                emitted = True
                chunk = {**chunk,
                         "choices": [{**chunk["choices"][0],
                                      "delta": {**delta, "content": tok}}]}
            yield chunk
            continue
        proto = chunk
        buf += tok
        i = buf.find("</think>")
        if i >= 0:
            passed = True
            rest = buf[i + len("</think>"):].lstrip("\n")
            if rest:
                emitted = True
                yield {**chunk,
                       "choices": [{**chunk["choices"][0],
                                    "delta": {**delta, "content": rest}}]}
        else:
            yield None  # keep-alive: думаем, но сокет живой
    if not passed and buf.strip() and proto is not None:
        log.warning("Мысли заняли весь лимит (%d символов), до ответа не "
                    "дошло — вернула заглушку. Выключи 💭 или подними "
                    "locallm.max_new_tokens.", len(buf))
        d0 = proto["choices"][0]
        yield {**proto, "choices": [{**d0, "delta": {
            **d0.get("delta", {}),
            "content": "[мысли не уложились в лимит токенов — ответа не "
                       "осталось. Выключи 💭 в меню модели или подними "
                       "locallm.max_new_tokens]"}}]}


def _stream(messages, temperature, max_tokens, enable_thinking=True):
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
    # ждём очередь, а не отшиваем сразу: Сайка сама ставит реплики «отвечу
    # следом», и мгновенный отказ превращался в мусорный ответ из 1 токена
    # «[LocalLM уже занята генерацией]» (лог 2026-07-23)
    if not _infer_lock.acquire(timeout=180):
        yield ("data: " + json.dumps({
            "choices": [{"index": 0,
                        "delta": {"content": "[LocalLM занята дольше 3 минут — "
                                             "похоже, генерация зависла]"},
                        "finish_reason": "stop"}]}, ensure_ascii=False)
              + "\n\n")
        yield "data: [DONE]\n\n"
        return
    try:
        msgs = _sanitize_messages(messages)
        t0 = time.monotonic()
        n_chars = 0
        prompt = None
        try:
            prompt = _render_prompt(msgs, enable_thinking)
        except Exception:
            log.exception("Рендер шаблона не удался — откат на "
                          "create_chat_completion")
        if prompt is not None:
            if enable_thinking:
                # мысли легко съедают 2048 целиком, а Сайка max_tokens не
                # шлёт — даём запас, чтобы после думания остался сам ответ
                max_tokens = max(max_tokens, 6144)
            raw = _model.create_completion(
                prompt=prompt, stream=True, temperature=temperature,
                max_tokens=max_tokens, stop=["<|im_end|>"])
            stream = _completion_as_chat(raw)
            # think вкл: всё до </think> — мысли, глотаем; think выкл: шаблон
            # подставил пустой блок, но страхуемся фильтром от протечек тегов
            stream = (_swallow_thinking(stream) if enable_thinking
                      else _filter_think(stream))
        else:
            stream = _model.create_chat_completion(
                    messages=msgs, stream=True,
                    temperature=temperature, max_tokens=max_tokens)
            if not enable_thinking:
                stream = _filter_think(stream)
        for chunk in stream:
            if chunk is None:  # проглоченный think-токен -> keep-alive
                yield ": think\n\n"   # SSE-комментарий, парсеры игнорируют
                continue
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
                     or payload.get("max_completion_tokens")
                     or MAX_TOKENS_CAP)
    max_tokens = min(max_tokens, MAX_TOKENS_CAP)
    think = bool((payload.get("chat_template_kwargs") or {})
                 .get("enable_thinking", True))
    if payload.get("stream", False):
        return StreamingResponse(
            _stream(messages, temperature, max_tokens, enable_thinking=think),
            media_type="text/event-stream")
    text = ""
    for chunk in _stream(messages, temperature, max_tokens,
                         enable_thinking=think):
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
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS_CAP)
    args = ap.parse_args()
    MODEL_REPO = args.repo
    QUANT = args.quant
    N_CTX_DEFAULT = args.n_ctx
    MAX_TOKENS_CAP = args.max_tokens
    (ROOT / "logs").mkdir(exist_ok=True)
    log.info("LocalLM (llama.cpp) воркер: %s / %s, порт=%s, n_ctx=%s",
             MODEL_REPO, QUANT, args.port, N_CTX_DEFAULT)
    threading.Thread(target=_try_load, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
