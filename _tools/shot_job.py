# -*- coding: utf-8 -*-
"""Снимок окна ANAMORF: смотрим, что реально рисует живая система."""
import io, os, time, traceback
OUT = r"E:\Loading\_atlas_tmp"
ST = os.path.join(OUT, "shot_status.txt")
def note(m):
    with io.open(ST, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))
try:
    note("start")
    import ctypes
    from ctypes import wintypes
    u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32
    # ищем окно приложения по заголовку
    hwnds = []
    def cb(h, _):
        n = u32.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, b, n + 1)
            t = b.value
            if "ANAMORF" in t.upper() or "Сайка" in t:
                if u32.IsWindowVisible(h):
                    hwnds.append((h, t))
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    u32.EnumWindows(WNDENUMPROC(cb), 0)
    note("окна: %r" % (hwnds,))
    from PIL import ImageGrab
    if hwnds:
        h = hwnds[0][0]
        u32.SetForegroundWindow(h)
        time.sleep(1.2)
        r = wintypes.RECT()
        u32.GetWindowRect(h, ctypes.byref(r))
        note("прямоугольник %d,%d,%d,%d" % (r.left, r.top, r.right, r.bottom))
        img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
    else:
        img = ImageGrab.grab(all_screens=True)
        note("окно не найдено — весь экран")
    dst = os.path.join(OUT, "anamorf_live.png")
    img.save(dst)
    note("ГОТОВО -> %s (%dx%d)" % (dst, img.width, img.height))
except Exception:
    note("ОШИБКА:\n" + traceback.format_exc())
