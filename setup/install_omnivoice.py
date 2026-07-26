"""Установка OmniVoice (k2-fsa) в ОТДЕЛЬНОЕ окружение .venv_omni.

Зачем отдельное: OmniVoice тестирован на torch 2.8, а у нас в основном .venv
стоит torch cu130 под RTX. Поставишь его зависимости в общий venv — pip
утянет свою версию torch и утащит за собой faster-whisper, GigaAM и
Qwen3-TTS. Ровно та же причина, по которой Voxtral живёт отдельно от слуха.

Хитрость та же, что в install_voxtral.py: torch (~7 ГБ) НЕ ставим второй раз.
После установки в .venv_omni кладём main_env.pth со ссылкой на site-packages
основного .venv — torch, numpy, fastapi, uvicorn, soundfile берутся оттуда.
Сам omnivoice ставим с --no-deps, чтобы он не притащил свой torch, а
остальные его зависимости добираем поимённо.

Зачем вообще OmniVoice: из всего, что умеет клонировать голос, он
единственный под Apache-2.0 (XTTS-v2 — некоммерческая Coqui CPML, у Silero
лицензия только образовательная). 646 языков, русский — 20 338 часов в
обучении, RTF 0.025 на GPU, 0.6B параметров.

ВАЖНО: после установки ничего не ставь pip-ом внутрь .venv_omni — из-за .pth
pip увидит пакеты основного окружения и может их поломать. Нужно что-то
доставить — удали main_env.pth, поставь, верни обратно.

Использование:
  setup\\install_omnivoice.bat        (или python setup/install_omnivoice.py)
  python setup/install_omnivoice.py --remove   удалить окружение целиком
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv_omni"
MAIN_SP = ROOT / ".venv" / "Lib" / "site-packages"
VENV_PY = VENV / "Scripts" / "python.exe"
VENV_SP = VENV / "Lib" / "site-packages"

os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# Зависимости omnivoice, кроме torch/numpy/soundfile (те из основного venv).
# Список поимённо, потому что ставим пакет с --no-deps: иначе он приведёт
# свою версию torch и всё сломает.
EXTRA = ["omnivoice", "einops", "vocos", "jieba", "pypinyin", "unidecode",
         "num2words", "cached_path"]


def run(cmd, check=True):
    tmp = ROOT / ".pip_tmp"
    tmp.mkdir(exist_ok=True)
    env = dict(os.environ, TMP=str(tmp), TEMP=str(tmp))
    print(">>>", " ".join(str(c) for c in cmd))
    ok = subprocess.run([str(c) for c in cmd], env=env).returncode == 0
    if not ok and check:
        return False
    return True


def main():
    if "--remove" in sys.argv:
        if VENV.exists():
            shutil.rmtree(VENV)
            print("✓ .venv_omni удалён.")
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
        print("[1/4] Создаю .venv_omni…")
        if not run([sys.executable, "-m", "venv", VENV]):
            sys.exit(1)
    else:
        print("[1/4] .venv_omni уже есть")

    # .pth убираем на время pip install — иначе pip увидит основное окружение
    pth.unlink(missing_ok=True)

    print("[2/4] Ставлю omnivoice БЕЗ зависимостей (torch берём из основного)…")
    if not run([VENV_PY, "-m", "pip", "install", "-U", "--no-deps",
                "omnivoice", "--timeout", "180", "--retries", "10"]):
        print("[X] omnivoice не поставился. Возможно, пакета нет в PyPI под "
              "этим именем — попробуй из исходников:\n"
              "    .venv_omni\\Scripts\\python.exe -m pip install --no-deps "
              "git+https://github.com/k2-fsa/OmniVoice.git")
        sys.exit(1)

    print("[3/4] Доставляю его мелкие зависимости…")
    # по одной: если какой-то пакет не нужен этой версии или не собирается,
    # это не повод валить всю установку
    for pkg in EXTRA[1:]:
        run([VENV_PY, "-m", "pip", "install", "-U", pkg,
             "--no-deps", "--timeout", "120", "--retries", "5"], check=False)

    print("[4/4] Подключаю torch/fastapi из основного окружения (main_env.pth)…")
    # путь ОТНОСИТЕЛЬНЫЙ (от папки .pth-файла): переносимый диск может
    # менять букву (E: -> I:), абсолютный путь бы сломался
    rel = os.path.relpath(MAIN_SP, VENV_SP)
    pth.write_text(rel + "\n", encoding="utf-8")

    print("Проверка…")
    code = ("import torch, omnivoice, fastapi, uvicorn, soundfile;"
            "print('torch', torch.__version__, '| cuda',"
            " torch.cuda.is_available(), '| omnivoice ok')")
    if not run([VENV_PY, "-c", code]):
        print("[!] Проверка не прошла. Частая причина — omnivoice ждёт пакет,"
              "\n    которого нет в списке EXTRA этого скрипта. Смотри имя в"
              "\n    ошибке выше и допиши его туда, потом запусти снова.")
        sys.exit(1)

    print("""
✓ Готово. В интерфейсе Сайки убери "omni" из tts.hidden (config.json) и
  выбери движок озвучки «OmniVoice» — сервер сам поднимет воркер.
  Первый синтез скачает веса (~1.5 ГБ) в models/hf; прогресс —
  logs/omnivoice_worker.log.
  Удалить окружение: python setup/install_omnivoice.py --remove
""")


if __name__ == "__main__":
    main()
