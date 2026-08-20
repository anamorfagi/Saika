"""ПОИСК ПРОГРАММ ПО ДИСКАМ — когда в «Пуске» их нет (2026-08-14).

Владелец: «нужно сделать так, чтобы она сама первый раз по просьбе могла
найти программу — мы же знаем, где они примерно находятся. Пусть ищет в
системе и запоминает… потом, если запрос повторяется, она уже не думает,
херачит запуск».

ПОЧЕМУ ЭТО ОТДЕЛЬНЫЙ ФАЙЛ. Каталог из «Пуска» и реестра (pc_control.py,
app_memory.py) работает и трогать его незачем — он быстрый и покрывает
90% случаев. Здесь ТРЕТИЙ, медленный заход: включается, только когда те
два ничего не нашли, и его результат сразу уходит в память — чтобы
медленным он был ровно один раз в жизни.

ГДЕ ИЩЕМ. Не «по всему диску» — это минуты и сотни тысяч файлов. Игры и
программы лежат в предсказуемых местах, и мы их знаем:
  * Program Files / Program Files (x86) / LOCALAPPDATA\\Programs
  * библиотеки лаунчеров: Steam (steamapps\\common), Epic, GOG, HoYoPlay,
    Riot, Battle.net, EA — включая ДРУГИЕ диски: игры почти всегда стоят
    не на системном
  * папки верхнего уровня с говорящими именами: games, игры, программы,
    programs, soft, apps
Глубина ограничена: внутри такой папки исполняемый файл лежит на 1-3
уровне, глубже — ресурсы движка, туда лезть незачем.

ЧТО ОТСЕИВАЕМ. unins*, vcredist, dxsetup, crashhandler, launcher-helper и
прочую служебку: она мозолит выдачу и никогда не является тем, что просят.
"""
import logging
import os
import re
import time
from pathlib import Path

log = logging.getLogger("saika.finder")

_SKIP = re.compile(
    r"unins|uninstall|setup|vcredist|dxsetup|directx|redist|crashhandler|"
    r"crashpad|helper|updater|update\.exe|repair|report|dotnet|python|"
    r"launcher_helper|service|daemon|watchdog|installer", re.I)

# папки, внутрь которых лезть бессмысленно — там ресурсы, а не программы
_SKIP_DIR = re.compile(
    r"^(?:\.git|node_modules|__pycache__|cache|logs?|temp|tmp|"
    r"content|resources|assets|data|locale|plugins|redist|"
    r"windows|winsxs|drivers|system32|syswow64)$", re.I)

_LAUNCHER_SUB = ("steamapps/common", "steamlibrary/steamapps/common",
                 "epic games", "gog galaxy/games", "hoyoplay", "hoyoverse",
                 "riot games", "battle.net", "ea games", "origin games",
                 "games", "игры", "programs", "программы", "soft", "apps")

_index = {"apps": [], "built": 0.0}
_TTL = 6 * 3600


def _drives() -> list[Path]:
    """Диски, на которых имеет смысл искать."""
    out = []
    if os.name != "nt":
        return out
    import string
    for letter in string.ascii_uppercase:
        p = Path(f"{letter}:/")
        try:
            if p.exists():
                out.append(p)
        except Exception:
            continue
    return out


def roots() -> list[Path]:
    """Где искать. Порядок — от вероятного к менее вероятному."""
    out = []
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        v = os.environ.get(env)
        if v:
            out.append(Path(v))
    la = os.environ.get("LOCALAPPDATA")
    if la:
        out.append(Path(la) / "Programs")
    for d in _drives():
        try:
            for child in d.iterdir():
                if not child.is_dir():
                    continue
                low = child.name.lower()
                if any(low == s or low.startswith(s.split("/")[0])
                       for s in _LAUNCHER_SUB):
                    out.append(child)
                # SteamLibrary и подобное лежат на диске отдельной папкой
                if "steam" in low or "epic" in low or "hoyo" in low:
                    out.append(child)
        except Exception:
            continue
    # уточняющие подпапки лаунчеров
    extra = []
    for r in out:
        for sub in ("steamapps/common", "Games"):
            p = r / sub
            try:
                if p.is_dir():
                    extra.append(p)
            except Exception:
                pass
    seen, uniq = set(), []
    for p in out + extra:
        k = str(p).lower()
        if k not in seen and p.exists():
            seen.add(k)
            uniq.append(p)
    return uniq


def _walk(root: Path, depth: int, out: list, budget: dict):
    if depth < 0 or budget["files"] <= 0:
        return
    try:
        entries = list(root.iterdir())
    except Exception:
        return
    for e in entries:
        if budget["files"] <= 0:
            return
        try:
            if e.is_dir():
                if _SKIP_DIR.match(e.name):
                    continue
                _walk(e, depth - 1, out, budget)
            elif e.suffix.lower() == ".exe":
                budget["files"] -= 1
                if _SKIP.search(e.name) or _SKIP.search(str(e.parent.name)):
                    continue
                out.append({"name": e.stem, "path": str(e),
                            "folder": e.parent.name})
        except Exception:
            continue


def index(force=False) -> list:
    """Собрать (и закэшировать) список программ с дисков."""
    if not force and _index["apps"] and time.time() - _index["built"] < _TTL:
        return _index["apps"]
    t0 = time.time()
    apps, budget = [], {"files": 40000}      # потолок, чтобы не уйти в час
    for r in roots():
        _walk(r, 3, apps, budget)
    # одинаковые имена из разных мест — оставляем самое короткое по пути
    best = {}
    for a in apps:
        k = a["name"].lower()
        if k not in best or len(a["path"]) < len(best[k]["path"]):
            best[k] = a
    _index.update(apps=list(best.values()), built=time.time())
    log.info("Поиск по дискам: %d программ за %.1fс",
             len(_index["apps"]), time.time() - t0)
    return _index["apps"]


def search(query: str, limit: int = 4) -> list:
    """Найти программу по человеческому названию. Возвращает кандидатов
    в том же формате, что и каталог «Пуска»: {name, path, score}."""
    from anamorf.pc_control import _score
    q = (query or "").strip().lower()
    if not q:
        return []
    out = []
    for a in index():
        # сравниваем и с именем файла, и с именем ПАПКИ: у игр
        # исполняемый файл часто зовётся не как игра
        # (GenshinImpact.exe в HoYoPlay лежит рядом, но бывает launcher.exe
        # в папке «Genshin Impact»)
        sc = max(_score(a["name"], q), _score(a.get("folder", ""), q))
        if sc >= 45:
            out.append({"name": a["name"], "path": a["path"], "score": sc,
                        "folder": a.get("folder", "")})
    out.sort(key=lambda c: -c["score"])
    return out[:limit]
