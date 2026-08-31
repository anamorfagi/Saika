# -*- coding: utf-8 -*-
"""Проверка логики присуждения имени голосу — на живых фразах."""
import io, sys
sys.path.insert(0, r"C:\AI\Saika\build\ANAMORF-0.2.1\app")
OUT = r"E:\Loading\_atlas_tmp\naming.txt"
from anamorf.voiceprint import naming
CASES = [
    # (фраза, что ДОЛЖНО получиться)
    ("меня зовут Виталя",                 "Виталя"),
    ("привет, меня зовут Ольга",          "Ольга"),
    ("это я, Саня",                       "Саня"),
    ("я Дмитрий, очень приятно",          "Дмитрий"),
    ("Серёга, подай ключ",                "Серёга"),
    ("дядя Коля сказал что придёт",       "Коля"),
    ("тётя Люда звонила вчера",           "Люда"),
    ("ну пожалуй я пойду",                None),
    ("впрочем это неважно",               None),
    ("похоже дождь собирается",           None),
    ("короче я думаю так",                None),
    ("слушай а ты чего",                  None),
    ("Сайка включи музыку",               None),
    ("да ладно тебе",                     None),
    ("мы вчера с Мариной ходили в кино",  "Марина"),
    ("Андрей Петрович будет в среду",     "Андрей"),
    ("я не планировал типа это",          None),
    ("вот так вот получилось",            None),
]
with io.open(OUT, "w", encoding="utf-8") as f:
    ok = bad = 0
    for txt, want in CASES:
        try:
            g = naming.guess(txt)
        except Exception as e:
            g = ("ОШИБКА %r" % e,)
        got = None
        if g:
            got = g[0] if isinstance(g, (list, tuple)) else g
            if isinstance(got, (list, tuple)):
                got = got[0]
        good = (str(got) == str(want)) or (want is None and not got)
        ok += good; bad += (not good)
        f.write("%-38s -> %-12s %s\n" % (txt, str(got), "ok" if good else "НЕ ТО, ждали: %s" % want))
    f.write("\nверно %d из %d\n" % (ok, ok + bad))
