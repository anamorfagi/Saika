"""Из чего собрана ЭТА сборка.

Реестр лежит в features.json — он один на всё: из него берутся галочки
компилятора клиентского билда, список файлов, которые копируются в сборку,
набор зависимостей, экраны первого запуска и то, что рисуется в интерфейсе.

Раньше это знание было размазано по пяти местам: список пакетов — в
setup/ensure_features.py, имена ключей — в secrets.example.json, тексты про
возможности — внутри ui/index.html, состав установки — в setup/first_run.py,
а что не должно попасть клиенту — вообще нигде. Пять списков, которые никто
не синхронизировал.

Что включено именно здесь, написано в build.json — его кладёт компилятор.
Нет файла — значит, это рабочая копия автора, и включено всё.

Пользоваться так:

    from anamorf import features
    if features.on("messengers"):
        from anamorf import messengers

Импорт выключенной фичи ОБЯЗАН быть внутри такой проверки и внутри функции.
Наверху модуля он выполнится при старте, файла в сборке не будет, и
приложение упадёт на импорте — то есть ещё до того, как сможет объяснить,
что случилось.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("features")

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "features.json"
BUILD_PATH = ROOT / "build.json"

_registry: dict | None = None
_build: dict | None = None
_index: dict[str, dict] | None = None


def _load() -> None:
    global _registry, _build, _index
    if _index is not None:
        return
    try:
        _registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        # Без реестра работаем как раньше: всё включено. Падать из-за
        # отсутствия описи неправильно — опись нужна сборке, а не разговору.
        log.warning("features.json не прочитан (%s) — считаю, что включено всё", e)
        _registry = {"groups": []}
    _index = {f["id"]: f
              for g in _registry.get("groups", [])
              for f in g.get("features", [])}
    for g in _registry.get("groups", []):
        for f in g.get("features", []):
            f["group"] = g["id"]
            f["group_title"] = g.get("title", g["id"])
    try:
        _build = json.loads(BUILD_PATH.read_text(encoding="utf-8"))
    except Exception:
        _build = None


def is_build() -> bool:
    """Это собранный билд, а не рабочая копия?"""
    _load()
    return _build is not None


def on(feature_id: str) -> bool:
    """Есть ли эта фича в текущей сборке и включена ли она.

    В рабочей копии автора включено всё — иначе разработка превращается в
    угадывание, что сейчас доступно.
    """
    _load()
    f = _index.get(feature_id)
    if f is None:
        log.warning("спрашивают про неизвестную фичу %r", feature_id)
        return False
    if f.get("lock"):
        return True
    if _build is None:
        return True
    return feature_id in set(_build.get("features", []))


def enabled() -> list[str]:
    """Всё, что включено сейчас."""
    _load()
    return [fid for fid in _index if on(fid)]


def feature(feature_id: str) -> dict:
    _load()
    return dict(_index.get(feature_id) or {})


def all_features() -> list[dict]:
    _load()
    return [dict(f) for f in _index.values()]


def of_module(rel_path: str) -> str | None:
    """Какой фиче принадлежит файл. Путь — относительно anamorf/."""
    _load()
    rel = rel_path.replace("\\", "/").lstrip("./")
    for fid, f in _index.items():
        for m in f.get("mods", []):
            if m.endswith("/") and rel.startswith(m):
                return fid
            if m == rel:
                return fid
    return None


def keys_needed() -> list[dict]:
    """Ключи, которые есть смысл спросить в этой сборке.

    Спрашивать про Телеграм в билде без Телеграма — верный способ, чтобы
    экран первого запуска перестали читать.
    """
    _load()
    out = []
    for fid, f in _index.items():
        if not on(fid):
            continue
        for k in f.get("keys", []):
            out.append({**k, "feature": fid, "title": f.get("title", fid)})
    return out


def notices() -> list[str]:
    """Лицензионные обязательства включённых фич — для «О программе»."""
    _load()
    return [f["notice"] for fid, f in _index.items()
            if on(fid) and f.get("notice")]


def describe() -> dict:
    """Для панели диагностики и экрана «О программе»."""
    _load()
    en = enabled()
    return {
        "build": _build.get("version") if _build else None,
        "channel": _build.get("channel") if _build else "dev",
        "tier": _build.get("tier") if _build else "dev",
        "features_on": len(en),
        "features_total": len(_index),
        "enabled": sorted(en),
    }

class FeatureOff(RuntimeError):
    """Фичи нет в этой сборке. Не поломка, а сознательный выбор при сборке."""


class _Absent:
    """Заглушка вместо модуля выключенной фичи.

    Ложная при проверке (`if devboard:`), а при попытке что-то у неё
    вызвать объясняет словами, чего не хватает. Так отсутствие фичи
    перестаёт быть падением на импорте при старте и становится понятным
    ответом в тот момент, когда её действительно попросили.
    """

    __slots__ = ("_id", "_title")

    def __init__(self, feature_id: str, title: str):
        self._id, self._title = feature_id, title

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return f"<фича «{self._title}» не входит в эту сборку>"

    def __getattr__(self, name):
        raise FeatureOff(
            f"«{self._title}» не входит в эту сборку, поэтому {name} "
            f"недоступно. Если нужно — соберите версию с этой фичей.")


def optional(feature_id: str, module: str | None = None):
    """Модуль фичи, если она включена, иначе — понятная заглушка.

    Нужно, потому что импорт наверху модуля исполняется при старте: в
    сборке без этой фичи файла нет, и приложение падает на импорте — то
    есть ДО того, как способно объяснить, что случилось. Здесь же
    отсутствие фичи всплывает в момент обращения и человеческим текстом.
    """
    _load()
    f = _index.get(feature_id) or {}
    title = f.get("title", feature_id)
    if not on(feature_id):
        return _Absent(feature_id, title)
    name = module or feature_id
    try:
        import importlib
        return importlib.import_module(name if "." in name
                                       else f"anamorf.{name}")
    except Exception as e:
        log.warning("фича «%s» включена, но модуль не загрузился: %s", title, e)
        return _Absent(feature_id, title)
