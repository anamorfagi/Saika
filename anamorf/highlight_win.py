"""СВЕЧЕНИЕ БЕЗ TKINTER: рамка вокруг окна на голом Win32 (2026-08-23).

ПОЧЕМУ ЭТОТ ФАЙЛ ВООБЩЕ ЕСТЬ. Подсветка «вот в этом окне я сейчас
работаю» была нарисована средствами tkinter — и это нормально для
разработки, где стоит обычный Python. Но клиентская сборка едет на
ВСТРАИВАЕМОМ интерпретаторе, а в нём tkinter нет вовсе: ни модуля, ни
tcl/tk рядом. В живом логе это выглядело одной строкой —

    Свечение выключено: нет tkinter (No module named 'tkinter')

— и владелец справедливо спросил: «почему она не подсвечивает окно, в
каком работает». Ответ был не «сломалось», а «этой возможности в сборке
никогда и не было». Достать tkinter неоткуда: python.org недоступен, а
tkinter из соседней Miniconda собран под другую версию языка и в этот
интерпретатор не встанет.

Поэтому рисуем сами. Окно-слой (WS_EX_LAYERED) с прозрачным ключевым
цветом, поверх всех, не принимающее фокус и не ловящее мышь
(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE) — то есть предмет, который видно,
но которого нет для остального рабочего стола. Никаких зависимостей:
user32 и gdi32 есть на любой Windows.

Интерфейс намеренно повторяет то, что ждёт highlight.py: читаем из его
очереди словари {rect, label, ms, color, glow, hwnd} и держим рамку, пока
не истечёт срок или не придёт новая цель.
"""
from __future__ import annotations

import ctypes
import logging
import queue
import time
from ctypes import wintypes

log = logging.getLogger("saika.highlight")

# ⚠️ СВОЙ ЭКЗЕМПЛЯР БИБЛИОТЕКИ, А НЕ ОБЩИЙ (2026-08-23, живой провал).
# ctypes.windll.user32 — ОДИН объект на весь процесс, и объявленные на нём
# argtypes видны всем. Этот файл объявил типы для GetWindowRect «под себя»,
# а pc_control зовёт ту же функцию со своим RECT — и получил
#     ctypes.ArgumentError: argument 2: expected LP_RECT instead of ...
# Внешне это выглядело так, будто Сайка не умеет двигать окна: «перенеси
# браузер на второй экран» -> «не могу управлять размещением окон между
# мониторами». Ничего она не разучилась — падал вызов, а объяснение
# модель придумывала сама.
# WinDLL создаёт ОТДЕЛЬНЫЙ экземпляр: наши типы остаются нашими.
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# ТИПЫ ОБЪЯВЛЯЕМ ЯВНО (2026-08-23, живой лог: «Win32-слой не поднялся»).
# По умолчанию ctypes считает, что функция возвращает C-шный int — то есть
# 32 бита. На 64-битной Windows дескриптор окна и результат оконной
# процедуры шире, и молчаливое усечение до int32 превращает валидный HWND
# в мусор: CreateWindowExW «удаётся», а работать с этим уже нельзя.
# Ошибка из тех, что не падают, а просто ничего не делают.
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint,
                             wintypes.WPARAM, wintypes.LPARAM)

user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.SetLayeredWindowAttributes.argtypes = [
    wintypes.HWND, wintypes.COLORREF, ctypes.c_ubyte, wintypes.DWORD]
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.BeginPaint.restype = wintypes.HDC
user32.GetWindowRect.argtypes = [wintypes.HWND,
                                 ctypes.POINTER(wintypes.RECT)]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.CreatePen.restype = wintypes.HPEN
gdi32.GetStockObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]

WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_POPUP = 0x80000000
SW_SHOWNOACTIVATE = 4
SW_HIDE = 0
LWA_COLORKEY = 0x00000001
HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
WM_PAINT = 0x000F
WM_DESTROY = 0x0002

# ключевой цвет: этим цветом красим всё, что должно быть насквозь
# прозрачным. Берём не чистый чёрный — чтобы не выесть тёмные пиксели
# самой рамки, если цвет свечения окажется близок к нулю.
KEY = 0x010101


def _rgb(color: str) -> int:
    """«#ff9a3c» -> COLORREF (у Windows порядок байт обратный: 0x00BBGGRR)."""
    c = (color or "").strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except Exception:
        r, g, b = 0xFF, 0x9A, 0x3C
    return (b << 16) | (g << 8) | r


class _Overlay:
    """Одно окно-слой на весь экран цели; рамку рисуем внутри него."""

    def __init__(self):
        self.hwnd = 0
        self.rect = (0, 0, 0, 0)
        self.color = _rgb("#ff9a3c")
        self.glow = 16
        self.label = ""
        self._wndproc = None
        self._cls = None

    # ---------- создание ----------
    def create(self) -> bool:
        def proc(hwnd, msg, wp, lp):
            if msg == WM_PAINT:
                self._paint(hwnd)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wp, lp)

        self._wndproc = WNDPROC(proc)          # держим ссылку: иначе сборщик
        #                                        мусора уберёт колбэк, и
        #                                        Windows вызовет пустоту

        class WNDCLASS(ctypes.Structure):
            _fields_ = [("style", ctypes.c_uint),
                        ("lpfnWndProc", WNDPROC),
                        ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE),
                        ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE),
                        ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR),
                        ("lpszClassName", wintypes.LPCWSTR)]

        wc = WNDCLASS()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
        wc.lpszClassName = "AnamorfGlow"
        wc.hbrBackground = 0
        self._cls = wc
        if not user32.RegisterClassW(ctypes.byref(wc)):
            err = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
            # класс мог остаться от прошлого запуска в этом же процессе —
            # это не беда, продолжаем
            log.debug("класс окна свечения: %s", err)

        self.hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST
            | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            "AnamorfGlow", "anamorf", WS_POPUP,
            0, 0, 10, 10, None, None, wc.hInstance, None)
        if not self.hwnd:
            return False
        # ЦВЕТОВОЙ КЛЮЧ НЕ СТАВИМ (2026-08-23, владелец: «подсветка имеет
        # жёсткие контуры, такого не должно быть»). Ключ — это ответ «да
        # или нет» на каждый пиксель: он либо есть целиком, либо его нет
        # вовсе. Полутонов у него не бывает по построению, поэтому любой
        # градиент превращается в лесенку. Рисуем через UpdateLayeredWindow
        # попиксельной прозрачностью, а эти два способа взаимоисключающие:
        # позовёшь SetLayeredWindowAttributes — и попиксельная выключится.
        return True

    # ---------- рисование ----------
    # СВОЙ КОД РИСОВАНИЯ УДАЛЁН (2026-08-23, владелец: «ты же знаешь, как
    # мы делали в проекте, просто повтори»). Он и правда уже сделан —
    # в highlight.py: попиксельная альфа, профиль яркости поперёк контура,
    # честное двумерное расстояние в углах, скругление от самой цели. Здесь
    # была вторая, худшая версия того же самого — вложенные прямоугольники
    # GDI поверх цветового ключа, то есть заведомо жёсткий край. Второй
    # источник правды в рисовании стоил владельцу ровно того, что он и
    # увидел: одна подсветка мягкая, другая ступеньками.
    def _bits(self, w, h):
        from anamorf import highlight as _hl
        rgb = _hl._rgb(self.color_s)
        t = max(2, min(int(self.glow), w // 4, h // 4))
        return _hl._contour_bits(w, h, t, rgb, 1.0, self.radius)

    def place(self, rect, color, glow, label):
        self.rect = rect
        self.color_s = color or "#ff9a3c"
        self.color = _rgb(self.color_s)
        # ТОНЬШЕ (2026-08-23, владелец: «но сделать чуть тоньше»). Контур
        # показывает, ГДЕ она работает, а не обводит предмет рамкой:
        # тонкая линия со свечением читается как внимание, толстая — как
        # выделение объекта, то есть как чужое действие над ним.
        self.glow = max(2, int(glow or 10))
        self.radius = int(CFG_RADIUS)
        self.label = str(label or "")[:80]
        x, y, w, h = rect
        if w < 8 or h < 8:
            return
        try:
            from anamorf import highlight as _hl
            bits = self._bits(w, h)
            if self.label:
                bits = _with_label(bits, w, h, self.label, self.color)
            _hl._paint(self.hwnd, x, y, w, h, bits)
        except Exception as e:
            log.warning("свечение не нарисовалось: %s", e, exc_info=True)
            return
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, x, y, w, h,
                            SWP_NOACTIVATE | SWP_SHOWWINDOW)

    def hide(self):
        user32.ShowWindow(self.hwnd, SW_HIDE)


# Скругление контура. Настоящий радиус окна умеет спросить highlight.py у
# самой цели (DWM), но здесь мы часто подсвечиваем не окно, а область
# экрана; ровный небольшой радиус выглядит лучше острого угла.
CFG_RADIUS = 10


def _with_label(bits: bytes, w: int, h: int, text: str, rgb) -> bytes:
    """Подпись поверх контура.

    Через PIL, а не GDI: GDI рисует текст без альфы, и на попиксельно
    прозрачном окне буквы вышли бы дырой в свечении. Нет PIL или шрифта —
    молча остаёмся без подписи: контур важнее, и терять его из-за буквы
    нельзя."""
    try:
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return bits
    try:
        font = None
        for p in (r"C:\Windows\Fonts\segoeui.ttf",
                  r"C:\Windows\Fonts\arial.ttf"):
            try:
                font = ImageFont.truetype(p, 15)
                break
            except Exception:
                continue
        if font is None:
            return bits
        lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        pad = 6
        box = d.textbbox((0, 0), text, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        x0, y0 = 14, 12
        # тёмная подложка со скруглением: на светлом окне светлый текст
        # иначе не читается вовсе
        d.rounded_rectangle((x0 - pad, y0 - pad, x0 + tw + pad, y0 + th + pad),
                            radius=8, fill=(12, 14, 20, 190))
        d.text((x0 - box[0], y0 - box[1]), text, font=font,
               fill=(int(rgb[0]), int(rgb[1]), int(rgb[2]), 235))
        lay = np.asarray(lay).astype(np.float32)
        a = lay[..., 3:4] / 255.0
        # премультиплицируем и кладём поверх контура «нормальным» смешением
        top = np.concatenate([lay[..., 2:3] * a, lay[..., 1:2] * a,
                              lay[..., 0:1] * a, lay[..., 3:4]], axis=2)
        base = np.frombuffer(bits, dtype=np.uint8).reshape(h, w, 4)
        base = base.astype(np.float32)
        out = top + base * (1.0 - a)
        return np.clip(out, 0, 255).astype(np.uint8).tobytes()
    except Exception as e:
        log.debug("подпись не нарисовалась: %s", e)
        return bits


def _win_rect(hwnd: int):
    """Где сейчас окно цели — чтобы рамка ехала за ним.

    ВИДИМАЯ РАМКА, А НЕ СЛУЖЕБНАЯ (2026-08-23, владелец: «подсветка по
    краям криво отрабатывает — должна быть внутри рамки приложения»).
    GetWindowRect на Windows 10/11 возвращает прямоугольник ВМЕСТЕ с
    невидимыми полями под тень — примерно по 7 пикселей с трёх сторон.
    Свечение, построенное по нему, висело в воздухе рядом с окном.
    Настоящую видимую границу знает композитор: DWMWA_EXTENDED_FRAME_BOUNDS.
    """
    try:
        r = wintypes.RECT()
        try:
            DWMWA_EXTENDED_FRAME_BOUNDS = 9
            hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                wintypes.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS,
                ctypes.byref(r), ctypes.sizeof(r))
            if hr == 0 and r.right > r.left and r.bottom > r.top:
                return (r.left, r.top, r.right - r.left, r.bottom - r.top)
        except Exception:
            pass
        if user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r)):
            return (r.left, r.top, r.right - r.left, r.bottom - r.top)
    except Exception:
        pass
    return None


def loop(q: "queue.Queue", state: dict):
    """Цикл сторожа: живёт в своём потоке, пока есть что показывать."""
    ov = _Overlay()
    try:
        ok = ov.create()
    except Exception as e:
        ok = False
        log.warning("Свечение: окно-слой не создалось (%s)", e, exc_info=True)
    if not ok:
        state["dead"] = True
        log.warning("Свечение не поднялось: окно-слой не создалось "
                    "(последняя ошибка Windows: %s)",
                    ctypes.get_last_error() if hasattr(ctypes, "get_last_error")
                    else "?")
        return
    log.info("Свечение: рисую сама, без tkinter (Win32-слой)")
    cur = None          # текущее задание
    until = 0.0
    msg = wintypes.MSG()
    while True:
        try:
            job = q.get_nowait()
        except queue.Empty:
            job = None
        if job:
            cur, until = job, time.time() + max(0.5, job["ms"] / 1000.0)
            ov.place(job["rect"], job["color"], job["glow"], job["label"])
        # окно могло переехать или закрыться — рамка обязана следовать
        if cur and cur.get("hwnd"):
            r = _win_rect(int(cur["hwnd"]))
            if r and r != ov.rect and r[2] > 0 and r[3] > 0:
                ov.place(r, cur["color"], cur["glow"], cur["label"])
        if cur and time.time() > until:
            cur = None
            ov.hide()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.04)
