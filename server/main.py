"""Сайка — главный сервер.

FastAPI + WebSocket. Браузер шлёт PCM с микрофона, сервер возвращает
распознанный текст, стрим ответа LLM и стрим озвучки.
Все подсистемы обёрнуты в самодиагностику: ошибка -> событие в UI ->
автопереключение -> фоновая починка.
"""
import asyncio
import atexit
import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from server.config import CFG, ROOT, resolve
from server import baymax
from server import devboard
from server import messengers
from server import ratings
from server.persona import build_system_prompt
from server.llm import manager as llm
from server.llm import dreampc
from server.llm import train_manager
from server import dataset_hub
from server import git_sync
from server.proc_utils import kill_by_port, register_console_close_handler
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

# Любое НЕПОЙМАННОЕ исключение в фоновом потоке (диалог, TTS, починка) —
# в лог с полным трейсбеком. Иначе поток умирает молча: Сайка «не отвечает»,
# а в saika.log пусто.
def _thread_crash_hook(args):
    log.error("Поток %s упал: %s", args.thread.name if args.thread else "?",
              args.exc_value, exc_info=(args.exc_type, args.exc_value,
                                        args.exc_traceback))
threading.excepthook = _thread_crash_hook

app = FastAPI(title="Saika")

PROBLEMS: list[dict] = []          # лента проблем/починок для UI
ACTIVE_LLM = {"backend": "", "model": ""}  # кто реально отвечал последним
EVENT_CLIENTS: set = set()          # активные websockets
DIALOG_CUTOFF = {"ts": 0.0}         # «новый диалог»: контекст только после отметки
DIALOG_STATE = {"active_since": 0.0}   # идёт ли сейчас ответ (для импульсов)
LAST_IMAGE = {"data": None, "ts": 0.0}  # последняя картинка (для OCR слепыми)
# уникальный id этого запуска процесса: вкладка запоминает его при коннекте
# и, если после переподключения видит другой id, значит сервер
# перезапустился (упал и поднялся start.bat'ом) — делает F5 сама. Так одна
# и та же вкладка всегда свежая, а новые вкладки на рестартах не плодятся.
BOOT_ID = uuid.uuid4().hex


def report_problem(component, error, action, diag=None):
    item = {"component": component, "error": error, "action": action}
    PROBLEMS.append(item)
    del PROBLEMS[:-50]
    # проблемы обязаны попадать в лог: иначе при тихой смерти потока
    # диалога в saika.log пусто и отлаживать нечего
    log.warning("PROBLEM %s: %s -> %s", component, error or "(починилось)",
                action)
    # Беймакс: та же новость, но живым языком, отдельным пузырём в чат
    try:
        bm = baymax.line(component, error, action, diag)
    except Exception:
        bm = None
    # дев-доска: авто-отметка бага/починки (пустая ошибка = починилось)
    try:
        devboard.note_problem(component, error, action, fixed=not error)
    except Exception:
        pass
    for ws_queue in list(EVENT_CLIENTS):
        try:
            ws_queue.put_nowait({"type": "problem", **item})
            if bm:
                ws_queue.put_nowait({"type": "baymax", **bm})
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


@app.get("/baymax/{fname}")
def baymax_asset(fname: str):
    """Маленькие гифки Беймакса по настроению (ui/baymax/*.gif|png). Отдаём
    только файлы из этой папки — без выхода наружу по пути."""
    if "/" in fname or "\\" in fname or ".." in fname:
        return JSONResponse({"error": "bad name"}, status_code=400)
    p = ROOT / "ui" / "baymax" / fname
    if not p.exists() or p.suffix.lower() not in (".gif", ".png", ".webp"):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(p, headers={"Cache-Control": "max-age=60"})


@app.get("/api/status")
def status():
    return {
        "llm": {"backends": llm.backend_status(),
                "active": ACTIVE_LLM,
                "backend": CFG.get("llm.backend"),
                "model": CFG.get("llm.model"),
                "think": bool(CFG.get("llm.think", False))},
        "stt": stt.status(),
        "tts": tts.status(),
        "memory": memory.stats(),
        "problems": PROBLEMS[-10:],
        "assistant": CFG.get("assistant_name", "Сайка"),
        "attention_always": CFG.get("attention.always", False),
        "control_enabled": CFG.get("messengers.control_enabled", False),
    }


@app.get("/api/models")
def models():
    return {"models": llm.list_models(), "loaded": llm.loaded_models(),
            "ratings": ratings.llm_scores(), "tps": ratings.llm_tps()}


@app.get("/api/baymax")
def baymax():
    """«Привет, я Беймакс». Оценка здоровья всех модулей по шкале 1..10 +
    что делать (лечение). UI показывает это отдельной панелью."""
    from server import diagnostics as dg
    modules = []

    # --- LLM ---
    backends = llm.backend_status()
    any_llm = any(backends.values())
    loaded_llm = llm.loaded_models()
    cur_model = CFG.get("llm.model", "")
    if any_llm:
        in_mem = cur_model in loaded_llm
        modules.append({
            "group": "Мозг (LLM)", "name": cur_model or "не выбрана",
            "score": 10 if in_mem else 8,
            "verdict": ("активна, в памяти" if in_mem
                        else "бэкенд на связи, модель подгрузится по запросу"),
            "treatment": "" if in_mem else "нажми ⬇ у модели, чтобы держать её "
                                           "в памяти и отвечать быстрее"})
    else:
        modules.append({
            "group": "Мозг (LLM)", "name": "нет бэкенда", "score": 2,
            "verdict": "ни Ollama, ни LM Studio не отвечают",
            "treatment": "запусти Ollama или LM Studio (в LM Studio: "
                         "Developer → Start Server)"})

    # --- Слух (STT) ---
    st = stt.status()
    for nm in st.get("engines", []):
        modules.append({
            "group": "Слух (STT)", "name": nm,
            **dg.assess("stt." + nm, st["health"].get(nm, "unknown"),
                        st.get("loaded", {}).get(nm),
                        nm == st.get("current"),
                        st.get("diag", {}).get(nm))})

    # --- Голос (TTS) ---
    tt = tts.status()
    for nm in tt.get("engines", []):
        modules.append({
            "group": "Голос (TTS)", "name": nm,
            **dg.assess("tts." + nm, tt["health"].get(nm, "unknown"),
                        tt.get("loaded", {}).get(nm),
                        nm == tt.get("current"),
                        tt.get("diag", {}).get(nm))})

    scores = [m["score"] for m in modules]
    overall = round(sum(scores) / len(scores), 1) if scores else 0
    ill = [m for m in modules if m["score"] <= 5]
    return {"overall": overall, "modules": modules,
            "summary": ("Все системы в норме, лечить нечего."
                        if not ill else
                        f"Вижу проблемы в модулях: "
                        + ", ".join(m["name"] for m in ill) + ".")}


@app.get("/api/net")
def net_status():
    """Пинг/доступность сети для индикатора у имени. Ловит отрубы (в т.ч.
    когда VPN режет соединение): online=false или большой пинг -> сигнал."""
    import socket

    def probe(host, port=443):
        t = time.monotonic()
        try:
            socket.create_connection((host, port), timeout=3).close()
            return round((time.monotonic() - t) * 1000)
        except OSError:
            return None

    ping = probe("1.1.1.1")                     # Cloudflare — быстрый общий пинг
    hf = probe("huggingface.co") is not None    # важно для скачивания моделей
    return {"online": ping is not None, "ping_ms": ping, "hf": hf}


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


@app.post("/api/llm/model")
async def llm_model(payload: dict):
    """Ручная загрузка/выгрузка LLM-модели (кнопки ⬇/⏏ в списке моделей)."""
    name = payload.get("name")
    backend = payload.get("backend", "ollama")
    action = payload.get("action")
    try:
        if action == "load":
            ok = await asyncio.get_event_loop().run_in_executor(
                None, llm.warmup, backend, name)
        elif action == "unload":
            ok = await asyncio.get_event_loop().run_in_executor(
                None, llm.unload_model, backend, name)
        else:
            return JSONResponse({"error": "unknown action"}, status_code=400)
        return {"ok": bool(ok)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/llm/cloud")
def llm_cloud_get():
    """Текущие настройки облака (без ключа — его не отдаём)."""
    c = CFG.get("llm.cloud", {}) or {}
    has_key = bool(llm._cloud().get("key"))
    return {"enabled": bool(c.get("enabled")),
            "provider": c.get("provider", "openrouter"),
            "base_url": c.get("base_url", "https://openrouter.ai/api/v1"),
            "model": c.get("model", ""), "has_key": has_key}


@app.post("/api/llm/cloud")
def llm_cloud_set(payload: dict):
    """Сохранить онлайн-модель: base_url/model/provider — в config, API-ключ —
    в secrets.json (в git не попадёт). Если включили — делаем облако активным."""
    if payload.get("provider") is not None:
        CFG.set("llm.cloud.provider", payload["provider"])
    if payload.get("base_url") is not None:
        CFG.set("llm.cloud.base_url", payload["base_url"])
    if payload.get("model") is not None:
        CFG.set("llm.cloud.model", payload["model"])
    if payload.get("api_key"):
        llm.save_cloud_key(payload["api_key"])
    enabled = bool(payload.get("enabled"))
    CFG.set("llm.cloud.enabled", enabled)
    if enabled and payload.get("model"):
        CFG.set("llm.backend", "cloud")
        CFG.set("llm.model", payload["model"])
    return {"ok": True}


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
            # переключение с защитой памяти: switch_model сперва выгрузит
            # прочие модели (чтобы две большие не висели разом и не вешали ПК),
            # потом прогреет новую. UI следит через /api/models
            threading.Thread(target=llm.switch_model, args=(backend, value),
                             daemon=True).start()
        elif kind == "stt":
            stt.set_engine(value)
        elif kind == "think":
            # тумблер «размышлений» думающих моделей (gemma-4, qwen3, r1…):
            # мысли — главный пожиратель секунд перед ответом
            CFG.set("llm.think", bool(value))
        elif kind == "tts":
            tts.set_engine(value)
        elif kind == "tts_enabled":
            CFG.set("tts.enabled", bool(value))
        elif kind == "attention_always":
            # «слушать всё» vs умный режим внимания (по имени/окну)
            CFG.set("attention.always", bool(value))
        else:
            return JSONResponse({"error": "unknown kind"}, status_code=400)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/config")
def get_config():
    return CFG.data


# ---------------------- дев-доска (карта разработки) ----------------------
@app.get("/api/devboard")
def devboard_get():
    return devboard.get()


@app.post("/api/devboard/add")
def devboard_add(payload: dict):
    return devboard.add_item(payload.get("col", "doing"),
                             payload.get("text", ""), payload.get("note", ""))


@app.post("/api/devboard/update")
def devboard_update(payload: dict):
    return devboard.update_item(payload.get("id"), col=payload.get("col"),
                                text=payload.get("text"),
                                note=payload.get("note"))


@app.post("/api/devboard/delete")
def devboard_delete(payload: dict):
    return devboard.delete_item(payload.get("id"))


@app.post("/api/control")
def set_control(payload: dict):
    """Мастер-рубильник управления ПК из мессенджеров (кнопка 🔒/🔓 в углу UI).
    Выключен = боты не закрывают/не запускают ничего, даже владелец. Защита
    от «друг по приколу что-то выключил», пока владелец сам не включит."""
    on = bool(payload.get("enabled"))
    CFG.set("messengers.control_enabled", on)
    log.info("Управление ПК из мессенджеров: %s", "ВКЛ" if on else "ВЫКЛ")
    return {"ok": True, "control_enabled": on}


@app.post("/api/dialog/clear")
def dialog_clear():
    """Начать диалог с чистого листа: старые сообщения не идут в контекст
    (долгая память не трогается)."""
    DIALOG_CUTOFF["ts"] = time.time()
    return {"ok": True}


@app.get("/api/git/status")
def git_status():
    return git_sync.status()


@app.post("/api/git/sync")
async def git_sync_endpoint(payload: dict):
    """Кнопка ⬆ в углу UI: git add -A && commit && push в фоновом потоке
    (push может подождать сеть, не блокируем event loop)."""
    message = payload.get("message", "")
    result = await asyncio.get_event_loop().run_in_executor(
        None, git_sync.sync, message)
    return result


@app.post("/api/git/pull")
async def git_pull_endpoint():
    """Кнопка ⬇ в углу UI: git pull --ff-only — подтянуть код с другого ПК.
    Новые компоненты (venv/воркеры) после этого ставятся лениво, по клику
    на свою кнопку — как сейчас у DreamPC/Voxtral, не сразу все скопом."""
    result = await asyncio.get_event_loop().run_in_executor(None, git_sync.pull)
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    return result


@app.post("/api/dreampc/ensure")
async def dreampc_ensure():
    """Поднимает воркер DreamPC (диффузионная LLaDA-8B) по требованию —
    полностью автономно: сама ставит окружение при первом разе, сама её же
    переустанавливает, если находит проблему (см. server/llm/dreampc.py).
    Ничего не блокирует UI — статус установки уходит через
    /api/dreampc/install_status."""
    result = await asyncio.get_event_loop().run_in_executor(
        None, dreampc.ensure_running)
    if result.get("error"):
        return JSONResponse(result, status_code=400)
    return result


@app.get("/api/dreampc/install_status")
def dreampc_install_status():
    return dreampc.install_status()


@app.get("/api/dreampc/status")
def dreampc_worker_status():
    """Живой статус воркера (качаю/гружу/генерирую + хвост лога) для панели."""
    return dreampc.worker_status()


# известные диффузионные модели, совместимые с воркером (LLaDA-семейство,
# mask-токен воркер подберёт сам по имени). name — repo на HF, note — подсказка.
DREAMPC_MODELS = [
    {"name": "GSAI-ML/LLaDA-8B-Instruct",
     "label": "LLaDA-8B Instruct", "note": "плотная 8B, точнее, но медленнее (~16 ГБ)"},
    {"name": "inclusionAI/LLaDA-MoE-7B-A1B-Instruct",
     "label": "LLaDA-MoE 7B (A1B)", "note": "MoE: ~1.4B активны — заметно быстрее (~14 ГБ)"},
    {"name": "GSAI-ML/LLaDA-8B-Base",
     "label": "LLaDA-8B Base", "note": "без чат-настройки, для экспериментов"},
]


@app.get("/api/dreampc/models")
def dreampc_models():
    return {"models": DREAMPC_MODELS, "current": CFG.get("dreampc.model")}


@app.post("/api/dreampc/model")
def dreampc_set_model(payload: dict):
    """Сменить диффузионную модель. Гасим текущий воркер — при следующем
    «Проявить» он поднимется уже с новой (и сам скачает её при первом разе)."""
    name = payload.get("name")
    if not name:
        return JSONResponse({"error": "no model"}, status_code=400)
    CFG.set("dreampc.model", name)
    dreampc.kill_stale()  # следующий ensure_running поднимет воркер с новой моделью
    return {"ok": True, "model": name}


# ============================================================
# Инженерная вкладка обучения: датасет (локальный + HF) + LoRA-обучение.
# Тот же паттерн автономности, что у DreamPC — ставится/чинится по запросу,
# ничего руками. train_manager.py — спавнер воркера, dataset_hub.py —
# работа с датасетом (сводка, self-instruct расширение, поиск/импорт с HF).
# ============================================================

@app.get("/api/training/dataset/summary")
def training_dataset_summary():
    return dataset_hub.summary()


@app.post("/api/training/dataset/open_folder")
def training_dataset_open_folder():
    return dataset_hub.open_dataset_folder()


@app.post("/api/training/dataset/expand")
def training_dataset_expand(payload: dict):
    target = int(payload.get("target", 1000))
    model = payload.get("model", CFG.get("tools.browser_model", "qwen3.6:latest"))
    result = dataset_hub.start_expand(target, model)
    if result.get("error"):
        return JSONResponse(result, status_code=409)
    return result


@app.get("/api/training/dataset/expand_status")
def training_dataset_expand_status():
    return dataset_hub.expand_status()


@app.post("/api/training/dataset/expand_stop")
def training_dataset_expand_stop():
    return dataset_hub.stop_expand()


@app.post("/api/training/dataset/hf_search")
async def training_hf_search(payload: dict):
    query = payload.get("query", "")
    if not query:
        return JSONResponse({"error": "пустой запрос"}, status_code=400)
    result = await asyncio.get_event_loop().run_in_executor(
        None, dataset_hub.hf_search, query)
    if result.get("error"):
        return JSONResponse(result, status_code=502)
    return result


@app.post("/api/training/dataset/hf_preview")
async def training_hf_preview(payload: dict):
    name = payload.get("name")
    if not name:
        return JSONResponse({"error": "нужно имя датасета"}, status_code=400)
    result = await asyncio.get_event_loop().run_in_executor(
        None, dataset_hub.hf_preview, name,
        payload.get("config", "default"), payload.get("split", "train"),
        payload.get("limit", 200))
    if result.get("error"):
        return JSONResponse(result, status_code=502)
    return result


@app.post("/api/training/dataset/hf_import")
async def training_hf_import(payload: dict):
    name = payload.get("name")
    if not name:
        return JSONResponse({"error": "нужно имя датасета"}, status_code=400)
    result = await asyncio.get_event_loop().run_in_executor(
        None, dataset_hub.hf_import, name,
        payload.get("config", "default"), payload.get("split", "train"),
        payload.get("limit", 300))
    if result.get("error"):
        return JSONResponse(result, status_code=502)
    return result


@app.post("/api/training/dataset/merge")
def training_dataset_merge():
    return dataset_hub.merge_full_dataset()


# известные компактные модели, совместимые с unsloth QLoRA — под "чтобы
# летала" (см. training/dataset/README.md). base уже подтянут к текущей
# чат-модели gemma-4-e4b-it из config.json.
TRAIN_BASE_MODELS = [
    {"name": "unsloth/gemma-3n-E4B-it",
     "label": "Gemma 3n E4B-it", "note": "ближе всего к текущей чат-модели, ~4B эффективных"},
    {"name": "unsloth/gemma-3n-E2B-it",
     "label": "Gemma 3n E2B-it", "note": "легче и быстрее, ~2B эффективных"},
    {"name": "unsloth/Qwen2.5-3B-Instruct",
     "label": "Qwen2.5 3B Instruct", "note": "компактная, хорошо держит русский"},
    {"name": "unsloth/Llama-3.2-3B-Instruct",
     "label": "Llama 3.2 3B Instruct", "note": "альтернатива, английский акцент сильнее"},
]


@app.get("/api/training/base_models")
def training_base_models():
    return {"models": TRAIN_BASE_MODELS, "current": CFG.get("training.base_model")}


@app.post("/api/training/ensure")
async def training_ensure():
    result = await asyncio.get_event_loop().run_in_executor(
        None, train_manager.ensure_running)
    if result.get("error"):
        return JSONResponse(result, status_code=400)
    return result


@app.get("/api/training/install_status")
def training_install_status():
    return train_manager.install_status()


@app.post("/api/training/start")
async def training_start(payload: dict):
    ensure = await asyncio.get_event_loop().run_in_executor(
        None, train_manager.ensure_running)
    if ensure.get("error"):
        return JSONResponse(ensure, status_code=400)
    if ensure.get("installing"):
        return JSONResponse(ensure, status_code=202)

    cfg = CFG.get("training", {})
    dataset_path = payload.get("dataset_path") or str(
        resolve(cfg.get("dataset_dir", "training/dataset")) / "full_dataset.jsonl")
    start_cfg = {
        "base_model": payload.get("base_model", cfg.get("base_model")),
        "dataset_path": dataset_path,
        "lora_r": payload.get("lora_r", cfg.get("lora_r", 16)),
        "lora_alpha": payload.get("lora_alpha", cfg.get("lora_alpha", 16)),
        "lora_dropout": payload.get("lora_dropout", cfg.get("lora_dropout", 0.0)),
        "learning_rate": payload.get("learning_rate", cfg.get("learning_rate", 2e-4)),
        "epochs": payload.get("epochs", cfg.get("epochs", 3)),
        "batch_size": payload.get("batch_size", cfg.get("batch_size", 2)),
        "grad_accum": payload.get("grad_accum", cfg.get("grad_accum", 4)),
        "max_seq_len": payload.get("max_seq_len", cfg.get("max_seq_len", 1024)),
        "output_name": payload.get("output_name", cfg.get("output_name", "saika-char")),
    }
    result, code = await asyncio.get_event_loop().run_in_executor(
        None, train_manager.start_training, start_cfg)
    if code >= 400:
        return JSONResponse(result, status_code=code)
    return result


@app.get("/api/training/status")
async def training_status():
    result = await asyncio.get_event_loop().run_in_executor(
        None, train_manager.training_status)
    return result


@app.post("/api/training/stop")
async def training_stop():
    result, code = await asyncio.get_event_loop().run_in_executor(
        None, train_manager.stop_training)
    return result


@app.post("/api/training/export_gguf")
async def training_export_gguf(payload: dict):
    cfg = CFG.get("training", {})
    export_cfg = {
        "output_name": payload.get("output_name", cfg.get("output_name", "saika-char")),
        "quant": payload.get("quant", "q4_k_m"),
        "max_seq_len": payload.get("max_seq_len", cfg.get("max_seq_len", 1024)),
    }
    result, code = await asyncio.get_event_loop().run_in_executor(
        None, train_manager.export_gguf, export_cfg)
    if code >= 400:
        return JSONResponse(result, status_code=code)
    return result


@app.post("/api/memory/compress")
def force_compress():
    """Ручной запуск сжатия памяти (для отладки)."""
    threading.Thread(target=memory.compress_raw, args=(llm.chat_once,),
                     daemon=True).start()
    return {"ok": True}


# ---------------------- REST-чат для нативных клиентов (UE5 и т.п.) --------
class _ServerSpeaker:
    """Играет PCM (int16 mono) через колонки ЭТОГО ПК — для клиентов без
    своего аудио (нативный UE-интерфейс). Ленивая инициализация sounddevice:
    нет пакета — молча без звука (подсказка уйдёт в problems)."""

    def __init__(self):
        self._stream = None
        self._sr = 0

    def play(self, pcm: bytes, sr: int):
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError:
            report_problem("tts", "нет пакета sounddevice",
                           "pip install sounddevice — и озвучка REST-чата "
                           "заиграет через колонки")
            return
        # TTS отдаёт PCM как FLOAT32 (браузер играет через Float32Array,
        # см. ui/index.html:663). 2026-07-20 плеер играл эти байты как
        # int16 -> адский скрежет на всю громкость. Играем как float32,
        # с потолком громкости и защитой от кривого семпл-рейта.
        if not (8000 <= sr <= 48000):
            report_problem("tts", f"подозрительный sample rate {sr}",
                           "чанк озвучки пропущен")
            return
        if self._stream is None or self._sr != sr:
            self.close()
            self._stream = sd.OutputStream(
                samplerate=sr, channels=1, dtype="float32",
                device=CFG.get("tts.output_device") or None)
            self._stream.start()
            self._sr = sr
        data = np.frombuffer(pcm, dtype=np.float32)
        vol = max(0.0, min(1.0, float(CFG.get("tts.server_volume", 0.8))))
        self._stream.write(np.clip(data * vol, -1.0, 1.0))

    def close(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None


AUDIO_LEVEL = {"level": 0.0, "ts": 0.0}


@app.get("/api/audio_level")
def audio_level():
    """Текущая громкость голоса Сайки 0..1 (для волны-эквалайзера в UE).
    Голос замолк -> быстро затухает до нуля."""
    age = time.time() - AUDIO_LEVEL["ts"]
    lvl = AUDIO_LEVEL["level"] * max(0.0, 1.0 - age / 0.4)
    return PlainTextResponse(f"{lvl:.3f}")


@app.get("/api/attention_toggle")
def attention_toggle():
    """Тумблер «активный диалог» (слушать всё без имени) — для кнопки в UE."""
    val = not CFG.get("attention.always", False)
    CFG.set("attention.always", val)
    return PlainTextResponse("on" if val else "off")


@app.post("/api/chat_text")
async def api_chat_text(request: Request):
    """Тот же чат, но максимально простой для клиентов без JSON (UE HTTP
    Blueprint): тело запроса — просто текст, ответ — просто текст."""
    text = (await request.body()).decode("utf-8", "ignore").strip()
    r = api_chat({"text": text})
    if isinstance(r, JSONResponse):
        return PlainTextResponse("(ошибка: пустой текст или LLM недоступна)",
                                 status_code=r.status_code)
    return PlainTextResponse(r.get("reply", ""))


@app.post("/api/chat")
def api_chat(payload: dict):
    """Блокирующий чат: текст входит — полный ответ выходит одним JSON.
    Озвучка (если tts.server_playback, по умолчанию вкл) играет через
    колонки сервера — клиенту звук не нужен. Для UE5/скриптов/curl."""
    text = (payload.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "пустой текст"}, status_code=400)
    speak_here = bool(payload.get("speak",
                                  CFG.get("tts.server_playback", True)))
    out: "queue.Queue" = queue.Queue()
    stop_event = threading.Event()
    worker = threading.Thread(
        target=run_dialog, args=(text, out, stop_event), daemon=True)
    worker.start()

    reply_parts, stats, spk = [], {}, _ServerSpeaker()
    sr = 24000
    deadline = time.time() + float(payload.get("timeout_s", 600))
    try:
        while time.time() < deadline:
            try:
                item = out.get(timeout=5)
            except queue.Empty:
                if not worker.is_alive():
                    break
                continue
            if isinstance(item, bytes):
                if speak_here:
                    try:
                        spk.play(item, sr)
                    except Exception as e:
                        report_problem("tts", str(e),
                                       "REST-чат продолжает без звука")
                        speak_here = False
                continue
            t = item.get("type")
            if t == "audio_meta":
                sr = item.get("sr", sr)
            elif t == "token":
                reply_parts.append(item.get("text", ""))
            elif t == "stats":
                stats = {k: v for k, v in item.items() if k != "type"}
            elif t == "error":
                return JSONResponse({"error": item.get("text", "LLM error")},
                                    status_code=502)
            elif t == "done":
                break
    finally:
        spk.close()
    return {"reply": "".join(reply_parts).strip(), **stats}


# ---------------------- диалоговый пайплайн ----------------------
def _is_dev_query(text: str) -> bool:
    """Вопрос явно про разработку Сайки — тогда подкладываем ей всю доску."""
    t = (text or "").lower()
    keys = ("что нов", "чекни", "погляди что у тебя", "посмотри что у тебя",
            "своей разработ", "о разработ", "про разработ", "что сдела",
            "что измен", "истори разработ", "что готово", "дев-доск",
            "в доске", "чем занимаемся", "что в планах",
            "что у тебя происходит", "что у тебя нового")
    return any(k in t for k in keys)


def run_dialog(user_text: str, out: "queue.Queue", stop_event: threading.Event,
               heard_ts: float | None = None, image: str | None = None):
    """Блокирующий пайплайн в отдельном потоке: LLM stream -> TTS stream.
    heard_ts (time.monotonic) — момент, когда фраза была распознана: по нему
    считаем задержку до первого токена ответа («думала N сек»)."""
    person_id = CFG.get("owner.id", "owner")
    person_name = CFG.get("owner.name", "Owner")
    memory.add_event(person_id, "user", user_text)

    DIALOG_STATE["active_since"] = time.time()
    t0 = time.monotonic()   # старт пайплайна (для разбивки «думала N сек»)
    mem_context = ""
    try:
        mem_context = memory.build_context(person_id, user_text)
    except Exception as e:
        report_problem("memory", str(e), "продолжаю без контекста памяти")
    t_mem = time.monotonic()  # память (Chroma/SQLite) отработала

    # Скорость первого токена: системный промпт держим СТАТИЧНЫМ (одинаковым
    # от фразы к фразе) — тогда llama.cpp/LM Studio переиспользует KV-кэш
    # префикса и prefill'ит только новые токены, а не весь промпт заново.
    # Раньше контекст памяти (разный на каждую фразу) вшивался в НАЧАЛО
    # системного промпта — кэш ломался с первого токена, и «думала N сек»
    # почти целиком было пережёвыванием одного и того же. Вся динамика хода
    # теперь копится в dyn_parts и уходит В КОНЕЦ промпта, перед последней
    # фразой пользователя.
    system = build_system_prompt(None, person_name)
    dyn_parts = []
    # МЕТКА ТОНА (оболочка даёт ярлык поведения, остроумие — на модели):
    # хамство/провокация/пошлость/флирт/похвала -> разрешение вести себя
    # соответующе, коротко и в характере, без нотаций
    try:
        from server import tone as _tone
        _hint = _tone.behavior_hint(user_text)
        if _hint:
            dyn_parts.append(_hint)
    except Exception:
        pass
    if mem_context:
        dyn_parts.append(
            "### Твоя память по теме (используй естественно, не цитируй "
            "дословно):\n" + mem_context)
    if image:
        LAST_IMAGE["data"], LAST_IMAGE["ts"] = image, time.time()
        from server import capabilities as caps
        if caps.vision(CFG.get("llm.model", "")) is False:
            # модель БЕЗ зрения: картинку ей не даём (иначе 400 или бред),
            # а учим честно признаться и предложить распознавание — по «да»
            # сервер одолжит глаза у vision-модели парка (блок ниже)
            dyn_parts.append(
                "### Пользователь прислал КАРТИНКУ, но текущая твоя модель "
                "БЕЗ ЗРЕНИЯ — ты изображение НЕ видишь. Скажи об этом честно "
                "и по-своему (в духе: «я не вижу, что ты отправил — судя по "
                "всему, картинка. Вытащить из неё текст?») и предложи "
                "распознать. СТРОГО запрещено выдумывать содержимое.")
            image = None
        else:
            dyn_parts.append(
                "### К этому сообщению пользователь ПРИКРЕПИЛ КАРТИНКУ — "
                "она передана тебе вместе с текстом. Посмотри на изображение "
                "и ответь по нему. Не говори, что у тебя нет зрения — на "
                "этот раз картинка у тебя есть.")
    # «да, вытащи» после её предложения распознать: сервер-оркестратор
    # делает OCR чужой vision-моделью и отдаёт текст текущей болтушке —
    # умеющих самих это не касается (у них image уходит напрямую выше)
    try:
        from server import capabilities as caps
        if (LAST_IMAGE["data"] and image is None
                and time.time() - LAST_IMAGE["ts"] < 600
                and caps.vision(CFG.get("llm.model", "")) is False
                and re.match(r"^(да|ага|угу|давай|можно|конечно|вытащи|"
                             r"достань|прочитай|распознай|проверь)\b",
                             user_text.strip(), re.I)):
            pick = caps.pick_vision_model(llm.list_models(),
                                          llm.loaded_models())
            if pick:
                vb, vm = pick
                out.put({"type": "tool", "name": "ocr·" + vm,
                         "args": "читаю картинку чужими глазами"})
                log.info("OCR: одалживаю зрение у %s/%s", vb, vm)
                ocr = llm.ask_specific(vb, vm, [
                    {"role": "user", "content":
                     "Выпиши ВЕСЬ текст с изображения дословно, как есть, "
                     "без комментариев и без исправлений."}],
                    image=LAST_IMAGE["data"])
                if ocr.strip():
                    dyn_parts.append(
                        "### Ты «одолжила глаза» у vision-модели (" + vm +
                        ") — вот дословный текст с картинки:\n" + ocr[:4000] +
                        "\n\nЕсли просили проверить орфографию/ошибки — выдай "
                        "исправленный чистый вариант и коротко перечисли "
                        "главные правки. Иначе просто отдай/перескажи текст.")
                    LAST_IMAGE["data"] = None
                else:
                    dyn_parts.append(
                        "### Распознавание не удалось (vision-модель ничего "
                        "не ответила). Скажи честно и предложи повторить.")
            else:
                dyn_parts.append(
                    "### В парке нет ни одной модели со зрением — распознать "
                    "картинку некому. Скажи честно.")
    except Exception as e:
        report_problem("vision", str(e), "распознавание не удалось")
    # Окно её браузера открыто — поведение живого человека: тема закрыта ->
    # один раз спросить про окно; «закрой» -> close_browser; «оставь» ->
    # оставить и не переспрашивать
    try:
        from server import browser_hands
        if browser_hands.is_open():
            dyn_parts.append(
                "### У тебя сейчас ОТКРЫТО окно твоего браузера (после "
                "недавнего поиска). Веди себя с ним как человек: если тема, "
                "ради которой искала, закончилась — ОДИН раз коротко спроси, "
                "оставить ли окно. Ответит «закрой»/«нет»/«не нужно» — вызови "
                "close_browser и подтверди одним словом. Ответит «оставь» — "
                "оставь и больше об этом не заговаривай. Попросит закрыть "
                "прямо — просто вызови close_browser без вопросов.")
    except Exception:
        pass
    # УМНЫЙ СЕРФИНГ ПО ВОЗМОЖНОСТЯМ МОДЕЛИ: система сама знает, какая модель
    # умеет инструменты (tools_broken наполняется автоматически). Если модель
    # «безрукая», а пользователь явно просит поискать — поиск выполняет САМ
    # СЕРВЕР (web_research кодом), и модели отдаются готовые материалы:
    # пересказать источники может даже самая мелкая болтушка.
    try:
        if re.search(r"\b(найди|загугли|погугли|поищи|глянь в (инете|сети)|"
                     r"что нового в мире)\b", user_text, re.I):
            _cur_model = CFG.get("llm.model", "")
            _no_tools = (_cur_model in set(CFG.get("llm.tools_broken", []))
                         or not CFG.get("tools.enabled", True))
            if _no_tools and CFG.get("browser.enabled", True):
                from server import browser_hands
                _q = re.sub(r"^(сайка[,!\s]*)?(найди|загугли|погугли|поищи|"
                            r"глянь)( в (инете|сети|интернете))?\s*", "",
                            user_text, flags=re.I).strip() or user_text
                log.info("Серверный поиск для модели без инструментов: %r", _q)
                out.put({"type": "tool", "name": "web_research·server",
                         "args": _q[:80]})
                _found = browser_hands.research(_q)
                if _found:
                    dyn_parts.append(
                        "### Результаты ТВОЕГО поиска в интернете (система "
                        "выполнила его за тебя автоматически — смело говори "
                        "«я поискала»):\n" + _found +
                        "\n\nПерескажи пользователю суть своими словами с "
                        "опорой на источники. Сверх найденного не выдумывай.")
    except Exception as e:
        report_problem("browser", str(e), "серверный поиск не удался — "
                       "отвечаю без него")
    # Сайка в курсе своей истории разработки (дев-доска) — может рассказать,
    # чем сейчас занимаемся, что готово, что багует
    try:
        board = devboard.summary_for_llm()
        if board:
            system += (
                "\n\n### Твоя история разработки (дев-доска, факт): " + board +
                "\nКогда спрашивают про твою разработку / что сделано / что "
                "нового / что сломано — НЕ говори общими словами. Сначала "
                "загляни в доску инструментом devboard_read, назови конкретные "
                "пункты (что в работе, что недавно сделано, что багует) и дай "
                "короткий вердикт. Если замечаешь новое, чего в доске нет, или "
                "тебя просят записать — добавляй через devboard_add.")
    except Exception:
        pass
    # Маленькая модель сама инструмент не дёрнет и «льёт воду». Если вопрос
    # явно про разработку — подкладываем ВСЮ доску прямо в контекст и жёстко
    # требуем конкретики. Тогда даже gemma просто перечислит факты.
    if _is_dev_query(user_text):
        try:
            from server.llm import tools as _t
            board_md = _t._local_call("devboard_read", {})
            dyn_parts.append(
                "### ЗАДАНИЕ СЕЙЧАС: пользователь спрашивает про твою "
                "разработку. Ниже — твоя дев-доска целиком (ФАКТ, не выдумывай "
                "и не философствуй). Ответь КОРОТКО и КОНКРЕТНО: перечисли "
                "5-6 последних готовых пунктов и что сейчас в работе, своими "
                "словами, живо. Запрещено: рассуждения про «калибровку», "
                "«частоту», «оттачивание угла зрения» и прочую воду — только "
                "пункты из доски.\n\n" + board_md)
        except Exception:
            pass
    # если HandsPC жив — Сайка должна знать о своих «руках», иначе она
    # уверяет, что не имеет доступа к интернету, хотя инструменты подключены
    try:
        from server.llm import tools as handspc
        names = [s["function"]["name"] for s in handspc.schemas()]
        # модели из чёрного списка (кривой формат tool_calls) — раздел
        # инструментов в промпт НЕ даём вообще: иначе она пишет
        # <|tool_call|> текстом в чат и «странно реагирует»
        if CFG.get("llm.model") in set(CFG.get("llm.tools_broken", [])):
            names = []
        if names:
            system += (
                "\n\n### Твои инструменты (факт, важнее всего сказанного "
                "ранее в диалоге): " + ", ".join(names) + ".\n"
                "- Спросили о том, чего не знаешь или что могло измениться "
                "(люди, ники, события, цены, погода, термины) — не отвечай "
                "«не знаю» и «мне не предоставлен контекст»: молча возьми "
                "web_search и выясни. «Загугли», «глянь», «поищи» = сразу "
                "зови инструмент, без встречных вопросов.\n"
                "- Добивайся результата сама: не нашла — переформулируй "
                "запрос и попробуй ещё; поиск молчит — открой страницу "
                "через fetch_page или возьми browser_task. Сдаваться можно "
                "после 2-3 РАЗНЫХ попыток, не раньше.\n"
                "- Об ошибках говори своими словами, каждый раз по-разному "
                "и в своём характере — никаких заученных фраз. Про проблемы "
                "с сетью упоминай только если инструмент реально вернул "
                "сетевую ошибку.\n"
                "- Файлы и папки: у тебя есть РЕАЛЬНЫЕ руки в рабочей папке "
                "(fs_list, fs_read, fs_write, fs_mkdir, fs_rename, fs_move, "
                "fs_delete, fs_open, fs_close_windows). Просят создать/"
                "открыть/прочитать/переименовать/убрать файл или папку — "
                "молча зови нужный инструмент и подтверждай результат парой "
                "слов. Не рассказывай, что «закладываешь в инструментарий» — "
                "инструменты уже есть, действуй.\n"
                "- Поиск в интернете: web_search — быстрая выдача; "
                "web_research — ГЛУБОКИЙ: сама открываешь и читаешь "
                "несколько страниц и приносишь сводку с источниками (бери "
                "его для содержательных вопросов: кто такой, что за проект, "
                "обзор, сравнение). Всё происходит в твоём ВИДИМОМ окне "
                "браузера — пользователь видит, как ты ищешь и листаешь. "
                "open_page открывает ссылку, close_browser закрывает окно.\n"
                "- Повторная просьба поискать («попробуй ещё», «найди "
                "снова», «поищи также») = ОБЯЗАТЕЛЬНЫЙ новый вызов "
                "web_search с переформулированным запросом — даже если "
                "раньше поиск ничего не дал или ты отвечала, что данных "
                "нет. Отвечать «мы уже проверяли» вместо реального вызова "
                "запрещено.\n"
                "- ЗАПРЕЩЕНО отыгрывать поиск словами («провожу глубокий "
                "поиск…» и следом выдуманные результаты) без реального "
                "вызова. Сказала, что ищешь = в ЭТОМ ЖЕ ответе вызвала "
                "web_search или web_research.\n"
                "- Инструменты — только когда попросили или когда без них "
                "не ответить. На бытовые реплики («привет», «ты тут?», «как "
                "дела») инструменты НЕ дёргаются — просто отвечаешь. "
                "«Ты тут?» — это вопрос присутствия, а не задание найти, "
                "кто ты такая. Но если прямо попросят что-то загуглить — "
                "хоть тебя саму — это обычный запрос, выполняй.\n"
                "- Никогда не говори, что у тебя нет доступа к интернету, "
                "файлам или инструментов — это неправда. Если инструмент "
                "вернул, что что-то ещё устанавливается или недоступно — "
                "передай это честно и предложи повторить позже, не выдумывай "
                "результат.")
    except Exception:
        pass
    history = memory.recent_raw(limit=CFG.get("llm.max_history", 30),
                                since_ts=DIALOG_CUTOFF["ts"])
    # Умный бюджет контекста: LM Studio валит «Context size has been exceeded»,
    # если система+история не влезают в окно модели. Режем историю с хвоста
    # (свежие сообщения важнее старых — старое и так уехало в память-эпизоды):
    # считаем в символах, ~3.5 символа на токен для русского.
    budget = int(CFG.get("llm.context_chars", 12000))
    hist_budget = max(2000, budget - len(system))
    trimmed, used = [], 0
    for r, t in reversed(history):
        if used + len(t) > hist_budget:
            break
        trimmed.append((r, t))
        used += len(t)
    trimmed.reverse()
    if len(trimmed) < len(history):
        log.info("Контекст: обрезала историю %s -> %s сообщений (бюджет %s символов)",
                 len(history), len(trimmed), hist_budget)
    messages = [{"role": "system", "content": system}]
    hist_msgs = [{"role": r, "content": t} for r, t in trimmed]
    if dyn_parts:
        # динамика хода — отдельным системным сообщением ПЕРЕД последней
        # фразой пользователя: весь префикс до неё стабилен => KV-кэш живёт
        dyn_msg = {"role": "system", "content": "\n\n".join(dyn_parts)}
        if hist_msgs:
            messages += hist_msgs[:-1] + [dyn_msg, hist_msgs[-1]]
        else:
            messages += [dyn_msg]
    else:
        messages += hist_msgs

    full_reply = []
    sentence_buf = ""
    n_tokens = 0
    t_first = None

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
            if not re.search(r"[0-9a-zа-яё]", sentence, re.I):
                continue   # «...» и прочее безбуквенное — не озвучиваем
            if "<|" in sentence or "tool_call" in sentence:
                continue   # мусор спецтокенов от кривых моделей — не читаем
            try:
                for pcm_bytes, sr in tts.speak(sentence):
                    if stop_event.is_set():
                        break
                    # уровень голоса для визуализаций (волна-эквалайзер в UE):
                    # RMS чанка float32 -> AUDIO_LEVEL, отдаётся /api/audio_level
                    try:
                        _a = np.frombuffer(pcm_bytes, dtype=np.float32)
                        AUDIO_LEVEL["level"] = min(
                            1.0, float(np.sqrt(np.mean(_a * _a))) * 4.0)
                        AUDIO_LEVEL["ts"] = time.time()
                    except Exception:
                        pass
                    out.put({"type": "audio_meta", "sr": sr})
                    out.put(pcm_bytes)
            except Exception as e:
                report_problem("tts", str(e), "продолжаю без озвучки")

    tts_thread = threading.Thread(target=tts_worker, daemon=True)
    tts_thread.start()

    def speak(sentence):
        tts_q.put(sentence)

    used_llm = {}

    try:
        def on_fallback(backend, model):
            report_problem("llm", "основной бэкенд недоступен",
                           f"переключилась на {backend}/{model}")

        def on_model(backend, model):
            # кто РЕАЛЬНО отвечает (после фолбэков) — для чипа модели в UI
            used_llm["backend"], used_llm["model"] = backend, model
            ACTIVE_LLM["backend"], ACTIVE_LLM["model"] = backend, model

        def on_tool(name, args):
            out.put({"type": "tool", "name": name,
                     "args": json.dumps(args, ensure_ascii=False)[:200]})

        from server.llm.guard import LoopGuard, RECOVERY_PROMPT
        guard = LoopGuard(
            hard_tokens=int(CFG.get("llm.max_tokens_hard", 4000)),
            max_seconds=int(CFG.get("llm.max_gen_seconds", 180)))
        looped = None

        t_req = time.monotonic()  # промпт собран, уходим в LLM
        for token in llm.chat_stream(messages, on_fallback=on_fallback,
                                     on_tool=on_tool, image=image,
                                     on_model=on_model,
                                     should_stop=stop_event.is_set):
            if stop_event.is_set():
                break
            if t_first is None:
                t_first = time.monotonic()
            n_tokens += 1
            full_reply.append(token)
            sentence_buf += token
            # НЕ шлём в UI куски псевдо-вызова: кривые модели (12b-qat)
            # печатают <|tool_call|>call:close_browser{} текстом. Как только
            # в буфере появился зачин такого — прекращаем стримить наружу,
            # хвост дособерём и обработаем после цикла.
            if "<|" in sentence_buf or "call:" in sentence_buf \
                    or re.search(r'\{\s*"name"\s*:', sentence_buf):
                pass  # придержали — не эхо-каем спецтокены в чат
            else:
                out.put({"type": "token", "text": token})
            looped = guard.feed(token)
            if looped:
                # обрыв стрима закрывает соединение — бэкенд гасит генерацию
                log.warning("LoopGuard: %s — обрываю генерацию", looped)
                report_problem("llm.guard", f"генерация зависла: {looped}",
                               "оборвала и привожу Сайку в чувство")
                break
            done = split_sentences(sentence_buf)
            # озвучиваем законченные предложения, остаток держим в буфере
            if len(done) > 1:
                for s in done[:-1]:
                    speak(s)
                sentence_buf = done[-1]
        log.info("LLM стрим завершён: %d токенов, прерван stop_event=%s",
                 n_tokens, stop_event.is_set())

        # Псевдо-вызовы текстом от кривых моделей: <|tool_call|>call:NAME{...}
        # или голый JSON {"name":"NAME"}. Вырезаем из ответа (в чат/память
        # такое не попадает), а безопасные намерения ИСПОЛНЯЕМ по-настоящему:
        # close_browser — закрыть окно; поисковые — заменить на честный
        # серверный поиск словами; shutdown — только пометка, без действия.
        _raw = "".join(full_reply)
        _has_pseudo = ("<|" in _raw or "call:" in _raw
                       or re.search(r'\{\s*"name"\s*:', _raw))
        if _has_pseudo:
            _names = re.findall(r'(?:call:|"name"\s*:\s*")([a-z_]+)',
                                _raw, re.I)
            clean = re.sub(r'<\|[^>]*\|>', '', _raw)
            clean = re.sub(r'call:[a-z_]+\s*(\{[^}]*\})?', '', clean, flags=re.I)
            clean = re.sub(r'\{\s*"name"\s*:.*?\}', '', clean, flags=re.S)
            clean = clean.strip()
            acted = None
            if "close_browser" in _names:
                try:
                    from server import browser_hands
                    if browser_hands.is_open():
                        browser_hands.close()
                        acted = "закрыла окно браузера"
                except Exception:
                    pass
            sentence_buf = ""
            if not clean:
                clean = "Закрыла браузер." if acted else "Секунду, разберусь."
            full_reply = [clean]
            out.put({"type": "token", "text": clean})  # чистый текст в чат
            speak(clean)
            log.info("Псевдо-вызовы вырезаны: %s; действие: %s",
                     _names, acted or "нет")
        if looped:
            # залипший хвост не озвучиваем и выкидываем из ответа
            sentence_buf = ""
            glitch = "".join(full_reply)[-70:]
            trimmed = guard.trimmed("".join(full_reply))
            full_reply = [trimmed] if trimmed else []
            out.put({"type": "guard", "reason": looped})
            # recovery: показываем Сайке её же затуп — пусть сама обыграет
            if not stop_event.is_set():
                rec_messages = messages + [
                    {"role": "assistant", "content": trimmed or "…"},
                    {"role": "system", "content": RECOVERY_PROMPT.format(
                        reason=looped, glitch=glitch)}]
                rec_guard = LoopGuard(hard_tokens=400, max_seconds=60)
                try:
                    for token in llm.chat_stream(
                            rec_messages, on_model=on_model,
                            should_stop=stop_event.is_set):
                        if stop_event.is_set() or rec_guard.feed(token):
                            break  # второй луп подряд — молча сдаёмся
                        full_reply.append(token)
                        sentence_buf += token
                        out.put({"type": "token", "text": token})
                        done = split_sentences(sentence_buf)
                        if len(done) > 1:
                            for s in done[:-1]:
                                speak(s)
                            sentence_buf = done[-1]
                except Exception as e:
                    log.warning("recovery после лупа не удался: %s", e)
        # Модель написала tool-вызовы ТЕКСТОМ (llama3.2 льёт JSON
        # {"name":...,"parameters":...} прямо в чат) — это не ответ.
        # Модель в чёрный список инструментов, мусор выкидываем и уходим
        # в повтор без инструментов (ветка «0 токенов» ниже).
        _txt = "".join(full_reply).strip()
        if _txt and re.match(r'^[\[\{\s]*\{\s*"name"\s*:', _txt) \
                and ("parameters" in _txt[:300] or "arguments" in _txt[:300]):
            bad_model = used_llm.get("model") or CFG.get("llm.model", "")
            log.warning("Модель %s пишет tool-JSON текстом — в чёрный "
                        "список инструментов", bad_model)
            if bad_model:
                CFG.set("llm.tools_broken", sorted(set(
                    CFG.get("llm.tools_broken", []) + [bad_model])))
            full_reply, sentence_buf, n_tokens = [], "", 0

        if n_tokens == 0 and not stop_event.is_set() and not looped:
            # Модель потратила все раунды на инструменты и не сказала НИ
            # СЛОВА (или ответ пустой) — молчать нельзя: повторяем один раз
            # БЕЗ инструментов, чтобы она хотя бы ответила словами
            log.info("Пустой ответ (0 токенов) — повторяю без инструментов")
            try:
                retry_msgs = messages + [{"role": "system", "content":
                    "(Служебно: инструменты сейчас недоступны — ответь "
                    "обычными словами, БЕЗ tool_call и без обещаний "
                    "что-то вызвать.)"}]
                for token in llm.chat_stream(retry_msgs, on_model=on_model,
                                             use_tools=False,
                                             should_stop=stop_event.is_set):
                    if stop_event.is_set():
                        break
                    if t_first is None:
                        t_first = time.monotonic()
                    n_tokens += 1
                    full_reply.append(token)
                    sentence_buf += token
                    out.put({"type": "token", "text": token})
                    done = split_sentences(sentence_buf)
                    if len(done) > 1:
                        for s in done[:-1]:
                            speak(s)
                        sentence_buf = done[-1]
            except Exception as e:
                log.warning("Повтор без инструментов не удался: %s", e)
        if sentence_buf.strip() and not stop_event.is_set():
            speak(sentence_buf.strip())
    except Exception as e:
        report_problem("llm", str(e), "проверь что Ollama или LM Studio запущены")
        out.put({"type": "error", "text": f"LLM недоступна: {e}"})

    # скорость генерации: считаем от первого токена (без времени prefill).
    # Статистику шлём ВСЕГДА, когда были токены (раньше короткие/быстрые
    # ответы оставались без строки «⚡ …» — dt<=0.2 резал их); честный tps
    # пишем только если стрим был достаточно длинным для замера
    if n_tokens >= 1 and t_first is not None:
        dt = time.monotonic() - t_first
        if True:
            stats = {"type": "stats", "tokens": n_tokens}
            if n_tokens > 2 and dt > 0.15:
                stats["tps"] = round((n_tokens - 1) / dt, 1)
            if used_llm.get("model"):
                stats["model"] = used_llm["model"]
            # задержка «услышала -> начала отвечать» (prefill + очередь)
            if heard_ts is not None:
                stats["latency_ms"] = round((t_first - heard_ts) * 1000)
            # Разбивка задержки по этапам — по ней видно, кто съел секунды:
            # «очередь» — от распознавания до старта пайплайна;
            # «память» — Chroma/SQLite RAG; «промпт» — дев-доска/инструменты;
            # «prefill» — LM Studio/Ollama пережёвывает контекст до 1-го токена
            try:
                log.info(
                    "Тайминги ответа: очередь %sмс | память %dмс | промпт %dмс"
                    " | LLM prefill %dмс | итого до 1-го токена %sмс",
                    round((t0 - heard_ts) * 1000) if heard_ts else "-",
                    round((t_mem - t0) * 1000),
                    round((t_req - t_mem) * 1000),
                    round((t_first - t_req) * 1000),
                    stats.get("latency_ms", "-"))
            except Exception:
                pass
            out.put(stats)
            # копим оценку отзывчивости МОДЕЛИ, КОТОРАЯ ОТВЕЧАЛА (после
            # фолбэков) — раньше рейтинг приписывался выбранной в конфиге
            try:
                if "tps" in stats:   # без замера — нечего писать в рейтинг
                    ratings.record_llm(used_llm.get("model")
                                       or CFG.get("llm.model", ""),
                                       stats["tps"])
            except Exception:
                pass

    tts_q.put(None)
    tts_thread.join(timeout=600)
    reply = "".join(full_reply).strip()
    if reply:
        # прервали на полуслове (живой контекст — юзер докинул) -> помечаем,
        # чтобы на следующем заходе она видела, что не договорила
        if stop_event.is_set() and n_tokens > 0:
            reply += " …(прервана — собеседник добавил уточнение)"
        memory.add_event(person_id, "assistant", reply)
    DIALOG_STATE["active_since"] = 0.0
    out.put({"type": "done"})


# ---------------------- импульсы (heartbeat) ----------------------
# «Живые таймеры самозапросов»: раз в минуту фоновый тик проверяет условия
# и, если пора, Сайка получает ВНУТРЕННИЙ импульс — сообщение самой себе,
# на которое отвечает как обычно (с инструментами). Так она сама вспоминает
# про открытое окно браузера и решает его судьбу, как живой человек.
# Механика расширяемая: новые импульсы = новые проверки в _impulse_tick.
IMPULSE_LAST: dict = {}
# присутствие пользователя: обновляется ТОЛЬКО его действиями (текст/голос),
# импульсы её собственных мыслей сюда не пишут
LAST_USER = {"ts": time.time(), "seen": False}  # seen: был ли юзер в ЭТОЙ сессии
IDLE_STATE = {"stage": 0}   # 0 тишины нет | 1 буркнула | 2 спросила «есть кто» | 3 бормочет


def _user_activity():
    LAST_USER["ts"] = time.time()
    LAST_USER["seen"] = True
    IDLE_STATE["stage"] = 0


def _impulse_ready(key, cooldown_s):
    if time.time() - IMPULSE_LAST.get(key, 0) < cooldown_s:
        return False
    # не влезаем в идущий ответ; «ответ» старше 10 мин считаем зависшим
    active = DIALOG_STATE["active_since"]
    if active and time.time() - active < 600:
        return False
    return bool(EVENT_CLIENTS)


def _fire_impulse(key, text):
    IMPULSE_LAST[key] = time.time()
    out = next(iter(EVENT_CLIENTS))
    log.info("Импульс %s: запускаю внутренний монолог", key)

    def run():
        # на время импульса инструменты пользователя заблокированы
        from server.llm import tools as _tls
        _tls.IMPULSE_MODE["on"] = True
        try:
            run_dialog(text, out, threading.Event())
        finally:
            _tls.IMPULSE_MODE["on"] = False

    threading.Thread(target=run, daemon=True).start()


def _impulse_tick():
    # ---------- ступени тишины (как idle-анимации персонажа в игре) ----------
    # Пара минут: мелочь — короткая мысль под нос. 15-20 мин: «а тут есть
    # кто?». Дальше: редкое забавное бормотание с большим кулдауном, часть
    # тиков молча пропускается — живой человек не разговаривает по таймеру.
    import random
    # пока пользователь в этой сессии ни разу не появлялся — молчим:
    # сервер могли запустить и уйти, «оживать» не перед кем
    if CFG.get("idle.enabled", True) and LAST_USER["seen"]:
        silence_min = (time.time() - LAST_USER["ts"]) / 60
        first = CFG.get("idle.first_min", 6)
        second = CFG.get("idle.second_min", 18)
        mutter = CFG.get("idle.mutter_min", 40)
        mutter_cd = CFG.get("idle.mutter_cooldown_min", 35) * 60
        stage = IDLE_STATE["stage"]
        if stage == 0 and silence_min >= first and _impulse_ready("idle", 120):
            IDLE_STATE["stage"] = 1
            extra = ""
            try:
                from server import browser_hands as _bh
                if _bh.is_open():
                    extra = (" Кстати, у тебя открыто окно браузера — если "
                             "оно уже не нужно, можешь закрыть его "
                             "инструментом close_browser.")
            except Exception:
                pass
            _fire_impulse("idle", (
                "[внутренний импульс — твоя собственная мысль, пользователь "
                f"ничего не писал] Тишина ~{int(silence_min)} мин: пользователь "
                "отошёл или занят. Можешь ОДНОЙ короткой фразой буркнуть себе "
                "под нос бытовую/ироничную мысль (не вопрос, ответа не "
                "требуешь). А можешь просто промолчать — тогда ответь ровно "
                "«...». НИКОГДА не заявляй, что что-то сделала (закрыла, "
                "проверила, навела порядок), если реально не вызывала "
                "инструмент." + extra))
        elif stage == 1 and silence_min >= second and _impulse_ready("idle", 120):
            IDLE_STATE["stage"] = 2
            _fire_impulse("idle", (
                "[внутренний импульс — твоя собственная мысль] Тишина уже "
                f"~{int(silence_min)} мин. Спроси легко и коротко, есть ли "
                "тут кто живой — одной фразой, в своём стиле, с лёгкой "
                "иронией, каждый раз по-разному. Без обид и драмы. Не "
                "заявляй действий, которых не делала."))
        elif stage in (2, 3) and CFG.get("idle.allow_self_shutdown", True) \
                and silence_min >= CFG.get("idle.goodbye_min", 300) \
                and _impulse_ready("idle", 120):
            # на «есть кто?» никто не ответил — можно попрощаться и уйти.
            # Решение и ТОН прощания — её: зависят от того, каким был
            # последний разговор (он в её RAW-памяти)
            IDLE_STATE["stage"] = 5
            _fire_impulse("idle", (
                "[внутренний импульс — твоя собственная мысль] На «есть ли "
                f"кто» никто не ответил, тишина ~{int(silence_min)} мин — "
                "тебя, похоже, оставили одну. Реши сама, по-человечески, "
                "опираясь на то, КАКИМ был последний разговор (тёплый, "
                "рабочий, нервный — вспомни): (а) тихо попрощаться 1-2 "
                "фразами в своём стиле, подстроив тон под этот разговор "
                "(в духе «да-а, походу меня оставили одну… ладно, до "
                "завтра»), и вызвать shutdown_self — я выключусь после "
                "твоих слов; или (б) остаться дежурить — тогда ответь "
                "ровно «...». Прощание каждый раз своё, без драмы и обид."))
        elif stage >= 2 and silence_min >= mutter \
                and _impulse_ready("idle", mutter_cd) and random.random() < 0.5:
            IDLE_STATE["stage"] = max(3, stage)
            _fire_impulse("idle", (
                "[внутренний импульс — твоя собственная мысль] Ты давно одна "
                f"(~{int(silence_min)} мин), на «есть кто?» никто не ответил. "
                "Смирилась. Можешь пробормотать себе под нос короткий "
                "забавный монолог из 1-2 фраз (самоирония, наблюдение, "
                "абсурдная мини-байка о себе) — как персонаж игры, у "
                "которого игрок отошёл. Пользователя НЕ зови, вопросов не "
                "задавай, действий не выдумывай. Или ответь «...» и молчи."))

    # --- окно браузера простаивает -> сама спрашивает/закрывает ---
    try:
        from server import browser_hands
        st = browser_hands.STATE
        if browser_hands.is_open():
            idle_min = (time.time() - st["last_used"]) / 60
            ask_after = CFG.get("browser.ask_after_min", 3)
            if idle_min >= ask_after and _impulse_ready("browser_ask", 600):
                _fire_impulse("browser_ask", (
                    "[внутренний импульс — пользователь этого не писал, это "
                    "твоя собственная мысль] Твоё окно браузера открыто и "
                    f"простаивает уже ~{int(idle_min)} мин. Реши сама, "
                    "по-человечески: если из разговора очевидно, что окно "
                    "больше не нужно — вызови close_browser и скажи одной "
                    "фразой, что закрыла. Если не уверена — коротко спроси "
                    "пользователя, оставить ли. Если недавно уже спрашивала "
                    "и он сказал оставить — просто молчи: ответь ровно "
                    "словом «...» и всё."))
    except Exception as e:
        log.debug("impulse browser: %s", e)


def _impulse_loop():
    while True:
        time.sleep(60)
        try:
            _impulse_tick()
        except Exception as e:
            log.debug("impulse tick: %s", e)


# ---------------------- WebSocket ----------------------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    out: "queue.Queue" = queue.Queue()
    EVENT_CLIENTS.add(out)
    stop_event = threading.Event()
    worker: threading.Thread | None = None

    # первым делом — id запуска: вкладка сравнит со своим и, если сервер
    # успел перезапуститься, сама перезагрузится (см. UI, тип «hello»)
    out.put({"type": "hello", "boot": BOOT_ID})
    # Беймакс здоровается и коротко докладывает, как система себя чувствует
    try:
        out.put({"type": "baymax", **baymax.greeting(stt.status(), tts.status())})
    except Exception:
        pass

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
                    if item.get("type") == "done":
                        # Сайка договорила — окно диалога продлевается,
                        # можно отвечать ей без имени
                        attn["until"] = time.time() + \
                            CFG.get("attention.window_s", 30)
                    await ws.send_text(json.dumps(item, ensure_ascii=False))
            except Exception:
                break

    send_task = asyncio.create_task(sender())

    # Очередь фраз: раньше каждая новая фраза стартовала ПАРАЛЛЕЛЬНЫЙ
    # run_dialog, пока старый ещё генерил — два стрима в одну LM Studio
    # ломали друг друга (сбитая генерация, перемешанные токены, «Context
    # size has been exceeded»). Теперь: пока Сайка отвечает, новые фразы
    # копятся в pending (транскриб при этом молотит на полной скорости),
    # а по окончании ответа склеиваются в ОДНО сообщение и уходят следом.
    pending: list[str] = []
    pending_meta = {"heard_ts": None, "image": None}
    pending_lock = threading.Lock()

    def _dialog_loop(user_text, heard_ts, image):
        # ЖИВОЙ КОНТЕКСТ (как у Claude): докинул реплику во время ответа —
        # текущий ответ прерывается, а новый заход стартует с уже обновлённой
        # памятью: там и её частичный ответ (run_dialog пишет его при
        # прерывании), и твоя новая фраза. Так она подхватывает вводные на
        # лету, а не отвечает на них отдельным куском потом.
        cur, hts, img = user_text, heard_ts, image
        while True:
            stop_event.clear()
            run_dialog(cur, out, stop_event, hts, img)
            with pending_lock:
                has = bool(pending)
                merged = " ".join(pending)
                pending.clear()
                phts = pending_meta["heard_ts"]
                pimg = pending_meta["image"]
                pending_meta.update(heard_ts=None, image=None)
            # прервали и НЕ докинули (стоп-команда/interrupt чистят pending)
            # -> выходим. Докинули -> pending есть -> заход с обновлённым
            # контекстом (память уже содержит начатый ответ + новую фразу).
            if not has:
                break
            out.put({"type": "dequeued", "text": merged})
            cur, hts, img = merged, (phts or hts), pimg

    def handle_text(user_text, heard_ts=None, image=None):
        nonlocal worker
        if worker is not None and worker.is_alive():
            if CFG.get("dialog.live_context", True):
                # докидка на лету: копим фразу И прерываем текущий ответ —
                # _dialog_loop подхватит её в обновлённом контексте
                log.info("handle_text: живой контекст — докидываю %r и "
                         "перезапускаю с учётом сказанного", user_text[:40])
                with pending_lock:
                    pending.append(user_text)
                    if pending_meta["heard_ts"] is None:
                        pending_meta["heard_ts"] = heard_ts
                    if image:
                        pending_meta["image"] = image
                    n = len(pending)
                out.put({"type": "queued", "text": user_text, "n": n})
                stop_event.set()   # прервать текущий ответ -> рестарт в loop
            else:
                # старое поведение: копим, ответим одним куском после
                log.info("handle_text: диалог идёт — фраза %r в очередь",
                         user_text[:40])
                with pending_lock:
                    pending.append(user_text)
                    if pending_meta["heard_ts"] is None:
                        pending_meta["heard_ts"] = heard_ts
                    if image:
                        pending_meta["image"] = image
                    n = len(pending)
                out.put({"type": "queued", "text": user_text, "n": n})
            return
        stop_event.clear()
        log.info("handle_text: стартую диалог для %r", user_text[:40])
        try:  # предохранитель shutdown_self: помним последнюю фразу юзера
            from server.llm import tools as _tls
            _tls.LAST_USER["text"] = user_text
        except Exception:
            pass
        worker = threading.Thread(
            target=_dialog_loop,
            args=(user_text, heard_ts, image), daemon=True)
        worker.start()

    # ---------- внимание: когда фраза адресована Сайке ----------
    # Правила: (1) в фразе есть имя -> отвечаем и открываем «окно диалога»;
    # (2) окно открыто (недавно общались) -> отвечаем; (3) иначе — фон
    # (телевизор, чужой разговор): показываем серым, но молчим.
    attn = {"until": 0.0}

    def _window():
        return CFG.get("attention.window_s", 30)

    def _edit_distance(a: str, b: str) -> int:
        if len(a) < len(b):
            a, b = b, a
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i] + [0] * len(b)
            for j, cb in enumerate(b, 1):
                cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                            prev[j - 1] + (ca != cb))
            prev = cur
        return prev[-1]

    def _fuzzy_hit(word: str, name: str) -> bool:
        """Слово похоже на имя: точный префикс — как раньше — или максимум
        1-2 буквы отличаются от него же по длине. Слух регулярно подменяет
        «Сайка» на созвучное с той же длиной и окончанием («зайка», «сайра»,
        «майка», «файка», «гайка», «чайка») — точный префикс это не ловит,
        а именно из-за этого не получается «дозваться»."""
        if word.startswith(name):
            return True
        if len(word) < 5:            # короче — слишком мало сигнала
            return False
        dist = _edit_distance(word[:len(name)], name)
        return dist <= CFG.get("attention.fuzzy_max_edits", 1)

    def _is_stop(text: str) -> bool:
        """Короткая команда «замолчи». НЕ уходит в LLM — просто глушим
        генерацию и озвучку (иначе маленькая модель начинает рассуждать, как
        ей замолчать). Ловим и «стоп», и «зайка остановись» (имя + стоп):
        сначала выкидываем обращение по имени, потом смотрим — короткая ли
        фраза, где есть стоп-слово."""
        stops = set(CFG.get("attention.stop_words",
                            ["стоп", "стой", "хватит", "замолчи", "молчи",
                             "помолчи", "тихо", "тише", "заткнись",
                             "остановись", "стопэ"]))
        names = tuple(CFG.get("attention.name_prefixes", ["сайк", "saik"]))
        words = re.findall(r"[а-яa-zё]+", text.lower())
        if not words:
            return False
        # убираем обращение по имени (и его искажения слухом)
        core = [w for w in words if not any(_fuzzy_hit(w, n) for n in names)]
        if not core:
            return False   # это просто имя, не команда
        # короткая фраза, где есть хотя бы одно стоп-слово = «замолчи»
        return len(core) <= 4 and any(w in stops for w in core)

    def _addressed(text: str) -> bool:
        names = tuple(CFG.get("attention.name_prefixes", ["сайк", "saik"]))
        words = re.findall(r"[а-яa-zё]+", text.lower())
        if any(_fuzzy_hit(w, n) for w in words for n in names):
            return True
        # склейка соседних слов — слух иногда рвёт «сайка» на «сай ка».
        # Тут только точный префикс: нечёткость на склейке двух случайных
        # слов слишком легко даёт ложные срабатывания (например «на сайт»
        # даёт «насайт», «сайт и» — «сайти», почти неотличимо от «сайка»).
        pairs = (a + b for a, b in zip(words, words[1:]))
        return any(p.startswith(n) for p in pairs for n in names)

    def _fire_voice_hotkey(text):
        try:
            from server import hotkeys
            b = hotkeys.match_voice(text)
            if b and hotkeys.fire(b["action"], b.get("params", "")):
                log.info("Голосовой хоткей «%s» -> %s", b["trigger"],
                         b["action"])
                out.put({"type": "hotkey", "trigger": b["trigger"],
                         "action": b["action"]})
                return True
        except Exception as e:
            log.debug("voice hotkey: %s", e)
        return False

    def voice_phrase(r):
        now = time.time()
        heard_mono = r.pop("_heard_mono", None)  # внутреннее, не шлём в UI
        # «стоп/хватит/молчи» — глушим генерацию и озвучку, в LLM не отправляем
        if _is_stop(r["text"]):
            _user_activity()
            stop_event.set()
            with pending_lock:
                pending.clear()   # и копившиеся фразы тоже — «стоп» значит стоп
            out.put({"type": "stt_stop", **r})
            return
        # ГОЛОСОВОЙ ХОТКЕЙ: слово-триггер срабатывает МГНОВЕННО, мимо LLM
        if _fire_voice_hotkey(r["text"]):
            _user_activity()
            return
        # режим «слушать всё»: отвечает на любую распознанную речь, без имени
        # и без окна (умный режим внимания остаётся дефолтом — см. UI-тумблер)
        always = CFG.get("attention.always", False)
        if (always or not CFG.get("attention.enabled", True)
                or _addressed(r["text"]) or now < attn["until"]):
            _user_activity()
            attn["until"] = now + _window()
            out.put({"type": "stt", **r})
            handle_text(r["text"], heard_ts=heard_mono)
        else:
            out.put({"type": "stt_ignored", **r})

    try:
        while True:
            msg = await ws.receive()
            # клиент отключился (вкладка закрыта/обновлена): starlette отдаёт
            # событие disconnect ОДИН раз, повторный receive() кидает
            # RuntimeError. Ловим тип явно и выходим тихо, без спама трейсом.
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                pcm = np.frombuffer(msg["bytes"], dtype=np.int16)
                t0 = time.monotonic()
                results = await asyncio.get_event_loop().run_in_executor(
                    None, stt.process_chunk, pcm)
                stt_ms = round((time.monotonic() - t0) * 1000)
                for r in results:
                    # сколько заняла транскрибация и когда услышала (для UI)
                    r["stt_ms"] = stt_ms
                    r["heard_at"] = time.strftime("%H:%M:%S")
                    r["_heard_mono"] = time.monotonic()
                    voice_phrase(r)
            elif msg.get("text"):
                data = json.loads(msg["text"])
                mtype = data.get("type")
                if mtype == "text":
                    # набранный текст не эхо-каем обратно — UI уже показал
                    # пузырь сам; «услышано: …» остаётся только для голоса
                    log.info("WS: текст от пользователя: %r",
                             str(data.get("text"))[:60])
                    _user_activity()
                    # печатный «стоп/хватит» = КОМАНДА, как и голосовой:
                    # глушим генерацию и инструменты, в LLM не отправляем
                    # (раньше уходил «докидкой» и амок продолжался)
                    if _is_stop(data.get("text", "")):
                        log.info("WS: текстовая стоп-команда — глушу всё")
                        stop_event.set()
                        with pending_lock:
                            pending.clear()
                        out.put({"type": "stt_stop",
                                 "text": data.get("text", "")})
                        continue
                    # печатный хоткей-триггер — тоже мгновенно, мимо LLM
                    if _fire_voice_hotkey(data.get("text", "")):
                        continue
                    attn["until"] = time.time() + _window()
                    handle_text(data["text"], heard_ts=time.monotonic(),
                                image=data.get("image"))
                elif mtype == "mic_on":
                    # включение микрофона = намерение поговорить
                    attn["until"] = time.time() + _window()
                elif mtype == "mic_stop":
                    t0 = time.monotonic()
                    results = await asyncio.get_event_loop().run_in_executor(
                        None, stt.flush)
                    stt_ms = round((time.monotonic() - t0) * 1000)
                    for r in results:
                        r["stt_ms"] = stt_ms
                        r["heard_at"] = time.strftime("%H:%M:%S")
                        r["_heard_mono"] = time.monotonic()
                        voice_phrase(r)
                elif mtype == "interrupt":
                    # ВАЖНО для отладки «не отвечает»: если это летит часто —
                    # клиентский барж-ин глушит каждый ответ (шум в микрофон,
                    # клик по эквалайзеру, клавиша V)
                    log.info("WS: interrupt от клиента — глушу генерацию")
                    stop_event.set()
                    with pending_lock:
                        pending.clear()
                    # перебили её на полуслове (амплитудный барж-ин на
                    # клиенте) — это само по себе доказывает, что обращаются
                    # к ней, имя можно не повторять
                    attn["until"] = time.time() + _window()
    except WebSocketDisconnect:
        pass
    finally:
        stop_event.set()
        EVENT_CLIENTS.discard(out)
        out.put(None)
        send_task.cancel()


def _handspc_port():
    url = CFG.get("tools.handspc_url", "http://127.0.0.1:8767")
    return urlparse(url).port or 8767


def _close_handspc():
    """HandsPC — отдельная программа (C:\\AI\\HandsPC, своё окно), не дочерний
    процесс Сайки, поэтому сама по себе не закрывается вместе с ней. По
    просьбе пользователя (2026-07-15): закрытие окна Сайки должно тянуть
    за собой и HandsPC — ищем процесс по порту и убиваем."""
    if kill_by_port(_handspc_port(), "HandsPC"):
        log.info("HandsPC закрыт вместе с Сайкой")


def _unload_llms():
    """При выходе выгружаем прогретые локальные LLM (2026-07-20): иначе
    Ollama держит модель в VRAM ещё keep_alive-минуты после закрытия
    Сайки, а LM Studio — по своему TTL. Быстро (timeout 3с на модель),
    ошибки глотаем — выходу ничто не должно мешать."""
    try:
        for backend, name in llm._loaded_with_backend():
            try:
                llm.unload_model(backend, name)
            except Exception:
                pass
    except Exception:
        pass


def _on_exit():
    _close_handspc()
    _unload_llms()


def _autostart_components():
    """Автопуск слуха/голоса/мозгов при старте (2026-07-20). Каждый компонент
    пробуется по списку кандидатов ПО УБЫВАНИЮ приоритета: сломался лучший —
    молча берём следующий. Слух/голос — конфиг + fallback_order; мозги —
    рейтинг скорости (data/ratings.json), затем выбор из конфига.
    Работает фоном, старту сервера не мешает."""
    time.sleep(2)  # даём uvicorn подняться, потом греем тяжёлое

    def _try_chain(kind, names, loader):
        for name in names:
            try:
                loader(name)
                log.info("Автопуск: %s (%s) готов", kind, name)
                return name
            except Exception as e:
                report_problem(kind, f"{name}: {e}",
                               "автопуск пробует следующий по списку")
        report_problem(kind, "ни один движок не поднялся",
                       "смотри logs/saika.log")
        return None

    # слух: выбранный движок, дальше по fallback_order
    stt_chain = [CFG.get("stt.engine", "gigaam")]
    for n in CFG.get("stt.fallback_order", []):
        if n not in stt_chain:
            stt_chain.append(n)
    _try_chain("stt", stt_chain, stt.load_engine)

    # голос: аналогично
    tts_chain = [CFG.get("tts.engine", "qwen3")]
    for n in CFG.get("tts.fallback_order", []):
        if n not in tts_chain:
            tts_chain.append(n)
    _try_chain("tts", tts_chain, tts.load_engine)
    # разовый бенч незамеренных запасных голосов — чтобы выбор «по рейтингу»
    # опирался на реальные замеры этого ПК, а не на порядок в конфиге
    try:
        tts.benchmark_missing()
    except Exception as e:
        log.info("Бенч голосов пропущен: %s", e)

    # мозги: СНАЧАЛА выбранная пользователем модель (config) — его выбор
    # важнее рейтинга, рейтинг чисто скоростной и всегда тащит самую мелкую
    # (e2b «обгоняет» e4b по ток/с, но не по уму). Остальные — запасные по
    # убыванию рейтинга, если выбранная не поднялась.
    try:
        tps = ratings.llm_tps()
        cands = [(m["backend"], m["name"]) for m in llm.list_models()
                 if m["backend"] in ("ollama", "lmstudio")
                 and "embed" not in m["name"].lower()]
        cands.sort(key=lambda c: -tps.get(c[1], 0))
        cfg_pick = (CFG.get("llm.backend", "ollama"), CFG.get("llm.model", ""))
        if cfg_pick[1] and cfg_pick[0] in ("ollama", "lmstudio"):
            cands = [cfg_pick] + [c for c in cands if c != cfg_pick]
        for backend, model in cands:
            try:
                if not llm.switch_model(backend, model):
                    raise RuntimeError("прогрев не удался")
                CFG.set("llm.backend", backend)
                CFG.set("llm.model", model)
                log.info("Автопуск: мозги — %s/%s (%.1f ток/с в рейтинге)",
                         backend, model, tps.get(model, 0))
                break
            except Exception as e:
                report_problem("llm", f"{model}: {e}",
                               "автопуск пробует следующую модель")
    except Exception as e:
        report_problem("llm", str(e), "автопуск мозгов не удался")


def main():
    (ROOT / "logs").mkdir(exist_ok=True)
    dreampc.kill_stale()  # чистим детач-воркер с прошлого запуска (если завис)
    train_manager.kill_stale()  # то же для воркера дообучения
    from server.llm import locallm as _locallm
    _locallm.kill_stale()  # то же для воркера LocalLM
    # закрытие HandsPC при завершении Сайки — и по Ctrl+C/обычному выходу
    # (atexit), и по крестику на окне консоли (Windows CTRL_CLOSE_EVENT,
    # который обычный atexit/signal не ловит — см. proc_utils)
    atexit.register(_on_exit)
    register_console_close_handler(_on_exit)
    # автопрогрев (2026-07-20): слух/голос/мозги поднимаются сами при старте,
    # мозги — лучшая модель по рейтингу скорости (data/ratings.json)
    if CFG.get("autostart.enabled", True):
        threading.Thread(target=_autostart_components, daemon=True).start()
    # голос без браузера: серверный микрофон + озвучка в колонки (для UE-UI)
    if CFG.get("mic.server_capture", False):
        from server.voice_local import LocalVoiceLoop

        def _broadcast(item):
            for q in list(EVENT_CLIENTS):
                try:
                    q.put_nowait(item)
                except Exception:
                    pass

        LocalVoiceLoop(CFG, stt, run_dialog, _broadcast, report_problem,
                       _ServerSpeaker,
                       has_browser=lambda: bool(EVENT_CLIENTS)).start()
    start_scheduler(memory, llm.chat_once)
    # страховка видимого браузера: окно без дела N минут -> тихо закрыть.
    # Плюс проактивная докачка Chromium, если прошлую загрузку порвала сеть
    try:
        from server import browser_hands
        browser_hands.idle_watchdog()
        browser_hands.ensure_ready_bg(report_problem)
    except Exception:
        pass
    # heartbeat самозапросов (импульсы): сама вспоминает про окно браузера
    threading.Thread(target=_impulse_loop, daemon=True).start()
    # поднять сохранённые клавиатурные хоткеи (если пакет keyboard стоит)
    try:
        from server import hotkeys
        hotkeys.register_all_keys()
    except Exception as e:
        log.debug("hotkeys register: %s", e)
    # живой самолечащий сторож: следит в реальном времени, Беймакс говорит
    # о проблеме и тут же чинит (report_problem внутри зовёт Беймакса)
    try:
        from server import self_heal
        self_heal.start(report_problem)
    except Exception as e:
        log.debug("self_heal: %s", e)
    # боты мессенджеров (Telegram/VK) — если включены и заполнены токены;
    # иначе тихо ничего не делает. Управление ПК с телефона.
    try:
        messengers.start_all()
    except Exception as e:
        log.warning("Мессенджеры не поднялись: %s", e)
    host = CFG.get("server.host", "127.0.0.1")
    port = CFG.get("server.port", 8765)
    # Порт занят прошлым, ещё живым экземпляром Сайки (частый случай: запустил
    # start.bat, пока старое окно не закрыто) -> uvicorn падает с 10048, и
    # start.bat после 3 попыток сдаётся. Сами освобождаем порт — новый запуск
    # просто перехватывает управление у зависшего старого.
    if kill_by_port(port, "прошлый экземпляр Сайки"):
        log.info("Порт %s был занят старым экземпляром — освободила", port)
        time.sleep(1.0)
    # Открываем вкладку только на ПЕРВОМ запуске. При крэш-рестарте start.bat
    # выставляет SAIKA_AUTO_OPEN=0 — новую вкладку не плодим, уже открытая
    # сама переподключится и обновится по BOOT_ID. Так после серии падений
    # не остаётся десятка вкладок.
    auto_open = CFG.get("server.auto_open_browser", True)
    env_open = os.environ.get("SAIKA_AUTO_OPEN")
    if env_open is not None:
        auto_open = env_open == "1"
    if auto_open:
        # не плодим вкладки (2026-07-20): старая вкладка после рестарта сервера
        # сама переподключается по WS за ~1-2 сек (логика BOOT_ID в UI).
        # Ждём 3 сек: если кто-то уже подключился — вкладка жива, новую не
        # открываем. Подключений нет — значит вкладки правда нет, открываем.
        def _open_if_no_tab():
            if EVENT_CLIENTS:
                log.info("Вкладка уже открыта (переподключилась) — "
                         "новую не открываю")
                return
            webbrowser.open(f"http://{host}:{port}")

        threading.Timer(3.0, _open_if_no_tab).start()
    log.info("Сайка запускается на http://%s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
