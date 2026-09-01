# -*- coding: utf-8 -*-
"""КАЖДЫЙ ПРОГОН — СТРОКА ИЗМЕРЕНИЙ, А НЕ ВПЕЧАТЛЕНИЕ (2026-08-31).

Повод — прямой упрёк владельца: «логи просто летят, я надеюсь ты хотя бы
данные собираешь». Не собирал. Прогоны шли, цифры читались глазами и
выбрасывались, а потом я дважды прочитал собственную калибровку задом
наперёд и один раз правил ключ, которого система не читает. Ровно этого
и не случается, когда каждый прогон ложится в файл рядом с настройками,
при которых он был сделан.

Что считает: WER против эталона владельца, число и длину фраз, задержку
разбора, сколько раз выходил живой черновик, сколько людей завела
кластеризация, сколько было наложений и запикиваний. Плюс СНИМОК РУЧЕК —
без него строка бесполезна: непонятно, что именно её породило.

Файл дописывается, никогда не переписывается: сравнивать имеет смысл
только соседние строки.
"""
import io, os, sys, json, re, time, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
LOG = os.path.join(ROOT, "logs", "saika.log")
OUT = os.path.join(ROOT, "logs", "bench_hear.jsonl")
REF = os.path.join(ROOT, "slux_test", "snailkik_dnk", "ref_1320_1500.txt")

KNOBS = ["stt.vad.silence_ms", "stt.vad.max_segment_s", "stt.vad.min_speech_ms",
         "stt.polish_every_s", "stt.polish_min_s", "stt.polish_skip_q",
         "voiceprint.tracks.link_cos", "voiceprint.tracks.merge_cos",
         "voiceprint.tracks.confirm_s", "voiceprint.encoder",
         "denoise.engine", "stt.engine"]


def norm(t):
    t = t.lower().replace("ё", "е")
    t = re.sub(r"[^а-яa-z0-9 ]+", " ", t)
    return [w for w in t.split() if w]


def wer(ref, hyp):
    r, h = norm(ref), norm(hyp)
    if not r:
        return None, 0, 0
    d = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1):
        d[i][0] = i
    for j in range(len(h) + 1):
        d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i][j] = min(d[i-1][j] + 1, d[i][j-1] + 1,
                          d[i-1][j-1] + (r[i-1] != h[j-1]))
    return d[len(r)][len(h)] / len(r), len(r), len(h)


def tail(path, marker_bytes):
    with io.open(path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(marker_bytes)
        return f.read()


def main():
    # Канал команд не умеет передавать аргументы, поэтому метку начала
    # прогона кладут в файл рядом. Без неё замер считает по всему
    # журналу разом и выдаёт бессмысленное число — что и случилось на
    # первом же запуске.
    mark, note = 0, ""
    if len(sys.argv) > 1:
        mark = int(sys.argv[1])
        note = sys.argv[2] if len(sys.argv) > 2 else ""
    else:
        try:
            d = json.load(io.open(os.path.join(ROOT, "data", "bench_mark.json"),
                                  encoding="utf-8"))
            mark, note = int(d.get("mark", 0)), str(d.get("note", ""))
        except Exception:
            pass
    if not mark:
        print("НЕТ МЕТКИ начала прогона — считать не по чему. "
              "Положи data/bench_mark.json перед реплеем.")
        return
    txt = tail(LOG, mark)

    secs = [float(x) for x in re.findall(r"Слух по стадиям \(([0-9.]+)с звука", txt)]
    mss = [int(x) for x in re.findall(r"итого (\d+)мс", txt)]
    heard = re.findall(r"Мозги выключены — реплику не рождаю: '([^']*)'", txt)
    row = {
        "ts": time.strftime("%Y-%m-%d %H:%M"),
        "note": note,
        "фраз": len(secs),
        "средняя_длина_с": round(sum(secs) / len(secs), 2) if secs else 0,
        "мин_с": round(min(secs), 2) if secs else 0,
        "макс_с": round(max(secs), 2) if secs else 0,
        "средняя_задержка_мс": round(sum(mss) / len(mss)) if mss else 0,
        "черновиков": len(re.findall(r"stt_draft", txt)),
        "черновик_молчал": dict(re.findall(r"Черновик молчит: ([^×]+)×(\d+)", txt)[:6]),
        "новых_кластеров": len(re.findall(r"Дорожки: новый кластер", txt)),
        "стали_людьми": len(re.findall(r"Дорожки: кластер \d+ стал человеком", txt)),
        "наложений": len(re.findall(r"разведено на 2 дорожки", txt)),
        "смена_голоса_в_фразе": len(re.findall(r"Смена голоса внутри фразы", txt)),
    }
    try:
        from anamorf.config import CFG
        row["ручки"] = {k: CFG.get(k, None) for k in KNOBS}
    except Exception as e:
        row["ручки"] = {"ошибка": str(e)[:80]}

    if heard and os.path.exists(REF):
        ref = io.open(REF, encoding="utf-8").read()
        w, nr, nh = wer(ref, " ".join(heard))
        row["WER"] = round(w, 3) if w is not None else None
        row["слов_эталон"] = nr
        row["слов_услышано"] = nh
        row["примечание_WER"] = ("считан по обрезанным строкам журнала "
                                 "(до 60 символов) — годится для сравнения "
                                 "прогонов между собой, не как абсолют")

    with io.open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(row, ensure_ascii=False, indent=1))


main()
