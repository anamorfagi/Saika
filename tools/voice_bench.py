# -*- coding: utf-8 -*-
"""ЭКЗАМЕН СЛУХА НА ЖИВОЙ МНОГОГОЛОСОЙ РЕЧИ (05.09.2026).

Владелец: «врубай ролик со Снейл Киком и запускай тесты по распознаванию
голоса… наптренируй систему пользоваться всеми своими модулями, чтобы она
хотя бы старалась правильно распознавать частоты голосов людей и правильно
в чате подкрашивала диалоги людей из ролика».

═══ ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ, А ЧТО НЕТ ═══

Проверяется ровно то, что нельзя проверить синтетикой: три минуты студии,
где говорят несколько человек, перебивают друг друга, смеются, а под этим
играет заставка. Один и тот же человек за три минуты звучит по-разному —
громче, тише, на смехе, на крике. Ни один искусственный набор такого не
даёт, а именно на этом слух и разваливается.

НЕ проверяется качество моделей вообще. Проверяется ЭТА связка на ЭТОМ
железе: сколько людей она насчитала, не склеила ли двух в одного, и
насколько текст похож на эталонный.

═══ ПОЧЕМУ ЗВУК ИДЁТ ЧЕРЕЗ КОЛОНКИ, А НЕ ФАЙЛОМ В ДВИЖОК ═══

Можно было скормить wav прямо распознавателю — вышло бы чище и быстрее.
И бесполезно: в реальной жизни звук проходит через колонки, комнату,
микрофон и петлю системного вывода, и ломается он именно там. Экзамен
должен идти тем же путём, что и работа.

Эталон рядом: slux_test/snailkik_dnk/ref_1320_1500.txt — расшифровка
того же куска, сделанная заранее. По ней и считается похожесть.
"""
import io
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
O = []


def say(*a):
    O.append(" ".join(str(x) for x in a))


WAV = ROOT / "data" / "snailkick.wav"
REF = ROOT / "slux_test" / "snailkik_dnk" / "ref_1320_1500.txt"
LOG = ROOT / "logs" / "saika.log"

_HEARD = re.compile(r"Слух по стадиям")
_STT = re.compile(r'"text":\s*"([^"]{2,})"')


def _norm(t: str) -> list:
    t = (t or "").lower().replace("ё", "е")
    t = re.sub(r"[^а-яa-z0-9 ]+", " ", t)
    return [w for w in t.split() if w]


def _wer_like(ref: list, hyp: list) -> float:
    """Доля эталонных слов, встретившихся в услышанном.

    Это НЕ настоящий WER: порядок не учитывается, и число завышено. Взято
    намеренно — настоящий WER требует выравнивания по времени, а у нас
    куски приходят вперемешку и с пропусками. Для вопроса «слышит вообще
    или кашу» этой меры достаточно, и она честно названа своим именем."""
    if not ref:
        return 0.0
    hs = {}
    for w in hyp:
        hs[w] = hs.get(w, 0) + 1
    hit = 0
    for w in ref:
        if hs.get(w):
            hs[w] -= 1
            hit += 1
    return hit / len(ref)


def main():
    from anamorf.config import CFG
    from anamorf import voiceprint as vp

    if not WAV.exists():
        say("нет файла %s" % WAV)
        return
    try:
        import wave
        with wave.open(str(WAV)) as w:
            secs = int(w.getnframes() / float(w.getframerate()))
    except Exception:
        secs = 180

    say("=== ЭКЗАМЕН СЛУХА ===")
    say("файл: %s (%d с)" % (WAV.name, secs))
    say("движок слуха: %s | отпечаток: %s | auto_meet: %s"
        % (CFG.get("stt.engine"), CFG.get("voiceprint.enabled"),
           CFG.get("voiceprint.auto_meet")))
    before = set((vp.S.reg.speakers or {}).keys())
    say("голосов в реестре ДО: %d %s" % (len(before),
                                         sorted(before)[:8]))
    pos = LOG.stat().st_size

    say("")
    say("--- играю через системный выход (тем же путём, что и живая речь)")
    import os
    os.startfile(str(WAV))
    t0 = time.time()
    while time.time() - t0 < secs + 25:
        time.sleep(5)

    say("--- слушала %d с, разбираю" % int(time.time() - t0))
    with open(LOG, "rb") as f:
        f.seek(pos)
        tail = f.read().decode("utf-8", "ignore")

    heard = []
    for line in tail.splitlines():
        m = re.search(r"Слух: язык|УСЛЫШАЛА", line)
        if "handle_text" in line and "в очередь" in line:
            mm = re.search(r"фраза '([^']+)'", line)
            if mm:
                heard.append(mm.group(1))
    # реплики уходят и через broadcast — соберём из журнала стенограммы
    for mm in re.finditer(r"стенограмма[^\n]*?«([^»]{4,})»", tail):
        heard.append(mm.group(1))

    after = set((vp.S.reg.speakers or {}).keys())
    new = sorted(after - before)
    say("")
    say("=== ГОЛОСА ===")
    say("было %d, стало %d, новых %d: %s"
        % (len(before), len(after), len(new), ", ".join(new[:12])))
    try:
        st = vp.status() or {}
        say("состояние отпечатка: " + json.dumps(
            {k: v for k, v in st.items()
             if k in ("enabled", "encoder", "dim", "n", "tracks")},
            ensure_ascii=False)[:300])
    except Exception:
        pass

    say("")
    say("=== ТЕКСТ ===")
    hyp = []
    for h in heard:
        hyp += _norm(h)
    ref = _norm(REF.read_text(encoding="utf-8")) if REF.exists() else []
    say("услышала слов: %d, в эталоне: %d" % (len(hyp), len(ref)))
    if ref and hyp:
        say("совпало по словам: %.0f%% (мера грубая, см. шапку файла)"
            % (100 * _wer_like(ref, hyp)))
    say("")
    say("первые реплики, как она их услышала:")
    for h in heard[:12]:
        say("   " + h[:110])

    say("")
    say("=== ЧТО ПИСАЛА В ЛОГ ПРО УЧЁБУ ===")
    for line in tail.splitlines():
        if "Дорожки" in line or "voice_learn" in line or "кластер" in line:
            say("   " + line.strip()[:170])


try:
    main()
except Exception:
    import traceback
    say(traceback.format_exc())
io.open(ROOT / "data" / "voice_bench.txt", "w",
        encoding="utf-8").write("\n".join(O))
