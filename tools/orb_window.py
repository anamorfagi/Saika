"""ЯДРО НА РАБОЧЕМ СТОЛЕ (2026-08-23).

Маленькое круглое окно без рамки и без фона: в нём та же сцена, что на
главном экране, раздетая до ядра и кольца полосок. Большое окно на это
время спрятано — режим так и называется, «исчезновение».

Управление сделано так, чтобы его не надо было объяснять:
    таскать        зажать и вести — хватать можно за любое место кольца;
    размер         колесо мыши (шар остаётся круглым, окно квадратным);
    вернуть окно   ЩЕЛЧОК ПО САМОМУ ШАРУ — предмет, который человек и так
                   считает главной кнопкой этой программы;
    меню           правая кнопка: вернуть окно, закрыть;
    аварийный ход  Shift+Esc — вернуть окно, если мышь занята.

Щелчок отличается от перетаскивания по пройденному пути (меньше пяти
пикселей) — иначе любое перетаскивание за шар заканчивалось бы выходом из
режима, и таскать было бы нечем.

Положение и размер помнятся в config.json (ui.orb): человек ставит ядро в
свой угол один раз.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG_PATH = ROOT / "config.json"


def _cfg() -> dict:
    try:
        return json.loads(CFG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(x, y, w, h):
    try:
        data = _cfg()
        d = data.setdefault("ui", {}).setdefault("orb", {})
        d.update(x=int(x), y=int(y), w=int(w), h=int(h))
        CFG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    except Exception as e:
        print("не сохранила положение ядра:", e, file=sys.stderr)


def _post(port, path, body=None):
    try:
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", data=data,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception as e:
        print("сервер не ответил на", path, e, file=sys.stderr)
        return {}


def main():
    cfg = _cfg()
    port = 0
    try:
        port = int(os.environ.get("ANAMORF_PORT") or 0)
    except Exception:
        port = 0
    if not port:
        port = int((cfg.get("server") or {}).get("port", 8765))
    orb = ((cfg.get("ui") or {}).get("orb") or {})

    from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, QUrl
    from PySide6.QtGui import QColor

    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)

    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView

    MIN, MAX = 96, 560

    class Orb(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Ядро")
            # Tool — без строки в панели задач: в режиме исчезновения
            # программы там быть не должно вообще, в этом весь режим.
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool
                                | Qt.WindowStaysOnTopHint)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            # И системный фон окна тоже: Windows успевает залить рамку
            # своим цветом до первого кадра страницы — на прозрачном окне
            # это видно как чёрный прямоугольник, который «иногда есть».
            self.setAttribute(Qt.WA_NoSystemBackground, True)
            self.setStyleSheet("background: transparent;")

            w = max(MIN, min(MAX, int(orb.get("w", 190))))
            h = w
            # ВЫДЕРНУЛ РУКОЙ — ЗНАЧИТ, МЕСТО УЖЕ НАЗВАНО (2026-08-23).
            # Человек тянет ядро за внешнее кольцо и кладёт куда хочет;
            # открывать окно в «своём» углу после этого — значит отменить
            # только что сделанное им движение.
            drop = None
            try:
                _xy = os.environ.get("ANAMORF_ORB_XY") or ""
                if "," in _xy:
                    dx, dy = _xy.split(",", 1)
                    drop = (int(dx), int(dy))
            except Exception:
                drop = None
            if drop:
                x, y = drop[0] - w // 2, drop[1] - h // 2
            else:
                x, y = int(orb.get("x", -1)), int(orb.get("y", -1))
            scr = QApplication.primaryScreen().availableGeometry()
            if x < 0 or y < 0 or not any(
                    s.geometry().intersects(QRect(x, y, w, h))
                    for s in QApplication.screens()):
                # первый запуск или окно уехало за отключённый монитор:
                # правый нижний угол — там, где люди держат виджеты
                x = scr.right() - w - 40
                y = scr.bottom() - h - 60
            self.setGeometry(x, y, w, h)

            self.view = QWebEngineView(self)
            self.view.setAttribute(Qt.WA_TranslucentBackground, True)
            self.view.setStyleSheet("background: transparent;")
            self.view.page().setBackgroundColor(QColor(Qt.transparent))
            self.view.settings().setAttribute(
                QWebEngineSettings.ShowScrollBars, False)
            # Микрофон у большого окна, оно спрятано, но живо и слышит.
            # Здесь разрешение всё равно выдаём: страница одна и та же, и
            # молчаливый отказ в правах читался бы как поломка звука.
            try:
                self.view.page().featurePermissionRequested.connect(
                    lambda o, f: self.view.page().setFeaturePermission(
                        o, f, QWebEnginePage.PermissionGrantedByUser))
            except Exception:
                pass

            self._url = QUrl(f"http://127.0.0.1:{port}/?orb=1")
            self._tries = 0

            def _try_load():
                self._tries += 1
                try:
                    with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/api/orb", timeout=1.5):
                        self.view.load(self._url)
                        return
                except Exception:
                    pass
                if self._tries < 120:
                    QTimer.singleShot(1000, _try_load)
                else:
                    print("сервер так и не ответил — ядро осталось пустым",
                          flush=True)

            _try_load()

            lay = QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self.view)

            self._press = None        # где нажали (глобально)
            self._origin = None       # где было окно в момент нажатия
            self._moved = 0.0

            self.view.installEventFilter(self)
            self.view.loadFinished.connect(self._grab_input)
            self.view.loadFinished.connect(self._loaded)

            self.setContextMenuPolicy(Qt.CustomContextMenu)
            self.customContextMenuRequested.connect(self._menu)

            self._beat = QTimer(self)
            self._beat.timeout.connect(self._sync)
            self._beat.start(700)

            # ЖЕСТ НАЧАЛСЯ В ЧУЖОМ ОКНЕ (2026-08-23). Человек зажал кнопку
            # в интерфейсе и потянул ядро наружу; нас в этот момент ещё не
            # существовало. Перехватить чужое нажатие нельзя — оно
            # принадлежит другому процессу. Зато можно честно смотреть,
            # держит он кнопку или уже отпустил: пока держит, едем за
            # курсором, отпустил — остаёмся там, где он нас положил.
            # Так одно движение руки доводится до конца, хотя посередине
            # него сменилось окно.
            self._follow = os.environ.get("ANAMORF_ORB_FOLLOW") == "1" \
                and sys.platform == "win32"
            self._follow_left = 6.0            # не дольше шести секунд
            if self._follow:
                self._ftimer = QTimer(self)
                self._ftimer.timeout.connect(self._follow_cursor)
                self._ftimer.start(16)

        def _follow_cursor(self):
            """Ехать за курсором, пока зажата левая кнопка."""
            self._follow_left -= 0.016
            try:
                import ctypes
                u = ctypes.windll.user32
                held = u.GetAsyncKeyState(0x01) & 0x8000     # VK_LBUTTON
                if not held or self._follow_left <= 0:
                    self._ftimer.stop()
                    self._follow = False
                    _save(self.x(), self.y(), self.width(), self.height())
                    return

                class P(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

                pt = P()
                u.GetCursorPos(ctypes.byref(pt))
                self.move(pt.x - self.width() // 2, pt.y - self.height() // 2)
            except Exception as e:
                print("не смогла поехать за курсором:", e, file=sys.stderr)
                try:
                    self._ftimer.stop()
                except Exception:
                    pass
                self._follow = False

        # ── ввод ──
        def _grab_input(self, *_):
            """Мышь ловим на внутреннем виджете композитора QtWebEngine:
            до родителя события не доходят, это уже проходили с окном
            модели."""
            try:
                fp = self.view.focusProxy()
                if fp:
                    fp.installEventFilter(self)
            except Exception:
                pass

        def eventFilter(self, obj, e):
            t = e.type()
            if t == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
                self._press = e.globalPosition().toPoint()
                self._origin = self.pos()
                self._moved = 0.0
                return True
            # НАВЕДЕНИЕ ОТДАЁМ СТРАНИЦЕ (2026-08-23). Пока мы съедали ВСЕ
            # движения мыши, шар не знал, что на него смотрят: подсветка
            # под курсором не работала, и виджет казался картинкой. Ловим
            # только то, что действительно наше, — движение с зажатой
            # кнопкой, то есть перетаскивание.
            if t == QEvent.MouseMove and self._press is None:
                return False
            if t == QEvent.MouseMove and self._press is not None:
                g = e.globalPosition().toPoint()
                d = g - self._press
                self._moved = max(self._moved, abs(d.x()) + abs(d.y()))
                self.move(self._origin + d)
                return True
            if t == QEvent.MouseButtonRelease and e.button() == Qt.LeftButton \
                    and self._press is not None:
                pt = e.position().toPoint()
                click = self._moved < 5
                self._press = None
                if not click:
                    self._snap_edges()
                _save(self.x(), self.y(), self.width(), self.height())
                if click and self._on_core(pt):
                    self._back()
                return True
            if t == QEvent.Wheel:
                self._zoom(e.angleDelta().y())
                return True
            return super().eventFilter(obj, e)

        def _snap_edges(self):
            """Прилипание к краю экрана — как у пузыря на телефоне.

            Поставить окно РОВНО в угол мышью нельзя: промах в два-три
            пикселя человек не видит, но видит потом, когда рядом окажется
            другое окно. Поэтому у края добираем сами."""
            g = None
            c = self.geometry().center()
            for scr in QApplication.screens():
                if scr.geometry().contains(c):
                    g = scr.availableGeometry()
                    break
            if g is None:
                g = QApplication.primaryScreen().availableGeometry()
            snap, x, y = 24, self.x(), self.y()
            w, h = self.width(), self.height()
            if abs(x - g.left()) < snap:
                x = g.left()
            elif abs((x + w) - g.right()) < snap:
                x = g.right() - w
            if abs(y - g.top()) < snap:
                y = g.top()
            elif abs((y + h) - g.bottom()) < snap:
                y = g.bottom() - h
            if (x, y) != (self.x(), self.y()):
                self.move(x, y)

        def _on_core(self, pt) -> bool:
            """Шар — это середина окна, его 35% (столько же в разметке
            главного экрана: #zcore width:35%). Промах по кольцу — не
            выход из режима, а просто щелчок в пустоту."""
            c = QPoint(self.width() // 2, self.height() // 2)
            r = self.width() * 0.19
            dx, dy = pt.x() - c.x(), pt.y() - c.y()
            return dx * dx + dy * dy <= r * r

        def _zoom(self, delta):
            w = self.width()
            step = max(8, int(w * 0.12)) * (1 if delta > 0 else -1)
            nw = max(MIN, min(MAX, w + step))
            if nw == w:
                return
            # растём от середины: иначе ядро уползает из-под курсора
            c = self.geometry().center()
            self.setGeometry(c.x() - nw // 2, c.y() - nw // 2, nw, nw)
            _save(self.x(), self.y(), nw, nw)

        def keyPressEvent(self, e):
            if e.key() == Qt.Key_Escape and (e.modifiers() & Qt.ShiftModifier):
                self._back()
                return
            super().keyPressEvent(e)

        def _menu(self, pos):
            from PySide6.QtWidgets import QMenu
            m = QMenu(self)
            m.addAction("Вернуть окно", self._back)
            m.addAction("Закрыть ядро", self.close)
            m.exec(self.mapToGlobal(pos))

        # ── связь с сервером ──
        def _loaded(self, ok):
            if not ok:
                print("страница ядра не открылась", file=sys.stderr)
                return
            _post(port, "/api/orb/seen")
            # ЧТО ВНУТРИ ОКНА НА САМОМ ДЕЛЕ (2026-08-23). Окно прозрачное и
            # без рамки: когда в нём что-то не так, снаружи это выглядит
            # как «всратая png», и разбираться приходится по скриншотам.
            # Пусть страница сама скажет, в каком она режиме и что рисует
            # фон, — строкой в logs/orb.log.
            try:
                self.view.page().runJavaScript(
                    "(function(){try{var b=getComputedStyle(document.body);"
                    "var big=[];document.querySelectorAll('body>*').forEach("
                    "function(e){var r=e.getBoundingClientRect();"
                    "if(r.width>40&&r.height>40&&getComputedStyle(e).display"
                    "!=='none')big.push((e.id||e.tagName)+':'+Math.round(r.width)"
                    "+'x'+Math.round(r.height));});"
                    "return JSON.stringify({orb:!!window.ORBMODE,"
                    "bg:b.backgroundColor,big:big});}catch(e){return ''+e;}})()",
                    lambda r: print("страница ядра:", r, flush=True))
            except Exception as e:
                print("не смогла опросить страницу:", e, file=sys.stderr)

        def _back(self):
            """Выйти из режима: сервер вернёт большое окно и закроет нас."""
            _post(port, "/api/orb", {"on": False})
            QTimer.singleShot(1200, self.close)

        def _sync(self):
            """Сервер знает, включён режим или нет. Выключили из
            интерфейса или голосом — закрываемся сами."""
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/orb", timeout=1.5) as r:
                    st = json.loads(r.read().decode() or "{}")
            except Exception:
                return          # сервер молчит — не повод исчезать
            if not st.get("on", True):
                self.close()
            else:
                _post(port, "/api/orb/seen")

    win = Orb()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
