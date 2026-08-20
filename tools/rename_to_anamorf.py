"""Переименование пакета anamorf/ в anamorf/ — одним заходом.

Система называется ANAMORF, Сайка — имя персоны внутри неё. Пакет должен
называться так же, как продукт: иначе через полгода никто не вспомнит, что
`server` — это не «сервер», а вся система целиком.

Делать это надо СЕЙЧАС, до распила main.py на подсистемы. После распила
переименовывать придётся вдвое больше файлов, и половина из них будет
свежей — то есть непроверенной.

По умолчанию скрипт НИЧЕГО не меняет: показывает каждую правку с номером
строки и куском текста. Применяет только с --apply.

    python tools\\rename_to_anamorf.py            # посмотреть, что будет
    python tools\\rename_to_anamorf.py --apply    # сделать

Что НЕ трогаем осознанно:

  * ключи настроек server.host / server.port / server.token — это раздел
    конфига, а не имя пакета. Переименование потребовало бы миграции файлов
    у всех, кто уже работает, ради нуля пользы;
  * адреса /api/... — внутренний разговор сервера с собственным интерфейсом.
    Сломать его переименованием легко, выиграть нечего;
  * слово server там, где оно английское: llama-server, Local Server,
    ollama serve, server.py сторонних библиотек.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPLY = "--apply" in sys.argv

# Где ищем. Всё остальное (.venv, models, third_party, .git) не трогаем.
SCAN_DIRS = ["server", "workers", "setup", "tools", "tests", "ui", "docs",
             "training", "workshop", "HandsPC"]
SCAN_ROOT_FILES = ["start.bat", "fix_venv.bat", "finish_day.bat",
                   "stop_avatar.bat", "AGENTS.md", "ARCHITECTURE.md",
                   "CLAUDE.md", "CONFIG.md", "README.md", "RULES.md",
                   "ROADMAP.md", "WORKFLOW.md", "PLAN_BUILD.md",
                   "PHILOSOPHY.md", ".gitignore", "requirements.txt"]
SUFFIXES = {".py", ".bat", ".cmd", ".md", ".html", ".json", ".txt", ".ps1"}

# Строки с этими кусками пропускаем целиком: там server — не наш пакет.
SKIP_LINE = (
    '"server.host"', "'server.host'", '"server.port"', "'server.port'",
    '"server.token"', "'server.token'", '"server.https"', "'server.https'",
    'CFG.get("server', "CFG.get('server", 'CFG.set("server', "CFG.set('server",
    "llama-server", "llama_server", "Local Server", "ollama serve",
    "getattr(server", "http.server", "socketserver", "uvicorn.run",
)

# Каждая замена — с объяснением, что именно она ловит.
RULES = [
    (re.compile(r"\bfrom server import\b"),      "from anamorf import",
     "from anamorf import X"),
    (re.compile(r"\bfrom anamorf\."),             "from anamorf.",
     "from anamorf.X import Y"),
    (re.compile(r"\bimport anamorf\.(\w)"),       r"import anamorf.\1",
     "import anamorf.X"),
    (re.compile(r"\bimport anamorf\b(?!\.)"),     "import anamorf",
     "import anamorf"),
    (re.compile(r"\bserver\.main\b"),            "anamorf.main",
     "python -m anamorf.main"),
    (re.compile(r"(?<![\w./\\-])anamorf/"),       "anamorf/",
     "путь anamorf/..."),
    (re.compile(r"(?<![\w./-])anamorf\\\\"),      r"anamorf\\\\",
     "путь anamorf\\... в строке Python"),
    (re.compile(r"(?<![\w./-])anamorf\\(?![\\])"), r"anamorf\\",
     "путь anamorf\\... в bat"),
    (re.compile(r'ROOT / "anamorf"'),             'ROOT / "anamorf"',
     'ROOT / "anamorf"'),
]


def files_to_scan():
    for name in SCAN_ROOT_FILES:
        p = ROOT / name
        if p.exists():
            yield p
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.suffix.lower() in SUFFIXES:
                if "__pycache__" in p.parts or ".venv" in p.parts:
                    continue
                yield p


def process(path: Path):
    """Вернуть (новый текст, список правок) или (None, []) если менять нечего."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None, []

    out, edits = [], []
    for n, line in enumerate(text.split("\n"), 1):
        if any(s in line for s in SKIP_LINE):
            out.append(line)
            continue
        new = line
        hits = []
        for rx, repl, why in RULES:
            if rx.search(new):
                new = rx.sub(repl, new)
                hits.append(why)
        if new != line:
            edits.append((n, line.strip()[:96], new.strip()[:96], hits[0]))
        out.append(new)
    return ("\n".join(out), edits) if edits else (None, [])


def main():
    print("=" * 72)
    print("ПЕРЕИМЕНОВАНИЕ anamorf/ → anamorf/   " +
          ("(ПРИМЕНЯЮ)" if APPLY else "(только показываю, ничего не меняю)"))
    print("=" * 72)

    if APPLY:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                           capture_output=True, text=True)
        if r.stdout.strip():
            print("\nВ репозитории есть незакоммиченные правки:\n")
            print(r.stdout)
            print("Сначала закоммить их — иначе, если что-то пойдёт не так,")
            print("нечем будет откатиться (git checkout . вернёт всё разом).")
            return 1

    planned, total = [], 0
    for path in files_to_scan():
        new, edits = process(path)
        if edits:
            planned.append((path, new, edits))
            total += len(edits)

    for path, _new, edits in planned:
        rel = path.relative_to(ROOT)
        print(f"\n── {rel}  ({len(edits)})")
        for n, was, now, why in edits[:6]:
            print(f"   {n:>5}  {why}")
            print(f"          - {was}")
            print(f"          + {now}")
        if len(edits) > 6:
            print(f"          … и ещё {len(edits) - 6}")

    print("\n" + "=" * 72)
    print(f"файлов: {len(planned)}   правок: {total}")

    if not APPLY:
        print("\nНичего не изменено. Посмотри список выше — если он выглядит")
        print("правильно, запусти ещё раз с --apply.")
        return 0

    print("\n1. Переношу папку через git mv (история файлов сохранится)…")
    r = subprocess.run(["git", "mv", "server", "anamorf"], cwd=ROOT,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("   git mv не смог:", r.stderr.strip())
        print("   Ничего не изменено.")
        return 1
    print("   anamorf/ → anamorf/")

    print("2. Правлю тексты…")
    for path, new, edits in planned:
        # файлы бывшего anamorf/ уже переехали — берём их по новому пути
        target = path
        if not target.exists():
            rel = path.relative_to(ROOT)
            if rel.parts and rel.parts[0] == "server":
                target = ROOT / "anamorf" / Path(*rel.parts[1:])
        if not target.exists():
            print(f"   ! пропал из виду: {path.relative_to(ROOT)}")
            continue
        target.write_text(new, encoding="utf-8")
    print(f"   поправлено файлов: {len(planned)}")

    print("3. Проверяю синтаксис…")
    import py_compile
    bad = []
    for p in sorted((ROOT / "anamorf").rglob("*.py")):
        try:
            py_compile.compile(str(p), doraise=True)
        except Exception as e:
            bad.append((p.name, str(e)[:80]))
    print("   ошибок синтаксиса:", bad or "нет")

    print("4. Ищу забытые упоминания…")
    left = (subprocess.run(
        ["git", "grep", "-n", r"\(from\|import\) anamorf\b"], cwd=ROOT,
        capture_output=True, text=True,
        encoding="utf-8", errors="replace").stdout or "").strip()
    print("   " + (left or "не осталось"))

    print("\nГотово. Дальше:")
    print("  1. Запусти Сайку и поговори с ней — это единственная настоящая проверка.")
    print("  2. Если всё живо: git add -A && git commit -m \"server -> anamorf\"")
    print("  3. Если сломалось: git checkout . && git reset  — вернёт как было.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
