"""Мгновенное чтение ТЕКСТА с экрана — OCR, а не большая нейросеть.

ЗАЧЕМ (15.08.2026, владелец): «чтобы она могла супер часто это делать,
мгновенно, чтобы в игре могла даже диалоги читать — найди современные
подходы». Современный подход ровно один и он встроен в Windows: движок
Windows.Media.Ocr читает кадр за 50-150 мс НА ПРОЦЕССОРЕ, по-русски, без
единого мегабайта видеопамяти. Им пользуются PowerToys Text Extractor и
Snipping Tool. Для «что написано на экране» звать VLM-гиганта — это
секунды и гигабайты; OCR — сотая доля цены, можно дёргать хоть каждый
кадр. VLM (look_screen) остаётся для «что ПРОИСХОДИТ на экране»; этот
модуль — для «что НАПИСАНО».

Запасной путь — RapidOCR (PaddleOCR на onnxruntime), если стоит: он
лучше на стилизованных игровых шрифтах. Нет ни того ни другого — честная
инструкция, что поставить (winsdk весит мегабайты, ставится за секунды).
"""
import logging
import time

import numpy as np

from server.config import CFG

log = logging.getLogger("saika.ocr")

_ENG = {"winrt": None, "rapid": None, "why": ""}


def _winrt_engine():
    if _ENG["winrt"] is not None:
        return _ENG["winrt"]
    try:
        from winsdk.windows.globalization import Language
        from winsdk.windows.media.ocr import OcrEngine
        eng = OcrEngine.try_create_from_language(Language("ru"))
        _ENG["ru"] = bool(eng)
        if not eng:
            # БЕЗ РУССКОГО ДВИЖКА НЕ ЧИТАЕМ ИМ КИРИЛЛИЦУ (2026-08-15,
            # живой позор: английский движок «прочитал» игровой диалог как
            # «ABTO Q YavnbA. CTyKN» — транслит вместо текста, и Сайка
            # выдала эту кашу владельцу. Латиница англ. движком читается
            # нормально, поэтому не выбрасываем его совсем — но для
            # кириллицы первым идёт RapidOCR, а лечение говорим прямо.)
            eng = OcrEngine.try_create_from_user_profile_languages()
            _ENG["why"] = ("Windows-OCR без русского: Параметры → Время и "
                           "язык → Язык → Русский → Распознавание текста; "
                           "или дождись rapidocr (ставится start.bat)")
        _ENG["winrt"] = eng or False
    except Exception as e:
        _ENG["winrt"] = False
        _ENG["why"] = ("нет пакета winsdk — поставь: .venv\\Scripts\\pip "
                       "install winsdk (пара мегабайт, секунды)")
        log.debug("winrt ocr: %s", e)
    return _ENG["winrt"]


def _winrt_read(img) -> str:
    """numpy BGR -> текст через Windows.Media.Ocr."""
    import asyncio

    from winsdk.windows.graphics.imaging import (BitmapPixelFormat,
                                                 SoftwareBitmap)
    from winsdk.windows.security.cryptography import CryptographicBuffer

    eng = _winrt_engine()
    if not eng:
        raise RuntimeError(_ENG["why"] or "Windows-OCR недоступен")
    h, w = img.shape[:2]
    bgra = np.dstack([img, np.full((h, w), 255, np.uint8)])
    buf = CryptographicBuffer.create_from_byte_array(list(bgra.tobytes()))
    bmp = SoftwareBitmap.create_copy_from_buffer(
        buf, BitmapPixelFormat.BGRA8, w, h)

    async def _run():
        return await eng.recognize_async(bmp)

    res = asyncio.run(_run())
    lines = [ln.text for ln in res.lines] if res else []
    return "\n".join(lines)


def _rapid_read(img) -> str:
    if _ENG["rapid"] is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ENG["rapid"] = RapidOCR()
        except Exception:
            _ENG["rapid"] = False
    if not _ENG["rapid"]:
        raise RuntimeError("rapidocr не установлен")
    res, _ = _ENG["rapid"](img)
    return "\n".join(r[1] for r in (res or []))


def read_screen(monitor=None) -> str:
    """Снять кадр и вернуть ВЕСЬ читаемый текст. Быстро, можно часто."""
    from server import vision
    t0 = time.monotonic()
    img = vision.grab_screen(monitor)
    errs = []
    order = ((_winrt_read, "winrt"), (_rapid_read, "rapid"))
    _winrt_engine()
    if _ENG.get("ru") is False:
        order = ((_rapid_read, "rapid"), (_winrt_read, "winrt"))
    for fn, tag in order:
        try:
            txt = (fn(img) or "").strip()
            ms = round((time.monotonic() - t0) * 1000)
            if txt:
                log.info("OCR (%s): %d символов за %d мс", tag, len(txt), ms)
                return txt
            errs.append(f"{tag}: текста не нашёл")
        except Exception as e:
            errs.append(f"{tag}: {str(e)[:120]}")
    raise RuntimeError("; ".join(errs))


def tool_call(arguments) -> str:
    """Для tools.call: человеческий ответ, а не трассировка."""
    a = arguments or {}
    if isinstance(a, str):
        a = {}
    # ВИДНО, ОТКУДА ЧИТАЕТ (2026-08-19). Мелкое действие, но человек должен
    # видеть, с какого экрана она сняла текст, — иначе «я прочитала» звучит
    # так же, как «я придумала». Номер экрана считаем по-человечески, как в
    # vision._pick_monitor: 1 — первый.
    try:
        from server import highlight
        _m = a.get("monitor") or a.get("screen")
        highlight.show_monitor(int(_m) if _m else 1, "читаю текст")
    except Exception as _he:
        log.debug("прицел OCR: %s", _he)
    try:
        txt = read_screen(a.get("monitor"))
    except Exception as e:
        return ("прочитать текст с экрана не вышло: %s. Скажи это прямо и "
                "коротко." % str(e)[:200])
    if len(txt) > 1800:
        txt = txt[:1800] + "…"
    return ("текст на экране (прочитан мгновенным OCR, дословно):\n" + txt +
            "\nПерескажи человеку ТО, О ЧЁМ он спросил, а не весь список.")
