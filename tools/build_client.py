"""Компилятор клиентского билда: из реестра фич — в готовую папку.

Собирает не «всё, что есть», а ровно то, что отмечено. Как сборка проекта в
игровом движке: выбрал профиль, нажал проверку, увидел ошибки сборки,
поправил, собрал.

    python tools\\build_client.py --check                 только проверить
    python tools\\build_client.py --profile base          собрать базовый
    python tools\\build_client.py --features pc,files,stt только эти
    python tools\\build_client.py --profile base --apply  собрать по-настоящему

Профили:
    min    только ядро — проверить, что система вообще живёт без всего
    base   то, что человек получает из коробки
    full   всё бесплатное издание
    pro    плюс лаборатория и обучение

Проверка отвечает на четыре вопроса, каждый из которых иначе всплывёт уже
у человека:

  1. Есть ли жёсткие ссылки на выключенные фичи? Модуль, который сверху
     пишет `from anamorf import messengers`, в билде без мессенджеров
     упадёт на импорте — то есть ДО того, как сможет объяснить, что не так.
     Такие импорты должны жить внутри функции и внутри features.on().
  2. Все ли модули приписаны к фичам.
  3. Не уехали ли в пакет личные пути автора и секреты.
  4. Собирается ли всё выбранное синтаксически.
"""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "anamorf"
OUT_ROOT = ROOT / "build"

# Следы машины автора. Попадут в пакет — уедут к человеку вместе с кодом.
PRIVATE = [
    ("C:\\AI\\Cnox", "путь к обходчику DPI на машине автора"),
    ("F:/AI_load_work", "рабочая папка автора"),
    ("anamorf.agi@", "личная почта автора"),
    ("домашний-ПК", "имя компьютера автора"),
]

PROFILES = {
    "min":  lambda f: bool(f.get("lock")),
    "base": lambda f: bool(f.get("lock") or f.get("base")),
    "full": lambda f: f.get("tier", "free") == "free" and
                      f.get("default", True) is not False or bool(f.get("lock") or f.get("base")),
    "pro":  lambda f: f.get("default", True) is not False or bool(f.get("lock") or f.get("base")),
}


def registry() -> dict:
    d = json.loads((ROOT / "features.json").read_text(encoding="utf-8"))
    return {f["id"]: f for g in d["groups"] for f in g["features"]}


def pick(feats: dict, profile: str | None, explicit: str | None) -> set[str]:
    if explicit:
        chosen = {s.strip() for s in explicit.split(",") if s.strip()}
        unknown = chosen - set(feats)
        if unknown:
            print(f"[!] неизвестные фичи: {', '.join(sorted(unknown))}")
            sys.exit(1)
        chosen |= {fid for fid, f in feats.items() if f.get("lock")}
    else:
        test = PROFILES[profile or "base"]
        chosen = {fid for fid, f in feats.items() if test(f)}
    # Инструменты разработчика не едут никогда — это не выбор, а правило.
    return {fid for fid in chosen if not feats[fid].get("dev")}


def module_owner(feats: dict) -> dict[str, str]:
    """Файл → фича. Пакеты (`stt/`) разворачиваем в конкретные файлы."""
    owner: dict[str, str] = {}
    for fid, f in feats.items():
        for m in f.get("mods", []):
            if m.endswith("/"):
                d = PKG / m.rstrip("/")
                if d.is_dir():
                    for p in d.rglob("*.py"):
                        owner[p.relative_to(PKG).as_posix()] = fid
            else:
                owner[m] = fid
    return owner


def hard_refs(owner: dict[str, str], on: set[str]) -> list[tuple]:
    """Импорты выключенного, выполняемые при старте.

    Ищем только импорты верхнего уровня: внутри функции импорт исполнится
    лишь тогда, когда до него дойдут, и его законное место — под проверкой
    features.on(). Наверху модуля он выстрелит при первом же запуске.
    """
    out = []
    for rel, fid in sorted(owner.items()):
        if fid not in on:
            continue                      # сам модуль в билд не едет
        p = PKG / rel
        if not p.exists():
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in tree.body:            # ТОЛЬКО верхний уровень
            names = []
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("anamorf"):
                tail = (node.module or "")[len("anamorf"):].lstrip(".")
                names = [f"{tail}/{a.name}" if tail else a.name for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name[len("anamorf."):] for a in node.names
                         if a.name.startswith("anamorf.")]
            for n in names:
                cand = (n.replace(".", "/") + ".py",
                        n.replace(".", "/") + "/__init__.py")
                dep = next((owner[c] for c in cand if c in owner), None)
                if dep and dep not in on:
                    out.append((rel, node.lineno, n, dep))
    return out


def check(feats: dict, on: set[str]) -> int:
    owner = module_owner(feats)
    print(f"фич выбрано: {len(on)}   модулей в билде: "
          f"{sum(1 for f in owner.values() if f in on)}\n")

    problems = 0

    print("1. Жёсткие ссылки на выключенные фичи")
    refs = hard_refs(owner, on)
    if refs:
        problems += len(refs)
        for rel, line, name, dep in refs:
            print(f"   anamorf/{rel}:{line}  зовёт {name} (фича «{dep}»)")
        print("   → заверни импорт в функцию и в features.on(\"фича\")")
    else:
        print("   нет — выключенное никто не тянет при старте")

    print("\n2. Модули вне реестра")
    orphans = [p.relative_to(PKG).as_posix() for p in PKG.rglob("*.py")
               if "__pycache__" not in p.parts
               and p.relative_to(PKG).as_posix() not in owner
               and not p.name == "__init__.py"]
    if orphans:
        problems += len(orphans)
        for o in orphans:
            print(f"   {o}")
    else:
        print("   нет — каждый модуль знает свою фичу")

    print("\n3. Личное автора в пакете")
    found = []
    for rel, fid in owner.items():
        if fid not in on:
            continue
        p = PKG / rel
        try:
            src = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for needle, why in PRIVATE:
            if needle in src:
                found.append((rel, needle, why))
    if found:
        problems += len(found)
        for rel, needle, why in found:
            print(f"   anamorf/{rel}: {needle}  — {why}")
    else:
        print("   нет — следов машины автора не найдено")

    print("\n4. Синтаксис выбранного")
    import py_compile
    bad = []
    for rel, fid in owner.items():
        if fid not in on:
            continue
        try:
            py_compile.compile(str(PKG / rel), doraise=True)
        except Exception as e:
            bad.append((rel, str(e)[:70]))
    if bad:
        problems += len(bad)
        for rel, e in bad:
            print(f"   {rel}: {e}")
    else:
        print("   чисто")

    torch = any(feats[f].get("torch") for f in on)
    mb = 520 + (2900 if torch else 0) + sum(feats[f].get("mb", 0) for f in on
                                            if not feats[f].get("pack"))
    packs = [f for f in on if feats[f].get("pack")]
    print(f"\nустановщик ~{mb/1000:.1f} ГБ" + (" (с torch)" if torch else ""))
    if packs:
        print(f"докачкой: {', '.join(sorted(packs))}")

    print("\n" + ("ПРОВЕРКА НЕ ПРОЙДЕНА: " + str(problems) + " — собирать рано"
                  if problems else "ПРОВЕРКА ПРОЙДЕНА — можно собирать"))
    return problems


def assemble(feats: dict, on: set[str], version: str) -> Path:
    owner = module_owner(feats)
    out = OUT_ROOT / f"ANAMORF-{version}"
    shutil.rmtree(out, ignore_errors=True)
    app = out / "app"
    (app / "anamorf").mkdir(parents=True, exist_ok=True)

    n = 0
    for rel, fid in sorted(owner.items()):
        if fid not in on:
            continue
        src, dst = PKG / rel, app / "anamorf" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
    # __init__ пакетов нужны всегда, иначе импорт не найдёт подпакет
    for p in PKG.rglob("__init__.py"):
        rel = p.relative_to(PKG)
        d = app / "anamorf" / rel
        if not d.exists() and (app / "anamorf" / rel.parent).is_dir():
            shutil.copy2(p, d)
            n += 1

    shutil.copytree(ROOT / "ui", app / "ui", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    for f in ("features.json", "packs.json", "config.default.json", "VERSION"):
        if (ROOT / f).exists():
            shutil.copy2(ROOT / f, app / f)

    (app / "build.json").write_text(json.dumps({
        "version": version,
        "channel": "stable",
        "tier": "pro" if any(feats[f].get("tier") == "pro" for f in on) else "free",
        "features": sorted(on),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\nсобрано: {out}")
    print(f"   файлов кода: {n}")
    print("   ui/ скопирован, build.json записан")
    print("\nЧего ещё нет: runtime\\ с интерпретатором и ANAMORF.exe — "
          "это следующий шаг.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=list(PROFILES), default=None)
    ap.add_argument("--features", default=None)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--version", default=None)
    a = ap.parse_args()

    version = a.version or (ROOT / "VERSION").read_text().strip()
    feats = registry()
    on = pick(feats, a.profile, a.features)

    print("=" * 66)
    print(f"СБОРКА КЛИЕНТА ANAMORF {version}   профиль: "
          f"{a.features or a.profile or 'base'}")
    print("=" * 66 + "\n")

    problems = check(feats, on)
    if not a.apply:
        if not a.check:
            print("\n(это была только проверка — собрать: --apply)")
        return 1 if problems else 0
    if problems:
        print("\nНе собираю: сначала поправь найденное.")
        return 1
    assemble(feats, on, version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
