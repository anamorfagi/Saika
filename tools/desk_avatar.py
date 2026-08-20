"""ОКНО С МОДЕЛЬЮ НА РАБОЧЕМ СТОЛЕ (2026-08-14).

Прозрачное окно без рамки, в нём — та же VRM-модель, что и в интерфейсе.
Панель в интерфейсе при этом живёт своей жизнью и ничего не теряет: это
ДОПОЛНИТЕЛЬНОЕ окно, а не переезд.

Управление:
    перетаскивание   мышью за саму модель (рамки нет)
    масштаб          колесо мыши, пропорции сохраняются
    поверх всех      кнопка в интерфейсе Сайки
    замок движения   кнопка в интерфейсе: поставил куда надо — зафиксировал,
                     дальше окно не сдвинуть и не отмасштабировать случайно
    закрыть          той же кнопкой в интерфейсе

Почему кнопки в интерфейсе, а не только в меню окна: владелец расставляет
модель мышью, а фиксирует уже не целясь — тянуться правой кнопкой к
прозрачному окну ровно в тот момент, когда оно наконец стоит как надо,
неудобно и легко сбить.

Состояние окно забирает само, опрашивая /api/avatar/desk раз в полсекунды.
Это проще любого IPC и переживает перезапуск сервера.

ПРОЗРАЧНОСТЬ собирается из трёх слоёв, без любого будет чёрный прямоугольник:
  1. окно     — FramelessWindowHint + WA_TranslucentBackground;
  2. страница — QWebEnginePage.setBackgroundColor(Qt.transparent);
  3. сцена    — three.js уже умеет (alpha:true, setClearAlpha(0)); нужен
                адрес БЕЗ параметра bg, тогда фон канваса пустой.
"""
import importlib.util
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG_PATH = ROOT / "config.json"


def _load_slots():
    """anamorf/desk_slots.py — общая с сервером память окна для каждой модели.

    Загружаем ФАЙЛОМ, а не «from anamorf import ...»: пакет server тянет за
    собой торч, голоса и полминуты запуска, а окну нужны оттуда четыре
    чистых функции. Не нашёлся — работаем как раньше, по общим полям."""
    try:
        spec = importlib.util.spec_from_file_location(
            "saika_desk_slots", ROOT / "anamorf" / "desk_slots.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    except Exception as e:
        print("нет памяти по моделям:", e, file=sys.stderr)
        return None


SLOTS = _load_slots()


def _model_key(cfg: dict) -> str:
    m = ((cfg.get("avatar") or {}).get("web") or {}).get("model", "")
    return SLOTS.key_of(m) if SLOTS else "default"


def _cfg() -> dict:
    try:
        return json.loads(CFG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_geometry(x, y, w, h):
    """Запомнить, где человек её поставил — для ЭТОЙ модели.

    2026-08-14, владелец: «добавь запоминание размера окна, положения
    модельки, как в прошлый раз оно было запущено, также для всех
    моделей». Раньше запись была одна на всех, и переодевание аватара
    сбрасывало подогнанную рамку. Пишем в слот модели и, как и прежде, в
    общие поля — они остаются «как было в прошлый раз вообще»."""
    try:
        data = _cfg()
        d = data.setdefault("avatar", {}).setdefault("desk", {})
        geom = dict(x=int(x), y=int(y), w=int(w), h=int(h))
        if SLOTS:
            SLOTS.remember(d, _model_key(data), geom=geom)
        else:
            d.update(geom)
        CFG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    except Exception as e:
        print("не сохранила положение:", e, file=sys.stderr)


def _now():
    return time.monotonic()


def main():
    cfg = _cfg()
    port = int((cfg.get("server") or {}).get("port", 8765))
    desk = ((cfg.get("avatar") or {}).get("desk") or {})

    from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, QUrl
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

    # атрибуты OpenGL — строго ДО создания QApplication, иначе QtWebEngine
    # поднимет свой контекст и проигнорирует их
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)

    from PySide6.QtWebEngineCore import QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView

    class Desk(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Сайка")
            # Tool — не занимать место на панели задач: это не программа,
            # с которой переключаются, это она сама на столе
            self._base_flags = (Qt.FramelessWindowHint | Qt.Tool)
            self.setWindowFlags(self._base_flags | Qt.WindowStaysOnTopHint)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            # ГЕОМЕТРИЯ МОГЛА ОСТАТЬСЯ ОТ ДРУГОГО МОНИТОРА (2026-08-14).
            # Координаты копятся в конфиге; отключили второй экран — и окно
            # честно открывается на x=1415, то есть в пустоте. Со стороны
            # это выглядит как «кнопка не работает»: процесс живой, окно
            # есть, видеть его негде. Проверяем, попадает ли прямоугольник
            # хоть на один экран, и если нет — ставим по центру основного.
            g0 = (SLOTS.geom_for(desk, _model_key(cfg)) if SLOTS else {})
            x, y = int(g0.get("x", desk.get("x", 60))), \
                int(g0.get("y", desk.get("y", 120)))
            w, h = int(g0.get("w", desk.get("w", 360))), \
                int(g0.get("h", desk.get("h", 620)))
            from PySide6.QtCore import QRect
            want = QRect(x, y, w, h)
            visible = any(scr.geometry().intersects(want)
                          for scr in QApplication.screens())
            if not visible:
                g = QApplication.primaryScreen().availableGeometry()
                x = g.center().x() - w // 2
                y = max(g.top() + 20, g.center().y() - h // 2)
                print(f"окно уехало за экраны — ставлю по центру ({x},{y})",
                      file=sys.stderr)
            self.setGeometry(x, y, w, h)

            # ПРОЗРАЧНОСТЬ СОБИРАЕТСЯ ИЗ ЧЕТЫРЁХ МЕСТ, и чёрный фон в окне
            # означал, что одного из них не хватило: мало объявить окно
            # полупрозрачным — виджеты рисуют свою подложку сами, пока им
            # не сказать обратного таблицей стилей.
            self.setStyleSheet("background: transparent;")
            self.view = QWebEngineView(self)
            self.view.setAttribute(Qt.WA_TranslucentBackground, True)
            self.view.setStyleSheet("background: transparent;")
            self.view.page().setBackgroundColor(QColor(Qt.transparent))
            self.view.settings().setAttribute(
                QWebEngineSettings.ShowScrollBars, False)
            # desk=1 прячет кнопки и подсказку внутри страницы; параметр bg
            # НЕ передаём — именно его отсутствие включает прозрачный фон
            # АДРЕС СТРАНИЦЫ — /avatar, А НЕ /avatar.html (2026-08-14,
            # живой промах: окно открылось честно, прозрачное и поверх
            # всего, и показало {"detail":"Not Found"}. Сервер отдаёт файл
            # по маршруту /avatar; имени файла в URL нет вообще.)
            self.view.load(QUrl(f"http://127.0.0.1:{port}/avatar?desk=1"))

            lay = QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self.view)

            self._drag = None
            self._lock = bool(desk.get("lock", False))
            self._frame = bool(desk.get("frame", True))
            self._edge = None          # какой край тянем сейчас
            self._spanned = False
            self._model = _model_key(cfg)   # чья настройка сейчас в окне
            self._mid0 = None          # начало жеста средней кнопкой
            self._top = True
            self._snap = 18            # прилипание к краям экрана

            # ЛОВИТЬ МЫШЬ НАДО НА ВНУТРЕННЕМ ВИДЖЕТЕ: QtWebEngine рисует
            # страницу в дочернем окне композитора, и до родителя события
            # не доходят. Настоящий получатель — focusProxy(), и он
            # появляется только после загрузки страницы.
            self.view.installEventFilter(self)
            self.view.loadFinished.connect(self._grab_input)

            self.view.loadFinished.connect(self._loaded)

            # ПРАВАЯ КНОПКА = «ЗАКРЫТЬ» (2026-08-14). Второй выход, не
            # зависящий от сервера: пока окно ловит мышь (замок снят), его
            # можно закрыть прямо на месте, не идя в интерфейс.
            self.setContextMenuPolicy(Qt.CustomContextMenu)
            self.customContextMenuRequested.connect(self._menu)

            self._lost = 0.0        # когда сервер замолчал
            self._rescued = False
            self._poll = QTimer(self)
            self._poll.timeout.connect(self._sync)
            # 250 мс вместо 500: между щелчком и эффектом человек не должен
            # успевать подумать «нажалось ли». Запрос локальный и дешёвый —
            # заметно дешевле, чем ощущение неотзывчивости.
            self._poll.start(250)

        def _menu(self, pos):
            from PySide6.QtWidgets import QMenu
            m = QMenu(self)
            m.addAction("Закрыть окно", self.close)
            m.addAction("Показать рамку", lambda: setattr(self, "_frame", True))
            m.exec(self.mapToGlobal(pos))

        def keyPressEvent(self, e):
            # Esc с зажатым Shift — намеренное сочетание: случайный Esc
            # окно не уронит, а выход есть даже когда мышь занята
            if e.key() == Qt.Key_Escape and (e.modifiers() & Qt.ShiftModifier):
                self.close()
                return
            super().keyPressEvent(e)

        def resizeEvent(self, e):
            # МОДЕЛЬ ОБРЕЗАЛАСЬ ПРИ ДРУГИХ ПРОПОРЦИЯХ ОКНА. Панель в
            # интерфейсе почти квадратная, а окно на столе узкое и высокое —
            # кадр, подобранный под одно, во втором режет ноги. Просим
            # страницу пересобрать вид под фактический размер.
            super().resizeEvent(e)
            try:
                self.view.page().runJavaScript(
                    "window.saikaFit && window.saikaFit()")
            except Exception:
                pass

        def _loaded(self, ok):
            # СТРАНИЦА НЕ ОТКРЫЛАСЬ — СКАЗАТЬ ЭТО, А НЕ ВИСЕТЬ ПУСТЫМ
            # ПРЯМОУГОЛЬНИКОМ. Прозрачное окно с ошибкой внутри выглядит
            # как «ничего не произошло», и человек ищет несуществующую
            # кнопку вместо того, чтобы прочитать причину.
            if not ok:
                print("страница аватара не открылась", file=sys.stderr)
                return
            # ВОССТАНАВЛИВАЕМ, А НЕ ПОДГОНЯЕМ: если человек уже настроил
            # масштаб, слепой saikaFit сбросил бы его при каждом открытии
            self.view.page().runJavaScript(
                "window.saikaRestore && window.saikaRestore()")

        def _apply_lock(self, on: bool):
            """СКВОЗНОЕ ОКНО ПО-НАСТОЯЩЕМУ (2026-08-14, второй заход).

            Первая версия ставила Qt.WA_TransparentForMouseEvents — и замок
            честно не работал: владелец «кнопка блокировки опять нихуя не
            блокирует перемещение окна и не даёт возможность нажимать за
            ней». Атрибут внутренний, он говорит ЦИКЛУ СОБЫТИЙ QT не
            доставлять мышь этому виджету. Но окно верхнего уровня — это
            настоящее окно Windows, и клики ему раздаёт система, а она про
            флаги Qt не знает вообще. Нужен расширенный стиль окна:
            WS_EX_TRANSPARENT выключает попадание курсора при проверке
            «кто под мышью», WS_EX_LAYERED обязателен рядом с ним."""
            self.setAttribute(Qt.WA_TransparentForMouseEvents, on)
            if sys.platform != "win32":
                return
            try:
                import ctypes
                GWL_EXSTYLE = -20
                WS_EX_TRANSPARENT, WS_EX_LAYERED = 0x20, 0x80000
                u = ctypes.windll.user32
                hwnd = int(self.winId())
                get = getattr(u, "GetWindowLongPtrW", u.GetWindowLongW)
                setf = getattr(u, "SetWindowLongPtrW", u.SetWindowLongW)
                get.restype = ctypes.c_longlong
                setf.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                 ctypes.c_longlong]
                st = int(get(hwnd, GWL_EXSTYLE))
                st = (st | WS_EX_TRANSPARENT | WS_EX_LAYERED) if on \
                    else (st & ~WS_EX_TRANSPARENT)
                setf(hwnd, GWL_EXSTYLE, st)
                print(f"замок {'поставлен' if on else 'снят'}: "
                      f"ex-style 0x{st:X}", file=sys.stderr)
            except Exception as e:
                print("не смогла переключить сквозной режим:", e,
                      file=sys.stderr)

        # ── ОКНО БЕЗ СЕРВЕРА ОБЯЗАНО ЗАКРЫВАТЬСЯ ──────────────────────
        # 2026-08-14, владелец: «окно не могу закрыть, если система не
        # запущена». И он прав: мы сами сделали окно без рамки, без
        # крестика и без строки в панели задач (Qt.Tool), а единственную
        # кнопку «закрыть» положили в интерфейс — который живёт на
        # сервере. Сервер упал — и на столе висит вещь, которую нечем
        # взять: ни мышью (при замке она вообще сквозная), ни с панели
        # задач, ни правой кнопкой. Только диспетчер задач.
        #
        # Лечим в два шага, а не одним «сразу закрыться»: перезапуск
        # сервера — дело нормальное, и терять из-за него расставленное
        # окно обидно.
        #   через ~8 с молчания — окно становится ОБЫЧНЫМ: рамка, заголовок,
        #     крестик, строка в панели задач, замок снят. Его видно и можно
        #     закрыть руками, как любое другое.
        #   через ~90 с — закрывается само: сервера нет, показывать нечего.
        GRAB_S, GIVEUP_S = 8.0, 90.0

        def _orphan(self):
            now = _now()
            if not getattr(self, "_lost", 0.0):
                self._lost = now
                return
            gone = now - self._lost
            if gone > self.GIVEUP_S:
                print("сервера нет %.0f с — закрываюсь" % gone,
                      file=sys.stderr)
                self.close()
                QApplication.quit()
                return
            if gone > self.GRAB_S and not getattr(self, "_rescued", False):
                self._rescued = True
                print("сервера нет — показываю рамку, чтобы окно можно "
                      "было закрыть руками", file=sys.stderr)
                self._frame = True
                self._lock = False
                try:
                    self._apply_lock(False)
                except Exception:
                    pass
                self.setWindowFlags(Qt.Window | Qt.WindowTitleHint
                                    | Qt.WindowCloseButtonHint
                                    | Qt.WindowMinimizeButtonHint)
                self.setWindowTitle("Сайка — сервер не отвечает, окно можно "
                                    "закрыть")
                self.show()
                self.raise_()

        def _apply_slot(self, key):
            """Поставить окно так, как эта модель стояла в прошлый раз."""
            if not SLOTS:
                return
            desk = ((_cfg().get("avatar") or {}).get("desk") or {})
            g = SLOTS.geom_for(desk, key)
            if g and not self._spanned:
                from PySide6.QtCore import QRect
                want = QRect(int(g.get("x", self.x())),
                             int(g.get("y", self.y())),
                             int(g.get("w", self.width())),
                             int(g.get("h", self.height())))
                if any(scr.geometry().intersects(want)
                       for scr in QApplication.screens()):
                    self.setGeometry(want)
            # страницу перечитываем: сама модель и её масштаб живут там,
            # а вид она возьмёт из того же слота через /api/avatar/desk
            self.view.reload()

        def _span_all(self):
            """Растянуть окно на объединение всех экранов."""
            g = None
            for scr in QApplication.screens():
                r = scr.geometry()
                g = r if g is None else g.united(r)
            if g is not None:
                self.setGeometry(g)
                _save_geometry(g.x(), g.y(), g.width(), g.height())
                self.view.page().runJavaScript(
                    "window.saikaFit && window.saikaFit()")

        def _grab_input(self, ok=True):
            fp = self.view.focusProxy()
            if fp is not None:
                fp.installEventFilter(self)

        # ── что нажали в интерфейсе ──
        def _sync(self):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/avatar/desk",
                        timeout=1.5) as r:
                    st = json.load(r)
            except Exception as e:
                # сервер перезапускается — не паникуем, но и не молчим:
                # немой опрос выглядит как «кнопки не работают»
                if not getattr(self, "_sync_warned", False):
                    self._sync_warned = True
                    print("не читаю состояние с сервера:", e, file=sys.stderr)
                self._orphan()
                return
            self._sync_warned = False
            self._lost = 0.0
            # ПЕРЕОДЕЛИСЬ — БЕРЁМ ЕЁ РАМКУ (2026-08-14). Библиотека
            # аватаров меняет модель на лету, а окно про это не знало и
            # оставалось в размерах прошлой: высокая помещалась, чиби
            # висела в воздухе, спрайт растягивался. Теперь сервер отдаёт
            # ключ модели, и на смену окно подтягивает её собственные
            # размеры с положением и перечитывает страницу.
            mk = st.get("model")
            if mk and mk != self._model:
                self._model = mk
                self._apply_slot(mk)
            # ЗАМОК = ОКНО ПЕРЕСТАЁТ СУЩЕСТВОВАТЬ ДЛЯ МЫШИ (2026-08-14).
            # Владелец: «блокировка должна по идее блокировать в целом
            # нажатие на это окно, чтобы я за ней мог нажимать на экране».
            # Сначала я развёл это на две кнопки — замок отдельно, сквозной
            # режим отдельно — и получил ровно ту путаницу, о которой он
            # написал раньше («блокировка работает наоборот»): при снятом
            # замке окно не двигалось, потому что был включён второй режим.
            # Одно понятие — одна кнопка: поставил замок, и она стала
            # картинкой на столе, сквозь которую можно работать.
            # СЦЕНА НА ВСЕ ЭКРАНЫ (2026-08-14, замысел владельца: «когда
            # рамка выключена и вместе с блокировкой — это даст нужный
            # эффект, когда я ей дам например область сразу двух экранов,
            # чтобы она могла перемещаться вправо-влево по экранам»).
            # Окно становится во всю ширину рабочего стола, прозрачное и
            # не ловящее мышь, — и модель внутри него свободно ходит из
            # монитора в монитор, ничего не перекрывая.
            if st.get("span") and not self._spanned:
                self._spanned = True
                self._span_all()
            elif not st.get("span") and self._spanned:
                self._spanned = False
            self._frame = bool(st.get("frame", True))
            lock = bool(st.get("lock"))
            if lock != self._lock:
                self._lock = lock
                self._apply_lock(lock)
            top = bool(st.get("top", True))
            if top != self._top:
                self._top = top
                self.setWindowFlags(self._base_flags
                                    | (Qt.WindowStaysOnTopHint if top else
                                       Qt.Widget))
                self.show()

        # ── перетаскивание за модель, как у Live2D-маскота ──
        _EDGE = 14                 # ширина чувствительной полосы у края

        def _edge_at(self, pos):
            """У какого края курсор: 'l','r','t','b' и их пары, или None."""
            if not self._frame:
                return None
            x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
            e = self._EDGE
            s = ("t" if y < e else "b" if y > h - e else "")
            s += ("l" if x < e else "r" if x > w - e else "")
            return s or None

        def _press(self, e):
            if self._lock:
                return
            if e.button() != Qt.LeftButton:
                return
            self._edge = self._edge_at(e.position().toPoint())
            self._drag = e.globalPosition().toPoint() - self.pos()
            self._geo0 = self.geometry()

        def _move(self, e):
            if self._lock:
                return
            # курсор подсказывает, что край потянется — иначе о такой
            # возможности никто не догадается
            if self._drag is None:
                ed = self._edge_at(e.position().toPoint())
                self.setCursor({None: Qt.ArrowCursor,
                                "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
                                "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
                                "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
                                "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor
                                }.get(ed, Qt.ArrowCursor))
                return
            if not (e.buttons() & Qt.LeftButton):
                return
            if self._edge:
                g, gp = self._geo0, e.globalPosition().toPoint()
                l, t, r, b = g.left(), g.top(), g.right(), g.bottom()
                if "l" in self._edge:
                    l = min(gp.x(), r - 160)
                if "r" in self._edge:
                    r = max(gp.x(), l + 160)
                if "t" in self._edge:
                    t = min(gp.y(), b - 160)
                if "b" in self._edge:
                    b = max(gp.y(), t + 160)
                self.setGeometry(l, t, r - l, b - t)
                return
            pos = e.globalPosition().toPoint() - self._drag
            # ПРИЛИПАНИЕ К КРАЮ: мышью попасть точно в угол трудно, а ставят
            # её туда почти всегда — последние пиксели окно доходит само
            scr = self.screen().availableGeometry()
            x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
            if abs(x - scr.left()) < self._snap:
                x = scr.left()
            if abs(x + w - scr.right()) < self._snap:
                x = scr.right() - w
            if abs(y - scr.top()) < self._snap:
                y = scr.top()
            if abs(y + h - scr.bottom()) < self._snap:
                y = scr.bottom() - h
            self.move(QPoint(x, y))

        def _release(self, e):
            if self._drag is None:
                return
            self._drag = None
            self._edge = None
            g = self.geometry()
            _save_geometry(g.x(), g.y(), g.width(), g.height())

        def _wheel(self, e):
            """КОЛЕСО МАСШТАБИРУЕТ МОДЕЛЬ, А НЕ ОКНО (2026-08-14).

            Было наоборот: колесо меняло размер окна, и оно росло от левого
            верхнего угла — то есть уезжало вбок, а модель внутри оставалась
            прежней. Владелец: «максимум что должно оно делать — это
            масштабировать модельку внутри него». Так и есть: размер окна
            задаётся один раз, за края рамки, а колесом человек подгоняет
            саму фигуру. Событие просто отдаём странице — она это умеет,
            там тот же обработчик, что и в панели интерфейса."""
            return

        def eventFilter(self, obj, ev):
            if obj is not self.view and obj is not self.view.focusProxy():
                return super().eventFilter(obj, ev)
            t = ev.type()
            # СРЕДНЮЮ КНОПКУ ВЕДЁМ САМИ (2026-08-14: «блядь, чё я в окне её
            # сместить не могу»). Между мышью и страницей здесь стоит
            # QtWebEngine со своим Chromium, и середина доезжала до страницы
            # не всегда — её перехватывает то автопрокрутка, то композитор.
            # Гадать, кто именно, можно долго. Qt эти события получает
            # гарантированно (левой кнопкой окно двигается), поэтому ловим
            # их здесь и передаём странице напрямую вызовом saikaNudge.
            if t in (QEvent.MouseButtonPress, QEvent.MouseMove,
                     QEvent.MouseButtonRelease) and not self._lock:
                mid = (ev.buttons() & Qt.MiddleButton) or \
                      (t != QEvent.MouseMove and ev.button() == Qt.MiddleButton)
                if mid:
                    pos = ev.globalPosition().toPoint()
                    if t == QEvent.MouseButtonPress:
                        self._mid0 = pos
                        return True
                    if t == QEvent.MouseButtonRelease:
                        self._mid0 = None
                        self.view.page().runJavaScript(
                            "window.saikaNudge && "
                            "window.saikaNudge(0,0,0,0,0,1)")
                        return True
                    if self._mid0 is not None:
                        d = pos - self._mid0
                        self._mid0 = pos
                        m = ev.modifiers()
                        self.view.page().runJavaScript(
                            "window.saikaNudge && window.saikaNudge("
                            f"{d.x()},{d.y()},"
                            f"{1 if m & Qt.AltModifier else 0},"
                            f"{1 if m & Qt.ControlModifier else 0},"
                            f"{1 if m & Qt.ShiftModifier else 0},0)")
                        return True
            if t == QEvent.MouseButtonPress:
                self._press(ev)
            elif t == QEvent.MouseMove:
                self._move(ev)
            elif t == QEvent.MouseButtonRelease:
                self._release(ev)
            elif t == QEvent.Wheel:
                return False              # колесо — целиком странице
            return False

        # те же жесты, если мышь пришла мимо веб-вида
        def mousePressEvent(self, e): self._press(e)
        def mouseMoveEvent(self, e): self._move(e)
        def mouseReleaseEvent(self, e): self._release(e)
        def wheelEvent(self, e): e.ignore()

    w = Desk()
    w.show()
    # ex-стиль ставится только на СОЗДАННОЕ окно: до show() winId() ещё
    # ничего не значит, и замок из конфига молча терялся
    w._apply_lock(w._lock)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
