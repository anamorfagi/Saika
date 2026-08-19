"""ПРОЗРАЧНОЕ ОКНО-ПРИЦЕЛ: ВИДНО, КУДА НАЦЕЛЕНО ДЕЙСТВИЕ (2026-08-19).

Владелец: «я не видел подсветку по краям моника, где она работает. Нужно
какое-то прозрачное окно, которое будет визуализировать, куда нацелено её
действие, чтобы оно масштабировалось по размерам окна, где она работает в
текущем моменте».

КАК УСТРОЕНО. Мягкое свечение по краю цели: по каждой стороне несколько
узких полос, от плотной снаружи к почти невидимой внутрь — вместе они
читаются как градиент. Полосы — обычные окна с общей прозрачностью
(-alpha), поэтому чёрного прямоугольника не будет НИКОГДА.

⚠️ ПОЧЕМУ НЕ ОДНО ОКНО НА ВСЮ ЦЕЛЬ (2026-08-19, живой инцидент). Первая
версия накрывала цель одним окном и делала середину прозрачной через
-transparentcolor. На машине владельца этот фокус не прошёл — и весь экран
стал ЧЁРНЫМ, поверх всего: «у меня экран чёрный стал, не подскажешь, в чём
дело». Урок простой: украшение не имеет права закрывать человеку работу,
даже если что-то пошло не так. Полосы по краям физически не могут накрыть
середину, что бы ни случилось с прозрачностью.

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
BANDS = 6                 # полос на сторону: больше — мягче градиент


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


def _click_through(win):
    """Окно не ловит мышь и не забирает фокус."""
    try:
        import ctypes
        GWL_EXSTYLE = -20
        WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x00080000, 0x00000020
        WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x00000080, 0x08000000
        hwnd = int(win.winfo_id())
        user32 = ctypes.windll.user32
        cur = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              cur | WS_EX_LAYERED | WS_EX_TRANSPARENT
                              | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
    except Exception as e:
        log.debug("сквозное окно не получилось: %s", e)


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
        # 4 стороны * BANDS полос. Полоса — крошечное окно с общей
        # прозрачностью: чем ближе к центру, тем прозрачнее.
        strips = []
        for _ in range(4 * BANDS):
            b = tk.Toplevel(root)
            b.overrideredirect(True)
            b.attributes("-topmost", True)
            b.attributes("-alpha", 0.0)
            b.configure(bg="#ff9a3c")
            b.withdraw()
            strips.append(b)
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

        def band_alpha(i: int) -> float:
            """Снаружи плотнее, внутрь — в ноль. Квадратичный спад читается
            глазом как мягкое свечение, линейный — как ступеньки."""
            k = 1.0 - (i / float(BANDS))
            return 0.34 * (k ** 2)

        def place(rect):
            x, y, w, h = rect
            # СВЕЧЕНИЕ НЕ ДОЛЖНО СЪЕДАТЬ МАЛЕНЬКОЕ ОКНО: у окна 200x150 сто
            # пикселей с каждой стороны — это оно целиком. Ограничиваем
            # четвертью меньшей стороны, чтобы середина всегда осталась
            # чистой, что бы ни пришло в rect.
            g = max(8, min(int(st["glow"]), w // 4, h // 4))
            t = max(1, g // BANDS)
            n = 0
            for i in range(BANDS):
                off = i * t
                geo = ((x + off, y + off, max(w - 2 * off, 1), t),      # верх
                       (x + off, y + h - off - t, max(w - 2 * off, 1), t),
                       (x + off, y + off, t, max(h - 2 * off, 1)),      # лево
                       (x + w - off - t, y + off, t, max(h - 2 * off, 1)))
                for gx, gy, gw, gh in geo:
                    b = strips[n]
                    n += 1
                    b.geometry(f"{max(gw, 1)}x{max(gh, 1)}+{gx}+{gy}")
                    b.configure(bg=st["color"])
                    try:
                        b.attributes("-alpha", band_alpha(i) * st["fade"])
                    except Exception:
                        pass
                    b.deiconify()
                    b.lift()
                    _click_through(b)
            if st["label"]:
                lbl.configure(text=st["label"], bg=st["color"])
                cap.update_idletasks()
                cw = cap.winfo_reqwidth()
                cap.geometry(f"+{x + max(0, (w - cw) // 2)}+{max(0, y + 6)}")
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
            for b in strips:
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
                    # ЗАТУХАНИЕ: ярко, пока есть запас, и плавно в ноль на
                    # последней трети срока.
                    span = max(0.5, st["life"] * 0.35)
                    f = 1.0 if left > span else max(0.0, left / span)
                    moved = False
                    if st["hwnd"]:
                        r = _win_rect(st["hwnd"])
                        if r and r != st["rect"] and r[2] > 0 and r[3] > 0:
                            st["rect"] = r
                            moved = True
                    if moved or abs(f - st["fade"]) > 0.03:
                        st["fade"] = f
                        place(st["rect"])
            root.after(100, tick)

        root.after(100, tick)
        log.info("Свечение внимания готово: %d полос, %dпx, цвет %s",
                 len(strips), GLOW_PX, CFG.get("pc.highlight_color", "#ff9a3c"))
        root.mainloop()
    except Exception as e:
        _T["dead"] = True
        log.warning("Свечение выключилось: %s", e)
