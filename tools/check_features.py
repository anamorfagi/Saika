"""Сверка кода с реестром фич — сухая проверка перед сборкой.

Отвечает на три вопроса, на которые до сих пор никто не отвечал:

  1. Есть ли модули, не приписанные ни к одной фиче? Такой модуль не попадёт
     ни в один билд, и никто этого не заметит. Ровно так два месяца прожил
     network.py: он числился живым в карте модулей, а ссылок на него не было
     ни одной.
  2. Есть ли в реестре файлы, которых больше нет на диске? Значит, реестр
     врёт, и сборка положит в билд пустоту.
  3. Есть ли модули, на которые никто не ссылается? Кандидаты в мёртвые.

    python tools\\check_features.py

Код возврата 1, если нашлось что-то из первых двух пунктов — чтобы этим
можно было останавливать сборку.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "anamorf"


def registry() -> dict:
    d = json.loads((ROOT / "features.json").read_text(encoding="utf-8"))
    return {f["id"]: f for g in d["groups"] for f in g["features"]}


def owner_of(rel: str, feats: dict) -> str | None:
    for fid, f in feats.items():
        for m in f.get("mods", []):
            if m.endswith("/") and rel.startswith(m):
                return fid
            if m == rel:
                return fid
    return None


def main() -> int:
    feats = registry()
    files = sorted(p.relative_to(PKG).as_posix()
                   for p in PKG.rglob("*.py")
                   if "__pycache__" not in p.parts)

    print(f"модулей на диске: {len(files)}   фич в реестре: {len(feats)}\n")

    # 1. сироты
    orphans = [f for f in files
               if owner_of(f, feats) is None and not f.endswith("__init__.py")
]
    if orphans:
        print("НЕ ПРИПИСАНЫ НИ К ОДНОЙ ФИЧЕ:")
        for f in orphans:
            print(f"   {f}")
        print("   → допиши их в features.json, иначе они не попадут в билд\n")
    else:
        print("сирот нет: каждый модуль знает свою фичу\n")

    # 2. реестр указывает в пустоту
    ghosts = []
    for fid, f in feats.items():
        for m in f.get("mods", []):
            p = PKG / m
            if m.endswith("/"):
                if not p.is_dir():
                    ghosts.append((fid, m))
            elif not p.exists():
                ghosts.append((fid, m))
    if ghosts:
        print("В РЕЕСТРЕ ЕСТЬ, НА ДИСКЕ НЕТ:")
        for fid, m in ghosts:
            print(f"   {fid}: {m}")
        print()
    else:
        print("реестр не врёт: все перечисленные файлы на месте\n")

    # 3. кто на кого ссылается
    imported: set[str] = set()
    rx = re.compile(r"(?:from|import)\s+anamorf\.?([\w.]*)")
    for p in PKG.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in rx.finditer(src):
            if m.group(1):
                imported.add(m.group(1).split(".")[0])
        # from anamorf import a, b, c
        for m in re.finditer(r"from anamorf import ([^\n#]+)", src):
            for name in m.group(1).split(","):
                imported.add(name.strip().split(" ")[0])

    lonely = []
    for f in files:
        if f.endswith("__init__.py") or "/" in f:
            continue
        name = f[:-3]
        if name in ("main", "features"):
            continue
        if name not in imported:
            lonely.append((name, owner_of(f, feats)))
    if lonely:
        print("НА НИХ НИКТО НЕ ССЫЛАЕТСЯ (кандидаты в мёртвые):")
        for name, fid in lonely:
            print(f"   {name}.py   (фича: {fid})")
        print("   → проверь грепом, прежде чем удалять: модуль может звать\n"
              "     сам себя из main.py строкой или подключаться динамически\n")
    else:
        print("на каждый модуль кто-то ссылается\n")

    bad = bool(orphans or ghosts)
    print("ИТОГ:", "есть что поправить" if bad else "сборку можно запускать")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
