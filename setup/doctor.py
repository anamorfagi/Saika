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
    import torch
    if torch.cuda.is_available():
        return True, torch.cuda.get_device_name(0)
    return False, "CUDA недоступна — TTS/STT будут на CPU (медленно)"


def _stt_engine_valid():
    """Выбранный STT-движок хотя бы импортируется? Иначе переключаем.
    Внешние движки (со своим venv, напр. voxtral) валидны, если venv на месте."""
    from server.config import CFG
    order = CFG.get("stt.fallback_order", [])
    mods = {"faster_whisper": "faster_whisper", "gigaam": "gigaam",
            "vosk": "vosk", "whispercpp": "pywhispercpp", "tone": "tone"}

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
            try:
                importlib.import_module(mod)
            except Exception:
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
    # если из-за этого TTS раньше переключили на silero — вернём qwen3
    try:
        importlib.invalidate_caches()
        importlib.import_module("qwen_tts")
        from server.config import CFG
        if CFG.get("tts.engine") != "qwen3":
            CFG.set("tts.engine", "qwen3")
    except Exception:
        pass


def _qwen_tts_ok():
    try:
        importlib.import_module("qwen_tts")
        return True, "пакет установлен"
    except Exception:
        from server.config import CFG
        CFG.set("tts.engine", "silero")
        return False, "qwen_tts не установлен -> TTS переключён на silero"


def run_checks(fix=False):
    print("\n── Доктор Сайки ──────────────────────────────")
    report = []
    for mod, pkg in PKG_FIX.items():
        report.append(_check(f"пакет {mod}", mod in ("fastapi", "uvicorn",
                                                     "numpy", "requests"),
                             _import_ok(mod), _pip_fix(mod, pkg), fix))
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

    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    bad = [c for c in report if c["status"] == "fail" and c["required"]]
    print("──────────────────────────────────────────────")
    print("✗ Есть критические проблемы" if bad else "✓ Система готова")
    return report


if __name__ == "__main__":
    fix = "--fix" in sys.argv
    report = run_checks(fix=fix)
    sys.exit(1 if any(c["status"] == "fail" and c["required"]
                      for c in report) else 0)
