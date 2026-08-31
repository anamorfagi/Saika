"""Спавнер + автопочинка воркера дообучения (train_worker.py).

Тот же паттерн, что и у DreamPC (anamorf/llm/dreampc.py): venv нет -> тихая
фоновая установка + поллинг прогресса; воркер жив, но окружение сломано ->
автопереустановка (до MAX_AUTO_REPAIRS раз); временные проблемы (сеть) не
считаются проблемой окружения — тут дело серьёзнее, чем у DreamPC (нет
смысла ретраить внутри воркера, обучение — разовая долгая операция), поэтому
ошибки просто показываются пользователю с понятной причиной.
"""
import logging
import os
import subprocess
import threading
import time

from anamorf.config import CFG, resolve
from anamorf.proc_utils import kill_by_port

log = logging.getLogger("saika.train")

_proc = None
_install_proc = None
_install_log = None
_fail_streak = 0
_lock = threading.Lock()

MAX_AUTO_REPAIRS = 2
ENV_ERROR_SIGNS = ("cuda", "could not load this library", "no module named",
                   "cannot import name", "cannot import", ".dll", ".pyd",
                   "no module named 'unsloth'")


def _cfg():
    return CFG.get("training", {})


def _url(path):
    return f"http://127.0.0.1:{_cfg().get('port', 8769)}{path}"


def _get(path, timeout=2):
    import requests
    try:
        r = requests.get(_url(path), timeout=timeout)
        return r.json() if r.ok else None
    except Exception:
        return None


def _post(path, payload, timeout=10):
    import requests
    try:
        r = requests.post(_url(path), json=payload, timeout=timeout)
        return r.json(), r.status_code
    except Exception as e:
        return {"error": str(e)}, 599


def _health():
    return _get("/health")


def _venv_python():
    venv = resolve(_cfg().get("venv", ".venv_train"))
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def kill_stale():
    """Убить зависший с прошлого запуска воркер (см. dreampc.kill_stale)."""
    # ЖИВОГО СОСЕДА НЕ УБИВАЕМ (2026-08-25, аудит). Раньше kill_stale слепо
    # снимал ЛЮБОЙ процесс на порту. Если запущены две копии Сайки (исходник
    # и собранный билд), старт одной убивал воркер другой, тот поднимал свой
    # — и два тяжёлых воркера дрались за карту. Теперь: отвечает здоровым
    # health — значит он либо наш с прошлого раза, либо чужой рабочий; не
    # трогаем, ensure_running его подхватит. Убиваем только молчащий (завис).
    try:
        if _health() is not None:
            return
    except Exception:
        pass
    kill_by_port(_cfg().get("port", 8769), "зависший воркер обучения")


def _looks_like_env_problem(text: str) -> bool:
    t = (text or "").lower()
    return any(s in t for s in ENV_ERROR_SIGNS)


def install_status() -> dict:
    running = _install_proc is not None and _install_proc.poll() is None
    tail = ""
    if _install_log is not None and _install_log.exists():
        try:
            lines = _install_log.read_text(encoding="utf-8", errors="ignore").splitlines()
            tail = "\n".join(lines[-25:])
        except Exception:
            pass
    done = _install_proc is not None and _install_proc.poll() is not None
    ok = done and _install_proc.returncode == 0
    return {"running": running, "done": done, "ok": ok, "log_tail": tail}


def _start_install():
    global _install_proc, _install_log
    main_py = resolve(".venv/Scripts/python.exe" if os.name == "nt"
                      else ".venv/bin/python")
    script = resolve("setup/install_train.py")
    _install_log = resolve("logs") / "train_install.log"
    _install_log.parent.mkdir(exist_ok=True)
    logf = open(_install_log, "w", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log.info("train: запускаю автоустановку/автопочинку окружения в фоне")
    _install_proc = subprocess.Popen(
        [str(main_py), str(script)], cwd=str(resolve(".")),
        stdout=logf, stderr=subprocess.STDOUT, creationflags=flags)


def _handle_worker_error(err: str) -> dict:
    global _fail_streak
    if not _looks_like_env_problem(err):
        return {"error": err}
    if _fail_streak >= MAX_AUTO_REPAIRS:
        return {"error": f"автопочинка окружения пробовала {_fail_streak} "
                          f"раз(а) и не помогла — похоже, дело не в venv "
                          f"обучения: {err}"}
    _fail_streak += 1
    log.warning("train: похоже на проблему окружения (%s) — автопочинка, "
               "попытка %s/%s", err, _fail_streak, MAX_AUTO_REPAIRS)
    kill_stale()
    _start_install()
    return {"ok": True, "installing": True,
            "note": "нашла проблему окружения, переустанавливаю автоматически"}


def ensure_running() -> dict:
    global _proc, _install_proc, _fail_streak
    with _lock:
        cfg = _cfg()
        port = cfg.get("port", 8769)

        if _install_proc is not None:
            code = _install_proc.poll()
            if code is None:
                return {"ok": True, "installing": True,
                        "note": "устанавливаю/чиню окружение обучения — "
                                "первый раз может занять 5-10 минут"}
            _install_proc = None
            if code != 0:
                return {"error": f"автоустановка не справилась (код {code}) "
                                  "— смотри logs/train_install.log"}
            _fail_streak = 0

        health = _health()
        if health is not None:
            _fail_streak = 0
            return {"ok": True, "port": port}

        venv_py = _venv_python()
        if not venv_py.exists():
            _start_install()
            return {"ok": True, "installing": True,
                    "note": "окружения ещё нет — ставлю автоматически "
                            "(unsloth + связка torch/xformers/bitsandbytes, "
                            "первый раз небыстро)"}

        worker = resolve(cfg.get("worker", "workers/train_worker.py"))
        cmd = [str(venv_py), str(worker), "--port", str(port)]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log.info("train: запускаю воркер: %s", " ".join(cmd))
        _proc = subprocess.Popen(cmd, cwd=str(resolve(".")), creationflags=flags)

        deadline = time.time() + 60
        while time.time() < deadline:
            h = _health()
            if h is not None:
                _fail_streak = 0
                return {"ok": True, "port": port}
            if _proc.poll() is not None:
                return {"error": f"воркер обучения упал при старте (код "
                                  f"{_proc.returncode}), см. "
                                  "logs/train_worker.log"}
            time.sleep(1)
        return {"error": "воркер обучения не ответил за 60 секунд при старте"}


def start_training(payload: dict):
    return _post("/start", payload)


def training_status():
    return _get("/status") or {"error": "воркер не отвечает"}


def stop_training():
    return _post("/stop", {})


def export_gguf(payload: dict):
    return _post("/export_gguf", payload, timeout=5)


def stop_worker():
    """Погасить СВОЙ воркер при выходе Сайки (2026-08-25, аудит). Воркер —
    детач-процесс и переживает закрытие окна: без явного terminate он висел
    в памяти гигабайтами до следующего старта. Гасим только свой (_proc),
    чужого (второй экземпляр) не трогаем — им займётся его собственный
    выход."""
    global _proc
    try:
        if _proc is not None and _proc.poll() is None:
            _proc.terminate()
            try:
                _proc.wait(timeout=3)
            except Exception:
                try:
                    _proc.kill()
                except Exception:
                    pass
    except Exception:
        pass
    _proc = None
