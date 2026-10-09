# -*- coding: utf-8 -*-
"""КАКАЯ ПЕТЛЯ РЕАЛЬНО НЕСЁТ ЗВУК (05.09.2026).

НИЧЕГО НЕ ВКЛЮЧАЕТ САМА (правка 05.09, вечер). Первая версия для
замера запускала data/snailkick.wav — и на машине владельца это
заиграло ПОВЕРХ его ролика: два звука разом, слух ловил кашу.
Стенд не имеет права трогать звук в системе. Меряем то, что играет:
если тихо — так и говорим «включи звук и повтори», а не создаём его
сами.

Владелец отключил наушники, и слух замолчал: Сайка слушала петлю с
устройства, которого больше нет в тракте. Перевыбор по умолчанию не
помогает — «выход по умолчанию» и «выход, где реально играет звук» на
этой машине разные вещи (виртуальные устройства Oculus, Steam, VB-Cable
все объявляют себя выходами).

Поэтому не спрашиваем систему, а СЛУШАЕМ: запускаем ролик и меряем
уровень на каждой петле по очереди. Та, где есть сигнал, и есть ответ.
Гадать тут нечего — это измерение."""
import io, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
O = []
def say(*a): O.append(" ".join(str(x) for x in a))

WAV = ROOT / "data" / "snailkick.wav"
SR = 16000

try:
    import numpy as np
    import soundcard as sc

    try:
        say("выход по умолчанию:", sc.default_speaker().name)
    except Exception as e:
        say("выход по умолчанию не спросился:", repr(e))

    loops = [m for m in sc.all_microphones(include_loopback=True)
             if getattr(m, "isloopback", False)]
    say("петель найдено: %d" % len(loops))
    say("")
    say("меряю каждую петлю по 1.6 с — по тому, что играет сейчас")

    rows = []
    for m in loops:
        peak = 0.0
        err = ""
        try:
            with m.recorder(samplerate=SR, channels=1,
                            blocksize=int(SR * 0.1)) as rec:
                t0 = time.time()
                while time.time() - t0 < 1.6:
                    d = np.asarray(rec.record(numframes=int(SR * 0.1)),
                                   dtype=np.float32)
                    if d.ndim > 1:
                        d = d.mean(axis=1)
                    if d.size:
                        peak = max(peak, float(np.abs(d).max()))
        except Exception as e:
            err = repr(e)[:70]
        db = 20 * np.log10(max(peak, 1e-7))
        rows.append((peak, db, m.name, err))
        say("   %7.1f дБ  %-52s %s"
            % (db, m.name[:52], ("ОШИБКА: " + err) if err else
               ("<== ЗДЕСЬ ЗВУК" if peak > 0.003 else "")))

    rows.sort(reverse=True)
    say("")
    if rows and rows[0][0] > 0.003:
        say("ОТВЕТ: звук идёт через «%s» (%.1f дБ)" % (rows[0][2], rows[0][1]))
        say("Пропишу её как петлю по умолчанию.")
    else:
        say("НИ НА ОДНОЙ ПЕТЛЕ СИГНАЛА НЕТ.")
        say("Значит звук уходит на устройство, которое Windows не отдаёт в "
            "петлю: чаще всего это интерфейс в монопольном режиме "
            "(ASIO/Focusrite). Лечится галочкой «Разрешить приложениям "
            "монопольный режим» в свойствах устройства — снять её, — либо "
            "выводом звука на обычные динамики.")
except Exception:
    import traceback; say(traceback.format_exc())

io.open(ROOT / "data" / "find_loopback.txt", "w",
        encoding="utf-8").write("\n".join(O))
