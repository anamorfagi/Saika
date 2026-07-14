"""Воркер Voxtral Mini 4B Realtime (Mistral). Живёт в .venv_voxtral.

Запускается сервером автоматически (server/stt/external.py), вручную:
  .venv_voxtral\\Scripts\\python.exe workers\\voxtral_worker.py --port 8766

Требует в своём окружении transformers>=5.2 и mistral-common[audio]
(ставит setup/install_voxtral.bat); torch/numpy/fastapi берутся из основного
.venv через main_env.pth.
"""
import argparse
import logging
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# кэши моделей — в папке проекта (как у всего остального)
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import numpy as np  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(),
              logging.FileHandler(ROOT / "logs" / "voxtral_worker.log",
                                  encoding="utf-8")])
log = logging.getLogger("voxtral_worker")

app = FastAPI()
_model = None
_processor = None
_error = None
_ready = threading.Event()
_infer_lock = threading.Lock()
MODEL_REPO = "mistralai/Voxtral-Mini-4B-Realtime-2602"


def _load_model():
    global _model, _processor, _error
    try:
        import torch
        from transformers import (AutoProcessor,
                                  VoxtralRealtimeForConditionalGeneration)
        log.info("Загружаю %s (первый раз — скачивание ~9 ГБ)…", MODEL_REPO)
        _processor = AutoProcessor.from_pretrained(MODEL_REPO)
        _model = VoxtralRealtimeForConditionalGeneration.from_pretrained(
            MODEL_REPO, device_map="auto",
            dtype=torch.bfloat16 if torch.cuda.is_available()
            else torch.float32)
        log.info("Модель готова (device=%s)", _model.device)
    except Exception as e:
        _error = str(e)
        log.exception("Не удалось загрузить модель")
    finally:
        _ready.set()


@app.get("/health")
def health():
    return {"ok": True, "model_loaded": _model is not None, "error": _error}


@app.post("/transcribe")
async def transcribe(request: Request, sr: int = 16000):
    _ready.wait(timeout=1800)  # первая загрузка может качать модель
    if _error:
        return {"error": _error}
    body = await request.body()
    pcm = np.frombuffer(body, dtype=np.int16)
    audio = pcm.astype(np.float32) / 32768.0

    target_sr = _processor.feature_extractor.sampling_rate
    if sr != target_sr:
        import soxr
        audio = soxr.resample(audio, sr, target_sr)

    with _infer_lock:
        inputs = _processor(audio, return_tensors="pt")
        inputs = inputs.to(_model.device, dtype=_model.dtype)
        out = _model.generate(**inputs)
    text = _processor.batch_decode(out, skip_special_tokens=True)[0]
    return {"text": text.strip()}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--model", default=MODEL_REPO)
    args = ap.parse_args()
    MODEL_REPO = args.model
    (ROOT / "logs").mkdir(exist_ok=True)
    # модель грузим в фоне — /health отвечает сразу, сервер не ждёт
    threading.Thread(target=_load_model, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
