# -*- coding: utf-8 -*-
"""ПРОВЕРКА СНАРУЖИ — что реально изменилось на ПК (для стенда поведения).

Сайка может сказать «закрыла», и даже вызвать инструмент, а вкладка
останется висеть (живой случай владельца 09.10, 18:02). Поэтому стенд
верит не словам и не логу, а состоянию системы ДО и ПОСЛЕ хода:
заголовки окон (вкладка браузера = заголовок его окна), громкость.
"""
import ctypes
from ctypes import wintypes

_u32 = ctypes.windll.user32


def window_titles() -> list:
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        if _u32.IsWindowVisible(h):
            n = _u32.GetWindowTextLengthW(h)
            if n:
                b = ctypes.create_unicode_buffer(n + 1)
                _u32.GetWindowTextW(h, b, n + 1)
                out.append(b.value)
        return True
    _u32.EnumWindows(cb, 0)
    return out


def has_window(*words) -> bool:
    t = " | ".join(window_titles()).lower()
    return any(w.lower() in t for w in words)


def volume() -> int:
    try:
        from pycaw.pycaw import AudioUtilities
        dev = AudioUtilities.GetSpeakers()
        vol = dev.EndpointVolume
        return int(round(vol.GetMasterVolumeLevelScalar() * 100))
    except Exception:
        try:
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            iface = AudioUtilities.GetSpeakers().Activate(
                IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            v = ctypes.cast(iface, ctypes.POINTER(IAudioEndpointVolume))
            return int(round(v.GetMasterVolumeLevelScalar() * 100))
        except Exception:
            return -1


if __name__ == "__main__":
    print(volume())
    for t in window_titles():
        print(t)
