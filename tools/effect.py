"""ЖУРНАЛ ЭФФЕКТА: помогла правка или только показалась (2026-08-20).

Владелец, про идею стащить чужую практику: «сделай что полезно
потенциально и следи, реально ли это нам поможет в будущем».

Вторая половина фразы и есть весь смысл этого файла. Мы за два дня
закрыли восемь живых поломок, и каждая правка звучала убедительно —
убедительно звучали и прошлые, после которых человек снова писал «я тебе
уже об этом говорил, но ты не правил». Единственный способ отличить
починку от впечатления о починке — цифра ДО и цифра ПОСЛЕ.

ПОЧЕМУ ЦИФРЫ НОРМИРОВАНЫ. «Вранья стало меньше» ничего не значит, если в
этот день просто меньше разговаривали. Поэтому всё считается НА СТО
КОМАНД: знаменатель — сколько раз вообще начинался диалог. Абсолютные
числа тоже показываем, но решение принимается по нормированным.

ЧТО МЕРЯЕМ — ровно то, что обещали правки, и ничего «на всякий случай»:

  врёт            модель сказала «сделала», не вызвав инструмент.
                  Главная болезнь проекта (PLAN_BUILD, этап 1).
  без модели      доля команд, закрытых рефлексом. Растёт — значит,
                  команды перестают зависеть от облака и от прогрева.
  второй движок   сколько раз поднималась вторая локальная модель.
                  После one_local.py обязано стать НУЛЁМ.
  рубила всё      сколько раз защита сносила голос, слух и мозги разом.
                  После ступеней разгрузки должно падать.
  ронял звук      сколько раз слух не успевал за реальным временем.
  ответ           медиана «до первого токена», в секундах.

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. Главное мерило проекта — «сколько команд подряд
идёт без повтора» — по логу не считается: в нём не видно, повторил человек
просьбу или сказал новое. Врать удобной оценкой хуже, чем честно
признать, что этой цифры у нас пока нет.

    python tools/effect.py                  весь лог по дням
    python tools/effect.py --split 2026-08-20   было / стало вокруг даты
    python tools/effect.py --save           дописать снимок в историю

--save важен отдельно: логи ротируются и стираются, а logs/effect.jsonl
остаётся. Через месяц он и ответит на вопрос «реально ли это нам помогло».
Файл лежит в logs/, то есть ВНЕ git, и это нарочно: это история работы
конкретного человека за конкретным компьютером, ей не место в публичном
репозитории. На новой машине снимки начнут копиться заново.
"""
import argparse
import collections
import io
import json
import os
import re
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "logs", "saika.log")
HIST = os.path.join(ROOT, "logs", "effect.jsonl")

# знаменатель: сколько раз вообще начинался разговор
BASE = re.compile(r"handle_text: стартую диалог")

EVENTS = (
    ("врёт",          re.compile(r"заявила о действии, которого не делала")),
    ("рефлекс",       re.compile(r"Рефлекс: |Мгновенный рефлекс")),
    ("второй движок", re.compile(r"locallm: запускаю воркер|"
                                 r"Второй локальный движок не поднимаю")),
    ("рубила всё",    re.compile(r"ЗАЩИТА: .*выгружаю всё")),
    ("ронял звук",    re.compile(r"Слух не успевает")),
    ("держала ввод",  re.compile(r"Отправку придержала")),
)
LATENCY = re.compile(r"итого до 1-го токена (\d+)мс")


def scan(path=LOG):
    """Лог -> {день: {метрика: число}} + задержки по дням."""
    days = collections.defaultdict(collections.Counter)
    lat = collections.defaultdict(list)
    if not os.path.exists(path):
        return days, lat
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            day = line[:10]
            if len(day) != 10 or day[4] != "-":
                continue
            if BASE.search(line):
                days[day]["команд"] += 1
            for name, rx in EVENTS:
                if rx.search(line):
                    days[day][name] += 1
            m = LATENCY.search(line)
            if m:
                lat[day].append(int(m.group(1)))
    return days, lat


def fold(days, lat, keys):
    """Свернуть несколько дней в один набор цифр."""
    tot = collections.Counter()
    all_lat = []
    for d in keys:
        tot.update(days[d])
        all_lat += lat.get(d, [])
    n = max(1, tot.get("команд", 0))
    out = {"дней": len(keys), "команд": tot.get("команд", 0)}
    for name, _ in EVENTS:
        out[name] = tot.get(name, 0)
        out[name + "/100"] = round(tot.get(name, 0) * 100.0 / n, 1)
    out["ответ, с"] = (round(statistics.median(all_lat) / 1000.0, 1)
                       if all_lat else None)
    return out


def _fmt(v):
    return "—" if v is None else str(v)


def show_days(days, lat):
    print(f"{'день':<12}{'команд':>7}{'врёт':>7}{'/100':>7}"
          f"{'рефлекс':>9}{'/100':>7}{'2-й движок':>12}"
          f"{'рубила всё':>12}{'ронял звук':>12}{'ответ,с':>9}")
    for d in sorted(days):
        c = days[d]
        n = max(1, c.get("команд", 0))
        med = (round(statistics.median(lat[d]) / 1000.0, 1)
               if lat.get(d) else None)
        print(f"{d:<12}{c.get('команд', 0):>7}{c.get('врёт', 0):>7}"
              f"{c.get('врёт', 0) * 100.0 / n:>7.1f}"
              f"{c.get('рефлекс', 0):>9}{c.get('рефлекс', 0) * 100.0 / n:>7.1f}"
              f"{c.get('второй движок', 0):>12}{c.get('рубила всё', 0):>12}"
              f"{c.get('ронял звук', 0):>12}{_fmt(med):>9}")


def show_split(days, lat, date):
    before = [d for d in sorted(days) if d < date]
    after = [d for d in sorted(days) if d >= date]
    if not before or not after:
        print(f"Для сравнения нужны дни и до {date}, и после. "
              f"Есть: {len(before)} и {len(after)}.")
        return
    a, b = fold(days, lat, before), fold(days, lat, after)
    print(f"БЫЛО (до {date}, дней {a['дней']}, команд {a['команд']})")
    print(f"СТАЛО (с {date}, дней {b['дней']}, команд {b['команд']})\n")
    print(f"{'метрика':<18}{'было/100':>10}{'стало/100':>11}{'сдвиг':>10}")
    for name, _ in EVENTS:
        k = name + "/100"
        d = b[k] - a[k]
        arrow = "лучше" if (d < 0) != (name == "рефлекс") else "хуже"
        if abs(d) < 0.05:
            arrow = "ровно"
        print(f"{name:<18}{a[k]:>10}{b[k]:>11}{d:>+9.1f}  {arrow}")
    if a["ответ, с"] and b["ответ, с"]:
        d = b["ответ, с"] - a["ответ, с"]
        print(f"{'ответ, с':<18}{a['ответ, с']:>10}{b['ответ, с']:>11}"
              f"{d:>+9.1f}  {'лучше' if d < 0 else 'хуже'}")
    print("\nЦифры нормированы на сто команд: иначе «стало меньше» значило "
          "бы только\nто, что в этот день меньше разговаривали.")


def save(days, lat):
    keys = sorted(days)
    if not keys:
        print("В логе нечего сохранять.")
        return
    snap = fold(days, lat, keys)
    snap.update(снято=time.strftime("%Y-%m-%d %H:%M"),
                период=f"{keys[0]}..{keys[-1]}")
    with io.open(HIST, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(snap, ensure_ascii=False) + "\n")
    print(f"Снимок дописан в {HIST}: {snap['период']}, "
          f"команд {snap['команд']}.")


def main():
    ap = argparse.ArgumentParser(description="помогла правка или показалась")
    ap.add_argument("--split", metavar="ГГГГ-ММ-ДД",
                    help="сравнить «до» и «с» этой даты")
    ap.add_argument("--save", action="store_true",
                    help="дописать снимок в logs/effect.jsonl")
    ap.add_argument("--log", default=LOG)
    args = ap.parse_args()

    days, lat = scan(args.log)
    if not days:
        print(f"Лога нет или он пуст: {args.log}")
        return 1
    if args.split:
        show_split(days, lat, args.split)
    else:
        show_days(days, lat)
    if args.save:
        save(days, lat)
    return 0


if __name__ == "__main__":
    sys.exit(main())
