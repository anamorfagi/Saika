"""Чинит venv после переноса папки на другой ПК или диск.

Windows-venv хранит в pyvenv.cfg абсолютный путь к базовому Python
(home = C:\\...\\Python312). На другом ПК путь другой — venv не стартует,
хотя все пакеты в нём целы. Правим пути на актуальные и venv оживает
без переустановки ~10 ГБ зависимостей.

Запускается СИСТЕМНЫМ Python 3.12 из start.bat до первого обращения к venv.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fix(venv: Path):
    cfg = venv / "pyvenv.cfg"
    if not cfg.exists():
        return
    home = str(Path(sys.executable).parent)
    text = cfg.read_text(encoding="utf-8")
    # замены через lambda: в путях Windows есть \U, \t и т.п. — строковая
    # замена re.sub трактует их как escape-последовательности и падает
    new = re.sub(r"(?m)^home *=.*$", lambda m: "home = " + home, text)
    new = re.sub(r"(?m)^executable *=.*$",
                 lambda m: "executable = " + sys.executable, new)
    new = re.sub(r"(?m)^command *=.*$",
                 lambda m: f"command = {sys.executable} -m venv {venv}", new)
    if new != text:
        cfg.write_text(new, encoding="utf-8")
        print(f"[fix] {venv.name}: путь к Python обновлён -> {home}")


if __name__ == "__main__":
    for name in (".venv", ".venv_voxtral"):
        fix(ROOT / name)
