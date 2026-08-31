# -*- coding: utf-8 -*-
"""Нажать сектор СЛУХ и снять раскрытие покадрово."""
import io, os, time, ctypes
from ctypes import wintypes
OUT = r"E:\Loading\_atlas_tmp"
ST = os.path.join(OUT, "shot_status.txt")
def note(m):
    with io.open(ST, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))
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
W, H = r.right - r.left, r.bottom - r.top
# сектор СЛУХ — левый нижний: 19% ширины, 67% высоты
x = r.left + int(W * 0.19)
y = r.top + int(H * 0.67)
from PIL import ImageGrab
u32.SetCursorPos(x, y); time.sleep(.35)
u32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
time.sleep(.05)
u32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP
t0 = time.time()
for i in range(16):
    img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
    img = img.resize((img.width // 2, img.height // 2))
    img.save(os.path.join(OUT, "fan_%d.png" % i))
    time.sleep(0.09)
note("веер снят: 16 кадров, клик в %d,%d" % (x, y))
print("ok")
