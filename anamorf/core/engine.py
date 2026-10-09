"""ДВИЖОК — ОДИН ВЛАДЕЛЕЦ (Архитектура v2, §2.5).

Старый слой (llamacpp.py + vramplan + triage + keeper + автопуск) решал
про llama-server сразу пятью головами: окно «плавало» по свободной
памяти, сервер перезапускался посреди разговора. Здесь всё наоборот:
  * профиль ФИКСИРОВАННЫЙ (core.engine.* в config.json), без автоподбора;
  * свой порт (8781) — старые сторожа его не видят и не трогают;
  * перезапуск только если изменился профиль или процесс умер;
  * кэш слота пишется на диск после ответа и поднимается при старте —
    первая реплика после запуска не платит полный пересчёт промпта.
"""
import hashlib
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import requests

from anamorf.config import CFG, resolve

log = logging.getLogger("saika.core.engine")
_LOCK = threading.RLock()
_PROC = {"p": None, "sig": ""}

# ── ПРОФИЛЬ ПО УМОЛЧАНИЮ: замерен 09.10.2026 на 4070 Ti Super 16 ГБ + 47 ГБ ОЗУ
# (≈30 ток/с генерация, ≈1400 ток/с разбор, ~1 с до первого слова на тёплом кэше)
DEFAULTS = {
    "model": "models/gguf/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf",
    "mmproj": "models/gguf/mmproj-Qwen3.6-35B-A3B-BF16.gguf",
    "port": 8781,
    "ctx": 32768,            # промпт ядра v2 ~4-6 тыс. токенов, остальное — история
    "n_cpu_moe": 32,         # эксперты 32 из 40 слоёв в ОЗУ, на карте ~5.4 ГБ весов
    "batch": 2048, "ubatch": 2048,   # крупная пачка = меньше перекачки экспертов
    "ctx_checkpoints": 32, "checkpoint_step": 512,   # гибридная модель: откат кэша не в ноль
    "kv": "q8_0",
    "chat_template_file": "",        # агентный шаблон Qwen, если положен в models/
    "extra": [],
}


def cfg() -> dict:
    d = dict(DEFAULTS)
    d.update(CFG.get("core.engine", {}) or {})
    return d


def url() -> str:
    return f"http://127.0.0.1:{int(cfg()['port'])}"


def _path(p: str) -> str:
    return str(resolve(p)) if p and not os.path.isabs(p) else (p or "")


def _args(c: dict) -> list:
    from anamorf.llm import llamacpp as _old      # только чтобы найти бинарник
    a = [str(_old.binary()),
         "-m", _path(c["model"]),
         "--host", "127.0.0.1", "--port", str(int(c["port"])),
         "--alias", "saika-core",
         # два слота: 0 — разговор (его префикс живёт), 1 — служебное
         # (глаза, сводки). Каждому СВОЯ память, ctx на слот = c["ctx"].
         # БЫЛО --kv-unified (общий кэш) — стенд v2g, 09.10: у гибридной
         # Qwen3.6 запрос глаз в слоте 1 обнулял слот 0, и следующий ход
         # пересчитывал 10 тыс. токенов (11 с). KV у неё ~10 КБ/токен —
         # удвоить окно дешевле, чем терять кэш.
         "--ctx-size", str(int(c["ctx"]) * 2), "--parallel", "2",
         "-ngl", "999", "--n-cpu-moe", str(int(c["n_cpu_moe"])),
         "-fa", "on", "--no-mmap",
         "--batch-size", str(int(c["batch"])), "--ubatch-size", str(int(c["ubatch"])),
         "--ctx-checkpoints", str(int(c["ctx_checkpoints"])),
         "--checkpoint-min-step", str(int(c["checkpoint_step"])),
         "--cache-type-k", c["kv"], "--cache-type-v", c["kv"],
         "--jinja", "--reasoning-format", "deepseek", "--reasoning-budget", "0",
         "--slot-save-path", str(resolve("data/core_slots")),
         "--metrics"]
    mm = _path(c.get("mmproj", ""))
    if mm and os.path.exists(mm):
        a += ["--mmproj", mm]
    tpl = _path(c.get("chat_template_file", ""))
    if tpl and os.path.exists(tpl):
        a += ["--chat-template-file", tpl]
    return a + [str(x) for x in (c.get("extra") or [])]


def _sig(args: list) -> str:
    return hashlib.md5(json.dumps(args).encode()).hexdigest()[:10]


def healthy(timeout: float = 1.0) -> bool:
    try:
        r = requests.get(url() + "/health", timeout=timeout)
        return r.ok and (r.json() or {}).get("status") == "ok"
    except Exception:
        return False


def _kill_port(port: int):
    """Чужой/зависший процесс на нашем порту — убрать (только по порту)."""
    try:
        from anamorf.proc_utils import kill_by_port
        kill_by_port(port, "llama-server ядра v2")
    except Exception:
        try:
            out = subprocess.run(["netstat", "-ano"], capture_output=True,
                                 text=True, timeout=10).stdout
            for ln in out.splitlines():
                if f"127.0.0.1:{port} " in ln and "LISTENING" in ln:
                    subprocess.run(["taskkill", "/F", "/PID", ln.split()[-1]],
                                   capture_output=True, timeout=10)
        except Exception as e:
            log.debug("порт %s не освободился: %s", port, e)


def ensure(wait_s: float = 120.0) -> bool:
    """Поднять движок, если он не жив или профиль поменялся. Идемпотентно."""
    with _LOCK:
        c = cfg()
        args = _args(c)
        sig = _sig(args)
        p = _PROC["p"]
        if p is not None and p.poll() is None and _PROC["sig"] == sig and healthy():
            return True
        if p is None and _PROC.get("adopted") == sig and healthy():
            return True                      # чужой процесс уже проверен
        if p is not None and p.poll() is None:
            log.info("ядро v2: профиль движка изменился — перезапуск")
            p.terminate()
            try:
                p.wait(10)
            except Exception:
                p.kill()
        elif healthy() and _PROC["p"] is None:
            # сервер ядра пережил перезапуск Сайки — проверяем, тот ли он
            try:
                m = requests.get(url() + "/v1/models", timeout=2).json()
                if (m.get("data") or [{}])[0].get("id") == "saika-core" \
                        and _read_sig() == sig:
                    _PROC["sig"] = sig
                    _PROC["adopted"] = sig
                    log.info("ядро v2: движок уже работает — беру его")
                    return True
            except Exception:
                pass
            _kill_port(int(c["port"]))
        os.makedirs(resolve("data/core_slots"), exist_ok=True)
        logf = open(resolve("logs/core_engine.log"), "ab")
        flags = 0x08000000 if os.name == "nt" else 0      # без окна консоли
        log.info("ядро v2: запускаю движок: %s", " ".join(args[1:]))
        _PROC["p"] = subprocess.Popen(args, stdout=logf, stderr=logf,
                                      creationflags=flags)
        _PROC["sig"] = sig
        _write_sig(sig)
        t0 = time.time()
        while time.time() - t0 < wait_s:
            if _PROC["p"].poll() is not None:
                log.error("ядро v2: движок упал при старте — logs/core_engine.log")
                return False
            if healthy():
                log.info("ядро v2: движок готов за %.1f с", time.time() - t0)
                restore_slot()
                return True
            time.sleep(0.5)
        log.error("ядро v2: движок не поднялся за %.0f с", wait_s)
        return False


def _sig_file() -> Path:
    return Path(resolve("logs/core_engine.sig"))


def _read_sig() -> str:
    try:
        return _sig_file().read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _write_sig(s: str):
    try:
        _sig_file().write_text(s, encoding="utf-8")
    except Exception:
        pass


# ── КЭШ СЛОТА НА ДИСК ────────────────────────────────────────────────
# После каждого ответа (в фоне) сохраняем KV-кэш слота в файл; при старте
# движка поднимаем его обратно. Промпт ядра стабилен, поэтому после
# перезапуска первая реплика попадает в кэш, а не пересчитывает 10 тыс.
# токенов (было 30 с на первой фразе).
_SLOT_FILE = "saika_core.bin"
_SAVE = {"busy": False, "ts": 0.0}


def complete(messages: list, max_tokens: int = 600, temperature: float = 0.3,
             timeout: float = 90) -> str:
    """Служебный запрос в слот 1 (сводки поиска, сжатие памяти). Разговор
    в слоте 0 не трогает: у каждого слота своя память (см. _args)."""
    body = {"model": "saika-core", "messages": messages, "id_slot": 1,
            "stream": False, "temperature": temperature,
            "max_tokens": max_tokens, "cache_prompt": True,
            "chat_template_kwargs": {"enable_thinking": False}}
    r = requests.post(url() + "/v1/chat/completions", json=body, timeout=timeout)
    r.raise_for_status()
    return ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""


def save_slot_async():
    if _SAVE["busy"] or time.time() - _SAVE["ts"] < 20:
        return
    def run():
        _SAVE["busy"] = True
        try:
            t0 = time.time()
            r = requests.post(url() + "/slots/0?action=save",
                              json={"filename": _SLOT_FILE}, timeout=60)
            if r.ok:
                log.info("ядро v2: кэш слота сохранён за %.1f с", time.time() - t0)
            else:
                log.info("ядро v2: кэш слота не сохранился: %s", r.text[:160])
        except Exception as e:
            log.debug("сохранение слота: %s", e)
        finally:
            _SAVE["busy"] = False
            _SAVE["ts"] = time.time()
    threading.Thread(target=run, daemon=True, name="core-slot-save").start()


def restore_slot():
    f = Path(resolve("data/core_slots")) / _SLOT_FILE
    if not f.exists():
        return
    try:
        t0 = time.time()
        r = requests.post(url() + "/slots/0?action=restore",
                          json={"filename": _SLOT_FILE}, timeout=120)
        log.info("ядро v2: кэш слота %s за %.1f с%s",
                 "поднят" if r.ok else "НЕ поднят", time.time() - t0,
                 "" if r.ok else ": " + r.text[:160])
    except Exception as e:
        log.info("ядро v2: кэш слота не поднялся: %s", e)


def stop():
    with _LOCK:
        p = _PROC["p"]
        if p is not None and p.poll() is None:
            p.terminate()
        _PROC["p"] = None
