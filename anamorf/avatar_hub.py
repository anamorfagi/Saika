"""Библиотека аватаров: 2D и 3D, загрузка своих, переключение.

ЗАЧЕМ. До сих пор аватар был ОДИН файл — путь в config (avatar.web.model).
Чтобы поменять внешность, надо было лезть в json и перезапускаться. Наряды
(outfits) решали только половину задачи: это подмена того же тела другим
.vrm, а не другой персонаж и уж точно не 2D.

ЧТО ЗДЕСЬ. Папка models/avatar/library — всё, что человек туда положил,
само становится доступным в интерфейсе. Разбираем по расширению:

  .vrm / .glb / .gltf     — 3D, рисует three.js как раньше
  .png / .webp / .gif     — 2D, спрайт с процедурной анимацией
  папка с .model3.json    — Live2D Cubism

ПРО LIVE2D ЧЕСТНО. Формат Cubism проприетарный: рендерить его можно только
их же SDK, у которого своя лицензия (бесплатна для мелких компаний, но это
отдельное соглашение, а не MIT). Поэтому библиотека такие модели ВИДИТ и
показывает в списке, но подписывает, что для показа нужен их SDK — молча
подсовывать человеку лицензионную мину нельзя, он собирается это продавать.

ПОЧЕМУ НЕ ТРОГАЕМ СТАРЫЙ ПУТЬ. avatar.web.model остаётся главным ключом
конфига — просто теперь его пишет эта библиотека, а не человек руками. Всё,
что уже настроено (наряды, анимации, размер), продолжает работать как было.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from anamorf.config import CFG, ROOT

log = logging.getLogger("saika.avatar_hub")

KIND_3D = {".vrm", ".glb", ".gltf"}
KIND_2D = {".png", ".webp", ".gif", ".jpg", ".jpeg"}
MAX_MB = 300


def lib_dir() -> Path:
    raw = CFG.get("avatar.web.library_dir", "models/avatar/library")
    p = Path(raw)
    p = p if p.is_absolute() else (ROOT / raw)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _kind(p: Path) -> str:
    if p.is_dir():
        return "live2d" if any(p.glob("*.model3.json")) else ""
    s = p.suffix.lower()
    if s in KIND_3D:
        return "3d"
    if s in KIND_2D:
        return "2d"
    return ""


def current_path() -> Path:
    raw = CFG.get("avatar.web.model", "models/avatar/model.vrm")
    p = Path(raw)
    return p if p.is_absolute() else (ROOT / raw)


def current_kind() -> str:
    k = _kind(current_path())
    return k or "3d"


def scan() -> list:
    """Всё, что можно надеть. Плюс текущая модель, даже если она лежит вне
    библиотеки — иначе человек, у которого аватар настроен по-старому,
    открыл бы список и не увидел там того, кого видит на экране."""
    cur = current_path().resolve()
    out, seen = [], set()

    def add(p: Path, where: str):
        k = _kind(p)
        if not k:
            return
        rp = p.resolve()
        if rp in seen:
            return
        seen.add(rp)
        try:
            size = (sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                    if p.is_dir() else p.stat().st_size)
        except OSError:
            size = 0
        out.append({
            "name": p.stem if p.is_file() else p.name,
            "file": p.name, "kind": k, "where": where,
            "size_mb": round(size / 1048576, 1),
            "current": rp == cur,
            # Live2D видим, но включить не даём: рендер требует их SDK
            "playable": k != "live2d",
            "note": ("нужен Cubism SDK — формат проприетарный"
                     if k == "live2d" else ""),
        })

    d = lib_dir()
    for p in sorted(d.iterdir(), key=lambda x: x.name.lower()):
        add(p, "library")
    if cur.exists():
        add(cur, "config")
    # наряды показываем отдельной пометкой: это то же тело, другая одежда
    outfits = ROOT / str(CFG.get("avatar.web.outfits_dir",
                                 "models/avatar/outfits"))
    if outfits.exists():
        for p in sorted(outfits.glob("*.vrm")):
            add(p, "outfit")
    return out


def _find(name: str) -> Path | None:
    q = (name or "").strip().lower()
    if not q:
        return None
    for p in lib_dir().iterdir():
        if _kind(p) and (p.stem.lower() == q or p.name.lower() == q):
            return p
    outfits = ROOT / str(CFG.get("avatar.web.outfits_dir",
                                 "models/avatar/outfits"))
    if outfits.exists():
        for p in outfits.glob("*.vrm"):
            if p.stem.lower() == q:
                return p
    cur = current_path()
    if cur.exists() and cur.stem.lower() == q:
        return cur
    return None


def select(name: str) -> str:
    p = _find(name)
    if not p:
        return f"Не нашла «{name}» в библиотеке аватаров."
    k = _kind(p)
    if k == "live2d":
        return ("Это модель Live2D Cubism. Её формат проприетарный и "
                "рисуется только их SDK — включить прямо сейчас не могу. "
                "Файлы лежат на месте, ничего не потеряно.")
    try:
        rel = p.resolve().relative_to(ROOT.resolve())
        CFG.set("avatar.web.model", str(rel).replace("\\", "/"))
    except ValueError:
        CFG.set("avatar.web.model", str(p.resolve()).replace("\\", "/"))
    CFG.set("avatar.web.kind", k)
    return f"Надела «{p.stem}»." + (
        " Обнови окно аватара, если оно уже открыто." if k == "2d" else "")


def save_upload(filename: str, data: bytes) -> str:
    """Положить присланный файл в библиотеку."""
    name = os.path.basename(filename or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("плохое имя файла")
    ext = Path(name).suffix.lower()
    if ext not in KIND_3D | KIND_2D:
        raise ValueError("умею .vrm, .glb, .gltf для 3D и .png, .webp, "
                         ".gif, .jpg для 2D")
    if len(data) > MAX_MB * 1048576:
        raise ValueError(f"файл больше {MAX_MB} МБ")
    dest = lib_dir() / name
    if dest.exists():
        # не затираем молча: у человека уже может быть настроен этот аватар
        dest = lib_dir() / f"{Path(name).stem}_{int(time.time())}{ext}"
    dest.write_bytes(data)
    return dest.stem


def delete(name: str) -> str:
    """Убираем в _trash, а не стираем: аватар человек рисовал или покупал,
    случайный клик не должен стоить ему модели."""
    p = _find(name)
    if not p:
        return f"Не нашла «{name}»."
    if p.resolve() == current_path().resolve():
        return ("Эта модель сейчас надета — сначала выбери другую, потом "
                "удаляй.")
    trash = lib_dir() / "_trash"
    trash.mkdir(exist_ok=True)
    dest = trash / p.name
    if dest.exists():
        dest = trash / f"{p.stem}_{int(time.time())}{p.suffix}"
    shutil.move(str(p), str(dest))
    return f"Убрала «{p.stem}» в _trash — оттуда можно вернуть."


def open_folder() -> str:
    d = lib_dir()
    try:
        if os.name == "nt":
            os.startfile(str(d))       # noqa: S606 — своя же папка проекта
        else:
            subprocess.Popen(["xdg-open", str(d)])
    except Exception as e:
        return f"Не смогла открыть папку: {e}"
    return f"Открыла {d}"


# ───────────────────────── настройки внешности ─────────────────────────
# Ровно те ручки, которые человек крутит глазами, а не в конфиге. Каждая с
# дефолтом — иначе первый заход в панель показал бы пустые поля.
SETTINGS = (
    ("avatar.web.scale", 1.0, float),
    ("avatar.web.offset_y", 0.0, float),
    ("avatar.web.bg", "", str),            # цвет фона, пусто = прозрачный
    ("avatar.enabled", False, bool),
    ("avatar.llm_gestures", True, bool),
    ("avatar.idle_fidgets", True, bool),
    ("avatar.look_at_cursor", True, bool),
    ("avatar.2d.sway", 1.0, float),        # сила покачивания у 2D
    ("avatar.2d.breath", 1.0, float),      # дыхание в покое
)


def settings() -> dict:
    out = {k: CFG.get(k, d) for k, d, _t in SETTINGS}
    out["kind"] = current_kind()
    out["model"] = current_path().stem
    return out


def set_settings(payload: dict) -> dict:
    types = {k: t for k, _d, t in SETTINGS}
    for k, v in (payload or {}).items():
        if k not in types:
            continue
        t = types[k]
        try:
            CFG.set(k, bool(v) if t is bool else t(v))
        except (TypeError, ValueError):
            raise ValueError(f"«{k}»: не разобрала значение {v!r}")
    return settings()
