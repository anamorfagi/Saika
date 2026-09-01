# -*- coding: utf-8 -*-
"""ЗАМЕР ПО ЭТАЛОНУ ВЛАДЕЛЬЦА, А НЕ ПО ОЩУЩЕНИЯМ (2026-08-31).

Повод. Весь вечер пороги подбирались на глаз: «людей многовато»,
«похоже, слиплось». Дважды я прочитал собственную калибровку задом
наперёд, а один раз вообще правил ключ, который система не читает.
Ощущение — не измеритель. Владелец предложил разметить ролик руками:
кто говорит и с какой секунды. Это и есть эталон.

Что считаем:
  • сколько людей нашли против скольких есть на самом деле
  • ЧИСТОТА кластера — доля секунд одного человека внутри кластера
    (кластер из двух людей пополам даёт 0.5)
  • ПОЛНОТА человека — доля его секунд, попавших в его главный кластер
    (человек, размазанный по трём кластерам, даёт ~0.33)
  • DER — сколько секунд отнесено не тому, в процентах от речи

Чистота и полнота тянут в разные стороны: слепить всех в один кластер
даёт полноту 1.0 и никакой чистоты, а завести кластер на каждую реплику
— наоборот. Правильный порог тот, где обе высокие.

Запуск:
    ctl runpy tools/score_diar.py           — по последнему живому прогону
    (берёт разметку slux_test/snailkik_dnk/speakers.txt и дорожки из
     data/diar_last.json, который пишет живой прогон)
"""
import io, os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "slux_test", "snailkik_dnk", "speakers.txt")
HYP = os.path.join(ROOT, "data", "diar_last.json")


def t2s(t):
    p = [float(x) for x in t.split(":")]
    return p[0] * 60 + p[1] if len(p) == 2 else p[0]


def load_ref():
    out = []
    total = None
    for ln in io.open(REF, encoding="utf-8"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        m = re.match(r"^ВСЕГО:\s*(\d+)", ln)
        if m:
            total = int(m.group(1)); continue
        m = re.match(r"^(\d+:\d+(?:\.\d+)?)\s*-\s*(\d+:\d+(?:\.\d+)?)\s+(.+)$", ln)
        if m:
            out.append((t2s(m.group(1)), t2s(m.group(2)), m.group(3).strip()))
    return out, total


def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def main():
    ref, total = load_ref()
    if not ref:
        print("Разметка пустая — заполни %s" % REF); return
    if not os.path.exists(HYP):
        print("Нет %s — сначала прогони ролик живьём" % HYP); return
    hyp = json.load(io.open(HYP, encoding="utf-8"))   # [{t0,t1,cluster}]
    people = sorted({n for _, _, n in ref if n != "-"})
    print("в эталоне людей: %d%s, размеченной речи %.1fс"
          % (len(people), "" if total is None else " (заявлено %d)" % total,
             sum(b - a for a, b, n in ref if n != "-")))
    print("система нашла кластеров: %d, реплик %d"
          % (len({h["cluster"] for h in hyp}), len(hyp)))

    # матрица секунд: кластер x человек
    M = {}
    for h in hyp:
        for a, b, n in ref:
            if n == "-":
                continue
            ov = overlap(h["t0"], h["t1"], a, b)
            if ov > 0:
                M.setdefault(h["cluster"], {}).setdefault(n, 0.0)
                M[h["cluster"]][n] += ov
    if not M:
        print("Пересечений нет — проверь, что время в разметке от НАЧАЛА куска")
        return
    tot = sum(sum(v.values()) for v in M.values())
    pure = sum(max(v.values()) for v in M.values())
    print("\nчистота кластеров: %.0f%% (%.1f из %.1fс)"
          % (pure / tot * 100, pure, tot))
    print("%-12s %-14s %s" % ("кластер", "кто это на деле", "секунды"))
    for c, v in sorted(M.items(), key=lambda kv: -sum(kv[1].values())):
        parts = ", ".join("%s %.1fс" % (n, s)
                          for n, s in sorted(v.items(), key=lambda x: -x[1]))
        print("%-12s %s" % (c, parts))

    print("\nчеловек -> в скольких кластерах размазан")
    der_bad = 0.0
    for n in people:
        got = {c: v[n] for c, v in M.items() if n in v}
        if not got:
            print("  %-12s НЕ НАЙДЕН" % n); continue
        s = sum(got.values()); top = max(got.values())
        der_bad += s - top
        print("  %-12s кластеров %d, полнота %.0f%% (%.1f из %.1fс)"
              % (n, len(got), top / s * 100, top, s))
    print("\nDER (не тому отнесено): %.0f%%" % (der_bad / tot * 100))


main()
