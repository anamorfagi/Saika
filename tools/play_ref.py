# -*- coding: utf-8 -*-
"""Найти скачанный ролик и запустить его (05.09.2026).

Нужен для проверки слуха на живой многоголосой речи: в ролике говорят
несколько человек, и это ровно та задача, ради которой строились дорожки
голосов. Синтетикой такое не проверишь — там нет ни перебиваний, ни
музыки под речь, ни того, что один человек за десять минут звучит
по-разному."""
import io, os, sys, glob, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
O = []
def say(*a): O.append(" ".join(str(x) for x in a))

import sys as _sys
# имя ролика можно передать аргументом: tools/play_ref.py "snail kick"
WORDS = tuple(w.lower() for w in _sys.argv[1:]) or ()
EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4a", ".mp3", ".wav")
home = os.path.expanduser("~")
roots = [os.path.join(home, d) for d in ("Downloads", "Videos", "Desktop",
                                         "Music")]
roots += [r"C:\AI\Saika", r"D:\\", r"I:\\"]

found = []
for r in roots:
    if not os.path.isdir(r):
        continue
    try:
        for f in glob.glob(os.path.join(r, "**", "*"), recursive=True)[:40000]:
            if not f.lower().endswith(EXT):
                continue
            nm = os.path.basename(f).lower()
            if not WORDS or any(w in nm for w in WORDS):
                try:
                    st = os.stat(f)
                    if st.st_size > 2 * 1024 * 1024:      # не огрызки
                        found.append((st.st_mtime, st.st_size, f))
                except Exception:
                    pass
    except Exception as e:
        say("обход %s: %r" % (r, e))

found.sort(reverse=True)
say("=== НАШЛА ПОДХОДЯЩИХ ФАЙЛОВ: %d ===" % len(found))
for ts, sz, f in found[:10]:
    say("   %6.1f МБ  %s" % (sz / 1048576.0, f))

# НЕ НАШЛА ТОЧНОЕ — СПРОСИ, А НЕ ЗАПУСКАЙ ПОХОЖЕЕ (исправлено 05.09.2026
# после живого промаха: фильтр по имени ничего не дал, скрипт расширил
# поиск до «самого свежего видео» и запустил старый тестовый eval_take.wav.
# Правило «не нашла — расширь поиск» плохое: оно превращает промах в
# уверенное неправильное действие, а это ровно то, чего владелец не
# терпит. Запускаем только явное совпадение по имени либо прямо
# названный путь.)
if found and WORDS:
    target = found[0][2]
    say("")
    say("ЗАПУСКАЮ: " + target)
    try:
        os.startfile(target)
        say("отдала системе — играет в плеере по умолчанию")
    except Exception as e:
        say("не запустилось: %r" % e)
else:
    say("")
    say("Ничего похожего не нашла. Скажи путь или имя файла.")
    # покажу свежие видео, вдруг название другое
    recent = []
    for r in roots[:3]:
        if not os.path.isdir(r):
            continue
        for f in glob.glob(os.path.join(r, "*")):
            if f.lower().endswith(EXT):
                try:
                    recent.append((os.path.getmtime(f), f))
                except Exception:
                    pass
    recent.sort(reverse=True)
    say("Свежие видео/аудио рядом:")
    for _t, f in recent[:12]:
        say("   " + f)

io.open(ROOT / "data" / "play_ref.txt", "w",
        encoding="utf-8").write("\n".join(O))
