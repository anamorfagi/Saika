"""ПРОЗРАЧНОЕ ОКНО-ПРИЦЕЛ: ВИДНО, КУДА НАЦЕЛЕНО ДЕЙСТВИЕ (2026-08-19).

Владелец: «я не видел подсветку по краям моника, где она работает. Нужно
какое-то прозрачное окно, которое будет визуализировать, куда нацелено её
действие, чтобы оно масштабировалось по размерам окна, где она работает в
текущем моменте».

КАК УСТРОЕНО. Одно окно поверх всех, размером с цель (окно или целый
монитор). Середина ПОЛНОСТЬЮ прозрачная — через -transparentcolor: пиксели
волшебного цвета Windows не рисует и не ловит по ним мышь. Видна только
рамка по краю и подпись, что она делает. Пока подсветка живёт, окно каждые
100 мс перечитывает прямоугольник цели по hwnd и подстраивается — если
человек двигает или масштабирует окно, рамка едет за ним.

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
_MAGIC = "#010203"        # цвет, который Windows делает полностью прозрачным


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
            "color": color or str(CFG.get("pc.highlight_color", "#5ad1ff")),
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
        log.warning("Подсветка выключена: нет tkinter (%s). Действия всё "
                    "равно видны в интерфейсе, в блоке «Где я работаю».", e)
        return
    try:
        root = tk.Tk()
        root.withdraw()
        ov = tk.Toplevel(root)
        ov.overrideredirect(True)
        ov.attributes("-topmost", True)
        try:
            ov.attributes("-transparentcolor", _MAGIC)
        except Exception as e:      # старая Windows/Tk — тогда лёгкий тон
            log.debug("прозрачный цвет недоступен (%s) — беру альфу", e)
        try:
            ov.attributes("-alpha", 1.0)
        except Exception:
            pass
        cv = tk.Canvas(ov, highlightthickness=0, bd=0, bg=_MAGIC)
        cv.pack(fill="both", expand=True)
        ov.withdraw()
        st = {"until": 0.0, "shown": False, "hwnd": 0, "rect": None,
              "label": "", "color": "#5ad1ff", "life": 30.0, "alpha": 1.0}

        def paint(w, h):
            cv.delete("all")
            c = st["color"]
            for i, wide in enumerate((5, 3, 1)):
                cv.create_rectangle(1 + i * 2, 1 + i * 2,
                                    max(2, w - 1 - i * 2),
                                    max(2, h - 1 - i * 2),
                                    outline=c, width=wide)
            if st["label"]:
                pad = 8
                t = cv.create_text(pad + 6, pad + 11, text=st["label"],
                                   anchor="w", fill="#0b0d12",
                                   font=("Segoe UI", 9, "bold"))
                x1, y1, x2, y2 = cv.bbox(t)
                cv.create_rectangle(x1 - 6, y1 - 4, x2 + 6, y2 + 4,
                                    fill=c, outline=c)
                cv.tag_raise(t)

        def place(rect):
            x, y, w, h = rect
            ov.geometry(f"{max(w, 8)}x{max(h, 8)}+{x}+{y}")
            paint(max(w, 8), max(h, 8))

        def apply(job):
            st.update(until=time.time() + job["ms"] / 1000.0, shown=True,
                      life=job["ms"] / 1000.0, alpha=1.0,
                      hwnd=job["hwnd"], rect=job["rect"],
                      label=job["label"], color=job["color"])
            try:
                ov.attributes("-alpha", 1.0)
            except Exception:
                pass
            place(job["rect"])
            ov.deiconify()
            ov.lift()
            _click_through(ov)

        def tick():
            try:
                while True:
                    apply(_Q.get_nowait())
            except queue.Empty:
                pass
            except Exception as e:
                log.debug("подсветка: %s", e)
            if st["shown"]:
                left = st["until"] - time.time()
                if left <= 0:
                    ov.withdraw()
                    st["shown"] = False
                    st["alpha"] = 0.0
                else:
                    # ЗАТУХАНИЕ: ярко, пока есть запас, и плавно в ноль на
                    # последней трети срока.
                    fade = max(0.5, st["life"] * 0.35)
                    a = 1.0 if left > fade else max(0.04, left / fade)
                    if abs(a - st.get("alpha", 1.0)) > 0.02:
                        st["alpha"] = a
                        try:
                            ov.attributes("-alpha", a)
                        except Exception:
                            pass
                if st["shown"] and st["hwnd"]:
                    # ЕДЕТ ЗА ОКНОМ: человек двигает или масштабирует —
                    # рамка обязана оставаться на нём, иначе она врёт.
                    r = _win_rect(st["hwnd"])
                    if r and r != st["rect"] and r[2] > 0 and r[3] > 0:
                        st["rect"] = r
                        place(r)
                        ov.lift()
            root.after(100, tick)

        root.after(100, tick)
        log.info("Подсветка внимания готова (прозрачное окно поверх всех)")
        root.mainloop()
    except Exception as e:
        _T["dead"] = True
        log.warning("Подсветка выключилась: %s", e)
