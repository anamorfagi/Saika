#!/usr/bin/env python3
"""СТЕНД-ОЦЕНЩИК СЛУХА — насколько наш транскриб близок к эталону.

Что делает:
  1. чистит эталон (ютуб-транскрипт): выкидывает таймкоды и теги [музыка]…;
  2. читает наш транскриб (data/eval_capture.jsonl — по строке на реплику);
  3. выравнивает по словам (difflib) и считает WER, потерянные слова
     (deletions), фантомы (крупные insertions — выдуманные движком), а также
     сколько РАЗНЫХ голосов мы развели.

Запуск (на машине, где лежит проект):
    python tools/hear_eval.py --ref eval/dnk_ref_raw.txt \
        --ours data/eval_capture.jsonl [--from 0 --to 3600]

Ничего не тянет из сети и не грузит моделей — чистый текст, считается за
секунды. Это опорная линейка: сначала мерим, потом крутим пороги.
"""
import argparse
import difflib
import json
import re
import sys

# ── нормализация слов ──────────────────────────────────────────────────
_PUNC = re.compile(r"[^0-9a-zа-яё]+")
_TAG = re.compile(r"\[[^\]]*\]")           # [музыка], [смех], [ __ ]
_TS1 = re.compile(r"^\s*\d+:\d+\s*$")      # «21:44»
_TS2 = re.compile(r"^\s*\d+\s+(секунд|секунда|секунды|минут|минута|минуты|час)")


def norm_words(text: str):
    text = _TAG.sub(" ", text or "")
    text = text.replace("ё", "е").replace(">>", " ").lower()
    return [w for w in _PUNC.split(text) if w]


def load_ref(path: str):
    """Чистим ютуб-транскрипт: строки-таймкоды и теги — вон."""
    words = []
    for line in open(path, encoding="utf-8"):
        s = line.strip()
        if not s or _TS1.match(s) or _TS2.match(s):
            continue
        words.extend(norm_words(s))
    return words


def load_ours(path: str, t_from=None, t_to=None):
    """Наш транскриб: JSONL со строками {text, speaker, src, t?}.
    Возвращает (список_слов, множество_голосов, число_реплик)."""
    words, speakers, n = [], set(), 0
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if t_from is not None and r.get("t") is not None and r["t"] < t_from:
            continue
        if t_to is not None and r.get("t") is not None and r["t"] > t_to:
            continue
        w = norm_words(r.get("text", ""))
        if not w:
            continue
        words.extend(w)
        n += 1
        sp = r.get("speaker") or ""
        if sp:
            speakers.add(sp)
    return words, speakers, n


def score(ref, ours):
    """WER + разбор ошибок по блокам difflib.

    difflib даёт совпадающие блоки; между ними — замены/удаления/вставки.
    Крупная вставка (>=4 слов) без опоры в эталоне помечается как ФАНТОМ;
    крупное удаление — как ПОТЕРЯННЫЙ кусок речи."""
    sm = difflib.SequenceMatcher(a=ref, b=ours, autojunk=False)
    S = D = I = C = 0
    phantoms, drops = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        rlen, olen = i2 - i1, j2 - j1
        if tag == "equal":
            C += rlen
        elif tag == "replace":
            S += max(rlen, olen)
            if olen - rlen >= 4:
                phantoms.append(" ".join(ours[j1:j2]))
            if rlen - olen >= 4:
                drops.append(" ".join(ref[i1:i2]))
        elif tag == "delete":
            D += rlen
            if rlen >= 4:
                drops.append(" ".join(ref[i1:i2]))
        elif tag == "insert":
            I += olen
            if olen >= 4:
                phantoms.append(" ".join(ours[j1:j2]))
    wer = (S + D + I) / max(1, len(ref))
    return {"wer": wer, "sub": S, "del": D, "ins": I, "hit": C,
            "ref_words": len(ref), "our_words": len(ours),
            "phantoms": phantoms, "drops": drops}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", required=True)
    ap.add_argument("--ours", required=True)
    ap.add_argument("--from", dest="t_from", type=float, default=None)
    ap.add_argument("--to", dest="t_to", type=float, default=None)
    ap.add_argument("--show", type=int, default=12,
                    help="сколько примеров фантомов/потерь показать")
    a = ap.parse_args()

    ref = load_ref(a.ref)
    ours, speakers, n = load_ours(a.ours, a.t_from, a.t_to)
    if not ref:
        print("эталон пуст — проверь --ref"); sys.exit(1)
    if not ours:
        print("наш транскриб пуст — стенд ещё не писал (см. eval_capture)")
        sys.exit(1)

    r = score(ref, ours)
    print("═" * 56)
    print(f"  ЭТАЛОН   слов: {r['ref_words']}")
    print(f"  НАШ      слов: {r['our_words']}   реплик: {n}   голосов: {len(speakers)}")
    print("─" * 56)
    print(f"  WER: {r['wer']*100:5.1f}%   "
          f"(замен {r['sub']}, потерь {r['del']}, вставок {r['ins']}, "
          f"совпало {r['hit']})")
    acc = r['hit'] / max(1, r['ref_words'])
    print(f"  Покрытие эталона (совпало/эталон): {acc*100:5.1f}%")
    print("─" * 56)
    print(f"  ФАНТОМЫ (выдуманные куски, {len(r['phantoms'])}):")
    for p in r["phantoms"][:a.show]:
        print(f"    + {p[:80]}")
    print(f"  ПОТЕРЯННЫЕ КУСКИ ({len(r['drops'])}):")
    for d in r["drops"][:a.show]:
        print(f"    - {d[:80]}")
    if speakers:
        print("─" * 56)
        print(f"  Разведено голосов: {len(speakers)} -> {sorted(speakers)}")
    print("═" * 56)


if __name__ == "__main__":
    main()
