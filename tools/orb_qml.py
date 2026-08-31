"""ОКНО ЯДРА НА QML (2026-08-23).

Второй заход. Первый показывал в окне ту же HTML-страницу и уперся в
прозрачность: безрамочное окно с QWebEngineView на Windows отдаёт чёрный
прямоугольник вместо пустоты — известная болячка, из-за которой виджет
выглядел «как всратая png». Здесь веб-движка нет: рисует Qt, а у окна QML
прозрачность штатная — нужен только альфа-буфер и прозрачный цвет окна.

Что окно умеет:
    таскать        за любое место;
    размер         колесо мыши (шар остаётся круглым);
    вернуть окно   щелчок по самому шару;
    меню           правая кнопка;
    аварийный ход  Shift+Esc.

Откуда данные. Виджет ничего не выдумывает: полосы звука и состояния
органов приходят с сервера — по вебсокету /ws (как их видит сам
интерфейс) и по /api/ready раз в полторы секунды. Сервер замолчал — вид
гаснет наполовину, а не притворяется живым.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG_PATH = ROOT / "config.json"
QML = ROOT / "ui" / "orb.qml"
MIN, MAX = 110, 560


def _cfg() -> dict:
    try:
        return json.loads(CFG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(x, y, w, h):
    try:
        d = _cfg()
        d.setdefault("ui", {}).setdefault("orb", {}).update(
            x=int(x), y=int(y), w=int(w), h=int(h))
        CFG_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    except Exception as e:
        print("не сохранила положение ядра:", e, file=sys.stderr)


def _post(port, path, body=None):
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=json.dumps(body or {}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception as e:
        print("сервер не ответил на", path, e, file=sys.stderr)
        return {}


def main():
    cfg = _cfg()
    try:
        port = int(os.environ.get("ANAMORF_PORT") or 0)
    except Exception:
        port = 0
    if not port:
        port = int((cfg.get("server") or {}).get("port", 8765))
    orb = ((cfg.get("ui") or {}).get("orb") or {})

    from PySide6.QtCore import (QObject, QPoint, QRect, Qt, QTimer, QUrl,
                                Slot)
    from PySide6.QtGui import QColor, QGuiApplication, QSurfaceFormat
    from PySide6.QtQuick import QQuickView, QQuickWindow
    # QApplication, а не QGuiApplication: меню правой кнопки живёт в
    # QtWidgets, и на «облегчённом» приложении оно просто не откроется.
    from PySide6.QtWidgets import QApplication

    # АЛЬФА-БУФЕР ДО СОЗДАНИЯ ОКНА, иначе прозрачности не будет ни от
    # какого цвета: сцена просто не умеет хранить прозрачность пикселя.
    fmt = QSurfaceFormat.defaultFormat()
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)
    QQuickWindow.setDefaultAlphaBuffer(True)

    app = QApplication(sys.argv)

    view = QQuickView()
    view.setColor(QColor(0, 0, 0, 0))
    view.setFlags(Qt.FramelessWindowHint | Qt.Tool
                  | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
    view.setResizeMode(QQuickView.SizeRootObjectToView)

    w = max(MIN, min(MAX, int(orb.get("w", 210))))
    # ВЫДЕРНУЛ РУКОЙ — МЕСТО УЖЕ НАЗВАНО. Открывать окно в «своём» углу
    # после этого значит отменить только что сделанное человеком движение.
    drop = None
    try:
        xy = os.environ.get("ANAMORF_ORB_XY") or ""
        if "," in xy:
            a, b = xy.split(",", 1)
            drop = (int(a), int(b))
    except Exception:
        drop = None
    if drop:
        x, y = drop[0] - w // 2, drop[1] - w // 2
    else:
        x, y = int(orb.get("x", -1)), int(orb.get("y", -1))
    scr = QGuiApplication.primaryScreen().availableGeometry()
    if x < 0 or y < 0 or not any(s.geometry().intersects(QRect(x, y, w, w))
                                 for s in QGuiApplication.screens()):
        x, y = scr.right() - w - 40, scr.bottom() - w - 60
    view.setGeometry(x, y, w, w)

    class Bridge(QObject):
        """Всё, что ядро просит у системы: подвинуться, изменить размер,
        вернуть большое окно, показать меню."""

        def __init__(self):
            super().__init__()
            self._follow = os.environ.get("ANAMORF_ORB_FOLLOW") == "1" \
                and sys.platform == "win32"
            self._left = 6.0

        @Slot(float, float)
        def moveBy(self, dx, dy):
            view.setPosition(view.x() + int(dx), view.y() + int(dy))

        @Slot()
        def dropped(self):
            self._snap()
            _save(view.x(), view.y(), view.width(), view.height())

        @Slot(float)
        def zoom(self, delta):
            cur = view.width()
            step = max(10, int(cur * 0.12)) * (1 if delta > 0 else -1)
            nw = max(MIN, min(MAX, cur + step))
            if nw == cur:
                return
            c = QPoint(view.x() + cur // 2, view.y() + cur // 2)
            view.setGeometry(c.x() - nw // 2, c.y() - nw // 2, nw, nw)
            _save(view.x(), view.y(), nw, nw)

        @Slot()
        def back(self):
            _post(port, "/api/orb", {"on": False})
            QTimer.singleShot(1200, app.quit)

        @Slot()
        def menu(self):
            # Меню — списком системы, а не своей рисовкой: человек ждёт
            # тут привычное окно, а не ещё один придуманный виджет.
            try:
                from PySide6.QtWidgets import QMenu
                m = QMenu()
                m.addAction("Вернуть окно", self.back)
                m.addAction("Закрыть ядро", app.quit)
                m.exec()
            except Exception:
                self.back()

        def _snap(self):
            """Прилипание к краю экрана — как у пузыря на телефоне: рукой
            в угол ровно не поставишь, промах в пару пикселей видно потом."""
            g = None
            c = QPoint(view.x() + view.width() // 2,
                       view.y() + view.height() // 2)
            for s in QGuiApplication.screens():
                if s.geometry().contains(c):
                    g = s.availableGeometry()
                    break
            if g is None:
                g = QGuiApplication.primaryScreen().availableGeometry()
            snap, x, y = 24, view.x(), view.y()
            ww, hh = view.width(), view.height()
            if abs(x - g.left()) < snap:
                x = g.left()
            elif abs((x + ww) - g.right()) < snap:
                x = g.right() - ww
            if abs(y - g.top()) < snap:
                y = g.top()
            elif abs((y + hh) - g.bottom()) < snap:
                y = g.bottom() - hh
            if (x, y) != (view.x(), view.y()):
                view.setPosition(x, y)

    bridge = Bridge()
    view.rootContext().setContextProperty("bridge", bridge)
    view.setSource(QUrl.fromLocalFile(str(QML)))
    if view.status() == QQuickView.Error:
        for e in view.errors():
            print("QML:", e.toString(), file=sys.stderr)
        return 2
    view.show()
    _post(port, "/api/orb/seen")

    root = view.rootObject()

    # ── ЖЕСТ, НАЧАТЫЙ В ЧУЖОМ ОКНЕ ──
    # Человек тянул ядро в интерфейсе и вышел за край окна; нас в тот
    # момент ещё не было. Перехватить чужое нажатие нельзя — оно
    # принадлежит другому процессу. Зато видно, держит он кнопку или уже
    # отпустил: пока держит — едем за курсором.
    if bridge._follow:
        def _follow_cursor():
            bridge._left -= 0.016
            try:
                import ctypes
                u32 = ctypes.windll.user32
                if not (u32.GetAsyncKeyState(0x01) & 0x8000) or bridge._left <= 0:
                    ftimer.stop()
                    bridge.dropped()
                    return

                class P(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

                pt = P()
                u32.GetCursorPos(ctypes.byref(pt))
                view.setPosition(pt.x - view.width() // 2,
                                 pt.y - view.height() // 2)
            except Exception as e:
                print("не смогла поехать за курсором:", e, file=sys.stderr)
                ftimer.stop()

        ftimer = QTimer()
        ftimer.timeout.connect(_follow_cursor)
        ftimer.start(16)

    # ── ДАННЫЕ ──
    """Данные берём опросом одной ручки, а не вебсокетом.

    Вебсокет был бы изящнее, но QtWebSockets лежит в отдельном модуле
    PySide6 и на части сборок его просто нет — а виджет без полос звука
    это ровно та «всратая png», от которой мы уходим. Один путь, который
    работает всегда, лучше красивого, который иногда отваливается.
    Опрос адаптивный: пока звучит — двадцать раз в секунду, в тишине —
    впятеро реже. На localhost это дешевле, чем кажется, а разница между
    «живой» и «дёрганый» видна именно здесь."""

    def _poll_live():
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/orb/live", timeout=1.0) as r:
                d = json.loads(r.read().decode() or "{}")
        except Exception:
            root.setProperty("alive", False)
            live.setInterval(400)
            return
        root.setProperty("alive", True)
        b = d.get("b") or []
        half = len(b) // 2
        root.setProperty("bandsOut", b[:half])
        root.setProperty("bandsInn", b[half:])
        root.setProperty("mood", d.get("mood") or "idle")
        live.setInterval(50 if b else 220)

    live = QTimer()
    live.timeout.connect(_poll_live)
    live.start(220)

    def _poll_ready():
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/ready", timeout=1.5) as r:
                root.setProperty("organs", json.loads(r.read().decode()))
            root.setProperty("alive", True)
        except Exception:
            root.setProperty("alive", False)

    ready = QTimer()
    ready.timeout.connect(_poll_ready)
    ready.start(1500)
    _poll_ready()

    def _watch_mode():
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/orb", timeout=1.5) as r:
                st = json.loads(r.read().decode() or "{}")
        except Exception:
            return                     # сервер молчит — не повод исчезать
        if not st.get("on", True):
            app.quit()
        else:
            _post(port, "/api/orb/seen")

    mode = QTimer()
    mode.timeout.connect(_watch_mode)
    mode.start(900)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
