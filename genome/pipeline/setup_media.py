# -*- coding: utf-8 -*-
"""Поставить три способности и сразу проверить их делом, а не по факту установки.

crawl4ai — читать страницы браузером (403 и JS-заглушки).
yt-dlp    — снимать субтитры с видео: дословная речь без поиска по сайтам.
faster-whisper — расшифровка звука, когда субтитров нет.
"""
import json
import pathlib
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ЗДЕСЬ = pathlib.Path(__file__).resolve().parent
ПОТОЛОК = ЗДЕСЬ.parent.parent / "setup" / "constraints.txt"


def поставить(пакеты):
    cmd = [sys.executable, "-m", "pip", "install", "--quiet"] + пакеты
    if ПОТОЛОК.exists():
        cmd += ["-c", str(ПОТОЛОК)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=1800)
    print(("поставлено: " if r.returncode == 0 else "НЕ поставлено: ") + " ".join(пакеты))
    if r.returncode != 0:
        print((r.stderr or "")[-1200:])
    return r.returncode == 0


for группа in (["yt-dlp"], ["faster-whisper"], ["crawl4ai"]):
    поставить(группа)

sys.path.insert(0, str(ЗДЕСЬ))
import importlib
import tools_web
importlib.reload(tools_web)
print("\nготовность:", json.dumps(tools_web.чего_не_хватает(), ensure_ascii=False))

# Проверка делом: субтитры с известного ролика и чтение закрытой 403 страницы.
print("\n-- субтитры с видео --")
try:
    r = tools_web.субтитры_видео("https://www.youtube.com/watch?v=BQ4yd2W50No", "en")
    print(r["вид"], r["символов"], "символов")
    print(r["текст"][:300].replace("\n", " | "))
except Exception as e:
    print("не вышло:", str(e)[:300])

print("\n-- страница, закрытая 403 --")
try:
    t = tools_web.читать_браузером("https://marvelcinematicuniverse.fandom.com/wiki/Karen")
    print(len(t), "символов")
    print(t[:300].replace("\n", " | "))
except Exception as e:
    print("не вышло:", str(e)[:300])
