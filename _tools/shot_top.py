# -*- coding: utf-8 -*-
"""Прокрутить панель СЛУХ в самый верх (к атласу) и снять кадр."""
import io, os, time, traceback
OUT = r"E:\Loading\_atlas_tmp"
ST = os.path.join(OUT, "shot_status.txt")
def note(m):
    with io.open(ST, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))
try:
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    hw = []
    def cb(h, _):
        n = u32.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(h, b, n + 1)
            if b.value.strip().upper() == "ANAMORF" and u32.IsWindowVisible(h):
                hw.append(h)
        return True
    P = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    u32.EnumWindows(P(cb), 0)
    if not hw:
        note("окно ANAMORF не найдено"); raise SystemExit
    h = hw[0]
    u32.SetForegroundWindow(h); time.sleep(1.0)
    r = wintypes.RECT(); u32.GetWindowRect(h, ctypes.byref(r))
    # КРУТИМ НАД ПРАВОЙ КОЛОНКОЙ, А НЕ НАД КАРТОЙ: колесо над сценой
    # атласа — это зум, и снимок выходил в диком приближении
    cx = r.left + int((r.right - r.left) * 0.86)
    cy = (r.top + r.bottom) // 2
    u32.SetCursorPos(cx, cy); time.sleep(.3)
    # крутим колесо вверх — панель уезжает к первой странице
    for _ in range(110):
        u32.mouse_event(0x0800, 0, 0, 240, 0)   # MOUSEEVENTF_WHEEL
        time.sleep(0.02)
    time.sleep(1.5)
    from PIL import ImageGrab
    img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
    dst = os.path.join(OUT, "anamorf_atlas.png")
    img.save(dst)
    note("ГОТОВО атлас -> %s (%dx%d)" % (dst, img.width, img.height))
except Exception:
    note("ОШИБКА:\n" + traceback.format_exc())
