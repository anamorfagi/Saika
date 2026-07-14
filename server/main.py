"""Сайка — главный сервер.

FastAPI + WebSocket. Браузер шлёт PCM с микрофона, сервер возвращает
распознанный текст, стрим ответа LLM и стрим озвучки.
Все подсистемы обёрнуты в самодиагностику: ошибка -> событие в UI ->
автопереключение -> фоновая починка.
"""
import asyncio
import json
import logging
import queue
import subprocess
import threading
import webbrowser
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from server.config import CFG, ROOT
from server.persona import build_system_prompt
from server.llm import manager as llm
from server.stt.manager import STTManager
from server.tts.manager import TTSManager, split_sentences
from server.memory.memory import Memory, start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(),
              logging.FileHandler(ROOT / "logs" / "saika.log", encoding="utf-8")])
log = logging.getLogger("saika")
# шумные логгеры: sox ворчит про отсутствие бинарника (он не нужен),
# qwen_tts сыпет INFO про дефолтные конфиги при каждой загрузке
logging.getLogger("sox").setLevel(logging.ERROR)
logging.getLogger("qwen_tts").setLevel(logging.WARNING)

app = FastAPI(title="Saika")

PROBLEMS: list[dict] = []          # лента проблем/починок для UI
EVENT_CLIENTS: set = set()          # активные websockets


def report_problem(component, error, action):
    item = {"component": component, "error": error, "action": action}
    PROBLEMS.append(item)
    del PROBLEMS[:-50]
    for ws_queue in list(EVENT_CLIENTS):
        try:
            ws_queue.put_nowait({"type": "problem", **item})
        except Exception:
            pass


stt = STTManager(on_problem=report_problem)
tts = TTSManager(on_problem=report_problem)
memory = Memory()


# ---------------------- REST ----------------------
@app.get("/")
def index():
    # no-store: иначе браузер кэширует старый UI и после обновлений
    # интерфейс ведёт себя странно (пропадают списки и т.п.)
    return FileResponse(ROOT / "ui" / "index.html",
                        headers={"Cache-Control": "no-store"})


@app.get("/api/status")
def status():
    return {
        "llm": {"backends": llm.backend_status(),
                "backend": CFG.get("llm.backend"),
                "model": CFG.get("llm.model")},
        "stt": stt.status(),
        "tts": tts.status(),
        "memory": memory.stats(),
        "problems": PROBLEMS[-10:],
        "assistant": CFG.get("assistant_name", "Сайка"),
    }


@app.get("/api/models")
def models():
    return {"models": llm.list_models(), "loaded": llm.loaded_models()}


@app.get("/api/system")
def system_info():
    """Загрузка системы для панели слева: ЦП, ОЗУ, GPU/VRAM."""
    info = {"cpu": {}, "ram": {}, "gpu": None}
    try:
        import psutil
        vm = psutil.virtual_memory()
        info["ram"] = {"total": vm.total, "used": vm.total - vm.available,
                       "percent": vm.percent}
        info["cpu"] = {"percent": psutil.cpu_percent(interval=None),
                       "cores": psutil.cpu_count(logical=True)}
    except Exception:
        pass
    try:
        import platform
        info["cpu"]["name"] = platform.processor() or ""
    except Exception:
        pass
    # GPU: сперва nvidia-smi (есть утилизация и температура), иначе torch
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,"
             "utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        name, mt, mu, util, temp = [s.strip() for s in
                                    r.stdout.strip().splitlines()[0].split(",")]
        info["gpu"] = {"name": name, "vram_total": int(mt) * 2**20,
                       "vram_used": int(mu) * 2**20,
                       "util": int(util), "temp": int(temp)}
    except Exception:
        try:
            import torch
            if torch.cuda.is_available():
                free, total = torch.cuda.mem_get_info(0)
                info["gpu"] = {"name": torch.cuda.get_device_name(0),
                               "vram_total": total, "vram_used": total - free,
                               "util": None, "temp": None}
        except Exception:
            pass
    return info


@app.post("/api/stt/model")
async def stt_model(payload: dict):
    """Ручная загрузка/выгрузка модели STT-движка (кнопки ⬇/⏏ в UI).
    Загрузка может качать модель и длиться долго — выполняем в пуле."""
    name = payload.get("name")
    action = payload.get("action")
    try:
        if action == "load":
            await asyncio.get_event_loop().run_in_executor(
                None, stt.load_engine, name)
        elif action == "unload":
            stt.unload_engine(name)
        else:
            return JSONResponse({"error": "unknown action"}, status_code=400)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/tts/model")
async def tts_model(payload: dict):
    """Ручная загрузка/выгрузка модели TTS-движка (кнопки ⬇/⏏ в UI)."""
    name = payload.get("name")
    action = payload.get("action")
    try:
        if action == "load":
            await asyncio.get_event_loop().run_in_executor(
                None, tts.load_engine, name)
        elif action == "unload":
            tts.unload_engine(name)
        else:
            return JSONResponse({"error": "unknown action"}, status_code=400)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/select")
async def select(payload: dict):
    """Единая точка переключения: llm-модель, stt-движок, tts-движок."""
    kind = payload.get("kind")
    value = payload.get("value")
    try:
        if kind == "model":
            backend = payload.get("backend", "ollama")
            CFG.set("llm.backend", backend)
            CFG.set("llm.model", value)
            # греем модель в фоне: UI следит за прогрессом через /api/models
            threading.Thread(target=llm.warmup, args=(backend, value),
                             daemon=True).start()
        elif kind == "stt":
            stt.set_engine(value)
        elif kind == "tts":
            tts.set_engine(value)
        elif kind == "tts_enabled":
            CFG.set("tts.enabled", bool(value))
        else:
            return JSONResponse({"error": "unknown kind"}, status_code=400)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/config")
def get_config():
    return CFG.data


@app.post("/api/memory/compress")
def force_compress():
    """Ручной запуск сжатия памяти (для отладки)."""
    threading.Thread(target=memory.compress_raw, args=(llm.chat_once,),
                     daemon=True).start()
    return {"ok": True}


# ---------------------- диалоговый пайплайн ----------------------
def run_dialog(user_text: str, out: "queue.Queue", stop_event: threading.Event):
    """Блокирующий пайплайн в отдельном потоке: LLM stream -> TTS stream."""
    person_id = CFG.get("owner.id", "owner")
    person_name = CFG.get("owner.name", "Owner")
    memory.add_event(person_id, "user", user_text)

    mem_context = ""
    try:
        mem_context = memory.build_context(person_id, user_text)
    except Exception as e:
        report_problem("memory", str(e), "продолжаю без контекста памяти")

    system = build_system_prompt(mem_context, person_name)
    history = memory.recent_raw(limit=CFG.get("llm.max_history", 30))
    messages = [{"role": "system", "content": system}]
    messages += [{"role": r, "content": t} for r, t in history]

    full_reply = []
    sentence_buf = ""

    # Озвучка — в отдельном потоке через очередь, иначе TTS блокирует
    # стрим токенов LLM и текст появляется «кусочками» по предложению.
    tts_q: "queue.Queue" = queue.Queue()

    def tts_worker():
        while True:
            sentence = tts_q.get()
            if sentence is None:
                break
            if stop_event.is_set():
                continue
            try:
                for pcm_bytes, sr in tts.speak(sentence):
                    if stop_event.is_set():
                        break
                    out.put({"type": "audio_meta", "sr": sr})
                    out.put(pcm_bytes)
            except Exception as e:
                report_problem("tts", str(e), "продолжаю без озвучки")

    tts_thread = threading.Thread(target=tts_worker, daemon=True)
    tts_thread.start()

    def speak(sentence):
        tts_q.put(sentence)

    try:
        def on_fallback(backend, model):
            report_problem("llm", "основной бэкенд недоступен",
                           f"переключилась на {backend}/{model}")

        for token in llm.chat_stream(messages, on_fallback=on_fallback):
            if stop_event.is_set():
                break
            full_reply.append(token)
            sentence_buf += token
            out.put({"type": "token", "text": token})
            done = split_sentences(sentence_buf)
            # озвучиваем законченные предложения, остаток держим в буфере
            if len(done) > 1:
                for s in done[:-1]:
                    speak(s)
                sentence_buf = done[-1]
        if sentence_buf.strip() and not stop_event.is_set():
            speak(sentence_buf.strip())
    except Exception as e:
        report_problem("llm", str(e), "проверь что Ollama или LM Studio запущены")
        out.put({"type": "error", "text": f"LLM недоступна: {e}"})

    tts_q.put(None)
    tts_thread.join(timeout=600)
    reply = "".join(full_reply).strip()
    if reply:
        memory.add_event(person_id, "assistant", reply)
    out.put({"type": "done"})


# ---------------------- WebSocket ----------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    out: "queue.Queue" = queue.Queue()
    EVENT_CLIENTS.add(out)
    stop_event = threading.Event()
    worker: threading.Thread | None = None

    async def sender():
        while True:
            try:
                item = await asyncio.get_event_loop().run_in_executor(
                    None, out.get)
                if item is None:
                    break
                if isinstance(item, bytes):
                    await ws.send_bytes(item)
                else:
                    await ws.send_text(json.dumps(item, ensure_ascii=False))
            except Exception:
                break

    send_task = asyncio.create_task(sender())

    def handle_text(user_text):
        nonlocal worker
        stop_event.clear()
        worker = threading.Thread(target=run_dialog,
                                  args=(user_text, out, stop_event), daemon=True)
        worker.start()

    try:
        while True:
            msg = await ws.receive()
            if msg.get("bytes") is not None:
                pcm = np.frombuffer(msg["bytes"], dtype=np.int16)
                results = await asyncio.get_event_loop().run_in_executor(
                    None, stt.process_chunk, pcm)
                for r in results:
                    out.put({"type": "stt", **r})
                    handle_text(r["text"])
            elif msg.get("text"):
                data = json.loads(msg["text"])
                mtype = data.get("type")
                if mtype == "text":
                    # набранный текст не эхо-каем обратно — UI уже показал
                    # пузырь сам; «услышано: …» остаётся только для голоса
                    handle_text(data["text"])
                elif mtype == "mic_stop":
                    results = await asyncio.get_event_loop().run_in_executor(
                        None, stt.flush)
                    for r in results:
                        out.put({"type": "stt", **r})
                        handle_text(r["text"])
                elif mtype == "interrupt":
                    stop_event.set()
    except WebSocketDisconnect:
        pass
    finally:
        stop_event.set()
        EVENT_CLIENTS.discard(out)
        out.put(None)
        send_task.cancel()


def main():
    (ROOT / "logs").mkdir(exist_ok=True)
    start_scheduler(memory, llm.chat_once)
    host = CFG.get("server.host", "127.0.0.1")
    port = CFG.get("server.port", 8765)
    if CFG.get("server.auto_open_browser", True):
        threading.Timer(1.5, webbrowser.open,
                        args=(f"http://{host}:{port}",)).start()
    log.info("Сайка запускается на http://%s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
