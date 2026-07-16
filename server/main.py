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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from server.config import CFG, ROOT
from server import baymax
from server.persona import build_system_prompt
from server.llm import manager as llm
from server.llm import dreampc
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

app = FastAPI(title="Saika")

PROBLEMS: list[dict] = []          # лента проблем/починок для UI
EVENT_CLIENTS: set = set()          # активные websockets
DIALOG_CUTOFF = {"ts": 0.0}         # «новый диалог»: контекст только после отметки
# уникальный id этого запуска процесса: вкладка запоминает его при коннекте
# и, если после переподключения видит другой id, значит сервер
# перезапустился (упал и поднялся start.bat'ом) — делает F5 сама. Так одна
# и та же вкладка всегда свежая, а новые вкладки на рестартах не плодятся.
BOOT_ID = uuid.uuid4().hex


def report_problem(component, error, action, diag=None):
    item = {"component": component, "error": error, "action": action}
    PROBLEMS.append(item)
    del PROBLEMS[:-50]
    # Беймакс: та же новость, но живым языком, отдельным пузырём в чат
    try:
        bm = baymax.line(component, error, action, diag)
    except Exception:
        bm = None
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
                "backend": CFG.get("llm.backend"),
                "model": CFG.get("llm.model")},
        "stt": stt.status(),
        "tts": tts.status(),
        "memory": memory.stats(),
        "problems": PROBLEMS[-10:],
        "assistant": CFG.get("assistant_name", "Сайка"),
        "attention_always": CFG.get("attention.always", False),
    }


@app.get("/api/models")
def models():
    return {"models": llm.list_models(), "loaded": llm.loaded_models()}


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


@app.post("/api/memory/compress")
def force_compress():
    """Ручной запуск сжатия памяти (для отладки)."""
    threading.Thread(target=memory.compress_raw, args=(llm.chat_once,),
                     daemon=True).start()
    return {"ok": True}


# ---------------------- диалоговый пайплайн ----------------------
def run_dialog(user_text: str, out: "queue.Queue", stop_event: threading.Event,
               heard_ts: float | None = None):
    """Блокирующий пайплайн в отдельном потоке: LLM stream -> TTS stream.
    heard_ts (time.monotonic) — момент, когда фраза была распознана: по нему
    считаем задержку до первого токена ответа («думала N сек»)."""
    person_id = CFG.get("owner.id", "owner")
    person_name = CFG.get("owner.name", "Owner")
    memory.add_event(person_id, "user", user_text)

    mem_context = ""
    try:
        mem_context = memory.build_context(person_id, user_text)
    except Exception as e:
        report_problem("memory", str(e), "продолжаю без контекста памяти")

    system = build_system_prompt(mem_context, person_name)
    # если HandsPC жив — Сайка должна знать о своих «руках», иначе она
    # уверяет, что не имеет доступа к интернету, хотя инструменты подключены
    try:
        from server.llm import tools as handspc
        names = [s["function"]["name"] for s in handspc.schemas()]
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
                "- Никогда не говори, что у тебя нет доступа к интернету "
                "или инструментов — это неправда.")
    except Exception:
        pass
    history = memory.recent_raw(limit=CFG.get("llm.max_history", 30),
                                since_ts=DIALOG_CUTOFF["ts"])
    messages = [{"role": "system", "content": system}]
    messages += [{"role": r, "content": t} for r, t in history]

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

        def on_tool(name, args):
            out.put({"type": "tool", "name": name,
                     "args": json.dumps(args, ensure_ascii=False)[:200]})

        for token in llm.chat_stream(messages, on_fallback=on_fallback,
                                     on_tool=on_tool):
            if stop_event.is_set():
                break
            if t_first is None:
                t_first = time.monotonic()
            n_tokens += 1
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

    # скорость генерации: считаем от первого токена (без времени prefill)
    if n_tokens > 1 and t_first is not None:
        dt = time.monotonic() - t_first
        if dt > 0.2:
            stats = {"type": "stats", "tps": round((n_tokens - 1) / dt, 1),
                     "tokens": n_tokens}
            # задержка «услышала -> начала отвечать» (prefill + очередь)
            if heard_ts is not None:
                stats["latency_ms"] = round((t_first - heard_ts) * 1000)
            out.put(stats)

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

    def handle_text(user_text, heard_ts=None):
        nonlocal worker
        stop_event.clear()
        worker = threading.Thread(
            target=run_dialog,
            args=(user_text, out, stop_event, heard_ts), daemon=True)
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

    def voice_phrase(r):
        now = time.time()
        heard_mono = r.pop("_heard_mono", None)  # внутреннее, не шлём в UI
        # «стоп/хватит/молчи» — глушим генерацию и озвучку, в LLM не отправляем
        if _is_stop(r["text"]):
            stop_event.set()
            out.put({"type": "stt_stop", **r})
            return
        # режим «слушать всё»: отвечает на любую распознанную речь, без имени
        # и без окна (умный режим внимания остаётся дефолтом — см. UI-тумблер)
        always = CFG.get("attention.always", False)
        if (always or not CFG.get("attention.enabled", True)
                or _addressed(r["text"]) or now < attn["until"]):
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
                    attn["until"] = time.time() + _window()
                    handle_text(data["text"], heard_ts=time.monotonic())
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
                    stop_event.set()
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


def main():
    (ROOT / "logs").mkdir(exist_ok=True)
    dreampc.kill_stale()  # чистим детач-воркер с прошлого запуска (если завис)
    # закрытие HandsPC при завершении Сайки — и по Ctrl+C/обычному выходу
    # (atexit), и по крестику на окне консоли (Windows CTRL_CLOSE_EVENT,
    # который обычный atexit/signal не ловит — см. proc_utils)
    atexit.register(_close_handspc)
    register_console_close_handler(_close_handspc)
    start_scheduler(memory, llm.chat_once)
    host = CFG.get("server.host", "127.0.0.1")
    port = CFG.get("server.port", 8765)
    # Открываем вкладку только на ПЕРВОМ запуске. При крэш-рестарте start.bat
    # выставляет SAIKA_AUTO_OPEN=0 — новую вкладку не плодим, уже открытая
    # сама переподключится и обновится по BOOT_ID. Так после серии падений
    # не остаётся десятка вкладок.
    auto_open = CFG.get("server.auto_open_browser", True)
    env_open = os.environ.get("SAIKA_AUTO_OPEN")
    if env_open is not None:
        auto_open = env_open == "1"
    if auto_open:
        threading.Timer(1.5, webbrowser.open,
                        args=(f"http://{host}:{port}",)).start()
    log.info("Сайка запускается на http://%s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
