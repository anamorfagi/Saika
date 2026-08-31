# -*- coding: utf-8 -*-
"""Распознавание роликов движком Сайки (faster-whisper large-v3-turbo,
модель лежит локально). Запускается через файловый канал: cmd=runpy."""
import sys, os, io, time, traceback

OUTDIR = r"E:\Loading\_atlas_tmp"
STATUS = os.path.join(OUTDIR, "stt_status.txt")

def note(msg):
    try:
        with io.open(STATUS, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass

try:
    note("start | python=%s" % sys.executable)
    from faster_whisper import WhisperModel
    note("faster_whisper импортирован")

    MODEL = (r"C:\AI\Saika\models\hf\hub"
             r"\models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"
             r"\snapshots\0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf")
    note("модель есть: %s" % os.path.isdir(MODEL))

    # CUDA-рантайма нет (нет cublas64_12.dll) — честно идём на CPU
    dev, ct = "cpu", "int8"
    note("устройство=%s тип=%s" % (dev, ct))

    m = WhisperModel(MODEL, device=dev, compute_type=ct, local_files_only=True)
    note("модель загружена")

    for name in ("birdsong", "howsound"):
        wav = os.path.join(OUTDIR, name + ".wav")
        if not os.path.isfile(wav):
            note("нет файла %s" % wav); continue
        note("распознаю %s" % name)
        segs, info = m.transcribe(wav, language="en", beam_size=5, vad_filter=True)
        dst = os.path.join(OUTDIR, name + "_transcript.txt")
        n = 0
        with io.open(dst, "w", encoding="utf-8") as f:
            f.write("# %s | язык=%s | длительность=%.1f c\n\n"
                    % (name, info.language, info.duration))
            for s in segs:
                f.write("[%7.2f -> %7.2f] %s\n" % (s.start, s.end, s.text.strip()))
                n += 1
                if n % 25 == 0:
                    f.flush(); note("%s: %d реплик, %.0f c" % (name, n, s.end))
        note("ГОТОВО %s: %d реплик -> %s" % (name, n, dst))
    note("ВСЁ ГОТОВО")
except Exception:
    note("ОШИБКА:\n" + traceback.format_exc())
