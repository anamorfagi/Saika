"""Спавнер + автопочинка воркера DreamPC (диффузионная LLaDA-8B).

Полностью автономно: человек жмёт 🧪 в UI и просто смотрит на прогресс —
никаких консольных окон, никаких ручных команд.

- venv нет -> тихо (без окна) запускаем setup/install_dreampc.py в фоне,
  UI поллит /api/dreampc/install_status и видит прогресс.
- воркер жив, но здоров -> обычный запуск запроса.
- воркер жив, но /health вернул ошибку окружения (нет CUDA, битые DLL,
  ImportError и т.п.) -> сами убиваем воркер и запускаем переустановку
  (install_dreampc.py сам разберётся, что там сломано и снесёт/переставит).
  Временные проблемы (сеть до HF и т.п.) НЕ считаются проблемой окружения —
  воркер сам их перепробует при следующей генерации (см.
  workers/dreampc_worker.py, _try_load), тут ничего чинить не нужно.
- после MAX_AUTO_REPAIRS неудачных подряд автопочинок — прекращаем попытки
  и отдаём ошибку как есть, чтобы не долбить одно и то же вхолостую (если
  дело не в venv, а, например, в драйверах видеокарты)."""
import logging
import os
import subprocess
import threading
import time

from anamorf.config import CFG, resolve
from anamorf.proc_utils import kill_by_port

log = logging.getLogger("saika.dreampc")

_proc = None
_install_proc = None
_install_log = None
_fail_streak = 0
_lock = threading.Lock()

MAX_AUTO_REPAIRS = 2

# ключевые слова, по которым отличаем "проблема окружения" (лечится
# переустановкой) от временных проблем (сеть и т.п., лечатся сами).
# ВАЖНО: str(exception) НЕ включает имя класса исключения (ImportError,
# ModuleNotFoundError) — только текст сообщения. Ловили баг на
# "cannot import name 'is_offline_mode' from 'huggingface_hub'": ни
# "importerror", ни "modulenotfounderror" там не встречаются, и
# автопочинка эту ошибку игнорировала (2026-07-15). Матчим по реальным
# фразам, которые Python и torch/transformers пишут в текст сообщения.
ENV_ERROR_SIGNS = ("cuda", "could not load this library", "no module named",
                   "cannot import name", "cannot import", ".dll", ".pyd",
                   # transformers 5.x против remote-кода LLaDA (2026-07-23):
                   # реинсталл теперь ставит пин transformers==4.57.3 — само
                   # чинится именно переустановкой окружения
                   "all_tied_weights_keys")


def _cfg():
    return CFG.get("dreampc", {})


def _url(path):
    return f"http://127.0.0.1:{_cfg().get('port', 8768)}{path}"


def _health():
    """Распарсенный /health, либо None если воркер вообще не отвечает."""
    import requests
    try:
        r = requests.get(_url("/health"), timeout=2)
        return r.json() if r.ok else None
    except Exception:
        return None


def _venv_python():
    venv = resolve(_cfg().get("venv", ".venv_dreampc"))
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def kill_stale():
    """Убивает воркер, оставшийся от прошлого запуска Сайки (если есть).

    Воркер — детач-процесс (subprocess.Popen), закрытие консоли start.bat не
    гарантированно его убивает, поэтому без этой чистки пользователю
    приходилось вручную искать PID по порту и делать taskkill. Вызывается
    один раз при старте сервера (main.py) — так простой перезапуск start.bat
    всегда даёт свежий воркер с текущим кодом."""
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
    kill_by_port(_cfg().get("port", 8768), "зависший воркер DreamPC")


def _looks_like_env_problem(text: str) -> bool:
    t = (text or "").lower()
    return any(s in t for s in ENV_ERROR_SIGNS)


def install_status() -> dict:
    """Статус фоновой (пере)установки окружения — для прогресса в UI."""
    running = _install_proc is not None and _install_proc.poll() is None
    tail = ""
    if _install_log is not None and _install_log.exists():
        try:
            lines = _install_log.read_text(
                encoding="utf-8", errors="ignore").splitlines()
            tail = "\n".join(lines[-20:])
        except Exception:
            pass
    done = _install_proc is not None and _install_proc.poll() is not None
    ok = done and _install_proc.returncode == 0
    return {"running": running, "done": done, "ok": ok, "log_tail": tail}


def _start_install():
    """Запускает setup/install_dreampc.py тихо в фоне (без окна/pause),
    вывод — в logs/dreampc_install.log. Сам разберётся, что чинить."""
    global _install_proc, _install_log
    main_py = resolve(".venv/Scripts/python.exe" if os.name == "nt"
                      else ".venv/bin/python")
    script = resolve("setup/install_dreampc.py")
    _install_log = resolve("logs") / "dreampc_install.log"
    _install_log.parent.mkdir(exist_ok=True)
    logf = open(_install_log, "w", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log.info("dreampc: запускаю автоустановку/автопочинку окружения в фоне")
    _install_proc = subprocess.Popen(
        [str(main_py), str(script)], cwd=str(resolve(".")),
        stdout=logf, stderr=subprocess.STDOUT, creationflags=flags)


def worker_status() -> dict:
    """Что сейчас с воркером — для панели DreamPC, чтобы было видно «качаю /
    гружу / генерирую», а не глухое «проявляю…». Тянет health + хвост лога
    воркера (там строки скачивания весов с huggingface)."""
    h = _health()
    tail = ""
    p = resolve("logs") / "dreampc_worker.log"
    if p.exists():
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            # чистим шумные http-строки, оставляем осмысленные
            keep = [ln for ln in lines[-25:]
                    if "HTTP Request" not in ln][-8:]
            tail = "\n".join(keep)
        except Exception:
            pass
    if h is None:
        state = "воркер запускается…"
    elif h.get("error"):
        state = "ошибка: " + str(h["error"])[:200]
    elif h.get("model_loaded"):
        state = "модель загружена, генерирую…"
    else:
        state = "загружаю модель (первый раз качает веса ~14 ГБ)…"
    return {"model_loaded": bool(h and h.get("model_loaded")),
            "error": (h or {}).get("error"), "state": state, "log_tail": tail}


def _handle_worker_error(err: str) -> dict:
    global _fail_streak
    if not _looks_like_env_problem(err):
        # временная штука (сеть до HF и т.п.) — воркер сам перепробует
        # на следующей генерации, тут чинить нечего
        return {"error": err}
    if _fail_streak >= MAX_AUTO_REPAIRS:
        return {"error": f"автопочинка окружения пробовала {_fail_streak} "
                          f"раз(а) и не помогла — похоже, дело не в venv "
                          f"DreamPC: {err}"}
    _fail_streak += 1
    log.warning("dreampc: похоже на проблему окружения (%s) — "
               "автопочинка, попытка %s/%s", err, _fail_streak, MAX_AUTO_REPAIRS)
    kill_stale()
    _start_install()
    return {"ok": True, "installing": True,
            "note": "нашла проблему окружения, переустанавливаю автоматически"}


def ensure_running() -> dict:
    """Возвращает {"ok":True,"port":N} / {"ok":True,"installing":True,...}
    / {"error":"..."}."""
    global _proc, _install_proc, _fail_streak
    with _lock:
        cfg = _cfg()
        port = cfg.get("port", 8768)

        # 1) установка уже идёт или только что закончилась?
        if _install_proc is not None:
            code = _install_proc.poll()
            if code is None:
                return {"ok": True, "installing": True,
                        "note": "устанавливаю/чиню окружение — первый раз "
                                "может занять несколько минут"}
            _install_proc = None
            if code != 0:
                return {"error": f"автоустановка не справилась (код {code}) "
                                  "— смотри logs/dreampc_install.log"}
            _fail_streak = 0
            # провалимся дальше — установка прошла, запускаем воркер

        # 2) воркер уже жив?
        health = _health()
        if health is not None:
            if not health.get("error"):
                _fail_streak = 0
                return {"ok": True, "port": port}
            return _handle_worker_error(health["error"])

        # 3) venv вообще есть?
        venv_py = _venv_python()
        if not venv_py.exists():
            _start_install()
            return {"ok": True, "installing": True,
                    "note": "окружения ещё нет — ставлю автоматически "
                            "(первый раз небыстро: библиотеки + веса модели)"}

        # 4) спавним воркер и ждём /health
        worker = resolve(cfg.get("worker", "workers/dreampc_worker.py"))
        model = cfg.get("model", "GSAI-ML/LLaDA-8B-Instruct")
        cmd = [str(venv_py), str(worker), "--port", str(port), "--model", model,
               # 0 = воркер сам подберёт mask-токен по модели (см. MASK_IDS)
               "--mask-id", str(cfg.get("mask_id", 0))]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log.info("dreampc: запускаю воркер: %s", " ".join(cmd))
        _proc = subprocess.Popen(cmd, cwd=str(resolve(".")), creationflags=flags)

        deadline = time.time() + 60
        while time.time() < deadline:
            h = _health()
            if h is not None:
                if not h.get("error"):
                    _fail_streak = 0
                    return {"ok": True, "port": port}
                return _handle_worker_error(h["error"])
            if _proc.poll() is not None:
                return {"error": f"воркер упал при старте (код "
                                  f"{_proc.returncode}), см. "
                                  "logs/dreampc_worker.log"}
            time.sleep(1)
        return {"ok": True, "port": port,
                "note": "воркер стартует, первая загрузка модели может "
                        "занять время"}


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
