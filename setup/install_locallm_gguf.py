"""Установка БЫСТРОГО движка LocalLM — llama.cpp (llama-cpp-python) вместо
transformers+bitsandbytes. Отдельное окружение .venv_locallm_gguf.

Зачем отдельное окружение: llama.cpp — самостоятельный C++ инференс-движок,
torch ему НЕ нужен вообще (в отличие от DreamPC/LocalLM-transformers) — тут
нет main_env.pth трюка, венв полностью независимый и лёгкий.

Почему это быстрее: transformers+bitsandbytes деквантует веса в Python-цикле
на каждый токен — это тот же движок, что и в LM Studio под капотом (там ты
видел 85-95 ток/с на gemma-4-e4b). GGUF-кванты + компилированные CUDA-ядра
llama.cpp дают на порядок меньше накладных расходов при той же 4-битной
математике.

Единственная реальная сложность: готовый Windows-wheel с CUDA для
llama-cpp-python существует не всегда для любой комбинации версий — пробуем
по очереди несколько тегов CUDA (cu124 -> cu122 -> cu121), первый успешный
устанавливаем. Если НИ ОДИН wheel не встал — самостоятельно ничего не
компилируем (сборка требует Visual Studio Build Tools + CUDA Toolkit,
занимает долго и легко ломается на чужой машине без присмотра) — печатаем
понятную инструкцию и останавливаемся, а не тратим 20 минут на слепую сборку.

Модель — GGUF-файл конкретного кванта, а не весь репозиторий (в GGUF-репо
обычно лежит 5-10 разных квантов сразу, там десятки ГБ). Ищем подходящий файл
по суффиксу кванта (locallm_gguf.quant, например "Q4_K_M"), а не по жёстко
зашитому имени — точные имена файлов у разных квантователей чуть отличаются
(регистр, дефисы), и жёсткое имя было бы хрупким.

Использование:
  setup\\install_locallm_gguf.bat                 (или python setup/install_locallm_gguf.py)
  python setup/install_locallm_gguf.py --download  скачать GGUF-файл сразу
  python setup/install_locallm_gguf.py --remove    удалить окружение целиком
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
VENV = ROOT / ".venv_locallm_gguf"
VENV_PY = VENV / "Scripts" / "python.exe"

# готовые CUDA-wheel'ы llama-cpp-python (abetlen.github.io) — пробуем по
# очереди от новых к старым; более старый тег обычно ставится и на новых
# драйверах (CUDA runtime обратно совместим с драйвером), а не наоборот
WHEEL_INDEXES = [
    "https://abetlen.github.io/llama-cpp-python/whl/cu124",
    "https://abetlen.github.io/llama-cpp-python/whl/cu122",
    "https://abetlen.github.io/llama-cpp-python/whl/cu121",
]

DEFAULT_REPO = "mradermacher/Huihui-Qwen3.5-9B-abliterated-i1-GGUF"
DEFAULT_QUANT = "Q4_K_M"

os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")


def run(cmd, env=None):
    tmp = ROOT / ".pip_tmp"
    tmp.mkdir(exist_ok=True)
    full_env = dict(os.environ, TMP=str(tmp), TEMP=str(tmp))
    if env:
        full_env.update(env)
    print(">>>", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], env=full_env).returncode == 0


def _pypi_reachable() -> bool:
    import socket
    try:
        socket.create_connection(("pypi.org", 443), timeout=5).close()
        return True
    except OSError:
        return False


def _import_ok() -> bool:
    if not VENV_PY.exists():
        return False
    try:
        return subprocess.run(
            [str(VENV_PY), "-c", "import llama_cpp"], timeout=30).returncode == 0
    except Exception:
        return False


def _gpu_offload_ok() -> bool:
    """Проверка, что бинарник собран с поддержкой GPU (CUDA/cuBLAS).
    llama_cpp.llama_supports_gpu_offload() — низкоуровневая функция ggml;
    если её нет в этой версии биндинга (менялось между релизами) — не считаем
    это провалом установки, реальное подтверждение будет при первой загрузке
    модели в воркере (там сразу видно, ушла она в VRAM или легла на CPU)."""
    if not VENV_PY.exists():
        return False
    code = (
        "import llama_cpp\n"
        "try:\n"
        "    ok = llama_cpp.llama_supports_gpu_offload()\n"
        "except Exception:\n"
        "    ok = None\n"
        "import sys\n"
        "sys.exit(0 if ok in (True, None) else 1)\n")
    try:
        return subprocess.run(
            [str(VENV_PY), "-c", code], timeout=30).returncode == 0
    except Exception:
        return False


def _install_llama_cpp_python() -> bool:
    """Пробует готовые CUDA-wheel'ы по очереди. True — что-то встало."""
    for idx in WHEEL_INDEXES:
        print(f"[2/3] Пробую готовый wheel llama-cpp-python ({idx.rsplit('/', 1)[-1]})…",
              flush=True)
        if run([VENV_PY, "-m", "pip", "install", "-U", "llama-cpp-python",
                "--prefer-binary", "--extra-index-url", idx,
                "--timeout", "180", "--retries", "3"]):
            if _import_ok():
                print(f"[OK] llama-cpp-python встал с {idx}", flush=True)
                return True
        print(f"[i] {idx} не подошёл, пробую следующий…", flush=True)
    return False


def _install_once() -> bool:
    if not VENV_PY.exists():
        print("[1/3] Создаю .venv_locallm_gguf…", flush=True)
        if not run([sys.executable, "-m", "venv", VENV]):
            return False
    else:
        print("[1/3] .venv_locallm_gguf уже есть", flush=True)

    if not _install_llama_cpp_python():
        print("""
[X] Ни один готовый CUDA-wheel llama-cpp-python не подошёл (cu124/122/121).
    Автоматическую сборку из исходников я НЕ запускаю — она требует Visual
    Studio Build Tools (компонент "Desktop development with C++") и
    установленный CUDA Toolkit, занимает долго и на чужой машине без
    присмотра легко разваливается на середине.

    Если хочешь собрать вручную — после установки VS Build Tools и CUDA
    Toolkit выполни:
      set CMAKE_ARGS=-DGGML_CUDA=on
      .venv_locallm_gguf\\Scripts\\python.exe -m pip install llama-cpp-python --no-cache-dir

    Либо просто оставайся на движке transformers (locallm.engine="transformers"
    в config.json) — он уже стоит и работает, просто медленнее.
""", flush=True)
        return False

    print("[3/3] Ставлю fastapi/uvicorn/huggingface_hub (никакого torch — "
          "движку он не нужен)…", flush=True)
    if not run([VENV_PY, "-m", "pip", "install", "-U",
                "fastapi", "uvicorn", "huggingface_hub", "requests",
                "--timeout", "180", "--retries", "10"]):
        return False

    return _import_ok()


def _model_cfg() -> tuple[str, str]:
    """(repo, quant) из config.json, без импорта серверного кода."""
    import json
    try:
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        g = cfg.get("locallm_gguf", {}) or {}
        return (g.get("repo") or DEFAULT_REPO, g.get("quant") or DEFAULT_QUANT)
    except Exception:
        return DEFAULT_REPO, DEFAULT_QUANT


def _download_gguf() -> bool:
    """Ищет файл нужного кванта по суффиксу имени (не зная точного имени
    заранее — квантователи называют файлы чуть по-разному) и качает его."""
    repo, quant = _model_cfg()
    print(f"[download] Ищу квант {quant} в {repo}…", flush=True)
    code = (
        "import os, socket, sys\n"
        "def ok(h):\n"
        "    try:\n"
        "        socket.create_connection((h, 443), timeout=3).close()\n"
        "        return True\n"
        "    except OSError:\n"
        "        return False\n"
        "if not ok('huggingface.co') and ok('hf-mirror.com'):\n"
        "    os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'\n"
        "    print('huggingface.co недоступен - качаю с зеркала hf-mirror.com')\n"
        "from huggingface_hub import list_repo_files, hf_hub_download\n"
        f"repo, quant = {repo!r}, {quant!r}\n"
        "files = [f for f in list_repo_files(repo) if f.lower().endswith('.gguf')]\n"
        "cands = [f for f in files if quant.lower() in f.lower()]\n"
        "if not cands:\n"
        "    print('Кванты в репо:', files)\n"
        "    print(f'НЕ нашла файл с \"{quant}\" в имени - см. список выше, '\n"
        "          f'поправь locallm_gguf.quant в config.json на точное совпадение.')\n"
        "    sys.exit(1)\n"
        "fname = sorted(cands, key=len)[0]  # короче имя = обычно один файл, не multi-part\n"
        "print('Качаю:', fname)\n"
        "p = hf_hub_download(repo, fname)\n"
        "print('OK ->', p)\n")
    return run([VENV_PY, "-c", code])


def main():
    if "--remove" in sys.argv:
        if VENV.exists():
            shutil.rmtree(VENV)
            print("[OK] .venv_locallm_gguf удалён.", flush=True)
        else:
            print("Нечего удалять.", flush=True)
        return

    print(__doc__, flush=True)

    ok = _install_once()
    if not ok and VENV.exists() and not _import_ok():
        if not _pypi_reachable():
            print("\n[X] PyPI недоступен сейчас — дело в сети, не в venv. "
                  "Повтори при живом интернете.\n", flush=True)
            sys.exit(1)

    if not _import_ok():
        sys.exit(1)  # подробное сообщение уже напечатано выше

    if not _gpu_offload_ok():
        print("[!] Не удалось подтвердить GPU-офлоад в бинарнике — возможно, "
              "встал CPU-only wheel. Реальная проверка будет при первой "
              "загрузке модели (смотри logs/locallm_gguf_worker.log — если "
              "модель ляжет на CPU, генерация будет заметно медленнее, но "
              "не упадёт).", flush=True)

    if "--download" in sys.argv:
        if not _download_gguf():
            print("[!] GGUF скачать не удалось (сеть до HF? неверный квант в "
                  "config.json?) — воркер попробует докачать сам при первом "
                  "запуске.", flush=True)

    repo, quant = _model_cfg()
    print(f"""
[OK] Готово. Дальше:
  1) в config.json: "locallm": {{"engine": "llamacpp", ...}};
  2) сервер сам поднимет воркер при первом запросе. Модель — {quant} из
     {repo}, первая загрузка скачает файл в models/hf, если ещё не скачан.
  Логи: logs/locallm_gguf_worker.log. Удалить окружение:
  python setup/install_locallm_gguf.py --remove
""", flush=True)


if __name__ == "__main__":
    main()
