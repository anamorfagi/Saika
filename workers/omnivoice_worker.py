"""Воркер OmniVoice (k2-fsa) — клон голоса Сайки. Живёт в .venv_omni.

ПОЧЕМУ ОТДЕЛЬНОЕ ОКРУЖЕНИЕ. OmniVoice тестирован на torch 2.8, а у нас в
основном .venv стоит torch cu130 под RTX. Ставить его зависимости в общий
venv нельзя: pip утянет свою версию torch и утащит за собой faster-whisper,
GigaAM и Qwen3-TTS. Тот же приём, что уже проверен на Voxtral: пакет
ставится в своё окружение, а torch/numpy/fastapi берутся из основного через
main_env.pth (см. setup/install_omnivoice.py).

ЗАЧЕМ ВООБЩЕ. Из всего, что умеет клонировать голос, OmniVoice —
единственный под **Apache-2.0**: XTTS-v2 под некоммерческой Coqui CPML, у
Silero лицензия только образовательная. Для проекта, который планируется
монетизировать, это решает.

Ручной запуск:
  .venv_omni\\Scripts\\python.exe workers\\omnivoice_worker.py --port 8772

Протокол тот же, что у остальных воркеров проекта:
  GET  /health        -> {"ok", "model_loaded", "loading", "error"}
  POST /tts           {"text", "ref", "ref_text", "lang"} -> audio/wav
  POST /admin/unload  выгрузить модель из памяти
"""
import argparse
import asyncio
import io
import logging
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# кэши моделей — в папке проекта, как у всего остального (переносимый диск)
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")

# ЛОГИРОВАНИЕ НАСТРАИВАЕМ ДО ТЯЖЁЛЫХ ИМПОРТОВ (2026-07-26). Раньше оно
# стояло после import numpy/uvicorn/fastapi — и если падал сам импорт
# (битая DLL, несовместимый numpy из main_env.pth), файл лога вообще не
# создавался. Снаружи это выглядело как «воркер молча не стартовал».
(ROOT / "logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(),
              logging.FileHandler(ROOT / "logs" / "omnivoice_worker.log",
                                  encoding="utf-8")])
log = logging.getLogger("omnivoice_worker")

try:
    import numpy as np  # noqa: E402
    import uvicorn  # noqa: E402
    from fastapi import FastAPI, Response  # noqa: E402
except Exception:
    # трассировка уедет и в файл, и в stdout (его перехватывает спавнер) —
    # чтобы причина была видна с обеих сторон
    log.exception("Не смогла импортировать базовые пакеты. Обычные причины: "
                  "main_env.pth указывает не туда, или numpy/torch из "
                  "основного .venv несовместимы с этим Python")
    raise

app = FastAPI()
_model = None
_error = None
_loading = False
_ready = threading.Event()
_lock = threading.Lock()          # синтез по одному: модель не реентерабельна
ARGS = None


def _load_blocking():
    """Грузим в фоне. НЕ в event loop: первая загрузка качает веса, и если
    держать её в цикле — /health перестаёт отвечать, сервер решает, что
    воркер умер, и спавнит второго на тот же порт (грабля с Voxtral)."""
    global _model, _error, _loading
    _loading = True
    try:
        import torch
        from omnivoice import OmniVoice
        dev = "cuda:0" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if dev.startswith("cuda") else torch.float32
        log.info("Загружаю OmniVoice на %s (%s)…", dev, dtype)
        _model = OmniVoice.from_pretrained(ARGS.model, device_map=dev,
                                           dtype=dtype)
        log.info("OmniVoice готов")
        _ready.set()
    except Exception as e:
        _error = f"{type(e).__name__}: {e}"
        log.exception("OmniVoice не загрузился")
    finally:
        _loading = False


@app.get("/health")
def health():
    return {"ok": _error is None, "model_loaded": _model is not None,
            "loading": _loading, "error": _error}


@app.post("/admin/unload")
def unload():
    global _model
    with _lock:
        _model = None
    _ready.clear()
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass
    log.info("Модель выгружена по просьбе сервера")
    return {"ok": True}


def _synth(text, ref, ref_text, lang, steps):
    with _lock:
        if _model is None:
            raise RuntimeError("модель не загружена")
        kw = {"text": text}
        if ref:
            kw["ref_audio"] = ref
            # ref_text обязателен для клонирования: модель выравнивает
            # образец по его расшифровке. У нас она уже есть в конфиге
            # (tts.voice_ref_text) — сервер её и присылает.
            kw["ref_text"] = ref_text or ""
        if lang:
            kw["lang"] = lang
        if steps:
            kw["num_step"] = int(steps)
        try:
            audio = _model.generate(**kw)
        except TypeError:
            # версия постарше: могла не знать lang/num_step — пробуем без них
            kw.pop("lang", None)
            kw.pop("num_step", None)
            audio = _model.generate(**kw)
    a = np.asarray(audio, dtype=np.float32)
    if a.ndim > 1:
        a = a[0]
    return a


@app.post("/tts")
async def tts(payload: dict):
    if _model is None:
        # УПАЛА ЗАГРУЗКА — ЭТО НЕ «ЕЩЁ ГРУЖУСЬ» (2026-08-15). Раньше
        # ответ был один на оба случая: loading=True плюс текст ошибки
        # сбоку. Сервер смотрел на loading, говорил «OmniVoice ещё
        # грузит модель» и повторял это вечно — а модель не грузилась
        # с 13 августа: ImportError HiggsAudioV2TokenizerModel, потому
        # что transformers подхватывается из основного .venv и он
        # старее, чем нужно omnivoice. Владелец полтора дня слушал
        # «греется» вместо «сломано вот здесь, чинится вот так».
        if _error:
            return {"error": _error, "loading": False}
        # мгновенный ответ вместо ожидания: сервер уведёт озвучку на
        # следующий движок, а не будет висеть минуты на первой загрузке
        if _loading or not _ready.is_set():
            if not _loading:
                threading.Thread(target=_load_blocking, daemon=True).start()
            return {"loading": True, "error": None}
    text = str(payload.get("text", "")).strip()
    if not text:
        return {"error": "пустой текст"}
    try:
        a = await asyncio.to_thread(
            _synth, text, payload.get("ref"), payload.get("ref_text"),
            payload.get("lang", "ru"), payload.get("steps"))
    except Exception as e:
        log.exception("синтез не удался")
        return {"error": f"{type(e).__name__}: {e}"}
    import soundfile as sf
    buf = io.BytesIO()
    sf.write(buf, a, ARGS.sample_rate, format="WAV", subtype="FLOAT")
    return Response(content=buf.getvalue(), media_type="audio/wav")


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8772)
    ap.add_argument("--model", default="k2-fsa/OmniVoice")
    ap.add_argument("--sample-rate", dest="sample_rate", type=int, default=24000)
    ARGS = ap.parse_args()
    # греем сразу в фоне: к первой фразе модель обычно уже готова
    threading.Thread(target=_load_blocking, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=ARGS.port, log_level="warning")


if __name__ == "__main__":
    main()
