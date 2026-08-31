"""Спавнер + автопочинка воркера LocalLM («своя» LLM Сайки, без Ollama/LM
Studio). Полная копия проверенного паттерна DreamPC (anamorf/llm/dreampc.py,
там подробные комментарии к каждому решению):

- venv нет -> тихо запускаем setup/install_locallm.py в фоне;
- воркер жив и здоров -> отдаём порт;
- /health вернул ошибку окружения (CUDA/DLL/import) -> убиваем воркер и
  запускаем переустановку; временные проблемы (сеть до HF) не чиним —
  воркер сам перепробует при следующей генерации;
- после MAX_AUTO_REPAIRS неудач подряд — отдаём ошибку как есть.
"""
import logging
import os
import subprocess
import threading
import time

from anamorf.config import CFG, resolve
from anamorf.proc_utils import kill_by_port

log = logging.getLogger("saika.locallm")

_proc = None
_install_proc = None
_install_log = None
_fail_streak = 0
_lock = threading.Lock()

MAX_AUTO_REPAIRS = 2

# отличаем «проблему окружения» (лечится переустановкой) от временных;
# матчим по реальным фразам в тексте сообщений (см. комментарий в dreampc.py
# про то, почему тут нет имён классов исключений)
ENV_ERROR_SIGNS = ("cuda", "could not load this library", "no module named",
                   "cannot import name", "cannot import", ".dll", ".pyd")

DEFAULT_MODEL = "t-tech/T-lite-it-2.1"
DEFAULT_PORT = 8770

# Два движка за одним и тем же портом/контрактом (/health, /v1/models,
# /v1/chat/completions, /admin/unload) — менеджер и остальной код их не
# различают. "llamacpp" — быстрый путь (llama.cpp/GGUF, отдельный
# .venv_locallm_gguf, без torch). "transformers" — исходный путь
# (bitsandbytes nf4, тот же venv, что и раньше) — рабочий фолбэк, если
# под конкретную машину не нашлось готового CUDA-wheel для llama-cpp-python.
ENGINES = {
    "llamacpp": {
        "venv": ".venv_locallm_gguf",
        "worker": "workers/locallm_worker_gguf.py",
        "installer": "setup/install_locallm_gguf.py",
        "install_log": "logs/locallm_gguf_install.log",
        "worker_log": "logs/locallm_gguf_worker.log",
    },
    "transformers": {
        "venv": ".venv_locallm",
        "worker": "workers/locallm_worker.py",
        "installer": "setup/install_locallm.py",
        "install_log": "logs/locallm_install.log",
        "worker_log": "logs/locallm_worker.log",
    },
}


def _cfg():
    return CFG.get("locallm", {})


def _engine():
    name = _cfg().get("engine", "llamacpp")
    return ENGINES.get(name, ENGINES["llamacpp"])


def model_name() -> str:
    return _cfg().get("model", DEFAULT_MODEL)


def port() -> int:
    return _cfg().get("port", DEFAULT_PORT)


def base_url() -> str:
    return f"http://127.0.0.1:{port()}"


def _url(path):
    return base_url() + path


def _health():
    import requests
    try:
        r = requests.get(_url("/health"), timeout=2)
        return r.json() if r.ok else None
    except Exception:
        return None


def _venv_python():
    # ВСЕГДА берём venv из ENGINES по текущему engine, а не из
    # locallm.venv в конфиге — оставшийся там ключ от старой установки
    # (или случайно затёртый обратно живым процессом через Config.save(),
    # который пишет ВЕСЬ объект целиком — реальный инцидент 2026-07-22:
    # чинили руками config.json, пока старый процесс ещё работал, и он
    # затёр правку при первом же несвязанном CFG.set()) не должен иметь
    # приоритет над выбором движка — иначе engine="llamacpp" молча
    # запускается в venv транформерс-версии с чужими аргументами.
    venv = resolve(_engine()["venv"])
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def installed() -> bool:
    """Стоит ли окружение (для list_models: не показываем бэкенд, которого
    нет, чтобы не соблазнять UI пустышкой)."""
    return _venv_python().exists()


def kill_stale():
    """Убивает детач-воркер, оставшийся от прошлого запуска Сайки (вызов —
    из main.py при старте, рядом с dreampc.kill_stale())."""
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
    kill_by_port(port(), "зависший воркер LocalLM")


def _looks_like_env_problem(text: str) -> bool:
    t = (text or "").lower()
    return any(s in t for s in ENV_ERROR_SIGNS)


def install_status() -> dict:
    """Статус фоновой (пере)установки окружения."""
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
    global _install_proc, _install_log
    main_py = resolve(".venv/Scripts/python.exe" if os.name == "nt"
                      else ".venv/bin/python")
    eng = _engine()
    script = resolve(eng["installer"])
    _install_log = resolve(eng["install_log"])
    _install_log.parent.mkdir(exist_ok=True)
    logf = open(_install_log, "w", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log.info("locallm: запускаю автоустановку/автопочинку окружения в фоне")
    _install_proc = subprocess.Popen(
        [str(main_py), str(script)], cwd=str(resolve(".")),
        stdout=logf, stderr=subprocess.STDOUT, creationflags=flags)


def worker_status() -> dict:
    """Что сейчас с воркером — для UI/диагностики."""
    h = _health()
    tail = ""
    p = resolve(_engine()["worker_log"])
    if p.exists():
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            keep = [ln for ln in lines[-25:] if "HTTP Request" not in ln][-8:]
            tail = "\n".join(keep)
        except Exception:
            pass
    if h is None:
        state = "воркер запускается…"
    elif h.get("error"):
        state = "ошибка: " + str(h["error"])[:200]
    elif h.get("model_loaded"):
        state = "модель загружена"
    else:
        state = "загружаю модель (первый раз качает веса ~16 ГБ)…"
    return {"model_loaded": bool(h and h.get("model_loaded")),
            "error": (h or {}).get("error"), "state": state, "log_tail": tail}


def _handle_worker_error(err: str) -> dict:
    global _fail_streak
    if not _looks_like_env_problem(err):
        return {"error": err}
    if _fail_streak >= MAX_AUTO_REPAIRS:
        return {"error": f"автопочинка окружения пробовала {_fail_streak} "
                         f"раз(а) и не помогла — похоже, дело не в venv "
                         f"LocalLM: {err}"}
    _fail_streak += 1
    log.warning("locallm: похоже на проблему окружения (%s) — автопочинка, "
                "попытка %s/%s", err, _fail_streak, MAX_AUTO_REPAIRS)
    kill_stale()
    _start_install()
    return {"ok": True, "installing": True,
            "note": "нашла проблему окружения, переустанавливаю автоматически"}


def ensure_running() -> dict:
    """{"ok":True,"port":N} / {"ok":True,"installing":True,...} / {"error":…}."""
    global _proc, _install_proc, _fail_streak
    with _lock:
        prt = port()

        # 1) установка идёт или только что закончилась?
        if _install_proc is not None:
            code = _install_proc.poll()
            if code is None:
                return {"ok": True, "installing": True,
                        "note": "устанавливаю/чиню окружение — первый раз "
                                "может занять несколько минут"}
            _install_proc = None
            if code != 0:
                return {"error": f"автоустановка не справилась (код {code}) "
                                 "— смотри logs/locallm_install.log"}
            _fail_streak = 0

        # 2) воркер уже жив?
        health = _health()
        if health is not None:
            if not health.get("error"):
                _fail_streak = 0
                return {"ok": True, "port": prt}
            return _handle_worker_error(health["error"])

        # 3) venv есть?
        venv_py = _venv_python()
        if not venv_py.exists():
            _start_install()
            return {"ok": True, "installing": True,
                    "note": "окружения ещё нет — ставлю автоматически "
                            "(первый раз небыстро: библиотеки + веса модели)"}

        # 4) ОДИН ЛОКАЛЬНЫЙ ДВИЖОК НА ВИДЕОКАРТУ — разбор в one_local.py.
        # Живой лог 09:03: разговор шёл на llamacpp/gemma, а сюда пришли
        # поднимать T-lite 8B; через пять секунд VRAM 96% и защита снесла
        # голос, слух и мозги. Отказ здесь дешевле любой разгрузки потом.
        from anamorf.llm import one_local
        _no = one_local.refuse("locallm")
        if _no:
            return _no

        # 5) спавним воркер и ждём /health
        # worker тоже ВСЕГДА из ENGINES по engine — та же причина, что и
        # в _venv_python() выше (см. комментарий там).
        eng_name = _cfg().get("engine", "llamacpp")
        worker = resolve(_engine()["worker"])
        if eng_name == "llamacpp":
            g = CFG.get("locallm_gguf", {}) or {}
            cmd = [str(venv_py), str(worker), "--port", str(prt),
                   "--repo", g.get("repo", "mradermacher/Huihui-Qwen3.5-9B-abliterated-i1-GGUF"),
                   "--quant", g.get("quant", "Q4_K_M"),
                   "--n-ctx", str(g.get("n_ctx", 8192)),
                   "--kv-quant", str(g.get("kv_quant", "q8_0")),
                   # потолок длины ответа (кран для голосового режима:
                   # 58 ток/с * 2048 токенов = полминуты монолога; для
                   # «ответ за 3 сек» ставь в конфиге ~300)
                   "--max-tokens", str(_cfg().get("max_new_tokens", 2048))]
        else:
            cmd = [str(venv_py), str(worker), "--port", str(prt),
                   "--model", model_name(),
                   "--max-new-tokens", str(_cfg().get("max_new_tokens", 2048))]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log.info("locallm: запускаю воркер: %s", " ".join(cmd))
        _proc = subprocess.Popen(cmd, cwd=str(resolve(".")),
                                 creationflags=flags)

        deadline = time.time() + 60
        while time.time() < deadline:
            h = _health()
            if h is not None:
                if not h.get("error"):
                    _fail_streak = 0
                    return {"ok": True, "port": prt}
                return _handle_worker_error(h["error"])
            if _proc.poll() is not None:
                return {"error": f"воркер упал при старте (код "
                                 f"{_proc.returncode}), см. "
                                 "logs/locallm_worker.log"}
            time.sleep(1)
        return {"ok": True, "port": prt,
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
