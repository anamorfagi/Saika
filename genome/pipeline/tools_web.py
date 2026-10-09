# -*- coding: utf-8 -*-
"""
[БЛОК ИНСТРУМЕНТЫ] Три способности, которых движку не хватало: пробить защиту
страницы, снять субтитры с видео и расшифровать звук.

Зачем. Обычный запрос по http получает от fandom.com 403, а от JS-сайтов —
пустую оболочку на 21 символ. Видео вообще не читалось: страница с роликом
отдаёт описание, а не речь. Между тем у фильма и ролика есть готовые
субтитры — это дословная речь, её не надо искать по фан-сайтам.

Каждая функция работает сама и честно сообщает, чего не хватает, а не делает
вид, что справилась. Всё это подключено инструментами в цикл охоты: модель
вызывает их сама, когда видит, что обычное чтение не дало текста.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ВРЕМЕННО = pathlib.Path(tempfile.gettempdir()) / "anamorf_media"


def _найти(имя):
    """Найти программу, даже если её папки нет в PATH процесса.

    ffmpeg на машине стоит давно, но дочерний процесс запускался без его
    папки в PATH, и проверка врала «не установлен». Смотрим PATH, затем
    обычные места установки, затем реестр conda/winget-оболочек.
    """
    прямо = shutil.which(имя)
    if прямо:
        return прямо
    хвост = ".exe" if os.name == "nt" else ""
    места = []
    for пер in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "USERPROFILE", "ProgramData"):
        корень = os.environ.get(пер)
        if not корень:
            continue
        места += [
            pathlib.Path(корень) / imя / "bin" / (имя + хвост) for imя in
            ("ffmpeg", "FFmpeg", "ffmpeg-master-latest-win64-gpl", "Gyan.FFmpeg")]
        места.append(pathlib.Path(корень) / (имя + хвост))
        места.append(pathlib.Path(корень) / "Microsoft" / "WindowsApps" / (имя + хвост))
    места += [pathlib.Path(r"C:\ffmpeg\bin") / (имя + хвост),
              pathlib.Path(r"C:\Program Files\ffmpeg\bin") / (имя + хвост),
              pathlib.Path(sys.prefix) / "Scripts" / (имя + хвост),
              pathlib.Path(sys.prefix) / "Library" / "bin" / (имя + хвост)]
    for путь in места:
        try:
            if путь.exists():
                return str(путь)
        except OSError:
            continue
    # Последняя попытка: поискать по дереву обычных мест установки, неглубоко.
    for корень in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles")):
        if not корень:
            continue
        for найдено in pathlib.Path(корень).glob("*/*/bin/" + имя + хвост):
            return str(найдено)
    return None


def _есть(имя):
    return _найти(имя) is not None


def _ytdlp():
    """Команда запуска yt-dlp.

    В venv пакет ставится, а exe в PATH не попадает — проверка shutil.which
    врала, что его нет. Модулем он доступен всегда, если пакет установлен.
    """
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    try:
        import yt_dlp  # noqa: F401
        return [sys.executable, "-m", "yt_dlp"]
    except Exception:
        return None


# ---------------------------------------------------------------- страницы

def _без_подмены():
    """Убрать папку pipeline из головы sys.path на время импорта чужих библиотек.

    В pipeline лежит свой profile.py, и crawl4ai, импортируя стандартный
    profile, получал наш — падало с «module 'profile' has no attribute run».
    """
    своя = str(pathlib.Path(__file__).resolve().parent)
    было = list(sys.path)
    sys.path[:] = [p for p in sys.path if pathlib.Path(p or '.').resolve() != pathlib.Path(своя)]
    sys.path.append(своя)
    for имя in ("profile", "corpus", "ingest", "scout", "persona"):
        подмена = sys.modules.get(имя)
        if подмена and getattr(подмена, "__file__", "").startswith(своя):
            del sys.modules[имя]
    return было


def читать_браузером(url, таймаут=90):
    """Прочитать страницу настоящим браузером: рендерит JS и проходит 403.

    Возвращает текст. Поднимает RuntimeError, если crawl4ai не установлен —
    вызывающий тогда остаётся на обычном http-чтении, а не падает.
    """
    было = _без_подмены()
    try:
        from crawl4ai import WebCrawler  # старое имя, на части сборок ещё живо
    except Exception:
        WebCrawler = None
    finally:
        sys.path[:] = было
    if WebCrawler is not None:
        c = WebCrawler(); c.warmup()
        r = c.run(url=url, bypass_cache=True)
        return (getattr(r, "markdown", "") or getattr(r, "cleaned_html", "") or "")
    # Новый асинхронный интерфейс.
    import asyncio
    было = _без_подмены()
    try:
        from crawl4ai import AsyncWebCrawler
    finally:
        sys.path[:] = было

    async def _ход():
        async with AsyncWebCrawler(verbose=False) as c:
            r = await c.arun(url=url, bypass_cache=True, page_timeout=таймаут * 1000)
            текст = getattr(r, "markdown", None)
            if hasattr(текст, "raw_markdown"):
                текст = текст.raw_markdown
            return текст or getattr(r, "cleaned_html", "") or ""

    return asyncio.run(_ход())


# ---------------------------------------------------------------- субтитры

def _вытащить_текст_из_vtt(путь):
    """Из vtt/srt оставить только речь: без таймкодов, номеров и разметки."""
    строки = []
    for line in pathlib.Path(путь).read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.isdigit() or s.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")):
            continue
        if "-->" in s:
            continue
        s = re.sub(r"<[^>]+>", "", s)
        if s and (not строки or строки[-1] != s):
            строки.append(s)
    return "\n".join(строки)


def субтитры_видео(url, язык="en"):
    """Снять готовые субтитры с видео. Это дословная речь без расшифровки.

    Сначала берутся авторские субтитры, и только при их отсутствии —
    автоматические: у автоматических нет знаков препинания и они путают
    похожие слова, поэтому их качество надо понимать заранее.
    """
    ytdlp = _ytdlp()
    if not ytdlp:
        raise RuntimeError("нет yt-dlp — субтитры снять нечем")
    ВРЕМЕННО.mkdir(parents=True, exist_ok=True)
    папка = pathlib.Path(tempfile.mkdtemp(dir=str(ВРЕМЕННО)))
    основа = str(папка / "sub")
    # плейлист: только первые 4 видео (--playlist-items), иначе yt-dlp тянет сотню серий минутами
    авторские = subprocess.run(
        ytdlp + ["--skip-download", "--write-subs", "--sub-langs", f"{язык},{язык}.*,ru",
         "--sub-format", "vtt/srt", "--playlist-items", "1-4", "-o", основа + "_%(autonumber)s", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    файлы = sorted(папка.glob("*.vtt")) + sorted(папка.glob("*.srt"))
    вид = "авторские"
    if not файлы:
        subprocess.run(
            ytdlp + ["--skip-download", "--write-auto-subs", "--sub-langs", f"{язык},{язык}.*",
             "--sub-format", "vtt", "--playlist-items", "1-4", "-o", основа + "_%(autonumber)s", url],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240)
        файлы = sorted(папка.glob("*.vtt"))
        вид = "автоматические"
    if not файлы:
        хвост = (авторские.stderr or "")[-300:]
        raise RuntimeError("субтитров у этого видео нет. " + хвост)
    текст = _вытащить_текст_из_vtt(файлы[0])
    return {"вид": вид, "символов": len(текст), "текст": текст}


def субтитры_файла(путь, дорожка=0):
    """Вытащить встроенные субтитры из файла фильма на диске (ffmpeg)."""
    ff = _найти("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg не нашёлся ни в PATH, ни в обычных местах установки")
    путь = pathlib.Path(путь)
    if not путь.exists():
        raise RuntimeError("нет файла " + str(путь))
    ВРЕМЕННО.mkdir(parents=True, exist_ok=True)
    цель = ВРЕМЕННО / (путь.stem + ".srt")
    r = subprocess.run([ff, "-y", "-i", str(путь), "-map", f"0:s:{дорожка}", str(цель)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    if not цель.exists():
        raise RuntimeError("в файле нет дорожки субтитров №%d. %s" % (дорожка, (r.stderr or "")[-250:]))
    текст = _вытащить_текст_из_vtt(цель)
    return {"вид": "встроенные", "символов": len(текст), "текст": текст}


# ---------------------------------------------------------------- звук

def расшифровать(источник, язык=None, модель="small"):
    """Расшифровать речь из видео или аудио локально, без облака.

    Порядок: если это ссылка — сначала пробуем готовые субтитры, они точнее
    любой расшифровки и достаются за секунды. Расшифровка — запасной путь.
    """
    if str(источник).startswith("http"):
        try:
            готовое = субтитры_видео(источник, язык or "en")
            if готовое["символов"] > 400:
                return готовое
        except Exception:
            pass
        ytdlp = _ytdlp()
        if not ytdlp:
            raise RuntimeError("нет yt-dlp — звук не скачать")
        ВРЕМЕННО.mkdir(parents=True, exist_ok=True)
        папка = pathlib.Path(tempfile.mkdtemp(dir=str(ВРЕМЕННО)))
        subprocess.run(ytdlp + ["-x", "--audio-format", "mp3", "-o",
                        str(папка / "a.%(ext)s"), str(источник)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900)
        звуки = sorted(папка.glob("a.*"))
        if not звуки:
            raise RuntimeError("звук не скачался")
        путь = звуки[0]
    else:
        путь = pathlib.Path(источник)
        if not путь.exists():
            raise RuntimeError("нет файла " + str(путь))
    try:
        from faster_whisper import WhisperModel
    except Exception:
        raise RuntimeError("нет faster-whisper — расшифровать нечем")
    ядро = WhisperModel(модель, device="auto", compute_type="int8")
    куски, инфо = ядро.transcribe(str(путь), language=язык, vad_filter=True)
    строки = [s.text.strip() for s in куски if s.text and s.text.strip()]
    текст = "\n".join(строки)
    return {"вид": "расшифровка", "язык": getattr(инфо, "language", язык or ""),
            "символов": len(текст), "текст": текст}


def чего_не_хватает():
    """Честный отчёт о готовности — чтобы не гадать, почему инструмент молчит."""
    итог = {}
    итог["yt-dlp"] = _ytdlp() is not None
    итог["ffmpeg"] = _найти("ffmpeg") or False
    for имя, модуль in (("crawl4ai", "crawl4ai"), ("faster-whisper", "faster_whisper")):
        было = _без_подмены()
        try:
            __import__(модуль); итог[имя] = True
        except Exception as e:
            итог[имя] = "нет: " + str(e)[:90]
        finally:
            sys.path[:] = было
    return итог


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(чего_не_хватает(), ensure_ascii=False, indent=2))
