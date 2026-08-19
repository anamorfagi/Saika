"""ПРОЗРАЧНОЕ ОКНО-ПРИЦЕЛ: ВИДНО, КУДА НАЦЕЛЕНО ДЕЙСТВИЕ (2026-08-19).

Владелец: «я не видел подсветку по краям моника, где она работает. Нужно
какое-то прозрачное окно, которое будет визуализировать, куда нацелено её
действие, чтобы оно масштабировалось по размерам окна, где она работает в
текущем моменте».

КАК УСТРОЕНО. Несколько вложенных РАМОК со скруглёнными углами, от яркой
снаружи к еле заметной внутрь — вместе читаются как мягкое свечение.
Каждая рамка — окно, которому вырезана середина настоящей дырой
(SetWindowRgn: región окна = скруглённый прямоугольник МИНУС внутренний).
Дыра — не «прозрачный цвет», который может не сработать, а физическое
отсутствие окна: сквозь неё и видно, и кликается.

⚠️ ТРИ ЗАХОДА, И ВОТ ПОЧЕМУ (2026-08-19).
  1. Одно окно на всю цель с прозрачной серединой через -transparentcolor.
     У владельца фокус не прошёл — ВЕСЬ ЭКРАН стал чёрным поверх всего.
  2. Четыре прямые полосы по краям. Чёрного экрана больше нет, но: углы
     без скруглений, цвет на малой прозрачности читается как «чёрная
     полоса, чуть посветлее», а главное — полосы ЛОВИЛИ МЫШЬ, и с окном
     под ними нельзя было работать («я не могу с ним взаимодействовать,
     оно перекрывает прогу»). Сквозной стиль ставился не тому окну: у
     Tk-окна winfo_id() — это внутреннее окно, а слои и «не ловить мышь»
     живут на его обёртке (GetParent).
  3. Рамки с настоящей дырой и скруглением — то, что здесь. Мышь ловить
     нечему: середины у окна физически нет, а сама рамка помечена
     WS_EX_TRANSPARENT уже на правильном hwnd.

Пока свечение живёт, каждые 100 мс перечитывается прямоугольник цели по
hwnd — человек двигает или растягивает окно, свечение едет и
масштабируется за ним.

ЖИВЁТ ДОЛГО И ГАСНЕТ ПЛАВНО. Владелец: «сделай подсветку затухающей через
некоторое время, скажем в течение 30 секунд — как у тебя в браузерной
версии». Поэтому рамка держится ярко большую часть срока, а последнюю треть
плавно уходит в ноль по прозрачности: заметить успеваешь, надоесть — нет.
Время и цвет настраиваются: pc.highlight_ms, pc.highlight_color.

ПОЧЕМУ ОТДЕЛЬНЫЙ ПОТОК С TK. Qt в проекте занят окном аватара и требует
главного потока (он у uvicorn). Tk держит свой цикл событий там, где
создан, — поэтому здесь свой поток и очередь заданий. Наружу торчит только
show()/show_window()/show_monitor().

Сломается или не найдётся tkinter — молча выключаемся: это украшение, руки
из-за него вставать не должны.
"""
import logging
import queue
import threading
import time

from server.config import CFG

log = logging.getLogger("saika.highlight")

_Q = queue.Queue()
_T = {"thread": None, "dead": False}
GLOW_PX = 100             # ширина свечения по умолчанию, пиксели
BANDS = 5                 # вложенных рамок: больше — мягче градиент


def enabled() -> bool:
    return bool(CFG.get("pc.highlight", True)) and not _T["dead"]


def state() -> dict:
    """Для интерфейса: жива ли подсветка вообще и почему нет."""
    return {"enabled": bool(CFG.get("pc.highlight", True)),
            "dead": _T["dead"],
            "running": bool(_T["thread"] and _T["thread"].is_alive())}


def show(rect, label: str = "", ms: int = 0, color: str = "", hwnd: int = 0):
    """rect — (x, y, w, h). hwnd — если задан, рамка следует за окном."""
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
        log.debug("экрана %s нет среди %s", num,
                  [d["num"] for d in pc_control._mon_info()])
    except Exception as e:
        log.debug("подсветка экрана %s: %s", num, e)


def _ensure():
    if _T["thread"] and _T["thread"].is_alive():
        return
    t = threading.Thread(target=_loop, name="saika-highlight", daemon=True)
    _T["thread"] = t
    t.start()


def _win_rect(hwnd: int):
    """Прямоугольник окна прямо сейчас — чтобы рамка ехала за ним."""
    try:
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(int(hwnd), ctypes.byref(r)):
            return None
        return (r.left, r.top, r.right - r.left, r.bottom - r.top)
    except Exception:
        return None


def _hwnds(win) -> list:
    """Своё окно И его обёртку. У Tk winfo_id() отдаёт ВНУТРЕННЕЕ окно, а
    стили слоя и «не ловить мышь» действуют на верхнем (2026-08-19: из-за
    этого рамка перехватывала клики и с приложением нельзя было работать)."""
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


def _target_radius(hwnd: int) -> int:
    """Скругление САМОЙ цели, чтобы рамка села по её углам (2026-08-19,
    владелец: «нужно, чтобы окно подстраивало скругление под элемент, на
    который смотрит»).

    Windows 11 сама знает, скруглено ли окно: DWMWA_WINDOW_CORNER_PREFERENCE
    отвечает «как обычно» (8пx), «маленькое» (4пx) или «не скруглять».
    Развёрнутое окно углов не имеет вовсе, целый монитор — тем более.
    Windows 10 на этот вопрос не отвечает — там просто нули, и это честно:
    углы там прямые."""
    if not hwnd:
        return 0                       # монитор целиком — углы прямые
    try:
        import ctypes
        user32 = ctypes.windll.user32
        if user32.IsZoomed(int(hwnd)):
            return 0                   # развёрнутое окно не скруглено
        DWMWA_CORNER = 33
        val = ctypes.c_int(0)
        hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            ctypes.c_void_p(int(hwnd)), ctypes.c_uint(DWMWA_CORNER),
            ctypes.byref(val), ctypes.sizeof(val))
        if hr != 0:
            return 0                   # старая Windows — прямые углы
        return {0: 8, 1: 8, 2: 0, 3: 8, 4: 4}.get(int(val.value), 8)
    except Exception as e:
        log.debug("скругление цели не спросилось: %s", e)
        return 0


def _click_through(win):
    """Окно не ловит мышь и не забирает фокус — на ВСЕХ его уровнях."""
    try:
        import ctypes
        GWL_EXSTYLE = -20
        WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x00080000, 0x00000020
        WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x00000080, 0x08000000
        user32 = ctypes.windll.user32
        for h in _hwnds(win):
            cur = user32.GetWindowLongW(h, GWL_EXSTYLE)
            user32.SetWindowLongW(h, GWL_EXSTYLE,
                                  cur | WS_EX_LAYERED | WS_EX_TRANSPARENT
                                  | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
    except Exception as e:
        log.debug("сквозное окно не получилось: %s", e)


def _ring_region(win, w: int, h: int, thick: int, radius: int) -> bool:
    """Вырезать в окне скруглённую рамку: сама рамка есть, середины НЕТ.
    Дыра настоящая — сквозь неё видно и кликается. False — не вышло, и
    тогда рамку лучше не показывать вовсе, чем показать плашкой."""
    try:
        import ctypes
        gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32
        RGN_DIFF = 4
        r = max(0, int(radius))

        def rgn(x1, y1, x2, y2, rad):
            # РОВНО ПРЯМОЙ УГОЛ, КОГДА У ЦЕЛИ ОН ПРЯМОЙ. CreateRoundRectRgn
            # с нулевым эллипсом ведёт себя по-разному на разных сборках —
            # для прямых углов честнее обычный прямоугольник.
            if rad < 3:
                return gdi32.CreateRectRgn(x1, y1, x2, y2)
            return gdi32.CreateRoundRectRgn(x1, y1, x2, y2, rad * 2, rad * 2)

        outer = rgn(0, 0, w + 1, h + 1, r)
        inner = rgn(thick, thick, w - thick + 1, h - thick + 1,
                    max(0, r - thick))
        if not outer or not inner:
            return False
        gdi32.CombineRgn(outer, outer, inner, RGN_DIFF)
        gdi32.DeleteObject(inner)
        ok = False
        for hd in _hwnds(win)[::-1]:          # сперва обёртка
            if user32.SetWindowRgn(hd, outer, True):
                ok = True
                break
        if not ok:
            gdi32.DeleteObject(outer)
        return bool(ok)
    except Exception as e:
        log.debug("рамка-дыра не вырезалась: %s", e)
        return False


def _loop():
    try:
        import tkinter as tk
    except Exception as e:
        _T["dead"] = True
        log.warning("Свечение выключено: нет tkinter (%s). Действия всё "
                    "равно видны в интерфейсе, в блоке «Где я работаю».", e)
        return
    try:
        root = tk.Tk()
        root.withdraw()
        rings = []
        for _ in range(BANDS):
            b = tk.Toplevel(root)
            b.overrideredirect(True)
            b.attributes("-topmost", True)
            b.attributes("-alpha", 0.0)
            b.configure(bg="#ff9a3c")
            b.withdraw()
            rings.append(b)
        cap = tk.Toplevel(root)
        cap.overrideredirect(True)
        cap.attributes("-topmost", True)
        lbl = tk.Label(cap, text="", font=("Segoe UI", 9, "bold"),
                       padx=9, pady=3, fg="#141414", bg="#ff9a3c")
        lbl.pack()
        cap.withdraw()

        st = {"until": 0.0, "shown": False, "hwnd": 0, "rect": None,
              "label": "", "color": "#ff9a3c", "life": 30.0, "fade": 1.0,
              "glow": GLOW_PX}

        def ring_alpha(i: int) -> float:
            """Ярче всего у самой границы окна, дальше внутрь — гаснет.
            Значения выше прежних: на 0.3 тёплый цвет поверх тёмного стола
            читался как «чёрная полоса чуть посветлее»."""
            k = 1.0 - (i / float(BANDS))
            return 0.10 + 0.55 * (k ** 2)

        def place(rect):
            x, y, w, h = rect
            g = max(10, min(int(st["glow"]), w // 4, h // 4))
            t = max(3, g // BANDS)
            # Углы берём у самой цели: у скруглённого окна Windows 11 рамка
            # ляжет по его радиусу, у развёрнутого и у монитора — прямая.
            base_r = _target_radius(st["hwnd"])
            for i, b in enumerate(rings):
                off = i * t
                rw, rh = w - 2 * off, h - 2 * off
                if rw < 3 * t or rh < 3 * t:
                    b.withdraw()
                    continue
                b.geometry(f"{rw}x{rh}+{x + off}+{y + off}")
                b.configure(bg=st["color"])
                b.deiconify()
                b.update_idletasks()
                # СНАЧАЛА ДЫРА, ПОТОМ ПОКАЗ. Не вышло вырезать середину —
                # окно не показываем вовсе: плашка поверх работы хуже, чем
                # отсутствие украшения (см. историю про чёрный экран).
                # у вложенных рамок радиус убывает ровно на отступ —
                # иначе внутренние углы «распухают» и рамка выглядит кривой
                if not _ring_region(b, rw, rh, t, max(0, base_r - off)):
                    b.withdraw()
                    continue
                try:
                    b.attributes("-alpha", ring_alpha(i) * st["fade"])
                except Exception:
                    pass
                b.lift()
                _click_through(b)
            if st["label"]:
                lbl.configure(text=st["label"], bg=st["color"])
                cap.update_idletasks()
                cw = cap.winfo_reqwidth()
                cap.geometry(f"+{x + max(0, (w - cw) // 2)}+{max(0, y + 8)}")
                try:
                    cap.attributes("-alpha", min(1.0, 0.92 * st["fade"]))
                except Exception:
                    pass
                cap.deiconify()
                cap.lift()
                _click_through(cap)
            else:
                cap.withdraw()

        def hide():
            for b in rings:
                b.withdraw()
            cap.withdraw()
            st["shown"] = False

        def apply(job):
            st.update(until=time.time() + job["ms"] / 1000.0, shown=True,
                      life=max(0.5, job["ms"] / 1000.0), fade=1.0,
                      hwnd=job["hwnd"], rect=job["rect"],
                      label=job["label"], color=job["color"],
                      glow=job.get("glow") or GLOW_PX)
            place(job["rect"])

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
                    moved = False
                    if st["hwnd"]:
                        r = _win_rect(st["hwnd"])
                        if r and r != st["rect"] and r[2] > 0 and r[3] > 0:
                            st["rect"] = r
                            moved = True
                    if moved:
                        st["fade"] = f
                        place(st["rect"])
                    elif abs(f - st["fade"]) > 0.03:
                        st["fade"] = f
                        for i, b in enumerate(rings):
                            try:
                                if b.winfo_viewable():
                                    b.attributes("-alpha", ring_alpha(i) * f)
                            except Exception:
                                pass
                        try:
                            cap.attributes("-alpha", min(1.0, 0.92 * f))
                        except Exception:
                            pass
            root.after(100, tick)

        root.after(100, tick)
        log.info("Свечение внимания готово: %d рамок со скруглением, %dпx, "
                 "цвет %s", BANDS, GLOW_PX,
                 CFG.get("pc.highlight_color", "#ff9a3c"))
        root.mainloop()
    except Exception as e:
        _T["dead"] = True
        log.warning("Свечение выключилось: %s", e)
