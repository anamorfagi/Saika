"""Воркер DreamPC — диффузионная LLM LLaDA-8B-Instruct (GSAI-ML).

Экспериментальный модуль: в отличие от Ollama/LM Studio (авторегрессия,
токен за токеном), диффузионная модель шумит весь ответ маской и постепенно
"проявляет" его за N шагов. Инструментов/tool-calling и обычного стриминга
у неё нет, поэтому она не подключена к основному диалоговому пайплайну —
живёт отдельной панелью в UI (кнопка 🧪) для наблюдения за процессом.

Живёт в .venv_dreampc (ставит setup/install_dreampc.py): свежие transformers
+ accelerate + bitsandbytes, torch/fastapi/uvicorn — из основного .venv через
main_env.pth (как у Voxtral).

Запускается сервером по требованию (server/llm/dreampc.py), вручную:
  .venv_dreampc\\Scripts\\python.exe workers\\dreampc_worker.py --port 8768

Протокол: GET /health; POST /generate {"prompt": "...", "steps"?, "gen_length"?,
"block_length"?, "temperature"?} -> Server-Sent Events:
  data: {"type":"step","step":i,"total":steps,"text":"..."}
  data: {"type":"done","text":"...","tokens":N,"elapsed":S,"tps":T,"steps":steps}
  data: {"type":"error","text":"..."}

Diffusion-сэмплинг адаптирован из generate.py оригинального репозитория
ML-GSAI/LLaDA (MIT, https://github.com/ML-GSAI/LLaDA) — там же взят
mask_id=126336 (id спец-токена [MASK] у токенизатора LLaDA).
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
# HF рвёт соединение через 10 сек по умолчанию — на медленной сети 16 ГБ
# LLaDA качаются вечными таймаутами с докачкой. 60 сек = меньше обрывов.
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")

# main_env.pth подключает site-packages ОСНОВНОГO venv (torch/fastapi общие
# с остальной Сайкой) — вместе с ними подтягиваются torchaudio/torchvision,
# поставленные там ради TTS/STT. LLaDA — чистый текст, они ей не нужны
# вообще, а их нативные .pyd на этой машине биты/не того ABI (см.
# known_issues.md, "торч/CUDA-DLL") — transformers при импорте пытается их
# тоже подхватить и падает с "Could not load this library: ...pyd".
# Подделываем неудачный импорт заранее: sys.modules[x]=None — официально
# поддерживаемый способ Python сказать "модуля нет", библиотеки ловят это
# как обычный ImportError и просто работают без аудио/видео-бэкенда.
sys.modules["torchaudio"] = None
sys.modules["torchvision"] = None

def _configure_hf_endpoint():
    """Авто-выбор зеркала/офлайна, как в server/config.py — но перевызывается
    перед КАЖДОЙ попыткой загрузки (не один раз при старте процесса), чтобы
    ожившая сеть/включённый VPN подхватывались без перезапуска воркера.
    ВАЖНО: должно отработать до импорта huggingface_hub/transformers."""
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

    # huggingface_hub/transformers СНИМАЮТ эти env в константы при импорте.
    # Если первая попытка загрузки прошла в офлайне, то при ретрае в том же
    # процессе одной смены env недостаточно — библиотеки держат старый
    # снимок («outgoing traffic has been disabled», лог 2026-07-15 11:18).
    # Патчим константы уже импортированных модулей (best effort).
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

import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(),
              logging.FileHandler(ROOT / "logs" / "dreampc_worker.log",
                                  encoding="utf-8")])
log = logging.getLogger("dreampc_worker")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # только локальные запросы из ui/index.html
    allow_methods=["*"], allow_headers=["*"])

MODEL_REPO = "GSAI-ML/LLaDA-8B-Instruct"
# id спец-токена [MASK] у разных диффузионных моделей РАЗНЫЙ. Захардкоженный
# один id ломал переключение моделей. Держим карту + авто-выбор по репо;
# можно переопределить в config.json (dreampc.mask_id) или через --mask-id.
MASK_IDS = {
    "GSAI-ML/LLaDA-8B-Instruct": 126336,
    "GSAI-ML/LLaDA-8B-Base": 126336,
    "GSAI-ML/LLaDA-1.5": 126336,
    "inclusionAI/LLaDA-MoE-7B-A1B-Instruct": 156895,
    "inclusionAI/LLaDA-MoE-7B-A1B-Base": 156895,
}
MASK_ID = 126336  # выставляется в __main__ по модели (см. MASK_IDS)

_model = None
_tokenizer = None
_mask_str = None
_error = None
_ready = threading.Event()
_infer_lock = threading.Lock()
_load_lock = threading.Lock()


def _try_load():
    """(Пере)пытается загрузить модель. Потокобезопасно и идемпотентно:
    если модель уже загружена — не трогает; если предыдущая попытка упала
    (например, сеть моргнула) — пробует заново, а не отдаёт вечно старую
    закэшированную ошибку (баг первой версии воркера)."""
    global _model, _tokenizer, _mask_str, _error
    if _model is not None:
        return
    with _load_lock:
        if _model is not None:  # кто-то успел загрузить, пока ждали лок
            return
        _error = None
        try:
            if not torch.cuda.is_available():
                # НЕ падаем молча на CPU: модель на 8B параметров в float32
                # на процессоре — это ~32 ГБ ОЗУ, забивает память в ноль и
                # вешает систему свопом (реальный инцидент 2026-07-15, когда
                # .venv_dreampc случайно получил свой CPU-only torch). Лучше
                # честная ошибка, чем повторение этого.
                raise RuntimeError(
                    "torch не видит CUDA в .venv_dreampc — отказываюсь "
                    "грузить 8B-модель на CPU (забьёт ОЗУ). Скорее всего, "
                    "при установке pip подтянул свой CPU-only torch поверх "
                    "main_env.pth — см. setup/known_issues.md, «DreamPC»/"
                    "переустанови окружение (python setup/install_dreampc.py "
                    "--remove, затем установка заново).")
            _configure_hf_endpoint()
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
            log.info("Загружаю %s (первый раз — скачивание ~16 ГБ bf16-весов, "
                      "квантование в 4 бита происходит уже на лету)…", MODEL_REPO)
            tok = AutoTokenizer.from_pretrained(MODEL_REPO, trust_remote_code=True)
            if tok.padding_side != "left":
                tok.padding_side = "left"
            bnb = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
            )
            model = AutoModelForCausalLM.from_pretrained(
                MODEL_REPO, trust_remote_code=True,
                quantization_config=bnb if torch.cuda.is_available() else None,
                dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
                device_map="auto" if torch.cuda.is_available() else None,
            )
            if not torch.cuda.is_available():
                model = model.to("cpu")
            model.eval()
            _tokenizer = tok
            _mask_str = tok.decode([MASK_ID])
            _model = model  # выставляем последним — до этого момента модель "не готова"
            log.info("Модель готова (device=%s)", next(_model.parameters()).device)
        except Exception as e:
            _error = str(e)
            log.exception("Не удалось загрузить модель")
        finally:
            _ready.set()


@app.get("/health")
def health():
    return {"ok": True, "model_loaded": _model is not None, "error": _error}


# ---------------------- diffusion sampling (адаптировано из ML-GSAI/LLaDA) ----------------------
def _add_gumbel_noise(logits, temperature):
    if temperature == 0:
        return logits
    logits = logits.to(torch.float64)
    noise = torch.rand_like(logits, dtype=torch.float64)
    gumbel_noise = (-torch.log(noise)) ** temperature
    return logits.exp() / gumbel_noise


def _num_transfer_tokens(mask_index, steps):
    mask_num = mask_index.sum(dim=1, keepdim=True)
    base = mask_num // steps
    remainder = mask_num % steps
    out = torch.zeros(mask_num.size(0), steps, device=mask_index.device,
                      dtype=torch.int64) + base
    for i in range(mask_num.size(0)):
        out[i, :remainder[i]] += 1
    return out


@torch.no_grad()
def _diffusion_generate(prompt_ids, steps, gen_length, block_length, temperature):
    """Генератор: на каждом шаге отдаёт (step_idx, decoded_text_so_far)."""
    device = next(_model.parameters()).device
    x = torch.full((1, prompt_ids.shape[1] + gen_length), MASK_ID,
                   dtype=torch.long, device=device)
    x[:, :prompt_ids.shape[1]] = prompt_ids.to(device)
    prompt_len = prompt_ids.shape[1]
    prompt_index = (x != MASK_ID)

    assert gen_length % block_length == 0, "gen_length должен делиться на block_length"
    num_blocks = gen_length // block_length
    assert steps % num_blocks == 0, "steps должен делиться на число блоков"
    steps_per_block = steps // num_blocks

    step_i = 0
    for num_block in range(num_blocks):
        lo = prompt_len + num_block * block_length
        hi = prompt_len + (num_block + 1) * block_length
        block_mask_index = (x[:, lo:hi] == MASK_ID)
        transfer_counts = _num_transfer_tokens(block_mask_index, steps_per_block)
        for i in range(steps_per_block):
            mask_index = (x == MASK_ID)
            logits = _model(x).logits
            logits_noised = _add_gumbel_noise(logits, temperature=temperature)
            x0 = torch.argmax(logits_noised, dim=-1)

            p = F.softmax(logits, dim=-1)
            x0_p = torch.squeeze(torch.gather(p, dim=-1, index=x0.unsqueeze(-1)), -1)
            x0_p[:, hi:] = -np.inf

            x0 = torch.where(mask_index, x0, x)
            confidence = torch.where(mask_index, x0_p, torch.tensor(-np.inf, device=device))

            transfer_index = torch.zeros_like(x0, dtype=torch.bool)
            k = int(transfer_counts[0, i].item())
            if k > 0:
                _, select_index = torch.topk(confidence[0], k=k)
                transfer_index[0, select_index] = True
            x[transfer_index] = x0[transfer_index]

            step_i += 1
            text = _tokenizer.decode(x[0, prompt_len:], skip_special_tokens=False)
            text = text.replace(_mask_str, "▓").strip()
            yield step_i, text

    final = _tokenizer.decode(x[0, prompt_len:], skip_special_tokens=True).strip()
    yield step_i, final


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _stream(prompt, steps, gen_length, block_length, temperature):
    _ready.wait(timeout=1800)
    if _model is None:
        # первая попытка (в фоне при старте) могла не удаться из-за сети —
        # пробуем ещё раз прямо в этом запросе, а не насовсем застреваем
        # на старой ошибке (см. _try_load)
        _try_load()
    if _error:
        yield _sse({"type": "error", "text": _error})
        return
    if not _infer_lock.acquire(blocking=False):
        yield _sse({"type": "error", "text": "воркер уже занят генерацией"})
        return
    try:
        messages = [{"role": "user", "content": prompt}]
        text_in = _tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False)
        enc = _tokenizer(text_in, add_special_tokens=False, return_tensors="pt")
        prompt_ids = enc["input_ids"]

        t0 = time.monotonic()
        last_text = ""
        for step_i, text in _diffusion_generate(
                prompt_ids, steps, gen_length, block_length, temperature):
            last_text = text
            yield _sse({"type": "step", "step": step_i, "total": steps, "text": text})
        elapsed = max(time.monotonic() - t0, 0.001)
        tps = round(gen_length / elapsed, 1)
        yield _sse({"type": "done", "text": last_text, "tokens": gen_length,
                    "elapsed": round(elapsed, 1), "tps": tps, "steps": steps})
    except Exception as e:
        log.exception("Ошибка генерации")
        yield _sse({"type": "error", "text": str(e)})
    finally:
        _infer_lock.release()


@app.post("/generate")
def generate_endpoint(payload: dict):
    prompt = payload.get("prompt", "")
    steps = int(payload.get("steps", 128))
    gen_length = int(payload.get("gen_length", 128))
    block_length = int(payload.get("block_length", 32))
    temperature = float(payload.get("temperature", 0.0))
    return StreamingResponse(
        _stream(prompt, steps, gen_length, block_length, temperature),
        media_type="text/event-stream")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8768)
    ap.add_argument("--model", default=MODEL_REPO)
    ap.add_argument("--mask-id", type=int, default=0,
                    help="id токена [MASK]; 0 = авто по модели (MASK_IDS)")
    args = ap.parse_args()
    MODEL_REPO = args.model
    # mask-токен: явный аргумент > карта по модели > дефолт LLaDA-8B
    MASK_ID = args.mask_id or MASK_IDS.get(MODEL_REPO, 126336)
    log.info("DreamPC воркер: модель=%s, mask_id=%s", MODEL_REPO, MASK_ID)
    (ROOT / "logs").mkdir(exist_ok=True)
    threading.Thread(target=_try_load, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
