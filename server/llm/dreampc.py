"""Спавнер воркера DreamPC (диффузионная LLaDA-8B) — отдельный процесс/venv,
по образцу server/stt/external.py, но не привязан к STTEngine (это не STT).

- venv есть -> запускаем воркер (если ещё не жив) и ждём /health
- venv нет  -> открываем окно установщика (setup/install_dreampc.bat) один раз
  и честно падаем — UI покажет ошибку, повторный клик после установки заведёт
"""
import logging
import os
import subprocess
import time

from server.config import CFG, resolve

log = logging.getLogger("saika.dreampc")

_proc = None
_setup_started = False


def _cfg():
    return CFG.get("dreampc", {})


def _url(path):
    return f"http://127.0.0.1:{_cfg().get('port', 8768)}{path}"


def _alive():
    import requests
    try:
        return requests.get(_url("/health"), timeout=2).ok
    except Exception:
        return False


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
    port = _cfg().get("port", 8768)
    try:
        import psutil
    except Exception:
        return
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            conns_fn = getattr(proc, "net_connections", None) or proc.connections
            conns = conns_fn(kind="inet")
        except Exception:
            continue
        for c in conns:
            if (c.laddr and c.laddr.port == port
                    and c.status == psutil.CONN_LISTEN):
                log.info("dreampc: убиваю зависший воркер с прошлого "
                         "запуска (pid %s)", proc.info.get("pid"))
                try:
                    proc.kill()
                except Exception:
                    pass
                break


def ensure_running() -> dict:
    """Возвращает {"ok":True,"port":N} либо {"error":"..."}."""
    global _proc, _setup_started
    cfg = _cfg()
    port = cfg.get("port", 8768)

    if _alive():
        return {"ok": True, "port": port}

    venv_py = _venv_python()
    if not venv_py.exists():
        setup = resolve(cfg.get("setup", "setup/install_dreampc.bat"))
        if os.name == "nt" and setup.exists():
            if not _setup_started:
                _setup_started = True
                subprocess.Popen(["cmd", "/c", "start",
                                  "Установка DreamPC", str(setup)])
            return {"error": "окружения ещё нет — открыл окно установки. "
                              "Когда закончится, нажми 🧪 ещё раз."}
        return {"error": f"нет окружения ({venv_py.parent.parent}) — "
                          f"запусти {cfg.get('setup', 'установщик')}"}

    worker = resolve(cfg.get("worker", "workers/dreampc_worker.py"))
    model = cfg.get("model", "GSAI-ML/LLaDA-8B-Instruct")
    cmd = [str(venv_py), str(worker), "--port", str(port), "--model", model]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log.info("dreampc: запускаю воркер: %s", " ".join(cmd))
    _proc = subprocess.Popen(cmd, cwd=str(resolve(".")), creationflags=flags)

    deadline = time.time() + 60
    while time.time() < deadline:
        if _alive():
            return {"ok": True, "port": port}
        if _proc.poll() is not None:
            return {"error": f"воркер упал при старте (код {_proc.returncode}), "
                              "см. logs/dreampc_worker.log"}
        time.sleep(1)
    # не ответил за минуту — не обязательно ошибка: первый запуск может
    # качать модель (~16 ГБ) в фоне, /health отвечает сразу, но раз не
    # отвечает вовсе — процесс, видимо, ещё поднимается
    return {"ok": True, "port": port,
            "note": "воркер стартует, первая загрузка модели может занять время"}
