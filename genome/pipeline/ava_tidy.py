# -*- coding: utf-8 -*-
"""
[БЛОК ЛИЦА] Навести порядок в папке ava.

Карточка ищет лицо строго по ava/<id>.<расширение>. Всё остальное — «эм.png»,
«Kurumi Tokisaki ( 時崎狂三 ).jpg», случайные хэши — она не найдёт никогда, но эти
файлы засоряют папку и путают: кажется, что лицо есть, а карточка пустая.

Скрипт НИЧЕГО НЕ УДАЛЯЕТ. Посторонние имена уезжают в ava/_исходники/, откуда их
всегда можно достать. Лица под правильными именами не трогаются.

Запуск: python pipeline/ava_tidy.py
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
СКЛАД = AVA / "_исходники"
КАРТИНКА = re.compile(r"\.(jpe?g|png|webp|gif)$", re.I)


def известные():
    out = set()
    for f in SHARE.glob("*.genome.json"):
        try:
            out.add(str(json.loads(f.read_text(encoding="utf-8")).get("id") or "").lower())
        except Exception:
            pass
    out.discard("")
    return out


def main():
    if not AVA.exists():
        print("папки ava нет"); return
    ids = известные()
    убрано, оставлено, лишние_копии = 0, [], []
    for p in sorted(AVA.iterdir()):
        if not p.is_file() or not КАРТИНКА.search(p.name):
            continue
        имя = p.stem.lower()
        if имя in ids:
            оставлено.append(p.name)
            continue
        # лицо под чужим именем: может быть копией того, что уже лежит правильно
        СКЛАД.mkdir(exist_ok=True)
        цель = СКЛАД / p.name
        n = 1
        while цель.exists():
            цель = СКЛАД / ("%s (%d)%s" % (p.stem, n, p.suffix)); n += 1
        shutil.move(str(p), str(цель))
        убрано += 1
        print("убрано в _исходники: %s" % p.name)
    print("\nостались как лица персонажей (%d): %s" % (len(оставлено), ", ".join(оставлено)))
    print("убрано посторонних: %d" % убрано)
    нет_лица = sorted(i for i in ids if not any((AVA / (i + "." + e)).exists()
                                                for e in ("jpg", "jpeg", "png", "webp", "gif")))
    if нет_лица:
        print("без файла лица: " + ", ".join(нет_лица) + " (если лицо вшито в карточку, она всё равно его покажет)")


if __name__ == "__main__":
    main()
