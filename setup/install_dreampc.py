"""Установка DreamPC (диффузионная LLM LLaDA-8B-Instruct) в ОТДЕЛЬНОЕ
окружение .venv_dreampc. Полностью автономна и самопочиняющаяся: сама
проверяет результат и сама переустанавливает, если находит проблему —
никаких ручных --remove не требуется ни при первом запуске, ни при починке.

Зачем отдельное: свежие transformers/accelerate/bitsandbytes нужны только
этой экспериментальной панели — не хотим менять пины основного окружения
(Qwen3-TTS пинит transformers==4.57.3). Воркер (workers/dreampc_worker.py)
крутится в своём окружении, сервер общается с ним по HTTP (как Voxtral).

Хитрость: torch (~7 ГБ) не ставим второй раз — после установки зависимостей
в .venv_dreampc кладём main_env.pth со ссылкой на site-packages основного
.venv (torch, numpy, fastapi, uvicorn берутся оттуда).

ВАЖНО: ставим transformers/accelerate/bitsandbytes с --no-deps. Без этого
флага во время установки (main_env.pth ещё не подключен, torch pip не
виден) pip САМ подтягивает свой собственный CPU-only torch как зависимость
accelerate/bitsandbytes — он тихо ложится в .venv_dreampc и перекрывает
GPU-torch из main_env.pth. Модель на 8B тогда лезет грузиться в float32
на ЦП (~32 ГБ ОЗУ) вместо 4 бит на видеокарту — на практике это забивало
всю оперативную память и вешало систему свопом (было замечено 2026-07-15).
Если такое всё же обнаружится (после установки CUDA не видна) — скрипт
сам сносит venv и пробует ещё раз, автоматически, один раз.

ВАЖНО: после установки НИЧЕГО не ставь pip-ом внутрь .venv_dreampc —
из-за .pth pip увидит пакеты основного окружения и может их поломать.
Нужно что-то доставить — удали main_env.pth, поставь, верни обратно.

Модель GSAI-ML/LLaDA-8B-Instruct весит ~16 ГБ (bf16) — скачивается один раз
при первом запуске воркера в models/hf. 4-битное квантование (bitsandbytes)
уменьшает только объём VRAM при инференсе (~6 ГБ), НЕ размер скачивания.

Использование:
  setup\\install_dreampc.bat                 (или python setup/install_dreampc.py)
  python setup/install_dreampc.py --remove   удалить окружение целиком

Вызывается и вручную человеком, и автоматически сервером в фоне (без окна,
см. server/llm/dreampc.py) — поэтому НИЧЕГО не должно ждать ввода с
клавиатуры (pause есть только в install_dreampc.bat, не здесь).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv_dreampc"
MAIN_SP = ROOT / ".venv" / "Lib" / "site-packages"
VENV_PY = VENV / "Scripts" / "python.exe"
VENV_SP = VENV / "Lib" / "site-packages"

os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def run(cmd):
    tmp = ROOT / ".pip_tmp"
    tmp.mkdir(exist_ok=True)
    env = dict(os.environ, TMP=str(tmp), TEMP=str(tmp))
    print(">>>", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], env=env).returncode == 0


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
        print("[1/3] Создаю .venv_dreampc…", flush=True)
        if not run([sys.executable, "-m", "venv", VENV]):
            return False
    else:
        print("[1/3] .venv_dreampc уже есть", flush=True)

    pth.unlink(missing_ok=True)

    print("[2/3] Ставлю transformers + accelerate + bitsandbytes + "
          "huggingface_hub + tokenizers + safetensors (--no-deps, торч не "
          "трогаем — иначе pip подтянет свой CPU-only)…", flush=True)
    # Всё, что версийно жёстко привязано к transformers, ставим своей
    # копией (--no-deps, не общей с main venv): свежий transformers (5.x)
    # требует новее huggingface_hub/tokenizers/safetensors, чем стоит в
    # main venv (там старьё под transformers==4.57.3 для Qwen3-TTS) — без
    # своих копий падает "cannot import name 'is_offline_mode'" и подобное
    # (см. known_issues.md, поймано 2026-07-15). numpy/requests/pyyaml и
    # т.п. по-прежнему берём из main venv — эти API стабильнее и не рвутся.
    if not run([VENV_PY, "-m", "pip", "install", "-U", "--no-deps",
                "transformers", "accelerate", "bitsandbytes", "huggingface_hub",
                "tokenizers", "safetensors",
                "--timeout", "180", "--retries", "10"]):
        return False

    print("[3/3] Подключаю torch/fastapi из основного окружения (main_env.pth)…",
          flush=True)
    rel = os.path.relpath(MAIN_SP, VENV_SP)
    pth.write_text(rel + "\n", encoding="utf-8")

    print("Проверка…", flush=True)
    code = ("import torch, transformers, accelerate, bitsandbytes, huggingface_hub,"
            "fastapi, uvicorn;"
            "print('torch', torch.__version__, '| cuda', torch.cuda.is_available(),"
            "'| transformers', transformers.__version__,"
            "'| bitsandbytes', bitsandbytes.__version__,"
            "'| hf_hub', huggingface_hub.__version__)")
    if not run([VENV_PY, "-c", code]):
        print("[X] Проверка не прошла — смотри вывод выше.", flush=True)
        return False

    return _cuda_ok()


def main():
    if "--remove" in sys.argv:
        if VENV.exists():
            shutil.rmtree(VENV)
            print("✓ .venv_dreampc удалён.", flush=True)
        else:
            print("Нечего удалять.", flush=True)
        return

    print(__doc__, flush=True)

    if not MAIN_SP.exists():
        print(f"[X] Не найдено основное окружение: {MAIN_SP}. "
              "Сначала запусти start.bat.", flush=True)
        sys.exit(1)

    # Самопочинка: если venv уже существует, но torch в нём битый/CPU-only
    # (см. ВАЖНО выше) — сносим и ставим с нуля, без вопросов пользователю.
    if VENV.exists() and not _cuda_ok():
        print("[i] Существующее окружение .venv_dreampc битое (CUDA не "
              "видна) — сношу и ставлю с нуля…", flush=True)
        shutil.rmtree(VENV, ignore_errors=True)

    ok = _install_once()
    if not ok and VENV.exists():
        # даже свежая установка умудрилась остаться без CUDA — пробуем
        # ОДИН раз с полного нуля (мало ли pip закэшировал что-то не то)
        print("[i] После установки CUDA всё ещё не видна — сношу и "
              "пробую ещё раз с чистого листа (последняя попытка)…",
              flush=True)
        shutil.rmtree(VENV, ignore_errors=True)
        ok = _install_once()

    if not ok:
        print("""
[X] Не удалось поставить окружение с рабочей CUDA даже после чистой
    переустановки. Похоже, дело не в venv, а в чём-то более глубоком —
    например, у основного .venv тоже нет GPU-torch, или сломаны драйверы
    NVIDIA. Проверь вручную:
      .venv\\Scripts\\python.exe -c "import torch; print(torch.cuda.is_available())"
    Если там тоже False — сначала почини основное окружение (setup/doctor.py
    --fix), DreamPC тут ни при чём.
""", flush=True)
        sys.exit(1)

    print("""
✓ Готово, CUDA на месте. В веб-интерфейсе Сайки нажми 🧪 (DreamPC) — сервер
  сам запустит воркер. Первая генерация скачает веса модели (~16 ГБ bf16)
  в models/hf и займёт время; прогресс — в logs/dreampc_worker.log. В
  память видеокарты модель ложится уже в 4-битном виде (~6 ГБ).
  Удалить окружение: python setup/install_dreampc.py --remove
""", flush=True)


if __name__ == "__main__":
    main()
