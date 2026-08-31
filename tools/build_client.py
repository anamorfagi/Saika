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
WITH_SECRETS = False   # --with-secrets: класть личные ключи в сборку

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
        # 2026-08-26: пока Сайка запущена, часть файлов build\runtime занята
        # её же процессом, и copytree ронял сборку ровно посередине — exe,
        # голос и секреты не доезжали. Занятый файл теперь пропускается со
        # счётом, совпадающий по размеру и времени — не копируется заново:
        # пересборка при живом приложении возможна и быстра.
        skipped = [0]

        def _rt_copy(src, dst):
            try:
                if os.path.exists(dst):
                    a, b = os.stat(src), os.stat(dst)
                    if a.st_size == b.st_size and int(a.st_mtime) == int(b.st_mtime):
                        return dst
                return shutil.copy2(src, dst)
            except (PermissionError, OSError):
                skipped[0] += 1
                return dst

        import os
        try:
            shutil.copytree(rt, out / "runtime", dirs_exist_ok=True,
                            copy_function=_rt_copy)
        except shutil.Error as e:
            # copytree копит ошибки copystat на занятых КАТАЛОГАХ и бросает
            # их пачкой в конце, когда файлы уже скопированы. Метаданные
            # каталога — не повод ронять сборку.
            skipped[0] += len(e.args[0]) if e.args else 1
        print("   runtime\\ скопирован" +
              (f" (пропущено занятого: {skipped[0]})" if skipped[0] else ""))
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

    dress(out, app)

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


def dress(out: Path, app: Path) -> None:
    """ЧЕТЫРЕ ДЫРЫ РЕЦЕПТА (2026-08-22). Свежая сборка приезжала формально
    целой, а по факту немой и слепой — и каждый раз это чинили руками уже
    в собранной папке. Руками чинится один билд; чинить надо рецепт.

    1. ОБРАЗЕЦ ГОЛОСА. Клон-голос без `voice/ref.wav` не заводится вовсе —
       движок падает с «нет референса голоса». Файл не код и в app\\ не
       едет: его место рядом, в DATA_ROOT, который переживает обновление.
    2. ТЕКСТ ОБРАЗЦА. Мало положить wav: Qwen3-TTS клонирует по ПАРЕ
       «звук + расшифровка». В config.default.json поле стояло пустым, и
       билд ронял клон ровно тем же «нет референса», имея файл на диске.
    3. ПОТОКОВЫЙ QWEN_TTS. В pypi лежит ванильный 0.0.4 без
       `stream_generate_voice_clone` — с ним голос падает «с незнакомой
       ошибкой». Рабочий форк лежит в third_party и обязан подменять пакет
       в runtime при каждой сборке, а не однажды вручную.
    4. МОДЕЛЬ АВАТАРА. Без .vrm окно образа честно пишет «нет файла
       модели»: код есть, персонажа нет.

    Ничего не перезаписываем поверх пользовательского: у человека в этой
    папке могут лежать свои голос и аватар, и сборка кода не имеет права
    их трогать.
    """
    import json as _j

    # 1. образец голоса
    vsrc = ROOT / "voice"
    if vsrc.is_dir():
        (out / "voice").mkdir(exist_ok=True)
        for f in ("ref.wav", "ref.mp3"):
            src, dst = vsrc / f, out / "voice" / f
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)
                print(f"   голос: образец {f} положен в voice\\")
    else:
        print("   ! нет voice\\ref.wav — клон-голос в билде не заведётся")

    # 2. текст образца в настройки по умолчанию
    dflt = app / "config.default.json"
    if dflt.exists():
        try:
            d = _j.loads(dflt.read_text(encoding="utf-8"))
            live = _j.loads((ROOT / "config.json").read_text(encoding="utf-8"))
            txt = ((live.get("tts") or {}).get("voice_ref_text") or "").strip()
            if txt and not ((d.get("tts") or {}).get("voice_ref_text") or ""):
                d.setdefault("tts", {})["voice_ref_text"] = txt
                dflt.write_text(_j.dumps(d, ensure_ascii=False, indent=1),
                                encoding="utf-8")
                print(f"   голос: расшифровка образца ({len(txt)} симв.) "
                      "вписана в config.default.json")
            elif not txt:
                print("   ! нет tts.voice_ref_text — клон-голос упадёт "
                      "«нет референса», даже имея wav")
        except Exception as e:
            print(f"   ! настройки по умолчанию не поправлены: {e}")

    # 3. потоковый форк qwen_tts в runtime
    fork = ROOT / "third_party" / "Qwen3-TTS-streaming" / "qwen_tts"
    sp = out / "runtime" / "Lib" / "site-packages"
    if fork.is_dir() and sp.is_dir():
        marker = fork / "inference" / "qwen3_tts_model.py"
        ok = marker.exists() and "stream_generate_voice_clone" in \
            marker.read_text(encoding="utf-8", errors="ignore")
        if not ok:
            print("   ! форк qwen_tts без stream_generate_voice_clone — "
                  "не подменяю, иначе станет только хуже")
        else:
            dst = sp / "qwen_tts"
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(fork, dst,
                            ignore=shutil.ignore_patterns("__pycache__"))
            print("   голос: в runtime поставлен потоковый qwen_tts "
                  "(с клоном голоса)")
    elif fork.is_dir():
        print("   (runtime рядом нет — потоковый qwen_tts поставится "
              "при следующей сборке с runtime)")

    # 3б. GigaAM: в pypi лежит 0.1.0, который про модели v3 не знает
    #     вовсе («Model 'v3_e2e_rnnt' not found»), а конфиг просит именно
    #     v3. Ставим свой пакет из third_party и кладём исходники рядом с
    #     кодом: по ним же кнопка «Обновить пакет» лечит это у клиента,
    #     не требуя ни сети, ни пересборки.
    for pkg, rel in (("gigaam", "third_party/GigaAM/gigaam"),
                     ("qwen_tts",
                      "third_party/Qwen3-TTS-streaming/qwen_tts")):
        src = ROOT / rel
        if not src.is_dir():
            print(f"   ! нет {rel} — «{pkg}» в сборке останется тем, что "
                  "приедет из pypi")
            continue
        keep = app / rel
        keep.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, keep, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if sp.is_dir() and pkg == "gigaam":
            dst = sp / pkg
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst,
                            ignore=shutil.ignore_patterns("__pycache__",
                                                          "*.pyc"))
            print("   слух: в runtime поставлен gigaam с моделями v3")

    # 3в. КЛЮЧИ. Живой вечер 22.08: облачная модель отвечала «не задан
    #     API-ключ», хотя ключ у владельца есть — `secrets.json` лежал в
    #     основном проекте и в сборку не ехал вовсе. Кладём рядом со
    #     сборкой (не в app\: его сносит любое обновление) и только если
    #     там ещё нет своего — чужие ключи не перетираем.
    #     ЛИЧНЫЕ КЛЮЧИ В РАЗДАВАЕМУЮ СБОРКУ НЕ ЕДУТ (2026-08-25, аудит
    #     безопасности). Раньше dress() копировал боевой secrets.json автора
    #     в папку релиза «чтобы ключ не вбивать заново». Но эта же папка и
    #     есть то, что автор раздаёт людям, — значит его ключи OpenRouter,
    #     Mistral, GigaChat, токены GitHub и ботов уезжали КАЖДОМУ
    #     получателю. Это утечка, а не удобство.
    #
    #     Теперь по умолчанию рядом со сборкой кладётся пустой ШАБЛОН
    #     (secrets.example.json -> secrets.json), а клиент впишет свои ключи
    #     сам — через интерфейс (см. /api/keys). Свою личную сборку с
    #     ключами автор собирает осознанно: build_client.py --with-secrets.
    dst = out / "secrets.json"
    tmpl = ROOT / "secrets.example.json"
    sec = ROOT / "secrets.json"
    if dst.exists():
        print("   ключи: у сборки уже есть свой secrets.json — не трогаю")
    elif WITH_SECRETS and sec.exists():
        shutil.copy2(sec, dst)
        print("   ключи: ЛИЧНЫЙ secrets.json положен в сборку "
              "(--with-secrets) — эту сборку НЕЛЬЗЯ раздавать")
    elif tmpl.exists():
        shutil.copy2(tmpl, dst)
        print("   ключи: положен пустой шаблон secrets.json — клиент впишет "
              "свои ключи в интерфейсе")
    else:
        print("   ! нет secrets.example.json — клиенту нечем задать ключи")

    # 3г. ЗАГОЛОВКИ PYTHON ДЛЯ TRITON (2026-08-23). Клон-голос ускоряется
    #     только с Triton, а тот собирает свои ядра компилятором tcc: ему
    #     нужны Python.h и python312.lib. В embedded-рантайме нет ни
    #     заголовков, ни pip — и Triton падал с CalledProcessError, ища
    #     `runtime\Include`. Заголовки лежат в third_party/py312_include:
    #     кладём их рядом с интерпретатором, иначе каждая пересборка
    #     снова оставляет голос без ускорения.
    inc_src = ROOT / "third_party" / "py312_include"
    inc_dst = out / "runtime" / "Include"
    if inc_src.is_dir() and (out / "runtime").is_dir():
        shutil.copytree(inc_src, inc_dst, dirs_exist_ok=True)
        print("   голос: заголовки Python положены в runtime\\Include")
    elif (out / "runtime").is_dir() and not inc_dst.is_dir():
        print("   ! нет runtime\\Include — Triton не соберёт ядра, "
              "клон-голос останется медленным")

    # 3д. PIP В RUNTIME (2026-08-23). Встраиваемый питон едет без pip, и
    #     это осознанно: клиенту незачем собирать окружение. Но пока
    #     готовых блоков нет, отсутствие pip означает «нельзя вообще
    #     ничего» — окно с моделью на рабочем столе просило PySide6 и
    #     упиралось в пустоту. Кладём pip как запасной путь.
    pipw = sorted((ROOT / "third_party" / "wheels").glob("pip-*.whl")) \
        if (ROOT / "third_party" / "wheels").is_dir() else []
    if pipw and sp.is_dir() and not (sp / "pip").is_dir():
        import zipfile
        with zipfile.ZipFile(pipw[-1]) as z:
            z.extractall(sp)
        print(f"   runtime: положен {pipw[-1].name}")

    # 3е. ФАЙЛ ОКНА С МОДЕЛЬЮ (2026-08-23). Модуль desk_avatar только
    #     ЗАПУСКАЕТ отдельный процесс, а сам процесс живёт в
    #     tools/desk_avatar.py — и этой папки в сборке не было вовсе.
    #     Кнопка честно ставила PySide6 (150 МБ!), а потом упиралась в
    #     «нет файла окна» и молчала. Кладём файл рядом с кодом.
    # Тем же правилом едет окно ядра (режим исчезновения, 2026-08-23):
    # anamorf/orb.py только запускает процесс, само окно — tools/orb_window.py.
    for _nm in ("desk_avatar.py", "orb_window.py", "orb_qml.py",
                "command_drill.py"):
        da = ROOT / "tools" / _nm
        if da.exists():
            (app / "tools").mkdir(parents=True, exist_ok=True)
            shutil.copy2(da, app / "tools" / da.name)
            print(f"   окна: tools\\{_nm} положен в сборку")
        else:
            print(f"   ВНИМАНИЕ: нет tools\\{_nm} — окно не откроется")

    # 4. модель аватара
    try:
        d = _j.loads((app / "config.default.json").read_text(encoding="utf-8"))
        rel = ((d.get("avatar") or {}).get("web") or {}).get("model", "")
    except Exception:
        rel = ""
    if rel:
        src, dst = ROOT / rel, out / rel
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            print(f"   образ: {src.name} положен в {rel}")
        elif not src.exists():
            print(f"   ! нет модели аватара {rel} — окно образа будет "
                  "показывать «нет файла модели»")

    # 5. СЛУХ ПО УМОЛЧАНИЮ: движок есть, весов нет (не чиним молча, а
    #    называем вслух — качать их всё равно человеку при первом запуске)
    try:
        d = _j.loads((app / "config.default.json").read_text(encoding="utf-8"))
        eng = ((d.get("stt") or {}).get("engine") or "")
    except Exception:
        eng = ""
    weights = {"gigaam": Path.home() / ".cache" / "gigaam",
               "faster_whisper": ROOT / "models" / "hf" / "hub"}
    if eng in weights and not any(weights[eng].glob("*")):
        print(f"   ! слух по умолчанию «{eng}», а весов рядом нет — "
              "в билде он поднимется только после закачки "
              "(кнопка «Починить» в списке движков умеет это сама)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=list(PROFILES), default=None)
    ap.add_argument("--features", default=None)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--version", default=None)
    ap.add_argument("--with-secrets", action="store_true",
                    help="положить в сборку ЛИЧНЫЙ secrets.json автора — "
                         "только для себя, такую сборку раздавать нельзя")
    a = ap.parse_args()
    global WITH_SECRETS
    WITH_SECRETS = bool(a.with_secrets)

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
