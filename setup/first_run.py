"""Менеджер первой настройки Сайки.

Запускается из start.bat при первом старте (или если .setup_state.json
неполный). Ставит всё сам, по шагам, с сохранением прогресса — упавший шаг
можно перезапустить, готовые шаги пропускаются.

Каждый шаг: [обязательный?] что делает
 1. [да] pip, базовые зависимости (fastapi, uvicorn, numpy, ...)
 2. [да] PyTorch CUDA (cu130) — общий для TTS и STT
 3. [нет] flash-attn (ускорение Qwen3-TTS; без него будет sdpa)
 4. [да] Qwen3-TTS-streaming (git clone + pip install -e)
 5. [да] faster-whisper
 6. [нет] GigaAM (git), Vosk (+модель), pywhispercpp, T-one (git)
 7. [нет] cuBLAS/cuDNN 12 (DLL для faster-whisper на GPU)
 8. [нет] ffmpeg (для GigaAM и конвертации референса)
 9. [нет] Ollama (winget) — если нет ни Ollama, ни LM Studio
10. [да] Подготовка голоса: mp3 -> wav 24k + автотранскрипт для клона
11. [да] Финальная проверка (doctor)
"""
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / ".setup_state.json"
PY = sys.executable

# Все кэши моделей — в папке проекта (переносимый диск, ничего на C:).
# Должно быть выставлено до первого импорта huggingface_hub/torch.
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
os.environ.setdefault("TORCH_HOME", str(ROOT / "models" / "torch"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
# Xet-бэкенд (cas-server.xethub.hf.co) часто блокируется провайдерами —
# качаем по обычному HTTPS через CDN hf.co.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
# дочерние pip/python-процессы наследуют это окружение автоматически

VOSK_URL = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
QWEN_TTS_REPO = "https://github.com/dffdeeq/Qwen3-TTS-streaming.git"
GIGAAM_REPO = "https://github.com/salute-developers/GigaAM.git"
TONE_REPO = "https://github.com/voicekit-team/T-one.git"
FLASH_ATTN_WHEEL = ("https://github.com/mjun0812/flash-attention-prebuild-wheels/"
                    "releases/download/v0.7.12/"
                    "flash_attn-2.8.3%2Bcu130torch2.10-cp312-cp312-win_amd64.whl")

CORE_REQS = [
    "fastapi", "uvicorn[standard]", "websockets", "requests", "numpy",
    "soundfile", "apscheduler", "chromadb", "edge-tts", "librosa", "psutil",
    "sounddevice",
]


def state_load():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def state_save(st):
    STATE_PATH.write_text(json.dumps(st, indent=2), encoding="utf-8")


def run(cmd, **kw):
    print(f"\n>>> {' '.join(str(c) for c in cmd)}")
    return subprocess.run([str(c) for c in cmd], **kw).returncode == 0


def pip(*args):
    # Временные файлы pip держим на диске проекта, а не в C:\Windows\Temp:
    # антивирус любит блокировать большие whl-файлы там (WinError 32).
    # Плюс длинный таймаут и авто-повторы — большие колёса (torch ~3.5 ГБ)
    # часто рвутся по сети.
    tmp = ROOT / ".pip_tmp"
    tmp.mkdir(exist_ok=True)
    env = dict(os.environ, TMP=str(tmp), TEMP=str(tmp))
    extra = []
    if args and args[0] == "install":
        extra = ["--timeout", "180", "--retries", "10"]
    ok = run([PY, "-m", "pip", *args, *extra], env=env)
    if not ok and args and args[0] == "install":
        print("[retry] Повторяю установку ещё раз…")
        ok = run([PY, "-m", "pip", *args, *extra], env=env)
    return ok


def step(st, key, title, fn, required=True):
    if st.get(key) == "done":
        print(f"[skip] {title} — уже сделано")
        return True
    print("\n" + "=" * 60)
    print(f"[шаг] {title}")
    print("=" * 60)
    try:
        ok = fn()
    except Exception as e:
        print(f"[ошибка] {e}")
        ok = False
    if ok:
        st[key] = "done"
    else:
        st[key] = "failed"
        msg = f"[!] Шаг «{title}» не удался."
        if required:
            print(msg + " Он обязательный — установка остановлена.")
            state_save(st)
            sys.exit(1)
        print(msg + " Он необязательный — продолжаю, доктор подхватит позже.")
    state_save(st)
    return ok


# ---------------- шаги ----------------
def s_base():
    pip("install", "--upgrade", "pip")
    return pip("install", *CORE_REQS)


def s_torch():
    code = ("import torch;"
            "print(torch.__version__, torch.cuda.is_available())")
    r = subprocess.run([PY, "-c", code], capture_output=True, text=True)
    if r.returncode == 0 and "True" in r.stdout:
        print("PyTorch с CUDA уже установлен:", r.stdout.strip())
        return True
    return pip("install", "torch", "torchaudio",
               "--index-url", "https://download.pytorch.org/whl/cu130")


def s_flash_attn():
    if pip("install", FLASH_ATTN_WHEEL):
        pip("install", "-U", "triton-windows<3.7")
        return True
    return False


def s_qwen_tts():
    dst = ROOT / "third_party" / "Qwen3-TTS-streaming"
    dst.parent.mkdir(exist_ok=True)
    if not dst.exists():
        if not run(["git", "clone", "--depth", "1", QWEN_TTS_REPO, dst]):
            return False
    return pip("install", "-e", dst)


def s_faster_whisper():
    return pip("install", "faster-whisper")


def s_gigaam():
    dst = ROOT / "third_party" / "GigaAM"
    dst.parent.mkdir(exist_ok=True)
    if not dst.exists():
        if not run(["git", "clone", "--depth", "1", GIGAAM_REPO, dst]):
            return False
    return pip("install", "-e", f"{dst}[torch]")


def s_vosk():
    if not pip("install", "vosk"):
        return False
    model_dir = ROOT / "models" / "vosk-model-small-ru-0.22"
    if model_dir.exists():
        return True
    print("Качаю модель Vosk (~45 МБ)…")
    zip_path = ROOT / "models" / "vosk-ru.zip"
    urlretrieve(VOSK_URL, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(ROOT / "models")
    zip_path.unlink()
    return model_dir.exists()


def s_whispercpp():
    return pip("install", "pywhispercpp")


def s_tone():
    # KenLM на Windows не собирается — T-one опционален
    ok = pip("install", f"git+{TONE_REPO}")
    # T-one тянет numpy<2 и ломает scipy/gigaam/librosa — сразу возвращаем
    pip("install", "numpy>=2,<2.5")
    return ok


def s_numpy_fix():
    """T-one (и некоторые другие) даунгрейдят numpy до 1.x. Возвращаем 2.x,
    иначе scipy/librosa падают с ошибкой np.long."""
    return pip("install", "numpy>=2,<2.5")


FFMPEG_URL = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/"
              "latest/ffmpeg-master-latest-win64-gpl.zip")


def s_ffmpeg():
    if shutil.which("ffmpeg"):
        print("ffmpeg уже в PATH")
        return True
    local_bin = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    if local_bin.exists():
        print("локальный ffmpeg уже скачан")
        return True
    # winget есть не у всех — пробуем, но не рассчитываем
    try:
        if run(["winget", "install", "--id", "Gyan.FFmpeg", "-e",
                "--accept-source-agreements", "--accept-package-agreements"]):
            return True
    except FileNotFoundError:
        print("winget не найден — качаю ffmpeg напрямую (~80 МБ)…")
    tools = ROOT / "tools"
    tools.mkdir(exist_ok=True)
    zip_path = tools / "ffmpeg.zip"
    urlretrieve(FFMPEG_URL, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tools)
    zip_path.unlink()
    # распакованная папка называется ffmpeg-master-latest-win64-gpl — переименуем
    for d in tools.iterdir():
        if d.is_dir() and d.name.startswith("ffmpeg-"):
            d.rename(tools / "ffmpeg")
            break
    return (ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe").exists()


def s_ollama():
    import requests
    for name, url in (("Ollama", "http://127.0.0.1:11434/api/tags"),
                      ("LM Studio", "http://127.0.0.1:1234/v1/models")):
        try:
            requests.get(url, timeout=2)
            print(f"{name} уже работает — LLM-бэкенд есть.")
            return True
        except Exception:
            pass
    if shutil.which("ollama"):
        print("Ollama установлена, но не запущена — start.bat запустит её.")
        return True
    print("Ставлю Ollama через winget…")
    return run(["winget", "install", "--id", "Ollama.Ollama", "-e",
                "--accept-source-agreements", "--accept-package-agreements"])


def s_cuda_dlls():
    """CTranslate2 (faster-whisper) собран под CUDA 12, а torch cu130 несёт
    только DLL 13-й версии — без этих пакетов будет
    «cublas64_12.dll is not found». anamorf/config.py подключает их bin к PATH."""
    if os.name != "nt":
        return True
    return pip("install", "nvidia-cublas-cu12", "nvidia-cudnn-cu12")


def _ffmpeg_exe():
    local = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    if local.exists():
        return str(local)
    return shutil.which("ffmpeg")


def s_voice():
    """mp3 -> wav (24k mono) + автотранскрипт референса для клона голоса.
    Конвертация через ffmpeg — не тянем librosa/numba в критический путь."""
    sys.path.insert(0, str(ROOT))
    from anamorf.config import CFG, resolve

    src = resolve(CFG.get("tts.voice_ref"))
    dst = resolve(CFG.get("tts.voice_ref_wav"))
    if not src.exists():
        print(f"[!] Нет файла голоса: {src}")
        return False

    if not dst.exists():
        ff = _ffmpeg_exe()
        if not ff:
            print("[!] Нет ffmpeg — шаг ffmpeg должен пройти раньше")
            return False
        if not run([ff, "-y", "-i", src, "-ar", "24000", "-ac", "1", dst]):
            return False
        print(f"Референс сконвертирован: {dst}")

    if not CFG.get("tts.voice_ref_text"):
        print("Расшифровываю референс голосом faster-whisper…")
        from faster_whisper import WhisperModel

        def _transcribe(device, compute):
            # ошибка CUDA (cublas и т.п.) может вылезти не при создании модели,
            # а при первом инференсе — поэтому транскрибируем внутри
            model = WhisperModel("large-v3-turbo", device=device,
                                 compute_type=compute)
            segments, _ = model.transcribe(str(dst), language="ru")
            return " ".join(s.text.strip() for s in segments).strip()

        try:
            text = _transcribe("auto", "auto")
        except Exception as e:
            print(f"[!] GPU-инференс не удался ({e}) — пробую CPU int8…")
            text = _transcribe("cpu", "int8")
        if not text:
            print("[!] Не удалось расшифровать референс")
            return False
        CFG.set("tts.voice_ref_text", text)
        print(f"Транскрипт: {text[:120]}…")
    return True


def s_vision():
    """Глаза: захват экрана и вебки (2026-07-25). Всё open source.
    Необязательный шаг: не встанет — Сайка живёт слепой, но живёт."""
    ok = pip("install", "opencv-python==4.13.0.92", "mss")
    # быстрые бэкенды отдельной командой: падение одного колеса не должно
    # утаскивать обязательную часть
    if not pip("install", "dxcam[cv2]", "windows-capture", "pygrabber"):
        print("[~] быстрые бэкенды захвата не встали — останется mss")
    return ok


def s_doctor():
    sys.path.insert(0, str(ROOT))
    from setup.doctor import run_checks
    report = run_checks(fix=True)
    bad = [c for c in report if c["status"] == "fail" and c["required"]]
    return not bad


def main():
    os.chdir(ROOT)
    print("""
  ┌─────────────────────────────────────────────┐
  │   Сайка — менеджер первой настройки         │
  └─────────────────────────────────────────────┘
""")
    st = state_load()
    step(st, "base", "Базовые зависимости (fastapi, chromadb, …)", s_base)
    step(st, "torch", "PyTorch CUDA", s_torch)
    step(st, "flash_attn", "flash-attn (ускорение TTS)", s_flash_attn,
         required=False)
    step(st, "qwen_tts", "Qwen3-TTS-streaming (голос Сайки)", s_qwen_tts)
    step(st, "faster_whisper", "STT 1/5: faster-whisper", s_faster_whisper)
    step(st, "gigaam", "STT 2/5: GigaAM (Сбер)", s_gigaam, required=False)
    step(st, "vosk", "STT 3/5: Vosk + русская модель", s_vosk, required=False)
    step(st, "whispercpp", "STT 4/5: whisper.cpp", s_whispercpp, required=False)
    step(st, "tone", "STT 5/5: T-one (Т-Банк, опционально)", s_tone,
         required=False)
    print("[i] Шестой STT — Voxtral Realtime — ставится отдельно "
          "(setup/install_voxtral.bat или выбор в веб-UI): своё окружение "
          "из-за конфликта зависимостей с Qwen3-TTS.")
    step(st, "numpy_fix2", "Починка numpy (2.x, но <2.5 для numba)", s_numpy_fix)
    step(st, "cuda_dlls", "cuBLAS/cuDNN 12 для faster-whisper (GPU)",
         s_cuda_dlls, required=False)
    step(st, "ffmpeg", "ffmpeg", s_ffmpeg, required=False)
    step(st, "ollama", "LLM-бэкенд (Ollama / LM Studio)", s_ollama,
         required=False)
    step(st, "vision", "Глаза: захват экрана и вебки", s_vision,
         required=False)
    step(st, "voice", "Подготовка голоса Сайки", s_voice)
    step(st, "doctor", "Финальная проверка", s_doctor, required=False)

    st["setup_complete"] = True
    state_save(st)
    print("\n✓ Установка завершена. Запускай start.bat ещё раз — Сайка стартует.")


if __name__ == "__main__":
    main()
