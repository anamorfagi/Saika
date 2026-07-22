"""Установка «своей» LLM Сайки (LocalLM) в ОТДЕЛЬНОЕ окружение .venv_locallm.

Зачем: собственный воркер вместо Ollama/LM Studio — модель качается прямо в
проект (models/hf), грузится transformers-ом в 4 битах на GPU, стримит токены
по OpenAI-совместимому HTTP. Никакого стороннего софта; та же модель потом
дообучается LoRA во вкладке 🎓 (training.base_model = locallm.model).

Модель по умолчанию: t-tech/T-lite-it-2.1 (8B, файнтюн Qwen3-8B от Т-Банка,
Apache 2.0) — лучший русский в классе 8B (Ru Arena Hard 83.9), без
дополнительного safety-alignment, ~5.5 ГБ VRAM в nf4. Меняется в config.json
(locallm.model).

Схема окружения — 1:1 как у DreamPC (setup/install_dreampc.py, там подробно
про каждую граблю): transformers обычным pip resolve; accelerate+bitsandbytes
с --no-deps (иначе pip тихо притащит CPU-only torch — реальный инцидент
2026-07-15, свопом вешало систему); torch/fastapi/uvicorn — из основного
.venv через main_env.pth; самопочинка «CUDA не видна -> снос и переустановка».

Использование:
  setup\\install_locallm.bat                 (или python setup/install_locallm.py)
  python setup/install_locallm.py --download  дополнительно скачать веса модели
                                              сразу (иначе — при первом запуске
                                              воркера)
  python setup/install_locallm.py --remove    удалить окружение целиком

Вызывается и вручную, и автоматически сервером в фоне (server/llm/locallm.py)
— НИЧЕГО не должно ждать ввода с клавиатуры.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Windows-консоль обычно в cp1251 — не даём юникод-принтам ронять скрипт
# (см. ту же шапку в install_dreampc.py).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv_locallm"
MAIN_SP = ROOT / ".venv" / "Lib" / "site-packages"
VENV_PY = VENV / "Scripts" / "python.exe"
VENV_SP = VENV / "Lib" / "site-packages"

DEFAULT_MODEL = "t-tech/T-lite-it-2.1"

os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")


def run(cmd):
    tmp = ROOT / ".pip_tmp"
    tmp.mkdir(exist_ok=True)
    env = dict(os.environ, TMP=str(tmp), TEMP=str(tmp))
    print(">>>", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], env=env).returncode == 0


def _pypi_reachable() -> bool:
    import socket
    try:
        socket.create_connection(("pypi.org", 443), timeout=5).close()
        return True
    except OSError:
        return False


def _cuda_ok() -> bool:
    if not VENV_PY.exists():
        return False
    try:
        return subprocess.run(
            [str(VENV_PY), "-c",
             "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)"],
            timeout=30).returncode == 0
    except Exception:
        return False


def _install_once() -> bool:
    """Один проход установки. True — CUDA после установки на месте."""
    pth = VENV_SP / "main_env.pth"

    if not VENV_PY.exists():
        print("[1/3] Создаю .venv_locallm…", flush=True)
        if not run([sys.executable, "-m", "venv", VENV]):
            return False
    else:
        print("[1/3] .venv_locallm уже есть", flush=True)

    pth.unlink(missing_ok=True)

    print("[2/3] Ставлю transformers (обычный pip resolve — сам подберёт "
          "huggingface_hub/tokenizers/safetensors)…", flush=True)
    if not run([VENV_PY, "-m", "pip", "install", "-U",
                "transformers", "--timeout", "180", "--retries", "10"]):
        return False

    print("[2b/3] Ставлю accelerate + bitsandbytes (--no-deps — эти двое тянут "
          "torch как обязательную зависимость; свой CPU-only torch нам не "
          "нужен, GPU-torch придёт из main_env.pth)…", flush=True)
    if not run([VENV_PY, "-m", "pip", "install", "-U", "--no-deps",
                "accelerate", "bitsandbytes",
                "--timeout", "180", "--retries", "10"]):
        return False

    print("[3/3] Подключаю torch/fastapi из основного окружения (main_env.pth)…",
          flush=True)
    rel = os.path.relpath(MAIN_SP, VENV_SP)
    pth.write_text(rel + "\n", encoding="utf-8")

    print("Проверка…", flush=True)
    code = ("import torch, transformers, accelerate, bitsandbytes,"
            "huggingface_hub, fastapi, uvicorn;"
            "print('torch', torch.__version__, '| cuda', torch.cuda.is_available(),"
            "'| transformers', transformers.__version__,"
            "'| bitsandbytes', bitsandbytes.__version__)")
    if not run([VENV_PY, "-c", code]):
        print("[X] Проверка не прошла — смотри вывод выше.", flush=True)
        return False

    return _cuda_ok()


def _model_from_config() -> str:
    """locallm.model из config.json, без импорта серверного кода (скрипт
    должен работать даже при полуживом окружении)."""
    import json
    try:
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        return (cfg.get("locallm", {}) or {}).get("model") or DEFAULT_MODEL
    except Exception:
        return DEFAULT_MODEL


def _download_weights() -> bool:
    """Скачивает веса модели в models/hf через окружение воркера (там свежий
    huggingface_hub). Повторный запуск докачивает недокачанное."""
    model = _model_from_config()
    print(f"[download] Качаю веса {model} в models/hf (8B ~ 16 ГБ bf16; "
          "повторный запуск докачивает)…", flush=True)
    code = (
        "import os, socket\n"
        "def ok(h):\n"
        "    try:\n"
        "        socket.create_connection((h, 443), timeout=3).close()\n"
        "        return True\n"
        "    except OSError:\n"
        "        return False\n"
        "if not ok('huggingface.co') and ok('hf-mirror.com'):\n"
        "    os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'\n"
        "    print('huggingface.co недоступен - качаю с зеркала hf-mirror.com')\n"
        "from huggingface_hub import snapshot_download\n"
        f"p = snapshot_download('{model}')\n"
        "print('OK ->', p)\n")
    return run([VENV_PY, "-c", code])


def main():
    if "--remove" in sys.argv:
        if VENV.exists():
            shutil.rmtree(VENV)
            print("[OK] .venv_locallm удалён.", flush=True)
        else:
            print("Нечего удалять.", flush=True)
        return

    print(__doc__, flush=True)

    if not MAIN_SP.exists():
        print(f"[X] Не найдено основное окружение: {MAIN_SP}. "
              "Сначала запусти start.bat.", flush=True)
        sys.exit(1)

    # Самопочинка: venv есть, но torch битый/CPU-only — снос без вопросов.
    if VENV.exists() and not _cuda_ok():
        print("[i] Существующее окружение .venv_locallm битое (CUDA не "
              "видна) — сношу и ставлю с нуля…", flush=True)
        shutil.rmtree(VENV, ignore_errors=True)

    ok = _install_once()
    if not ok and VENV.exists():
        if not _pypi_reachable():
            print("\n[X] Установка не прошла, PyPI недоступен — это сеть/VPN, "
                  "не venv. Повтори, когда появится доступ к pypi.org.\n",
                  flush=True)
            sys.exit(1)
        print("[i] После установки CUDA всё ещё не видна — пробую ещё раз "
              "с чистого листа (последняя попытка)…", flush=True)
        shutil.rmtree(VENV, ignore_errors=True)
        ok = _install_once()

    if not ok:
        if not _pypi_reachable():
            print("\n[X] Установка не прошла — PyPI недоступен прямо сейчас. "
                  "Попробуй ещё раз при живом интернете.\n", flush=True)
        else:
            print("""
[X] Не удалось поставить окружение с рабочей CUDA даже после чистой
    переустановки. Проверь основное окружение:
      .venv\\Scripts\\python.exe -c "import torch; print(torch.cuda.is_available())"
    Если там тоже False — сначала setup/doctor.py --fix, LocalLM ни при чём.
""", flush=True)
        sys.exit(1)

    if "--download" in sys.argv:
        if not _download_weights():
            print("[!] Веса скачать не удалось (сеть до HF?) — не страшно: "
                  "воркер сам докачает при первом запуске.", flush=True)

    print(f"""
[OK] Готово, CUDA на месте. Дальше:
  1) в config.json поставь "llm": {{"backend": "locallm", ...}} — или выбери
     бэкенд в UI, когда он появится в списке;
  2) сервер сам поднимет воркер при первом запросе (server/llm/locallm.py);
     первая загрузка скачает веса {_model_from_config()} в models/hf.
  Логи: logs/locallm_worker.log. Удалить окружение:
  python setup/install_locallm.py --remove
""", flush=True)


if __name__ == "__main__":
    main()
