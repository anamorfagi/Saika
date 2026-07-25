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
from server import avatar
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
HISTORY_ANCHOR = {"ts": 0.0}        # якорь окна истории: стабильный префикс промпта => живой KV-кэш
_SILENCE_REPORTED = {"ts": 0.0}     # троттлинг жалоб на молчание модели
DIALOG_STATE = {"active_since": 0.0, "first_token_ts": 0.0}   # идёт ли сейчас ответ + успела ли выдать первый токен (для импульсов и живого контекста)
LAST_IMAGE = {"data": None, "ts": 0.0}  # последняя картинка (для OCR слепыми)
# уникальный id этого запуска процесса: вкладка запоминает его при коннекте
# и, если после переподключения видит другой id, значит сервер
# перезапустился (упал и поднялся start.bat'ом) — делает F5 сама. Так одна
# и та же вкладка всегда свежая, а новые вкладки на рестартах не плодятся.
BOOT_ID = uuid.uuid4().hex


def broadcast_event(evt: dict):
    """Разослать событие всем открытым вкладкам (websocket-очередям)."""
    for ws_queue in list(EVENT_CLIENTS):
        try:
            ws_queue.put_nowait(evt)
        except Exception:
            pass


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


# ---------- собственный веб-аватар (three-vrm, 2026-07-25) ----------
@app.get("/avatar")
def avatar_page():
    return FileResponse(ROOT / "ui" / "avatar.html",
                        headers={"Cache-Control": "no-store"})


@app.get("/vendor/{fname}")
def vendor_asset(fname: str):
    """JS-библиотеки рендера (three.js и др.) из ui/vendor — офлайн."""
    if "/" in fname or "\\" in fname or ".." in fname:
        return JSONResponse({"error": "bad name"}, status_code=400)
    p = ROOT / "ui" / "vendor" / fname
    if not p.exists() or p.suffix != ".js":
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(p, media_type="application/javascript",
                        headers={"Cache-Control": "max-age=3600"})


def _avatar_model_path():
    from pathlib import Path as _P
    raw = CFG.get("avatar.web.model", "models/avatar/model.vrm")
    p = _P(raw)
    return p if p.is_absolute() else (ROOT / raw)


@app.get("/avatar/model.vrm")
def avatar_model():
    p = _avatar_model_path()
    if not p.exists():
        return JSONResponse(
            {"error": f"нет модели: {p} — укажи путь в avatar.web.model"},
            status_code=404)
    return FileResponse(p, media_type="model/gltf-binary")


def _anims_dir():
    from pathlib import Path as _P
    raw = CFG.get("avatar.web.anims_dir", "models/avatar/anims")
    p = _P(raw)
    return p if p.is_absolute() else (ROOT / raw)


@app.get("/avatar/anims")
def avatar_anims():
    """Библиотека анимаций: список *.vrma. Имя файла = имя жеста — новый
    файл в папке автоматически становится жестом, доступным Сайке."""
    d = _anims_dir()
    if not d.exists():
        return []
    return sorted(f.name for f in d.glob("*.vrma"))


@app.get("/avatar/anims/{fname}")
def avatar_anim_file(fname: str):
    if "/" in fname or "\\" in fname or ".." in fname:
        return JSONResponse({"error": "bad name"}, status_code=400)
    p = _anims_dir() / fname
    if not p.exists() or p.suffix.lower() != ".vrma":
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(p, media_type="model/gltf-binary")


def _outfits_dir():
    """Наряды (2026-07-25): смена одежды через ПОЛНОЦЕННУЮ подмену VRM-файла
    целиком (не toggle мешей — обычный экспорт из VRoid Studio не хранит
    несколько нарядов в одном файле). Кладём каждый наряд отдельным .vrm в
    эту папку — имя файла = имя наряда, avatar.html подгружает его вместо
    базовой модели по команде change_outfit."""
    from pathlib import Path as _P
    raw = CFG.get("avatar.web.outfits_dir", "models/avatar/outfits")
    p = raw if isinstance(raw, _P) else _P(raw)
    p = p if p.is_absolute() else (ROOT / raw)
    p.mkdir(parents=True, exist_ok=True)
    return p


@app.get("/avatar/outfits")
def avatar_outfits():
    """Список нарядов: *.vrm из models/avatar/outfits (имя без расширения).
    «default» — всегда доступен, это базовая модель из avatar.web.model."""
    d = _outfits_dir()
    names = sorted(f.stem for f in d.glob("*.vrm")) if d.exists() else []
    return {"outfits": ["default"] + names}


@app.get("/avatar/outfits/{fname}")
def avatar_outfit_file(fname: str):
    if "/" in fname or "\\" in fname or ".." in fname:
        return JSONResponse({"error": "bad name"}, status_code=400)
    p = _outfits_dir() / fname
    if not p.exists() or p.suffix.lower() != ".vrm":
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(p, media_type="model/gltf-binary")


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
    from server.llm import passport as _passport
    return {"models": llm.list_models(), "loaded": llm.loaded_models(),
            "ratings": ratings.llm_scores(), "tps": ratings.llm_tps(),
            "manual": ratings.manual_scores(),
            "passports": _passport.all_passports()}


@app.post("/api/ratings/manual")
def ratings_manual(payload: dict):
    """Синхронизация ручных оценок из UI. Раньше палочки-оценки жили только
    в localStorage браузера — сервер их не видел, и автопуск игнорировал
    выбор владельца (жалоба 2026-07-23). Принимает либо {"scores": {имя:
    1..10}} (массовая, при старте UI), либо {"name": ..., "score": 1..10|
    null} (одиночная, при перетаскивании палочек)."""
    if isinstance(payload.get("scores"), dict):
        merged = ratings.merge_manual(payload["scores"])
    else:
        ratings.set_manual(payload.get("name", ""), payload.get("score"))
        merged = ratings.manual_scores()
    return {"ok": True, "manual": merged}


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


_MD_STRIP_RE = re.compile(r'(\*\*|__|`{1,3}|^\s*#{1,6}\s+|^\s*[-*•]\s+)',
                          re.MULTILINE)


def _strip_markdown(text: str) -> str:
    """Защита от markdown в живой речи (2026-07-23): персона ПРЯМО запрещает
    **, #, списки — ответы озвучиваются голосом, и звёздочки либо молчат,
    либо звучат абсурдно. Но дисциплина модели не гарантия (живой инцидент:
    t-tech/T-lite-it-2.1 сплошь в **жирном** и списках вопреки прямому
    запрету в промпте) — чистим кодом на выходе, а не только просьбой.
    Снимает только маркеры разметки, слова не трогает."""
    if not text or ("*" not in text and "__" not in text and "#" not in text
                    and "`" not in text
                    and not re.search(r'^\s*[-•]\s+', text, re.MULTILINE)):
        return text
    cleaned = _MD_STRIP_RE.sub("", text)
    cleaned = re.sub(r'\*', '', cleaned)   # одиночные звёздочки-огрызки
    return re.sub(r'[ \t]{2,}', ' ', cleaned).strip()


# --------- текстовый протокол жестов для маленьких моделей (2026-07-25) -----
# Мелкие/квантованные модели часто НЕ умеют tool-calls (или пишут их кривым
# JSON-текстом — см. чёрный список llm.tools_broken). Жесты аватара для них
# гарантируем текстовым маркером: модель пишет в ответе [жест:joy] (или
# [эмоция: радость]) — сервер исполняет жест ДЕТЕРМИНИРОВАННО кодом и
# вырезает маркер из озвучки/текста. Работает с любой моделью, которая
# способна напечатать квадратные скобки.
_GESTURE_MARK_RE = re.compile(
    r'[\[({]\s*(?:жест|эмоция|gesture|emote)\s*[:=\-]?\s*'
    r'([a-zа-яё0-9_]+)\s*[\])}]', re.I)
# ОБОРВАННЫЙ маркер (генерация кончилась на «[жест:good» без скобки,
# 2026-07-25 — озвучка честно читала «жест гуд» вслух). Вырезаем хвост,
# жест из него по возможности исполняем.
_GESTURE_TAIL_RE = re.compile(
    r'[\[({]\s*(?:жест|эмоция|gesture|emote)\s*[:=\-]?\s*'
    r'([a-zа-яё0-9_]*)\s*$', re.I)


def _apply_gesture_marks(text: str, fire: bool = True) -> str:
    """Найти маркеры [жест:имя], исполнить (fire=True) и вырезать из текста."""
    if not text or not ("[" in text or "(" in text or "{" in text):
        return text

    def _sub(m):
        if fire:
            try:
                r = avatar.fire_named(m.group(1))
                log.info("жест-маркер %r -> %s", m.group(0), r)
            except Exception as e:
                log.debug("жест-маркер %r: %s", m.group(0), e)
        return " "

    out = _GESTURE_MARK_RE.sub(_sub, text)
    out = _GESTURE_TAIL_RE.sub(_sub, out)   # оборванный маркер в конце
    return re.sub(r'[ \t]{2,}', ' ', out).strip()


def _diagnose_silence(backend: str, model: str, generated_tokens: int) -> str:
    """Сайка промолчала — собираем ЧЕЛОВЕЧЕСКОЕ объяснение для чата
    (2026-07-23, просьба владельца: «выводить, почему модель не ответила»).
    Раньше пустой ответ выглядел как «прослушала и проигнорила», а причина
    жила только в logs/saika.log."""
    parts = []
    if generated_tokens > 0:
        parts.append("я ГЕНЕРИРОВАЛА ответ (%d токенов), но всё "
                     "сгенерированное оказалось служебным — размышления или "
                     "псевдо-вызовы инструментов, показать нечего"
                     % generated_tokens)
    if backend != "cloud":
        try:
            if not llm.backend_status().get(backend):
                parts.append(f"бэкенд {backend} не отвечает — он запущен?")
        except Exception:
            pass
    try:
        from server.llm import passport as _pp
        p = _pp.get(model)
        if p and not p.get("big_prompt_ok"):
            parts.append("по паспорту эта модель молча давится большим "
                         "промптом (класс багов «0 токенов») — начни новый "
                         "диалог 🧹 или подними Context Length в LM Studio")
    except Exception:
        pass
    try:
        g = system_info().get("gpu") or {}
        if g.get("vram_total") and g.get("vram_used") and \
                g["vram_used"] / g["vram_total"] > 0.92:
            parts.append("VRAM почти забита (%.1f/%.1f ГБ) — модель могла не "
                         "влезть или генерировать мучительно медленно; "
                         "выгрузи лишнее кнопкой ⏏ в списке моделей"
                         % (g["vram_used"] / 2**30, g["vram_total"] / 2**30))
    except Exception:
        pass
    if not parts:
        parts.append("модель вернула пустой ответ без ошибки — чаще всего "
                     "это переполненное окно контекста или зависший prefill; "
                     "попробуй 🧹 новый диалог или перезагрузи модель ⏏/⬇")
    return "; ".join(parts)


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
        elif action == "delete":
            # крестик ✕: стереть модель с диска (Ollama API / папка LM Studio)
            detail = await asyncio.get_event_loop().run_in_executor(
                None, llm.delete_model, backend, name)
            log.info("Модель удалена по запросу из UI: %s/%s", backend, name)
            return {"ok": True, "detail": detail}
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
        llm.save_cloud_key(payload["api_key"], payload.get("provider"))
    enabled = bool(payload.get("enabled"))
    CFG.set("llm.cloud.enabled", enabled)
    if enabled and payload.get("model"):
        CFG.set("llm.backend", "cloud")
        CFG.set("llm.model", payload["model"])
    # ПРОВЕРКА КЛЮЧА И МОДЕЛИ (2026-07-23): раньше «Сохранить и включить»
    # просто писало конфиг, и опечатка в имени модели (или модель другого
    # провайдера, напр. openrouter-имя с «:free» у Groq) всплывала только
    # ошибкой при первой фразе. Теперь сразу спрашиваем у провайдера
    # /models: жив ли ключ и есть ли такая модель; если нет — подсказываем.
    check = {"key_ok": None, "model_ok": None, "models": []}
    try:
        import requests as _rq
        base = (CFG.get("llm.cloud.base_url") or "").rstrip("/")
        key = (llm._cloud() or {}).get("key", "")
        if base and key:
            r = _rq.get(base + "/models",
                        headers={"Authorization": "Bearer " + key},
                        timeout=8)
            if r.status_code in (401, 403):
                check["key_ok"] = False
            else:
                r.raise_for_status()
                check["key_ok"] = True
                ids = [m.get("id", "") for m in
                       (r.json().get("data") or [])]
                check["models"] = ids[:40]
                want = payload.get("model") or CFG.get("llm.cloud.model", "")
                if ids and want:
                    check["model_ok"] = want in ids
    except Exception as e:
        log.info("Проверка облачного ключа не удалась: %s", e)
    return {"ok": True, **check}


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


@app.post("/api/panic_unload")
async def panic_unload():
    """«ЖЁСТКАЯ РАЗГРУЗКА» (2026-07-25, просьба владельца): выгрузить ВСЁ
    тяжёлое из памяти разом — все STT-движки (включая внешние воркеры,
    им terminate), все TTS-движки, все LLM у Ollama/LM Studio, CUDA-кэш.
    Сама Сайка (сервер, веб-UI, память, диалог) остаётся работать — после
    разгрузки нужное подгружается по порядку руками или лениво при первой
    фразе. Спасение, когда ОЗУ/VRAM забиты и непонятно кем."""
    def _do():
        freed, failed = [], []
        for n in list(stt.instances):
            try:
                stt.unload_engine(n)
                freed.append("слух:" + n)
            except Exception as e:
                failed.append(f"слух:{n} ({e})")
        for n in list(tts.engines):
            try:
                tts.unload_engine(n)
                freed.append("голос:" + n)
            except Exception as e:
                failed.append(f"голос:{n} ({e})")
        try:
            # пустая «оставляемая» пара не совпадёт ни с чем -> выгрузит все
            for b, m in llm.unload_others("", ""):
                failed.append(f"LLM:{b}/{m}")
            freed.append("LLM: все локальные")
        except Exception as e:
            failed.append(f"LLM ({e})")
        try:
            import gc
            gc.collect()
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                freed.append("CUDA-кэш")
        except Exception:
            pass
        # состояние «ничего не выбрано»: иначе первая же фраза/озвучка лениво
        # подгружает модели обратно, и разгрузка выглядит неработающей
        try:
            stt.set_engine("none")
            CFG.set("tts.enabled", False)
            freed.append("слух и озвучка выключены до ручного выбора")
        except Exception:
            pass
        msg = "🧹 Жёсткая разгрузка: выгрузила " + ", ".join(freed or ["ничего"])
        if failed:
            msg += ". НЕ поддались: " + ", ".join(failed) + \
                   " — их добивай через диспетчер задач"
        msg += ". Сама я работаю; подгружай нужное по порядку — кликом " \
               "по движку или кнопкой ⬇."
        log.info("panic_unload: freed=%s failed=%s", freed, failed)
        broadcast_event({"type": "baymax", "mood": "meh", "text": msg})
    await asyncio.get_event_loop().run_in_executor(None, _do)
    return {"ok": True}


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
            # потом прогреет новую. UI следит через /api/models.
            def _do_switch(_backend=backend, _model=value):
                r = llm.switch_model(_backend, _model)
                # раньше провал выгрузки старой модели (частый случай — LM
                # Studio без свежего REST API /models/unload) терялся молча:
                # владелец видел «кликнул на модель — старая всё ещё в
                # памяти» без единого объяснения (жалоба 2026-07-23)
                if r.get("unload_failed"):
                    names = ", ".join(f"{b}/{n}" for b, n in
                                      r["unload_failed"])
                    broadcast_event({
                        "type": "baymax", "mood": "meh",
                        "text": (f"⚠ переключилась на {_model}, но не смогла "
                                "выгрузить из памяти: " + names +
                                " (у LM Studio для этого нужна свежая версия "
                                "с REST API /models/unload — обнови "
                                "приложение или выгрузи вручную кнопкой ⏏)")})
                if not r.get("ok"):
                    broadcast_event({
                        "type": "baymax", "mood": "bad",
                        "text": f"⚠ {_backend}/{_model} не прогрелась — "
                                "смотри logs/saika.log"})
            threading.Thread(target=_do_switch, daemon=True).start()
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
    HISTORY_ANCHOR["ts"] = 0.0   # новый диалог — новый якорь окна истории
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
        self._streams = {}   # "primary"/"dup" -> (sd.OutputStream, sr, device)

    @staticmethod
    def _resolve_device(name):
        """Имя устройства (подстрока, как в браузерном списке) -> индекс
        sounddevice. Так пользователю не нужно знать числовые ID — те же
        человеческие имена, что и в попапе озвучки браузера (CABLE Input,
        WH-1000XM4 и т.п.). Не нашли — отдаём строку как есть, sounddevice
        попробует сам; пусто/None — системное устройство по умолчанию."""
        if not name:
            return None
        try:
            import sounddevice as sd
            needle = str(name).strip().lower()
            for idx, d in enumerate(sd.query_devices()):
                if d.get("max_output_channels", 0) > 0 \
                        and needle in d.get("name", "").lower():
                    return idx
        except Exception:
            pass
        return name

    def _get_stream(self, key: str, device_cfg_key: str, sr: int):
        device = self._resolve_device(CFG.get(device_cfg_key) or None)
        cur = self._streams.get(key)
        if cur is not None and cur[1] == sr and cur[2] == device:
            return cur[0]
        if cur is not None:
            try:
                cur[0].stop(); cur[0].close()
            except Exception:
                pass
        import sounddevice as sd
        stream = sd.OutputStream(samplerate=sr, channels=1, dtype="float32",
                                 device=device)
        stream.start()
        self._streams[key] = (stream, sr, device)
        return stream

    def play(self, pcm: bytes, sr: int):
        try:
            import numpy as np
            import sounddevice as sd  # noqa: F401 (проверка наличия пакета)
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
        vol = max(0.0, min(1.0, float(CFG.get("tts.server_volume", 0.8))))
        data = np.clip(np.frombuffer(pcm, dtype=np.float32) * vol, -1.0, 1.0)
        try:
            self._get_stream("primary", "tts.output_device", sr).write(data)
        except Exception as e:
            report_problem("tts", str(e),
                           "основной серверный вывод озвучки не сработал")
        # дубль — как в браузере: второе устройство одновременно (например,
        # CABLE Input для LipSync аватара, пока основное играет в наушники,
        # или наоборот). Пусто в конфиге -> дубль просто не создаётся.
        if CFG.get("tts.output_device_dup"):
            try:
                self._get_stream("dup", "tts.output_device_dup", sr).write(data)
            except Exception as e:
                report_problem("tts", str(e),
                               "дубль-вывод озвучки сервера не сработал")

    def close(self):
        for key, (stream, _sr, _dev) in list(self._streams.items()):
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self._streams.clear()


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
    # картинка без подписи шлёт user_text='' — не кладём пустую строку в
    # память НАВСЕГДА (см. подробности у сборки hist_msgs ниже, где та же
    # защита стоит и для уже отравленной старой истории)
    memory.add_event(person_id, "user",
                     user_text.strip() if user_text and user_text.strip()
                     else ("(картинка без подписи)" if image else "…"))

    DIALOG_STATE["active_since"] = time.time()
    DIALOG_STATE["first_token_ts"] = 0.0
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
    _tone_cls = None
    try:
        from server import tone as _tone
        _tone_cls = _tone.detect(user_text)
        _hint = _tone.behavior_hint(user_text)
        if _hint:
            dyn_parts.append(_hint)
    except Exception:
        pass
    # РЕАКЦИЯ АВАТАРА (VMagicMirror и т.п., server/avatar.py) — жест/эмоция
    # по той же метке тона, ДО генерации ответа, чтобы она была синхронна
    # с началом реплики, а не отставала. Выключено по умолчанию
    # (avatar.enabled=false в config.json), никак не зависит от LLM.
    try:
        avatar.react(user_text, _tone_cls)
    except Exception as e:
        log.debug("avatar.react пропущен: %s", e)
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
        elif not (user_text or "").strip():
            # 2026-07-23: картинка БЕЗ единого слова — раньше модель сама
            # решала, что с ней делать, и то молча анализировала (неуместно
            # для случайного/личного фото — «скинул картинку голого мужика»
            # это не запрос на разбор), то путалась. Живой человек в такой
            # ситуации сначала спросит «а это что и зачем», а не выдаёт
            # непрошеный разбор. Как только пользователь поясняет (тем же
            # сообщением или следующей репликой — живой контекст донесёт
            # картинку дальше, см. pending_meta в handle_text) — дальше
            # работает обычная ветка ниже, отвечает по сути.
            dyn_parts.append(
                "### Пользователь прислал КАРТИНКУ БЕЗ единого слова пояснения "
                "— просто кинул файл. НЕ начинай сама разбирать, описывать "
                "или оценивать её содержимое незвано. Спроси коротко и в "
                "своём характере (можно с сухой иронией), что это и зачем "
                "прислал — как обычный человек, которому молча кинули файл. "
                "Если дальше поясняет или просит что-то конкретное (описать, "
                "поправить, распознать) — тогда отвечай по сути, картинка "
                "остаётся с тобой.")
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
    # 2026-07-23: живой инцидент — «Попробуй загуглить, кто такая овсянка»
    # (инфинитив «загуглить», а не только повелительное «загугли») не ловился
    # старым \bзагугли\b, и модель (openai/gpt-oss-20b, тогда ещё НЕ в
    # tools_broken) вместо поиска сама ПРИДУМАЛА факты — включая выдуманное
    # «уволила создателя» вместо реального мема. Хуже молчания: уверенная
    # дезинформация. Расширила глаголы до основ (\w*), и завела вторую
    # защиту ниже — если модель имела право звать инструмент, но НЕ позвала
    # его на явную просьбу поискать, в следующий раз для неё поиск тоже
    # берёт на себя сервер (llm.search_unreliable), а не её добросовестность.
    _search_intent = bool(re.search(
        r"\b(найди|загугл\w*|погугл\w*|поищ\w*|глянь в (инете|сети)|"
        r"что нового в мире)\b", user_text, re.I))
    _no_tools = False
    try:
        if _search_intent:
            _cur_model = CFG.get("llm.model", "")
            _no_tools = (_cur_model in set(CFG.get("llm.tools_broken", []))
                         or _cur_model in set(CFG.get("llm.search_unreliable", []))
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
                "- ГЛАВНОЕ ПРАВИЛО: инструменты — редкое исключение, а не "
                "привычка. Обычный разговор, приветствия, болтовня, реакции, "
                "мнения, шутки, вопросы О ТЕБЕ САМОЙ — отвечай СЛОВАМИ, БЕЗ "
                "единого вызова. «Привет», «как дела», «что делаешь» — это "
                "болтовня, НЕ повод лезть в интернет.\n"
                "- web_search бери ТОЛЬКО когда нужен ВНЕШНИЙ факт, которого "
                "ты знать не можешь (свежие события, цены, погода, "
                "незнакомый термин/человек) ИЛИ когда прямо просят "
                "(«загугли», «глянь», «поищи»). Сомневаешься, нужен ли "
                "поиск — значит НЕ нужен, отвечай словами.\n"
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
    # ЯКОРЬ ИСТОРИИ (2026-07-23, борьба за <1с до первого токена).
    # Раньше: recent_raw(limit=N) — СКОЛЬЗЯЩЕЕ окно. Как только диалог
    # длиннее N, каждый ход выкидывает самое старое сообщение, префикс
    # промпта меняется прямо после system — LM Studio/llama.cpp пере-
    # prefill'ит ВСЁ (~7к токенов ≈ 2.5с на gemma-e4b, это и была
    # «думала 3-4с» на 9-токенных ответах). Теперь окно прибито ЯКОРЕМ:
    # состав истории только ДОПОЛНЯЕТСЯ с хвоста => префикс стабилен,
    # prefill догоняет лишь новые сообщения. Когда бюджет переполняется,
    # якорь одним прыжком уезжает вперёд (оставляем ~60% бюджета) — одна
    # полная пережёвка раз в десятки ходов вместо каждой фразы.
    _anchor_ts = max(DIALOG_CUTOFF["ts"], HISTORY_ANCHOR["ts"])
    history_ts = memory.recent_raw(limit=300, since_ts=_anchor_ts,
                                   with_ts=True)
    history = [(r, t) for _ts, r, t in history_ts]
    # Умный бюджет контекста: модель валит запрос, если система+история+
    # СХЕМЫ ИНСТРУМЕНТОВ не влезают в окно. Режем историю с хвоста (свежие
    # важнее — старое уехало в память-эпизоды). ВАЖНО (2026-07-23): кириллица
    # у Qwen токенизируется ~вдвое плотнее английского, а раньше считали
    # оптимистично ~3.5 симв/ток — промпт с инструментами вылетал за окно
    # 16384 на первых же репликах. Теперь: (1) бюджет в символах = n_ctx *
    # консервативный симв/ток, (2) из него вычитаем и систему, И размер
    # тул-схем (их досыпает шаблон, раньше в бюджете не учитывались — главный
    # промах), И запас под ответ.
    n_ctx = int((CFG.get("locallm_gguf") or {}).get("n_ctx", 8192))
    CHARS_PER_TOKEN = 1.5                      # воркер всё равно подрежет точно; тут просто ориентир
    ANSWER_RESERVE_TOKENS = 1500               # место под сам ответ
    budget = int((n_ctx - ANSWER_RESERVE_TOKENS) * CHARS_PER_TOKEN)
    cfg_budget = CFG.get("llm.context_chars")  # ручной потолок, если задан
    if cfg_budget:
        budget = min(budget, int(cfg_budget))
    # ОБЛАКО: бюджет истории считался от окна ЛОКАЛЬНОГО движка (32k → ~47к
    # символов) — и вся эта простыня улетала в API на каждую фразу. У облака
    # нет нашего тёплого KV-кэша: провайдер пережёвывает промпт целиком,
    # kimi-k3 на 30к символов давал prefill 16-25с. Режем до вменяемого
    # (llm.cloud.context_chars, дефолт 9000 ≈ 6к токенов) — длинную память
    # всё равно держит RAG, а не хвост чата.
    if CFG.get("llm.backend") == "cloud":
        budget = min(budget, int(CFG.get("llm.cloud.context_chars", 9000)))
    # размер схем инструментов (шаблон впишет их в промпт помимо system)
    tools_chars = 0
    try:
        if CFG.get("llm.model") not in set(CFG.get("llm.tools_broken", [])):
            from server.llm import tools as _hp
            import json as _json
            tools_chars = len(_json.dumps(_hp.schemas(), ensure_ascii=False))
    except Exception:
        pass
    # паспорт модели: если пробы выяснили молчаливое переполнение окна —
    # ужимаем до замеренного рабочего бюджета
    try:
        from server.llm import passport as _passport
        _pc = _passport.context_chars_for(CFG.get("llm.model", ""))
        if _pc and _pc < budget:
            budget = _pc
    except Exception:
        pass
    hist_budget = max(1500, budget - len(system) - tools_chars)
    total_chars = sum(len(t) for _, t in history)
    if total_chars <= hist_budget:
        trimmed = history          # влезает целиком — префикс не трогаем
    else:
        # переполнение: двигаем якорь вперёд ОДНИМ прыжком (оставляем ~60%
        # бюджета) — следующая пере-prefill'ка случится нескоро, а не
        # каждый ход, как при скользящем окне
        keep, used = [], 0
        for ts, r, t in reversed(history_ts):
            if used + len(t) > hist_budget * 0.6 and keep:
                break
            keep.append((ts, r, t))
            used += len(t)
        keep.reverse()
        HISTORY_ANCHOR["ts"] = keep[0][0] - 1e-6
        trimmed = [(r, t) for _ts, r, t in keep]
        log.info("Контекст: якорь истории сдвинут, %s -> %s сообщений "
                 "(бюджет %s символов) — одна полная пережёвка промпта",
                 len(history), len(trimmed), hist_budget)
    messages = [{"role": "system", "content": system}]
    # 2026-07-23: реальный инцидент — картинка БЕЗ подписи хранилась в
    # памяти пустой строкой ('' от WS, когда user_text не заполнен). Часть
    # облачных API (Moonshot/Kimi) отвергают ЛЮБОЕ сообщение с пустым
    # content, включая СТАРЫЕ реплики из истории — и это лупилось на КАЖДОМ
    # ходу («message at position N must not be empty»), Kimi отваливалась
    # НАВСЕГДА (пока история не уедет за анкер), а Сайка тихо отвечала
    # мелкой локальной моделью, ничего не объясняя. Заплатка на пустое
    # content — здесь, в САМОЙ ТОЧКЕ сборки истории: чинит и старые уже
    # отравленные записи в этом диалоге, не только новые.
    hist_msgs = [{"role": r, "content": (t or "").strip() or "…"}
                for r, t in trimmed]
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
            sentence = _strip_markdown(sentence)   # см. коммент у функции
            if not sentence:
                continue
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
                        avatar.on_audio_chunk(AUDIO_LEVEL["level"])
                    except Exception:
                        pass
                    out.put({"type": "audio_meta", "sr": sr})
                    out.put(pcm_bytes)
            except Exception as e:
                report_problem("tts", str(e), "продолжаю без озвучки")

    tts_thread = threading.Thread(target=tts_worker, daemon=True)
    tts_thread.start()

    def speak(sentence):
        # текстовые жест-маркеры исполняем здесь: через speak() проходят ВСЕ
        # реплики (стрим, повтор без инструментов, финальный хвост) — жест
        # гарантированно сработает даже у модели без tool-calls
        sentence = _apply_gesture_marks(sentence)
        if sentence:
            # вопрос -> наклон головы у веб-аватара (co-speech, 2026-07-25)
            if sentence.rstrip().endswith("?"):
                try:
                    avatar.question_cue()
                except Exception:
                    pass
            tts_q.put(sentence)

    used_llm = {}

    try:
        def on_fallback(backend, model, reason=None):
            why = (str(reason)[:220] + "") if reason else "недоступен"
            report_problem("llm", f"основной бэкенд не ответил: {why}",
                           f"переключилась на {backend}/{model}")

        def on_model(backend, model):
            # кто РЕАЛЬНО отвечает (после фолбэков) — для чипа модели в UI
            used_llm["backend"], used_llm["model"] = backend, model
            ACTIVE_LLM["backend"], ACTIVE_LLM["model"] = backend, model

        _tool_used = {"any": False}

        def on_tool(name, args):
            _tool_used["any"] = True
            out.put({"type": "tool", "name": name,
                     "args": json.dumps(args, ensure_ascii=False)[:200]})

        from server.llm.guard import LoopGuard, RECOVERY_PROMPT
        guard = LoopGuard(
            hard_tokens=int(CFG.get("llm.max_tokens_hard", 4000)),
            max_seconds=int(CFG.get("llm.max_gen_seconds", 180)))
        looped = None

        # ЖИВОЙ СТАТУС ПРИ ДОЛГОМ МОЛЧАНИИ (2026-07-23). Инцидент: workshop_create
        # с большой SVG-картинкой у Kimi встал колом на генерации первого токена
        # — 4 минуты пользователь видел только «⏳ отвечу следом» (это про ОЧЕРЕДЬ
        # фраз, не про зависание) и решил, что Беймакс спит. LoopGuard свою
        # работу СДЕЛАЛ (оборвал ровно на 180с), но до этого — тишина. Пока не
        # пришёл первый токен, короткий фоновый таймер сам подаёт признаки
        # жизни: сначала мягко («ещё думаю»), потом честно предупреждает про
        # скорый обрыв — вместо голой тишины на грани иллюзии зависшего сервера.
        _first_tok_evt = threading.Event()

        def _slow_watch():
            if _first_tok_evt.wait(timeout=14):
                return
            out.put({"type": "thinking", "text": "ещё думаю…"})
            if _first_tok_evt.wait(timeout=150):
                return
            out.put({"type": "thinking",
                     "text": "думаю непривычно долго — если не отвечу в "
                             "ближайшие секунды, оборву сама и приду в себя"})
        threading.Thread(target=_slow_watch, daemon=True).start()

        t_req = time.monotonic()  # промпт собран, уходим в LLM
        for token in llm.chat_stream(messages, on_fallback=on_fallback,
                                     on_tool=on_tool, image=image,
                                     on_model=on_model,
                                     should_stop=stop_event.is_set):
            if stop_event.is_set():
                break
            if t_first is None:
                t_first = time.monotonic()
                DIALOG_STATE["first_token_ts"] = time.time()
                _first_tok_evt.set()
            n_tokens += 1
            full_reply.append(token)
            sentence_buf += token
            # НЕ шлём в UI куски псевдо-вызова: кривые модели (12b-qat)
            # печатают <|tool_call|>call:close_browser{} текстом. Как только
            # в буфере появился зачин такого — прекращаем стримить наружу,
            # хвост дособерём и обработаем после цикла.
            if "<|" in sentence_buf or "call:" in sentence_buf \
                    or re.search(r'\{\s*"name"\s*:', sentence_buf) \
                    or re.search(r'\bto=[a-z_]+', sentence_buf) \
                    or re.search(r'\b(?:commentary|analysis|final)\s+'
                                r'[a-z_]{3,}\b', sentence_buf, re.I):
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
        _first_tok_evt.set()  # стрим завершён (даже без токенов) — будить некого
        log.info("LLM стрим завершён: %d токенов, прерван stop_event=%s",
                 n_tokens, stop_event.is_set())
        # ПОЙМАЛИ модель на слове: явно просили поискать, сервер сам поиск
        # НЕ подсовывал (модель формально «умеет» инструменты), а она вместо
        # вызова web_search придумала ответ из головы. В следующий раз для
        # неё поиск берёт на себя сервер — как для настоящих tools_broken.
        if (_search_intent and not _no_tools and not _tool_used["any"]
                and not stop_event.is_set()):
            _bad_model = used_llm.get("model") or CFG.get("llm.model", "")
            _unreliable = set(CFG.get("llm.search_unreliable", []))
            if _bad_model and _bad_model not in _unreliable:
                _unreliable.add(_bad_model)
                CFG.set("llm.search_unreliable", sorted(_unreliable))
                log.warning("Модель %s не позвала поиск на явную просьбу "
                           "(«%s») — похоже, ответила из головы вместо "
                           "поиска. В следующий раз поиск за неё сделает "
                           "сервер.", _bad_model, user_text[:80])

        # Псевдо-вызовы текстом от кривых моделей: <|tool_call|>call:NAME{...},
        # голый JSON {"name":"NAME"}, или Harmony-формат gpt-oss — модель шлёт
        # спецтокены <|channel|>commentary to=functions.web_search<|message|>
        # {...}, LM Studio их прячет, а голый текст между ними («commentary
        # to=web_search json{"query":...}») утекает как обычный ответ —
        # 2026-07-23: openai/gpt-oss-20b именно так «ответил» пользователю
        # сырым текстом инструмента вместо результата поиска.
        # Вырезаем из ответа (в чат/память такое не попадает), а безопасные
        # намерения ИСПОЛНЯЕМ по-настоящему: close_browser — закрыть окно;
        # web_search/web_research/open_page/fetch_page — реальный вызов +
        # короткая суммаризация словами; shutdown — только пометка.
        # жест-маркеры уже исполнены в speak() — из текста для чата/памяти
        # просто вырезаем (fire=False, чтобы не отыграть жест дважды)
        _raw = _apply_gesture_marks("".join(full_reply), fire=False)
        # Harmony (gpt-oss): «commentary to=web_search json{...}». Имя ловим
        # ЛЕНИВО ([a-z_]+?), иначе приклеенный «json» без пробела съедается
        # в имя («to=web_searchjson{» давало несуществующий инструмент
        # web_searchjson — 2026-07-23, вызов молча не исполнялся).
        # между именем и JSON бывают «json», спецтокены <|constrain|>,
        # <|message|> в любых сочетаниях — пропускаем их все.
        # 2026-07-23 (второй заход): та же модель выдала «commentary
        # devboard_read{"board":"Anamorf"}» — БЕЗ «to=» вообще, только канал
        # (commentary/analysis/final) + голое имя + JSON. Старый regex это
        # пропускал целиком (утекло в чат сырым текстом). Вторая ветка
        # альтернации ловит именно такой канал-без-to= вариант.
        _harmony_m = re.search(
            r'(?:to=(?:functions\.)?'
            r'|\b(?:commentary|analysis|final)\s+(?:functions\.)?)'
            r'([a-z_]+?)(?:json)?\s*'
            r'(?:(?:<\|[^|>]*\|>|json)\s*)*(\{.*)',
            _raw, re.I | re.S)
        _has_pseudo = ("<|" in _raw or "call:" in _raw
                       or re.search(r'\{\s*"name"\s*:', _raw)
                       or re.search(r'\bto=[a-z_]+', _raw)
                       or _harmony_m)
        if _has_pseudo:
            # сырьё в лог: если экстрактор снова что-то не поймёт (новый
            # формат очередной модели) — будет видно, ЧТО именно пришло
            log.info("Псевдо-вызов сырьём: %r", _raw[:400])
            _names = re.findall(r'(?:call:|"name"\s*:\s*")([a-z_]+)',
                                _raw, re.I)
            _harmony_args = None
            if _harmony_m:
                _names.append(_harmony_m.group(1).lower())
                # достаём JSON-объект по балансу скобок — regex `.*` жадно
                # хватает лишнее, а нам нужен ровно один объект
                _tail = _harmony_m.group(2)
                depth, end = 0, None
                for i, ch in enumerate(_tail):
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                if end:
                    try:
                        _harmony_args = json.loads(_tail[:end])
                    except Exception:
                        _harmony_args = None
            clean = re.sub(r'<\|[^>]*\|>', '', _raw)
            clean = re.sub(r'call:[a-z_]+\s*(\{[^}]*\})?', '', clean, flags=re.I)
            clean = re.sub(r'\{\s*"name"\s*:.*?\}', '', clean, flags=re.S)
            if _harmony_m:
                # позиции _harmony_m посчитаны по _raw ДО подстановок выше —
                # переиспользовать их как офсеты в уже изменённом clean
                # опасно (могут разъехаться, если сработал ещё и другой
                # паттерн). Ищем по факту в clean заново и режем максимум
                # один раз.
                _fresh = re.search(
                    r'(?:to=(?:functions\.)?'
                    r'|\b(?:commentary|analysis|final)\s+(?:functions\.)?)'
                    r'[a-z_]+?(?:json)?\s*'
                    r'(?:(?:<\|[^|>]*\|>|json)\s*)*\{.*',
                    clean, re.I | re.S)
                if _fresh:
                    clean = clean[:_fresh.start()] + clean[_fresh.end():]
                # огрызки Harmony-каналов («commentary», «analysis») —
                # не текст ответа, в чат/озвучку не пускаем
                clean = re.sub(r'^\s*(?:assistant|commentary|analysis|'
                               r'final)\b[:\s]*', '', clean, flags=re.I)
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
            elif any(n in _names for n in
                    ("web_search", "web_research", "open_page", "fetch_page")):
                _tool_name = next(n for n in _names if n in
                                  ("web_search", "web_research",
                                   "open_page", "fetch_page"))
                try:
                    from server.llm import tools as _handspc
                    _result = _handspc.call(_tool_name, _harmony_args or {})
                    _result = (_result or "")[:2500]
                    if _result and "отказ:" not in _result[:20]:
                        _summary = llm.chat_once([
                            {"role": "system", "content":
                             "Ты голосовой ассистент. Дай короткий "
                             "устный ответ (1-3 фразы) по результату "
                             "поиска ниже — без markdown, без ссылок "
                             "списком, как будто рассказываешь другу."},
                            {"role": "user", "content":
                             f"Результат поиска:\n{_result}"}],
                            max_len=600).strip()
                        if _summary:
                            clean = _summary
                            acted = f"{_tool_name} исполнен по-настоящему"
                except Exception as e:
                    log.info("Досчитать псевдо-%s не вышло: %s",
                            _tool_name, e)
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
                        DIALOG_STATE["first_token_ts"] = time.time()
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
    # чистим markdown ПЕРЕД записью в память: она же потом уходит в history
    # следующих ходов (recent_raw) — если хранить сырьё с **жирным**, модель
    # видит собственные нарушения правила как «нормальный» пример и множит
    # их дальше. Живой UI уже получил токены как есть (стрим не переиграть),
    # это только для будущего контекста.
    reply = _strip_markdown("".join(full_reply).strip())
    if reply:
        # прервали на полуслове (живой контекст — юзер докинул) -> помечаем,
        # чтобы на следующем заходе она видела, что не договорила
        if stop_event.is_set() and n_tokens > 0:
            reply += " …(прервана — собеседник добавил уточнение)"
        memory.add_event(person_id, "assistant", reply)
    # МОЛЧАНИЕ — НЕ ОТВЕТ: если наружу не ушло ни слова и нас не перебивали,
    # объясняем в чате, почему (раньше причина тонула в логе, а в UI
    # выглядело так, будто Сайка просто проигнорировала фразу)
    if not reply and not stop_event.is_set():
        try:
            why = _diagnose_silence(
                used_llm.get("backend") or CFG.get("llm.backend", ""),
                used_llm.get("model") or CFG.get("llm.model", ""),
                n_tokens)
        except Exception as e:
            why = f"причину выяснить не удалось ({e})"
        log.warning("Молчание вместо ответа: %s", why)
        out.put({"type": "noreply", "text": "Не смогла ответить: " + why})
        # Беймакс не спит: событие уходит в общий канал проблем (пузырь +
        # дев-доска), но не чаще раза в 2 минуты — молчание может сыпаться
        # подряд, а долбёжка сама по себе проблема
        now_ts = time.time()
        if now_ts - _SILENCE_REPORTED["ts"] > 120:
            _SILENCE_REPORTED["ts"] = now_ts
            report_problem("llm.silence",
                           "модель промолчала: " + why[:180],
                           "объяснила в чате; если есть ключ Kimi — зову "
                           "облачный консилиум")
            # умная облачная починка: сильная модель читает лог и советует
            try:
                from server import ai_consult
                ai_consult.consult_async(
                    f"модель {used_llm.get('model') or CFG.get('llm.model')} "
                    f"не выдала ответ ({n_tokens} токенов наружу). "
                    f"Диагноз кода: {why}", broadcast_event)
            except Exception as e:
                log.debug("consult: %s", e)
    DIALOG_STATE["active_since"] = 0.0
    DIALOG_STATE["first_token_ts"] = 0.0
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
            # живой контекст интересен только когда генерация УЖЕ что-то
            # говорит — тогда есть что подхватывать. Если она ещё не выдала
            # ни одного токена (холодный старт модели, долгий prefill,
            # разбухший от предыдущих доливок промпт) — прерывать бессмысленно
            # и вредно: 2026-07-23 ровно так модель ни разу не успела
            # ответить за 3+ минуты — каждая новая (нетерпеливая) реплика
            # юзера рестартовала генерацию за долю секунды до первого
            # токена, и счётчик обнулялся до бесконечности («0 токенов,
            # прерван stop_event=True» по кругу). Даём генерации грейс-период
            # на выдачу первого токена; если он уже прошёл — считаем её
            # зависшей и тоже не мешаем ждать (перезапуск всё равно не
            # ускорит уже идущий prefill/загрузку модели).
            started = DIALOG_STATE.get("active_since", 0.0)
            has_output = DIALOG_STATE.get("first_token_ts", 0.0) > 0
            gen_age = (time.time() - started) if started else 0.0
            grace = CFG.get("dialog.live_context_grace_s", 6)
            if CFG.get("dialog.live_context", True) and (has_output or gen_age < grace):
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
                if CFG.get("dialog.live_context", True):
                    log.info("handle_text: генерация ещё без единого токена "
                             "дольше %sс (холодный старт/завал) — коплю %r "
                             "молча, НЕ прерываю", grace, user_text[:40])
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
                    # PDF-чертежи (эвакуационные планы и т.п.): клиент шлёт
                    # сырой base64 PDF, тут рендерим первую страницу в PNG и
                    # дальше пускаем по обычному пути image (vision-модель
                    # видит её как обычную прикреплённую картинку).
                    _img = data.get("image")
                    _pdf = data.get("pdf")
                    if _pdf and not _img:
                        try:
                            from server import pdf_hands
                            _img, _pmeta = pdf_hands.to_image_data_url(_pdf)
                            if _pmeta.get("pages", 1) > 1:
                                out.put({"type": "tool", "name": "pdf",
                                        "args": (f"стр. 1 из {_pmeta['pages']}"
                                                 " (остальные страницы пока "
                                                 "не смотрю)")})
                        except Exception as e:
                            report_problem("pdf", str(e),
                                           "отвечаю без чертежа")
                            _img = None
                    handle_text(data["text"], heard_ts=time.monotonic(),
                                image=_img)
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

    # слух/голос: базовый порядок — выбранный движок + fallback_order, но
    # РУЧНАЯ оценка владельца (палочки в UI) поднимает движок выше: sort
    # стабильный, поэтому не оценённые вручную остаются в прежнем порядке
    # (решение владельца 2026-07-23 — «неважно ллм или ттс или стт»).
    #
    # БЫСТРЫЙ СТАРТ (2026-07-23, цель владельца: первый голосовой обмен
    # через 10-20с): слух, голос и мозги грузятся ПАРАЛЛЕЛЬНО (раньше —
    # цепочкой, и 60-секундная компиляция qwen3-TTS держала всё остальное).
    # Голос — с времянкой: лёгкий silero/edge встаёт за секунды и отвечает,
    # пока тяжёлый qwen3 компилируется в фоне; как догрелся — подхватывается
    # на лету (tts.boot_override, конфиг не трогаем).
    _manual = ratings.manual_scores()

    def _boot_stt():
        stt_chain = [CFG.get("stt.engine", "gigaam")]
        for n in CFG.get("stt.fallback_order", []):
            if n not in stt_chain:
                stt_chain.append(n)
        stt_chain.sort(key=lambda n: -_manual.get(n, 0))
        _try_chain("stt", stt_chain, stt.load_engine)

    def _boot_tts():
        tts_chain = [CFG.get("tts.engine", "qwen3")]
        for n in CFG.get("tts.fallback_order", []):
            if n not in tts_chain:
                tts_chain.append(n)
        tts_chain.sort(key=lambda n: -_manual.get(n, 0))
        # времянка: лучший движок тяжёлый (не из FAST) — поднимаем лёгкий
        # и назначаем текущим, пока тяжёлый греется
        FAST_TTS = ("silero", "edge")
        best = tts_chain[0] if tts_chain else None
        if best and best not in FAST_TTS:
            fast = next((n for n in tts_chain if n in FAST_TTS), None)
            if fast:
                try:
                    tts.load_engine(fast)
                    tts.boot_override = fast
                    log.info("Автопуск: голос-времянка %s (пока %s греется)",
                             fast, best)
                except Exception as e:
                    log.info("Голос-времянка %s не поднялась: %s", fast, e)
        _try_chain("tts", tts_chain, tts.load_engine)
        tts.boot_override = None  # тяжёлый готов (или фолбэк) — времянку прочь
        # разовый бенч незамеренных запасных голосов — чтобы выбор «по
        # рейтингу» опирался на реальные замеры этого ПК
        try:
            tts.benchmark_missing()
        except Exception as e:
            log.info("Бенч голосов пропущен: %s", e)

    threads = [threading.Thread(target=f, daemon=True, name=f.__name__)
               for f in (_boot_stt, _boot_tts)]
    for t in threads:
        t.start()
    # мозги грузим в ЭТОМ потоке параллельно слуху/голосу — код ниже

    # мозги: ПО РЕЙТИНГУ, лучшая — первая (решение владельца 2026-07-23:
    # «модель, которая по рейтингу выше всего, должна быть самой первой на
    # автоматическую загрузку»). Рейтинг = ручная оценка владельца (палочки
    # в UI, синхронизируются через /api/ratings/manual) — она ПЕРЕБИВАЕТ
    # авто-скоростную, ровно как в списке UI (effScore). Без ручной оценки —
    # авто-балл из замеров ток/с. Последний выбор из config — только
    # тайбрейк при равном рейтинге, очередь он больше не перепрыгивает.
    # ВАЖНО: "locallm" (свой llama.cpp/transformers движок) — полноправный
    # бэкенд наравне с ollama/lmstudio (был забыт тут, исправлено 2026-07-22).
    BACKENDS_AUTOSTART = ("ollama", "lmstudio", "locallm")
    try:
        tps = ratings.llm_tps()
        manual = ratings.manual_scores()
        cands = [(m["backend"], m["name"]) for m in llm.list_models()
                 if m["backend"] in BACKENDS_AUTOSTART
                 and "embed" not in m["name"].lower()]
        cfg_pick = (CFG.get("llm.backend", "ollama"), CFG.get("llm.model", ""))

        def _eff(name):  # та же семантика, что effScore в ui/index.html
            return manual.get(name, ratings.score_of(tps.get(name, 0)))

        cands.sort(key=lambda c: (-_eff(c[1]), -tps.get(c[1], 0),
                                  0 if c == cfg_pick else 1))
        for backend, model in cands:
            try:
                if not llm.switch_model(backend, model)["ok"]:
                    raise RuntimeError("прогрев не удался")
                CFG.set("llm.backend", backend)
                CFG.set("llm.model", model)
                log.info("Автопуск: мозги — %s/%s (%.1f ток/с в рейтинге)",
                         backend, model, tps.get(model, 0))
                # прогрев KV-кэша боевой персоной в фоне: первый реальный
                # ответ докатывает только хвост промпта, а не все ~7КБ
                try:
                    from server.persona import SAIKA_SYSTEM
                    threading.Thread(
                        target=llm.prewarm_context,
                        args=(backend, model, SAIKA_SYSTEM),
                        daemon=True).start()
                except Exception:
                    pass
                break
            except Exception as e:
                report_problem("llm", f"{model}: {e}",
                               "автопуск пробует следующую модель")
    except Exception as e:
        report_problem("llm", str(e), "автопуск мозгов не удался")
    for t in threads:  # дождаться слух/голос (сам автопуск — фоновый поток)
        t.join(timeout=600)


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
    # поднять сохранённые клавиатурные хоткеи — ТОЛЬКО если владелец включил
    # hotkeys.enabled (по умолчанию выкл: модель дважды вешала опасные бинды)
    if CFG.get("hotkeys.enabled", False):
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
    # Аватар (VMagicMirror и т.п.) машет и сбрасывает позу один раз при
    # старте сервера — небольшая задержка, чтобы дать программе-аватару
    # время быть уже открытой (если сама Sайка стартует раньше неё —
    # хоткей просто никуда не попадёт, это не страшно).
    def _avatar_startup_wave():
        time.sleep(3)
        avatar.on_startup()
    threading.Thread(target=_avatar_startup_wave, daemon=True).start()
    # ИИ-Беймакс на старте (2026-07-23): не ждём серии падений — через минуту
    # после запуска сам осматривает систему (отчёт доктора + логи) и, если
    # видит проблемы, зовёт LLM (текущие мозги, в т.ч. облачные вроде Kimi)
    # и чинит по белому списку. Прогресс — пузырями Беймакса в чат.
    if CFG.get("doctor.startup_ai", True):
        def _startup_ai_doctor():
            time.sleep(CFG.get("doctor.startup_ai_delay_s", 60))
            try:
                from setup import ai_doctor
                ai_doctor.run(auto=True, on_event=lambda t: broadcast_event(
                    {"type": "baymax", "mood": "meh",
                     "text": "🩺 " + str(t)[:500]}))
            except Exception as e:
                log.debug("startup ai_doctor: %s", e)
        threading.Thread(target=_startup_ai_doctor, daemon=True).start()
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
        # не плодим вкладки (2026-07-20, доработано 2026-07-23): старая
        # вкладка после рестарта переподключается за ~1-2с, видит новый
        # BOOT_ID и делает location.reload() — на пару секунд подключений
        # снова НОЛЬ, хотя вкладка жива. Разовый снимок ровно на 3-й секунде
        # попадал в это окно и открывал дубль (реальные лишние вкладки
        # 2026-07-23). Теперь наблюдаем 8 секунд с шагом 0.25с и ЗАЩЁЛКОЙ:
        # вкладка хоть раз объявилась — значит, она есть, дубль не открываем
        # никогда; за все 8с никого — вкладки правда нет, открываем.
        def _open_if_no_tab():
            for _ in range(32):  # 32 × 0.25с = 8с
                if EVENT_CLIENTS:
                    log.info("Вкладка уже открыта (переподключилась) — "
                             "новую не открываю")
                    return
                time.sleep(0.25)
            webbrowser.open(f"http://{host}:{port}")

        threading.Thread(target=_open_if_no_tab, daemon=True).start()
    log.info("Сайка запускается на http://%s:%s", host, port)
    # отметка «стек поднялся»: doctor.py --fast видит свежую метку и
    # пропускает полный осмотр (полный — после падения или раз в сутки)
    try:
        (ROOT / "logs" / "boot_ok.json").write_text(
            json.dumps({"ts": time.time()}), encoding="utf-8")
    except Exception:
        pass
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
