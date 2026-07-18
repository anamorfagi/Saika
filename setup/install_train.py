"""Установка окружения для дообучения характера Сайки (.venv_train).

Стек: unsloth (быстрый QLoRA — в разы быстрее ванильного HF Trainer,
и умеет сама подобрать совместимые torch/xformers/bitsandbytes под
конкретное железо) + trl (SFTTrainer) + peft + datasets.

Отличие от install_dreampc.py: там torch переиспользовался из основного
.venv через main_env.pth, потому что DreamPC нужен был только transformers
поверх уже стоящего torch. Здесь — намеренно НЕ переиспользуем: unsloth
тянет за собой связку torch+xformers+bitsandbytes, собранную и проверенную
как единое целое под конкретную версию CUDA, и трюк с .pth тут скорее
навредит (риск словить рассинхрон ABI между чужим torch и родными
компилированными kernel'ами xformers/bitsandbytes) — а обучение происходит
не каждый день, лишние ~7 ГБ на диск не критичны. Если места жалко —
после того как заработает, можно вручную попробовать оптимизировать.

Самопочинка: если после установки CUDA не видна — сносим .venv_train и
пробуем ещё раз с нуля один раз (как install_dreampc.py). Если и это не
помогло, и PyPI недоступен — сообщаем что дело в сети, а не в коде.

Использование:
  setup\\install_train.bat                 (или python setup/install_train.py)
  python setup/install_train.py --remove   удалить окружение целиком
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv_train"
VENV_PY = VENV / "Scripts" / "python.exe" if os.name == "nt" else VENV / "bin" / "python"

os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


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


def _verify() -> bool:
    if not VENV_PY.exists():
        return False
    code = (
        "import torch, unsloth, trl, peft, datasets, transformers;"
        "import sys;"
        "ok = torch.cuda.is_available();"
        "print('torch', torch.__version__, '| cuda', ok, '| unsloth OK');"
        "sys.exit(0 if ok else 1)"
    )
    try:
        return subprocess.run([str(VENV_PY), "-c", code], timeout=60).returncode == 0
    except Exception:
        return False


def _install_once() -> bool:
    if not VENV_PY.exists():
        print("[1/4] Создаю .venv_train…", flush=True)
        if not run([sys.executable, "-m", "venv", VENV]):
            return False
    else:
        print("[1/4] .venv_train уже есть", flush=True)

    print("[2/4] Обновляю pip (нужен свежий резолвер для unsloth)…", flush=True)
    if not run([VENV_PY, "-m", "pip", "install", "-U", "pip",
                "--timeout", "180", "--retries", "10"]):
        return False

    print("[3/4] Ставлю unsloth (сама подберёт совместимые torch/xformers/"
          "bitsandbytes под твою видеокарту — самая долгая часть, ~5-10 минут "
          "и несколько гигабайт)…", flush=True)
    if not run([VENV_PY, "-m", "pip", "install", "-U", "unsloth",
                "--timeout", "300", "--retries", "10"]):
        return False

    print("[4/4] Ставлю trl + peft + datasets + sentencepiece (SFT-трейнер и "
          "утилиты для датасета)…", flush=True)
    if not run([VENV_PY, "-m", "pip", "install", "-U",
                "trl", "peft", "datasets", "sentencepiece", "protobuf",
                "--timeout", "180", "--retries", "10"]):
        return False

    print("Проверка окружения…", flush=True)
    return _verify()


def main() -> None:
    if "--remove" in sys.argv:
        if VENV.exists():
            shutil.rmtree(VENV)
            print("[OK] .venv_train удалён.", flush=True)
        else:
            print("Нечего удалять.", flush=True)
        return

    print(__doc__, flush=True)

    ok = _install_once()
    if not ok and VENV.exists():
        if not _pypi_reachable():
            print("""
[X] Установка не прошла, и PyPI (pypi.org) сейчас недоступен с этой сети —
    похоже, дело в интернете/VPN, а не в venv. Подожди сеть и запусти
    установку ещё раз (кнопка в инженерной вкладке обучения, или
    python setup/install_train.py) — просто повтори, когда будет доступ.
""", flush=True)
            sys.exit(1)
        print("[i] После установки CUDA не видна или что-то не импортируется — "
              "сношу .venv_train и пробую ещё раз с чистого листа (последняя "
              "попытка)…", flush=True)
        shutil.rmtree(VENV, ignore_errors=True)
        ok = _install_once()

    if not ok:
        if not _pypi_reachable():
            print("""
[X] Установка не прошла — PyPI недоступен с этой сети прямо сейчас.
    Это не баг venv, а сеть/VPN. Попробуй ещё раз, когда будет интернет.
""", flush=True)
        else:
            print("""
[X] Не удалось поставить рабочее окружение с CUDA даже после чистой
    переустановки. Проверь вручную:
      .venv_train\\Scripts\\python.exe -c "import torch; print(torch.cuda.is_available())"
    Если False — вопрос к драйверам NVIDIA / версии CUDA, а не к unsloth.
    Полезно также посмотреть версию CUDA драйвера: nvidia-smi (верхний
    правый угол таблицы) и сверить с https://github.com/unslothai/unsloth
    (там список поддерживаемых комбинаций).
""", flush=True)
        sys.exit(1)

    print("""
[OK] Готово, CUDA на месте. В инженерной вкладке обучения выбери датасет,
  настрой параметры и жми «Начать обучение» — сервер сам поднимет воркер.
  Удалить окружение: python setup/install_train.py --remove
""", flush=True)


if __name__ == "__main__":
    main()
