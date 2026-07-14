"""Загрузка/сохранение конфига. Всё через один объект CFG."""
import json
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
_lock = threading.Lock()


class Config:
    def __init__(self):
        self._data = {}
        self.load()

    def load(self):
        with _lock:
            self._data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def save(self):
        with _lock:
            CONFIG_PATH.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def get(self, path, default=None):
        node = self._data
        for key in path.split("."):
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def set(self, path, value):
        keys = path.split(".")
        node = self._data
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value
        self.save()

    @property
    def data(self):
        return self._data


CFG = Config()


def resolve(rel_path: str) -> Path:
    """Путь относительно корня проекта."""
    p = Path(rel_path)
    return p if p.is_absolute() else ROOT / p


# Локальный ffmpeg (tools/ffmpeg/bin) добавляем в PATH процесса —
# нужен GigaAM и librosa, установщик кладёт его туда если нет системного.
import os  # noqa: E402

_ffmpeg_bin = ROOT / "tools" / "ffmpeg" / "bin"
if _ffmpeg_bin.exists():
    os.environ["PATH"] = str(_ffmpeg_bin) + os.pathsep + os.environ.get("PATH", "")

# Все кэши моделей — внутри проекта (переносимый диск, ничего на C:).
# Важно: выставляем ДО импорта huggingface_hub/torch, поэтому здесь.
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
os.environ.setdefault("TORCH_HOME", str(ROOT / "models" / "torch"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
# Xet-бэкенд (cas-server.xethub.hf.co) часто блокируется провайдерами —
# качаем по обычному HTTPS через CDN hf.co.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# DNS до huggingface.co бывает недоступен (провайдер/VPN). Без этой проверки
# huggingface_hub мучает каждый файл ретраями по минуте и старт зависает.
# Порядок: hf.co доступен -> ничего не делаем; нет -> пробуем зеркало
# hf-mirror.com; нет и его -> офлайн-режим (кэш работает, некэшированное
# падает сразу с понятной ошибкой, а не висит).
if not os.environ.get("HF_HUB_OFFLINE") and not os.environ.get("HF_ENDPOINT"):
    import socket

    def _reachable(host):
        try:
            socket.create_connection((host, 443), timeout=3).close()
            return True
        except OSError:
            return False

    if not _reachable("huggingface.co"):
        if _reachable("hf-mirror.com"):
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
            print("[i] huggingface.co недоступен — использую зеркало hf-mirror.com")
        else:
            os.environ["HF_HUB_OFFLINE"] = "1"
            print("[i] huggingface.co недоступен — HF в офлайн-режиме, "
                  "работаю на уже скачанных моделях")

# CTranslate2 (faster-whisper) собран под CUDA 12, а torch cu130 несёт DLL
# только 13-й версии — отсюда «cublas64_12.dll is not found». Подключаем к
# поиску DLL только cuBLAS 12 и nvrtc (имена уникальны, конфликтов нет).
# ВАЖНО: cuDNN из nvidia-cudnn-cu12 НЕ подключаем — у torch свой cuDNN в
# torch\lib, и смешение двух копий даёт при инференсе
# CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH. PATH не переставляем, только
# дополняем в конец.
if os.name == "nt":
    import site

    _sp_dirs = list(site.getsitepackages())
    if site.getusersitepackages():
        _sp_dirs.append(site.getusersitepackages())
    for _sp in _sp_dirs:
        _dirs = [Path(_sp) / "torch" / "lib",              # cuDNN торча — один на всех
                 Path(_sp) / "nvidia" / "cublas" / "bin",
                 Path(_sp) / "nvidia" / "cuda_nvrtc" / "bin"]
        for _bin in _dirs:
            if _bin.is_dir():
                try:
                    os.add_dll_directory(str(_bin))
                except OSError:
                    pass
                os.environ["PATH"] = (os.environ.get("PATH", "")
                                      + os.pathsep + str(_bin))
