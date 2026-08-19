"""Прогон всех проверок. Без pytest — чтобы работало на любой машине.

    python tests/run.py            все
    python tests/run.py phrases    только tests/test_phrases.py
"""
import importlib
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

GREEN, RED, DIM, OFF = "\033[32m", "\033[31m", "\033[90m", "\033[0m"
if os.name == "nt" and not os.environ.get("WT_SESSION"):
    GREEN = RED = DIM = OFF = ""


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    names = sorted(f[:-3] for f in os.listdir(HERE)
                   if f.startswith("test_") and f.endswith(".py"))
    if only:
        names = [n for n in names if only in n]
    total = bad = skipped = 0
    for name in names:
        try:
            mod = importlib.import_module("tests." + name)
            rows = mod.run()
        except Exception:
            print(f"{RED}!! {name}: упал сам тест{OFF}")
            traceback.print_exc()
            bad += 1
            continue
        print(f"\n{name.replace('test_', '')}:")
        for title, ok, note in rows:
            total += 1
            if ok is None:
                skipped += 1
                print(f"  {DIM}~~ {title} — пропущено: {note}{OFF}")
            elif ok:
                print(f"  {GREEN}ok{OFF} {title}" + (f" {DIM}({note}){OFF}" if note else ""))
            else:
                bad += 1
                print(f"  {RED}!! {title} — {note}{OFF}")
    print(f"\nвсего проверок {total}, провалов {bad}, пропущено {skipped}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
