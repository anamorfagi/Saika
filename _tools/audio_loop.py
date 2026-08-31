# -*- coding: utf-8 -*-
"""Доходит ли звук из колонок до микрофона? Меряем, а не гадаем."""
import io, time, traceback
import numpy as np
OUT = r"E:\Loading\_atlas_tmp\audio_loop.txt"
def w(m):
    with io.open(OUT, "a", encoding="utf-8") as f: f.write(m + "\n")
io.open(OUT, "w", encoding="utf-8").write("")
try:
    import sounddevice as sd
    di, do = sd.default.device
    w("вход по умолчанию: %s" % str(sd.query_devices(sd.default.device[0])["name"]))
    w("выход по умолчанию: %s" % str(sd.query_devices(sd.default.device[1])["name"]))
    sr = 16000
    # тишина: какой фон
    rec = sd.rec(int(1.5 * sr), samplerate=sr, channels=1, dtype="float32")
    sd.wait()
    w("фон (тишина) RMS = %.5f" % float(np.sqrt((rec ** 2).mean())))
    # играем тон и одновременно пишем
    t = np.arange(int(2.0 * sr)) / sr
    tone = (0.35 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    rec = sd.rec(int(2.0 * sr), samplerate=sr, channels=1, dtype="float32")
    sd.play(tone, sr); sd.wait()
    r = float(np.sqrt((rec ** 2).mean()))
    w("во время тона 440 Гц RMS = %.5f  -> %s" %
      (r, "МИКРОФОН СЛЫШИТ КОЛОНКИ" if r > 0.004 else "НЕ СЛЫШИТ (колонки тихие/выключены или микрофон выключен)"))
    try:
        import comtypes; w("comtypes есть — вход можно переключить системно")
    except Exception as e:
        w("comtypes нет: %r" % e)
    try:
        from pycaw.pycaw import AudioUtilities; w("pycaw есть")
    except Exception as e:
        w("pycaw нет: %r" % e)
except Exception:
    w("ОШИБКА:\n" + traceback.format_exc())
