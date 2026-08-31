# -*- coding: utf-8 -*-
"""Включить слух: сфокусировать окно и нажать M (её штатный хоткей)."""
import io, time, ctypes
from ctypes import wintypes
OUT = r"E:\Loading\_atlas_tmp\pressm.txt"
def w(m):
    with io.open(OUT,"a",encoding="utf-8") as f: f.write(str(m)+"\n")
io.open(OUT,"w",encoding="utf-8").write("")
u32 = ctypes.windll.user32
hw=[]
def cb(h,_):
    n=u32.GetWindowTextLengthW(h)
    if n:
        b=ctypes.create_unicode_buffer(n+1); u32.GetWindowTextW(h,b,n+1)
        if b.value.strip().upper()=="ANAMORF" and u32.IsWindowVisible(h): hw.append(h)
    return True
P=ctypes.WINFUNCTYPE(ctypes.c_bool,wintypes.HWND,wintypes.LPARAM)
u32.EnumWindows(P(cb),0)
w("окон ANAMORF: %d"%len(hw))
if hw:
    h=hw[0]
    u32.ShowWindow(h,9)          # SW_RESTORE
    u32.SetForegroundWindow(h)
    time.sleep(1.2)
    VK_M=0x4D
    u32.keybd_event(VK_M,0,0,0); time.sleep(0.06)
    u32.keybd_event(VK_M,0,2,0)  # KEYEVENTF_KEYUP
    w("нажал M")
else:
    w("окно не найдено")
