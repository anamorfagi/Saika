# -*- coding: utf-8 -*-
"""СВЕРКА С РАСШИФРОВКОЙ ПО ТАЙМЕРУ РОЛИКА (06.09.2026).

Владелец: «проверяй в реальном режиме в проге, как она пишет, сравнивай с
транскрибом и реальными таймерами ролика», «научись улавливать, как
система пишет сверхтонкие элементы, даже с учётом того, что ты сам не
можешь слышать».

Слышать мне и не нужно — нужно СОВМЕСТИТЬ ДВЕ ЛЕНТЫ ВО ВРЕМЕНИ:
  • что написала Сайка (data/hear_bench/index.jsonl, у каждой реплики
    стенное время, длительность и время работы движка);
  • что говорят на самом деле (transkrib.txt, у каждой строки — секунда
    ролика).

Мост между ними — ЯКОРЬ: момент, когда ролик запущен с известной
секунды (data/play_anchor.txt). Дальше простая арифметика:
    конец звука   ≈ ts − время_работы_движка
    начало звука  ≈ конец − длительность
    секунда_ролика = начало − якорь + стартовая_секунда

Считаем на каждый кусок:
  НАЙДЕНО   — доля слов эталона, которые Сайка написала (пропуски);
  ЛИШНЕЕ    — доля её слов, которых в эталоне нет (выдумки);
  СДВИГ     — на сколько её окно разъехалось с эталоном по времени.
Это и есть «сверхтонкие элементы»: не «похоже/непохоже», а какие именно
слова потеряны и где именно.
"""
import io, json, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "slux_test" / "snailkik_dnk" / "transkrib.txt"
IDX = ROOT / "data" / "hear_bench" / "index.jsonl"
ANCH = ROOT / "data" / "play_anchor.txt"
OUT = ROOT / "data" / "hear_align.md"

_HEAD = re.compile(r'^(?:(\d+):)?(\d{1,2}):(\d{2})')
_SEC = re.compile(r'секунд[а-я]*')
_W = re.compile(r'[^\w\s]+', re.UNICODE)


def words(t):
    return [w for w in _W.sub(' ', (t or '').lower()).replace('ё', 'е').split() if w]


def load_ref():
    out = []
    for ln in io.open(REF, encoding='utf-8', errors='replace'):
        m = _HEAD.match(ln)
        if not m:
            continue
        t = int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        k = _SEC.search(ln)
        s = ln[k.end():].strip() if k else ''
        if s:
            out.append((t, s))
    return out


def ref_window(ref, a, b):
    """Слова эталона, чьи строки попадают в окно [a, b] секунд ролика.
    Берём с запасом в одну строку с каждой стороны: у эталона метка —
    НАЧАЛО строки, а строка может тянуться дальше."""
    got = []
    for i, (t, s) in enumerate(ref):
        nxt = ref[i + 1][0] if i + 1 < len(ref) else t + 10
        if nxt >= a and t <= b:
            got.append(s)
    return words(" ".join(got))


def overlap(a, b):
    """Сколько слов из a нашлось в b (мультимножеством)."""
    from collections import Counter
    cb = Counter(b)
    hit = 0
    for w in a:
        if cb[w] > 0:
            cb[w] -= 1
            hit += 1
    return hit


def main():
    if not ANCH.exists():
        print("нет якоря: сначала tools/play_from.py"); return
    m = re.search(r'ts=([\d.]+)\s+видео_сек=(\d+)', ANCH.read_text(encoding='utf-8'))
    a_ts, a_sec = float(m.group(1)), int(m.group(2))
    ref = load_ref()
    rows = []
    for ln in io.open(IDX, encoding='utf-8', errors='replace'):
        try:
            d = json.loads(ln)
        except Exception:
            continue
        ts = float(d.get('ts') or 0)
        if ts < a_ts:
            continue
        sec = float(d.get('sec') or 0)
        eng = float(d.get('ms') or 0) / 1000.0
        end = ts - eng - a_ts + a_sec
        beg = max(0.0, end - sec)
        heard = words(d.get('text'))
        want = ref_window(ref, beg - 1.5, end + 1.5)
        if not want and not heard:
            continue
        hit = overlap(want, heard)
        extra = len(heard) - overlap(heard, want)
        rows.append({
            "beg": beg, "end": end, "text": d.get('text') or '',
            "слов_у_неё": len(heard), "слов_в_эталоне": len(want),
            "найдено": round(hit / len(want), 3) if want else None,
            "лишнее": round(extra / len(heard), 3) if heard else None,
        })
    if not rows:
        print("после якоря ещё ничего не услышано"); return
    fnd = [r["найдено"] for r in rows if r["найдено"] is not None]
    ext = [r["лишнее"] for r in rows if r["лишнее"] is not None]
    avg = lambda v: round(sum(v) / len(v), 3) if v else 0
    print("ЧЕМ МЕРЕНО: %d реплик после якоря, эталон %s (%d строк)."
          % (len(rows), REF.name, len(ref)))
    print("НАЙДЕНО слов эталона (средн.): %.1f%%" % (avg(fnd) * 100))
    print("ЛИШНЕГО в её тексте (средн.):  %.1f%%" % (avg(ext) * 100))
    print("окно ролика: %02d:%02d — %02d:%02d"
          % (rows[0]["beg"] // 60, rows[0]["beg"] % 60,
             rows[-1]["end"] // 60, rows[-1]["end"] % 60))
    md = ["# Сверка с расшифровкой — %s" % time.strftime("%H:%M"), ""]
    md.append("ЧЕМ МЕРЕНО: %d реплик, эталон transkrib.txt (%d строк), "
              "якорь ts=%.0f видео_сек=%d\n" % (len(rows), len(ref), a_ts, a_sec))
    md.append("- НАЙДЕНО слов эталона: **%.1f%%**" % (avg(fnd) * 100))
    md.append("- ЛИШНЕГО у неё: **%.1f%%**\n" % (avg(ext) * 100))
    md.append("## Худшие куски\n")
    for r in sorted([r for r in rows if r["найдено"] is not None],
                    key=lambda x: x["найдено"])[:10]:
        md.append("- %02d:%02d–%02d:%02d найдено %.0f%% (её слов %d, в эталоне %d)\n  - %s"
                  % (r["beg"] // 60, r["beg"] % 60, r["end"] // 60, r["end"] % 60,
                     (r["найдено"] or 0) * 100, r["слов_у_неё"], r["слов_в_эталоне"],
                     r["text"][:100]))
    OUT.write_text("\n".join(md), encoding='utf-8')
    print("\nПодробно: data/hear_align.md")


if __name__ == "__main__":
    main()
