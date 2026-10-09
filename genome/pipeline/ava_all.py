# -*- coding: utf-8 -*-
"""Добыть картинки сразу всем собранным персонажам, по одному вызову.

Отдельные задания на каждого — это пять запусков питона и пять минут ожидания
на пустом месте. Здесь один проход, и по каждому видно, что получилось.
"""
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import ava_fetch

СПИСОК = [
    ("research_41d9477f6f48", "Karen AI suit interface Spider-Man Homecoming", "Карен"),
    ("research_22598d8014ba", "Peter Parker Spider-Man Homecoming portrait face", "Питер Паркер"),
    ("research_5688914232d0", "JARVIS Iron Man AI interface Marvel", "Джарвис"),
    ("research_7f9597669315", "Elsa Frozen Disney portrait face", "Эльза"),
    ("research_c44b711a1e1a", "Toothless Night Fury dragon How to Train Your Dragon face", "Беззубик"),
]

вышло, мимо = 0, []
for ид, запрос, имя in СПИСОК:
    print("\n=== " + имя)
    try:
        ava_fetch.вшить(ид, запрос, имя)
        вышло += 1
    except SystemExit as e:
        print("не получилось:", str(e)[:200]); мимо.append(имя)
    except Exception as e:
        print("сбой:", repr(e)[:200]); мимо.append(имя)

print(f"\nитог: вшито {вышло} из {len(СПИСОК)}" + ("; без картинки: " + ", ".join(мимо) if мимо else ""))
