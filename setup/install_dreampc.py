"""Установка DreamPC (диффузионная LLM LLaDA-8B-Instruct) в ОТДЕЛЬНОЕ
окружение .venv_dreampc.

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

ВАЖНО: после установки НИЧЕГО не ставь pip-ом внутрь .venv_dreampc —
из-за .pth pip увидит пакеты основного окружения и может их поломать.
Нужно что-то доставить — удали main_env.pth, поставь, верни обратно.

Модель GSAI-ML/LLaDA-8B-Instruct весит ~16 ГБ (bf16) — скачивается один раз
при первом запуске воркера в models/hf. 4-битное квантование (bitsandbytes)
уменьшает только объём VRAM при инференсе (~6 ГБ), НЕ размер скачивания.

Использование:
  setup\\install_dreampc.bat                 (или python setup/install_dreampc.py)
  python setup/install_dreampc.py --remove   удалить окружение целиком
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
    print(">>>", " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], env=env).returncode == 0


def main():
    if "--remove" in sys.argv:
        if VENV.exists():
            shutil.rmtree(VENV)
            print("✓ .venv_dreampc удалён.")
        else:
            print("Нечего удалять.")
        return

    print(__doc__)

    if not MAIN_SP.exists():
        print(f"[X] Не найдено основное окружение: {MAIN_SP}. "
              "Сначала запусти start.bat.")
        sys.exit(1)

    pth = VENV_SP / "main_env.pth"
    if not VENV_PY.exists():
        print("[1/3] Создаю .venv_dreampc…")
        if not run([sys.executable, "-m", "venv", VENV]):
            sys.exit(1)
    else:
        print("[1/3] .venv_dreampc уже есть")

    pth.unlink(missing_ok=True)

    print("[2/3] Ставлю transformers + accelerate + bitsandbytes (--no-deps, "
          "торч не трогаем — иначе pip подтянет свой CPU-only)…")
    if not run([VENV_PY, "-m", "pip", "install", "-U", "--no-deps",
                "transformers", "accelerate", "bitsandbytes",
                "--timeout", "180", "--retries", "10"]):
        sys.exit(1)

    print("[3/3] Подключаю torch/fastapi из основного окружения (main_env.pth)…")
    rel = os.path.relpath(MAIN_SP, VENV_SP)
    pth.write_text(rel + "\n", encoding="utf-8")

    print("Проверка…")
    code = ("import torch, transformers, accelerate, bitsandbytes, fastapi, uvicorn;"
            "print('torch', torch.__version__, '| cuda', torch.cuda.is_available(),"
            "'| transformers', transformers.__version__,"
            "'| bitsandbytes', bitsandbytes.__version__)")
    if not run([VENV_PY, "-c", code]):
        print("[X] Проверка не прошла — смотри вывод выше.")
        sys.exit(1)

    # Отдельно и жёстко проверяем именно CUDA: если её нет — значит где-то
    # всё же подтянулся свой CPU-torch (см. ВАЖНО выше), и модель на 8B
    # полезет грузиться в float32 на ЦП — тяжело падает по ОЗУ. Раз это уже
    # бывало — не даём тихо продолжить с CPU-torch, останавливаем установку.
    cuda_ok = subprocess.run(
        [str(VENV_PY), "-c",
         "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)"]
    ).returncode == 0
    if not cuda_ok:
        print("""
[X] torch в .venv_dreampc видит систему БЕЗ CUDA (CPU-only) — значит pip
    всё-таки подтянул свой собственный torch поверх main_env.pth. Запускать
    DreamPC в таком виде НЕЛЬЗЯ (см. ВАЖНО в начале файла — забьёт ОЗУ).
    Почини: удали .venv_dreampc\\Lib\\site-packages\\torch* (папку и все
    *.dist-info рядом) и запусти установку заново, либо снеси всё
    окружение целиком: python setup/install_dreampc.py --remove
""")
        sys.exit(1)

    print("""
✓ Готово. В веб-интерфейсе Сайки нажми 🧪 (DreamPC) — сервер сам запустит
  воркер. Первая генерация скачает веса модели (~16 ГБ bf16) в models/hf
  и займёт время; прогресс — в logs/dreampc_worker.log. В память видеокарты
  модель ложится уже в 4-битном виде (~6 ГБ).
  Удалить окружение: python setup/install_dreampc.py --remove
""")


if __name__ == "__main__":
    main()
