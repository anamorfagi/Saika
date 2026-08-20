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

class FeatureOff(AttributeError):
    """Фичи нет в этой сборке. Не поломка, а сознательный выбор при сборке.

    Наследуется от AttributeError не для красоты: так работает обычный
    `getattr(модуль, "ИМЯ", запасное)`. Код, который умеет обойтись без
    фичи, тихо берёт запасное значение; код, который не умеет, получает
    объяснение словами. Оба поведения — из одной строчки на месте вызова.
    """


_said: set = set()


def _once(key: str, msg: str) -> None:
    """Сказать один раз. Отсутствующую фичу могут дёргать сотни раз
    подряд — из потока звука, из опроса панели, — и повторять это в лог
    значит утопить в нём всё остальное."""
    if key not in _said:
        _said.add(key)
        log.info(msg)


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

    def __call__(self, *a, **kw):
        """Вызов отсутствующей фичи возвращает «ничего».

        Пустой кортеж, а не None, выбран нарочно: он ложный в проверках,
        по нему можно пройти циклом, и выражение `(x.get("a") or [])`
        отработает как задумано. Отсутствие фичи не должно ронять то, что
        к ней обращается мимоходом, — оно должно просто ничего не дать.
        """
        _once(f"{self._id}.вызов",
              f"«{self._title}» не в этой сборке — пропускаю обращение")
        return ()

    def __iter__(self):
        return iter(())

    def __getattr__(self, name):
        # Служебные имена (repr, копирование, отладчики) спрашивают у
        # объекта всё подряд. Ругаться на них — значит ронять инструменты
        # там, где никто ничего не просил.
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        # Возвращаем себя же: так работают и `hearing.feed(p)`, и
        # `hearing.STATE.get("tags")`. Ошибку поднимаем только там, где
        # результат действительно нужен как значение, — а это видно по
        # тому, что его пытаются использовать, а не вызвать.
        _once(f"{self._id}.{name}",
              f"«{self._title}» не в этой сборке — {name} недоступно")
        return self



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
    # Имя фичи и имя модуля совпадают не всегда: фича «git» живёт в
    # git_sync.py, «bench» — в hear_bench.py. Спрашиваем реестр, а не
    # угадываем по идентификатору: угадывание уже стоило нам пяти сотен
    # трейсбеков в логе на ровном месте.
    name = module
    if not name:
        mods = [m for m in f.get("mods", []) if m.endswith(".py")]
        name = mods[0][:-3].replace("/", ".") if mods else feature_id
    try:
        import importlib
        # Путь внутри пакета («llm.dreampc») — тоже с точкой, поэтому
        # проверяем не наличие точки, а начало строки.
        if not name.startswith("anamorf"):
            name = f"anamorf.{name}"
        return importlib.import_module(name)
    except Exception as e:
        log.warning("фича «%s» включена, но модуль не загрузился: %s", title, e)
        return _Absent(feature_id, title)

# ══════════════════════════════════════════════════════════════════════
#  ИМПОРТ ТОГО, ЧЕГО В СБОРКЕ НЕТ
# ══════════════════════════════════════════════════════════════════════
#
# В коде полсотни отложенных импортов: `from anamorf import browser_hands`
# внутри функции, которая вызывается по кнопке. Это правильный приём — так
# тяжёлое не грузится при старте. Но в сборке без этой фичи файла нет, и
# импорт падает ImportError в тот момент, когда человек нажал кнопку.
#
# Обойти это, обернув каждое место в try/except, нельзя честно: мест много,
# новые появляются, и проверить, что нигде не забыли, невозможно.
#
# Поэтому вмешиваемся на уровне самого механизма импорта. Если модуль
# ЧИСЛИТСЯ В РЕЕСТРЕ и его фича выключена — отдаём заглушку вместо ошибки.
# Ключевое слово «числится»: опечатку в имени модуля это не спрячет, для
# неё ImportError останется как был. Прячется только то, что мы сами
# сознательно не положили в сборку.


class _AbsentLoader:
    def __init__(self, fullname: str, feature_id: str):
        self.fullname, self.fid = fullname, feature_id

    def create_module(self, spec):
        import types
        f = _index.get(self.fid) or {}
        stub = _Absent(self.fid, f.get("title", self.fid))
        mod = types.ModuleType(self.fullname)
        mod.__dict__["__getattr__"] = lambda name: getattr(stub, name)
        mod.__dict__["__absent__"] = True
        mod.__dict__["__feature__"] = self.fid
        return mod

    def exec_module(self, module):
        return None


class _AbsentFinder:
    """Подставляет заглушку вместо модулей выключенных фич."""

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith("anamorf."):
            return None
        _load()
        rel = fullname[len("anamorf."):].replace(".", "/")
        fid = of_module(rel + ".py") or of_module(rel + "/__init__.py")
        if not fid or on(fid):
            return None            # либо не наше, либо фича включена
        import importlib.util
        _once(f"import:{fullname}",
              f"«{(_index.get(fid) or {}).get('title', fid)}» не в этой "
              f"сборке — {fullname} подменён заглушкой")
        return importlib.util.spec_from_loader(
            fullname, _AbsentLoader(fullname, fid))


def install_import_guard() -> bool:
    """Включить подмену. Зовётся один раз, при старте пакета.

    В рабочей копии ничего не делает: там включено всё, и подменять нечего.
    Заодно это значит, что настоящие ошибки импорта при разработке видны
    как есть, а не прячутся за вежливой заглушкой.
    """
    import sys
    if any(isinstance(f, _AbsentFinder) for f in sys.meta_path):
        return False
    if not is_build():
        return False
    sys.meta_path.insert(0, _AbsentFinder())
    return True
