# -*- coding: utf-8 -*-
"""
[БЛОК ЛИЦА] Разложить аватары персонажей под правильными именами.

Зачем. Карточка ищет лицо по строгому пути ava/<id>.jpg|png|webp, а в папке лежали
файлы с человеческими именами («Kurumi Tokisaki ( 時崎狂三 ).jpg», «эм.png») — ни одно
не совпадало с id, и лица не показывались. Сами картинки при этом никуда не девались:
они лежат внутри share/<id>.genome.json полем avatar в виде data:image/…;base64.

Скрипт достаёт их оттуда и кладёт рядом под именем id. Ничего не удаляет и не
перезаписывает без причины: если файл уже есть и он свежее записи в персонаже —
оставляет как есть.

Запуск: python pipeline/fix_avatars.py [--force]
"""
import base64
import json
import pathlib
import re
import sys

# Консоль Windows по умолчанию cp1251: стрелка и кириллица в выводе роняли скрипт
# с UnicodeEncodeError — и полезная работа пропадала из-за строчки печати.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHARE = ROOT / "share"
AVA = ROOT / "ava"
EXT = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "webp": "webp", "gif": "gif"}


def main():
    force = "--force" in sys.argv
    AVA.mkdir(exist_ok=True)
    взято = пропущено = без_лица = 0
    for f in sorted(SHARE.glob("*.genome.json")):
        try:
            card = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print("не читается %s: %s" % (f.name, e)); continue
        ident = str(card.get("id") or "").strip()
        data = card.get("avatar") or ""
        if not ident:
            continue
        m = re.match(r"^data:image/([a-z]+);base64,(.+)$", data, re.S)
        if not m:
            без_лица += 1
            print("%-26s лица в файле нет" % ident)
            continue
        ext = EXT.get(m.group(1), "jpg")
        out = AVA / (ident + "." + ext)
        if out.exists() and not force:
            пропущено += 1
            print("%-26s уже на месте (%s)" % (ident, out.name))
            continue
        raw = base64.b64decode(m.group(2))
        out.write_bytes(raw)
        взято += 1
        print("%-26s -> ava/%s  %d KB" % (ident, out.name, len(raw) // 1024))
    print("\nразложено: %d · уже было: %d · без лица в файле: %d" % (взято, пропущено, без_лица))
    лишние = [p.name for p in AVA.iterdir()
              if p.is_file() and not re.fullmatch(r"[a-z0-9_]+\.(jpg|png|webp|gif)", p.name)]
    if лишние:
        print("лежат с посторонними именами (карточка их не найдёт): " + ", ".join(лишние))


if __name__ == "__main__":
    main()
