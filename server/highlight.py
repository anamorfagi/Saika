"""МЯГКОЕ СВЕЧЕНИЕ ВОКРУГ ТОГО, НА ЧТО ОНА СМОТРИТ (2026-08-19).

Владелец: «нужно прозрачное окно, которое визуализирует, куда нацелено её
действие… тоненькая контурная подсветка, оранжевая… градиент так себе,
можно же сделать мягче сглаживание, а не вот эти полоски… и оно почему-то
зашло на первый экран немного».

КАК УСТРОЕНО СЕЙЧАС. ОДНО окно размером с цель, с ПОПИКСЕЛЬНОЙ
прозрачностью (UpdateLayeredWindow, 32-битный ARGB). Альфа каждого пикселя
считается от расстояния до границы: у самого края почти непрозрачно, вглубь
плавно в ноль, дальше контура — ноль. Углы получаются сами собой, потому
что расстояние честное, двумерное: скругление задаётся одной формулой
(signed distance скруглённого прямоугольника) и берётся у самой цели.

⚠️ ПОЧЕМУ НЕ ЧЕТЫРЕ ПОЛОСЫ (2026-08-19, владелец: «почему контуры в углах
прерывисты? Должен быть полностью объединённый контур»). Полосы знают
только своё направление: верхняя гаснет вниз, левая — вправо. В углу обе
уже почти прозрачны, и контур там разрывается. Одно окно с двумерным
расстоянием такой проблемы не имеет.

Побочная выгода: пиксели с нулевой альфой мышь не ловят вообще — по центру
цели можно спокойно работать.

⚠️ ЧЕТЫРЕ ЗАХОДА, И КАЖДЫЙ ЧЕМУ-ТО НАУЧИЛ:
  1. Одно окно на всю цель с -transparentcolor. На машине владельца фокус
     не прошёл — ВЕСЬ ЭКРАН стал чёрным поверх всего.
  2. Прямые полосы с общей прозрачностью. Чёрного экрана нет, но полосы
     ловили мышь: сквозной стиль ставился на winfo_id(), а нужен GetParent.
  3. Вложенные рамки с дырой (SetWindowRgn). Мышь прошла, но всё осталось
     ЧЁРНЫМ: _click_through писал ex-стиль заново вместе с WS_EX_LAYERED,
     а повторная установка этого бита ОБНУЛЯЕТ параметры слоя — окно
     рисуется чёрным, пока никто не позовёт SetLayeredWindowAttributes.
  4. Попиксельная альфа (здесь). Слой задаётся ОДНИМ вызовом
     UpdateLayeredWindow — обнулять нечего, цвет и мягкость на месте.

ГРАНИЦЫ ЭКРАНА. Прямоугольник цели берём через DWMWA_EXTENDED_FRAME_BOUNDS
(видимая рамка), а не GetWindowRect: у окон Windows по краям есть невидимая
рамка изменения размера в несколько пикселей, и по ней свечение заезжало на
соседний монитор. Сверх того прямоугольник подрезается по монитору, на
котором лежит центр цели.

Если что-то из этого не заводится — свечение молча выключается: украшение
не имеет права мешать работе.
"""
import logging
import queue
import threading
import time

from server.config import CFG

log = logging.getLogger("saika.highlight")

_Q = queue.Queue()
_T = {"thread": None, "dead": False}

GLOW_PX = 16              # толщина контура по умолчанию, пиксели


def enabled() -> bool:
    return bool(CFG.get("pc.highlight", True)) and not _T["dead"]


def state() -> dict:
    return {"enabled": bool(CFG.get("pc.highlight", True)),
            "dead": _T["dead"],
            "running": bool(_T["thread"] and _T["thread"].is_alive())}


def show(rect, label: str = "", ms: int = 0, color: str = "", hwnd: int = 0):
    """rect — (x, y, w, h). hwnd — если задан, свечение следует за окном."""
    if not enabled() or not rect:
        return
    try:
        x, y, w, h = (int(v) for v in rect)
    except Exception:
        return
    if w <= 0 or h <= 0:
        return
    _ensure()
    _Q.put({"rect": (x, y, w, h), "label": str(label or "")[:80],
            "ms": int(ms or CFG.get("pc.highlight_ms", 30000)),
            "color": color or str(CFG.get("pc.highlight_color", "#ff9a3c")),
            "glow": int(CFG.get("pc.highlight_glow", GLOW_PX)),
            "hwnd": int(hwnd or 0)})


def show_window(w: dict, label: str = ""):
    if not w:
        return
    show((w.get("x", 0), w.get("y", 0), w.get("w", 0), w.get("h", 0)),
         label or (w.get("title") or "")[:60], hwnd=int(w.get("hwnd") or 0))


def show_monitor(num: int, label: str = ""):
    try:
        from server import pc_control
        for d in pc_control._mon_info():
            if int(d["num"]) == int(num):
                r = d["rect"]
                show((r[0], r[1], r[2] - r[0], r[3] - r[1]),
                     label or f"смотрю: экран {num}")
                return
    except Exception as e:
        log.debug("подсветка экрана %s: %s", num, e)


def _ensure():
    if _T["thread"] and _T["thread"].is_alive():
        return
    t = threading.Thread(target=_loop, name="saika-highlight", daemon=True)
    _T["thread"] = t
    t.start()


# ─────────────────────── геометрия цели ───────────────────────
def _target_radius(hwnd: int) -> int:
    """Скругление САМОЙ цели: у окна Windows 11 — 8 пикселей (или 4 у
    маленьких), у развёрнутого и у монитора — прямой угол. Контур ложится
    по её углам, а не по своим."""
    if not hwnd:
        return 0
    try:
        import ctypes
        if ctypes.windll.user32.IsZoomed(int(hwnd)):
            return 0
        val = ctypes.c_int(0)
        hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            ctypes.c_void_p(int(hwnd)), ctypes.c_uint(33),
            ctypes.byref(val), ctypes.sizeof(val))
        if hr != 0:
            return 0
        return {0: 8, 1: 8, 2: 0, 3: 8, 4: 4}.get(int(val.value), 8)
    except Exception:
        return 0


def _visible_rect(hwnd: int):
    """Видимая рамка окна. GetWindowRect отдаёт её ВМЕСТЕ с невидимой
    границей изменения размера (несколько пикселей с каждой стороны) — из-за
    неё свечение заезжало на соседний экран."""
    try:
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            ctypes.c_void_p(int(hwnd)), ctypes.c_uint(9),   # EXTENDED_FRAME
            ctypes.byref(r), ctypes.sizeof(r))
        if hr == 0 and r.right > r.left and r.bottom > r.top:
            return (r.left, r.top, r.right - r.left, r.bottom - r.top)
        if not ctypes.windll.user32.GetWindowRect(int(hwnd), ctypes.byref(r)):
            return None
        return (r.left, r.top, r.right - r.left, r.bottom - r.top)
    except Exception:
        return None


def _clamp_to_screen(rect):
    """Не вылезать за монитор, на котором лежит центр цели."""
    try:
        from server import pc_control
        x, y, w, h = rect
        cx, cy = x + w // 2, y + h // 2
        for d in pc_control._mon_info():
            mx1, my1, mx2, my2 = d["rect"]
            if mx1 <= cx < mx2 and my1 <= cy < my2:
                nx, ny = max(x, mx1), max(y, my1)
                nw = min(x + w, mx2) - nx
                nh = min(y + h, my2) - ny
                if nw > 8 and nh > 8:
                    return (nx, ny, nw, nh)
                break
    except Exception as e:
        log.debug("подрезка по монитору не вышла: %s", e)
    return rect


# ─────────────────────── рисование ───────────────────────
def _rgb(color: str):
    c = (color or "#ff9a3c").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except Exception:
        return 255, 154, 60


def _alpha_profile(t: float, peak: float):
    """Профиль яркости поперёк контура: 1 у края, мягко в ноль на глубине t."""
    import numpy as np
    d = np.arange(int(t) + 1, dtype=np.float32)
    k = np.clip(1.0 - d / max(1.0, t), 0.0, 1.0)
    return (peak * (k * k * (3.0 - 2.0 * k)) * k).astype(np.float32)


def _contour_bits(w: int, h: int, thick: int, rgb, fade: float,
                  radius: int):
    """Премультиплицированный ARGB всего окна: контур по краю, середина —
    прозрачная дыра.

    СЧИТАЕМ ТОЛЬКО КРАЙ. Честная двумерная формула по всей площади — это
    треть секунды на 1920x1080, а нам надо успевать за движением окна.
    Поэтому стороны заполняются одномерным профилем (быстрое размножение
    строки), и лишь четыре угловых квадрата считаются двумерно — там, где
    контур поворачивает и где полосы когда-то и рвались."""
    import numpy as np
    r, g, b = rgb
    peak = 0.95 * max(0.0, min(1.0, fade))
    t = int(max(1, thick))
    rad = int(max(0, radius))
    prof = _alpha_profile(t, peak)                    # длина t+1

    a = np.zeros((h, w), dtype=np.float32)
    band = min(t + 1, h // 2, w // 2)
    if band > 0:
        col = prof[:band][:, None]                    # сверху вниз
        a[:band, :] = np.maximum(a[:band, :], col)
        a[h - band:, :] = np.maximum(a[h - band:, :], col[::-1])
        row = prof[:band][None, :]
        a[:, :band] = np.maximum(a[:, :band], row)
        a[:, w - band:] = np.maximum(a[:, w - band:], row[:, ::-1])

    # УГЛЫ: двумерное расстояние до скруглённой границы. Квадрат стороной
    # rad + t — больше не нужно, дальше начинается ровная сторона.
    c = min(rad + t + 1, h // 2, w // 2)
    if c > 0:
        yy = np.arange(c, dtype=np.float32)[:, None]
        xx = np.arange(c, dtype=np.float32)[None, :]
        # центр скругления в углу
        dx, dy = np.maximum(rad - xx, 0.0), np.maximum(rad - yy, 0.0)
        d = np.where(rad > 0,
                     rad - np.sqrt(dx * dx + dy * dy),   # внутри скругления
                     np.minimum(xx, yy))
        d = np.where((xx >= rad) | (yy >= rad), np.minimum(xx, yy), d)
        k = np.clip(1.0 - np.maximum(d, 0.0) / float(t), 0.0, 1.0)
        ca = (peak * (k * k * (3.0 - 2.0 * k)) * k).astype(np.float32)
        ca[d < 0] = 0.0                                 # снаружи скругления
        ca[d > t] = 0.0
        a[:c, :c] = ca
        a[:c, w - c:] = ca[:, ::-1]
        a[h - c:, :c] = ca[::-1, :]
        a[h - c:, w - c:] = ca[::-1, ::-1]

    out = np.empty((h, w, 4), dtype=np.uint8)
    out[..., 0] = (b * a).astype(np.uint8)              # премультиплицировано
    out[..., 1] = (g * a).astype(np.uint8)
    out[..., 2] = (r * a).astype(np.uint8)
    out[..., 3] = (a * 255.0).astype(np.uint8)
    return out.tobytes()


def _paint(hwnd: int, x: int, y: int, w: int, h: int, bits: bytes) -> bool:
    """Показать буфер как попиксельно-прозрачное окно."""
    try:
        import ctypes
        from ctypes import wintypes
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", ctypes.c_long),
                        ("biYPelsPerMeter", ctypes.c_long),
                        ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [("BlendOp", ctypes.c_byte),
                        ("BlendFlags", ctypes.c_byte),
                        ("SourceConstantAlpha", ctypes.c_byte),
                        ("AlphaFormat", ctypes.c_byte)]

        hdc_screen = user32.GetDC(0)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight = w, -h        # минус = сверху вниз
        bmi.biPlanes, bmi.biBitCount = 1, 32
        bits_ptr = ctypes.c_void_p()
        gdi32.CreateDIBSection.restype = ctypes.c_void_p
        hbmp = gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), 0,
                                      ctypes.byref(bits_ptr), None, 0)
        if not hbmp:
            raise RuntimeError("CreateDIBSection вернул пусто")
        gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi32.SelectObject.restype = ctypes.c_void_p
        old = gdi32.SelectObject(hdc_mem, hbmp)
        ctypes.memmove(bits_ptr, bits, min(len(bits), w * h * 4))

        pt_dst = wintypes.POINT(x, y)
        size = wintypes.SIZE(w, h)
        pt_src = wintypes.POINT(0, 0)
        blend = BLENDFUNCTION(0, 0, 255, 1)      # AC_SRC_OVER, AC_SRC_ALPHA
        user32.UpdateLayeredWindow.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.POINT),
            ctypes.POINTER(wintypes.SIZE), ctypes.c_void_p,
            ctypes.POINTER(wintypes.POINT), wintypes.DWORD,
            ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
        ok = user32.UpdateLayeredWindow(
            ctypes.c_void_p(hwnd), ctypes.c_void_p(hdc_screen),
            ctypes.byref(pt_dst), ctypes.byref(size),
            ctypes.c_void_p(hdc_mem), ctypes.byref(pt_src), 0,
            ctypes.byref(blend), 2)              # ULW_ALPHA

        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(ctypes.c_void_p(hbmp))
        gdi32.DeleteDC(ctypes.c_void_p(hdc_mem))
        user32.ReleaseDC(0, ctypes.c_void_p(hdc_screen))
        return bool(ok)
    except Exception as e:
        log.debug("попиксельная отрисовка не вышла: %s", e)
        return False


def _hwnds(win) -> list:
    """Своё окно И его обёртку: у Tk winfo_id() отдаёт внутреннее окно, а
    слой и «не ловить мышь» живут на верхнем."""
    out = []
    try:
        import ctypes
        h = int(win.winfo_id())
        out.append(h)
        p = ctypes.windll.user32.GetParent(h)
        if p and int(p) != h:
            out.append(int(p))
    except Exception as e:
        log.debug("hwnd не достался: %s", e)
    return out


def _make_layered(win):
    """Окно: слой + не ловить мышь + не забирать фокус. WS_EX_LAYERED тут
    ставить МОЖНО и нужно — прозрачность мы задаём сами, одним вызовом
    UpdateLayeredWindow, обнулять нечего."""
    try:
        import ctypes
        GWL_EXSTYLE = -20
        WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x00080000, 0x00000020
        WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x00000080, 0x08000000
        need = (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
                | WS_EX_NOACTIVATE)
        user32 = ctypes.windll.user32
        top = _hwnds(win)[-1] if _hwnds(win) else 0
        if not top:
            return 0
        cur = user32.GetWindowLongW(top, GWL_EXSTYLE)
        if cur & need != need:
            user32.SetWindowLongW(top, GWL_EXSTYLE, cur | need)
        return top
    except Exception as e:
        log.debug("слой не получился: %s", e)
        return 0


def _loop():
    try:
        import tkinter as tk
    except Exception as e:
        _T["dead"] = True
        log.warning("Свечение выключено: нет tkinter (%s). Действия видны "
                    "в интерфейсе, в блоке «Где я работаю».", e)
        return
    try:
        root = tk.Tk()
        root.withdraw()
        glass = tk.Toplevel(root)
        glass.overrideredirect(True)
        glass.attributes("-topmost", True)
        glass.geometry("1x1+0+0")
        glass.update_idletasks()
        g_hwnd = _make_layered(glass)
        cap = tk.Toplevel(root)
        cap.overrideredirect(True)
        cap.attributes("-topmost", True)
        lbl = tk.Label(cap, text="", font=("Segoe UI", 9, "bold"),
                       padx=9, pady=3, fg="#141414", bg="#ff9a3c")
        lbl.pack()
        cap.withdraw()

        st = {"until": 0.0, "shown": False, "hwnd": 0, "rect": None,
              "label": "", "color": "#ff9a3c", "life": 30.0, "fade": 1.0,
              "glow": GLOW_PX, "drawn": None}

        def place(rect, fade):
            nonlocal g_hwnd
            x, y, w, h = rect
            t = max(3, min(int(st["glow"]), w // 4, h // 4))
            rad = _target_radius(st["hwnd"])
            glass.geometry(f"{w}x{h}+{x}+{y}")
            glass.deiconify()
            glass.update_idletasks()
            if not g_hwnd:
                g_hwnd = _make_layered(glass)
            bits = _contour_bits(w, h, t, _rgb(st["color"]), fade, rad)
            if not _paint(g_hwnd, x, y, w, h, bits):
                glass.withdraw()
            else:
                glass.lift()
            if st["label"]:
                lbl.configure(text=st["label"], bg=st["color"])
                cap.configure(bg=st["color"])
                cap.update_idletasks()
                cw = cap.winfo_reqwidth()
                cap.geometry(f"+{x + max(0, (w - cw) // 2)}+{max(0, y + 6)}")
                try:
                    cap.attributes("-alpha", min(1.0, 0.92 * fade))
                except Exception:
                    pass
                cap.deiconify()
                cap.lift()
            else:
                cap.withdraw()
            st["drawn"] = (rect, round(fade, 2))

        def hide():
            glass.withdraw()
            cap.withdraw()
            st["shown"] = False

        def apply(job):
            rect = job["rect"]
            if job["hwnd"]:
                rect = _visible_rect(job["hwnd"]) or rect
            rect = _clamp_to_screen(rect)
            st.update(until=time.time() + job["ms"] / 1000.0, shown=True,
                      life=max(0.5, job["ms"] / 1000.0), fade=1.0,
                      hwnd=job["hwnd"], rect=rect, label=job["label"],
                      color=job["color"], glow=job.get("glow") or GLOW_PX)
            place(rect, 1.0)

        def tick():
            try:
                while True:
                    apply(_Q.get_nowait())
            except queue.Empty:
                pass
            except Exception as e:
                log.debug("свечение: %s", e)
            if st["shown"]:
                left = st["until"] - time.time()
                if left <= 0:
                    hide()
                else:
                    span = max(0.5, st["life"] * 0.35)
                    f = 1.0 if left > span else max(0.0, left / span)
                    rect = st["rect"]
                    if st["hwnd"]:
                        r = _visible_rect(st["hwnd"])
                        if r:
                            rect = _clamp_to_screen(r)
                    if st["drawn"] != (rect, round(f, 2)):
                        st["rect"], st["fade"] = rect, f
                        place(rect, f)
            root.after(100, tick)

        root.after(100, tick)
        log.info("Свечение внимания готово: единый контур, попиксельный "
                 "градиент, %dпx, цвет %s",
                 int(CFG.get("pc.highlight_glow", GLOW_PX)),
                 CFG.get("pc.highlight_color", "#ff9a3c"))
        root.mainloop()
    except Exception as e:
        _T["dead"] = True
        log.warning("Свечение выключилось: %s", e)
