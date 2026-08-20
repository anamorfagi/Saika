"""Версия сборки и версия данных — две разные вещи, и обе тут.

ВЕРСИЯ СБОРКИ — витрина. Отвечает человеку на вопрос «что у меня стоит» и
апдейтеру на вопрос «есть ли что новее». Пишется не руками: в рабочей копии
берётся из git-тега, в собранном билде — из файла VERSION, который туда
положил компилятор. Одно место, где она рождается, — тег. Иначе рано или
поздно выйдут две разные сборки с одинаковым номером, и разбираться, какая
из них у человека, будет нечем.

ВЕРСИЯ ДАННЫХ — контракт, и он куда серьёзнее. У приложения есть откат на
предыдущую версию, и код откатить легко. А память, профили голоса и
настройки — нельзя: новая версия записала их по-новому, старый код такого
не понимает. Поэтому данные носят свой номер, и правило простое:

    номер данных ниже нашего  → поднимаем миграциями
    номер равен нашему        → работаем
    номер ВЫШЕ нашего         → не трогаем и говорим вслух

Последний случай — это откат на версию, которая не понимает уже записанного.
Честный отказ здесь лучше тихой порчи: испорченную память человека не вернёт
никакой app.prev.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

log = logging.getLogger("version")

ROOT = Path(__file__).resolve().parent.parent


# Корень данных — на уровень выше кода, когда мы внутри собранного
# приложения (app\ по соседству с runtime\). Логика повторяет
# anamorf/config.py намеренно: эти три модуля обязаны работать до того,
# как поднимется конфиг, и тянуть его ради одной строки — значит
# заводить порядок импортов там, где он не нужен.
DATA_ROOT = (ROOT.parent
             if ROOT.name == "app" and (ROOT.parent / "runtime").is_dir()
             else ROOT)
VERSION_FILE = ROOT / "VERSION"
BUILD_FILE = ROOT / "build.json"
SCHEMA_FILE = DATA_ROOT / "data" / "schema.json"

# Поднимать РОВНО тогда, когда изменился формат чего-то в data/.
# Каждый подъём обязан получить миграцию в MIGRATIONS ниже.
DATA_VERSION = 1

_cache: dict = {}


# --------------------------------------------------------- версия сборки

def _from_git() -> str | None:
    try:
        r = subprocess.run(["git", "describe", "--tags", "--dirty", "--always"],
                           cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=5)
        out = (r.stdout or "").strip()
        return out.lstrip("v") if r.returncode == 0 and out else None
    except Exception:
        return None


def version() -> str:
    """Что у нас стоит. В рабочей копии — с хвостом от git, и это удобно:
    сразу видно, сколько коммитов утекло с последнего тега."""
    if "v" in _cache:
        return _cache["v"]
    v = None
    try:
        v = json.loads(BUILD_FILE.read_text(encoding="utf-8")).get("version")
    except Exception:
        pass
    if not v:
        v = _from_git()
    if not v:
        try:
            v = VERSION_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            v = "0.0.0"
    _cache["v"] = v
    return v


def channel() -> str:
    try:
        return json.loads(BUILD_FILE.read_text(encoding="utf-8")).get(
            "channel", "dev")
    except Exception:
        return "dev"


def describe() -> dict:
    """Для /api/version, экрана «О программе» и панели обновлений."""
    from anamorf import features, runtime_env
    return {
        "version": version(),
        "channel": channel(),
        "tier": (json.loads(BUILD_FILE.read_text(encoding="utf-8")).get("tier")
                 if BUILD_FILE.exists() else "dev"),
        "data_version": DATA_VERSION,
        "data_on_disk": data_version(),
        "dev": runtime_env.DEV,
        "frozen": runtime_env.FROZEN,
        "features_on": len(features.enabled()),
    }


# ---------------------------------------------------------- версия данных

def data_version() -> int:
    try:
        return int(json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
                   .get("data_version", 0))
    except Exception:
        # Файла нет — это либо чистая установка, либо данные, заведённые до
        # того, как номер появился. И то и другое считаем первой версией:
        # ломать существующую память ради формальности незачем.
        return 0 if not (DATA_ROOT / "data").is_dir() else 1


def _write_data_version(n: int) -> None:
    try:
        SCHEMA_FILE.parent.mkdir(parents=True, exist_ok=True)
        SCHEMA_FILE.write_text(
            json.dumps({"data_version": n,
                        "note": "Формат данных в этой папке. Приложение с "
                                "меньшим номером их не тронет."},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("не смогла записать версию данных: %s", e)


# Миграции: номер «во что поднимаем» → что для этого сделать.
# Функция обязана быть повторяемой: если её прервали на середине, второй
# запуск должен доделать, а не сломать.
MIGRATIONS: dict = {}


def check_data() -> tuple[bool, str]:
    """Можно ли работать с тем, что лежит в data/.

    Возвращает (можно, что сказать человеку). Зовётся при старте до того,
    как хоть что-то будет записано.
    """
    on_disk = data_version()

    if on_disk > DATA_VERSION:
        return False, (
            f"Данные в папке data записаны версией новее этой "
            f"(формат {on_disk}, я понимаю {DATA_VERSION}). Скорее всего, "
            f"это откат на старую версию. Ничего не трогаю, чтобы не "
            f"испортить память — поставь версию поновее или убери data в "
            f"сторону, если хочешь начать заново.")

    if on_disk == DATA_VERSION:
        return True, ""

    for step in range(on_disk + 1, DATA_VERSION + 1):
        fn = MIGRATIONS.get(step)
        if fn is None:
            log.warning("нет миграции до формата %s — просто помечаю", step)
            continue
        try:
            log.info("перевожу данные в формат %s…", step)
            fn()
        except Exception as e:
            return False, (f"не смогла перевести данные в формат {step}: {e}. "
                           f"Ничего не меняла.")
    _write_data_version(DATA_VERSION)
    return True, (f"данные переведены в формат {DATA_VERSION}"
                  if on_disk else "")
