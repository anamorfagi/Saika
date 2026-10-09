# -*- coding: utf-8 -*-
"""ЗАМКНУТЫЙ КРУГ: слушаю запись, вижу результат, правлю, повторяю.

Владелец: «если бы ты мог в потоке работать и сразу тестировать, сам
понимать, что нужно сделать, слушать ролик и одновременно видеть, как
система пишет, и находу править — мы бы в десять раз быстрее пришли».

Здесь ровно это, только без звука в его наушниках: в data/hear_bench/
лежат 300 РЕАЛЬНЫХ кусков его ролика и то, что система на них
услышала. Гоняем их заново тем же кодом и меряем.

═══ КАК МЕРИТЬ БЕЗ ЭТАЛОНА ═══
Расшифровки ролика у нас нет, и выдумывать её нельзя. Но три вещи
меряются без неё, и все три — прямо про его жалобы:

  СОГЛАСИЕ ДВУХ ДВИЖКОВ. Два независимых распознавателя, ошибающихся
  по-разному, согласились на слове — слово почти наверняка сказано.
  Разошлись — вот оно, подозрительное место. Это даёт УВЕРЕННОСТЬ ПО
  СЛОВАМ без единой строчки эталона: не «кажется лучше», а «стало
  больше слов, на которых оба сходятся».

  ЦЕЛОСТНОСТЬ ШВОВ. Кусок, закрытый ножом по потолку, рвёт слово
  пополам. Считаем, сколько кусков закрыто паузой, а сколько ножом, и
  сколько слов на стыках повторилось или пропало.

  ЦЕНА. Доля реального времени на кусок. Точность, купленная ценой
  отставания, на слабом железе не точность.

Запуск (из корня, в его venv):
    .venv\\Scripts\\python tools\\hear_loop.py            — все куски
    .venv\\Scripts\\python tools\\hear_loop.py 60         — первые 60
    .venv\\Scripts\\python tools\\hear_loop.py 60 метка   — с меткой прогона

Пишет data/hear_loop.jsonl (по куску) и data/hear_loop.md (сводка).
Каждый прогон дописывает строку в data/hear_loop_history.tsv — по нему
видно, СТАЛО ЛУЧШЕ ИЛИ ХУЖЕ после правки, а не «вроде получше».
"""
import io, json, os, sys, time, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); os.chdir(str(ROOT))

import numpy as np
from anamorf.config import CFG
from anamorf.stt.manager import STTManager
from anamorf.stt import tidy as _tidy
from anamorf.stt import stream_tone as _tone

BENCH = ROOT / "data" / "hear_bench"
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 0
MARK = sys.argv[2] if len(sys.argv) > 2 else ""


def read_wav(p: Path):
    with wave.open(str(p), "rb") as w:
        sr, n = w.getframerate(), w.getnframes()
        a = np.frombuffer(w.readframes(n), np.int16)
        if w.getnchannels() > 1:
            a = a.reshape(-1, w.getnchannels()).mean(axis=1).astype(np.int16)
    return a, sr


def words(t):
    import re
    return [w for w in re.sub(r"[^\w\s]+", " ", (t or "").lower()).split() if w]


def agree(a, b):
    """Доля слов первого текста, которые есть и во втором (по мультимножеству).

    Не WER: WER требует эталона, а его нет. Это согласие двух независимых
    свидетелей — величина, которая растёт ровно тогда, когда система
    начинает слышать вернее."""
    wa, wb = words(a), words(b)
    if not wa:
        return 0.0
    from collections import Counter
    cb = Counter(wb)
    hit = 0
    for w in wa:
        if cb[w] > 0:
            cb[w] -= 1
            hit += 1
    return hit / len(wa)


def main():
    idx = []
    f = BENCH / "index.jsonl"
    if f.exists():
        for line in io.open(f, encoding="utf-8"):
            try:
                idx.append(json.loads(line))
            except Exception:
                pass
    if LIMIT:
        idx = idx[-LIMIT:]
    if not idx:
        print("нет записей в data/hear_bench/index.jsonl"); return

    stt = STTManager()
    _tone.warm("lab")
    t0 = time.monotonic()
    while not _tone.status().get("ready") and time.monotonic() - t0 < 90:
        time.sleep(0.5)
    tone_ok = bool(_tone.status().get("ready"))
    print("поток T-one:", "поднят" if tone_ok else "не поднялся — считаю без него")

    out, rows = [], []
    for i, rec in enumerate(idx, 1):
        p = BENCH / str(rec.get("wav") or "")
        if not p.exists():
            continue
        a, sr = read_wav(p)
        sec = len(a) / float(sr or 16000)
        t1 = time.monotonic()
        try:
            res = stt.transcribe_segment(a) or []
        except Exception as e:
            print("  кусок %s упал: %r" % (p.name, e)); continue
        ms = (time.monotonic() - t1) * 1000
        txt = _tidy.polish((res[0].get("text") if res else "") or "", "lab", seam=False)

        # черновик потока — второй независимый свидетель
        draft = ""
        if tone_ok:
            s = _tone.stream("lab#0")
            if s._model is None:
                s._model = _tone.stream("lab")._model
            s._frames = []; s._tail = np.zeros(0, np.int32); s._state = None
            step = int(sr * 0.3)
            for k in range(0, len(a), step):
                s.feed(a[k:k + step])
            draft = s.close()

        r = {"wav": p.name, "sec": round(sec, 2), "ms": round(ms),
             "rtf": round(ms / 1000.0 / max(0.01, sec), 3),
             "text": txt, "draft": draft,
             "was": rec.get("text") or "",
             "agree_draft": round(agree(txt, draft), 3),
             "agree_prev": round(agree(txt, rec.get("text") or ""), 3),
             "words": len(words(txt))}
        rows.append(r)
        if i % 20 == 0:
            print("  %d/%d" % (i, len(idx)), flush=True)

    if not rows:
        print("нечего мерить"); return
    io.open(ROOT / "data" / "hear_loop.jsonl", "w", encoding="utf-8").write(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows))

    n = len(rows)
    med = lambda k: round(float(np.median([r[k] for r in rows])), 3)
    tot_w = sum(r["words"] for r in rows)
    empty = sum(1 for r in rows if not r["words"])
    summ = {
        "кусков": n,
        "слов всего": tot_w,
        "пустых кусков": empty,
        "слов на кусок (медиана)": med("words"),
        "согласие с потоком (медиана)": med("agree_draft"),
        "согласие с прошлым прогоном (медиана)": med("agree_prev"),
        "цена, доля реального времени (медиана)": med("rtf"),
        "хуже реального времени, кусков": sum(1 for r in rows if r["rtf"] > 1.0),
    }
    md = ["# Круг слуха — прогон %s%s\n" % (
        time.strftime("%Y-%m-%d %H:%M"), (" · " + MARK) if MARK else ""), ""]
    md.append("ЧЕМ МЕРЕНО: %d записанных кусков ролика из data/hear_bench, "
              "движок %s, поток %s.\n" % (
                  n, CFG.get("stt.engine", "?"),
                  "T-one" if tone_ok else "выключен"))
    for k, v in summ.items():
        md.append("- **%s**: %s" % (k, v))
    md.append("\n## Самые спорные куски (движок и поток разошлись)\n")
    for r in sorted(rows, key=lambda x: x["agree_draft"])[:12]:
        md.append("- `%s` (%.1fс, согласие %.2f)\n  - движок: %s\n  - поток: %s"
                  % (r["wav"], r["sec"], r["agree_draft"],
                     r["text"][:110], r["draft"][:110]))
    io.open(ROOT / "data" / "hear_loop.md", "w", encoding="utf-8").write(
        "\n".join(md))

    hist = ROOT / "data" / "hear_loop_history.tsv"
    if not hist.exists():
        io.open(hist, "w", encoding="utf-8").write(
            "время\tметка\tкусков\tслов\tпустых\tсогласие\tцена\tхуже РВ\n")
    io.open(hist, "a", encoding="utf-8").write(
        "%s\t%s\t%d\t%d\t%d\t%.3f\t%.3f\t%d\n" % (
            time.strftime("%Y-%m-%d %H:%M"), MARK or "-", n, tot_w, empty,
            summ["согласие с потоком (медиана)"],
            summ["цена, доля реального времени (медиана)"],
            summ["хуже реального времени, кусков"]))
    print("\n".join("%s: %s" % (k, v) for k, v in summ.items()))
    print("\nПодробно: data/hear_loop.md, data/hear_loop.jsonl")


if __name__ == "__main__":
    main()
