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
        # Верхний уровень — ошибка сборки: такой импорт исполнится при
        # запуске. Импорт внутри функции — предупреждение: он законен,
        # если стоит под features.on(), и смертелен, если нет. Отличить
        # автоматически нельзя, поэтому показываем и даём решить.
        deep = [n for n in ast.walk(tree)
                if isinstance(n, (ast.Import, ast.ImportFrom))
                and n not in tree.body]
        for node in list(tree.body) + deep:
            names = []
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("anamorf"):
                tail = (node.module or "")[len("anamorf"):].lstrip(".")
                # `from anamorf.earlog import EARLOG` — здесь модуль это
                # earlog, а EARLOG внутри него объект. Проверять надо ОБА
                # варианта: и сам путь, и путь с добавленным именем (случай
                # `from anamorf.stt import manager`). Раньше проверялся
                # только второй — и жёсткий импорт лаборатории в main.py
                # спокойно прошёл проверку и упал уже в собранном билде.
                if tail:
                    names.append(tail)
                names += [f"{tail}/{a.name}" if tail else a.name
                          for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name[len("anamorf."):] for a in node.names
                         if a.name.startswith("anamorf.")]
            for n in names:
                cand = (n.replace(".", "/") + ".py",
                        n.replace(".", "/") + "/__init__.py")
                dep = next((owner[c] for c in cand if c in owner), None)
                if dep and dep not in on:
                    out.append((rel, node.lineno, n, dep,
                                node in tree.body))
    return out


def check(feats: dict, on: set[str]) -> int:
    owner = module_owner(feats)
    print(f"фич выбрано: {len(on)}   модулей в билде: "
          f"{sum(1 for f in owner.values() if f in on)}\n")

    problems = 0

    print("1. Жёсткие ссылки на выключенные фичи")
    refs = hard_refs(owner, on)
    top = [r for r in refs if r[4]]
    deep = [r for r in refs if not r[4]]
    if top:
        problems += len(top)
        for rel, line, name, dep, _ in top:
            print(f"   anamorf/{rel}:{line}  зовёт {name} (фича «{dep}») "
                  f"— НА ВЕРХНЕМ УРОВНЕ")
        print("   → заверни импорт в функцию и в features.on(\"фича\")")
    else:
        print("   нет — выключенное никто не тянет при старте")
    if deep:
        print("   отложенные импорты выключенного (проверь, что под "
              "features.on):")
        for rel, line, name, dep, _ in deep:
            print(f"     anamorf/{rel}:{line}  {name} (фича «{dep}»)")

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


def busy(out: Path) -> list[str]:
    """Кто держит файлы билда.

    Запущенный билд держит открытыми свои DLL, и копирование поверх падает
    на середине — часть кода уже новая, часть ещё старая. Хуже того,
    падает оно не на первом файле, а на сто первом, когда полсборки уже
    перезаписано.

    Проверка простая: загруженную на исполнение DLL Windows не отдаёт на
    запись. Пробуем открыть — получили отказ, значит билд работает. Ни
    списка процессов, ни прав администратора для этого не нужно.
    """
    locked = []
    for pat in ("ANAMORF.exe", "_launcher/*.dll",
                "app/third_party/**/*.dll", "app/third_party/**/*.exe"):
        for f in out.glob(pat):
            try:
                with open(f, "r+b"):
                    pass
            except PermissionError:
                locked.append(str(f.relative_to(out)))
            except OSError:
                pass
    return locked


def who(out: Path) -> list[tuple]:
    """Процессы, запущенные из папки билда. Без psutil молча возвращаем
    пусто: подсказка приятная, но не настолько, чтобы делать её условием
    сборки."""
    try:
        import psutil
    except Exception:
        return []
    root = str(out).lower()
    found = []
    for pr in psutil.process_iter(["pid", "name", "exe"]):
        try:
            exe = (pr.info.get("exe") or "").lower()
            if exe.startswith(root):
                found.append((pr.info["pid"], pr.info["name"], pr.info["exe"]))
        except Exception:
            pass
    return found


def assemble(feats: dict, on: set[str], version: str) -> Path:
    owner = module_owner(feats)
    out = OUT_ROOT / f"ANAMORF-{version}"
    app = out / "app"

    if out.exists():
        lk = busy(out)
        if lk:
            print("\nБИЛД ЗАПУЩЕН — собирать поверх нельзя.")
            print("   Держит: " + ", ".join(lk[:4]) +
                  (f" и ещё {len(lk) - 4}" if len(lk) > 4 else ""))
            # Назвать процесс важнее, чем перечислить файлы. Закрыть окно —
            # не то же самое, что остановить приложение: сервер живёт
            # отдельным python.exe, а llama-server и вовсе своим exe, и оба
            # переживают закрытие окна. Человеку нужно имя и PID, иначе он
            # будет уверен, что всё выключил, и окажется прав по-своему.
            names = who(out)
            if names:
                print("   Живы процессы:")
                for pid, nm, path in names:
                    print(f"      {nm}  pid {pid}   {path}")
                print("   Снять всё разом:")
                print("      Get-Process | Where-Object { $_.Path -like "
                      f"'{out}\\*' " + "} | Stop-Process -Force")
            else:
                print("   Закрой ANAMORF.exe и повтори команду.")
            raise SystemExit(2)
        # Сносим ТОЛЬКО app\. data\, models\ и config.json переживают
        # пересборку — ровно по тому же правилу, по которому их не трогает
        # обновление. Раньше здесь сносилась вся папка, и каждая сборка
        # молча стирала настройки и профили голоса вместе с кодом.
        shutil.rmtree(app, ignore_errors=True)

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

    # РЕСУРСЫ ФИЧ. Кода мало — без модели аватара он рисует облачко вместо
    # персонажа, а без бинаря движка чип модели остаётся пустым. Раньше в
    # билд ехали только .py и ui/, и это было видно с первого запуска.
    for fid in sorted(on):
        for rel in feats[fid].get("assets", []):
            src = ROOT / rel.rstrip("/")
            if not src.exists():
                print(f"   ! нет ресурса {rel} (фича «{fid}»)")
                continue
            dst = app / rel.rstrip("/")
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns(
                                    "__pycache__", "*.pyc", ".git"))
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            size = sum(f.stat().st_size for f in dst.rglob("*")
                       if f.is_file()) if dst.is_dir() else dst.stat().st_size
            print(f"   ресурс {rel} — {size / 1e6:.0f} МБ")
    for f in ("features.json", "packs.json", "config.default.json", "VERSION"):
        if (ROOT / f).exists():
            shutil.copy2(ROOT / f, app / f)

    (app / "build.json").write_text(json.dumps({
        "version": version,
        "channel": "stable",
        "tier": "pro" if any(feats[f].get("tier") == "pro" for f in on) else "free",
        "features": sorted(on),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Готовый runtime кладём рядом, если он уже собран: build_client
    # отвечает за код, make_runtime — за интерпретатор, и смешивать эти две
    # долгие операции в одну кнопку неудобно.
    rt = OUT_ROOT / "runtime"
    if rt.is_dir():
        shutil.copytree(rt, out / "runtime", dirs_exist_ok=True)
        print("   runtime\\ скопирован")
    # Лаунчер собран onedir: рядом с ANAMORF.exe лежит _launcher\\ с его
    # библиотеками. Копировать надо оба, иначе exe не стартует. Старая
    # onefile-раскладка (просто build\\ANAMORF.exe) тоже поддержана — чтобы
    # уже собранный билд не сломался от смены спеки.
    ldir = OUT_ROOT / "_launcher_build"
    if not (ldir / "ANAMORF.exe").exists():
        ldir = OUT_ROOT / "ANAMORF"          # раскладка прошлой сборки
    exe = ldir / "ANAMORF.exe"
    if not exe.exists():
        exe = OUT_ROOT / "ANAMORF.exe"
        ldir = None
    if exe.exists():
        shutil.copy2(exe, out / "ANAMORF.exe")
        if ldir and (ldir / "_launcher").is_dir():
            shutil.copytree(ldir / "_launcher", out / "_launcher", dirs_exist_ok=True)
            print("   ANAMORF.exe + _launcher\\ скопированы")
        else:
            print("   ANAMORF.exe скопирован")

    for d in ("models", "data"):
        (out / d).mkdir(exist_ok=True)

    (out / "ЧИТАТЬ.txt").write_text(
        "ANAMORF " + version + "\n\n"
        "Запуск — ANAMORF.exe.\n\n"
        "Что где лежит:\n"
        "  app\\       код. Обновления меняют только его.\n"
        "  runtime\\   интерпретатор и библиотеки.\n"
        "  models\\    модели. Обновление их не трогает.\n"
        "  data\\      память, настройки, профили голоса. Тоже не трогает.\n\n"
        "Если что-то пошло не так — data\\logs\\launcher.log.\n",
        encoding="utf-8")

    print(f"\nсобрано: {out}")
    print(f"   файлов кода: {n}")
    missing = [x for x, ok in (("runtime\\", rt.is_dir()),
                               ("ANAMORF.exe", exe.exists())) if not ok]
    if missing:
        print("\nЧего не хватает до запускаемого билда: " + ", ".join(missing))
        print("   runtime:  python tools\\make_runtime.py --profile base --apply")
        print("   лаунчер:  pyinstaller launcher\\ANAMORF.spec "
              "--distpath build --workpath build\\_pyi")
    else:
        print("\nБилд запускаемый. Проверь его на чистой машине без Python.")
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
