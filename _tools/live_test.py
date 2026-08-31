# -*- coding: utf-8 -*-
"""Живой прогон: играем звук в комнату, Сайка слышит его своим трактом,
атлас строится сам. Снимаем несколько кадров по ходу."""
import io, os, time, traceback, threading
OUT = r"E:\Loading\_atlas_tmp"
ST = os.path.join(OUT, "shot_status.txt")
def note(m):
    with io.open(ST, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))
try:
    import ctypes
    from ctypes import wintypes
    from PIL import ImageGrab
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
        note("окна нет"); raise SystemExit
    h = hw[0]
    u32.SetForegroundWindow(h); time.sleep(.8)
    r = wintypes.RECT(); u32.GetWindowRect(h, ctypes.byref(r))
    box = (r.left, r.top, r.right, r.bottom)

    wav = os.path.join(OUT, "birdsong.wav")
    note("играю %s" % wav)
    import winsound
    winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
    for i, t in enumerate((8, 16, 26, 34)):
        while time.time() - t0 < t if False else False:
            pass
        time.sleep(8 if i == 0 else 8)
        img = ImageGrab.grab(bbox=box, all_screens=True)
        dst = os.path.join(OUT, "live_%d.png" % (i + 1))
        img.save(dst)
        note("кадр %d -> %s" % (i + 1, dst))
    winsound.PlaySound(None, 0)
    note("ГОТОВО живой прогон")
except Exception:
    note("ОШИБКА:\n" + traceback.format_exc())
