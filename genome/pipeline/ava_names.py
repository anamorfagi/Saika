# -*- coding: utf-8 -*-
"""
[БЛОК ЛИЦА] Подобрать картинкам с человеческими именами их персонажей.

Карточка ищет лицо строго по ava/<id>.<расширение>. Файлы вроде «эм.png» или
«Kurumi Tokisaki ( 時崎狂三 ).jpg» она не найдёт никогда. Здесь — осторожное
сопоставление: файл отдаётся персонажу, только если его имя однозначно указывает
на него. Ничего не удаляется: исходный файл остаётся на месте, рядом появляется копия
под правильным именем. Неопознанные просто перечисляются — решать по ним человеку.

Запуск: python pipeline/ava_names.py
"""
import json
import pathlib
import re
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHARE, AVA = ROOT / "share", ROOT / "ava"
ХОРОШЕЕ = re.compile(r"[a-z0-9_]+\.(jpg|jpeg|png|webp|gif)$")


def имена_персонажей():
    """id → набор слов, по которым персонажа можно узнать (имя, псевдоним, id)."""
    из_файлов = {}
    for f in sorted(SHARE.glob("*.genome.json")):
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        ident = str(c.get("id") or "").strip()
        if not ident:
            continue
        meta = c.get("meta") or {}
        слова = {ident.lower()}
        for ключ in ("name", "alias"):
            for кусок in re.split(r"[\s·,«»\"']+", str(meta.get(ключ) or "")):
                if len(кусок) >= 3:
                    слова.add(кусок.lower())
        есть = any((AVA / (ident + "." + e)).exists() for e in ("jpg", "png", "webp", "gif"))
        из_файлов[ident] = (слова, есть)
    return из_файлов


def main():
    if not AVA.exists():
        print("папки ava нет"); return
    карта = имена_персонажей()
    взято, нерешённые = 0, []
    for p in sorted(AVA.iterdir()):
        if not p.is_file() or ХОРОШЕЕ.fullmatch(p.name):
            continue
        основа = p.stem.lower()
        совпали = [i for i, (слова, есть) in карта.items()
                   if not есть and any(с in основа or основа in с for с in слова)]
        if len(совпали) == 1:
            цель = AVA / (совпали[0] + p.suffix.lower())
            shutil.copyfile(p, цель)
            карта[совпали[0]] = (карта[совпали[0]][0], True)
            взято += 1
            print("%-34s -> %s" % (p.name, цель.name))
        else:
            нерешённые.append((p.name, [i for i in совпали]))
    print("\nразобрано: %d" % взято)
    for имя, варианты in нерешённые:
        print("не понял чьё: %-30s %s" % (имя, ("подходят: " + ", ".join(варианты)) if варианты else "совпадений нет"))
    без = [i for i, (_, есть) in карта.items() if not есть]
    if без:
        print("остались без лица: " + ", ".join(без))


if __name__ == "__main__":
    main()
