"""Файловые «руки» Сайки — работа с файлами в разрешённых папках.

Безопасность на первом месте: все операции ЖЁСТКО заперты внутри
files.roots из config.json (по умолчанию F:/AI_load_work). Путь наружу
(..\\, другой диск, симлинк) — отказ. Удаление — не настоящее: файл
переезжает в _trash внутри корня (можно вернуть руками).

Инструменты (function calling, подключает anamorf/llm/tools.py):
  fs_list, fs_read, fs_write, fs_mkdir, fs_rename, fs_move, fs_delete,
  fs_open (открыть папку/файл в проводнике — видимо для пользователя).
"""
import json
import logging
import os
import shutil
import time
from pathlib import Path

from anamorf.config import CFG, ROOT

log = logging.getLogger("saika.files")

TRASH_NAME = "_trash"


def _default_root() -> str:
    """Папка самой Сайки. УМОЛЧАНИЕ ПО МЕСТУ, А НЕ ПО ПАМЯТИ (2026-08-13,
    живой отказ: человек четыре раза сказал «просто открой проводник» и
    четыре раза получил «папки F:\\AI_load_work тут нет». В конфиге
    files.roots отсутствовал, а в коде стояло умолчание «F:/AI_load_work» —
    чей-то путь с переносимого диска, которого на этой машине нет и не
    было. Рабочая папка указывала в никуда, и всё файловое молча ломалось.)"""
    return str(Path(__file__).resolve().parent.parent)


def roots() -> list[Path]:
    out = []
    for r in CFG.get("files.roots", None) or [_default_root()]:
        try:
            rp = Path(r).resolve()
        except Exception:
            continue
        out.append(rp)
    # все настроенные корни мертвы (сменилась буква диска, папка переехала) —
    # не оставляем её без рук: своя папка есть всегда
    if out and not any(r.exists() for r in out):
        log.warning("Ни один рабочий корень не существует (%s) — беру %s",
                    ", ".join(str(r) for r in out), _default_root())
        out.append(Path(_default_root()).resolve())
    return out


# СИСТЕМНЫЕ ПУТИ (2026-07-28, просьба владельца). files.roots задаёт, КУДА
# пускать, но если владелец однажды разрешит широкий корень (C:\ целиком),
# «удали лишнее» не должно уметь снести Windows. Каталоги ниже закрыты для
# ИЗМЕНЕНИЙ всегда, независимо от roots; читать/смотреть — можно, это
# безопасно и нужно для «что у меня в системе».
def _danger_roots() -> list:
    import os as _o
    out = []
    for env, fb in (("SystemRoot", r"C:\Windows"),
                    ("ProgramFiles", r"C:\Program Files"),
                    ("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                    ("ProgramData", r"C:\ProgramData")):
        try:
            out.append(Path(_o.environ.get(env, fb)).resolve())
        except Exception:
            pass
    return out


def _deny_if_dangerous(p: Path):
    for r in _danger_roots():
        if p == r or r in p.parents:
            raise PermissionError(
                f"отказ: {p} — системный путь, менять там что-либо опасно "
                "для Windows. Читать можно, менять — нет.")
    low = str(p).lower()
    if "$recycle.bin" in low or "system volume information" in low:
        raise PermissionError("отказ: служебная область диска")


def _resolve(user_path: str, write: bool = False) -> Path:
    """Путь пользователя -> абсолютный, строго внутри разрешённых корней.
    Относительный путь трактуем от первого корня. write=True — операция
    меняет диск, для неё системные каталоги закрыты всегда."""
    if not user_path:
        raise PermissionError("пустой путь")
    p = Path(str(user_path).strip().strip('"'))
    rs = roots()
    if not rs:
        raise PermissionError("нет разрешённых папок (files.roots в config)")
    if not p.is_absolute():
        p = rs[0] / p
    p = p.resolve()
    for r in rs:
        if p == r or r in p.parents:
            if write:
                _deny_if_dangerous(p)
            return p
    raise PermissionError(
        f"путь вне разрешённых папок ({', '.join(str(r) for r in rs)})")


def fs_list(path: str = "") -> str:
    p = _resolve(path or str(roots()[0]))
    if not p.exists():
        return f"нет такой папки: {p}"
    if p.is_file():
        return f"{p} — это файл ({p.stat().st_size} байт)"
    rows = []
    for child in sorted(p.iterdir(),
                        key=lambda c: (c.is_file(), c.name.lower())):
        if child.name == TRASH_NAME:
            continue
        if child.is_dir():
            rows.append(f"[папка] {child.name}")
        else:
            rows.append(f"        {child.name} · {child.stat().st_size} байт")
    return f"{p}:\n" + ("\n".join(rows) if rows else "(пусто)")


def fs_read(path: str) -> str:
    p = _resolve(path)
    if not p.is_file():
        return f"нет такого файла: {p}"
    if p.stat().st_size > 512 * 1024:
        return f"файл великоват ({p.stat().st_size} байт) — читаю только начало:\n" \
            + p.read_text(encoding="utf-8", errors="replace")[:6000]
    text = p.read_text(encoding="utf-8", errors="replace")
    return text[:6000] + ("…(обрезано)" if len(text) > 6000 else "")


def fs_write(path: str, text: str = "") -> str:
    p = _resolve(path, write=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text or "", encoding="utf-8")
    return f"записала {p} ({len(text or '')} символов)"


def fs_mkdir(path: str) -> str:
    p = _resolve(path, write=True)
    p.mkdir(parents=True, exist_ok=True)
    return f"папка готова: {p}"


def fs_rename(path: str, new_name: str) -> str:
    p = _resolve(path, write=True)
    if not p.exists():
        return f"нет такого пути: {p}"
    if any(ch in new_name for ch in r'\/:*?"<>|'):
        return "в новом имени недопустимые символы"
    dst = p.with_name(new_name)
    p.rename(dst)
    return f"переименовала: {p.name} -> {dst.name}"


def fs_move(src: str, dst: str) -> str:
    s = _resolve(src, write=True)
    d = _resolve(dst, write=True)
    if not s.exists():
        return f"нет такого пути: {s}"
    if d.is_dir():
        d = d / s.name
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return f"перенесла: {s} -> {d}"


def fs_delete(path: str) -> str:
    """Не удаляем безвозвратно — переносим в _trash внутри корня."""
    p = _resolve(path, write=True)
    if not p.exists():
        return f"нет такого пути: {p}"
    root = next(r for r in roots() if p == r or r in p.parents)
    if p == root:
        return "корневую папку не трогаю"
    trash = root / TRASH_NAME
    trash.mkdir(exist_ok=True)
    dst = trash / f"{int(time.time())}_{p.name}"
    shutil.move(str(p), str(dst))
    return f"убрала в корзину ({dst}) — можно вернуть, если что"


def fs_open(path: str = "") -> str:
    """Открыть папку/файл в проводнике — видимое действие для пользователя."""
    p = _resolve(path or str(roots()[0]))
    if not p.exists():
        return f"нет такого пути: {p}"
    os.startfile(str(p))  # noqa: S606 — намеренно, Windows
    return f"открыла в проводнике: {p}"


def fs_close_windows() -> str:
    """Закрыть окна проводника (просьба «закрой папки»)."""
    try:
        import subprocess
        # мягко: закрываем окна Explorer через COM — без убийства explorer.exe
        script = ("$sh = New-Object -ComObject Shell.Application; "
                  "$sh.Windows() | ForEach-Object { $_.Quit() }")
        subprocess.run(["powershell", "-NoProfile", "-Command", script],
                       timeout=15, check=False,
                       creationflags=0x08000000)  # CREATE_NO_WINDOW
        return "закрыла окна проводника"
    except Exception as e:
        return f"не вышло закрыть окна: {e}"


# ---------------- именованные места («это — рабочая папка») ----------------
# Пользователь один раз называет папку по-человечески, Сайка запоминает имя
# -> путь. Дальше «открой рабочую папку» знает, где это. Живёт в
# data/places.json. НЕ ограничено files.roots (это закладки, а не операции).
_PLACES = ROOT / "data" / "places.json"


def _places_load() -> dict:
    try:
        return json.loads(_PLACES.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _place_path(v) -> str:
    """Значение места: строка (старый формат) или словарь (новый)."""
    if isinstance(v, dict):
        return str(v.get("path") or "")
    return str(v or "")


def _places_write(d: dict):
    _PLACES.parent.mkdir(exist_ok=True)
    _PLACES.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                       encoding="utf-8")


def place_save(name: str, path: str) -> str:
    name = (name or "").strip().lower()
    path = (path or "").strip().strip('"')
    if not name or not path:
        return "нужны имя и путь"
    d = _places_load()
    old = d.get(name)
    n = int(old.get("n", 0)) if isinstance(old, dict) else 0
    # человек назвал место сам — это сильнее любого автозапоминания
    d[name] = {"path": path, "n": n, "trust": "сказал человек"}
    _places_write(d)
    return f"запомнила: «{name}» = {path}"


def place_seen(name: str, path: str) -> int:
    """ЗАПОМНИТЬ МЕСТО, КУДА ЧЕЛОВЕК ПРИВЁЛ САМ (2026-08-18).

    Владелец, дословно: «если мы напрямую будем просить „изучи мой ПК“, это
    будет звучать как „найди все мои секреты“… просто когда мы с ней будем
    говорить „открой то, открой это“ — куда мы будем приходить первые разы,
    пускай и запоминает как доверенные человеком».

    Он прав, и это не только про такт. Обход дисков заранее — это догадка о
    том, что человеку важно, по косвенным признакам: размеру папки, имени,
    расположению. А просьба «открой Ламоду» — прямое указание, и стоит она
    ноль ресурсов: мы туда всё равно идём. Место, куда привели, доверено по
    построению; место, которое нашёл сканер, — только предположение.

    Считаем визиты: из счётчика потом растут мгновенные пути. Один заход —
    случайность, три — привычка, и такую фразу уже можно исполнять не
    думая.

    Возвращает, сколько раз сюда приходили.
    """
    name = (name or "").strip().lower()
    path = (path or "").strip().strip('"')
    if not name or not path or len(name) < 3:
        return 0
    d = _places_load()
    cur = d.get(name)
    # человеческое имя не перебиваем автоматическим: он назвал — ему виднее
    if isinstance(cur, dict) and cur.get("trust") == "сказал человек" \
            and _place_path(cur) != path:
        return int(cur.get("n", 0))
    n = int(cur.get("n", 0)) if isinstance(cur, dict) else (1 if cur else 0)
    n += 1
    d[name] = {"path": path, "n": n, "trust": "приходили вместе"}
    try:
        _places_write(d)
    except Exception as e:
        log.debug("место «%s» не записалось: %s", name, e)
    return n


def place_habit(name: str, min_n: int = 3):
    """ПРИВЫЧНОЕ МЕСТО — то, куда ходили уже несколько раз (2026-08-18).

    Владелец: «постепенно формировать рефлексы у себя для моментальных
    запусков». Вот порог, после которого фразу можно исполнять не думая.

    Отличие от place_resolve: тот отвечает на любое похожее имя, потому что
    его зовёт МОДЕЛЬ — она уже подумала и решила, что речь о месте. Здесь
    решения ещё не было: фразу перехватывают ДО модели, и ошибиться нельзя.
    Поэтому и порог: три захода — это привычка, один — случайность, а по
    случайности молча открывать папку вместо разговора нельзя.

    Возвращает путь или None.
    """
    name = (name or "").strip().lower()
    if len(name) < 3:
        return None
    d = _places_load()
    q = _stems(name)
    if not q:
        return None
    best, best_score, best_n = None, 0, 0
    for k, v in d.items():
        if not isinstance(v, dict):
            continue                       # старая запись без счётчика
        n = int(v.get("n", 0))
        if n < min_n and v.get("trust") != "сказал человек":
            continue
        ks = _stems(k)
        if not ks:
            continue
        # имя должно совпасть ЦЕЛИКОМ, а не пересечься одним словом:
        # «открой игры» не должно уводить в «игровая музыка»
        if not (q <= ks or ks <= q):
            continue
        score = len(q & ks)
        if score > best_score or (score == best_score and n > best_n):
            best, best_score, best_n = _place_path(v), score, n
    if best and Path(best).is_dir():
        return best
    return None


def places_top(limit: int = 12) -> list:
    """Куда ходят чаще всего — для промпта и для будущих быстрых путей."""
    d = _places_load()
    items = []
    for k, v in d.items():
        items.append({"name": k, "path": _place_path(v),
                      "n": int(v.get("n", 1)) if isinstance(v, dict) else 1,
                      "trust": (v.get("trust", "") if isinstance(v, dict)
                                else "сказал человек")})
    items.sort(key=lambda i: -i["n"])
    return items[:limit]


def _stems(s: str) -> set:
    # грубая нормализация под русские склонения: слова по 5 первых букв,
    # мусорные слова-команды выкидываем («открой рабочую папку» -> {рабоч, папк})
    stop = {"открой", "открыть", "покажи", "зайди", "перейди", "папку",
            "папка", "папке", "в", "на", "мою", "мой", "это"}
    out = set()
    for w in "".join(c if c.isalnum() or c == " " else " "
                     for c in s.lower()).split():
        if w in stop or len(w) < 3:
            continue
        out.add(w[:5])
    return out


def place_resolve(name: str):
    name = (name or "").strip().lower()
    d = _places_load()
    if name in d:
        return _place_path(d[name])
    q = _stems(name)
    if not q:
        return None
    best, best_score, best_n = None, 0, -1
    for k, v in d.items():
        score = len(q & _stems(k))
        # при равном совпадении слов выигрывает то место, куда ходили чаще:
        # «проекты» у человека одни, а папок с похожим именем может быть три
        n = int(v.get("n", 1)) if isinstance(v, dict) else 1
        if score > best_score or (score == best_score and score and n > best_n):
            best, best_score, best_n = _place_path(v), score, n
    return best


def place_open(name: str) -> str:
    p = place_resolve(name)
    if not p:
        known = ", ".join(_places_load()) or "пусто"
        return f"не знаю места «{name}». Знаю: {known}"
    path = Path(p)
    if not path.exists():
        return f"место «{name}» ({p}) больше не существует"
    os.startfile(str(path))  # noqa: S606
    return f"открыла «{name}»: {p}"


def place_list() -> str:
    d = _places_load()
    return ("; ".join(f"{k} -> {v}" for k, v in d.items())
            if d else "запомненных мест пока нет")


CALLS = {
    "fs_list": lambda a: fs_list(a.get("path", "")),
    "place_save": lambda a: place_save(a.get("name", ""), a.get("path", "")),
    "place_open": lambda a: place_open(a.get("name", "")),
    "place_list": lambda a: place_list(),
    "fs_read": lambda a: fs_read(a.get("path", "")),
    "fs_write": lambda a: fs_write(a.get("path", ""), a.get("text", "")),
    "fs_mkdir": lambda a: fs_mkdir(a.get("path", "")),
    "fs_rename": lambda a: fs_rename(a.get("path", ""), a.get("new_name", "")),
    "fs_move": lambda a: fs_move(a.get("src", ""), a.get("dst", "")),
    "fs_delete": lambda a: fs_delete(a.get("path", "")),
    "fs_open": lambda a: fs_open(a.get("path", "")),
    "fs_close_windows": lambda a: fs_close_windows(),
}


def _fn(name, desc, props, required):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props,
                       "required": required}}}


_P = {"path": {"type": "string", "description": "путь (можно относительный "
                                                "от рабочей папки)"}}

SCHEMAS = [
    _fn("fs_list", "Показать содержимое папки в рабочей области. Пустой "
        "path = корень рабочей папки.", dict(_P), []),
    _fn("fs_read", "Прочитать текстовый файл (задание из почты, заметку, "
        "любой текст).", dict(_P), ["path"]),
    _fn("fs_write", "Создать или перезаписать текстовый файл (блокнот, "
        "заметку, результат).", {**_P, "text": {"type": "string",
        "description": "содержимое файла"}}, ["path"]),
    _fn("fs_mkdir", "Создать папку (вместе с родительскими).",
        dict(_P), ["path"]),
    _fn("fs_rename", "Переименовать файл или папку.", {**_P,
        "new_name": {"type": "string", "description": "новое имя без пути"}},
        ["path", "new_name"]),
    _fn("fs_move", "Перенести файл/папку в другое место рабочей области.",
        {"src": {"type": "string"}, "dst": {"type": "string"}},
        ["src", "dst"]),
    _fn("fs_delete", "Убрать файл/папку в корзину рабочей области "
        "(_trash, восстановимо).", dict(_P), ["path"]),
    _fn("fs_open", "Открыть папку или файл в проводнике Windows — "
        "пользователь увидит окно. Зови когда просят «открой папку».",
        dict(_P), []),
    _fn("fs_close_windows", "Закрыть все окна проводника — когда просят "
        "«закрой папки».", {}, []),
    _fn("place_save", "Запомнить именованное место: пользователь называет "
        "папку по-человечески и даёт путь («это рабочая папка, "
        "F:\\AI_load_work»). Дальше открывать по имени.",
        {"name": {"type": "string", "description": "человеческое имя, напр. «рабочая папка»"},
         "path": {"type": "string", "description": "полный путь"}},
        ["name", "path"]),
    _fn("place_open", "Открыть ранее запомненное место по имени («открой "
        "рабочую папку»).",
        {"name": {"type": "string"}}, ["name"]),
    _fn("place_list", "Показать все запомненные места.", {}, []),
]
NAMES = set(CALLS)
