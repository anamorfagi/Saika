"""Доктор — автопроверки и автопочинка.

Запускается: после установки, перед каждым стартом (быстро), и из start.bat
при падении сервера. С флагом fix=True пытается чинить сам:
- нет пакета -> pip install
- Ollama не запущена -> запустить
- нет модели в Ollama -> ollama pull
- сломанный движок в конфиге -> переключить на здоровый
Результат пишет в logs/doctor_report.json — сервер показывает его в UI.
"""
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REPORT_PATH = ROOT / "logs" / "doctor_report.json"

PKG_FIX = {
    "fastapi": "fastapi", "uvicorn": "uvicorn[standard]", "numpy": "numpy",
    "requests": "requests", "soundfile": "soundfile",
    "apscheduler": "apscheduler", "chromadb": "chromadb",
    "faster_whisper": "faster-whisper", "vosk": "vosk",
    "pywhispercpp": "pywhispercpp", "edge_tts": "edge-tts",
    "librosa": "librosa", "psutil": "psutil",
    "sounddevice": "sounddevice",
}


def _check(name, required, fn, fix_fn=None, fix=False):
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, str(e)
    if not ok and fix and fix_fn:
        try:
            print(f"[fix] {name}: {detail} — чиню…")
            fix_fn()
            time.sleep(1)
            ok, detail = fn()
            detail = ("исправлено: " if ok else "не починилось: ") + str(detail)
        except Exception as e:
            detail = f"починка не удалась: {e}"
    status = "ok" if ok else "fail"
    print(f"[{status:4}] {name}: {detail}")
    return {"name": name, "status": status, "detail": str(detail),
            "required": required}


def _import_ok(module):
    def f():
        importlib.import_module(module)
        return True, "установлен"
    return f


# Тяжёлые CUDA-модули проверяем в ОТДЕЛЬНОМ ЧИСТОМ процессе. Причины:
# 1) faster_whisper (ctranslate2) и torch несут РАЗНЫЕ cuDNN (12 и 13) —
#    импорт обоих в один процесс валит второго («partially initialized
#    module torch», WinError 1114), и отчёт врёт;
# 2) флаг -I не подмешивает папку проекта в sys.path — локальные пакеты
#    (tools/, setup/, training/) не перекрывают зависимости.
HEAVY_MODS = {"faster_whisper", "torch", "qwen_tts", "gigaam"}


def _sub_import(module, timeout=180):
    r = subprocess.run([sys.executable, "-I", "-c", f"import {module}"],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode == 0:
        return True, "установлен"
    lines = (r.stderr or "").strip().splitlines()
    return False, (lines[-1][:200] if lines else "import failed")


def _import_ok_sub(module):
    def f():
        return _sub_import(module)
    return f


def _pip_install(pkg):
    def f():
        subprocess.run([sys.executable, "-m", "pip", "install", pkg],
                       check=False)
    return f


def _pip_fix(module, pkg):
    """Настоящая починка импорта. Обычный `pip install` при битых файлах
    отвечает «already satisfied» и ничего не делает. Здесь: смотрим, КАКОЙ
    модуль не импортируется (может быть зависимость зависимости, например
    chromadb падает из-за opentelemetry.proto), находим дистрибутивы-владельцы
    и принудительно переустанавливаем именно их."""
    def f():
        import importlib.metadata as md
        missing = None
        try:
            importlib.import_module(module)
            return  # уже работает
        except ModuleNotFoundError as e:
            missing = (e.name or "").split(".")[0]
        except Exception:
            pass
        dists = set()
        if missing:
            dists.update(md.packages_distributions().get(missing) or [])
        if not dists:
            dists = {pkg}
        for d in sorted(dists):
            try:
                md.distribution(d)
                extra = ["--force-reinstall", "--no-deps"]  # битые файлы
            except md.PackageNotFoundError:
                extra = []                                  # вообще не стоял
            subprocess.run([sys.executable, "-m", "pip", "install", d,
                            *extra], check=False)
    return f


def _ollama_running():
    import requests
    try:
        r = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
        n = len(r.json().get("models", []))
        return True, f"работает, моделей: {n}"
    except Exception:
        return False, "не отвечает"


def _lmstudio_running():
    import requests
    try:
        r = requests.get("http://127.0.0.1:1234/v1/models", timeout=2)
        n = len(r.json().get("data", []))
        return True, f"работает, моделей: {n}"
    except Exception:
        return False, "не отвечает"


def _llamacpp_ready():
    """СВОЙ движок мозгов (2026-07-27). Отдельная строка в отчёте нужна
    потому, что это единственный бэкенд, который проект держит сам: если
    бинаря нет или сервер не поднялся, человек должен видеть это здесь, а
    не гадать, почему Сайка снова думает через чужую программу."""
    exe = ROOT / "third_party" / "llamacpp" / (
        "llama-server.exe" if os.name == "nt" else "llama-server")
    if not exe.exists():
        return False, ("не установлен (поставится сам при следующем "
                       "запуске start.bat)")
    ver = ""
    try:
        ver = (ROOT / "third_party" / "llamacpp" / "VERSION.txt").read_text(
            encoding="utf-8").splitlines()[0].strip()
    except Exception:
        pass
    import requests
    try:
        requests.get("http://127.0.0.1:8771/health", timeout=2)
        return True, f"работает{' (' + ver + ')' if ver else ''}"
    except Exception:
        return True, f"установлен{' (' + ver + ')' if ver else ''}, не запущен"


def _start_ollama():
    if shutil.which("ollama"):
        subprocess.Popen(["ollama", "serve"],
                         creationflags=getattr(subprocess,
                                               "CREATE_NO_WINDOW", 0))
        time.sleep(4)


def _ollama_has_model():
    import requests
    r = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
    models = r.json().get("models", [])
    if models:
        return True, f"{len(models)} шт."
    return False, "нет ни одной модели"


def _pull_default_model():
    subprocess.run(["ollama", "pull", "qwen2.5:7b-instruct"], check=False)


def _voice_ready():
    from server.config import CFG, resolve
    wav = resolve(CFG.get("tts.voice_ref_wav"))
    text = CFG.get("tts.voice_ref_text", "")
    if wav.exists() and text:
        return True, "референс и транскрипт готовы"
    return False, "нет wav или транскрипта (запусти setup/first_run.py)"


def _cuda_ok():
    # в чистом подпроцессе — см. комментарий у HEAVY_MODS
    code = ("import torch;"
            "print(torch.cuda.get_device_name(0) "
            "if torch.cuda.is_available() else 'NOCUDA')")
    r = subprocess.run([sys.executable, "-I", "-c", code],
                       capture_output=True, text=True, timeout=180)
    out = (r.stdout or "").strip()
    if r.returncode == 0 and out and out != "NOCUDA":
        return True, out
    if out == "NOCUDA":
        return False, "CUDA недоступна — TTS/STT будут на CPU (медленно)"
    lines = (r.stderr or "").strip().splitlines()
    return False, (lines[-1][:200] if lines else "torch не импортируется")


def _stt_engine_valid():
    """Выбранный STT-движок хотя бы импортируется? Иначе переключаем.
    Внешние движки (со своим venv, напр. voxtral) валидны, если venv на месте."""
    from server.config import CFG
    order = CFG.get("stt.fallback_order", [])
    mods = {"faster_whisper": "faster_whisper", "gigaam": "gigaam",
            "vosk": "vosk", "whispercpp": "pywhispercpp", "tone": "tone",
            "groq_whisper": "requests"}  # облачный — хватает requests

    def usable(name):
        venv = CFG.get(f"stt.engines.{name}.venv")
        if venv:  # внешний движок — проверяем его окружение, не импорт
            return (ROOT / venv / "Scripts" / "python.exe").exists()
        try:
            importlib.import_module(mods.get(name, name))
            return True
        except Exception:
            return False

    current = CFG.get("stt.engine")
    for name in [current] + [n for n in order if n != current]:
        if usable(name):
            if name != current:
                CFG.set("stt.engine", name)
                return True, f"«{current}» неисправен -> переключил на «{name}»"
            return True, f"активен: {name}"
    return False, "ни один STT-движок не импортируется"


# editable-пакеты (pip install -e) хранят АБСОЛЮТНЫЕ пути. Диск переносимый —
# буква меняется (E: -> I:) и импорт ломается. Чиним переустановкой без deps.
EDITABLE_PKGS = (("qwen_tts", "third_party/Qwen3-TTS-streaming", ""),
                 ("gigaam", "third_party/GigaAM", "[torch]"))


def _editable_broken():
    out = []
    for mod, path, extras in EDITABLE_PKGS:
        if (ROOT / path).exists():
            ok, _ = _sub_import(mod)   # чистый подпроцесс — без cuDNN-каши
            if not ok:
                out.append((mod, path, extras))
    return out


def _editable_ok():
    broken = _editable_broken()
    if broken:
        return False, ("битые пути (сменилась буква диска?): "
                       + ", ".join(b[0] for b in broken))
    return True, "пути актуальны"


def _fix_editable():
    for mod, path, extras in _editable_broken():
        subprocess.run([sys.executable, "-m", "pip", "install", "-e",
                        f"{ROOT / path}{extras}", "--no-deps"], check=False)
    # если из-за этого TTS раньше переключили на запасной — вернём qwen3
    try:
        ok, _ = _sub_import("qwen_tts")
        if not ok:
            raise ImportError("qwen_tts всё ещё не импортируется")
        from server.config import CFG
        if CFG.get("tts.engine") != "qwen3":
            CFG.set("tts.engine", "qwen3")
    except Exception:
        pass


def _best_backup_tts():
    """Запасной голос — лучший ПО РЕЙТИНГУ этого ПК, а не хардкод silero."""
    from server.config import CFG
    order = CFG.get("tts.fallback_order", ["silero", "edge"])
    try:
        from server import ratings
        best = ratings.best_tts(order, exclude=("qwen3",),
                                favorites=CFG.get("tts.favorites", []))
    except Exception:
        best = None
    return best or next((n for n in order if n != "qwen3"), "silero")


def _qwen_tts_ok():
    ok, detail = _sub_import("qwen_tts")
    if ok:
        return True, "пакет установлен"
    from server.config import CFG
    best = _best_backup_tts()
    CFG.set("tts.engine", best)
    return False, (f"qwen_tts сломан ({detail}) -> TTS переключён на {best} "
                   f"(по рейтингу)")


def _recover_from_crash(fix):
    """После нативного краша (0xC0000005) процесс умирает мгновенно — Python
    это не ловит. Но в saika.log последней строкой остаётся то, на чём он
    упал. Если это загрузка Qwen3-TTS (частый случай: не хватило VRAM, когда
    в видеопамяти уже сидит LLM) — переключаем озвучку на silero (CPU,
    стабильно) и гасим optimize, чтобы Сайка хотя бы поднялась."""
    if not fix:
        return
    try:
        lines = [l for l in (ROOT / "logs" / "saika.log").read_text(
            encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    except Exception:
        return
    joined = "\n".join(lines[-6:]).lower()
    crashed_on_qwen = ("qwen3-tts" in joined and "беру из" in joined
                       and "модель готова" not in joined
                       and "загружен (attn" not in joined)
    if crashed_on_qwen:
        from server.config import CFG
        # временно уводим на лучший ПО РЕЙТИНГУ запасной голос, чтобы
        # разорвать петлю крашей и поднять сервер. qwen3 НЕ отключаем
        # насовсем (это её родной клон-голос) — как освободится VRAM,
        # вернётся сама (или выбери его в UI).
        best = _best_backup_tts()
        CFG.set("tts.engine", best)
        print(f"[fix] Qwen3-TTS уронил процесс при загрузке (нативный крах — "
              f"чаще всего не хватило VRAM, когда её держит LLM). Временно "
              f"перевёл озвучку на {best} (лучший по рейтингу), чтобы поднять "
              f"сервер. Освободи видеопамять — и клон-голос снова заработает.")


def run_checks(fix=False):
    print("\n── Беймакс: осмотр системы ───────────────────")
    _recover_from_crash(fix)
    report = []
    for mod, pkg in PKG_FIX.items():
        checker = _import_ok_sub(mod) if mod in HEAVY_MODS else _import_ok(mod)
        report.append(_check(f"пакет {mod}", mod in ("fastapi", "uvicorn",
                                                     "numpy", "requests"),
                             checker, _pip_fix(mod, pkg), fix))
    report.append(_check("PyTorch CUDA", False, _cuda_ok))
    report.append(_check("Editable-пакеты (qwen_tts, gigaam)", False,
                         _editable_ok, _fix_editable, fix))
    report.append(_check("Qwen3-TTS", False, _qwen_tts_ok))
    report.append(_check("Голос Сайки", False, _voice_ready))
    report.append(_check("STT-движок", True, _stt_engine_valid))
    report.append(_check("ffmpeg", False,
                         lambda: (bool(shutil.which("ffmpeg")), "в PATH")))
    ollama = _check("Ollama", False, _ollama_running, _start_ollama, fix)
    report.append(ollama)
    if ollama["status"] == "ok":
        report.append(_check("Модель в Ollama", False, _ollama_has_model,
                             _pull_default_model, fix))
    report.append(_check("LM Studio", False, _lmstudio_running))
    report.append(_check("Свой движок (llama.cpp)", False, _llamacpp_ready))

    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    bad = [c for c in report if c["status"] == "fail" and c["required"]]
    print("──────────────────────────────────────────────")
    print("✗ Есть критические проблемы" if bad else "✓ Система готова")
    return report


def _fast_skip_ok():
    """Быстрый старт: полный осмотр (куча python-подпроцессов с импортом
    torch/faster_whisper/qwen_tts — десятки секунд) не нужен НА КАЖДЫЙ
    запуск. Пропускаем, если (а) прошлый запуск дошёл до веб-сервера
    (logs/boot_ok.json свежий, младше суток) и (б) последний отчёт доктора
    без критических провалов. Падение сервера start.bat лечит полным
    осмотром (зовёт doctor без --fast)."""
    try:
        boot = json.loads((ROOT / "logs" / "boot_ok.json")
                          .read_text(encoding="utf-8"))
        if time.time() - float(boot.get("ts", 0)) > 24 * 3600:
            return False
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        return not any(c.get("status") == "fail" and c.get("required")
                       for c in report)
    except Exception:
        return False


if __name__ == "__main__":
    fix = "--fix" in sys.argv
    if "--fast" in sys.argv and _fast_skip_ok():
        print("Беймакс: прошлый запуск был здоровым (<24ч) — быстрый старт, "
              "полный осмотр пропускаю. Полный: setup\\doctor.py --fix")
        sys.exit(0)
    report = run_checks(fix=fix)
    sys.exit(1 if any(c["status"] == "fail" and c["required"]
                      for c in report) else 0)
