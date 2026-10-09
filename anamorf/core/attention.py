"""КУДА ОНА СМОТРИТ — РАМКА ВНИМАНИЯ (ядро v2, просьба владельца 09.10).

«Чтобы буквально видеть, куда он смотрит: если в адресную строку — рамка
там; посмотрел на окно — рамка переместилась туда, где дальше действует;
и ровно по окну или области подстраивалась.»

Как устроено: агент-цикл зовёт before() ПЕРЕД каждым инструментом
(рамка встаёт на цель: адресная строка, полоса вкладок, окно, экран) и
after() ПОСЛЕ (рамка переезжает на то, что получилось — окно, которое
теперь впереди). Рисует существующий anamorf/highlight.py: одно окно
с попиксельной прозрачностью, сквозное для мыши, следует за окном.
Точные границы элементов (адресная строка) берём через UI Automation с
жёстким таймаутом; не успели — прикидываем по окну, но рамка будет всегда.
"""
import logging
import re
import threading

log = logging.getLogger("saika.core.attn")

_ADDR = {"web_open", "open_page", "web_search", "web_list", "web_research"}
_TABS = {"tab_control", "tabs_list"}
_PAGE = {"site_search", "click_on", "browser_scroll", "media_control", "close_ad"}
_WIN = {"window_focus", "window_close", "window_minimize", "window_maximize",
        "window_restore", "window_place", "app_launch"}
_COLOR_LOOK, _COLOR_ACT = "#4fd1c5", "#ff9a3c"     # бирюза — смотрит, оранж — действует


def _hl():
    from anamorf import highlight
    return highlight


def _browser():
    try:
        from anamorf import pc_control as pc
        ws = pc.browser_windows()
        return ws[0] if ws else None
    except Exception:
        return None


def _rect_of(hwnd: int):
    try:
        return _hl()._visible_rect(int(hwnd))
    except Exception:
        return None


def _uia_rect(hwnd: int, control_type: str, timeout: float = 1.2):
    """Точный прямоугольник первого элемента типа control_type в окне."""
    box = {}

    def run():
        try:
            from pywinauto import Desktop
            el = Desktop(backend="uia").window(handle=int(hwnd)).child_window(
                control_type=control_type, found_index=0).wrapper_object()
            r = el.rectangle()
            box["r"] = (r.left, r.top, r.width(), r.height())
        except Exception as e:
            box["e"] = e
    t = threading.Thread(target=run, daemon=True, name="attn-uia")
    t.start()
    t.join(timeout)
    return box.get("r")


def _show(rect, label, color, hwnd=0):
    if rect:
        _hl().show(rect, label, color=color, hwnd=hwnd)


def before(name: str, args: dict):
    """Рамка на то, КУДА она сейчас пойдёт."""
    try:
        if not _hl().enabled():
            return
        if name in ("look_screen", "screen_text"):
            mon = args.get("monitor")
            _hl().show_monitor(int(mon) if str(mon).lstrip("-").isdigit() and int(mon) > 0 else 1,
                               "смотрю на экран")
            return
        if name in _ADDR | _TABS | _PAGE:
            w = _browser()
            if not w:
                return
            hwnd = int(w.get("hwnd") or 0)
            wr = _rect_of(hwnd) or (w.get("x"), w.get("y"), w.get("w"), w.get("h"))
            if name in _ADDR:
                r = _uia_rect(hwnd, "Edit") or (wr[0] + 80, wr[1] + 40, max(200, wr[2] - 300), 36)
                _show(r, "адресная строка: " + str(args.get("site") or args.get("url")
                                                   or args.get("query") or "")[:40],
                      _COLOR_ACT, hwnd)
            elif name in _TABS:
                _show((wr[0], wr[1], wr[2], 42), "вкладки", _COLOR_LOOK, hwnd)
            else:
                _show((wr[0], wr[1] + 80, wr[2], max(100, wr[3] - 80)),
                      "страница", _COLOR_ACT, hwnd)
            return
        if name in _WIN:
            m = str(args.get("match") or args.get("name") or "").lower()
            if not m:
                return
            from anamorf import pc_control as pc
            for w in pc.windows(include_minimized=False):
                if m in str(w.get("title", "")).lower() or m in str(w.get("proc", "")).lower():
                    _hl().show_window(w, name + ": " + m[:30])
                    return
    except Exception as e:
        log.debug("рамка до %s: %s", name, e)


_FAIL = re.compile(r"^\s*(отказ|ошибка|не\s|нет\s|кадр не|нужно подтверждение)", re.I)


def after(name: str, args: dict, result: str):
    """Рамка на то, ЧТО получилось: окно, которое теперь впереди."""
    try:
        if not _hl().enabled() or name in ("calc", "memory_recall", "memory_about",
                                           "recall_thread", "tool_help", "where_am_i",
                                           "look_screen", "volume_set"):
            return
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        r = _rect_of(hwnd)          # своё окно (подпись рамки) -> None
        if not r and name in _ADDR | _TABS | _PAGE:
            w = _browser()
            if w:
                hwnd = int(w.get("hwnd") or 0)
                r = _rect_of(hwnd)
        if not r:
            return
        ok = not _FAIL.search(str(result or ""))
        _show(r, ("✓ " if ok else "✗ ") + name, _COLOR_LOOK if ok else "#e05050", hwnd)
    except Exception as e:
        log.debug("рамка после %s: %s", name, e)
