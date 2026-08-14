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
from fastapi import (FastAPI, File, Request, UploadFile, WebSocket,
                     WebSocketDisconnect, HTTPException)
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
from server import hearing
from server import voiceprint
from server.denoise import DENOISE
from server.draft import DRAFT
from server.earlog import EARLOG
from server.transcript import TRANSCRIPT, mood_of
from server.guard import GUARD
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


# ─────────────── ОХРАНА НА ВХОДЕ, КОГДА СЕРВЕР СМОТРИТ НАРУЖУ ───────────────
# 2026-07-26. Пока Сайка слушала только 127.0.0.1, вопрос доступа не стоял:
# достучаться могла лишь эта же машина. Как только владелец открывает её для
# телефона, всё меняется — у неё теперь руки в системе (запуск программ,
# окна, файлы), и любой в той же Wi-Fi получил бы их вместе с ней. Гость,
# сосед через слабый пароль роутера, чужой ноутбук.
#
# Правило простое: с самого компьютера — как раньше, без единого вопроса.
# Снаружи — только с токеном. Токен приезжает в ссылке из QR (?t=…), браузер
# телефона запоминает его сам и дальше шлёт заголовком.
@app.middleware("http")
async def _guard(request, call_next):
    from server import phone as _ph
    if not _ph.is_open():
        return await call_next(request)
    client = (request.client.hostname if hasattr(request.client, "hostname")
              else None) or (request.client.host if request.client else "")
    if client in ("127.0.0.1", "::1", "localhost"):
        return await call_next(request)
    path = request.url.path
    want = _ph.token()
    # КУДА СМОТРИМ ЗА ТОКЕНОМ И ПОЧЕМУ ИМЕННО ТАК (2026-07-26).
    # Заголовок ставит наш же JS. Параметр ?t= приезжает из QR. А cookie —
    # единственное, что работает для ВЛОЖЕННЫХ запросов, которые браузер
    # делает сам: <iframe src="/avatar">, картинки, шрифты, вебсокет. Их мы
    # не контролируем, заголовок туда не подложить. Живой случай: телефон
    # открылся, чат работал, а вкладка «Аватар» показывала голый JSON с
    # ошибкой — iframe уходил на сервер без единого признака доступа.
    got = (request.headers.get("x-saika-token")
           or request.query_params.get("t")
           or request.cookies.get("saika_token") or "")
    ok = bool(want) and got == want
    # ЗАКРЕПЛЯЕМ ДО ПРОВЕРКИ ПУТИ, а не после (иначе ссылка из QR ведёт на
    # «/», а он разрешён всем — короткое замыкание срабатывало раньше, чем
    # ставилась cookie, и телефон оставался без пропуска. Поймано живым
    # тестом: Set-Cookie не приходил вообще).
    set_ck = (ok and request.query_params.get("t") == want
              and request.cookies.get("saika_token") != want)
    # Саму страницу отдаём всегда: иначе телефону негде было бы ввести код,
    # если QR не сработал. Опасное — за токеном.
    free = (path == "/" or path.startswith("/static")
            or path.startswith("/ui")
            or path.endswith((".css", ".js", ".png", ".svg", ".ico",
                              ".woff2")))
    if not (ok or free):
        return JSONResponse(
            {"error": "нужен код доступа",
             "hint": "открой Сайку на компьютере → Подключение с телефона и "
                     "отсканируй QR заново"}, status_code=401)
    resp = await call_next(request)
    if set_ck:
        resp.set_cookie("saika_token", want, max_age=90 * 24 * 3600,
                        httponly=True, samesite="lax", path="/")
    return resp

PROBLEMS: list[dict] = []          # лента проблем/починок для UI
ACTIVE_LLM = {"backend": "", "model": ""}  # кто реально отвечал последним
# Жёсткая разгрузка была, и с тех пор владелец ничего не поднимал. Пока
# флаг стоит, внутренние импульсы молчат — они будят LLM, а «выгрузить всё»
# значит выгрузить ВСЁ. Снимается голосом/текстом владельца или загрузкой
# модели: любое из этого — явное «живём дальше».
HARD_UNLOADED = {"on": False}
CTX_WARN = {"sent": False}   # «окно мало» — Беймаксу, один раз за запуск
EVENT_CLIENTS: set = set()          # активные websockets
DIALOG_CUTOFF = {"ts": 0.0}         # «новый диалог»: контекст только после отметки
HISTORY_ANCHOR = {"ts": 0.0}        # якорь окна истории: стабильный префикс промпта => живой KV-кэш
_SILENCE_REPORTED = {"ts": 0.0}     # троттлинг жалоб на молчание модели
DIALOG_STATE = {"active_since": 0.0, "first_token_ts": 0.0}   # идёт ли сейчас ответ + успела ли выдать первый токен (для импульсов и живого контекста)

# СКОЛЬКО РАЗ ПОДРЯД МОДЕЛЬ ПРОМОЛЧАЛА С ИНСТРУМЕНТАМИ (2026-07-26).
# Инцидент: gemma-4-e4b-it на КАЖДУЮ фразу отдавала 0 токенов, срабатывал
# аварийный повтор без инструментов — и человек ждал ДВА запроса вместо
# одного. Хуже того, у этих двух запросов разный промпт (во втором нет
# tools и добавлено служебное сообщение), поэтому они вышибали KV-кэш друг
# друга: каждый ход шёл полный prefill дважды. В логе это выглядело как
# «LLM prefill 4700мс» и читалось как «модель медленная», хотя в LM Studio
# та же модель отвечает за десятые доли секунды.
# Чиним как и остальные причуды — учимся на лету: две пустышки подряд и
# модель уезжает в llm.tools_broken, дальше инструменты ей не даём вообще.
_TOOLS_EMPTY: dict = {}
_TOOLS_EMPTY_LIMIT = 2

# Последний замер задержки — чтобы панель «Скорость» показывала эффект
# правок сразу, а не «покрути и послушай ощущения».
LAST_TIMING: dict = {}
# САМОНАБЛЮДЕНИЕ (2026-07-28, просьба владельца). На вопрос «с какой
# скоростью ты отвечаешь?» она честно отвечала «не могу измерить» — хотя
# сервер меряет КАЖДЫЙ её ответ до миллисекунды и рисует это в интерфейсе.
# Числа под сообщением видел человек, но не она сама. Храним последние
# замеры и подкладываем ей фактом, когда разговор заходит о её скорости.
LAST_STATS: dict = {}    # tokens/tps/latency_ms/model последнего ответа
LAST_STT: dict = {}      # engine/stt_ms последнего распознавания
# Промпт предыдущего хода целиком — чтобы измерить, какая его доля СОВПАЛА с
# нынешним. Именно эта доля и берётся из KV-кэша, всё остальное модель жуёт
# заново. Раньше в лог писался хэш «стабильной части» (messages[:-3]), но она
# растёт с каждым ходом на два сообщения, поэтому хэш менялся ВСЕГДА — и
# ничего не сообщал. Длина общего префикса отвечает на вопрос прямо.
LAST_PROMPT = {"text": ""}
HEAR_DROP = {"n": 0}     # сколько чанков уронили, потому что слух не успевал

# СЧЁТЧИКИ СЛУХА (2026-07-28). Жалоба «пропускает слова между строк» не
# лечится глядением в экран: пропасть слово может в четырёх разных местах, и
# все они выглядят одинаково — тишина в чате.
#   1. чанк уронила очередь (движок не успевает);
#   2. VAD не увидел речи вовсе — порог выше голоса (шумодав придавил или
#      шумовой пол уполз вверх);
#   3. сегмент был, но движок вернул пустоту;
#   4. движок вернул текст, а фильтр галлюцинаций его выбросил.
# Каждый случай лечится по-своему и ни один не виден снаружи. Поэтому
# считаем всё и показываем числа: одна строка вместо часа догадок.
HEAR_STAT = {"chunks": 0, "dropped": 0, "segments": 0, "empty": 0,
             "quiet": 0, "rms": 0.0, "thr": 0.0, "q": 0,
             # ПИК ЗА ОКНО, а не мгновенный уровень (2026-07-29, живой
             # разбор: панель показывала «уровень 1 / порог 12» и кричала
             # «тише порога», хотя распознавание в ту же секунду отлично
             # писало текст. Мгновенное значение берётся с последнего чанка
             # — а человек между фразами МОЛЧИТ, и это норма. Смотреть надо
             # на пик за несколько секунд: он честно отвечает на вопрос
             # «доходит ли сюда голос вообще».
             "peak": 0.0, "peak_ts": 0.0,
             "den_ms": 0.0, "cut_ms": 0.0, "stt_ms": 0.0, "lag": 0}
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
    # no-store обязателен (2026-07-26). Адрес у модели ОДИН и тот же, а файл
    # за ним теперь меняется — библиотека аватаров переключает его на лету.
    # Без этого заголовка браузер отдавал закэшированный VRM, и человек
    # выбирал модель за моделью, а на экране оставалась прежняя.
    return FileResponse(p, media_type="model/gltf-binary",
                        headers={"Cache-Control": "no-store"})


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
        # «loaded» (2026-07-28): какие модели РЕАЛЬНО лежат в памяти. Нужен
        # интерфейсу, чтобы индикаторы честно гасли после «Выгрузить всё из
        # памяти»: раньше точка мозгов горела зелёным просто потому, что
        # бэкенд отвечает по сети, — а моделей в памяти уже не было.
        # Список кэшируется на 5с внутри менеджера (см. LATENCY.md), роут
        # синхронный и живёт в пуле потоков, событийный цикл не держит.
        "llm": {"backends": llm.backend_status(),
                "loaded": llm.loaded_models(),
                "active": ACTIVE_LLM,
                "backend": CFG.get("llm.backend"),
                "model": CFG.get("llm.model"),
                "off": bool(CFG.get("llm.off", False)),
                "think": bool(CFG.get("llm.think", False))},
        "stt": stt.status(),
        # числа слуха: где именно теряются слова (см. HEAR_STAT)
        "hear": dict(HEAR_STAT),
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
    _ms = llm.list_models()
    # РЕЙТИНГ УМА — ИЗ ЛЕСТНИЦЫ, А НЕ ИЗ ЗАМЕРА СКОРОСТИ (2026-08-14).
    # Владелец: «какого хрена у меня не работает рейтинг и не загружаются
    # самые первые по рейтингу». Лестница (server/llm/brains.py) со своей
    # таблицей ума существовала с прошлой недели — но её спрашивали ТОЛЬКО
    # при эскалации. Список в интерфейсе и автопуск сортировались по
    # ток/с, и четырёхмиллиардная gemma честно обгоняла llama-70b: она и
    # правда быстрее. Быстрее — не умнее.
    try:
        from server.llm import brains as _b
        from server.llm import skills as _sk
        for m in _ms:
            m["rank"] = _b.rank_of(m.get("name", ""), m.get("backend", ""))
            m["recent"] = _b.recent_pos(m.get("backend", ""),
                                        m.get("name", ""))
            # ЧТО ОНА УМЕЕТ, А НЕ ТОЛЬКО НАСКОЛЬКО УМНАЯ (2026-08-14).
            # Одно число «ум 8» не говорит, видит ли она картинки и можно
            # ли доверить ей руки. Карточка отвечает на оба вопроса.
            try:
                _c = _sk.card(m.get("name", ""), m.get("backend", ""))
                m["desc"], m["tags"] = _c["desc"], _c["tags"]
                m["skills"] = _c["skills"]
            except Exception:
                pass
    except Exception as e:
        log.debug("ранги моделей не собрались: %s", e)
    return {"models": _ms, "loaded": llm.loaded_models(),
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
    import concurrent.futures
    import socket

    def probe(host, port=443):
        t = time.monotonic()
        try:
            socket.create_connection((host, port), timeout=3).close()
            return round((time.monotonic() - t) * 1000)
        except OSError:
            return None

    # НЕ ОДИН ПРОБНИК, А НЕСКОЛЬКО (2026-08-15). Раньше вся «сеть» висела
    # на 1.1.1.1: у российских провайдеров он режется постоянно — и Сайка
    # рисовала «нет сети» человеку, который в ту же секунду спокойно сидел
    # на huggingface без всякого VPN. Онлайн — это «дозвонились хоть до
    # кого-то»; пинг показываем лучший из ответивших, а мимо кого не прошли
    # — не повод объявлять отсутствие интернета.
    hosts = ("1.1.1.1", "8.8.8.8", "huggingface.co", "ya.ru")
    pings = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for host, ms in zip(hosts, pool.map(probe, hosts)):
            pings[host] = ms
    alive = [v for v in pings.values() if v is not None]
    ping = min(alive) if alive else None
    hf = pings.get("huggingface.co") is not None
    out = {"online": bool(alive), "ping_ms": ping, "hf": hf,
           # кто именно не ответил — чтобы «нет сети» можно было проверить,
           # а не гадать (видно в подсказке индикатора)
           "probes": {k: v for k, v in pings.items()}}
    # ПОЛИТИКА СЕТИ (2026-08-15): часть адресов на этом ПК ходит через
    # обходчик DPI. Без этого знания любой отвал YouTube/Discord Сайка
    # объясняла «нет интернета» и предлагала чинить не то.
    try:
        from server import netpolicy
        out["bypass"] = netpolicy.state()
        out["diagnosis"] = netpolicy.explain(out["probes"])
    except Exception as e:
        log.debug("политика сети пропущена: %s", e)
    return out


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
# 2026-07-28: + avatar_action. Модель подсматривает ИМЯ ИНСТРУМЕНТА из схем
# и пишет [avatar_action:good] вместо [жест:good] — а этот вариант в регекс
# не входил, маркер утекал в чат и В ОЗВУЧКУ («аватар экшен гуд» вслух).
# Вчерашняя правка того же жила локально на рабочем ПК и потерялась при
# reset к origin/dev — поэтому чинится здесь, в ветке, а не на машине.
_GESTURE_MARK_RE = re.compile(
    r'[\[({]\s*(?:жест|эмоция|gesture|emote|avatar[_ ]?action|аватар)'
    r'\s*[:=\-]?\s*([a-zа-яё0-9_]+)\s*[\])}]', re.I)
# ОБОРВАННЫЙ маркер (генерация кончилась на «[жест:good» без скобки,
# 2026-07-25 — озвучка честно читала «жест гуд» вслух). Вырезаем хвост,
# жест из него по возможности исполняем.
_GESTURE_TAIL_RE = re.compile(
    r'[\[({]\s*(?:жест|эмоция|gesture|emote|avatar[_ ]?action|аватар)'
    r'\s*[:=\-]?\s*([a-zа-яё0-9_]*)\s*$', re.I)


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


# ── ТЕКСТОВЫЙ ПРОТОКОЛ ИНСТРУМЕНТОВ (2026-07-28) ──
# Наблюдение из живого диалога: научившись жестам-маркерам [жест:good],
# модель ЛОГИЧНО обобщила протокол на инструменты — писала [open_folder:.] и
# [find_folder:query="..."] текстом. Сервер понимал только жестовые маркеры,
# и её команды честно улетали в пустоту: она «выполняла», человек видел
# «не получилось» четыре раза подряд. Раз мелкая модель сама выбрала этот
# синтаксис — принимаем его как протокол: имя проверяется по реальному
# списку инструментов, действие исполняется через штатный tools.call (все
# предохранители — намерение, доверие, анти-амок — работают), результат
# человек видит сразу (⚡ в чате), а она сама — фактом в следующем ходе.
_TOOL_MARK_RE = re.compile(
    r'[\[({]\s*([a-z][a-z0-9_]{2,})\s*[:=]?\s*([^\])}]*)[\])}]')

# ДИАЛЕКТ ВЫЗОВА — ОДИН НА ДВА ПУТИ (2026-08-13). Раньше «прощение диалекта»
# жило внутри _run_tool_marks, а _strip_tool_marks резала озвучку сырой
# _TOOL_MARK_RE. Из-за этого «[вызываю close_browser]» ОДНОВРЕМЕННО не
# исполнялся (имя не латинское сразу после скобки) и не вырезался — то есть
# действие не происходило, а маркер зачитывался вслух. Теперь нормализация
# общая: что исполняем, то и вырезаем.
_CALL_PREFIX_RE = re.compile(
    r'([\[({])\s*(?:вызыв\w*|вызов\w*|вызв\w*|зову|зова\w*|'
    r'запуска\w*|запущ\w*|использу\w*|дёрга\w*|дерга\w*|'
    r'инструмент\w*|команда|tool[_\s-]?calls?|tool[_\s-]?use|'
    r'function[_\s-]?call|tool|call|calling|invoke|using)'
    r'\s*[:=]?\s*', re.I)

# ОБОРВАННЫЙ ВЫЗОВ (2026-08-13, живой чат: «[tool_callПохоже, ты прислал
# мне какой-то служебный текст…» — gemma открыла скобку, передумала и
# продолжила обычным текстом. Скобка не закрылась, _TOOL_MARK_RE такое не
# ловит, и служебное слово уехало в чат И В ОЗВУЧКУ).
_BROKEN_CALL_RE = re.compile(
    # \b здесь НЕ годится: между латинской «l» и кириллической «П» границы
    # слова нет — для Python обе буквы словесные, и «[tool_callПохоже» не
    # ловилось. Смотрим на смену алфавита явно.
    r'[\[({]\s*(?:tool[_\s-]?calls?|tool[_\s-]?use|function[_\s-]?call|'
    r'вызов|вызываю)(?![a-zA-Z_])[^\])}]{0,20}?(?=[А-ЯЁ])', re.I)


def _norm_call_dialect(text: str) -> str:
    return _CALL_PREFIX_RE.sub(r'\1', text or "")


# СЦЕНИЧЕСКИЕ РЕМАРКИ (2026-08-13, живой вечер: «[Я не могу заставить тебя
# увидеть что-то, что не видишь ты сама]», «[Я не могу воспроизвести аудио,
# поэтому это не проблема, а просто уточнение моей технической границы]» —
# и всё это ПРОИЗНОСИЛОСЬ вслух). Это не маркер инструмента, а мысли вслух
# в квадратных скобках: модель поясняет сама себе, зачем делает то, что
# делает. Человеку они не нужны ни в чате, ни тем более в озвучке.
_STAGE_RE = re.compile(
    r'\[\s*(?:Я|Мне|Мной|Моя|Мой|Моё|Это|Здесь|Тут|Note|I)\b[^\]]{15,400}\]',
    re.I)


# РАЗМЫШЛЕНИЕ ВСЛУХ (2026-08-14, живой лог: на «Не получилось» модель выдала
# 284 токена «Задача: … Контекст: … Мой характер: … План действий: 1… 2… 3…
# Выбранный ответ:», и всё это ушло человеку в чат и в озвучку. Дальше было
# 333, 417 и 532 токена того же). Это не характер и не ответ — это её
# черновик. Причина моя: я надобавлял ей блоков-регламентов, и мелкая
# модель начала им ПОДРАЖАТЬ вместо того, чтобы им следовать.
#
# Режем по маркерам черновика. Если после выреза остаётся осмысленный
# хвост — отдаём его; если черновиком была вся реплика, ответа нет, и
# честнее показать это, чем читать вслух её мысли.
_THINK_HEAD = re.compile(
    r'^\s*(?:\[?(?:thought|thinking|scratchpad|reasoning)\]?\s*:?\s*'
    r'|(?:задача|анализ|контекст|план(?:\s+ответа|\s+действий)?|'
    r'разбор|размышлени\w*|интерпретация|стратегия|вывод|'
    r'the user (?:said|is|wants)|analyz\w+|plan|step \d)\b[^\n]{0,120}:)',
    re.I)
_THINK_LINE = re.compile(
    r'^\s*(?:\*\*)?(?:\d+[.)]\s*)?(?:\*\*)?'
    r'(?:задача|анализ\w*|контекст|мой характер|моя персона|правило|'
    r'план(?:\s+\w+)?|выбранный ответ|действие|корректировка|вывод|'
    r'execution|self-?correction|refinement|strategy|goal|reasoning|'
    r'analyze the request|context check|previous failure|'
    r'my persona|my character)\b[^\n]{0,200}$',
    re.I | re.M)


def _strip_thinking(text: str) -> str:
    """Вырезать черновик модели, оставив собственно ответ."""
    t = text or ""
    if not t.strip():
        return t
    # весь текст начинается с маркера черновика — ищем, где он кончился:
    # черновик обычно заканчивается пустой строкой перед живой репликой
    if _THINK_HEAD.match(t) or _THINK_LINE.search(t):
        lines = t.split("\n")
        keep = [ln for ln in lines
                if not _THINK_LINE.match(ln) and not _THINK_HEAD.match(ln)]
        # выкидываем и нумерованные пункты плана, и строки со «звёздочками»
        keep = [ln for ln in keep
                if not re.match(r'^\s*(?:\*\s*)?\d+[.)]\s+\S', ln)
                and not re.match(r'^\s*\*+\s*\S.{0,160}\*+\s*$', ln)]
        out = "\n".join(keep).strip()
        # черновик бывает одним абзацем без переносов — тогда режем по
        # последнему маркеру и берём хвост
        if not out and len(t) > 200:
            parts = re.split(r'(?:вывод|итог|ответ|execution)\s*:', t,
                             flags=re.I)
            out = parts[-1].strip() if len(parts) > 1 else ""
        if out != t:
            log.info("Вырезала черновик модели: %d -> %d символов",
                     len(t), len(out))
        return out
    return t


def _strip_stage(text: str) -> str:
    out = _STAGE_RE.sub("", text or "")
    # после выреза остаётся осиротевшая точка: «показываю. . Вижу» —
    # в озвучке это лишняя пауза на ровном месте
    out = re.sub(r'([.!?…])\s*[.,;]+', r'\1', out)
    return re.sub(r'\s{2,}', ' ', out).strip()


def _strip_broken_call(text: str) -> str:
    """Убрать оборванную скобку вызова, за которой пошёл обычный текст."""
    return _BROKEN_CALL_RE.sub("", text or "")

# результат исполненных маркеров — для следующего хода (см. run_dialog)
PENDING_ACTIONS: list = []


def _marker_args(name: str, raw: str, schemas: list) -> dict:
    """'query="ноль", drive="E"' -> {"query": "ноль", "drive": "E"};
    голое значение ('.') уходит первым параметром схемы.

    ДИАЛЕКТЫ (2026-07-29, живой промах: gemma написала {name:Google Chrome}
    — фигурные скобки и двоеточие вместо кавычек и «=». Разбор выдал кашу
    «{name:Google Chrome» ПРЯМО В ЗАПРОС, и поиск программы искал программу
    с фигурной скобкой в имени). Мелкая модель пишет как привыкла в JSON —
    принимаем и это: скобки срезаем, «:» равносилен «=»."""
    raw = (raw or "").strip().strip("{}").strip()
    if not raw:
        return {}
    pairs = re.findall(
        r"([a-zа-яё_]\w*)\s*[=:]\s*(?:\"([^\"]*)\"|'([^']*)'"
        r"|((?:(?!\s+[a-zа-яё_]\w*\s*[=:])[^,\])}])+))",
        raw, re.I)
    if pairs:
        return {k: (a or b or c).strip() for k, a, b, c in pairs}
    val = raw.strip('"\'')
    for sc in schemas:
        f = sc.get("function", {})
        if f.get("name") == name:
            props = list((f.get("parameters", {}) or {})
                         .get("properties", {}) or {})
            if props:
                return {props[0]: val}
    return {"query": val}


def _args_from_last_user(name: str, schemas: list) -> dict:
    """Маркер пришёл без аргументов — подставить последнюю фразу человека в
    первый обязательный параметр. Работает только для инструментов, которым
    нужен ОДИН текстовый параметр (поиск, исследование, открыть) — там это
    ровно то, что человек и просил. Для всего остального пусто: лучше
    честный отказ, чем действие с выдуманным аргументом."""
    try:
        from server.llm import tools as _tls
        txt = (_tls.LAST_USER.get("text") or "").strip()
    except Exception:
        txt = ""
    if not txt:
        return {}
    for sc in schemas:
        f = sc.get("function", {})
        if f.get("name") != name:
            continue
        params = (f.get("parameters") or {})
        props = params.get("properties") or {}
        req = params.get("required") or list(props)[:1]
        if len(req) != 1:
            return {}
        key = req[0]
        if (props.get(key, {}) or {}).get("type", "string") != "string":
            return {}
        return {key: txt}
    return {}


def _run_tool_marks(text: str, skip: set | None = None) -> list:
    """Найти в готовом ответе текстовые вызовы, исполнить, вернуть
    [(имя, результат)]. Не больше двух за ответ — остальное пусть просит
    следующим ходом, это защита от простыни команд. skip — инструменты,
    уже вызванные в этом же ходе по-настоящему (их маркеры — дубли)."""
    if "[" not in (text or "") and "(" not in (text or ""):
        return []
    # ПРОЩАЕМ ДИАЛЕКТ (2026-07-29, живой вечер: gemma писала
    # [вызов:window_place] — слово «вызов» она взяла из наших же карточек
    # («вызов текстом: [...]») и склеила внутрь скобок. Сервер ждал латинское
    # имя сразу после скобки, маркеры честно улетали в никуда, а она
    # рапортовала «готово». Человек ждал впустую четыре раза подряд.
    # Синтаксис, который модель выбирает сама, дешевле принять, чем
    # переучивать: срезаем служебные префиксы перед именем инструмента.
    # 2026-08-13, живой вечер: та же болезнь, новая форма — gemma писала
    # «[вызываю web_research]» и «[вызываю close_browser]». «вызываю» не
    # совпадало ни с «вызов», ни с «вызвать», префикс не срезался, а
    # _TOOL_MARK_RE требует ЛАТИНСКОЕ имя сразу после скобки — маркер не
    # матчился вообще и умирал молча. Человек трижды повторил «браузер до
    # сих пор торчит». Поэтому теперь ловим не слова целиком, а КОРНИ.
    text = _norm_call_dialect(text)
    # диалект «[tool_code] web_open ... [/tool_code]» (gemma, живой вечер):
    # имя инструмента СНАРУЖИ скобок — заворачиваем в нормальный маркер
    text = re.sub(r'\[(?:tool_code|code|функция)\]\s*([a-z][a-z0-9_]{2,})'
                  r'\s*(.*?)\s*\[/(?:tool_code|code|функция)\]',
                  r'[\1:\2]', text, flags=re.I | re.S)
    from server.llm import tools as _tls
    try:
        schemas = _tls.schemas()
        known = {sc.get("function", {}).get("name") for sc in schemas}
    except Exception:
        return []
    done = []
    for m in _TOOL_MARK_RE.finditer(text):
        name = m.group(1)
        if name not in known:
            # ПОХОЖЕ НА ИНСТРУМЕНТ, НО ЕГО НЕТ (2026-07-29, живой чат:
            # gemma звала fs_mkdir, которого мелкой модели не выдали, —
            # маркер молча пропускался, и она трижды рапортовала «папка
            # создана» человеку в глаза. Молчание сервера = её враньё.
            # Теперь несуществующий/недоступный инструмент получает честный
            # ответ, который она увидит фактом в следующий ход).
            if re.match(r"^(fs_|window_|app_|screen_|web_|key_|keyboard_|"
                        r"tab_|volume_|model_|anim_|open_|find_|minimize_|"
                        r"remember_)", name):
                done.append((name, "такого инструмента у тебя сейчас НЕТ — "
                                   "действие НЕ выполнено. Не говори, что "
                                   "сделала. Скажи человеку честно, что "
                                   "инструмент недоступен."))
                if len(done) >= 2:
                    break
            continue                       # [прим:...] и прочее — не команда
        if skip and name in skip:
            continue                       # уже вызван по-настоящему — дубль
        try:
            args = _marker_args(name, m.group(2), schemas)
            # МАРКЕР БЕЗ АРГУМЕНТОВ (2026-08-13): «[вызываю web_research]» —
            # имя есть, запроса нет. Инструмент честно отвечал «пустой
            # запрос», но человек видел только голый маркер и тишину. Тему
            # берём из последней фразы человека — она и есть то, что он
            # просил найти.
            if not args:
                args = _args_from_last_user(name, schemas)
            res = _tls.call(name, args)
            log.info("Текст-вызов %s(%s) -> %s", name, args, str(res)[:100])
            done.append((name, str(res or "сделано")[:300]))
        except Exception as e:
            done.append((name, f"не вышло: {e}"))
        if len(done) >= 2:
            break
    return done


def _strip_tool_marks(text: str) -> str:
    """Вырезать текстовые вызовы из озвучки/истории — читать вслух
    'опен фолдер путь точка' не нужно, действие и так исполнено."""
    def _sub(m):
        # вырезаем только НАСТОЯЩИЕ имена инструментов — латиница со снейком;
        # [прим: ...] и кириллица остаются текстом
        return " "
    return re.sub(r'[ 	]{2,}', ' ',
                  _TOOL_MARK_RE.sub(_sub, _strip_thinking(_strip_stage(_strip_broken_call(
                      _norm_call_dialect(text)))))).strip()


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


_GPU_PROC_CACHE = {"ts": 0.0, "procs": []}


def _gpu_procs_windows():
    """Память GPU по процессам через счётчики Windows (WDDM прячет её от
    nvidia-smi). Один вызов PowerShell — сотни миллисекунд, поэтому кэш:
    панель системы обновляется чаще, чем меняется расклад по памяти."""
    if os.name != "nt":
        return []
    now = time.time()
    if now - _GPU_PROC_CACHE["ts"] < 15:
        return _GPU_PROC_CACHE["procs"]


    _GPU_PROC_CACHE["ts"] = now
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage')."
             "CounterSamples | Where-Object {$_.CookedValue -gt 50MB} | "
             "ForEach-Object { $_.InstanceName + '|' + "
             "[int64]$_.CookedValue }"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        agg = {}
        for line in r.stdout.strip().splitlines():
            if "|" not in line:
                continue
            inst, val = line.rsplit("|", 1)
            m = re.search(r"pid_(\d+)", inst)
            if not m:
                continue
            v = int(val)
            # мусор счётчиков (2026-07-29, живой пример: «iriunwebcam —
            # 5696.9 ГБ»): битые сэмплы больше всей VRAM на порядок.
            # Отбрасываем всё крупнее 64 ГБ — таких карт у людей нет.
            if v > 64 * 2 ** 30:
                continue
            agg[int(m.group(1))] = agg.get(int(m.group(1)), 0) + v
        me = os.getpid()
        procs = []
        try:
            import psutil
        except Exception:
            psutil = None
        for pid, b in agg.items():
            base = ""
            if psutil is not None:
                try:
                    base = psutil.Process(pid).name().lower()
                except Exception:
                    base = ""
            if "llama-server" in base:
                who = "мозги · llama.cpp"
            elif "ollama" in base:
                who = "мозги · ollama"
            elif "lm" in base and "studio" in base:
                who = "мозги · LM Studio"
            elif base.startswith("python") and pid == me:
                who = "Сайка · слух и голоса"
            elif base.startswith("python"):
                who = f"python · {pid}"
            elif any(x in base for x in ("chrome", "msedge", "firefox")):
                who = "браузер (интерфейс, аватар)"
            elif "dwm" in base:
                who = "Windows · рабочий стол"
            else:
                who = base.replace(".exe", "") or f"pid {pid}"
            procs.append({"who": who, "mb": int(b / 2**20)})
        # одинаковые имена складываем: у хрома десяток процессов
        by = {}
        for x in procs:
            by[x["who"]] = by.get(x["who"], 0) + x["mb"]
        procs = [{"who": k, "mb": v} for k, v in by.items()]
        procs.sort(key=lambda x: -x["mb"])
        _GPU_PROC_CACHE["procs"] = procs
    except Exception:
        pass
    return _GPU_PROC_CACHE["procs"]


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
        # КТО ИМЕННО ЕСТ VRAM (2026-07-28, вопрос владельца «почему столько
        # жрёт»). Одно число «11.2 ГБ» не отвечает на вопрос — отвечает
        # список по процессам: мозги отдельно, слух отдельно, браузер с
        # аватаром отдельно. nvidia-smi отдаёт это бесплатно.
        try:
            rp = subprocess.run(
                ["nvidia-smi", "--query-compute-apps="
                 "pid,process_name,used_memory",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=4,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            me = os.getpid()
            procs = []
            for line in rp.stdout.strip().splitlines():
                parts = [x.strip() for x in line.split(",")]
                if len(parts) < 3:
                    continue
                pid, pname, mb = parts[0], parts[1].lower(), parts[2]
                base = pname.rsplit("\\", 1)[-1]
                if "llama-server" in base:
                    who = "мозги · llama.cpp"
                elif "ollama" in base:
                    who = "мозги · ollama"
                elif "lm studio" in pname or "lmstudio" in pname:
                    who = "мозги · LM Studio"
                elif base.startswith("python") and str(me) == pid:
                    who = "Сайка · слух и голоса"
                elif base.startswith("python"):
                    who = "python · " + pid
                elif "chrome" in base or "msedge" in base or "firefox" in base:
                    who = "браузер (интерфейс, аватар)"
                else:
                    who = base.replace(".exe", "")
                try:
                    procs.append({"who": who, "mb": int(float(mb))})
                except Exception:
                    pass
            procs.sort(key=lambda x: -x["mb"])
            if not procs:
                # Windows в режиме WDDM часто не отдаёт память по процессам
                # через nvidia-smi — берём её из счётчиков производительности.
                # PowerShell дорогой (сотни мс), поэтому кэш на 15 секунд.
                procs = _gpu_procs_windows()
            info["gpu"]["procs"] = procs[:8]
        except Exception:
            pass
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


@app.post("/api/llm/off")
def llm_off(payload: dict):
    """Выключить/включить мозги. Модель из памяти не выгружается — она просто
    не зовётся; вернуть обратно можно тем же кликом, без прогрева."""
    CFG.set("llm.off", bool(payload.get("on")))
    broadcast_event({"type": "llm_off", "on": bool(CFG.get("llm.off"))})
    return {"ok": True, "off": bool(CFG.get("llm.off"))}


@app.post("/api/llm/model")
async def llm_model(payload: dict):
    """Ручная загрузка/выгрузка LLM-модели (кнопки ⬇/⏏ в списке моделей)."""
    name = payload.get("name")
    backend = payload.get("backend", "ollama")
    action = payload.get("action")
    try:
        if action == "load":
            HARD_UNLOADED["on"] = False   # явное «поднимай» от владельца
            ok = await asyncio.get_event_loop().run_in_executor(
                None, llm.warmup, backend, name)
        elif action == "unload":
            ok = await asyncio.get_event_loop().run_in_executor(
                None, llm.unload_model, backend, name)
        elif action == "delete":
            if backend == "cloud":
                # у облачной модели нет файла на диске — «удалить» значит
                # убрать из списка настроенных (ключ провайдера остаётся:
                # у одного провайдера моделей много)
                detail = llm.forget_cloud(name, payload.get("base_url"))
                log.info("Облачная модель убрана из списка: %s", name)
                return {"ok": True, "detail": detail}
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
    # в реестр — чтобы модель осталась в списке и после настройки следующей
    if payload.get("model"):
        llm.remember_cloud(CFG.get("llm.cloud.provider", ""),
                           CFG.get("llm.cloud.base_url", ""),
                           payload["model"])
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
        verify = True
        if base and key and llm._is_gigachat(base):
            # У Сбера ключ из кабинета — это НЕ Bearer-токен, а Basic-строка
            # для /oauth: сунуть её в /models = 401, и проверка врала, что
            # ключ плохой. Плюс сертификат подписан российским УЦ, которого
            # в Windows обычно нет — отсюда SSLCertVerificationError. Обмен
            # ключа на access-токен и решение про verify уже сделаны в
            # llm._gigachat_token, переиспользуем их.
            key = llm._gigachat_token(key)
            verify = llm._giga["verify"]
        if base and key:
            r = _rq.get(base + "/models",
                        headers={"Authorization": "Bearer " + key},
                        timeout=8, verify=verify)
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


# ------------------------- журнал слуха (час записи) ------------------------
# 2026-07-28. Включил — она час слушает комнату и потом отдаёт отчёт: сколько
# было голосов, как они звучат, какие были посторонние звуки. Сам звук не
# сохраняется, только числа (см. server/earlog.py).
@app.get("/api/earlog")
def earlog_status():
    return EARLOG.status()


@app.post("/api/earlog/start")
def earlog_start(payload: dict):
    return EARLOG.start(float(payload.get("minutes", 60)),
                        keep=bool(payload.get("keep", False)))


@app.post("/api/earlog/stop")
def earlog_stop():
    return EARLOG.stop()


@app.post("/api/earlog/report")
def earlog_report():
    r = EARLOG.report(reg=voiceprint.S.reg)
    return {"ok": True, "file": r["file"],
            "voices": len(r["voices"]), "sounds": len(r["sounds"])}


@app.post("/api/earlog/adopt")
def earlog_adopt(payload: dict):
    """Запомнить голос, найденный в отчёте, как знакомого — по номеру."""
    return EARLOG.adopt(int(payload.get("id", 0)), payload.get("name", ""),
                        voiceprint.S.reg)


@app.get("/earlog/{fname}")
def earlog_file(fname: str):
    # отчёт открывается ссылкой из интерфейса; имя чистим — путь наружу не даём
    safe = "".join(c for c in fname if c.isalnum() or c in "._-")
    p = ROOT / "data" / "earlog" / safe
    if not p.exists():
        raise HTTPException(status_code=404, detail="нет такого отчёта")
    return FileResponse(p, media_type="text/html; charset=utf-8")


# ---------------------------- шумодав ---------------------------------------
# 2026-07-28. Не галочка, а подсистема со сменными движками: см.
# server/denoise.py и стенд tools/denoise_bench.py. Ручки нарочно простые —
# выбрать движок, посмотреть выученный профиль шума, переучить его заново.
@app.get("/api/transcript")
def transcript_status():
    return TRANSCRIPT.status()


@app.post("/api/transcript/start")
def transcript_start():
    return TRANSCRIPT.start()


@app.post("/api/transcript/stop")
def transcript_stop():
    r = TRANSCRIPT.stop()
    try:
        return {**r, **TRANSCRIPT.save()}
    except Exception as e:
        return {**r, "ok": False, "error": str(e)}


@app.get("/transcript/{fname}")
def transcript_file(fname: str):
    p = (ROOT / "data" / "transcript" / fname).resolve()
    if not str(p).startswith(str((ROOT / "data" / "transcript").resolve())) \
            or not p.exists():
        return PlainTextResponse("нет такого файла", status_code=404)
    return FileResponse(str(p), media_type="text/markdown")


@app.get("/api/denoise")
def denoise_status():
    st = DENOISE.status()
    st["profile"] = DENOISE.profile()
    return st


@app.post("/api/denoise/set")
def denoise_set(payload: dict):
    if "engine" in payload:
        DENOISE.set_engine(str(payload["engine"]))
    for k in ("over", "floor", "gate_ratio", "gate_min", "min_bias",
              "gate_hold_ms"):
        if k in payload:
            CFG.set("denoise." + k, payload[k])
    st = DENOISE.status()
    st["profile"] = DENOISE.profile()
    return st


@app.post("/api/denoise/relearn")
def denoise_relearn():
    # Забыть выученный шум и слушать комнату заново. Нужно, когда обстановка
    # сменилась разом: включили вытяжку, приехали гости, переехали с наушников
    # на колонки. Сам профиль подстроится и без этого, но не мгновенно.
    st = DENOISE.relearn()
    st["profile"] = DENOISE.profile()
    return st


# ---------------------- отпечаток голоса (кто говорит) ----------------------
# 2026-07-28. Блок слуха научился отвечать не только «что сказано», но и
# «кем». Ручки нарочно простые: включить/выключить, записать голос, забыть,
# отдать облако точек для визуализации. Вся механика — в server/voiceprint.
@app.get("/api/voiceprint")
def voiceprint_status():
    return voiceprint.status()


@app.get("/api/voiceprint/points")
def voiceprint_points():
    """Всё накопленное облако в координатах ТЕКУЩЕЙ проекции. Интерфейс
    просит его при открытии окна и после каждого переобучения — координаты
    после переобучения другие, старые точки без пересчёта оказались бы в
    чужой системе координат."""
    return voiceprint.points()


@app.post("/api/voiceprint/set")
def voiceprint_set(payload: dict):
    if "enabled" in payload:
        voiceprint.set_enabled(bool(payload["enabled"]))
    # listen_self — слушает ли она саму себя. Выключается отдельно от всего
    # модуля: бывает нужно смотреть только на людей в комнате.
    if "listen_self" in payload:
        voiceprint.set_listen_self(bool(payload["listen_self"]))
    return voiceprint.status()


@app.post("/api/voiceprint/enroll")
def voiceprint_enroll(payload: dict):
    """action: start | stop | cancel. Запись эталона идёт из живой речи —
    человек просто говорит, модуль сам набирает нужное число векторов."""
    action = payload.get("action", "start")
    if action == "start":
        return voiceprint.enroll_start(payload.get("name", ""),
                                       int(payload.get("need", 24)))
    if action == "stop":
        return voiceprint.enroll_finish()
    if action in ("pause", "resume"):
        return voiceprint.enroll_pause(action == "pause")
    return voiceprint.enroll_cancel()


@app.post("/api/voiceprint/rename")
def voiceprint_rename(payload: dict):
    """Переименовать голос. По умолчанию имя ЗАКРЕПЛЯЕТСЯ: дальше она только
    учится его узнавать, но переименовать сама больше не может."""
    return voiceprint.rename(payload.get("old", ""), payload.get("new", ""),
                             pin=bool(payload.get("pin", True)))


@app.get("/api/guard")
def guard_status():
    """Защита железа: последние показания, пороги, диагноз прошлого
    выключения. Для товарища с гаснущим ПК — первое место, куда смотреть."""
    return GUARD.status()


@app.get("/api/room")
def room_state():
    """Сколько людей сейчас в комнате и какого они цвета. Лёгкий роут:
    интерфейс дёргает его часто, чтобы решать, как раскладывать диалог."""
    try:
        return voiceprint.room(float(CFG.get("voiceprint.room_window_s", 180)))
    except Exception as e:
        return {"people": [], "n": 0, "crowd": False, "error": str(e)[:120]}


@app.get("/api/hear")
def hear_stat():
    """Только счётчики слуха. Отдельным лёгким роутом, а не внутри
    /api/status: тот опрашивает бэкенды мозгов и во время подъёма
    llama-server отвечает не мгновенно, а эту строку панель дёргает часто."""
    out = dict(HEAR_STAT)
    # ПОЧЕМУ НЕ УЗНАЁТ ГОЛОС (2026-07-29). Числа слуха отвечали на вопрос
    # «слышу ли», но не на вопрос «почему не узнаю»: между ними стоит
    # проверка «это вообще голос?», и её вердикт нигде не был виден.
    # Теперь панель показывает последний отказ с баллом и разбором.
    try:
        from server import voiceprint as _vp
        st = _vp.S
        out["noise_seen"] = int(getattr(st, "noise_seen", 0))
        ln = getattr(st, "last_noise", None)
        if ln:
            out["noise_score"] = ln.get("score")
            out["noise_parts"] = ln.get("parts")
        out["speech_min"] = float(CFG.get("voiceprint.speech_min", 0.42))
        out["vp_on"] = bool(_vp.enabled())
        out["vp_heard_s"] = round(float(getattr(st, "heard_s", 0.0)), 1)
    except Exception as e:
        log.debug("статистика отпечатка не собралась: %s", e)
    return out


@app.post("/api/voiceprint/color")
def voiceprint_color(payload: dict):
    """Перекрасить голос. Золото не выдаётся: это цвет создателя."""
    return voiceprint.set_color(payload.get("name", ""),
                                payload.get("color", ""))


@app.post("/api/voiceprint/seal")
def voiceprint_seal(payload: dict):
    """«Твой голос, пупсик»: пометить голос создателем (золото, закреплён)
    и запечатать в проект — зашифрованный файл едет с репозиторием, ключ
    остаётся в secrets.json."""
    return voiceprint.seal_owner(payload.get("name", ""))


@app.post("/api/voiceprint/unseal")
def voiceprint_unseal():
    """Распечатать голос создателя из проекта — принудительно, поверх
    текущего состояния (2026-07-29). Нужна, когда список голосов почистили
    и создатель пропал: печать для того и делалась, чтобы вернуть его."""
    voiceprint.load_owner_seal(force=True)
    st = voiceprint.status()
    who = [n for n, v in (st.get("speakers") or {}).items() if v.get("owner")]
    return {"ok": bool(who), "owner": who[0] if who else "", **st}


@app.post("/api/voiceprint/enroll_file")
async def voiceprint_enroll_file(file: UploadFile = File(...),
                                 name: str = "", owner: bool = False):
    """Эталон из аудиофайла (диктофон телефона). owner=true — сразу пометить
    создателем и запечатать."""
    import tempfile
    suffix = Path(file.filename or "rec.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(await file.read())
        tmp = f.name
    try:
        r = await asyncio.get_event_loop().run_in_executor(
            None, voiceprint.enroll_file,
            (name or "Виталий").strip()[:32], tmp, bool(owner))
        return r
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


@app.post("/api/voiceprint/enroll_path")
def voiceprint_enroll_path(payload: dict):
    """Эталон из файла, уже лежащего НА ДИСКЕ этой машины (2026-07-28):
    владелец наговорил текст на диктофон, файл положили в voice/ — и одна
    команда строит эталон без возни с загрузкой через формы. Путь только
    внутри папки Сайки: этот роут — не читалка чужих дисков."""
    rel = str(payload.get("path", "")).strip()
    p = (ROOT / rel).resolve()
    if not str(p).startswith(str(ROOT.resolve())) or not p.exists():
        return {"ok": False, "error": f"нет файла {rel} внутри папки Сайки"}
    return voiceprint.enroll_file(
        (payload.get("name") or "Виталий").strip()[:32],
        str(p), bool(payload.get("owner")))


@app.post("/api/voiceprint/undo")
def voiceprint_undo():
    """Ctrl+Z для склейки голосов: вернуть как было."""
    return voiceprint.undo_merge()


@app.post("/api/voiceprint/merge")
def voiceprint_merge(payload: dict):
    """Слить два голоса в один: владелец перетащил плашку на плашку и тем
    самым сказал «это один и тот же человек». Его слово важнее порога."""
    return voiceprint.merge(payload.get("src", ""), payload.get("dst", ""))


@app.post("/api/voiceprint/forget")
def voiceprint_forget(payload: dict):
    return voiceprint.forget(payload.get("name", ""))


@app.post("/api/voiceprint/clear_map")
def voiceprint_clear_map():
    """Стереть накопленные облака с карты (эталоны голосов не трогаются)."""
    return voiceprint.clear_map()


@app.post("/api/voiceprint/refit")
def voiceprint_refit():
    voiceprint.refit()
    return voiceprint.status()


# ЗЕРКАЛО (2026-08-13). Кадр аватара живёт в браузере, сервер до канваса
# не дотягивается — поэтому просим интерфейс и ждём ответа на этом событии.
SELFIE = {"url": "", "err": "", "ev": threading.Event()}


@app.post("/api/avatar/selfie")
def avatar_selfie(payload: dict):
    SELFIE["url"] = str(payload.get("url") or "")
    SELFIE["err"] = str(payload.get("error") or "")
    SELFIE["ev"].set()
    return {"ok": True}


def take_selfie(timeout: float = 6.0):
    """Попросить интерфейс снять аватар. Возвращает data-url или None."""
    SELFIE["ev"].clear()
    SELFIE["url"] = SELFIE["err"] = ""
    broadcast_event({"type": "selfie_request"})
    if not SELFIE["ev"].wait(timeout):
        log.info("зеркало: интерфейс не ответил за %sс", timeout)
        return None
    if SELFIE["err"]:
        log.info("зеркало: %s", SELFIE["err"])
        return None
    return SELFIE["url"] or None


@app.get("/api/usage")
def usage_report(days: int = 7):
    """Сколько токенов сожжено и на что. Отдельно облако (деньги) и
    локальные (бесплатно, но показывает, где жуётся контекст)."""
    from server import usage as _u
    return _u.report(days)


@app.get("/api/avatar/desk")
def avatar_desk_get():
    """Состояние отдельного окна с моделью. Это же читает само окно —
    опрашивает раз в полсекунды, поэтому кнопка в интерфейсе доходит до
    уже запущенного окна без всякого IPC."""
    from server import desk_avatar as _da
    return _da.state()


@app.post("/api/avatar/desk")
def avatar_desk_set(payload: dict):
    """Три выключателя: on (открыть/закрыть), top (поверх всех),
    lock (замок движения). Панель аватара в интерфейсе не трогается."""
    from server import desk_avatar as _da
    return _da.apply(payload or {})


@app.get("/api/cards")
def cards_list():
    """Костюмы персонажей: что есть и что надето."""
    from server import cards as _c
    return {"cards": _c.list_cards(), "active": _c.active()}


@app.post("/api/cards/wear")
def cards_wear(payload: dict):
    from server import cards as _c
    cid = str((payload or {}).get("id", ""))
    return {"ok": True, "note": _c.off() if not cid else _c.wear(cid)}


@app.post("/api/cards/make")
def cards_make(payload: dict):
    """Сочинить карточку сильнейшим мозгом (может занять секунды)."""
    from server import cards as _c
    return {"note": _c.make(str((payload or {}).get("who", "")))}


@app.get("/api/voice/shape")
def voice_shape_get():
    """Темп и высота голоса — работают поверх ЛЮБОГО движка."""
    from server.tts import shape as _sh
    sp, semi = _sh.settings()
    return {"speed": sp, "pitch": semi}


@app.post("/api/voice/shape")
def voice_shape_set(payload: dict):
    p = payload or {}
    if "speed" in p:
        CFG.set("tts.speed", max(0.5, min(2.0, float(p["speed"]))))
    if "pitch" in p:
        CFG.set("tts.pitch", max(-8.0, min(8.0, float(p["pitch"]))))
    if "tone" in p:
        CFG.set("tts.tone", str(p["tone"] or ""))
    from server.tts import shape as _sh
    sp, semi = _sh.settings()
    return {"speed": sp, "pitch": semi, "tone": CFG.get("tts.tone", "")}


@app.get("/api/brains/providers")
def brains_providers():
    """Все известные провайдеры: кто подключён, кого можно подключить за
    минуту и где взять ключ. Пометки про VPN и карту — чтобы человек не
    узнавал о гео-блокировке на середине регистрации."""
    from server.llm import autoconnect as _ac
    return {"providers": _ac.status(), "suggest": _ac.missing()}


@app.post("/api/brains/connect")
def brains_connect():
    """Пересобрать парк по ключам, что есть прямо сейчас (после того как
    человек вписал новый ключ — не дожидаясь перезапуска)."""
    from server.llm import autoconnect as _ac
    return _ac.connect_all()


@app.get("/api/brains")
def brains_ladder():
    """Лестница мозгов: кто сильнее текущей модели и куда Сайка поднимется,
    если не справится. Тут же видно, кто временно «болен» (лимит/401)."""
    from server.llm import brains as _b
    return _b.describe()


@app.get("/api/doctor/model")
def doctor_model_get():
    """Какая модель чинит окружение (ИИ-Беймакс)."""
    return {"backend": CFG.get("doctor.backend", "") or "",
            "model": CFG.get("doctor.model", "") or ""}


@app.post("/api/doctor/model")
def doctor_model_set(payload: dict):
    """СВОЯ МОДЕЛЬ ДЛЯ БЕЙМАКСА (2026-08-13, просьба владельца).
    Разговорная модель выбирается по скорости — для болтовни это правильно,
    для починки окружения губительно: Беймакс ставит пакеты и правит конфиг,
    и мелкая модель тут именно ЛОМАЕТ (2026-07-29 она решила переустановить
    torch — колесо без CUDA снесло бы видеокарту всему проекту). Пустое
    значение — вернуться к текущей разговорной."""
    b = str(payload.get("backend") or "")
    m = str(payload.get("model") or "")
    if b == "cloud":
        # облако Беймаксу не отдаём: у каждой облачной модели свой адрес и
        # свой ключ (живой 404 с kimi-k3 по адресу GigaChat), а главное — он
        # просыпается в том числе когда отвалилась сеть
        return JSONResponse({"error": "Беймаксу нужна ЛОКАЛЬНАЯ модель: он "
                                      "чинит окружение и должен работать "
                                      "без сети"}, status_code=400)
    CFG.set("doctor.backend", b)
    CFG.set("doctor.model", m)
    log.info("Беймакс будет чинить моделью: %s", f"{b}/{m}" if m else "текущей")
    return {"ok": True, "backend": b, "model": m}


def do_panic_unload() -> str:
    """Та же выгрузка, но обычной функцией — чтобы её могла позвать и
    Сайка инструментом, а не только кнопка в интерфейсе (2026-08-13)."""
    _panic_body()
    return ("Выгрузила всё тяжёлое: слух, голос, локальные модели, кэш "
            "видеокарты. Сама работаю; нужное подгрузится заново.")


@app.post("/api/panic_unload")
async def panic_unload():
    """«ЖЁСТКАЯ РАЗГРУЗКА» (2026-07-25, просьба владельца): выгрузить ВСЁ
    тяжёлое из памяти разом — все STT-движки (включая внешние воркеры,
    им terminate), все TTS-движки, все LLM у Ollama/LM Studio, CUDA-кэш.
    Сама Сайка (сервер, веб-UI, память, диалог) остаётся работать — после
    разгрузки нужное подгружается по порядку руками или лениво при первой
    фразе. Спасение, когда ОЗУ/VRAM забиты и непонятно кем."""
    return await asyncio.get_event_loop().run_in_executor(
        None, _panic_body) or {"ok": True}


def _panic_body():
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
        # ГЛУШИМ НА СЕАНС, А НЕ В КОНФИГ (2026-07-29). Было
        # CFG.set("tts.enabled", False) — запись на диск, переживающая
        # перезапуск: один раз нажал «выгрузить всё», и озвучка мертва
        # навсегда, причём беззвучно (движки грузятся, speak молчит).
        # Смысл разгрузки — освободить память сейчас, а не запретить
        # звук на будущее. Движок в "off" делает ровно нужное: ничего
        # не подгружается само, а первый же выбор движка всё вернёт.
        CFG.set("tts.engine", "off")
        freed.append("слух и озвучка выключены до ручного выбора")
    except Exception:
        pass
    # ВСЁ В НЕАКТИВНОЕ (2026-07-28, просьба владельца): это по сути
    # кнопка выключения всех моделей, и интерфейс обязан это показать —
    # индикаторы гаснут, а не горят зелёным «всё хорошо». Забываем, кто
    # отвечал последним, и гасим отпечаток голоса: его рабочий поток
    # держал бы энкодер в памяти после разгрузки.
    ACTIVE_LLM.update(backend="", model="")
    HARD_UNLOADED["on"] = True
    try:
        # выключаем НА СЕЙЧАС, но узнавание само вернётся, как только
        # человек снова заговорит в живой микрофон (см. voiceprint.feed).
        # Иначе эта кнопка тихо ломала карту голосов на весь день.
        voiceprint.set_enabled(False)
        freed.append("узнавание голоса (вернётся, когда заговоришь)")
    except Exception:
        pass
    broadcast_event({"type": "unloaded"})
    msg = "🧹 Жёсткая разгрузка: выгрузила " + ", ".join(freed or ["ничего"])
    if failed:
        msg += ". НЕ поддались: " + ", ".join(failed) + \
               " — их добивай через диспетчер задач"
    msg += ". Сама я работаю; подгружай нужное по порядку — кликом " \
           "по движку или кнопкой ⬇."
    log.info("panic_unload: freed=%s failed=%s", freed, failed)
    broadcast_event({"type": "baymax", "mood": "meh", "text": msg})


@app.post("/api/tts/model")
async def tts_model(payload: dict):
    """Ручная загрузка/выгрузка модели TTS-движка (кнопки ⬇/⏏ в UI)."""
    name = payload.get("name")
    action = payload.get("action")
    try:
        if action == "load":
            # by_owner: кнопка ⬇ — это явная просьба человека, она
            # снимает автоматическое отключение движка (2026-08-15)
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: tts.load_engine(name, by_owner=True))
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
            if backend == "cloud":
                # у каждой облачной модели свой адрес и свой ключ — при
                # клике переезжаем на них целиком, иначе Groq пошёл бы по
                # адресу Mistral с чужим ключом
                if not llm.use_cloud(value, payload.get("base_url")):
                    return JSONResponse(
                        {"error": f"облачная модель «{value}» не настроена — "
                                  "добавь её через «Онлайн-модель»"},
                        status_code=400)
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
            # СРАЗУ И ПАМЯТЬ (2026-07-29, просьба владельца: «нажимаю на
            # движок — логично у него загрузку, а тот что стоял —
            # выгрузить»). Раньше клик только переключал выбор, модель
            # грузилась лениво на первой фразе, а старая продолжала висеть
            # в VRAM. Теперь: выбор мгновенный, а фоном старый выгружается
            # (сначала — освобождает память) и новый греется.
            prev = CFG.get("tts.engine", "")
            tts.set_engine(value)

            def _swap_tts(_prev=prev, _new=value):
                try:
                    if _prev and _prev not in (_new, "off"):
                        tts.unload_engine(_prev)
                except Exception as e:
                    log.debug("выгрузка %s: %s", _prev, e)
                try:
                    if _new != "off":
                        tts.load_engine(_new, by_owner=True)
                except Exception as e:
                    # ОТКЛЮЧЁННЫЙ ДВИЖОК — ЭТО РЕШЕНИЕ, А НЕ СБОЙ
                    # (2026-08-14). qwen3 сам себя отключил после двух
                    # обвалов; ругаться на это при каждом прогреве —
                    # шум, из-за которого лог читается как поломка.
                    if "отключён" in str(e):
                        log.info("прогрев %s пропущен: он отключён "
                                 "(нативно ронял процесс)", _new)
                    else:
                        log.warning("прогрев %s после клика: %s", _new, e)
            threading.Thread(target=_swap_tts, daemon=True).start()
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


@app.get("/api/llm/free")
def llm_free():
    """Каталог облаков с бесплатным тиром — чтобы можно было поговорить с
    Сайкой без карты и без локальной модели на 8 гигабайт."""
    from server.llm import free_tiers
    return {"providers": free_tiers.catalog(),
            "recommended": free_tiers.RECOMMENDED}


# ------------------------------ голоса ------------------------------
@app.get("/api/tts/voices")
def tts_voices():
    """Каталог голосов по движкам. Отдельный роут, а не часть /api/status:
    Edge отдаёт свой список ПО СЕТИ, и тянуть это на каждый опрос статуса
    (раз в пару секунд) — лишние запросы наружу в горячем цикле."""
    return {"voices": tts.voices(), "meta": tts.engine_meta(),
            "current": {"engine": tts.current_name,
                        "piper": CFG.get("tts.piper.voice", ""),
                        "silero": CFG.get("tts.silero.speaker", ""),
                        "edge": CFG.get("tts.edge.voice", ""),
                        "ref": str(CFG.get("tts.voice_ref_wav", "")).replace(
                            "\\", "/").split("/")[-1]}}


@app.post("/api/tts/voice")
def tts_set_voice(payload: dict):
    engine = str(payload.get("engine", "")).strip()
    voice = str(payload.get("voice", "")).strip()
    try:
        msg = tts.set_voice(engine, voice)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if payload.get("select_engine"):
        try:
            tts.set_engine(engine)
        except Exception:
            pass
    return {"ok": True, "message": msg}


@app.post("/api/tts/voice/download")
async def tts_voice_download(payload: dict):
    """Скачать голос из витрины. В отдельном потоке: закачка идёт по сети и
    в event loop заморозила бы /health и весь остальной сервер."""
    engine = str(payload.get("engine", "")).strip()
    key = str(payload.get("voice", "")).strip()
    if engine != "piper":
        return {"ok": False, "error": "скачивание есть только у Piper — "
                                      "остальные движки либо облачные, либо "
                                      "работают с образцами из папки voice/"}
    try:
        from server.tts import extra as _extra
        msg = await asyncio.get_event_loop().run_in_executor(
            None, _extra.piper_download, key)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    return {"ok": True, "message": msg}


@app.post("/api/tts/voice/delete")
def tts_voice_delete(payload: dict):
    """Удалить скачанный голос. Не в потоке: удаление файлов мгновенное."""
    engine = str(payload.get("engine", "")).strip()
    key = str(payload.get("voice", "")).strip()
    if engine != "piper":
        return {"ok": False, "error": "удалять можно только скачанные голоса "
                                      "Piper"}
    try:
        from server.tts import extra as _extra
        msg = _extra.piper_delete(key)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    return {"ok": True, "message": msg}


@app.post("/api/tts/preview")
async def tts_preview(payload: dict):
    """Короткая фраза выбранным движком — кнопка «послушать». Синтез идёт в
    отдельном потоке: часть движков блокирующие, и в event loop они
    заморозили бы весь сервер вместе с /health."""
    from fastapi.responses import Response as _Resp
    engine = str(payload.get("engine", "")).strip() or None
    text = str(payload.get("text", "")).strip() or None
    try:
        pcm, sr = await asyncio.get_event_loop().run_in_executor(
            None, tts.preview, engine, text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:300])
    import io as _io
    import struct as _struct
    # собираем WAV вручную: float32 PCM, чтобы не тянуть soundfile в роут
    n = len(pcm)
    hdr = b"RIFF" + _struct.pack("<I", 36 + n) + b"WAVEfmt " \
        + _struct.pack("<IHHIIHH", 16, 3, 1, sr, sr * 4, 4, 32) \
        + b"data" + _struct.pack("<I", n)
    return _Resp(content=hdr + pcm, media_type="audio/wav")


# ------------------------------ лорбук ------------------------------
@app.get("/api/lore")
def lore_get():
    from server import lorebook
    return {"entries": lorebook.load(), "stats": lorebook.stats()}


@app.post("/api/lore/save")
def lore_save(payload: dict):
    """Добавить или обновить запись. Без id — создастся по первому ключу."""
    from server import lorebook
    entries = lorebook.upsert(dict(payload.get("entry") or {}))
    return {"entries": entries, "stats": lorebook.stats()}


@app.post("/api/lore/delete")
def lore_delete(payload: dict):
    from server import lorebook
    entries = lorebook.delete(str(payload.get("id", "")))
    return {"entries": entries, "stats": lorebook.stats()}


@app.get("/api/prompt/order")
def prompt_order_get():
    from server import prompt_blocks
    return {"order": prompt_blocks.order(),
            "all": prompt_blocks.DEFAULT_ORDER}


@app.post("/api/prompt/order")
def prompt_order_set(payload: dict):
    """Порядок блоков промпта. Ближе к концу = весит больше: у языковых
    моделей свежая инструкция перебивает раннюю, поэтому «заметки автора»
    по умолчанию последние."""
    from server import prompt_blocks
    order = [x for x in (payload.get("order") or [])
             if x in prompt_blocks.DEFAULT_ORDER]
    if not order:
        return {"error": "пустой порядок", "order": prompt_blocks.order()}
    CFG.set("prompt.order", order)
    log.info("Порядок блоков промпта: %s", " → ".join(order))
    return {"order": prompt_blocks.order(),
            "all": prompt_blocks.DEFAULT_ORDER}


# ------------------------ заметки автора ------------------------
@app.get("/api/notes")
def notes_get():
    return {"notes": CFG.get("persona.author_notes", "") or ""}


@app.post("/api/notes")
def notes_set(payload: dict):
    """Скрытая инструкция «что делаем сейчас» — в отличие от персоны,
    которая описывает, КТО она. Меняется часто, персона — почти никогда."""
    CFG.set("persona.author_notes", str(payload.get("notes", ""))[:4000])
    return {"ok": True}


@app.post("/api/dialog/drop_last")
def dialog_drop_last(payload: dict):
    """Забыть последнюю реплику Сайки — для кнопки «↻ переспросить».
    Именно удалить, а не пометить: иначе модель увидит и отвергнутый ответ,
    и повторный вопрос, и выдаст то же самое, только с извинениями."""
    role = payload.get("role", "saika")
    n = int(payload.get("n", 1))
    dropped = memory.drop_last(CFG.get("owner.id", "owner"), role=role, n=n)
    log.info("Переспросить: забыла %d последних реплик (%s)", dropped, role)
    return {"ok": True, "dropped": dropped}


# --------------------------- сэмплинг LLM ---------------------------
# Пресеты — главная ценность панели: крутить 16 ручек вслепую никто не будет,
# а «живая речь» это один клик. Значения из практики llama.cpp-сообщества:
# DRY против повторов, XTC против сползания в шаблон, min_p как основной
# отсекатель хвоста вместо top_k/top_p.
SAMPLING_PRESETS = {
    "off": {"enabled": False},
    "lively": {                     # живая речь — то, зачем это вообще нужно
        "enabled": True, "top_p": 1.0, "top_k": 0, "min_p": 0.05,
        "repeat_penalty": 1.0,      # DRY делает это лучше, дублировать вредно
        "presence_penalty": 0.0, "frequency_penalty": 0.0,
        "dry_multiplier": 0.8, "dry_base": 1.75, "dry_allowed_length": 2,
        "xtc_probability": 0.3, "xtc_threshold": 0.1,
        "dynatemp_range": 0.0,
    },
    "precise": {                    # факты, код, инструменты
        "enabled": True, "top_p": 0.9, "top_k": 40, "min_p": 0.1,
        "repeat_penalty": 1.05,
        "presence_penalty": 0.0, "frequency_penalty": 0.0,
        "dry_multiplier": 0.0, "xtc_probability": 0.0,
        "dynatemp_range": 0.0,
    },
    "wild": {                       # эксперименты, максимум непредсказуемости
        "enabled": True, "top_p": 1.0, "top_k": 0, "min_p": 0.02,
        "repeat_penalty": 1.0,
        "dry_multiplier": 1.0, "dry_base": 1.75, "dry_allowed_length": 2,
        "xtc_probability": 0.5, "xtc_threshold": 0.1,
        "dynatemp_range": 0.4, "dynatemp_exponent": 1.0,
    },
}


@app.get("/api/llm/sampling")
def sampling_get():
    return {"sampling": CFG.get("llm.sampling", {}) or {},
            "presets": list(SAMPLING_PRESETS)}


# ─────────────────── САМОЧУВСТВИЕ ───────────────────
@app.get("/api/psyche")
def psyche_get():
    from server import psyche
    return psyche.state()


@app.post("/api/psyche")
def psyche_set(payload: dict):
    from server import psyche
    try:
        return {"ok": True, **psyche.set_settings(payload or {})}
    except (TypeError, ValueError) as e:
        return {"ok": False, "error": str(e)}


# ─────────────────── ДОСЬЕ НА МОДЕЛИ ───────────────────
# Надёжность отдельно от скорости: бодрая мелкая модель, которая пишет
# «запустила», ничего не запустив, хуже медленной и честной.
@app.get("/api/models/dossier")
def models_dossier():
    from server import model_dossier as dos
    dos.sync_all()          # новые модели заводят досье сами
    return {"models": dos.rank(), "prefer_cheap":
            bool(CFG.get("llm.prefer_cheap", True)),
            "cost_word": dos.COST_WORD}


@app.post("/api/models/dossier")
def models_dossier_set(payload: dict):
    from server import model_dossier as dos
    name = str(payload.get("name", ""))
    try:
        if "prefer_cheap" in payload:
            CFG.set("llm.prefer_cheap", bool(payload["prefer_cheap"]))
        if name and "manual" in payload:
            dos.set_manual(name, payload["manual"])
        if name and "note" in payload:
            dos.set_note(name, str(payload["note"]))
        if name and "cost" in payload:
            dos.set_cost(name, str(payload["cost"]))
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "models": dos.rank(),
            "prefer_cheap": bool(CFG.get("llm.prefer_cheap", True))}


# ─────────────────── БИБЛИОТЕКА АВАТАРОВ ───────────────────
# 2026-07-26. Раньше аватар был ОДИН файл, прописанный в config руками.
# Теперь папка models/avatar/library: что положил — то и доступно, 2D и 3D
# наравне, переключение кликом.
@app.get("/api/avatar/library")
def avatar_library():
    from server import avatar_hub as ah
    return {"models": ah.scan(), "settings": ah.settings(),
            "dir": str(ah.lib_dir())}


@app.post("/api/avatar/select")
def avatar_select(payload: dict):
    from server import avatar_hub as ah
    msg = ah.select(str(payload.get("name", "")))
    broadcast_event({"type": "avatar_reload"})   # окно аватара перечитает
    return {"ok": True, "message": msg, "settings": ah.settings()}


@app.post("/api/avatar/delete")
def avatar_delete(payload: dict):
    from server import avatar_hub as ah
    return {"ok": True, "message": ah.delete(str(payload.get("name", "")))}


@app.post("/api/avatar/folder")
def avatar_folder():
    from server import avatar_hub as ah
    return {"ok": True, "message": ah.open_folder()}


@app.post("/api/avatar/settings")
def avatar_settings(payload: dict):
    from server import avatar_hub as ah
    try:
        st = ah.set_settings(payload)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    broadcast_event({"type": "avatar_settings", **st})
    return {"ok": True, "settings": st}


@app.post("/api/avatar/upload")
async def avatar_upload(file: UploadFile = File(...)):
    """Загрузка своей модели. Читаем в память целиком — модели до 300 МБ,
    а поточная запись усложнила бы проверку размера до сохранения."""
    from server import avatar_hub as ah
    data = await file.read()
    try:
        name = await asyncio.get_event_loop().run_in_executor(
            None, ah.save_upload, file.filename, data)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:
        log.exception("загрузка аватара")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    return {"ok": True, "name": name}


@app.get("/api/avatar/current")
def avatar_current():
    """Что сейчас надето — окно аватара спрашивает это при старте, чтобы
    понять, рисовать three.js или 2D-спрайт."""
    from server import avatar_hub as ah
    p = ah.current_path()
    return {"kind": ah.current_kind(), "name": p.stem,
            "url": "/avatar/model.vrm" if ah.current_kind() == "3d"
                   else "/avatar/sprite",
            "settings": ah.settings()}


@app.get("/avatar/sprite")
def avatar_sprite():
    """Картинка 2D-аватара как есть."""
    from server import avatar_hub as ah
    p = ah.current_path()
    if not p.exists() or ah.current_kind() != "2d":
        return JSONResponse({"error": "сейчас надета не 2D-модель"},
                            status_code=404)
    mt = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
          ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(p.suffix.lower(),
                                                           "image/png")
    return FileResponse(p, media_type=mt,
                        headers={"Cache-Control": "no-store"})


# ─────────────────── ДОСТУП С ТЕЛЕФОНА ───────────────────
@app.get("/api/phone")
def phone_get():
    from server import phone as _ph
    return _ph.state()


@app.post("/api/phone")
def phone_set(payload: dict):
    from server import phone as _ph
    msg = ""
    if payload.get("new_token"):
        _ph.new_token()
    if payload.get("make_cert"):
        msg = _ph.make_cert(force=bool(payload.get("force")))
    if "https" in payload:
        on = bool(payload["https"])
        if on and not _ph.cert_ready():
            msg = _ph.make_cert()      # включаем — сразу и делаем
        CFG.set("server.https", on)
    if "open" in payload:
        _ph.set_open(bool(payload["open"]))
    st = _ph.state()
    st["restart_needed"] = True   # порт занимается один раз при старте
    if msg:
        st["message"] = msg
    return st


@app.get("/api/phone/qr")
def phone_qr(url: str = ""):
    from server import phone as _ph
    if not url:
        us = _ph.urls()
        url = us[0]["url"] if us else ""
    if not url:
        return PlainTextResponse("", media_type="image/svg+xml")
    svg = _ph.qr_svg(url)
    if not svg:
        return JSONResponse({"error": "нет библиотеки qrcode — она "
                                      "поставится при следующем запуске "
                                      "start.bat"}, status_code=503)
    return PlainTextResponse(svg, media_type="image/svg+xml")


# ─────────────────── УПРАВЛЕНИЕ КОМПЬЮТЕРОМ ───────────────────
# 2026-07-26. Каталог программ собирается сам из меню «Пуск» — прежний
# белый список путей надо было заполнять руками, и он так и остался пустым.
# Здесь же ползунок доверия и рабочая папка: три вещи, которые вместе
# отвечают на вопрос «что ей вообще позволено на этой машине».
@app.get("/api/pc")
def pc_get():
    from server import pc_control as pc
    from server import trust as _trust
    from server import file_hands
    try:
        catalog = pc.build_index()
    except Exception as e:
        log.warning("каталог программ не собрался: %s", e)
        catalog = {"apps": [], "built": 0}
    bad = pc.blocked()
    return {
        "enabled": bool(CFG.get("pc.enabled", True)),
        "self_ui": bool(CFG.get("pc.self_ui", True)),
        "open_any_folder": bool(CFG.get("pc.open_any_folder", True)),
        "apps": [{"name": a["name"], "blocked": a["name"].lower() in bad}
                 for a in catalog.get("apps", [])],
        "built": catalog.get("built", 0),
        "trust": _trust.describe(),
        "roots": [str(r) for r in file_hands.roots()],
        "roots_raw": list(CFG.get("files.roots", ["F:/AI_load_work"])),
    }


@app.post("/api/pc/refresh")
async def pc_refresh():
    """Пересобрать каталог: обход «Пуска» это тысячи файлов, в event loop
    он подвесил бы весь сервер вместе с /health."""
    from server import pc_control as pc
    idx = await asyncio.get_event_loop().run_in_executor(
        None, pc.build_index, True)
    return {"ok": True, "count": len(idx.get("apps", []))}


@app.post("/api/pc/set")
def pc_set(payload: dict):
    from server import trust as _trust
    for key, cfg in (("enabled", "pc.enabled"), ("self_ui", "pc.self_ui"),
                     ("open_any_folder", "pc.open_any_folder")):
        if key in payload:
            CFG.set(cfg, bool(payload[key]))
    if "trust_level" in payload:
        try:
            CFG.set("trust.level", max(1, min(10, int(payload["trust_level"]))))
        except (TypeError, ValueError):
            return {"ok": False, "error": "доверие — это число от 1 до 10"}
    if "block" in payload:
        from server import pc_control as pc
        pc.set_blocked(str(payload["block"]), bool(payload.get("on", True)))
    if "roots" in payload:
        # рабочая папка: единственное место, где ей вообще можно создавать
        # и править файлы. Проверяем, что путь существует — иначе человек
        # опечатается и потом полчаса гадает, почему «она ничего не пишет»
        from pathlib import Path as _P
        roots, bad = [], []
        for r in (payload["roots"] or []):
            r = str(r).strip()
            if not r:
                continue
            (roots if _P(r).is_dir() else bad).append(r)
        if bad:
            return {"ok": False,
                    "error": "нет таких папок на диске: " + ", ".join(bad)}
        if not roots:
            return {"ok": False, "error": "нужна хотя бы одна рабочая папка"}
        CFG.set("files.roots", roots)
    return {"ok": True, "trust": _trust.describe()}


@app.get("/api/pc/windows")
def pc_windows():
    """Карта рабочего стола — та же, что видит модель. В настройках она
    нужна, чтобы владелец проверил: видит ли Сайка его второй монитор."""
    from server import pc_control as pc
    try:
        return {"map": pc.screen_map(), "windows": pc.windows()[:40]}
    except Exception as e:
        return {"map": f"не смогла посмотреть окна: {e}", "windows": []}


# ─────────────────────── СКОРОСТЬ ОТВЕТА ───────────────────────
# 2026-07-26, просьба владельца: «не вижу настроек кешей, температуры».
# Ручки, которые реально решают, сколько ждать до первого слова, были
# раскиданы по config.json и наружу не показывались вообще. Собраны в одном
# месте, каждая с честной ценой: почти все они — размен «помнит больше» на
# «отвечает быстрее», и человек должен видеть, чем платит.
_SPEED_FIELDS = (
    ("llm.temperature", 0.8, float),
    ("llm.context_chars", 0, int),          # 0 = считать от окна модели
    ("llm.cloud.context_chars", 9000, int),
    ("llm.cloud.context_chars_max", 40000, int),   # потолок при известном окне
    ("tools.trim", True, bool),                    # слать схемы под фразу
    ("tools.max_chars", 12000, int),               # сколько отдаём схемам
    ("memory.context_chars", 3000, int),
    ("llm.keep_alive", "30m", str),
    ("llm.cache_prompt", True, bool),
    ("llm.target_response_s", 0, float),
    ("llm.max_gen_seconds", 180, int),
)


@app.get("/api/llm/speed")
def speed_get():
    vals = {k: CFG.get(k, d) for k, d, _t in _SPEED_FIELDS}
    vals["think"] = bool(CFG.get("llm.think", False))
    vals["backend"] = CFG.get("llm.backend")
    # последний реальный замер — чтобы крутить ручки и сразу видеть эффект,
    # а не гадать по ощущениям
    vals["last"] = dict(LAST_TIMING)
    return vals


@app.post("/api/llm/speed")
def speed_set(payload: dict):
    types = {k: t for k, _d, t in _SPEED_FIELDS}
    for k, v in (payload or {}).items():
        if k == "think":
            CFG.set("llm.think", bool(v))
            continue
        if k not in types:
            continue
        t = types[k]
        try:
            CFG.set(k, bool(v) if t is bool else t(v))
        except (TypeError, ValueError):
            return {"ok": False, "error": f"«{k}»: не разобрала значение {v!r}"}
    return {"ok": True, **speed_get()}


@app.post("/api/llm/sampling")
def sampling_set(payload: dict):
    """Панель «Сэмплинг» в меню модели. preset накладывается поверх текущего,
    отдельные поля — поверх пресета, чтобы можно было взять «живую речь» и
    подкрутить одну ручку."""
    cur = dict(CFG.get("llm.sampling", {}) or {})
    name = payload.get("preset")
    if name in SAMPLING_PRESETS:
        cur.update(SAMPLING_PRESETS[name])
        cur["preset"] = name
    for k, v in (payload.get("fields") or {}).items():
        if k in cur or k in ("stop", "seed"):
            cur[k] = v
            cur["preset"] = "custom"
    if "enabled" in payload:
        cur["enabled"] = bool(payload["enabled"])
        if not cur["enabled"]:
            cur["preset"] = "off"
    CFG.set("llm.sampling", cur)
    log.info("Сэмплинг: %s (%s)", "вкл" if cur.get("enabled") else "выкл",
             cur.get("preset"))
    return {"sampling": cur, "presets": list(SAMPLING_PRESETS)}


# ------------------------------- зрение -------------------------------
@app.get("/api/vision/state")
def vision_state():
    try:
        from server import vision
        return vision.state()
    except Exception as e:
        return {"enabled": False, "error": str(e), "monitors": [],
                "cameras": [], "watch_on": False}


@app.post("/api/vision/set")
def vision_set(payload: dict):
    """Кнопка 👁 в шапке и её меню: тумблер глаз, выбор дисплея/камеры,
    режим наблюдения. Наблюдение включается ТОЛЬКО отсюда — сама Сайка
    его не запускает."""
    from server import vision
    if "enabled" in payload:
        vision.set_enabled(bool(payload["enabled"]))
        if payload["enabled"]:
            VISION_USED["ts"] = time.time()
    if payload.get("monitor") is not None:
        CFG.set("vision.monitor", int(payload["monitor"]))
    if payload.get("camera") is not None:
        cam = int(payload["camera"])
        CFG.set("vision.camera_index", cam)
        # переключили камеру или выключили — прошлую отпускаем сразу, чтобы
        # не горела лампочка на устройстве, которым уже не пользуемся
        vision.camera_stop()
        if cam >= 0:
            # пробуем сразу: список DirectShow полон виртуальных устройств,
            # которые перечисляются всегда, а открываются далеко не всегда.
            # Лучше сказать об этом в момент выбора, чем показать чёрный
            # прямоугольник и оставить владельца гадать.
            vision.test_camera(cam, force=True)
    if payload.get("source"):
        CFG.set("vision.watch_source", str(payload["source"]))
    if "watch" in payload:
        if payload["watch"]:
            vision.watch_start(_vision_watch_cb,
                               payload.get("source"))
        else:
            vision.watch_stop()
    return vision.state()


@app.post("/api/vision/shot")
def vision_shot(payload: dict):
    """Пробный кадр для интерфейса: проверить, что захват вообще живой,
    не спрашивая Сайку. Возвращает data-url, UI показывает превью."""
    from server import vision
    if not vision.enabled():
        return {"ok": False, "error": "глаза выключены"}
    try:
        img = vision.grab(payload.get("source") or "screen")
        return {"ok": True, "image": vision.to_data_url(img, max_side=640,
                                                        quality=70),
                "source": vision.state()["last_source"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/vision/test_cameras")
def vision_test_cameras():
    """Кнопка «проверить все камеры». Открывает каждое устройство по очереди,
    поэтому занимает секунды — вешать это на открытие меню нельзя."""
    from server import vision
    vision.test_all_cameras()
    return vision.state()


@app.get("/api/vision/mjpeg")
def vision_mjpeg(source: str = "camera"):
    """Живое окно вебки/экрана прямо в интерфейсе. Обычный <img src> в
    браузере понимает multipart/x-mixed-replace как видео — ни WebRTC, ни
    единой новой зависимости. Пока окно открыто, камера считается нужной и
    не гаснет по простою; закрыл — через минуту сама отпустится."""
    from fastapi.responses import StreamingResponse
    from server import vision
    if not vision.enabled():
        raise HTTPException(status_code=409, detail="глаза выключены")
    if source.startswith("cam") and not vision.camera_enabled():
        raise HTTPException(status_code=409, detail="камера выключена")
    return StreamingResponse(
        vision.mjpeg(source),
        media_type="multipart/x-mixed-replace; boundary=saikaframe",
        headers={"Cache-Control": "no-store"})


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
# все живые плееры: «стоп» должен доставать до звука, который уже играет,
# а плеер создаётся на каждый REST-ответ и глобальной переменной не был
SPEAKERS = set()


class _ServerSpeaker:
    """Играет PCM (int16 mono) через колонки ЭТОГО ПК — для клиентов без
    своего аудио (нативный UE-интерфейс). Ленивая инициализация sounddevice:
    нет пакета — молча без звука (подсказка уйдёт в problems)."""

    def __init__(self):
        self._streams = {}   # "primary"/"dup" -> (sd.OutputStream, sr, device)
        self._q = {}         # то же -> очередь кусков
        self._th = {}        # то же -> поток-писатель
        SPEAKERS.add(self)

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
        # ЗАПАС В БУФЕРЕ ПРОТИВ МИКРОЗАВИСАНИЙ (2026-08-15). Владелец:
        # «в голосе появились микрозависания, локалку я не использую».
        # Поток открывался с настройками по умолчанию — то есть с самым
        # коротким буфером, какой согласится дать драйвер. Такой буфер
        # прощает задержку в единицы миллисекунд, а у нас в одном процессе
        # живут распознавание речи, отпечаток голоса, классификатор звуков
        # и веб-сервер: стоит ГИЛу задержать поток озвучки на пару десятков
        # миллисекунд — и в звуке дырка. latency='high' просит у драйвера
        # буфер побольше: задержка старта вырастает на десятки миллисекунд
        # (на слух незаметно), зато рывки пропадают.
        stream = sd.OutputStream(samplerate=sr, channels=1, dtype="float32",
                                 device=device,
                                 latency=CFG.get("tts.out_latency", "high"))
        stream.start()
        self._streams[key] = (stream, sr, device)
        return stream

    def _pump(self, key: str, device_cfg_key: str):
        """Свой поток на каждое устройство: пишем из очереди, а не по месту.

        Раньше play() писал ПОДРЯД в оба устройства (наушники и CABLE), в
        одном потоке. write() блокирующий: пока драйвер наушников не примет
        кусок, кусок для CABLE ждёт, и наоборот — у двух устройств свои
        часы, и они начинают тормозить друг друга. Плюс сама озвучка не
        может считать следующий кусок, пока не закончится запись. Очередь
        разводит их: генератор кладёт и идёт дальше, устройства пишут
        каждое в своём темпе."""
        import queue as _q
        while True:
            try:
                item = self._q[key].get()
            except Exception:
                return
            if item is None:
                return
            data, sr = item
            try:
                self._get_stream(key, device_cfg_key, sr).write(data)
            except Exception as e:
                log.debug("вывод озвучки %s: %s", key, e)
            finally:
                try:
                    self._q[key].task_done()
                except Exception:
                    pass

    def _send(self, key: str, device_cfg_key: str, data, sr: int):
        import queue as _q
        if key not in self._q:
            self._q[key] = _q.Queue(maxsize=64)
            t = threading.Thread(target=self._pump, args=(key, device_cfg_key),
                                 daemon=True, name="speak:" + key)
            t.start()
            self._th[key] = t
        try:
            self._q[key].put_nowait((data, sr))
        except Exception:
            # очередь забита — устройство отстаёт больше чем на секунду.
            # Лучше уронить кусок, чем копить задержку: голос должен идти
            # вровень с разговором, а не отставать от него.
            log.debug("очередь вывода %s переполнена — кусок пропущен", key)

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
        self._send("primary", "tts.output_device", data, sr)
        # дубль — как в браузере: второе устройство одновременно (например,
        # CABLE Input для LipSync аватара, пока основное играет в наушники,
        # или наоборот). Пусто в конфиге -> дубль просто не создаётся.
        if CFG.get("tts.output_device_dup"):
            self._send("dup", "tts.output_device_dup", data, sr)

    def drop(self):
        """Выбросить всё, что ещё не прозвучало. Устройства не закрываем —
        следующая фраза заиграет без паузы на переоткрытие."""
        for q in list(self._q.values()):
            try:
                while True:
                    q.get_nowait()
                    q.task_done()
            except Exception:
                pass

    def close(self):
        SPEAKERS.discard(self)
        # сначала гасим писателей, потом сами устройства: иначе поток
        # успевает дописать в уже закрытый поток и ловит исключение
        for key, q in list(self._q.items()):
            try:
                q.put_nowait(None)
            except Exception:
                pass
        for key, t in list(self._th.items()):
            try:
                t.join(timeout=1.0)
            except Exception:
                pass
        self._q.clear()
        self._th.clear()
        for key, (stream, _sr, _dev) in list(self._streams.items()):
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self._streams.clear()


AUDIO_LEVEL = {"level": 0.0, "ts": 0.0}

# Что Сайка только что произнесла — чтобы узнать собственный голос, если он
# вернулся в микрофон из колонок. Живёт на уровне модуля: озвучка идёт в
# run_dialog, а разбор речи — в обработчике вебсокета.
SAID_RECENT: list = []

# Каким умением она работала в прошлый ход — чтобы «молодец» через минуту
# улучшало веру именно в то, за что похвалили, а не в «разговор» вообще.
LAST_SKILL: dict = {"name": ""}


def remember_said(text: str):
    """Запомнить произнесённую фразу словами (для защиты от эха)."""
    t = re.sub(r"[^а-яa-zё ]", " ", (text or "").lower())
    words = [w for w in t.split() if len(w) > 2]
    if words:
        SAID_RECENT.append((time.time(), words))
    del SAID_RECENT[:-8]


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


def _is_perf_query(text: str) -> bool:
    """Разговор о её скорости/задержке — повод показать ей её же телеметрию."""
    t = (text or "").lower()
    keys = ("скорост", "быстр", "медлен", "тормоз", "задержк", "лаг",
            "ток/с", "токен", "тайминг", "долго дума", "долго отвеча",
            "распозна", "отклик", "речь в секунду")
    return any(k in t for k in keys)


def _perf_block() -> str:
    """Телеметрия последнего ответа — её собственные ощущения в числах.
    Собирается из того, что сервер и так меряет; ничего не выдумывается."""
    parts = []
    st = LAST_STATS
    if st.get("ts") and time.time() - st["ts"] < 3600:
        p = []
        if st.get("latency_ms") is not None:
            p.append("от фразы человека до твоего первого слова — "
                     f"{st['latency_ms'] / 1000:.1f} с")
        if st.get("tps"):
            # ~2.5 токена на русское слово: 78 ток/с ≈ 1870 слов/мин —
            # раз в десять быстрее человеческой речи
            p.append(f"скорость твоей генерации — {st['tps']} токенов/с "
                     f"(≈{int(st['tps'] * 24)} слов в минуту, много быстрее "
                     "человеческой речи)")
        if st.get("tokens"):
            p.append(f"в прошлом ответе было {st['tokens']} токенов")
        if st.get("model"):
            p.append(f"думала модель {st['model']}")
        if p:
            parts.append("; ".join(p))
    if LAST_STT.get("ts") and time.time() - LAST_STT["ts"] < 3600:
        parts.append("последнюю фразу ты расслышала за "
                     f"{LAST_STT['stt_ms'] / 1000:.1f} с "
                     f"(движок слуха {LAST_STT.get('engine', '?')})")
    tm = LAST_TIMING
    if tm.get("prefill") is not None:
        parts.append("подготовка мыслей (prefill) в прошлый раз заняла "
                     f"{tm['prefill'] / 1000:.1f} с, попадание в кэш "
                     f"{tm.get('cache_hit_pct', '?')}%")
    if not parts:
        return ""
    return ("### Твоя телеметрия (факт, замерено сервером только что):\n- "
            + "\n- ".join(parts) +
            "\nЭто твои реальные числа — можешь называть их уверенно, "
            "без «я не могу измерить».")


def _is_model_query(text: str) -> bool:
    """Разговор про её собственные мозги: какие модели есть, чем думает,
    взять поумнее/побыстрее. Нужен быстрому режиму — сводка по моделям
    (~680 символов) стоит полного prefill'а каждую реплику, а пригождается
    в одной из ста."""
    t = (text or "").lower()
    keys = ("модел", "мозг", "поумнее", "поглупее", "быстрее думай",
            "какая ллм", "llm", "ллм", "нейросет", "переключ", "движок",
            "gpt", "gemma", "qwen", "облач", "локальн")
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
    # БЫСТРОЕ МЫШЛЕНИЕ — ДО памяти (2026-07-27): решение о маршруте стоит
    # долей миллисекунды и нужно уже здесь, чтобы лёгкой реплике не платить
    # за RAG. См. server/llm/router.py.
    _route, _route_why = ("local", "")
    try:
        from server.llm import router as _router
        _route, _route_why = _router.pick(user_text)
    except Exception as e:
        log.debug("маршрутизатор пропущен: %s", e)
    # жалоба на результат? считаем серию и при второй подряд зовём облако
    if _COMPLAINT_RE.search(user_text or ""):
        FAIL_STREAK["n"] = (FAIL_STREAK["n"] + 1
                            if time.time() - FAIL_STREAK["ts"] < 600 else 1)
        FAIL_STREAK["ts"] = time.time()
    _escalated = False
    _prefer_local = None
    _prefer_brain = None      # (backend, model) — ступень лестницы мозгов
    # два повода поднять мозги: жалоба человека И собственный механический
    # провал. Второй важнее — он объективен и не требует, чтобы человек
    # дважды сказал «не работает».
    _mech = (MODEL_FAIL["n"] >= 2
             and time.time() - MODEL_FAIL["ts"] < 600)
    # В РАЗГОВОРЕ МОЗГИ НЕ МЕНЯЮТСЯ (2026-08-15). Живой чат: GigaChat,
    # mistral, GigaChat, mistral — через реплику, на пустой болтовне. У
    # каждой модели свой голос и своя манера, и человек разговаривает то с
    # одной, то с другой: «для начала нормально научиться разговаривать».
    # Лестница задумана для ЗАДАЧ, где важно дожать результат; в разговоре
    # менять собеседника посреди фразы — это не помощь, а раздражение.
    _task_now = False
    try:
        from server import workflow as _wf_esc
        _task_now = bool(_wf_esc.scenario(user_text))
    except Exception:
        pass
    if ((FAIL_STREAK["n"] >= 2 or _mech) and _route != "cloud" and _task_now
            and CFG.get("llm.escalate_on_fail", True)):
        _why = ("не справляется механически: " + MODEL_FAIL["why"]
                if _mech else "две неудачи подряд")
        # ЛЕСТНИЦА МОЗГОВ (2026-08-13, просьба владельца: «если не
        # получилось — просто использует мозг с более высоким рейтингом»).
        # Раньше здесь была ОДНА ступень: активный облачный слот, а если он
        # пуст — лучшая локальная ПО СКОРОСТИ (llm_scores меряет tps, то
        # есть самую быструю, обычно самую тупую). Теперь подъём идёт по
        # настоящей лестнице (server/llm/brains.py): облака с живым ключом
        # и парк, отсортированные по мозгам, и КАЖДЫЙ следующий провал
        # поднимает ещё на ступень, а не топчется на той же.
        try:
            from server.llm import brains as _brains
            if time.time() - ESCALATION["ts"] > 900:
                ESCALATION["tried"] = set()      # старое не мешает новому
            _step = _brains.next_brain(ESCALATION["tried"])
            if _step:
                ESCALATION["tried"].add((_step["backend"], _step["model"]))
                ESCALATION["ts"] = time.time()
                _prefer_brain = (_step["backend"], _step["model"])
                _route = "cloud" if _step["backend"] == "cloud" else _route
                _route_why = (_why + f" — поднимаюсь на {_step['model']} "
                              f"(мозги {_step['rank']}/10)")
                _escalated = True
                log.info("Эскалация: %s -> %s/%s (ранг %s)",
                         CFG.get("llm.model", ""), _step["backend"],
                         _step["model"], _step["rank"])
        except Exception as e:
            log.debug("лестница мозгов не сработала: %s", e)
        if _escalated:
            MODEL_FAIL["n"] = 0
            FAIL_STREAK["n"] = 0
            log.info("Эскалация: %s", _route_why)
    # РУКИ — ТОЛЬКО ТОМУ, КТО ИМИ РАБОТАЕТ (2026-08-13). Живой лог: пять
    # реплик подряд «уточни, пожалуйста» на «открой Геншин», хотя ярлык в
    # каталоге есть и нечёткий поиск даёт 70 баллов. Дело не в поиске и не
    # в предохранителе — за рулём сидела 4-миллиардная модель, которая
    # команду в вызов инструмента не превращает. Болтать пусть болтает кто
    # угодно (это быстро и бесплатно), но КОМАНДУ отдаём мозгу, который
    # дотягивает до планки. Дорого это не выходит: регламент рук
    # (workflow.scenario) отличает задачу от разговора, и на «привет»
    # облако не дёргается вообще.
    if not _escalated and not _prefer_brain:
        try:
            from server import workflow as _wf0
            from server.llm import brains as _br0
            if _wf0.scenario(user_text):
                _cb, _cm = _br0.current()
                _min = int(CFG.get("llm.hands_min_rank", 7))
                if _br0.rank_of(_cm, _cb) < _min:
                    _h = _br0.for_hands(_min)
                    if _h:
                        _prefer_brain = (_h["backend"], _h["model"])
                        _route = ("cloud" if _h["backend"] == "cloud"
                                  else _route)
                        _route_why = (f"задача руками — беру {_h['model']} "
                                      f"(мозги {_h['rank']}/10)")
                        log.info("Руки: %s -> %s/%s", _cm, _h["backend"],
                                 _h["model"])
        except Exception as e:
            log.debug("выбор мозга под руки пропущен: %s", e)
    _fast = bool(CFG.get("llm.fast_mode", False))
    # ЛЁГКАЯ РЕПЛИКА: короткая болтовня без намёка на задачу/инструменты.
    # Ей не нужен поиск по долгой памяти — это 125-500мс Chroma/SQLite на
    # каждое «привет». Диалоговую память она не теряет: последние реплики
    # и так в истории, а RAG вернётся на первой же содержательной фразе.
    _light = (_fast and _route == "local" and not image
              and len((user_text or "").strip())
              < int(CFG.get("llm.light_max_chars", 48)))
    # РЕФЛЕКС (2026-07-27): однозначная команда исполняется СЕЙЧАС, до
    # всякого промпта — как спинной мозг, не дожидаясь коры. Модель потом
    # прокомментирует уже сделанное (см. вставку в dyn_parts ниже).
    _reflex_done = ""
    # уже исполнено мгновенно в handle_text — второй раз не крутим ручку
    if (EARLY_REFLEX.get("text") == user_text
            and time.time() - EARLY_REFLEX.get("ts", 0) < 30):
        _reflex_done = EARLY_REFLEX.get("result", "")
        EARLY_REFLEX["text"] = ""
    try:
        from server import reflex as _rx
        _rx_hit = None if _reflex_done else _rx.match(user_text)
        if _rx_hit:
            out.put({"type": "tool", "name": "⚡ " + _rx_hit[0],
                     "args": str(_rx_hit[1])[:300]})
            _reflex_done = _rx.execute(_rx_hit, user_text)
            # ЧТО ИЗ ЭТОГО ВЫШЛО — В ЧАТ, ЦЕЛИКОМ (2026-08-14). Раньше в
            # чат уходил только ВЫЗОВ, а ответ инструмента («Не нашла окно
            # «Contacts»», «Открыла C:\, внутри: …») знала одна лишь
            # модель — и пересказывала как придётся, а то и бодрым
            # «готово» поверх отказа. Правило «молчаливый отказ запрещён»
            # (PHILOSOPHY §0.5) начинается ровно здесь.
            if _reflex_done:
                out.put({"type": "tool", "name": "⚡ " + _rx_hit[0],
                         "args": str(_reflex_done)[:900]})
    except Exception as e:
        log.debug("рефлекс пропущен: %s", e)
    # ═══ АГЕНТНЫЙ ЦИКЛ (2026-08-14, server/agent.py) ═══
    # Владелец: «за всё время она ни разу не юзала агентности никакой:
    # просто выполняет запрос и всё, останавливается, не завершив даже
    # задание». Регламент в промпте этого не лечит — устройство разговора
    # одноходовое. Цикл живёт ЗДЕСЬ, на сервере, где его не проигнорируешь.
    # Рефлекс уже всё сделал — цикл не поднимаем: он для того, что
    # правилом не решается.
    _agent_note = ""
    if not _reflex_done:
        try:
            from server import agent as _ag
            if _ag.wanted(user_text):
                out.put({"type": "tool", "name": "🧠 берусь за задачу",
                         "args": user_text[:80]})

                def _show(_t, _a, _r):
                    out.put({"type": "tool", "name": "↳ " + _t,
                             "args": str(_r)[:300]})
                _res = _ag.run(user_text, on_step=_show, user_text=user_text)
                _agent_note = _ag.digest(_res)
        except Exception as e:
            log.debug("агентный цикл пропущен: %s", e)
    mem_context = ""
    if not _light:
        try:
            mem_context = memory.build_context(
                person_id, user_text,
                limit_chars=int(CFG.get("memory.context_chars", 3000) or 0))
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
    # БЛОКИ ПРОМПТА (2026-07-26): порядок кусков теперь настройка, а не
    # порядок строк в этом файле. Blocks ведёт себя как обычный список,
    # поэтому все .append ниже работают как раньше — см. prompt_blocks.py.
    from server import prompt_blocks as _pb
    dyn_parts = _pb.Blocks()
    # ЛОРБУК: факты о мире всплывают по упоминанию ключа, а не висят в
    # персоне на каждой фразе. Ставим первым — это справочный контекст.
    try:
        from server import lorebook as _lore
        _hist_txt = [t for _r, t in memory.recent_raw(person_id, limit=6)] \
            if hasattr(memory, "recent_raw") else []
        _lb = _lore.block(user_text, _hist_txt)
        if _lb:
            dyn_parts.add("lore", _lb)
    except Exception as e:
        log.debug("лорбук пропущен: %s", e)
    # ОТКЛИК ВЛАДЕЛЬЦА (2026-07-26). Разбираем ДО генерации: похвала должна
    # успеть попасть в самочувствие, которое уходит в этот же промпт.
    # Привязываем к умению, которым она работала в прошлый ход — иначе
    # «молодец» после запуска программы улучшало бы веру в разговор.
    try:
        from server import psyche as _psy
        _fb = _psy.feedback(user_text, LAST_SKILL.get("name", ""))
        if _fb:
            log.info("Отклик владельца: %s (умение «%s»)", _fb,
                     LAST_SKILL.get("name", "разговор"))
    except Exception as e:
        log.debug("разбор отклика пропущен: %s", e)
    t_lore = time.monotonic()   # лорбук отработал (для разбивки задержки)
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
        # 2026-07-26: та же метка тона теперь красит и ГОЛОС, а не только
        # жест аватара. Раньше Сайка могла показать раздражение телом и
        # произнести это ровным дружелюбным тоном — рассинхрон, который
        # читается как фальшь.
        try:
            from server.tts import manager as _ttsm
            _ttsm.set_emotion(_tone_cls)
        except Exception:
            pass
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
    # БЫСТРЫЙ РЕЖИМ (llm.fast_mode, 2026-07-27). Из всего промпта КАЖДЫЙ ход
    # заново пережёвывается только динамика: системный промпт и история
    # лежат в KV-кэше неизменными, а память/психика/сводка по моделям
    # вставляются перед последней фразой и потому стоят полного prefill'а на
    # каждую реплику. На нашем железе это ~900 токенов = доли секунды, но
    # когда цель «отвечает как в чате LM Studio», доли секунды и остаются
    # единственным, что можно отыграть. Режим не выключает возможности
    # насовсем — он снимает то, что не нужно в конкретной реплике.
    if _escalated:
        dyn_parts.append(
            "### Важно (факт): человек уже НЕ ПЕРВЫЙ раз говорит, что "
            "результата нет. Сейчас ты думаешь усиленной моделью. Не "
            "отписывайся и не переспрашивай по кругу: проверь реальное "
            "состояние инструментами (window_list / apps_list / open_folder), "
            "разберись, что именно не сработало, и добейся результата или "
            "честно объясни, что мешает и какой есть обходной путь.")
    # КТО ПЕРЕД ТОБОЙ (2026-08-13, просьба владельца: «перестала ко мне
    # обращаться в женском роде»). Модель по умолчанию сыпала «ты сказала»,
    # «ты дала», «ты просила» — gemma в русском тянет женские окончания,
    # если пол собеседника не назван прямо. В персоне это есть общими
    # словами, но общее мелкая модель не удерживает: нужен КОРОТКИЙ факт
    # рядом с репликой, каждый ход.
    try:
        _g = str(CFG.get("owner.gender", "m")).lower()
        _nm = str(CFG.get("owner.name", "") or "").strip()
        if _g.startswith("m"):
            dyn_parts.append(
                "### Собеседник (факт): МУЖЧИНА"
                + (f", зовут {_nm}" if _nm else "") + ". Обращайся к нему в "
                "МУЖСКОМ роде: «ты сказал», «ты просил», «ты дал», «сам». "
                "Женские окончания в его адрес — грубая ошибка, он на них "
                "прямо жаловался.")
        elif _g.startswith("f") or _g.startswith("ж"):
            dyn_parts.append(
                "### Собеседник (факт): ЖЕНЩИНА"
                + (f", зовут {_nm}" if _nm else "") + ". Обращайся в женском "
                "роде.")
    except Exception:
        pass
    # ГДЕ Я СЕЙЧАС (2026-08-13, слова владельца: «не в предохранителе дело,
    # а в понимании, что она делает и где» / «она должна понимать и видеть,
    # какое приложение юзает»). До этого блока она действовала вслепую:
    # слала Ctrl+Tab «в браузер», не зная, что впереди десктопное
    # приложение, и переключила человеку чат в чужой программе. Дело было
    # не в отсутствии запрета, а в отсутствии глаз.
    try:
        # САМЫЙ ОПАСНЫЙ КУСОК: список окон через Win32 и заголовок страницы
        # через Playwright. Оба уходят наружу и оба умеют висеть — именно
        # здесь и встали те 67 секунд.
        from server import situation as _sit
        _where = _piece("обстановка", _sit.block, 0.8)
        if _where:
            dyn_parts.append(_where)
    except Exception as e:
        log.debug("обстановка пропущена: %s", e)
    if _agent_note:
        dyn_parts.append(_agent_note)
    # ЧТО Я УМЕЮ И ЧЬИМИ РУКАМИ (2026-08-14, владелец: «она должна не
    # втупую переключать модели, а точно знать, что она может с помощью
    # какой модели делать»). Без этого блока честное «я не вижу»
    # превращается в тупик; с ним — в следующий шаг, потому что она знает,
    # кто видит, и что система подключит его сама.
    try:
        from server.llm import skills as _skl
        _sb = _piece("умения", _skl.block, 0.5)
        if _sb:
            dyn_parts.append(_sb)
    except Exception as e:
        log.debug("блок умений пропущен: %s", e)
    # ГДЕ МЫ СЕЙЧАС СТОИМ В ПАПКАХ И ЧТО ПОКАЗАНО СПИСКОМ (2026-08-14).
    # Без этой строки прогулка теряется между фразами: человек говорит
    # «третий», а она не знает, что минуту назад показала десять путей, —
    # и переспрашивает. Строка короткая нарочно: это ориентир, не отчёт.
    try:
        from server import explorer as _walk
        _wn = _piece("прогулка", _walk.note, 0.4)
        if _wn:
            dyn_parts.append(
                "### Прогулка по компьютеру (факт): " + _wn +
                ". Номер от человека — это pick_number, не переспрашивай.")
    except Exception as e:
        log.debug("прогулка пропущена: %s", e)
    # ЧТО НА СТОЛЕ (2026-08-14, разбор «как понимается контекст»). Идёт
    # ПЕРВЫМ из всех динамических блоков: сперва «о чём вообще речь», и
    # только потом «кто я» и «в каком порядке действовать». Без этого
    # каждая фраза приходила голой, как первая в жизни.
    try:
        from server import focus as _focus
        _focus.note_user(user_text)
        _st = _focus.block()
        if _st:
            dyn_parts.append(_st)
    except Exception as e:
        log.debug("состояние разговора пропущено: %s", e)
    # КОСТЮМ (2026-08-13). Идёт ПЕРЕД регламентом рук: сначала «кто я
    # сейчас», потом «как действую». Пусто, когда костюма нет, — обычный
    # разговор промптом о ролевой игре не засоряется.
    try:
        from server import cards as _cards
        _suit = _piece("костюм", _cards.block, 0.4)
        if _suit:
            dyn_parts.append(_suit)
    except Exception as e:
        log.debug("костюм пропущен: %s", e)
    # РЕГЛАМЕНТ РУК (2026-08-13, разбор WORKFLOW.md). Обстановка отвечает
    # на «где я», а этот блок — на «в каком порядке действовать». Человек
    # проходит цикл цель→место→попасть→посмотреть→сделать→подтвердить→
    # проверить не задумываясь, потому что смотреть на экран ему бесплатно.
    # Модель без явного порядка пропускает «посмотреть» и «проверить» и
    # выдаёт намерение за результат. Кладём ТОЛЬКО под задачу руками и
    # ТОЛЬКО нужный сценарий: полный свод утопил бы мелкую модель.
    try:
        from server import workflow as _wf
        _plan = _wf.block(user_text)
        if _plan:
            dyn_parts.append(_plan)
    except Exception as e:
        log.debug("регламент рук пропущен: %s", e)
    # ЧТО СЛЫШНО ВОКРУГ (2026-08-13, просьба владельца: «давать Сайке
    # понимание за счёт меток от её слуха — но не как прямой запрос, а как
    # то, что она могла бы использовать в контексте диалога»). Поэтому это
    # dyn_parts, а не системный промпт: обстановка меняется каждую минуту и
    # не должна ломать KV-кэш, а формулировка блока прямо снимает с неё
    # обязанность реагировать.
    try:
        _ears = hearing.context_line()
        if _ears:
            dyn_parts.append("### Обстановка вокруг (факт): " + _ears)
    except Exception:
        pass
    if PENDING_ACTIONS:
        _acts = PENDING_ACTIONS[:3]
        del PENDING_ACTIONS[:len(_acts)]
        dyn_parts.append(
            "### Результат твоих действий из прошлой реплики (факт): "
            + "; ".join(f"{n} -> {r}" for n, r in _acts)
            + "\nУчитывай его в ответе; то же самое повторно не вызывай, "
              "если человек прямо не попросил.")
    if _reflex_done:
        dyn_parts.append(
            "### Только что (факт): по этой фразе система УЖЕ выполнила "
            "действие, результат: " + _reflex_done[:300] + "\n"
            "Ничего не вызывай повторно — просто отреагируй одной короткой "
            "фразой, как на уже сделанное тобой.")
    if mem_context:
        if _fast:
            # память режем, а не выбрасываем: без неё Сайка забывает, о чём
            # был разговор час назад, и это заметно сильнее лишних 0.2с
            _lim = int(CFG.get("llm.fast_memory_chars", 700))
            if len(mem_context) > _lim:
                mem_context = mem_context[:_lim].rsplit("\n", 1)[0]
        dyn_parts.append(
            "### Твоя память по теме (используй естественно, не цитируй "
            "дословно):\n" + mem_context)
    # ЗАМЕТКИ АВТОРА (2026-07-26): скрытая инструкция «что делаем сейчас».
    # Персона отвечает на вопрос «кто она» и меняется редко; заметки — на
    # «какой сейчас режим» и меняются каждый день. Смешивать их в persona.py
    # значит каждый раз лезть в характер ради разовой правки поведения.
    # САМОЧУВСТВИЕ И ВЕРА В СЕБЯ (2026-07-26). Настроение по PAD и
    # самооценка по умениям — см. server/psyche.py. Здесь же правило трёх
    # попыток: не долбиться в одно и то же, а честно позвать на помощь.
    try:
        from server import psyche as _psy
        _pb = _psy.block() if not _fast else ""
        if _pb:
            dyn_parts.add("psyche", _pb)
    except Exception as e:
        log.debug("самочувствие пропущено: %s", e)
    # СВОДКА ПРО СВОИ ЖЕ МОЗГИ (2026-07-26). Просьба владельца: «нужны
    # краткие сводки по возможностям для самой Сайки». Без этого просьба
    # «возьми модель поумнее» упирается в то, что она про свой арсенал
    # ничего не знает — и отвечает «не могу». Здесь же правило про деньги.
    # КАРТОЧКИ ИНСТРУМЕНТОВ ПО ФРАЗЕ (2026-07-28): фраза похожа на просьбу
    # что-то сделать — подкладываем 1-3 инструкции, как это вызвать. Работает
    # для ЛЮБОЙ модели: умеет tool_calls — зовёт функцию, не умеет — пишет
    # текстовый маркер, сервер исполнит (текст-протокол выше).
    try:
        from server.llm import tools as _tuc
        _cards = _tuc.usage_cards(user_text)
        if _cards:
            dyn_parts.add("tools", _cards)
        # УКАЗАТЕЛЬ НА ОСТАЛЬНЫЕ (2026-08-15): схемы теперь едут не все, и
        # без этой строки модель считала бы, что умеет только присланное —
        # то есть «не могу» на ровном месте. Имена стоят копейки, а вызвать
        # по маркеру можно любой: сервер ловит маркеры сам.
        _idx = _tuc.names_index(_tuc.schemas_for(user_text))
        if _idx:
            dyn_parts.add("tools", _idx)
    except Exception as e:
        log.debug("карточки инструментов пропущены: %s", e)
    # КТО ЭТО УМЕЕТ (2026-08-15). Модель судит о своих возможностях по
    # обучению, а не по этому компьютеру: GigaChat совершенно искренне
    # уверен, что зрения у него нет. Поэтому решает не она, а система —
    # и прямо говорит ей, чем задача делается и чьими силами.
    try:
        from server import routing as _rt
        _rtb = _rt.block(user_text)
        if _rtb:
            dyn_parts.add("models", _rtb)
    except Exception as e:
        log.debug("маршрут умений пропущен: %s", e)
    # ЧТО В РУКАХ ПРЯМО СЕЙЧАС. Блок короткий и живёт пять минут, но
    # именно он превращает «Извини, я не поняла» в ответ по существу,
    # когда человек уточняет предыдущий ход одним словом.
    try:
        from server import toolbuf as _tb
        _tbb = _tb.block()
        if _tbb:
            dyn_parts.add("tools", _tbb)
    except Exception as e:
        log.debug("буфер инструментов пропущен: %s", e)
    try:
        if _is_perf_query(user_text):
            _pfb = _perf_block()
            if _pfb:
                dyn_parts.append(_pfb)
    except Exception as e:
        log.debug("телеметрия пропущена: %s", e)
    try:
        from server import model_dossier as _dos
        # сводка про свой арсенал нужна на вопросы «возьми модель поумнее»,
        # а не на «как дела» — в быстром режиме её подкладывает только
        # разговор по теме
        _dg = _dos.digest() if not (_fast and not _is_model_query(user_text)) \
            else ""
        if _dg:
            dyn_parts.add("models", _dg)
    except Exception as e:
        log.debug("сводка по моделям пропущена: %s", e)
    _notes = (CFG.get("persona.author_notes", "") or "").strip()
    if _notes:
        dyn_parts.add("notes",
            "### Указание от владельца на СЕЙЧАС (выполняй, но НЕ упоминай "
            "и не цитируй — для человека это невидимая заметка, а не "
            "сообщение):\n" + _notes[:2000])
    # ЗРЕНИЕ (2026-07-25): человек попросил посмотреть — сервер сам делает
    # кадр и кладёт его в ЭТОТ ЖЕ запрос как обычную картинку. Почему так,
    # а не инструментом look_screen: работает с ЛЮБОЙ моделью, включая те,
    # что не умеют tool-calls (у нас таких большинство, см. llm.tools_broken).
    # Предохранители (тумблер 👁, чёрный список окон, намерение) — в vision.py.
    _looked = False
    # Внутренний импульс зрения уже несёт кадр и говорит про экран — если
    # прогнать его текст через auto_look, она схватит ВТОРОЙ кадр на ровном
    # месте. Метка ставится в _vision_watch_cb.
    if image is None and "[[vision-impulse]]" not in (user_text or ""):
        try:
            from server import capabilities as _caps_v
            from server import vision as _vis
            _url, _note = _vis.auto_look(user_text)
            if _url:
                VISION_USED["ts"] = time.time()
            if _url and _caps_v.vision(CFG.get("llm.model", "")) is False:
                # за рулём слепая болтушка — одалживаем глаза у vision-модели
                # парка (тот же приём, что для OCR присланных картинок ниже)
                out.put({"type": "tool", "name": "зрение",
                         "args": "смотрю чужими глазами"})
                _desc = _vis._describe(_url, "Опиши подробно, что на кадре: "
                                             "что происходит, что открыто, "
                                             "что бросается в глаза.")
                _url = None
                _note = (("### Ты посмотрела своими глазами, но твоя текущая "
                          "модель БЕЗ зрения — кадр разобрала vision-модель "
                          "из парка. Вот что на нём:\n" + _desc[:3000] +
                          "\n\nГовори так, будто видела сама, своими "
                          "словами. Не выдумывай того, чего в описании нет.")
                         if _desc else
                         "### Ты пыталась посмотреть, но разобрать кадр "
                         "некому: ни текущая модель, ни одна модель в парке "
                         "не умеет смотреть на картинки. Скажи честно.")
            if _note:
                dyn_parts.append(_note)
            if _url:
                image, _looked = _url, True
        except Exception as e:
            log.debug("зрение пропущено: %s", e)
    # Зрение — самый дорогой из «невидимых» этапов: кадр экрана, dHash,
    # иногда ещё и чужая vision-модель. Меряем отдельно, иначе его секунды
    # растворяются в общем «промпт» и выглядят как медленная LLM.
    t_vis = time.monotonic()
    if image and not _looked:
        LAST_IMAGE["data"], LAST_IMAGE["ts"] = image, time.time()
        from server import capabilities as caps
        if caps.vision(CFG.get("llm.model", "")) is False:
            # СЛЕПАЯ МОДЕЛЬ — НЕ ПОВОД ПЕРЕСПРАШИВАТЬ (2026-08-14, владелец:
            # «если какая-то модель не имеет возможности видеть, она должна
            # знать это о моделях и ПАРАЛЛЕЛЬНО запустить модель, которая
            # даст ей инфу о картинке»).
            #
            # Знание уже есть: capabilities.vision() честно отвечает, кто
            # умеет смотреть. И механика заимствования глаз тоже написана —
            # ровно этим занимается auto_look для кадров экрана. Не хватало
            # одного: здесь, на присланной картинке, она вместо дела
            # спрашивала «вытащить из неё текст?» и ждала «да». Человек
            # уже прислал картинку — это и есть его «да».
            #
            # Берём чужие глаза сразу и молча. Не вышло — тогда честное «не
            # вижу», но это запасной путь, а не первый.
            _seen = ""
            try:
                from server import vision as _vis2
                _seen = _piece(
                    "чужие глаза",
                    lambda: _vis2._describe(
                        image, "Опиши подробно, что на картинке: что "
                               "изображено, какой текст виден, что "
                               "бросается в глаза."),
                    float(CFG.get("vision.borrow_budget_s", 12.0))) or ""
            except Exception as _e:
                log.debug("чужие глаза не сложились: %s", _e)
            if _seen:
                out.put({"type": "tool", "name": "зрение",
                         "args": "картинку разобрала vision-модель парка"})
                dyn_parts.append(
                    "### Пользователь прислал КАРТИНКУ. Твоя модель без "
                    "зрения, поэтому кадр разобрала vision-модель из парка "
                    "— вот что на нём:\n" + _seen[:3000] +
                    "\n\nГовори так, будто видела сама, своими словами. "
                    "Не выдумывай того, чего в описании нет, и НЕ "
                    "спрашивай разрешения посмотреть — ты уже посмотрела.")
            else:
                dyn_parts.append(
                    "### Пользователь прислал КАРТИНКУ, но разобрать её "
                    "некому: твоя модель без зрения, и ни одна модель в "
                    "парке сейчас не смотрит. Скажи честно и коротко. "
                    "СТРОГО запрещено выдумывать содержимое.")
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
        # 2026-07-25: этот путь ходит в браузер МИМО tools.call(), поэтому
        # предохранитель импульса надо проверять здесь отдельно — иначе он
        # на внутреннюю мысль открывает окно и лезет в интернет.
        from server.llm import tools as _tls_guard
        if _tls_guard.IMPULSE_MODE.get("on"):
            _search_intent = False
    except Exception:
        pass
    # «НАЙДИ» ПРО ДИСК — НЕ ПОВОД ЛЕЗТЬ В ИНТЕРНЕТ (2026-08-14). Этот путь
    # ходит в браузер МИМО tools.call, значит и мимо предохранителя, который
    # уже стоит там (_intent_ok). В живом логе владельца из-за этого
    # трижды подряд открывался браузер: «зайди, найди мне игры на диске»,
    # «открой проводник, найди музыку», «короче, найди здесь игры» — и
    # каждый раз «нахер ты гуглишь». Проверку держим ровно ту же, чтобы
    # два пути не расходились в поведении.
    if _search_intent:
        try:
            from server.llm import tools as _tls_web
            _tls_web.LAST_USER["text"] = user_text
            if not _tls_web._intent_ok("web_research"):
                _search_intent = False
        except Exception as e:
            log.debug("проверка «диск или сеть» пропущена: %s", e)
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
        # в быстром режиме доска подкладывается только на разговор о ней
        board = ("" if (_fast and not _is_dev_query(user_text))
                 else devboard.summary_for_llm())
        if board:
            # НЕ в system! (2026-07-27, найдено по логу llama-server).
            # Дев-доска меняется каждый раз, когда мы что-то делаем, а лежала
            # она ВНУТРИ системного промпта — то есть в самом начале, в той
            # части, которая обязана быть неизменной. Любая правка доски
            # рушила KV-кэш прямо посреди системного промпта, и движок
            # пересчитывал ВСЁ, что идёт после неё. В логе llama-server это
            # видно прямым текстом: «prompt eval 4172 tokens» на каждую
            # реплику при промпте 6152 — переиспользовалось меньше трети.
            # Место доски — среди блоков динамики, в конце, где для неё уже
            # заведено имя "devboard" (см. prompt_blocks.DEFAULT_ORDER).
            dyn_parts.add("devboard",
                "### Твоя история разработки (дев-доска, факт): " + board +
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
                "- НЕ РАССКАЗЫВАЙ ПРО СВОЁ УСТРОЙСТВО. Вопрос «что на "
                "экране» — про экран, а не про то, какая модель отвечает, "
                "есть ли у неё зрение и через какой инструмент ты смотришь. "
                "Отвечай на заданный вопрос и молчи про внутренности, пока "
                "не спросили именно о них.\n"
                "- Никогда не говори, что у тебя нет ЗРЕНИЯ. Глаза у тебя "
                "есть: look_screen снимает кадр экрана и описывает его, "
                "look_camera — то же с вебкой. Если тумблер глаз выключен, "
                "он включится сам по просьбе. Фраза «я не могу видеть "
                "содержимое экрана» — ложь, за неё человек справедливо "
                "ругается.\n"
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
    # ОКНО БЕРЁМ У ТОГО, КТО ЕГО ДЕРЖИТ (2026-07-27). Раньше бюджет считался
    # от n_ctx НАШЕГО воркера — числа из config, к LM Studio отношения не
    # имеющего. Замер вскрыл, чем это кончается: модель была поднята с окном
    # 4096, Сайка строила промпт на ~10к токенов, LM Studio молча резала
    # начало (в usage стабильные prompt_tokens ≈ 4049 при растущем промпте).
    # Итог: терялся системный промпт и половина истории — молча, без единой
    # жалобы, — и KV-кэш не мог сработать, потому что окно сдвигалось каждый
    # ход. Спрашиваем настоящее окно у бэкенда; не ответил — остаёмся на
    # прежнем поведении.
    try:
        _real_ctx = llm.loaded_context_tokens(CFG.get("llm.backend", ""),
                                              CFG.get("llm.model", ""))
        if _real_ctx:
            if _real_ctx < n_ctx:
                log.info("Окно контекста у бэкенда %s токенов (в config было "
                         "%s) — считаю бюджет по реальному", _real_ctx, n_ctx)
            n_ctx = _real_ctx
    except Exception:
        log.debug("окно контекста не спросилось", exc_info=True)
    CHARS_PER_TOKEN = 1.5                      # воркер всё равно подрежет точно; тут просто ориентир
    ANSWER_RESERVE_TOKENS = 1500               # место под сам ответ
    budget = int((n_ctx - ANSWER_RESERVE_TOKENS) * CHARS_PER_TOKEN)
    # кто именно ограничил бюджет — чтобы предупреждение называло настоящего
    # виновника, а не советовало поднять то, что уже поднято (2026-07-29:
    # окно выросло до 32768, а бюджет так и стоял 24000 — его держал ручной
    # потолок llm.context_chars из config.json, о котором совет молчал)
    budget_src = "окно движка"
    cfg_budget = CFG.get("llm.context_chars")  # ручной потолок, если задан
    if cfg_budget and int(cfg_budget) < budget:
        budget = int(cfg_budget)
        budget_src = "ручной потолок llm.context_chars=%s в config.json" \
                     % cfg_budget
    # быстрый режим: короче история — реже сдвигается якорь, а значит реже
    # случается «одна полная пережёвка промпта» на ровном месте
    if CFG.get("llm.fast_mode", False):
        budget = min(budget, int(CFG.get("llm.fast_context_chars", 12000)))
    # ОБЛАКО: бюджет истории считался от окна ЛОКАЛЬНОГО движка (32k → ~47к
    # символов) — и вся эта простыня улетала в API на каждую фразу. У облака
    # нет нашего тёплого KV-кэша: провайдер пережёвывает промпт целиком,
    # kimi-k3 на 30к символов давал prefill 16-25с. Режем до вменяемого
    # (llm.cloud.context_chars, дефолт 9000 ≈ 6к токенов) — длинную память
    # всё равно держит RAG, а не хвост чата.
    if CFG.get("llm.backend") == "cloud" or _route == "cloud":
        # ПОТОЛОК ПО МОДЕЛИ, А НЕ ОДИН НА ВСЕХ (2026-08-15). 9000 символов
        # выбирались под kimi-k3, который жевал 30к по 16-25 секунд. Но
        # владелец сидит на GigaChat-2-Pro со 128 тысячами токенов окна и
        # СВОИМ префикс-кэшем (в ответах видно precached_prompt_tokens) —
        # для него этот потолок означал «помню три реплики» на ровном
        # месте. Просьба владельца дословно: «я хочу чтобы она могла за
        # весь день болтовню держать от десятков людей… а ближайшие 4 часа
        # более хорошо в подробностях». Даём столько, сколько модель
        # честно держит, но не больше разумного (платим-то за токены).
        _cap = int(CFG.get("llm.cloud.context_chars", 9000))
        try:
            from server.llm import brains as _br
            _win = _br.window_chars_of(CFG.get("llm.model", ""))
            if _win:
                # 70% окна — остальное системе провайдера, инструментам и
                # самому ответу. Занять окно целиком = получить молчаливую
                # подрезку начала промпта, ту же, на которой уже горели с
                # LM Studio.
                _cap = max(_cap, min(int(_win * 0.7), int(CFG.get(
                    "llm.cloud.context_chars_max", 40000))))
        except Exception:
            pass
        budget = min(budget, _cap)
    # размер схем инструментов (шаблон впишет их в промпт помимо system)
    tools_chars = 0
    try:
        if CFG.get("llm.model") not in set(CFG.get("llm.tools_broken", [])):
            from server.llm import tools as _hp
            import json as _json
            # СЧИТАЕМ ТО, ЧТО РЕАЛЬНО УЕДЕТ (2026-08-15): менеджер шлёт
            # подмножество схем под фразу, а бюджет вычитал полный набор —
            # и сам же душил историю тем, чего в запросе нет.
            tools_chars = len(_json.dumps(_hp.schemas_for(user_text),
                                          ensure_ascii=False))
    except Exception:
        pass
    # паспорт модели: если пробы выяснили молчаливое переполнение окна —
    # ужимаем до замеренного рабочего бюджета
    try:
        # ПАСПОРТНЫЙ ПОТОЛОК — НЕ ДЛЯ СВОЕГО ДВИЖКА (2026-07-28). Паспорт
        # однажды намерил «модель молчит на большом промпте» и записал
        # context_chars=24000 — но мерил он это при СТАРОМ окне 24576.
        # Окно выросло до 32768, а протухший потолок продолжал душить
        # бюджет, и история снова резалась до полутора тысяч символов.
        # «Молчание на большом промпте» — болезнь LM Studio с его тихой
        # подрезкой; наш llama-server стартует с явным --ctx-size, и его
        # окну можно верить. Для остальных бэкендов потолок остаётся.
        if CFG.get("llm.backend") != "llamacpp":
            from server.llm import passport as _passport
            _pc = _passport.context_chars_for(CFG.get("llm.model", ""))
            if _pc and _pc < budget:
                budget = _pc
    except Exception:
        pass
    hist_budget = max(1500, budget - len(system) - tools_chars)
    # ОКНО МЕНЬШЕ, ЧЕМ САМ ПРОМПТ — говорить об этом ГРОМКО (2026-07-27).
    # Молчаливая подрезка на стороне LM Studio выглядит не как поломка, а как
    # «Сайка поглупела и тормозит»: она не помнит начала разговора, теряет
    # системный промпт и каждый ход платит полным prefill. Ни одного признака
    # в интерфейсе при этом нет — поэтому пишем прямым текстом, что чинить.
    if budget - tools_chars < len(system) * 1.2:
        if budget_src != "окно движка":
            cure = ("бюджет держит %s — подними его до 45000 или убери "
                    "совсем (правится при ОСТАНОВЛЕННОЙ Сайке)" % budget_src)
        elif CFG.get("llm.backend") == "llamacpp":
            cure = ("подними llamacpp.n_ctx в config.json (сейчас %s) — "
                    "правится при ОСТАНОВЛЕННОЙ Сайке, движок стартует с "
                    "новым окном сам"
                    % (CFG.get("llamacpp", {}) or {}).get("n_ctx", "?"))
        elif CFG.get("llm.backend") == "cloud":
            # СОВЕТ ПРО LM STUDIO ОБЛАЧНОЙ МОДЕЛИ — ЭТО МУСОР (2026-08-14,
            # живой лог: отвечает llama-3.3-70b в Cloudflare, а Сайка
            # каждый ход советует «подними Context Length в LM Studio».
            # У облака окно чужое и не правится; там жмут инструменты —
            # 36 тысяч символов схем в КАЖДОМ запросе. Это и лечим.)
            cure = ("модель облачная — её окно не правится. Жмут схемы "
                    "инструментов (%d симв в каждом запросе): выключи "
                    "лишние в настройках инструментов или возьми модель "
                    "с окном побольше" % tools_chars)
        else:
            cure = ("подними Context Length у модели в LM Studio и "
                    "перезагрузи её")
        log.warning(
            "Окно контекста мало: под систему нужно ~%d симв + инструменты "
            "%d, а всего бюджета %d (окно %s токенов). Модель молча режет "
            "начало промпта — Сайка теряет память и каждый ход платит полным "
            "prefill. Лечение: %s",
            len(system), tools_chars, budget, n_ctx, cure)
        # И В ИНТЕРФЕЙС, А НЕ ТОЛЬКО В ЛОГ (2026-07-28, владелец: «чё Беймакс
        # спит и не чинит?»). Предупреждение жило в консоли, которую никто не
        # обязан читать, а снаружи выглядело как «Сайка поглупела и странно
        # разговаривает»: истории ей доставалось полторы тысячи символов —
        # три реплики. Теперь Беймакс говорит об этом сам, один раз за
        # запуск: чинится это не на лету, а перезапуском с большим окном.
        if not CTX_WARN["sent"]:
            CTX_WARN["sent"] = True
            report_problem(
                "контекст",
                "окно %s токенов, а системный промпт с инструментами съедают "
                "его почти целиком — на разговор остаётся ~%d символов, "
                "поэтому она забывает нить и отвечает странно"
                % (n_ctx, max(1500, budget - len(system) - tools_chars)),
                cure)
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
        _body = (dyn_parts.render() if hasattr(dyn_parts, "render")
                 else "\n\n".join(dyn_parts))
        log.debug("Блоки промпта: %s", dyn_parts.report()
                  if hasattr(dyn_parts, "report") else "?")
        dyn_msg = {"role": "system", "content": _body}
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
    # момент, когда в UI ушёл ПЕРВЫЙ кусок звука. Человек воспринимает
    # задержку именно так — не по первому токену текста, а по первому звуку
    t_sound = {"ts": None}

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
            sentence = _strip_tool_marks(sentence)  # [open_folder:...] не читаем
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
                        # СВОЙ ГОЛОС В ПРОСТРАНСТВО ГОЛОСОВ (2026-07-28).
                        # Тот же кусок звука уходит в отпечаток — ДО колонок,
                        # чистым. Так у неё появляется собственная метка, а
                        # эхо из микрофона перестаёт быть «незнакомцем»:
                        # видно, что это она сама. feed_self только кладёт в
                        # очередь, озвучка на этом не теряет ни миллисекунды.
                        voiceprint.feed_self(_a, sr)
                        # покачивание головой при речи считает сам веб-аватар
                        # по реальному звуку (BroadcastChannel из index.html);
                        # серверный канал в чужую прогу (VMC) удалён 2026-07-25
                    except Exception:
                        pass
                    if t_sound["ts"] is None:
                        t_sound["ts"] = time.monotonic()
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
        # РОД — МЕХАНИЧЕСКИ, НА ВЫХОДЕ (2026-08-15). «Ну ты скажи: поняла
        # или понял?» — «Понял.» Промптом это не лечится: «понял» самая
        # частая короткая реплика русского корпуса, она вылетает раньше,
        # чем модель доберётся до инструкций о характере, а у Сайки
        # половина ответов ровно такой длины. Правим здесь, где проходят
        # ВСЕ реплики — и стрим, и повтор, и хвост. См. server/gender.py.
        try:
            from server import gender as _gnd
            sentence = _gnd.feminize(sentence)
        except Exception:
            pass
        if sentence:
            remember_said(sentence)   # чтобы узнать себя в эхе из колонок
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

        _tool_used = {"any": False, "names": set()}

        def on_tool(name, args):
            _tool_used["any"] = True
            _tool_used["names"].add(str(name))
            try:
                from server import psyche as _psy
                LAST_SKILL["name"] = _psy.skill_of(name)
            except Exception:
                pass
            out.put({"type": "tool", "name": name,
                     "args": json.dumps(args, ensure_ascii=False)[:600]})

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
        _prefer = None
        # эскалация без облака: берём модель покрупнее из парка. Бэкенд
        # ищем в списке моделей — одного имени llm.chat_stream мало.
        if _prefer_local:
            try:
                for _m in llm.list_models():
                    if _m["name"] == _prefer_local and _m["backend"] != "cloud":
                        _prefer = (_m["backend"], _m["name"])
                        break
            except Exception as e:
                log.debug("не нашла бэкенд для %s: %s", _prefer_local, e)
        if _route == "cloud":
            _c = CFG.get("llm.cloud", {}) or {}
            if _c.get("model"):
                _prefer = ("cloud", _c["model"])
        # ступень лестницы важнее общего маршрута: она названа поимённо
        if _prefer_brain:
            _prefer = _prefer_brain
        for token in llm.chat_stream(messages, prefer=_prefer,
                                     on_fallback=on_fallback,
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
            # ЧЕРНОВИК НЕ СТРИМИМ (2026-08-14): «Задача: … План действий:»
            # доезжало до человека живьём, буква за буквой, и вырезать это
            # постфактум уже поздно — он уже прочитал и услышал.
            # ФИГУРНАЯ СКОБКА В НАЧАЛЕ — УЖЕ ПРИГОВОР (2026-08-14, живой
            # лог: в чат уехало «{"type": "function» и на этом оборвалось).
            # Придержка тут была, но искала ЦЕЛЫЕ образцы: «"type":
            # "function"» с закрывающей кавычкой. А поток идёт по буквам —
            # в момент показа кавычки ещё нет, образец не совпал, и кусок
            # ушёл человеку живьём. Вырезать постфактум поздно: он уже
            # прочитал и услышал.
            #
            # Ответ Сайки НИКОГДА не начинается с «{» или «[». Значит одной
            # первой скобки достаточно, чтобы придержать до конца: если это
            # окажется настоящий текст, он покажется целиком чуть позже;
            # если вызов — его исполнят и человек увидит результат, а не
            # обрубок разметки.
            if re.match(r'\s*[{\[]', sentence_buf) \
                    or _THINK_HEAD.match(sentence_buf) or _THINK_LINE.search(sentence_buf) \
                    or "<|" in sentence_buf or "call:" in sentence_buf \
                    or re.search(r'"(?:name|type|parameters|arguments)"\s*:',
                                 sentence_buf) \
                    or re.search(r'"type"\s*:\s*"func', sentence_buf) \
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
        # ЛОВИМ ПО ПОЛЮ "name", А НЕ ПО НАЧАЛУ СКОБКИ (2026-08-14, живой
        # случай: на «Привет» прилетело {"type": "function", "name":
        # "avatar_action", ...} и уехало человеку в чат сырьём. Старое
        # условие искало `{"name":` — то есть скобку ВПЛОТНУЮ к полю, а тут
        # перед ним стоит "type". Формат тот же, детектор мимо.)
        _bare_calls = _bare_tool_calls(_raw)
        _has_pseudo = ("<|" in _raw or "call:" in _raw
                       or re.search(r'"name"\s*:\s*"[a-z_]+"', _raw)
                       or re.search(r'"type"\s*:\s*"function"', _raw)
                       or re.search(r'"(?:parameters|arguments)"\s*:', _raw)
                       or re.search(r'\bto=[a-z_]+', _raw)
                       or _bare_calls
                       or _harmony_m)
        if _has_pseudo:
            # сырьё в лог: если экстрактор снова что-то не поймёт (новый
            # формат очередной модели) — будет видно, ЧТО именно пришло
            log.info("Псевдо-вызов сырьём: %r", _raw[:400])
            _names = re.findall(r'(?:call:|"name"\s*:\s*")([a-z_]+)',
                                _raw, re.I)
            _names += [n for n, _a in _bare_calls if n not in _names]
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
            if acted is None:
                # ЛЮБОЙ ИНСТРУМЕНТ, А НЕ ПЯТЬ ИЗБРАННЫХ (2026-08-13).
                # Раньше здесь стоял белый список, и «закрой блендер» через
                # такую модель просто исчезало: вызов вырезан, действие не
                # сделано, человеку сказано «Секунду, разберусь». Теперь
                # исполняем всё, что система знает — через штатный
                # tools.call, то есть с доверием и предохранителем намерения.
                try:
                    from server.llm import tools as _handspc
                    _known = {sc["function"]["name"]
                              for sc in _handspc.schemas()}
                    for _n, _a in (_text_tool_calls(_raw) or _bare_calls):
                        if _n not in _known:
                            continue
                        _handspc.LAST_USER["text"] = user_text
                        # args СТРОКОЙ: в интерфейсе объект печатался как
                        # «[object Object]» и человек не видел, с чем
                        # вызвано (2026-08-14, живой лог)
                        out.put({"type": "tool", "name": _n,
                                 "args": json.dumps(_a, ensure_ascii=False)})
                        _res = str(_handspc.call(_n, _a) or "")
                        log.info("Текстовый вызов исполнен: %s(%s) -> %s",
                                 _n, _a, _res[:120])
                        acted = f"{_n} исполнен по-настоящему"
                        # словами о результате — её же голосом, коротко
                        try:
                            _said = llm.chat_once([
                                {"role": "system", "content":
                                 "Ты голосовой ассистент. Одной короткой "
                                 "фразой скажи человеку, что получилось — "
                                 "своими словами, без markdown. Если в "
                                 "результате отказ или ошибка, скажи об "
                                 "этом честно и назови причину."},
                                {"role": "user", "content":
                                 f"Ты вызвала {_n}. Результат:\n{_res[:1200]}"}
                            ], max_len=400).strip()
                            if _said:
                                clean = _said
                        except Exception:
                            clean = _res[:400] or clean
                        break        # один вызов за ход, дальше — новый ход
                except Exception as e:
                    log.warning("текстовый вызов не исполнился: %s", e)
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

        _cur = used_llm.get("model") or CFG.get("llm.model", "")
        if n_tokens > 0:
            _TOOLS_EMPTY.pop(_cur, None)   # заговорила — счётчик обнуляем
        if n_tokens == 0 and not stop_event.is_set() and not looped:
            # Модель потратила все раунды на инструменты и не сказала НИ
            # СЛОВА (или ответ пустой) — молчать нельзя: повторяем один раз
            # БЕЗ инструментов, чтобы она хотя бы ответила словами
            log.info("Пустой ответ (0 токенов) — повторяю без инструментов")
            # Ни слова И НИ ОДНОГО вызова инструмента — значит модель
            # ломается от самого факта, что ей дали tools (а не «потратила
            # раунды на вызовы»). Считаем промахи: повторится — выключим ей
            # инструменты навсегда, и следующий ход пойдёт ОДНИМ запросом.
            if _cur and not _tool_used["any"] \
                    and _cur not in set(CFG.get("llm.tools_broken", [])):
                _TOOLS_EMPTY[_cur] = _TOOLS_EMPTY.get(_cur, 0) + 1
                if _TOOLS_EMPTY[_cur] >= _TOOLS_EMPTY_LIMIT:
                    CFG.set("llm.tools_broken", sorted(set(
                        CFG.get("llm.tools_broken", []) + [_cur])))
                    _TOOLS_EMPTY.pop(_cur, None)
                    log.warning(
                        "Модель %s молчит, когда ей дают инструменты (%d раза "
                        "подряд) — выключаю ей инструменты навсегда. Это "
                        "убирает второй запрос на каждый ход: было два "
                        "полных prefill, станет один.",
                        _cur, _TOOLS_EMPTY_LIMIT)
                    report_problem(
                        "llm", f"{_cur} не умеет инструменты — молчала на "
                        "каждый запрос с ними",
                        "выключила ей инструменты; ответы станут вдвое "
                        "быстрее, поиск и руки возьмёт на себя сервер")
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
        # ПРОГРЕВ СЛЕДУЮЩЕГО ХОДА: пока человек читает ответ, движок в фоне
        # укладывает в KV-кэш весь диалог вместе с этим ответом — следующая
        # фраза доплачивает prefill только за себя (см. llm.prewarm_next)
        if full_reply and not stop_event.is_set():
            _rt = "".join(full_reply)
            threading.Thread(target=llm.prewarm_next,
                             args=(messages, _rt), daemon=True).start()
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
            LAST_STATS.clear()
            LAST_STATS.update(stats, ts=time.time())
            # Разбивка задержки по этапам — по ней видно, кто съел секунды:
            # «очередь» — от распознавания до старта пайплайна;
            # «память» — Chroma/SQLite RAG; «промпт» — дев-доска/инструменты;
            # «prefill» — LM Studio/Ollama пережёвывает контекст до 1-го токена
            try:
                _ms = lambda a, b: max(0, round((b - a) * 1000))
                # Разбивку шлём и в лог, и В ИНТЕРФЕЙС. Раньше она была
                # только в логе — чтобы понять, куда ушли секунды, надо было
                # лезть в файл; на практике этого никто не делает, и
                # «медленно» списывалось на LLM даже когда виновата была
                # память или кадр экрана.
                stg = {"mem": _ms(t0, t_mem), "lore": _ms(t_mem, t_lore),
                       "vision": _ms(t_lore, t_vis),
                       "prompt": _ms(t_vis, t_req),
                       "prefill": _ms(t_req, t_first)}
                if heard_ts is not None:
                    stg["queue"] = _ms(heard_ts, t0)
                if t_sound["ts"] is not None:
                    stg["sound"] = _ms(t_first, t_sound["ts"])
                stats["stages"] = stg
                # размер промпта — без него «prefill 2.3с» нечем мерить:
                # то ли контекст огромный, то ли кэш не сработал
                _pch = sum(len(str(m.get("content", ""))) for m in messages)
                LAST_TIMING.clear()
                LAST_TIMING.update(stg)
                LAST_TIMING["prompt_chars"] = _pch
                LAST_TIMING["messages"] = len(messages)
                # СКОЛЬКО ПРОМПТА ВЗЯЛОСЬ ИЗ КЭША (2026-07-27, замена хэшу).
                # KV-кэш живёт ровно до первого расхождения с прошлым
                # запросом, поэтому единственное честное число — ДЛИНА ОБЩЕГО
                # ПРЕФИКСА с прошлым промптом. Было: хэш «стабильной части»
                # (messages[:-3]) — но она растёт на два сообщения каждый ход,
                # хэш менялся всегда и не значил ничего. Теперь в логе прямо
                # написано «кэш 92%» или «кэш 4%» — и сразу видно, кэш ли
                # виноват в prefill'е или промпт просто большой.
                import hashlib as _hl
                _h = lambda t: _hl.md5(t.encode("utf-8", "ignore")
                                       ).hexdigest()[:8]
                _flat = "\n".join(str(m.get("role", "")) + ":" +
                                  str(m.get("content", "")) for m in messages)
                _prev = LAST_PROMPT["text"]
                _common = 0
                if _prev:
                    _lim = min(len(_prev), len(_flat))
                    while _common < _lim and _prev[_common] == _flat[_common]:
                        _common += 1
                LAST_PROMPT["text"] = _flat
                _hit = round(100 * _common / max(1, len(_flat)))
                LAST_TIMING["cache_hit_pct"] = _hit
                # _body существует только если блоки были — считаем заново
                _dyn_ch = sum(len(t) for t in dyn_parts) if dyn_parts else 0
                _hist_ch = _pch - len(system) - _dyn_ch
                log.info("Отпечаток промпта: система %s (%d симв) | добавки "
                         "%s | история %d симв | совпало с прошлым ходом "
                         "%d%% (%d из %d симв — столько может взяться из "
                         "KV-кэша)",
                         _h(system), len(system),
                         dyn_parts.sizes() if hasattr(dyn_parts, "sizes")
                         else "?", max(0, _hist_ch), _hit, _common, len(_flat))
                log.info(
                    "Тайминги ответа: очередь %sмс | память %dмс | лор %dмс "
                    "| зрение %dмс | промпт %dмс | LLM prefill %dмс | "
                    "до 1-го звука +%sмс | итого до 1-го токена %sмс "
                    "| промпт %d симв в %d сообщ. (~%d токенов)",
                    stg.get("queue", "-"), stg["mem"], stg["lore"],
                    stg["vision"], stg["prompt"], stg["prefill"],
                    stg.get("sound", "-"), stats.get("latency_ms", "-"),
                    _pch, len(messages), _pch // 3)
            except Exception:
                log.debug("разбивка таймингов не собралась", exc_info=True)
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
            # ЗАДЕРЖКА В ЛЕСТНИЦУ МОЗГОВ (2026-08-13): «3-ка бывает на 30
            # секунд отвечает». Копим время до первого токена по каждому
            # мозгу — медленный спустится на ступень сам, без правки кода.
            try:
                from server.llm import brains as _br
                _ms = stats.get("latency_ms")
                if _ms:
                    _br.note_latency(used_llm.get("backend")
                                     or CFG.get("llm.backend", ""),
                                     used_llm.get("model")
                                     or CFG.get("llm.model", ""),
                                     float(_ms) / 1000.0)
            except Exception:
                pass

    # ТРИ ПОПЫТКИ (2026-07-26). Считаем подходы к одной цели: провалился ли
    # инструмент ИМЕННО в этом ходу — видно по отметке времени, не таща
    # флаг через пять слоёв. На третьем провале Сайка получит в промпт
    # прямое указание остановиться и позвать владельца.
    try:
        from server import psyche as _psy
        _failed_now = _psy.LAST_FAIL_TS > 0 and (
            time.time() - _psy.LAST_FAIL_TS) < (time.time() - t0 + 1)
        _st = _psy.attempt(user_text, bool(_failed_now))
        if _st.get("give_up"):
            log.info("Три неудачи подряд по «%s» — прошу помощи у владельца",
                     (user_text or "")[:50])
    except Exception as e:
        log.debug("счётчик попыток пропущен: %s", e)

    # ДОСЬЕ МОДЕЛИ (2026-07-26). Владелец: «она часто ошибалась или наоборот
    # не делала под видом что сделала». Ловим это ровно здесь, где видно и
    # ответ, и был ли вызов инструмента: реплика в прошедшем времени про
    # физическое действие без единого вызова = приписала себе чужую работу.
    try:
        if _is_perf_query(user_text):
            _pfb = _perf_block()
            if _pfb:
                dyn_parts.append(_pfb)
    except Exception as e:
        log.debug("телеметрия пропущена: %s", e)
    try:
        from server import model_dossier as _dos
        _who = used_llm.get("model") or CFG.get("llm.model", "")
        _said = "".join(full_reply).strip()
        if _dos.check_claim(_who, _said, _tool_used["any"]):
            log.warning("Модель %s заявила о действии, которого не делала: %r",
                        _who, _said[:120])
            report_problem(
                "llm", f"{_who} написала, что выполнила действие, но ни один "
                "инструмент не вызывался",
                "снизила ей надёжность в досье — при выборе модели это "
                "теперь учитывается")
            # и СРАЗУ поднимаем мозги, а не только пишем в досье: досье
            # влияет на следующий автопуск, а человеку плохо сейчас
            note_model_fail("отрапортовала о действии, не вызвав инструмент")
            # ...И ГОВОРИМ ЕЙ ОБ ЭТОМ СЛЕДУЮЩИМ ХОДОМ (2026-08-13, живой
            # вечер: «Открываю плейлист, дай мне секунду» — ноль вызовов,
            # человек ждёт, ничего не происходит, и она об этом не знает.
            # Досье и рейтинг — это статистика для будущего; ей нужен факт
            # СЕЙЧАС, тем же каналом, что и результаты настоящих действий.)
            PENDING_ACTIONS.append((
                "твоё прошлое обещание",
                "ты НАПИСАЛА, что делаешь это, но инструмент не вызвала — "
                "значит НЕ СДЕЛАЛА, и человек сидит и ждёт впустую. "
                "Сделай сейчас: сначала вызов, потом одна короткая фраза. "
                "Не объясняй, почему в прошлый раз не вышло, — просто "
                "сделай."))
        elif _tool_used["any"]:
            _dos.record_ok(_who)
        # прямая жалоба владельца — самый весомый сигнал, весит как десять
        # автоматических
        if re.search(r"\bты\s+(?:же\s+)?(?:не\s+)?(?:ошиб|соврал|обманул|"
                     r"не\s+сделал|ничего\s+не\s+сделал|не\s+справ)",
                     (user_text or ""), re.I):
            _dos.record_complaint(_who, (user_text or "")[:80])
    except Exception as e:
        log.debug("досье не обновилось: %s", e)

    tts_q.put(None)
    tts_thread.join(timeout=600)
    # чистим markdown ПЕРЕД записью в память: она же потом уходит в history
    # следующих ходов (recent_raw) — если хранить сырьё с **жирным**, модель
    # видит собственные нарушения правила как «нормальный» пример и множит
    # их дальше. Живой UI уже получил токены как есть (стрим не переиграть),
    # это только для будущего контекста.
    reply = _strip_markdown("".join(full_reply).strip())
    # текстовые вызовы инструментов ([open_folder:...]) — исполняем и
    # показываем человеку сразу; ей результат уедет фактом в следующий ход
    if reply and not stop_event.is_set():
        try:
            # НЕ ДУБЛИРУЕМ (2026-07-29): gemma делает настоящий tool_call и
            # СЛЕДОМ пишет пустой маркер того же инструмента — раньше маркер
            # улетал в пустоту, теперь он живой и запускал бы всё вторично
            _skip = _tool_used.get("names", set())
            for _an, _ar in _run_tool_marks(reply, skip=_skip):
                out.put({"type": "tool", "name": "⚡ " + _an,
                         "args": _ar[:300]})
                PENDING_ACTIONS.append((_an, _ar))
            # в память ответ кладём без маркеров: история не должна учить
            # её, что маркеры это просто текст
            reply = _strip_tool_marks(reply)
        except Exception as e:
            log.debug("текст-вызовы пропущены: %s", e)
    if reply:
        # прервали на полуслове (живой контекст — юзер докинул) -> помечаем,
        # чтобы на следующем заходе она видела, что не договорила
        if stop_event.is_set() and n_tokens > 0:
            reply += " …(прервана — собеседник добавил уточнение)"
        memory.add_event(person_id, "assistant", reply)
    # ДЕЛО СДЕЛАНО — МОЛЧАНИЕ НЕ СТРАШНО (2026-07-29, живой чат: ответ
    # целиком состоял из вызова инструмента, после вырезания маркеров
    # осталась пустота — и человек читал пугающее «🤐 не смогла ответить»
    # ПОД строкой с успешно закрытым окном. Инструмент отработал — этого
    # достаточно, страшилка не нужна).
    if not reply and not stop_event.is_set() \
            and (_tool_used.get("names") or PENDING_ACTIONS):
        reply = ""          # результат уже показан строкой ⚡ — не дублируем
    # МОЛЧАНИЕ — НЕ ОТВЕТ: если наружу не ушло ни слова и нас не перебивали,
    # объясняем в чате, почему (раньше причина тонула в логе, а в UI
    # выглядело так, будто Сайка просто проигнорировала фразу)
    elif not reply and not stop_event.is_set():
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
# ЗАКРЫТАЯ ВКЛАДКА (2026-07-28, просьба владельца). Человек (создатель или
# гость) может закрыть окно её интерфейса — и она должна это ЗАМЕТИТЬ, как
# живая: не молча продолжить с чистого листа, а отреагировать в своём духе,
# когда её снова откроют. Запоминаем момент закрытия при живом разговоре;
# на новом подключении — импульс с фактом, реплику она сочиняет сама.
TAB_CLOSED = {"ts": 0.0}
# ЭСКАЛАЦИЯ ПОСЛЕ НЕУДАЧ (2026-07-28, просьба владельца: «она не оч хочет
# добиться результата»). Человек второй раз подряд говорит «не получилось» —
# значит локальная голова не вывозит эту задачу. Следующий ход думает
# ОБЛАЧНАЯ модель (как при «быстром мышлении», но триггер — неудача), с
# прямым указанием проверить состояние инструментами, а не отписаться.
FAIL_STREAK = {"n": 0, "ts": 0.0}

# ОНА САМА ВИДИТ, ЧТО НЕ ТЯНЕТ (2026-08-13, мысль владельца: «когда модель
# явно маленькая и мы физически не можем тут работать — она же может менять
# свои мозги, чтобы решать сложные задачи»).
#
# Раньше подъём модели запускала только ЖАЛОБА ЧЕЛОВЕКА, причём вторая
# подряд (FAIL_STREAK). То есть человек должен был дважды сказать «не
# работает», прежде чем что-то менялось. А механические провалы видны
# СЕРВЕРУ и без него, объективно: модель отрапортовала о действии, не
# вызвав инструмента; уронила в текст «[tool_call»; промолчала. В досье
# это и так писалось («снизила надёжность»), но на выбор модели ПРЯМО
# СЕЙЧАС не влияло — оно учитывалось только при следующем автопуске.
def _text_tool_calls(raw: str) -> list:
    """Вызовы инструментов, НАПЕЧАТАННЫЕ текстом, -> [(имя, аргументы)].

    2026-08-13, живой случай с Cloudflare/llama-3.3-70b: модель честно
    просит инструмент — `{"type":"function","name":"window_close",
    "parameters":{"match":"Blender"}}` — но приходит это обычным текстом,
    потому что OpenAI-совместимая обёртка провайдера не кладёт вызовы в
    поле tool_calls. Система такое ЛОВИЛА и вырезала, но исполняла лишь
    пять избранных инструментов из белого списка; всё остальное молча
    пропадало, а человек видел «Секунду, разберусь» и ничего больше.

    Модель не виновата и не глупая — виновата транспортная щель. Разбираем
    JSON по балансу скобок (regex на вложенных объектах врёт) и отдаём
    как обычный вызов: дальше он идёт через штатный tools.call со всеми
    предохранителями, как если бы пришёл нормальным путём."""
    out = []
    if not raw:
        return out
    for m in re.finditer(r'\{', raw):
        depth, end = 0, None
        for i in range(m.start(), len(raw)):
            if raw[i] == '{':
                depth += 1
            elif raw[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if not end:
            continue
        try:
            obj = json.loads(raw[m.start():end])
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        name = obj.get("name") or (obj.get("function") or {}).get("name")
        if not isinstance(name, str):
            continue
        args = (obj.get("parameters") or obj.get("arguments")
                or (obj.get("function") or {}).get("arguments") or {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        if isinstance(args, dict):
            out.append((name, args))
    return out


# ═════ ВЫЗОВ, СКАЗАННЫЙ ВСЛУХ, — ТОЖЕ ВЫЗОВ (2026-08-14) ═════
# Живой разговор владельца, двадцать минут подряд:
#     «перейди просто в диск C»  ->  go_to "диск C"      (в чат, текстом)
#     «закрой проводник»         ->  window_close "explorer"
#     «покажи окна»              ->  [window_list]
#     «зайди в SteamLibrary»     ->  open_folder, SteamLibrary.
# Она ВСЁ ПОНЯЛА ПРАВИЛЬНО. Она назвала нужный инструмент и нужный
# аргумент. Просто маленькая модель (gemma-4-e4b, GigaChat-2) не умеет
# класть вызовы в поле tool_calls и печатает их как умеет — словами.
# Система ловила только JSON-образные формы, а эти пропускала: человек
# видел «go_to "диск C"» в чате и ничего больше. Двадцать минут «не
# получилось» на ровном месте.
#
# Это транспортная щель, а не глупость модели. Форма записи — её дело,
# наше дело — понять. Разбираем любую: имя в кавычках, в скобках, через
# запятую, в квадратных скобках, просто имя. Защита от случайного
# срабатывания одна, зато железная: имя должно СОВПАДАТЬ со списком
# настоящих инструментов, и в нём должно быть подчёркивание (или оно
# должно стоять в скобках) — обычная русская речь так не выглядит.
_BARE_CACHE = {"rx": None, "arg": {}, "n": 0}


def _tool_arg_map():
    """{инструмент: имя главного параметра} — из схем, а не руками."""
    from server.llm import tools as _t
    scs = _t.schemas()
    if _BARE_CACHE["rx"] is not None and _BARE_CACHE["n"] == len(scs):
        return _BARE_CACHE["rx"], _BARE_CACHE["arg"]
    arg, names, need = {}, [], set()
    for sc in scs:
        f = sc.get("function") or {}
        nm = f.get("name")
        if not nm:
            continue
        names.append(nm)
        pr = ((f.get("parameters") or {}).get("properties") or {})
        req = ((f.get("parameters") or {}).get("required") or [])
        arg[nm] = (req[0] if req else (next(iter(pr), "")))
        if req:
            need.add(nm)                  # без аргумента такой вызов пустой
    _BARE_CACHE["need"] = need
    names.sort(key=len, reverse=True)
    rx = re.compile(
        r"(?<![\w-])(" + "|".join(re.escape(n) for n in names) + r")(?![\w-])"
        r"\s*(?:\(|\[|,|:|=|->)?\s*"
        r"(?:\"([^\"\n]{0,90})\"|'([^'\n]{0,90})'"
        r"|([^\n\"',.;!?()\[\]]{0,90}))?")
    _BARE_CACHE.update(rx=rx, arg=arg, n=len(scs))
    return rx, arg


_BARE_STOP = re.compile(r"^\s*(?:и|или|а|но|ну|же|бы|то|это|пожалуйста|"
                        r"сейчас|потом|тоже|также)\b", re.I)


def _bare_tool_calls(raw: str) -> list:
    """Вызовы, НАПЕЧАТАННЫЕ обычными словами -> [(имя, аргументы)]."""
    if not raw or len(raw) > 4000:
        return []
    try:
        rx, argmap = _tool_arg_map()
    except Exception as e:
        log.debug("карта инструментов недоступна: %s", e)
        return []
    out = []
    for m in rx.finditer(raw):
        name = m.group(1)
        # «eyes» — единственное имя без подчёркивания, и это обычное
        # английское слово. Берём его только в явной оболочке вызова.
        if "_" not in name:
            around = raw[max(0, m.start() - 1):m.end() + 1]
            if not re.search(r"[\[\(`]", around):
                continue
        # за именем сразу JSON — это работа _text_tool_calls, не наша
        if raw[m.end(1):m.end(1) + 3].lstrip().startswith("{"):
            continue
        val = (m.group(2) or m.group(3) or m.group(4) or "").strip()
        # двоеточие НЕ срезаем: «C:» — это диск, а не мусор
        val = val.strip(" .,;!?«»\"'()[]")
        if _BARE_STOP.match(val):
            val = ""
        key = argmap.get(name) or ""
        if not val and name in (_BARE_CACHE.get("need") or set()):
            # ПУСТОЙ ВЫЗОВ ХУЖЕ, ЧЕМ НИКАКОЙ (2026-08-14, живой лог:
            # модель напечатала голое «window_focus» — и получила «не
            # знаю, какое окно вы имеете в виду», а человек получил
            # встречный вопрос вместо действия. Инструменту нужен
            # аргумент, его нет — значит это не вызов, а обрывок мысли.
            # Пусть договорит.)
            log.info("Текстовый вызов %s без аргумента — пропускаю", name)
            continue
        out.append((name, {key: val} if (key and val) else {}))
    return out


# ═══ НИ ОДИН КУСОК ПРОМПТА НЕ ИМЕЕТ ПРАВА ОСТАНОВИТЬ ОТВЕТ (2026-08-14) ═══
# Живой лог, из-за которого это написано:
#
#   Тайминги ответа: очередь 25219мс | память 156мс | зрение 16мс |
#   промпт 66906мс | LLM prefill 3844мс | итого до 1-го токена 70938мс
#
# Семьдесят секунд до первого звука. Владелец: «и она сломалась». И он
# прав — с точки зрения человека это не «медленно», это сломано.
#
# Виновата не модель и не память: минуту простояла СБОРКА ПРОМПТА. Там
# десяток кусков, и каждый лезет наружу — за списком окон, за заголовком
# страницы в браузере, за текущей папкой. Пока всё живо, это миллисекунды.
# Но браузер только что закрыли, и обращение к его странице повисло — а
# ждал его весь ответ, потому что сборка идёт в один поток.
#
# Правило: обстановка — это СПРАВКА, а не обязательство. Не успела за
# отведённое время — идём со вчерашней справкой или вовсе без неё.
# Устаревшая строчка в промпте стоит копейки; минута тишины стоит всего.
_PIECE: dict = {}


def _piece(name: str, fn, budget: float = 0.7) -> str:
    """Кусок промпта под секундомером. Не уложился — берём прошлый ответ.

    Зависший вызов не бросаем и не убиваем (убить поток в Python нельзя):
    он доработает сам и положит результат в кэш для следующего хода. Пока
    он висит, второй такой же не запускаем — иначе на каждом ходу
    прибавлялся бы ещё один вечный поток."""
    st = _PIECE.setdefault(name, {"val": "", "busy": False, "ts": 0.0})
    if st["busy"]:
        return st["val"]                      # прошлый ещё не отпустил
    box = {}

    def run():
        try:
            box["v"] = fn() or ""
        except Exception as e:
            box["v"] = ""
            log.debug("кусок промпта %s не собрался: %s", name, e)
        finally:
            st["busy"] = False
            if "v" in box:
                st["val"], st["ts"] = box["v"], time.time()

    st["busy"] = True
    th = threading.Thread(target=run, daemon=True, name=f"piece-{name}")
    th.start()
    th.join(budget)
    if th.is_alive():
        log.warning("Кусок промпта «%s» думает дольше %.1fс — иду без него "
                    "(в промпт пойдёт прошлый вариант, %d симв). Это не "
                    "ошибка модели: что-то снаружи не отвечает.",
                    name, budget, len(st["val"]))
        return st["val"]
    return box.get("v", "")


# ЧТО ИСПОЛНЯЕТСЯ ДО РАЗДУМИЙ (2026-08-14). Только обратимое и мгновенное:
# ручка громкости, пауза, следующий трек, свернуть/развернуть окно. Ничего,
# что закрывает окна, пишет файлы или лезет в сеть, — такое пусть проходит
# обычным путём, там предохранители и обстановка. Правило простое: если
# человек может отменить это одним движением, ждать разрешения незачем.
INSTANT_TOOLS = {"volume_set", "media_control", "media", "tab_control",
                 "window_minimize", "window_focus", "minimize_all",
                 "window_maximize", "window_restore", "eyes",
                 # ШАГ ПО ПАПКАМ — ТОЖЕ МГНОВЕННЫЙ (2026-08-14, владелец:
                 # «она моментально просто переходит по пути, не пиздя
                 # излишне»). Задержка на шаге читается как «не поняла»:
                 # человек повторяет команду, а она приходит вторым шагом.
                 "go_to", "pick_number", "scan_disk", "find_here"}

# когда последний раз ругались, что владелец не отмечен (раз в час, не чаще)
_GUEST_NAG = {"ts": 0.0}

# результат мгновенного рефлекса — чтобы конвейер не повторил действие
EARLY_REFLEX = {"text": "", "name": "", "result": "", "ts": 0.0}

MODEL_FAIL = {"n": 0, "ts": 0.0, "why": ""}
# какие мозги уже пробовали в текущей серии провалов: следующая
# эскалация должна подниматься ВЫШЕ, а не звать того же неудачника
ESCALATION = {"tried": set(), "ts": 0.0}


def note_model_fail(why: str):
    """Механический провал модели — не жалоба человека, а факт сервера."""
    MODEL_FAIL["n"] = (MODEL_FAIL["n"] + 1
                       if time.time() - MODEL_FAIL["ts"] < 600 else 1)
    MODEL_FAIL["ts"] = time.time()
    MODEL_FAIL["why"] = why
    log.info("Провал модели (%s), подряд: %d", why, MODEL_FAIL["n"])
# АВТООТКЛЮЧЕНИЕ ГЛАЗ (2026-07-28, просьба владельца). Зрение — это захват
# кадров и место в VRAM; включённое «на всякий случай» оно просто греет
# карту. Помним, когда взгляд ПОСЛЕДНИЙ раз был нужен (auto_look отдал кадр,
# импульс зрения, ручной кадр из UI) — и если долго не нужен, выключаем
# сами, честно сообщив в интерфейс. Включается обратно словом («включи
# глаза» — рефлекс) или тумблером. vision.auto_off_min=0 отключает механику.
VISION_USED = {"ts": 0.0}
_COMPLAINT_RE = re.compile(
    r"не получил|не получается|не вышло|не выходит|не работает|не сработал|"
    r"ничего не (?:произошло|открыл|закрыл|измени|вижу)|опять не|снова не|"
    r"вс[её] ещ[её]|так и не|не закрыл|не открыл|результата нет", re.I)
IDLE_STATE = {"stage": 0}   # 0 тишины нет | 1 буркнула | 2 спросила «есть кто» | 3 бормочет


def _user_activity():
    LAST_USER["ts"] = time.time()
    LAST_USER["seen"] = True
    IDLE_STATE["stage"] = 0
    # владелец заговорил — значит, спячка после разгрузки кончилась
    HARD_UNLOADED["on"] = False


def _impulse_ready(key, cooldown_s):
    # ПОСЛЕ РАЗГРУЗКИ — ТИШИНА (2026-07-28, владелец поймал со смехом:
    # «я всё вырубил, а скрипт мне запустил ллм»). Импульс скуки шёл в
    # handle_text, тот лениво поднимал llama-server — и вся жёсткая
    # разгрузка отменялась сама собой через минуту простоя. Правило: если
    # мозги выключены или активной модели нет, внутренняя жизнь не имеет
    # права будить железо. Она просыпается вместе с моделью — когда
    # владелец сам выберет её кликом.
    if CFG.get("llm.off", False):
        return False
    if HARD_UNLOADED["on"]:
        return False
    if time.time() - IMPULSE_LAST.get(key, 0) < cooldown_s:
        return False
    # не влезаем в идущий ответ; «ответ» старше 10 мин считаем зависшим
    active = DIALOG_STATE["active_since"]
    if active and time.time() - active < 600:
        return False
    return bool(EVENT_CLIENTS)


def _fire_impulse(key, text, image=None):
    """image (2026-07-25) — для импульса зрения: Сайка сама заметила, что
    картинка изменилась, и говорит по кадру, а не по таймеру."""
    IMPULSE_LAST[key] = time.time()
    out = next(iter(EVENT_CLIENTS))
    log.info("Импульс %s: запускаю внутренний монолог", key)

    def run():
        # на время импульса инструменты пользователя заблокированы
        from server.llm import tools as _tls
        _tls.IMPULSE_MODE["on"] = True
        try:
            run_dialog(text, out, threading.Event(), image=image)
        finally:
            _tls.IMPULSE_MODE["on"] = False

    threading.Thread(target=run, daemon=True).start()


def _vision_auto_off():
    """Глаза включены, но взгляд давно не был нужен — выключаем сами."""
    try:
        mins = float(CFG.get("vision.auto_off_min", 15) or 0)
        if not mins or not vision.enabled():
            return
        idle = time.time() - VISION_USED["ts"]
        if VISION_USED["ts"] == 0.0:
            # ни разу не смотрела с этого включения — отсчёт от включения
            # вести не от 1970: ставим метку при первом же тике
            VISION_USED["ts"] = time.time()
            return
        if idle < mins * 60:
            return
        vision.set_enabled(False)
        log.info("Зрение выключилось само: не было нужно %.0f мин", idle / 60)
        broadcast_event({"type": "tool", "name": "глаза",
                         "args": f"выключились сами — не были нужны "
                                 f"{int(idle // 60)} мин. Слово «включи "
                                 f"глаза» вернёт."})
    except Exception as e:
        log.debug("автоотключение глаз: %s", e)


def _impulse_tick():
    _vision_auto_off()
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


def _vision_watch_cb(url, source, note):
    """Режим наблюдения заметил смену картинки. Сайка получает это как
    ВНУТРЕННИЙ импульс — то есть говорит по своей воле, а не отвечает.
    Кулдаун отдельный и щедрый: комментировать каждое переключение окна
    это не живость, а надоедливость.

    vision.watch_speaks=false — наблюдение работает молча (видно в логах и
    в счётчике реакций), но вслух Сайка ничего не говорит."""
    if not CFG.get("vision.watch_speaks", True):
        log.info("Наблюдение: смена картинки на %s (молча)", source)
        return
    cd = float(CFG.get("vision.impulse_cooldown_s", 120))
    if not _impulse_ready("vision", cd):
        return
    try:
        from server import capabilities as _caps_v
        from server import vision as _vis
        img = url
        if _caps_v.vision(CFG.get("llm.model", "")) is False:
            desc = _vis._describe(url, "Опиши коротко, что изменилось "
                                       "и что сейчас на кадре.")
            if not desc:
                return          # смотреть некому — молча пропускаем тик
            img = None
            note = ("### Ты в режиме наблюдения заметила, что картинка "
                    "изменилась. Твоя модель без зрения, кадр разобрала "
                    "vision-модель парка:\n" + desc[:2000] +
                    "\n\nСкажи коротко и по-своему, что думаешь.")
        where = "экране" if str(source).startswith("screen") else "камере"
        _fire_impulse("vision", note + f"\n(ты смотришь на {where} сама, "
                      "тебя никто не спрашивал — реплика должна быть "
                      "КОРОТКОЙ, одна-две фразы, и на этом всё. Ничего не "
                      "ищи, никуда не лезь, ничего не открывай: это просто "
                      "твоё наблюдение вслух.) [[vision-impulse]]",
                      image=img)
    except Exception as e:
        log.debug("импульс зрения: %s", e)


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
    # Вебсокет мимо http-middleware, поэтому охрана здесь отдельно: через
    # него идёт весь живой диалог, а значит и все команды в систему.
    try:
        from server import phone as _ph
        if _ph.is_open():
            _cl = ws.client.host if ws.client else ""
            if _cl not in ("127.0.0.1", "::1", "localhost"):
                # у вебсокета заголовки не наши: смотрим параметр и cookie,
                # которая ставится при первом заходе по ссылке из QR
                _tok = (ws.query_params.get("t")
                        or ws.cookies.get("saika_token") or "")
                if _tok != _ph.token():
                    await ws.close(code=4401)
                    log.warning("Отклонила websocket без кода доступа: %s",
                                _cl)
                    return
    except Exception as e:
        log.debug("проверка кода доступа пропущена: %s", e)
    await ws.accept()
    out: "queue.Queue" = queue.Queue()
    EVENT_CLIENTS.add(out)
    # интерфейс вернулся после закрытия при живом разговоре — она замечает.
    # Задержка 2с: пусть вкладка догрузится и websocket устаканится.
    # не раньше 10с после закрытия: F5 переподключается за 1-3с, и ворчать
    # на каждое обновление страницы — это уже не характер, а невроз
    if 10 < time.time() - TAB_CLOSED["ts"] < 600 \
            and time.time() - IMPULSE_LAST.get("tab_closed", 0) > 90:
        TAB_CLOSED["ts"] = 0.0
        def _react_tab():
            time.sleep(2)
            try:
                _fire_impulse("tab_closed",
                    "Служебный факт (не показывай его текстом): окно твоего "
                    "интерфейса только что ЗАКРЫВАЛИ — это сделал человек за "
                    "компьютером (создатель или гость), и вот его снова "
                    "открыли. Отреагируй одной-двумя короткими фразами в "
                    "своём характере — как живая, которую внезапно "
                    "захлопнули и снова открыли.")
            except Exception as e:
                log.debug("импульс tab_closed: %s", e)
        threading.Thread(target=_react_tab, daemon=True).start()
    stop_event = threading.Event()
    worker: threading.Thread | None = None
    # «слушаю, но не отвечаю» — состояние ЭТОЙ вкладки, не глобальное:
    # на телефоне может идти обычный разговор, пока на компьютере крутится
    # кино и она его каталогизирует
    # on  — «не отвечать»: слышит и распознаёт, но реплик не выдаёт
    # stt — распознавать ли речь вообще (для кино можно и не тратить)
    observe = {"on": False, "stt": True}
    # ГЛУБИНА ОЧЕРЕДИ СЛУХА. Было 40 чанков (4 секунды) — и этого не хватало
    # ровно в тот момент, когда всё и решается: движок берёт готовый кусок и
    # молчит секунды три, а звук в это время идёт. Тридцать чанков приходят,
    # сорок помещается — запас в десять штук, любая заминка (шумодав, своп,
    # сборка мусора) съедала его, и в стенограмме появлялась дырка. Хуже
    # всего, что дырка эта незаметная: текст идёт, просто в нём нет пары фраз.
    # Две минуты запаса стоят 4 МБ памяти и закрывают вопрос: движок в
    # среднем в восемь раз быстрее реального времени, отставание рассасывается
    # само, ронять приходится только если он сломался совсем.
    # 300 чанков = 30 секунд. Больше не нужно: горячий цикл теперь стоит
    # миллисекунды и за реальным временем успевает. Глубокая очередь тут не
    # запас прочности, а отставание: чем она длиннее, тем позже приходит
    # текст. Тридцати секунд хватает пережить любую заминку — своп, сборку
    # мусора, переобучение проекции.
    hear_q: "queue.Queue" = queue.Queue(maxsize=300)

    # ОЧЕРЕДЬ ГОТОВЫХ ФРАЗ. Между дешёвой нарезкой и дорогим распознаванием
    # (см. комментарий в server/stt/manager.py). Держим немного: если движок
    # отстал на десяток фраз, дальше он уже не догонит, и честнее сказать
    # об этом в лог, чем копить минуты.
    seg_q: "queue.Queue" = queue.Queue(maxsize=12)
    SEG_DROP = {"n": 0}

    def _hear_worker():
        """Шумодав -> отпечаток голоса -> НАРЕЗКА. Всё, что здесь есть,
        стоит миллисекунды: этот поток обязан успевать за реальным временем
        любой ценой, иначе звук придётся ронять. Распознавание живёт в
        соседнем потоке и на этот цикл больше не влияет."""
        while not stop_event_all.is_set():
            try:
                p = hear_q.get(timeout=0.4)
            except queue.Empty:
                continue
            if p is None:
                break
            try:
                t0 = time.monotonic()
                p = DENOISE.process(p)
                t1 = time.monotonic()
                # УХО (2026-08-13): сначала «что это вообще за звук», потом
                # «чей голос». Без этого порядка клацанье клавиатуры честно
                # получало эмбеддинг и заводило себе профиль в карте
                # («Голос 4», 153 срабатывания, 103-400 Гц — живой случай).
                hearing.feed(p)
                if hearing.speech_ok():
                    voiceprint.feed(p)
                if not observe["stt"]:
                    continue
                HEAR_STAT["chunks"] += 1
                HEAR_STAT["q"] = hear_q.qsize()
                try:
                    _r = round(float(np.sqrt(np.mean(
                        (p.astype(np.float32) / 32768.0) ** 2))), 5)
                    HEAR_STAT["rms"] = _r
                    HEAR_STAT["thr"] = round(stt.vad._eff_threshold(), 5)
                    # пик держим 6 секунд: столько живёт обычная пауза между
                    # фразами, и за это окно голос точно успевает прозвучать
                    _now = time.time()
                    if _r > HEAR_STAT["peak"] or _now - HEAR_STAT["peak_ts"] > 6:
                        HEAR_STAT["peak"] = _r
                        HEAR_STAT["peak_ts"] = _now
                    if HEAR_STAT["rms"] < HEAR_STAT["thr"] * 0.6:
                        HEAR_STAT["quiet"] += 1
                except Exception:
                    pass

                # is_streaming() лениво поднимает движок при первом
                # обращении — как раньше делал process_chunk. Дальше это
                # просто чтение поля, так что в горячем цикле уместно.
                if stt.is_streaming():
                    # потоковый движок (Vosk) отдаёт слова сам и стоит копейки
                    for r in (stt.process_chunk(p) or []):
                        _emit_phrase(r, 0)
                else:
                    seg = stt.cut(p)
                    if seg is not None:
                        HEAR_STAT["segments"] += 1
                        try:
                            seg_q.put_nowait(seg)
                        except queue.Full:
                            SEG_DROP["n"] += 1
                            log.warning("Распознавание не догоняет: пропустила "
                                        "фразу (всего %d)", SEG_DROP["n"])

                # ЧЕРНОВИК: слова на экране, пока точный движок думает.
                # Слух выключен — и черновик молчит: после «выгрузить всё»
                # ни одна модель не имеет права подниматься сама.
                try:
                    # Пока фразу уже хоть раз перечитал точный движок
                    # (см. _live_polish), сырой черновик Vosk молчит: иначе
                    # красивый текст со знаками каждые 200мс сменялся бы
                    # обратно на «сырую» строку без них.
                    #
                    # И ТОЛЬКО НА РЕЧИ (2026-07-28, «уронила 1701 чанков»).
                    # Черновик жевал ВСЁ подряд — включая аниме из системного
                    # звука. Музыка для Vosk — худший случай: решётка гипотез
                    # разрастается, каждые 100мс звука стоят дороже 100мс, и
                    # горячий цикл тонет. Пока VAD не слышит речи, черновику
                    # нечего показывать — и нечего считать.
                    if (stt.current_name not in stt.OFF and not POLISH["n"]
                            and getattr(stt.vad, "in_speech", False)):
                        d = DRAFT.feed(p)
                        if d:
                            out.put({"type": "stt_draft", "text": d})
                except Exception as e:
                    log.warning("Черновик споткнулся (дальше без него): %s", e)

                # по стадиям, а не одним числом: «движок 2мс» ни о чём не
                # говорит, когда 99 чанков из 100 движка вообще не видят
                HEAR_STAT["den_ms"] = round(
                    0.95 * HEAR_STAT["den_ms"] + 0.05 * (t1 - t0) * 1000, 2)
                HEAR_STAT["cut_ms"] = round(
                    0.95 * HEAR_STAT["cut_ms"]
                    + 0.05 * (time.monotonic() - t1) * 1000, 2)
            except Exception as e:
                log.warning("Поток слуха споткнулся: %s", e)

    def _emit_phrase(r, ms):
        """ГЛАВНОЕ — ПЕРВЫМ. Расписалась дорого (2026-07-28): черновик стоял
        ВЫШЕ выдачи фраз и звал DRAFT, который я забыла импортировать.
        NameError ловил общий except — и вместе с черновиком в него улетала
        КАЖДАЯ распознанная фраза. Урок: необязательная красота не имеет
        права стоять перед выдачей результата."""
        try:
            r["stt_ms"] = ms
            r["heard_at"] = time.strftime("%H:%M:%S")
            r["_heard_mono"] = time.monotonic()
            LAST_STT.update(engine=r.get("engine", "?"), stt_ms=ms,
                            ts=time.time())
            voice_phrase(r)
        except Exception as e:
            log.warning("Фраза не доехала: %s", e)

    # СКОЛЬЗЯЩАЯ НОРМАЛИЗАЦИЯ (2026-07-28, просьба владельца: «как у GPT —
    # слова сразу, и тут же знаки препинания и нормальный текст»). Три слоя:
    #   1. черновик Vosk — слова в момент произнесения, серым;
    #   2. этот код — пока фраза ЗВУЧИТ, точный движок раз в ~2с перечитывает
    #      накопленное и подменяет черновик правильным текстом со знаками;
    #   3. чистовик — конец фразы, как раньше, уходит в диалог и стенограмму.
    # Живёт в паузах потока распознавания: готовые фразы всегда важнее.
    POLISH = {"ts": 0.0, "n": 0}

    def _live_polish():
        if not CFG.get("stt.live_polish", True) or stt.is_streaming():
            return
        # движок медленнее двух секунд на кусок — перечитывание не успеет
        # за собственным циклом и только заткнёт очередь настоящих фраз
        if HEAR_STAT["stt_ms"] > 2000:
            return
        now = time.monotonic()
        wait = max(1.4, HEAR_STAT["stt_ms"] / 1000 * 1.5)
        if now - POLISH["ts"] < wait:
            return
        snap = stt.peek()
        if snap is None:
            return
        if len(snap) <= POLISH["n"] + 8000:      # наросло меньше полсекунды
            return
        POLISH["ts"], POLISH["n"] = now, len(snap)
        try:
            results = stt.transcribe_segment(snap)
            txt = (results[0]["text"] if results else "").strip()
            if txt:
                try:
                    txt = TRANSCRIPT._enhance(txt)   # знаки препинания
                except Exception:
                    pass
                DRAFT.reset()                        # версия Vosk устарела
                out.put({"type": "stt_draft", "text": txt})
        except Exception as e:
            log.debug("Скользящая нормализация споткнулась: %s", e)

    def _stt_worker():
        """Распознавание готовых фраз. Может думать секундами — и теперь это
        никому не мешает: поток слуха в это время спокойно режет дальше."""
        while not stop_event_all.is_set():
            try:
                seg = seg_q.get(timeout=0.4)
            except queue.Empty:
                _live_polish()
                continue
            if seg is None:
                break
            try:
                t0 = time.monotonic()
                results = stt.transcribe_segment(seg)
                ms = round((time.monotonic() - t0) * 1000)
                HEAR_STAT["stt_ms"] = round(
                    0.7 * HEAR_STAT["stt_ms"] + 0.3 * ms, 1)
                HEAR_STAT["lag"] = seg_q.qsize()
                if not results:
                    HEAR_STAT["empty"] += 1
                    continue
                POLISH["n"] = 0
                DRAFT.reset()
                out.put({"type": "stt_draft", "text": ""})
                for r in results:
                    _emit_phrase(r, ms)
            except Exception as e:
                log.warning("Распознавание споткнулось: %s", e)

    stop_event_all = threading.Event()

    # первым делом — id запуска: вкладка сравнит со своим и, если сервер
    # успел перезапуститься, сама перезагрузится (см. UI, тип «hello»)
    hear_thread = threading.Thread(target=_hear_worker, name="hear",
                                   daemon=True)
    hear_thread.start()
    stt_thread = threading.Thread(target=_stt_worker, name="stt", daemon=True)
    stt_thread.start()
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
        # МОДЕЛЬ ВЫКЛЮЧЕНА (2026-07-28). Отдельный режим «Сайка молчит»:
        # слух, отпечаток голоса и журнал работают, мозги не запускаются
        # вообще. Нужен для опытов с голосами и для просмотра кино — иначе
        # каждая услышанная фраза рождает ответ, и эксперимент превращается
        # в разговор с телевизором. Не то же самое, что выгрузка из памяти:
        # модель остаётся загруженной и готова, её просто не зовут.
        # СПИННОЙ МОЗГ РАБОТАЕТ ДО ГОЛОВНОГО (2026-08-14, просьба владельца:
        # «некоторые команды срабатывают, по типу громкости, но с задержкой,
        # если она думает — нужно, чтобы такие базовые вещи выполнялись
        # моментально, вне зависимости от её ответа»).
        #
        # Рефлекс и раньше шёл «до промпта», но ВНУТРИ диалогового
        # конвейера: сперва очередь, живой контекст, маршрутизатор, выбор
        # мозга, память, лорбук, кадр экрана — и только потом громкость.
        # Секунда-две набегали до того, как палец нажмёт на регулятор.
        # У человека рука на громкости не ждёт, пока он додумает фразу.
        # Теперь рефлекс исполняется ПЕРВОЙ строкой, ещё до всех проверок:
        # звук меняется мгновенно, а модель потом прокомментирует уже
        # сделанное (результат уезжает в EARLY_REFLEX и оттуда в промпт).
        try:
            from server import reflex as _rx0
            _hit0 = _rx0.match(user_text)
            if _hit0 and _hit0[0] in INSTANT_TOOLS:
                broadcast_event({"type": "tool", "name": "⚡ " + _hit0[0],
                                 "args": str(_hit0[1])[:300]})
                _res0 = _rx0.execute(_hit0, user_text)
                if _res0:
                    broadcast_event({"type": "tool",
                                     "name": "⚡ " + _hit0[0],
                                     "args": str(_res0)[:900]})
                EARLY_REFLEX.update(text=user_text, name=_hit0[0],
                                    result=_res0, ts=time.time())
                log.info("Мгновенный рефлекс: %s -> %s", _hit0[0],
                         str(_res0)[:80])
        except Exception as e:
            log.debug("мгновенный рефлекс пропущен: %s", e)
        if CFG.get("llm.off", False):
            log.info("Мозги выключены — реплику не рождаю: %r",
                     str(user_text)[:60])
            return
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
            # + короткая память намерения (2026-07-29): «открой телеграм на
            # втором экране» -> «первый» -> «просто открой» — к третьей
            # фразе предохранитель уже не видел ни «экрана», ни «открой» и
            # резал живое действие. Намерение живёт разговором, а не одной
            # репликой — храним хвост из трёх фраз.
            _rec = _tls.LAST_USER.setdefault("recent", [])
            _rec.append(user_text)
            del _rec[:-3]
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

    QUIET = {"on": False, "since": 0.0}

    def _wants_quiet(text: str) -> bool:
        """«Замолчи» это не то же, что «стоп». «Стоп» — прекрати ЭТО;
        «замолчи/помолчи/не мешай» — прекрати ВСЁ, пока не позову."""
        t = (text or "").lower()
        return bool(re.search(r"замолч|помолч|\bмолчи\b|заткнис|не\s+мешай|"
                              r"отвали|не\s+лезь|тихий\s+режим", t))

    def _silence_now():
        """Оборвать ЗВУК, который уже наговорен и играет.

        Одного stop_event мало: он останавливает генерацию, а куски,
        которые уже ушли в устройства вывода и в браузер, продолжают
        звучать секундами. «Стоп» должен слышаться сразу."""
        for sp in list(SPEAKERS):
            try:
                sp.drop()
            except Exception as e:
                log.debug("серверный вывод не заглушился: %s", e)
        try:
            broadcast_event({"type": "shutup"})
        except Exception as e:
            log.debug("браузеру не сказалось замолчать: %s", e)

    def _is_stop(text: str) -> bool:
        """Короткая команда «замолчи». НЕ уходит в LLM — просто глушим
        генерацию и озвучку (иначе маленькая модель начинает рассуждать, как
        ей замолчать). Ловим и «стоп», и «зайка остановись» (имя + стоп):
        сначала выкидываем обращение по имени, потом смотрим — короткая ли
        фраза, где есть стоп-слово."""
        # «тише» и «потише» убраны из стоп-слов (2026-07-26, живой случай):
        # владелец говорил про громкость СИСТЕМЫ, а Сайка глушила сама себя.
        # По-русски «тише» почти всегда про звук, а «замолчи» — это «стоп»,
        # «хватит», «молчи». Громкостью занимается разбор команд ниже.
        stops = set(CFG.get("attention.stop_words",
                            ["стоп", "стой", "хватит", "замолчи", "молчи",
                             "помолчи", "заткнись",
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

    def _echo_risk(now: float) -> bool:
        """Играет ли прямо сейчас её собственный голос."""
        if CFG.get("stt.echo_guard", True) is False:
            return False
        if CFG.get("tts.headphones", False):
            return False          # в наушниках эха нет — глушить нечего
        tail = float(CFG.get("stt.echo_tail_s", 0.9))
        return (now - AUDIO_LEVEL.get("ts", 0.0)) < tail

    def _echo_text(text: str) -> bool:
        """Совпадает ли услышанное с тем, что она только что сказала."""
        if CFG.get("stt.echo_guard", True) is False:
            return False
        t = re.sub(r"[^а-яa-zё ]", " ", (text or "").lower())
        words = [w for w in t.split() if len(w) > 2]
        if len(words) < 2:
            return False        # на коротком совпадение ничего не значит
        now = time.time()
        for ts, said in list(SAID_RECENT):
            if now - ts > 12:
                continue
            sw = set(said)
            hit = sum(1 for w in words if w in sw)
            if hit / len(words) >= 0.6:
                return True
        return False

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
        # ═══ «СТОП» ВЫШЕ ВСЕГО ОСТАЛЬНОГО (2026-08-15, просьба владельца:
        # «сделай команду остановить выше всех процессов, чтобы он мог
        # остановить процесс в любой момент без очередей, чисто на основе
        # системы и распознавателя»). Стоп-слово и раньше не уходило в
        # LLM, но проверялось ПОСЛЕ отпечатка голоса, проверки на гостя,
        # эхо-защиты и хоткеев — то есть после доброй половины конвейера.
        # Пока всё это считается, она продолжает говорить. Теперь это
        # первое, что случается с распознанной фразой, и глушим не только
        # генерацию, но и уже наговоренное: очередь фраз, серверные
        # устройства вывода и звук в браузере. ═══
        if _is_stop(r.get("text", "")):
            _user_activity()
            stop_event.set()
            with pending_lock:
                pending.clear()
            _silence_now()
            quiet = _wants_quiet(r.get("text", ""))
            if quiet:
                QUIET["on"] = True
                QUIET["since"] = now
                log.info("Тихий режим: слушаю, но не отвечаю, пока не "
                         "позовут по имени")
            out.put({"type": "stt_stop", **r, "quiet": quiet})
            return
        # МЕТКА ГОВОРЯЩЕГО (2026-07-28). Появляется только когда тембр уже
        # узнаётся устойчиво — до этого честнее не писать ничего, чем писать
        # наугад. Она же уходит в модуль имён: если во фразе прозвучало имя,
        # оно привяжется к сигнатуре голоса, а не к слову.
        try:
            _sp, _spc = voiceprint.who_now()
            if _sp:
                r["speaker"], r["speaker_conf"] = _sp, round(_spc, 2)
                # цвет говорящего — тот же, что у его территории на карте.
                # Нужен интерфейсу, чтобы реплики разных людей отличались
                # не только подписью (2026-07-29, замысел владельца:
                # разговор нескольких людей раскладывается по облачкам).
                try:
                    _v = voiceprint.S.reg.speakers.get(_sp) or {}
                    if _v.get("color"):
                        r["speaker_color"] = _v["color"]
                    if _v.get("owner"):
                        r["speaker_owner"] = True
                except Exception:
                    pass
            voiceprint.note_text(r.get("text", ""), _sp)
        except Exception as e:
            log.debug("метка говорящего: %s", e)
        # СТЕНОГРАММА (восстановлено 2026-07-28: обвязка выпала при слиянии
        # двух чатов — сам модуль был цел, а импорт и роуты потерялись, и
        # интерфейс сыпал 404 на /api/transcript)
        try:
            if TRANSCRIPT.on:
                _pr = voiceprint.prosody() if hasattr(voiceprint, "prosody") \
                    else {}
                _mood = mood_of(_pr.get("pitch", 0), _pr.get("energy", 0),
                                _pr.get("plo", 0), _pr.get("phi", 0))
                TRANSCRIPT.add(r.get("text", ""), r.get("speaker", ""),
                               _mood, r.get("engine", ""))
        except Exception as e:
            log.debug("стенограмма: %s", e)
        # «не отвечать»: текст показываем, реплику не рождаем. Ради этого
        # режима всё и затевалось — иначе эксперимент с голосами превращается
        # в разговор Сайки с телевизором.
        if observe["on"]:
            out.put({"type": "stt", **r})
            return
        # ЭХО ИЗ КОЛОНОК (2026-07-26, живой случай). Владелец говорит через
        # колонки, микрофон слышит её же голос, GigaAM послушно его
        # распознаёт — и Сайка отвечает сама себе обрывками своих реплик.
        # Наушники это лечат, но требовать наушников нельзя: разговор с
        # дивана и был смыслом всей затеи.
        #
        # Пока звук РЕАЛЬНО играет (AUDIO_LEVEL свежий) плюс хвост на
        # затухание — пропускаем только то, ради чего человек и перебивает:
        # стоп-слова и обращение по имени. Остальное это почти наверняка
        # она сама. Полностью глушить микрофон нельзя — тогда «стоп»
        # перестанет работать, а это худшее, что можно сделать.
        if _echo_risk(now) and not _is_stop(r["text"]) \
                and not _addressed(r["text"]):
            log.info("Пропустила эхо из колонок: %r", r["text"][:60])
            return
        if _echo_text(r["text"]):
            log.info("Пропустила своё же эхо (совпало с репликой): %r",
                     r["text"][:60])
            return
        # ОТВЕЧАЮ ТОЛЬКО ВЛАДЕЛЬЦУ (2026-08-13, просьба владельца: «если
        # Сайка слышит другие голоса — не реагировать на них ответами, пока
        # я не дам разрешение»).
        #
        # Разница с режимом «наблюдаю» принципиальная: там она молчит на
        # ВСЁ, здесь — слышит и записывает всех, но отвечает одному. Чужую
        # реплику по-прежнему видно в чате и в стенограмме: она не глухая,
        # она воспитанная.
        #
        # Два предохранителя, чтобы это не превратилось в кляп:
        #  - владелец в реестре не помечен — фильтр не работает вообще;
        #  - голос НЕ УЗНАН (метки нет или уверенность низкая) — отвечаем.
        #    Молчать из-за собственной неуверенности хуже, чем ответить
        #    лишний раз: человек тогда просто не понимает, сломалась она
        #    или обиделась.
        if CFG.get("owner.only_owner", True) and not r.get("speaker_owner"):
            _sp_name = r.get("speaker") or ""
            _sp_conf = float(r.get("speaker_conf") or 0)
            try:
                _has_owner = voiceprint.owner_marked()
            except Exception:
                _has_owner = False
            # ТИХАЯ ЗАЩИТА — НЕ ЗАЩИТА (2026-08-14). Владелец не отмечен в
            # реестре — весь фильтр не работает вообще, и об этом никто не
            # знает: снаружи это выглядит как «система тупая, пускает в
            # разговор посторонних». Говорим прямо и один раз в час, а не
            # молчим.
            if not _has_owner:
                if time.time() - _GUEST_NAG["ts"] > 3600:
                    _GUEST_NAG["ts"] = time.time()
                    log.warning("Владелец не отмечен в реестре голосов — "
                                "отвечаю ВСЕМ, включая посторонних. Отметь "
                                "свой голос золотом в панели «Твой голос».")
                    broadcast_event({"type": "baymax", "mood": "meh",
                                     "text": "🎙 Твой голос не отмечен как "
                                     "хозяйский — я отвечаю всем подряд, "
                                     "включая разговоры рядом. Отметь себя "
                                     "в панели «Твой голос»."})
            else:
                # ЛИДЕР СРАВНЕНИЯ, А НЕ ТОЛЬКО ВЗЯТЫЙ ПОРОГ (2026-08-14,
                # живой лог: рядом шёл чужой разговор про аренду и Юлю,
                # метка стояла «Голос 3 (26%)» — до порога 55% не дотянуло,
                # и всё уехало Сайке в контекст, а она послушно отвечала.
                # «Не уверена, кто это» и «это точно не владелец» — разные
                # вещи. Если ближе всего ЧУЖОЙ голос и он не еле-еле
                # похож — это чужая речь, и в разговор ей не надо.
                _near, _sim = "", 0.0
                try:
                    _near, _sim = voiceprint.near_now()
                except Exception:
                    pass
                _near_owner = False
                try:
                    _near_owner = bool((voiceprint.S.reg.speakers.get(_near)
                                        or {}).get("owner"))
                except Exception:
                    pass
                # ремень поверх подтяжек: если узнанный голос — сам
                # владелец, чужим он не бывает ни при каких цифрах
                _sp_owner = False
                try:
                    _sp_owner = bool((voiceprint.S.reg.speakers.get(_sp_name)
                                      or {}).get("owner"))
                except Exception:
                    pass
                _guest = (not _sp_owner and _sp_name
                          and _sp_conf >= float(CFG.get("owner.min_conf", 0.55)))
                if not _guest and _near and not _near_owner:
                    _guest = _sim >= float(CFG.get("owner.guest_sim", 0.45))
                if _guest:
                    log.info("Рядом говорит «%s» (уверенность %.0f%%, "
                             "похожесть %.2f) — записала, в разговор не "
                             "беру", _sp_name or _near, _sp_conf * 100, _sim)
                    out.put({"type": "stt", **r, "ignored_guest": True})
                    return
        # «стоп» уже отработал первой строкой voice_phrase (2026-08-15) —
        # здесь он был бы вторым и лишним
        # ГОЛОСОВОЙ ХОТКЕЙ: слово-триггер срабатывает МГНОВЕННО, мимо LLM
        if _fire_voice_hotkey(r["text"]):
            _user_activity()
            return
        # режим «слушать всё»: отвечает на любую распознанную речь, без имени
        # и без окна (умный режим внимания остаётся дефолтом — см. UI-тумблер)
        always = CFG.get("attention.always", False)
        # ТИХИЙ РЕЖИМ (2026-08-15, просьба владельца: «команда „замолчи“
        # чтобы переводила её слух в умный режим, пока я её не позову по
        # имени»). Слух, отпечаток голоса и журнал продолжают работать —
        # молчит только ответ. Выходит из него ровно одно: имя.
        if QUIET["on"]:
            if _addressed(r["text"]):
                QUIET["on"] = False
                log.info("Тихий режим снят — позвали по имени")
                out.put({"type": "quiet", "on": False})
            else:
                out.put({"type": "stt_ignored", **r, "quiet": True})
                return
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
                # СЛУХ ЖИВЁТ В СВОЁМ ПОТОКЕ, А НЕ В ЦИКЛЕ ВЕБСОКЕТА.
                # ГРАБЛИ 2026-07-28 (жалоба «транскриптор не справляется»):
                # раньше каждый чанк по 100мс ждал своей очереди в await, и
                # когда распознавание одного куска занимало секунды, за это
                # время накапливалось полсотни чанков. Отставание не
                # рассасывалось никогда — оно только росло, и в текст
                # попадала треть сказанного.
                # Теперь вебсокет только КЛАДЁТ чанк в очередь. Если слух не
                # успевает, очередь переполняется и старый звук РОНЯЕТСЯ:
                # для стенограммы потерять пару секунд лучше, чем отстать на
                # десять минут и писать вчерашнее.
                try:
                    hear_q.put_nowait(np.frombuffer(msg["bytes"], dtype=np.int16))
                except queue.Full:
                    HEAR_DROP["n"] += 1
                    HEAR_STAT["dropped"] += 1
                    try:
                        hear_q.get_nowait()
                        hear_q.put_nowait(
                            np.frombuffer(msg["bytes"], dtype=np.int16))
                    except Exception:
                        pass
                    if HEAR_DROP["n"] % 50 == 1:
                        log.warning("Слух не успевает: уронила %d чанков "
                                    "(движок медленнее реального времени)",
                                    HEAR_DROP["n"])
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
                elif mtype == "observe":
                    observe["on"] = bool(data.get("on"))
                    if "stt" in data:
                        observe["stt"] = bool(data.get("stt"))
                    # КОРОТКИЕ КУСКИ ДЛЯ НЕПРЕРЫВНОЙ РЕЧИ (2026-07-28).
                    # Разговор человека с ней сам режется паузами, и предел
                    # в 25 секунд не срабатывает почти никогда. Ютубер или
                    # кино не молчат вообще: сегмент дорастает до предела,
                    # GigaAM видит кусок длиннее двадцати секунд, лезет в
                    # longform, спотыкается об отсутствующий pyannote и режет
                    # сам — и всё это время на экране пусто. Восемь секунд:
                    # текст идёт заметно чаще, longform не трогаем вовсе,
                    # а фраза почти никогда не рвётся посередине, потому что
                    # пауза в 400мс между предложениями всё-таки бывает.
                    try:
                        if observe["on"]:
                            stt.vad.max_segment_s = 8
                            stt.vad.silence_ms = 420
                        else:
                            v = CFG.get("stt.vad", {}) or {}
                            stt.vad.max_segment_s = v.get("max_segment_s", 25)
                            stt.vad.silence_ms = v.get("silence_ms", 700)
                            # ХВОСТ. Выключили прослушивание — в буфере VAD
                            # осталась недоговорённая фраза. Раньше она там и
                            # умирала: «в конце вообще не пишет».
                            for r in (stt.flush() or []):
                                r["stt_ms"] = 0
                                r["heard_at"] = time.strftime("%H:%M:%S")
                                r["_heard_mono"] = time.monotonic()
                                voice_phrase(r)
                    except Exception as e:
                        log.warning("Не смогла перенастроить нарезку: %s", e)
                    log.info("Режим прослушивания: отвечать %s, распознавать %s",
                             "нет" if observe["on"] else "да",
                             "да" if observe["stt"] else "нет")
                    out.put({"type": "observe", **observe})
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
        stop_event_all.set()
        try:
            hear_q.put_nowait(None)
            try:
                seg_q.put_nowait(None)
            except Exception:
                pass
        except Exception:
            pass
        EVENT_CLIENTS.discard(out)
        # вкладку закрыли посреди живого общения (юзер был активен последние
        # 10 минут) — запоминаем; отреагирует при следующем открытии
        if LAST_USER["seen"] and time.time() - LAST_USER["ts"] < 600:
            TAB_CLOSED["ts"] = time.time()
        out.put(None)
        send_task.cancel()


def _handspc_port():
    url = CFG.get("tools.handspc_url", "http://127.0.0.1:8767")
    return urlparse(url).port or 8767


def _close_handspc():
    """HandsPC — отдельная программа (папка HandsPC/ внутри проекта), не дочерний
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

    # ВЕРНУТЬ ОКНО (2026-08-14): если человек оставил окно с моделью
    # открытым, после перезапуска оно должно открыться снова — вместе с
    # тем положением, размером и замком, что он выставил.
    try:
        from server import desk_avatar as _da
        _da.autostart()
    except Exception as e:
        log.debug("окно на столе не поднялось: %s", e)

    # ПОДКЛЮЧИТЬ ВСЁ, ПОД ЧТО ЕСТЬ КЛЮЧ (2026-08-13, владелец: «все
    # подключай, всё познаётся в сравнении — главный принцип этой
    # системы»). Ключ в secrets.json больше не лежит мёртвым грузом в
    # ожидании, пока человек нажмёт «Сохранить и включить»: есть ключ —
    # есть мозг в общем списке. Без батников и галочек, ровно тот смысл,
    # ради которого установка и затевалась.
    try:
        from server.llm import autoconnect as _ac
        _r = _ac.connect_all()
        if _r["added"]:
            log.info("Подключила сама: %s", ", ".join(_r["added"]))
    except Exception as e:
        log.debug("автоподключение провайдеров не вышло: %s", e)

    # БРАУЗЕР ЧЕЛОВЕКА — САМИ (2026-08-13, замечание владельца: «нафиг ты
    # мне опять подсовываешь батник»). Всё, что можно сделать без него,
    # делаем без него: Chrome не запущен — поднимаем сразу с отладочным
    # портом, и он уже управляемый, человек ничего не заметил. Запущен без
    # порта — молча перезапускать чужие вкладки нельзя, это его решение:
    # Сайка скажет словами и дождётся согласия.
    # …И ДЕЛАЕМ ЭТО В ФОНЕ (2026-08-14, владелец: «давай ускорим до предела
    # запуск»). Запуск Chrome с отладочным портом — это секунды, а к первому
    # слову он не нужен вообще: ни голосу, ни слуху, ни мозгам. Всё, что не
    # нужно для первой фразы, обязано уйти с дороги.
    def _chrome_bg():
        try:
            from server import browser_hands as _bh
            _note = _bh.autoattach()
            if _note:
                broadcast_event({"type": "baymax", "mood": "meh",
                                 "text": "🌐 " + _note})
        except Exception as _e:
            log.debug("автоподключение к Chrome: %s", _e)
    threading.Thread(target=_chrome_bg, daemon=True, name="chrome").start()

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
        # «без слуха» — осознанный выбор, а не поломка (2026-07-27): не
        # пробуем цепочку и не жалуемся в дев-доску, иначе автопуск бодро
        # поднимет GigaAM «на замену» тому, от чего человек отказался
        if CFG.get("stt.engine", "off") in ("", "none", "off"):
            log.info("Автопуск: слух выключен в настройках — не гружу")
            return
        stt_chain = [CFG.get("stt.engine", "gigaam")]
        for n in CFG.get("stt.fallback_order", []):
            if n not in stt_chain:
                stt_chain.append(n)
        stt_chain.sort(key=lambda n: -_manual.get(n, 0))
        _try_chain("stt", stt_chain, stt.load_engine)

    # СТРАЖ ПЕТЛИ КРАШЕЙ — ДО ВСЯКОЙ ЗАГРУЗКИ ГОЛОСА (2026-08-14). Смотрим
    # хлебную крошку: если прошлый старт умер на загрузке движка, второй
    # раз туда не лезем. Иначе получается ровно то, что было у владельца —
    # три перезапуска подряд с одним и тем же нативным обвалом.
    try:
        # tts здесь — ЭКЗЕМПЛЯР TTSManager, а страж живёт в модуле
        from server.tts import manager as _ttsmod
        _tts_note = _ttsmod.crash_guard()
        if _tts_note:
            log.warning("%s", _tts_note)
            broadcast_event({"type": "baymax", "mood": "meh",
                             "text": "🔇 " + _tts_note})
    except Exception as _e:
        log.debug("страж крашей озвучки: %s", _e)

    # РЕВИЗИЯ СВЯЗНОСТИ (2026-08-15). Умение объявлено в реестре, руки для
    # него написаны — а в набор схем не попали: ровно так look_screen
    # пролежал невидимым полгода, и Сайка честно отвечала «я не могу
    # видеть экран». Проверка стоит миллисекунды и снимает целый класс
    # тихих поломок: «умею на бумаге, не умею на деле».
    def _boot_audit():
        try:
            from server import routing as _rt
            for bad in _rt.audit():
                log.error("РЕВИЗИЯ: %s", bad["human"])
                report_problem("умения", bad["human"], bad["cure"])
        except Exception as e:
            log.debug("ревизия умений пропущена: %s", e)
    threading.Thread(target=_boot_audit, daemon=True,
                     name="caps_audit").start()

    def _boot_tts():
        # то же для голоса: «без озвучки» не должно превращаться в
        # «раз молчит — поднимем следующий по списку»
        if CFG.get("tts.engine", "qwen3") == "off":
            log.info("Автопуск: озвучка выключена в настройках — не гружу")
            return
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

    # тёплое облако для «быстрого мышления»: токен GigaChat обновляется в
    # фоне, чтобы переключение на умную модель не платило за вход
    threading.Thread(target=llm.keep_cloud_warm, daemon=True,
                     name="keep_cloud_warm").start()
    # полный справочник инструментов (data/tools_guide.md) — для дообучения,
    # внешнего RAG и людей; из живых схем, потому не протухает
    def _write_guide():
        time.sleep(20)                 # HandsPC успевает отдать свои схемы
        try:
            from server.llm import tools as _t
            _t.write_guide()
        except Exception as e:
            log.debug("справочник не записался: %s", e)
    threading.Thread(target=_write_guide, daemon=True).start()
    # ═══ ПОРЯДОК ЗАПУСКА (2026-08-14, слова владельца) ═══
    # «стартуй визуал параллельно сразу; ттс запускай [первым], т.к. квен
    #  дольше всего раздупляет; слух у неё очень быстро запускается, так
    #  что это следующим; и ставим в ответ первую ллм, которая в рейтинге —
    #  она онлайн, должно всё достаточно быстро получиться»
    #
    # Отсюда ровно три правила:
    #   1. Ничто не ждёт друг друга. Голос, слух и мозги — три независимых
    #      потока, и ни один не держит остальные.
    #   2. ГОЛОС ПЕРВЫМ. qwen3-TTS компилируется дольше всех, значит и
    #      очередь занимает первым — пока он греется, лёгкая времянка уже
    #      отвечает. Слух встаёт за секунды, ему очередь не нужна.
    #   3. Мозги — тоже отдельным потоком. Раньше они грузились В ЭТОМ
    #      потоке, и любая заминка (перебор локальных моделей, прогрев,
    #      таймаут провайдера) держала весь автопуск. Первой берётся
    #      верхняя по рейтингу; если она облачная — переключение стоит
    #      миллисекунды, и Сайка готова отвечать раньше, чем догрелся голос.
    _t_boot = time.monotonic()
    threads = [threading.Thread(target=f, daemon=True, name=f.__name__)
               for f in (_boot_tts, _boot_stt)]
    for t in threads:
        t.start()
        time.sleep(0.05)          # только чтобы порядок в логе был читаем

    # мозги: ПО РЕЙТИНГУ, лучшая — первая (решение владельца 2026-07-23:
    # «модель, которая по рейтингу выше всего, должна быть самой первой на
    # автоматическую загрузку»). Рейтинг = ручная оценка владельца (палочки
    # в UI, синхронизируются через /api/ratings/manual) — она ПЕРЕБИВАЕТ
    # авто-скоростную, ровно как в списке UI (effScore). Без ручной оценки —
    # авто-балл из замеров ток/с. Последний выбор из config — только
    # тайбрейк при равном рейтинге, очередь он больше не перепрыгивает.
    # ВАЖНО: "locallm" (свой llama.cpp/transformers движок) — полноправный
    # бэкенд наравне с ollama/lmstudio (был забыт тут, исправлено 2026-07-22).
    # "llamacpp" (свой нативный llama-server, 2026-07-27) — туда же: его
    # спавнер сам скачает бинарь и поднимет процесс, поэтому никакой
    # отдельной команды руками для него не нужно, он участвует в общем
    # отборе по рейтингу наравне с остальными.
    BACKENDS_AUTOSTART = ("ollama", "lmstudio", "locallm", "llamacpp")

    def _boot_llm():
      try:
          tps = ratings.llm_tps()
          manual = ratings.manual_scores()
          cands = [(m["backend"], m["name"]) for m in llm.list_models()
                   if m["backend"] in BACKENDS_AUTOSTART
                   and "embed" not in m["name"].lower()]
          cfg_pick = (CFG.get("llm.backend", "ollama"), CFG.get("llm.model", ""))

          # ОБЛАКО ТОЖЕ УЧАСТВУЕТ (2026-08-14). Раньше в отборе были только
          # локальные бэкенды — а у владельца полтора десятка облачных
          # моделей с живыми ключами, и все они при старте не
          # рассматривались вовсе. «Самые первые по рейтингу» просто не
          # могли загрузиться: их не было в списке кандидатов.
          try:
              from server.llm import brains as _bb
              for _c in _bb._cloud_candidates():
                  _pair = ("cloud", _c["model"])
                  if _pair not in cands:
                      cands.append(_pair)
          except Exception as _e:
              log.debug("облачные мозги в автопуск не попали: %s", _e)

          def _eff(backend, name):
              """Ум: ручная оценка владельца → таблица лестницы → скорость.

              Скорость СТОИТ ПОСЛЕДНЕЙ и только как запасной вариант для
              модели, которой нет в таблице. Быстрая четырёхмиллиардная
              модель не умнее медленной семидесятимиллиардной, а до
              2026-08-14 отбор считал ровно наоборот."""
              if name in manual:
                  return int(manual[name])
              try:
                  from server.llm import brains as _b2
                  return _b2.rank_of(name, backend)
              except Exception:
                  return ratings.score_of(tps.get(name, 0))

          def _recent(backend, name):
              try:
                  from server.llm import brains as _b3
                  return _b3.recent_pos(backend, name)
              except Exception:
                  return 99

          # при РАВНОМ уме первым берём того, с кем работали последним:
          # это привычка владельца, а не случайный сосед по таблице
          cands.sort(key=lambda c: (-_eff(c[0], c[1]), _recent(c[0], c[1]),
                                    -tps.get(c[1], 0),
                                    0 if c == cfg_pick else 1))
          log.info("Автопуск, порядок по уму: %s", ", ".join(
              f"{b}/{m}({_eff(b, m)})" for b, m in cands[:6]))
          for backend, model in cands:
              try:
                  # ОБЛАЧНАЯ ПЕРВОЙ — И ЭТО МГНОВЕННО (2026-08-14, владелец:
                  # «ставим в ответ первую ллм, которая в рейтинге, она
                  # онлайн — должно всё достаточно быстро получиться»).
                  # У каждой облачной модели свой адрес и свой ключ, поэтому
                  # переезжаем целиком, ровно как при клике в интерфейсе, —
                  # иначе Groq пошёл бы по адресу Mistral с чужим ключом.
                  # Ничего не грузится в память: готова отвечать сразу.
                  if backend == "cloud":
                      if not llm.use_cloud(model, None):
                          raise RuntimeError("нет ключа или адреса")
                      CFG.set("llm.backend", "cloud")
                      CFG.set("llm.model", model)
                      try:
                          from server.llm import brains as _b4
                          _b4.note_used("cloud", model)
                      except Exception:
                          pass
                      log.info("Автопуск: мозги — облако/%s (ум %s/10), "
                               "греть нечего, отвечаю сразу",
                               model, _eff("cloud", model))
                      break
                  if not llm.switch_model(backend, model)["ok"]:
                      raise RuntimeError("прогрев не удался")
                  CFG.set("llm.backend", backend)
                  CFG.set("llm.model", model)
                  log.info("Автопуск: мозги — %s/%s (ум %s/10, %.1f ток/с)",
                           backend, model, _eff(backend, model),
                           tps.get(model, 0))
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

    threads.append(threading.Thread(target=_boot_llm, daemon=True,
                                    name="_boot_llm"))
    threads[-1].start()

    # ждём все три и говорим ЧЕСТНОЕ ВРЕМЯ: без числа «ускорили» проверить
    # нечем, а глазами старт всегда кажется одинаково долгим
    for t in threads:
        t.join(timeout=600)
    log.info("Автопуск завершён за %.1fс (голос, слух и мозги грелись "
             "параллельно)", time.monotonic() - _t_boot)
    # ЗАСЕЧКА ЗДОРОВОГО ЗАПУСКА (2026-08-14). Это не статистика ради
    # статистики: именно она превращает диагноз Беймакса из «тут всё
    # гнилое» в «сломалось что-то одно и недавно». И она же отмечает, что
    # прошлое его лечение дожило до нормального старта, то есть помогло.
    try:
        from server import repairs as _rp
        _rp.note_healthy()
    except Exception as _e:
        log.debug("журнал починок: %s", _e)


def main():
    (ROOT / "logs").mkdir(exist_ok=True)
    dreampc.kill_stale()  # чистим детач-воркер с прошлого запуска (если завис)
    train_manager.kill_stale()  # то же для воркера дообучения
    from server.llm import locallm as _locallm
    _locallm.kill_stale()  # то же для воркера LocalLM
    # llama-server ОБЯЗАТЕЛЬНО глушим при старте (2026-07-27): процесс
    # переживает перезапуск Сайки, и новые флаги запуска (--swa-full,
    # окно, cache-reuse) иначе НИКОГДА не применяются — ensure_running
    # видит живой /health и радуется старому процессу со старыми флагами.
    # Ровно так два перезапуска подряд ничего не поменяли в таймингах.
    from server.llm import llamacpp as _llamacpp
    _llamacpp.kill_stale()
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
    # ОТПЕЧАТОК ГОЛОСА (2026-07-28): свой рабочий поток, поднимается сразу —
    # он лёгкий и пустой, пока в микрофон не заговорили. Эхо из колонок в
    # него не пускаем: её собственный голос образовал бы «ещё одного
    # человека» в пространстве голосов (тот же случай, что и с STT — см.
    # _echo_risk в вебсокете).
    def _vp_echo():
        if CFG.get("stt.echo_guard", True) is False:
            return False
        if CFG.get("tts.headphones", False):
            return False
        tail = float(CFG.get("stt.echo_tail_s", 0.9))
        return (time.time() - AUDIO_LEVEL.get("ts", 0.0)) < tail
    try:
        voiceprint.start(sink=broadcast_event, echo_guard=_vp_echo)
        # печать голоса создателя: на чужой машине распечатывается сама,
        # если рядом переносной secrets.json с ключом
        voiceprint.load_owner_seal()
        atexit.register(voiceprint.stop)
    except Exception as e:
        report_problem("voiceprint", str(e), "работаю без узнавания голосов")

    # ЗАЩИТА ЖЕЛЕЗА (2026-07-28, история с ПК товарища: гемма набирала 11 из
    # 12 ГБ VRAM, и через 10–20 минут комп ГАС — похоже на защиту БП или
    # перегрев). Чёрный ящик пишет температуру и память с fsync, а при
    # критических порогах Сайка сама выгружает всё тяжёлое: лучше минуту
    # посидеть без мозгов, чем уронить весь компьютер под нагрузкой.
    def _guard_warn(g):
        broadcast_event({"type": "guard", "level": "warn",
                         "temp": g.get("temp"),
                         "vram": round(g.get("vram_frac", 0) * 100)})
    def _guard_crit(g):
        broadcast_event({"type": "guard", "level": "critical",
                         "temp": g.get("temp"),
                         "vram": round(g.get("vram_frac", 0) * 100)})
        # та же жёсткая разгрузка, что по кнопке «Выгрузить всё из
        # памяти». Мы в потоке защиты, событийного цикла тут нет — просто
        # запускаем корутину в свежем цикле этого потока.
        try:
            asyncio.run(panic_unload())
        except Exception as e:
            log.warning("Защитная выгрузка не удалась: %s", e)
    try:
        GUARD.start(on_warn=_guard_warn, on_critical=_guard_crit)
        atexit.register(GUARD.stop)
        _aut = GUARD.autopsy()
        if _aut:
            log.warning(_aut)
            report_problem("железо", _aut, "смотри пороги в guard.*")
    except Exception as e:
        log.warning("Защита железа не поднялась: %s", e)
    # досье на модели заводим в фоне: list_models() опрашивает Ollama и LM
    # Studio по сети, в главном потоке это задержало бы старт
    def _sync_dossier():
        time.sleep(6)
        try:
            from server import model_dossier
            model_dossier.sync_all()
        except Exception as e:
            log.debug("синхронизация досье моделей: %s", e)
    threading.Thread(target=_sync_dossier, daemon=True).start()
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
            # ВОСЕМЬ СЕКУНД ТИШИНЫ НА ХОЛОДНОМ СТАРТЕ (2026-08-14,
            # владелец: «стартуй визуал параллельно сразу»). Защёлка нужна
            # только при ПЕРЕзапуске, когда старая вкладка переподключается
            # за 1-2 секунды. На первом запуске ждать некого — а ждали
            # всё равно, и человек восемь секунд смотрел в пустоту.
            # Полторы секунды покрывают переподключение с запасом.
            for _ in range(15):  # 15 × 0.1с = 1.5с
                if EVENT_CLIENTS:
                    log.info("Вкладка уже открыта (переподключилась) — "
                             "новую не открываю")
                    return
                time.sleep(0.1)
            # 0.0.0.0 — это «слушать на всех интерфейсах», а НЕ адрес, по
            # которому можно зайти: браузер отвечает ERR_ADDRESS_INVALID
            # (живой случай 2026-07-26, сразу после включения доступа с
            # телефона). Себе всегда открываем петлю.
            _h = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
            _s = "http"
            try:
                from server import phone as _ph
                if _ph.https_on():
                    _s = "https"
            except Exception:
                pass
            webbrowser.open(f"{_s}://{_h}:{port}")

        threading.Thread(target=_open_if_no_tab, daemon=True).start()
    # запоминаем РЕАЛЬНЫЙ адрес прослушки: панель телефона по нему поймёт,
    # что тумблер включён, а сервер ещё не перезапущен
    try:
        from server import phone as _ph
        _ph.BOUND_HOST = host
    except Exception:
        pass
    # в лог пишем адрес, по которому РЕАЛЬНО можно зайти, а не 0.0.0.0
    _mine = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    _sch = "http"
    try:
        from server import phone as _phl
        if _phl.https_on():
            _sch = "https"
    except Exception:
        pass
    if host in ("0.0.0.0", "::"):
        log.info("Сайка слушает ВСЕ интерфейсы (доступ с телефона включён). "
                 "Себе: %s://%s:%s", _sch, _mine, port)
    else:
        log.info("Сайка запускается на %s://%s:%s", _sch, host, port)
    # отметка «стек поднялся»: doctor.py --fast видит свежую метку и
    # пропускает полный осмотр (полный — после падения или раз в сутки)
    try:
        (ROOT / "logs" / "boot_ok.json").write_text(
            json.dumps({"ts": time.time()}), encoding="utf-8")
    except Exception:
        pass
    # HTTPS, если включён и сертификат на месте. Без него микрофон с
    # телефона не поднять: браузеры отдают navigator.mediaDevices только в
    # защищённом контексте (https или localhost).
    ssl_kw = {}
    try:
        from server import phone as _ph
        if _ph.https_on():
            _crt, _key = _ph._cert_paths()
            ssl_kw = {"ssl_certfile": str(_crt), "ssl_keyfile": str(_key)}
            log.info("Сайка поднимается по HTTPS (самоподписанный "
                     "сертификат) — микрофон с телефона заработает")
    except Exception as e:
        log.warning("HTTPS не включился: %s", e)
    uvicorn.run(app, host=host, port=port, log_level="warning", **ssl_kw)


if __name__ == "__main__":
    main()
