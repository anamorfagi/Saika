# -*- coding: utf-8 -*-
"""Что на самом деле лежит в собранной студии на диске."""
import pathlib, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
h = (pathlib.Path(__file__).resolve().parent.parent / "genome-studio.html").read_text(encoding="utf-8", errors="replace")
проверки = [
 ("промпт: разделы по весу", "Это в тебе главное"),
 ("промпт: второе лицо", "воВтороеЛицо"),
 ("промпт: кириллические границы", "const ГР='(?<![а-яёА-ЯЁ])'"),
 ("промпт: схлопывание дублей", "const похоже="),
 ("промпт: противоречия", "В тебе это уживается вместе"),
 ("промпт: старой дозировки НЕТ", None),
 ("кнопка собрать моделью", "data-smith"),
 ("кнопка сохранить в папку", "data-tofile"),
 ("архетипы: честный процент", "let score=raw;"),
 ("архетипы: род по полу", 'const NMof=s=>(SEX==="f")?s.n:(s.nm||s.n);'),
 ("возраст: канон первым", "по произведению"),
 ("гены существа", '["beast.pack"'),
 ("гены природы агента", '["nat.adaptive"'),
]
for имя, игла in проверки:
    if имя.endswith("НЕТ"):
        print(("ok   " if "doza(g.v)" not in h else "НЕТ  ") + имя)
    else:
        print(("ok   " if игла in h else "НЕТ  ") + имя)
print("\nразмер студии:", len(h), "знаков")
