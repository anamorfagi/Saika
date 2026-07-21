"""Файловые «руки» Сайки — работа с файлами в разрешённых папках.

Безопасность на первом месте: все операции ЖЁСТКО заперты внутри
files.roots из config.json (по умолчанию F:/AI_load_work). Путь наружу
(..\\, другой диск, симлинк) — отказ. Удаление — не настоящее: файл
переезжает в _trash внутри корня (можно вернуть руками).

Инструменты (function calling, подключает server/llm/tools.py):
  fs_list, fs_read, fs_write, fs_mkdir, fs_rename, fs_move, fs_delete,
  fs_open (открыть папку/файл в проводнике — видимо для пользователя).
"""
import logging
import os
import shutil
import time
from pathlib import Path

from server.config import CFG

log = logging.getLogger("saika.files")

TRASH_NAME = "_trash"


def roots() -> list[Path]:
    out = []
    for r in CFG.get("files.roots", ["F:/AI_load_work"]):
        try:
            out.append(Path(r).resolve())
        except Exception:
            continue
    return out


def _resolve(user_path: str) -> Path:
    """Путь пользователя -> абсолютный, строго внутри разрешённых корней.
    Относительный путь трактуем от первого корня."""
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
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text or "", encoding="utf-8")
    return f"записала {p} ({len(text or '')} символов)"


def fs_mkdir(path: str) -> str:
    p = _resolve(path)
    p.mkdir(parents=True, exist_ok=True)
    return f"папка готова: {p}"


def fs_rename(path: str, new_name: str) -> str:
    p = _resolve(path)
    if not p.exists():
        return f"нет такого пути: {p}"
    if any(ch in new_name for ch in r'\/:*?"<>|'):
        return "в новом имени недопустимые символы"
    dst = p.with_name(new_name)
    p.rename(dst)
    return f"переименовала: {p.name} -> {dst.name}"


def fs_move(src: str, dst: str) -> str:
    s = _resolve(src)
    d = _resolve(dst)
    if not s.exists():
        return f"нет такого пути: {s}"
    if d.is_dir():
        d = d / s.name
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return f"перенесла: {s} -> {d}"


def fs_delete(path: str) -> str:
    """Не удаляем безвозвратно — переносим в _trash внутри корня."""
    p = _resolve(path)
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


CALLS = {
    "fs_list": lambda a: fs_list(a.get("path", "")),
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
]
NAMES = set(CALLS)
