"""Загрузка/сохранение конфига. Всё через один объект CFG."""
import json
import secrets
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _data_root() -> Path:
    r"""Где живёт нажитое: память, логи, модели, настройки человека.

    В рабочей копии это тот же корень, что и у кода, — там всё в одной
    папке, и так удобнее. В собранном приложении раскладка другая:

        ANAMORF\
          app\        ← код. ОБНОВЛЕНИЕ ЗАМЕНЯЕТ ЕГО ЦЕЛИКОМ
          runtime\    ← интерпретатор
          data\       ← память и профили голоса
          models\     ← модели
          logs\       ← логи

    Код лежит в app\, и если писать данные рядом с ним, первое же
    обновление унесёт их вместе с папкой. Поэтому данные — на уровень
    выше. Распознаём сборку по соседству с runtime\: ни в одной рабочей
    копии такого соседа нет.
    """
    if ROOT.name == "app" and (ROOT.parent / "runtime").is_dir():
        return ROOT.parent
    return ROOT


DATA_ROOT = _data_root()
# Папки должны существовать раньше первого обращения: логирование
# настраивается на самой ранней строке main.py и падает, если каталога нет.
for _d in ("data", "logs", "models"):
    try:
        (DATA_ROOT / _d).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

# Настройки человека живут рядом с его данными, а не с кодом.
CONFIG_PATH = DATA_ROOT / "config.json"
# Значения по умолчанию едут вместе с приложением и обновляются вместе с ним.
# Из них рождается config.json на чистой машине — чтобы у человека после
# установки был рабочий файл, а не пустота, и чтобы личные значения автора
# (имя, ключ доступа, устройства, расшифровка голоса) не разъезжались с
# обновлениями. Править DEFAULT_PATH бесполезно: он перезаписывается.
DEFAULT_PATH = ROOT / "config.default.json"
# 2026-07-25: машинные настройки живут ОТДЕЛЬНО от общего конфига.
# ПРИЧИНА (стоила времени на каждом синке между домом и работой):
# config.json лежит в git, поэтому после `git pull` на второй машине
# прилетали чужие backend/model/движок слуха/устройство вывода, и их
# приходилось возвращать руками. Теперь всё машинно-специфичное дублируется
# в config.local.json, который в .gitignore — он накладывается ПОВЕРХ
# config.json при загрузке и переживает любой pull.
LOCAL_PATH = ROOT / "config.local.json"
_lock = threading.Lock()

# Что считается «настройкой этой машины». Пути указываются как в CFG.get.
LOCAL_KEYS = (
    "llm.backend", "llm.model",
    "stt.engine",
    "tts.engine", "tts.output_device", "tts.output_device_dup",
    "mic.device",
    "vision.monitor", "vision.camera_index",
    "messengers.pc_name",
    "files.roots",
    "hotkeys.enabled",
)


def _dig(node, path, default=None):
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def _plant(node, path, value):
    keys = path.split(".")
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value


_MISSING = object()


def _deep_merge(base: dict, over: dict) -> dict:
    """base, поверх — over; словари сливаются вглубь, остальное замещается."""
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _ensure_token() -> None:
    """Пустой ключ доступа — выдать новый прямо в существующем конфиге.

    Нужно отдельно от разворачивания умолчаний: у того, кто уже работал,
    config.json существует, и обновления его не трогают. Стереть строку с
    ключом руками — самый простой способ его перевыпустить, и после этого
    он должен родиться сам, а не остаться пустым.
    """
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    if raw.get("server", {}).get("token"):
        return
    raw.setdefault("server", {})["token"] = secrets.token_urlsafe(9)
    try:
        CONFIG_PATH.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[i] выдан новый ключ доступа к интерфейсу")
    except Exception as e:
        print(f"[!] не удалось записать ключ доступа: {e}")


def _bootstrap() -> None:
    """Первый запуск на чистой машине: сделать config.json из умолчаний.

    Заодно выдаём собственный ключ доступа. Раньше он был один на всех,
    лежал в репозитории открытым текстом и попадал к каждому, кто получил
    копию проекта, — а этим ключом открывается интерфейс, у которого есть
    руки в системе. Теперь ключ рождается на машине и никуда не уезжает.
    """
    if CONFIG_PATH.exists():
        _ensure_token()
        return
    if not DEFAULT_PATH.exists():
        return
    try:
        data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
        data.pop("_note", None)
        srv = data.setdefault("server", {})
        if not srv.get("token"):
            srv["token"] = secrets.token_urlsafe(9)
        CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[i] создан config.json из умолчаний, ключ доступа выдан")
    except Exception as e:
        print(f"[!] не удалось развернуть настройки по умолчанию: {e}")


class Config:
    def __init__(self):
        self._data = {}
        self.load()

    def load(self):
        with _lock:
            _bootstrap()
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            # накладываем машинный слой: он главнее общего
            if LOCAL_PATH.exists():
                try:
                    local = json.loads(LOCAL_PATH.read_text(encoding="utf-8"))
                except Exception as e:
                    print(f"[!] config.local.json битый ({e}) — игнорирую")
                    local = {}
                for path in LOCAL_KEYS:
                    val = _dig(local, path, _MISSING)
                    if val is not _MISSING:
                        _plant(data, path, val)
            self._data = data

    def save(self):
        """Сохранение БЕЗ затирания чужих правок (2026-07-27, третий раз
        те же грабли). save() писал ВЕСЬ объект из памяти процесса — и любая
        правка файла на диске, сделанная, пока Сайка работает (руками, из
        другого чата, скриптом), жила ровно до первого CFG.set() о чём-нибудь
        постороннем: 2026-07-22 так затёрся ручной фикс, 2026-07-27 —
        fast_mode, маршрутизатор облака и переезд на свой движок разом.
        Теперь диск — БАЗА, память накладывается ПОВЕРХ: ключи, добавленные
        на диске и неизвестные этому процессу, переживают сохранение. Ключи,
        которые процесс знает, побеждают — это его законные настройки."""
        with _lock:
            base = {}
            try:
                base = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
            self._data = _deep_merge(base, self._data)
            CONFIG_PATH.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._save_local()

    def _save_local(self):
        """Слепок машинных настроек рядом, в файл вне git. Пишем ТОЛЬКО те
        ключи, что реально есть в конфиге, — чтобы не плодить пустышки."""
        local = {}
        try:  # чужие ключи в local-файле не выбрасываем (та же логика, что в save)
            local = json.loads(LOCAL_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
        for path in LOCAL_KEYS:
            val = _dig(self._data, path, _MISSING)
            if val is not _MISSING:
                _plant(local, path, val)
        if not local:
            return
        local["_comment"] = ("Настройки ЭТОЙ машины. Файл в .gitignore и "
                             "накладывается поверх config.json, поэтому "
                             "переживает git pull. Правится сам, когда "
                             "меняешь модель/движок/устройство в интерфейсе.")
        try:
            LOCAL_PATH.write_text(
                json.dumps(local, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            print(f"[!] не смогла записать config.local.json: {e}")

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
    """Путь относительно корня проекта.

    Пути в data/, logs/ и models/ уводим к корню ДАННЫХ: в собранном
    приложении это другая папка, и путать их нельзя — потеряется нажитое.
    """
    p = Path(rel_path)
    if p.is_absolute():
        return p
    first = p.parts[0] if p.parts else ""
    return (DATA_ROOT if first in ("data", "logs", "models") else ROOT) / p


# Локальный ffmpeg (tools/ffmpeg/bin) добавляем в PATH процесса —
# нужен GigaAM и librosa, установщик кладёт его туда если нет системного.
import os  # noqa: E402

_ffmpeg_bin = ROOT / "tools" / "ffmpeg" / "bin"
if _ffmpeg_bin.exists():
    os.environ["PATH"] = str(_ffmpeg_bin) + os.pathsep + os.environ.get("PATH", "")

# Все кэши моделей — внутри проекта (переносимый диск, ничего на C:).
# Важно: выставляем ДО импорта huggingface_hub/torch, поэтому здесь.
os.environ.setdefault("HF_HOME", str(DATA_ROOT / "models" / "hf"))
os.environ.setdefault("TORCH_HOME", str(DATA_ROOT / "models" / "torch"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
# HF по умолчанию рвёт соединение через 10 сек — на нестабильной/медленной
# сети это даёт бесконечные «read operation timed out» и загрузки крупных
# моделей (LLaDA 16 ГБ, T-one, GigaAM) ползут или висят. Даём 60 сек.
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
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
