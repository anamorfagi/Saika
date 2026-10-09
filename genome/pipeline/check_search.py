# -*- coding: utf-8 -*-
"""Проверка поиска реплик без единого обращения к платной модели.

Гоняет новые шаблоны запросов, отбрасывает мусор и показывает, сколько
читаемого текста реально снимается со страницы. Нужно, чтобы отличить
«модель ошиблась» от «в источниках не было ни строчки речи».
"""
import sys
import pathlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import research as R

имя = sys.argv[1] if len(sys.argv) > 1 else "Karen"
работа = sys.argv[2] if len(sys.argv) > 2 else "Spider-Man: Homecoming"
клички = sys.argv[3].split("|") if len(sys.argv) > 3 else []

всего, читаемых = 0, 0
for q in R.речевые_запросы(имя, клички, работа):
    print("\n== " + q)
    try:
        rows = R.search_web(q)
    except Exception as e:
        print("   поиск не удался:", repr(e)[:160])
        continue
    for r in rows[:5]:
        url = r["url"]
        if R.junk_source(url):
            print("   мусор  ", url[:95]); continue
        if not R.по_делу(r, имя, клички, работа):
            print("   мимо   ", url[:95]); continue
        всего += 1
        try:
            текст = R.fetch_source(url)
        except Exception as e:
            print("   ошибка ", url[:80], repr(e)[:70]); continue
        реплик = текст.count(имя + ":") + текст.count(имя.upper() + ":")
        if len(текст) >= 600:
            читаемых += 1
        print(f"   {len(текст):>7} симв · строк «{имя}:» {реплик:>3} · {url[:80]}")

print(f"\nитог: пригодных ссылок {всего}, читаемых страниц {читаемых}")
