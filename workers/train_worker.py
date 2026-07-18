"""Воркер дообучения характера Сайки — QLoRA через unsloth + trl SFTTrainer.

Живёт в .venv_train (ставит setup/install_train.py) — отдельно от основного
окружения, потому что unsloth тянет свою проверенную связку torch/xformers/
bitsandbytes, и мешать её с основным venv (Qwen3-TTS/faster-whisper и т.д.)
рискованно (см. docstring install_train.py).

Запускается сервером по требованию (server/llm/train_manager.py), вручную:
  .venv_train\\Scripts\\python.exe workers\\train_worker.py --port 8769

Протокол (обычный HTTP, не SSE — обучение идёт долго, UI просто поллит
/status раз в 1-2 секунды, как и install_status у DreamPC):
  GET  /health
  POST /start  {base_model, dataset_path, lora_r, lora_alpha, lora_dropout,
                learning_rate, epochs, batch_size, grad_accum, max_seq_len,
                output_name}
       -> {"ok": true}  (обучение стартует в фоновом потоке)
  GET  /status -> {"running", "step", "total_steps", "loss", "tokens_per_sec",
                    "log_tail", "done", "ok", "error", "output_dir"}
  POST /stop   -> {"ok": true}  (мягкая остановка на следующем шаге)
  POST /export_gguf {"output_name", "quant"} -> {"ok": true, "path": "..."}
       (сборка LoRA в базовую модель + экспорт в GGUF, готовый для Ollama)
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

logging.basicConfig(level=logging.INFO,
                     format="%(asctime)s train_worker %(levelname)s %(message)s")
log = logging.getLogger("train_worker")


def _configure_hf_endpoint():
    """Тот же авто-выбор зеркала/офлайна, что и у остальных воркеров —
    перепроверяется перед каждым запуском обучения, не один раз при старте."""
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
        log.info("huggingface.co и hf-mirror.com недоступны — офлайн (нужна "
                 "уже скачанная базовая модель в models/hf)")


# ---------------------------------------------------------------- состояние

STATE = {
    "running": False,
    "step": 0,
    "total_steps": 0,
    "loss": None,
    "tokens_per_sec": None,
    "log_tail": [],
    "done": False,
    "ok": False,
    "error": None,
    "output_dir": None,
}
_stop_flag = threading.Event()
_lock = threading.Lock()


def _log_line(text: str):
    log.info(text)
    with _lock:
        STATE["log_tail"].append(text)
        STATE["log_tail"] = STATE["log_tail"][-30:]


def _load_messages_dataset(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _run_training(cfg: dict):
    global _stop_flag
    _stop_flag.clear()
    with _lock:
        STATE.update(running=True, step=0, total_steps=0, loss=None,
                     tokens_per_sec=None, done=False, ok=False, error=None,
                     log_tail=[])

    try:
        _configure_hf_endpoint()
        _log_line(f"Загружаю базовую модель {cfg['base_model']} (4-бит)…")

        from unsloth import FastLanguageModel
        import torch
        from datasets import Dataset
        from trl import SFTTrainer, SFTConfig
        from transformers import TrainerCallback

        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=cfg["base_model"],
            max_seq_length=cfg["max_seq_len"],
            load_in_4bit=True,
            dtype=None,  # unsloth сама выберет bf16/fp16 под железо
        )
        model = FastLanguageModel.get_peft_model(
            model,
            r=cfg["lora_r"],
            lora_alpha=cfg["lora_alpha"],
            lora_dropout=cfg["lora_dropout"],
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                            "gate_proj", "up_proj", "down_proj"],
            use_gradient_checkpointing="unsloth",
        )

        _log_line("Готовлю датасет…")
        raw = _load_messages_dataset(Path(cfg["dataset_path"]))
        texts = []
        for rec in raw:
            msgs = rec["messages"]
            texts.append(tokenizer.apply_chat_template(
                msgs, tokenize=False, add_generation_prompt=False))
        ds = Dataset.from_dict({"text": texts})
        _log_line(f"Диалогов в датасете: {len(ds)}")

        out_dir = ROOT / "training" / "runs" / cfg["output_name"]
        out_dir.mkdir(parents=True, exist_ok=True)
        with _lock:
            STATE["output_dir"] = str(out_dir)

        args = SFTConfig(
            output_dir=str(out_dir),
            per_device_train_batch_size=cfg["batch_size"],
            gradient_accumulation_steps=cfg["grad_accum"],
            num_train_epochs=cfg["epochs"],
            learning_rate=cfg["learning_rate"],
            logging_steps=1,
            save_strategy="epoch",
            optim="adamw_8bit",
            lr_scheduler_type="cosine",
            warmup_ratio=0.05,
            bf16=torch.cuda.is_bf16_supported(),
            fp16=not torch.cuda.is_bf16_supported(),
            max_seq_length=cfg["max_seq_len"],
            dataset_text_field="text",
            report_to="none",
        )

        _t0 = time.time()
        _tok_count = 0

        class ProgressCallback(TrainerCallback):
            def on_train_begin(self, args, state, control, **kw):
                with _lock:
                    STATE["total_steps"] = state.max_steps

            def on_log(self, args, state, control, logs=None, **kw):
                nonlocal _tok_count
                logs = logs or {}
                loss = logs.get("loss")
                elapsed = max(time.time() - _t0, 0.001)
                with _lock:
                    STATE["step"] = state.global_step
                    if loss is not None:
                        STATE["loss"] = round(loss, 4)
                    STATE["tokens_per_sec"] = round(
                        (state.global_step * cfg["batch_size"] * cfg["max_seq_len"])
                        / elapsed, 1)
                if loss is not None:
                    _log_line(f"шаг {state.global_step}/{state.max_steps} · "
                             f"loss {loss:.4f}")

            def on_step_end(self, args, state, control, **kw):
                if _stop_flag.is_set():
                    control.should_training_stop = True
                return control

        trainer = SFTTrainer(
            model=model,
            tokenizer=tokenizer,
            train_dataset=ds,
            args=args,
            callbacks=[ProgressCallback()],
        )

        _log_line("Обучение началось…")
        trainer.train()

        _log_line("Сохраняю LoRA-адаптер…")
        trainer.save_model(str(out_dir))
        tokenizer.save_pretrained(str(out_dir))

        with _lock:
            STATE.update(running=False, done=True, ok=True)
        _log_line(f"Готово. Адаптер сохранён в {out_dir}")

    except Exception as e:
        log.exception("Обучение упало")
        with _lock:
            STATE.update(running=False, done=True, ok=False, error=str(e))
        _log_line(f"Ошибка: {e}")


def _run_export(cfg: dict):
    """Слияние LoRA с базовой моделью и экспорт в GGUF для Ollama."""
    try:
        _log_line("Собираю GGUF для Ollama…")
        from unsloth import FastLanguageModel

        out_dir = ROOT / "training" / "runs" / cfg["output_name"]
        gguf_dir = ROOT / "training" / "gguf" / cfg["output_name"]
        gguf_dir.mkdir(parents=True, exist_ok=True)

        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=str(out_dir), max_seq_length=cfg.get("max_seq_len", 1024),
            load_in_4bit=True)
        quant = cfg.get("quant", "q4_k_m")
        model.save_pretrained_gguf(str(gguf_dir), tokenizer,
                                   quantization_method=quant)

        gguf_files = list(gguf_dir.glob("*.gguf"))
        if not gguf_files:
            raise RuntimeError("save_pretrained_gguf не создал .gguf файл")
        gguf_path = gguf_files[0]

        modelfile = gguf_dir / "Modelfile"
        modelfile.write_text(
            f'FROM {gguf_path.name}\n'
            f'PARAMETER temperature 0.8\n',
            encoding="utf-8")

        _log_line(f"GGUF готов: {gguf_path}")
        _log_line(f"Импорт в Ollama: cd {gguf_dir} && "
                 f"ollama create {cfg['output_name']} -f Modelfile")
        with _lock:
            STATE.update(done=True, ok=True,
                        gguf_path=str(gguf_path), modelfile=str(modelfile))
    except Exception as e:
        log.exception("Экспорт в GGUF упал")
        with _lock:
            STATE.update(done=True, ok=False, error=str(e))
        _log_line(f"Ошибка экспорта: {e}")


# ---------------------------------------------------------------- HTTP API

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
import uvicorn  # noqa: E402

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/start")
def start(cfg: dict):
    if STATE["running"]:
        return JSONResponse({"error": "обучение уже идёт"}, status_code=409)
    required_defaults = {
        "lora_r": 16, "lora_alpha": 16, "lora_dropout": 0.0,
        "learning_rate": 2e-4, "epochs": 3, "batch_size": 2,
        "grad_accum": 4, "max_seq_len": 1024, "output_name": "saika-char",
    }
    for k, v in required_defaults.items():
        cfg.setdefault(k, v)
    if "base_model" not in cfg or "dataset_path" not in cfg:
        return JSONResponse({"error": "нужны base_model и dataset_path"},
                            status_code=400)
    threading.Thread(target=_run_training, args=(cfg,), daemon=True).start()
    return {"ok": True}


@app.get("/status")
def status():
    with _lock:
        return dict(STATE)


@app.post("/stop")
def stop():
    _stop_flag.set()
    return {"ok": True}


@app.post("/export_gguf")
def export_gguf(cfg: dict):
    if STATE["running"]:
        return JSONResponse({"error": "дождись окончания обучения"}, status_code=409)
    with _lock:
        STATE.update(done=False, ok=False, error=None)
    threading.Thread(target=_run_export, args=(cfg,), daemon=True).start()
    return {"ok": True}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8769)
    args = ap.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
