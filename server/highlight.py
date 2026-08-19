"""ЛЁГКАЯ ПОДСВЕТКА ТОГО, НА ЧТО ОНА СМОТРИТ (2026-08-19).

Владелец: «визуально можно было бы сделать лёгкую подсветку окна, куда она
смотрит и что видит». Смысл ровно тот же, что у курсора мыши: человек
должен видеть, куда направлено внимание, — иначе действия ассистента
выглядят как случайные события на столе.

КАК УСТРОЕНО. Четыре тонкие полоски по краям окна (рамка), поверх всех
окон, полупрозрачные и СКВОЗНЫЕ для мыши: кликнуть в них нельзя, фокус они
не забирают. Плюс маленькая подпись сверху — что именно она сейчас делает.
Через 1.5 секунды всё гаснет само.

ПОЧЕМУ ОТДЕЛЬНЫЙ ПОТОК С TK. Qt в проекте уже занят окном аватара и
требует главного потока (он у uvicorn). Tk свой цикл событий держит в том
потоке, где создан, — поэтому здесь свой поток, своя очередь заданий и
никакого общения с остальным кодом, кроме show().

Если tkinter нет или что-то пошло не так — молча выключаемся: подсветка
это украшение, из-за неё руки останавливаться не должны.
"""
import logging
import queue
import threading
import time

from server.config import CFG

log = logging.getLogger("saika.highlight")

_Q = queue.Queue()
_T = {"thread": None, "dead": False}
THICK = 3                      # толщина рамки, пиксели


def enabled() -> bool:
    return bool(CFG.get("pc.highlight", True)) and not _T["dead"]


def show(rect, label: str = "", ms: int = 0, color: str = ""):
    """rect — (x, y, w, h) в пикселях рабочего стола."""
    if not enabled() or not rect:
        return
    try:
        x, y, w, h = (int(v) for v in rect)
    except Exception:
        return
    if w <= 0 or h <= 0:
        return
    _ensure()
    _Q.put({"rect": (x, y, w, h), "label": str(label or "")[:70],
            "ms": int(ms or CFG.get("pc.highlight_ms", 1600)),
            "color": color or str(CFG.get("pc.highlight_color", "#5ad1ff"))})


def show_window(w: dict, label: str = ""):
    """Подсветить окно из pc_control.windows()."""
    if not w:
        return
    show((w.get("x", 0), w.get("y", 0), w.get("w", 0), w.get("h", 0)),
         label or (w.get("title") or "")[:60])


def show_monitor(num: int, label: str = ""):
    """Подсветить целый экран — когда она снимает кадр монитора."""
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


def _click_through(win):
    """Окно не ловит мышь и не забирает фокус — иначе подсветка мешала бы
    работать ровно тому, ради чего она нарисована."""
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
        log.info("подсветка выключена: нет tkinter (%s)", e)
        return
    try:
        root = tk.Tk()
        root.withdraw()
        parts = []
        for _ in range(4):
            b = tk.Toplevel(root)
            b.overrideredirect(True)
            b.attributes("-topmost", True)
            b.attributes("-alpha", 0.6)
            b.withdraw()
            parts.append(b)
        cap = tk.Toplevel(root)
        cap.overrideredirect(True)
        cap.attributes("-topmost", True)
        cap.attributes("-alpha", 0.85)
        lbl = tk.Label(cap, text="", font=("Segoe UI", 9), padx=8, pady=2,
                       fg="#0b0d12", bg="#5ad1ff")
        lbl.pack()
        cap.withdraw()
        state = {"until": 0.0, "shown": False}

        def hide():
            for b in parts:
                b.withdraw()
            cap.withdraw()
            state["shown"] = False

        def apply(job):
            x, y, w, h = job["rect"]
            c = job["color"]
            # верх, низ, лево, право
            geo = ((x, y, w, THICK), (x, y + h - THICK, w, THICK),
                   (x, y, THICK, h), (x + w - THICK, y, THICK, h))
            for b, (gx, gy, gw, gh) in zip(parts, geo):
                b.configure(bg=c)
                b.geometry(f"{max(gw, 1)}x{max(gh, 1)}+{gx}+{gy}")
                b.deiconify()
                b.lift()
                _click_through(b)
            if job["label"]:
                lbl.configure(text=job["label"], bg=c)
                cap.update_idletasks()
                cw = cap.winfo_reqwidth()
                cap.geometry(f"+{x + max(0, (w - cw) // 2)}+{max(0, y - 26)}")
                cap.deiconify()
                cap.lift()
                _click_through(cap)
            else:
                cap.withdraw()
            state["until"] = time.time() + job["ms"] / 1000.0
            state["shown"] = True

        def tick():
            try:
                while True:
                    apply(_Q.get_nowait())
            except queue.Empty:
                pass
            except Exception as e:
                log.debug("подсветка: %s", e)
            if state["shown"] and time.time() > state["until"]:
                hide()
            root.after(70, tick)

        root.after(70, tick)
        root.mainloop()
    except Exception as e:
        _T["dead"] = True
        log.info("подсветка выключилась: %s", e)
