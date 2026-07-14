"""Установка Voxtral Mini 4B Realtime в ОТДЕЛЬНОЕ окружение .venv_voxtral.

Зачем отдельное: Voxtral требует transformers>=5.2, а Qwen3-TTS пинит
==4.57.3 — в одном venv они не живут. Воркер (workers/voxtral_worker.py)
крутится в своём окружении, сервер общается с ним по HTTP, основное
окружение не трогается вообще.

Хитрость: torch (~7 ГБ) не ставим второй раз — после установки зависимостей
в .venv_voxtral кладём main_env.pth со ссылкой на site-packages основного
.venv (torch, numpy, fastapi, uvicorn берутся оттуда; transformers 5.x
в своём venv перекрывает основной 4.57.3, т.к. ищется раньше).

ВАЖНО: после установки НИЧЕГО не ставь pip-ом внутрь .venv_voxtral —
из-за .pth pip увидит пакеты основного окружения и может их поломать.
Нужно что-то доставить — удали main_env.pth, поставь, верни обратно.

Использование:
  setup\\install_voxtral.bat            (или python setup/install_voxtral.py)
  python setup/install_voxtral.py --remove   удалить окружение целиком
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv_voxtral"
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
            print("✓ .venv_voxtral удалён.")
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
        print("[1/3] Создаю .venv_voxtral…")
        if not run([sys.executable, "-m", "venv", VENV]):
            sys.exit(1)
    else:
        print("[1/3] .venv_voxtral уже есть")

    # .pth убираем на время pip install — иначе pip увидит основное окружение
    pth.unlink(missing_ok=True)

    print("[2/3] Ставлю transformers>=5.2 + mistral-common[audio] + soxr…")
    if not run([VENV_PY, "-m", "pip", "install", "-U",
                "transformers>=5.2", "mistral-common[audio]", "soxr",
                "--timeout", "180", "--retries", "10"]):
        sys.exit(1)

    print("[3/3] Подключаю torch/fastapi из основного окружения (main_env.pth)…")
    # путь ОТНОСИТЕЛЬНЫЙ (от папки .pth-файла): переносимый диск может
    # менять букву (E: -> I:), абсолютный путь бы сломался
    rel = os.path.relpath(MAIN_SP, VENV_SP)
    pth.write_text(rel + "\n", encoding="utf-8")

    print("Проверка…")
    code = ("import torch, transformers, mistral_common, fastapi, uvicorn;"
            "print('torch', torch.__version__, '| cuda', torch.cuda.is_available(),"
            "'| transformers', transformers.__version__)")
    if not run([VENV_PY, "-c", code]):
        print("[X] Проверка не прошла — смотри вывод выше.")
        sys.exit(1)

    print("""
✓ Готово. В веб-интерфейсе Сайки выбери STT-движок «voxtral» —
  сервер сам запустит воркер. Первое распознавание скачает модель (~9 ГБ)
  в models/hf и займёт время; прогресс — в logs/voxtral_worker.log.
  Удалить окружение: python setup/install_voxtral.py --remove
""")


if __name__ == "__main__":
    main()
