"""РЕЖИМ ИСЧЕЗНОВЕНИЯ: на столе остаётся одно ядро (2026-08-23).

Владелец: «можно прогу сделать с режимом исчезновения чтобы чисто ядро с
полосками осталось и уменьшилось чтобы я его мог перемещать по системе».

Что происходит по нажатию:
    1. открывается маленькое окно без рамки и без фона — в нём та же
       сцена, что и на главном экране, но раздетая до ядра и кольца
       полосок (страница знает про ?orb=1 и прячет всё остальное);
    2. большое окно программы ПРЯЧЕТСЯ — целиком, вместе со строкой в
       панели задач: в этом весь смысл слова «исчезновение».
    3. щелчок по самому шару возвращает большое окно и закрывает ядро.

ПОЧЕМУ ЭТО ТА ЖЕ СТРАНИЦА, А НЕ ВТОРАЯ СВОЯ. Ядро — не картинка: дуги
органов, отсчёт готовности, мигание при загрузке, полоски звука — это всё
живая механика главного экрана. Скопировать её во второй файл значит
завести второй источник правды, который разойдётся с первым на ближайшей
правке и будет врать молча. Поэтому окно открывает ТОТ ЖЕ /?orb=1.

ПОЧЕМУ ОКНО ПРЯЧЕТСЯ, А НЕ ЗАКРЫВАЕТСЯ. В нём живёт микрофон (звук идёт в
распознавание прямо со страницы), разговор и вся сессия. Закрыть его —
значит оглушить её на время режима. Спрятанное окно продолжает слышать,
говорить и думать; видно только ядро.

СТРАХОВКА ОТ ПОТЕРИ ОКНА. Спрятанное окно человеку нечем достать: ни
кнопки, ни строки в панели задач. Поэтому:
  * сторож следит за процессом ядра — умер, а режим включён, значит
    большое окно немедленно возвращается;
  * сервер при старте всегда показывает окно обратно;
  * у самого ядра есть правая кнопка с пунктом «Вернуть окно» и Shift+Esc.
"""
import ctypes
import ctypes.wintypes
import logging
import os
import subprocess
import sys
import threading
import time

from anamorf import runtime_env
from anamorf.config import CFG, resolve

log = logging.getLogger("saika.orb")

_PROC = {"p": None}
_lock = threading.Lock()
_HIDDEN = []          # окна, которые мы спрятали (hwnd)
_WATCH = {"on": False}


def _announce(on: bool):
    """Сказать интерфейсу, что режим сменился.

    Без этого большое окно возвращается ТЕМ ЖЕ, каким его спрятали, — а
    прятали его в разгар жеста, когда страница свернула себя в ядро.
    Человек видел пустое окно с одной шапкой и справедливо считал это
    поломкой. Знает о смене режима только сервер: он и говорит."""
    try:
        from anamorf.main import broadcast_event
        broadcast_event({"type": "orb", "on": bool(on)})
    except Exception as e:
        log.debug("не смогла объявить режим: %s", e)


def _script():
    """Файл окна. Их два поколения, и это не запас на всякий случай.

    orb_qml.py рисует ядро средствами Qt — у окна QML прозрачность
    штатная. orb_window.py показывал ту же HTML-страницу через
    QWebEngineView и упирался в чёрный прямоугольник вместо пустоты
    (2026-08-23, владелец: «выглядит как всратая png»). Берём новое, если
    оно приехало в сборку; нет — работаем старым, но говорим об этом."""
    tools = resolve("tools")
    qml = tools / "orb_qml.py"
    if qml.exists() and (resolve("ui") / "orb.qml").exists():
        return qml
    log.warning("Нет orb_qml.py или ui/orb.qml — открываю старое окно "
                "ядра на веб-движке (прозрачность не гарантирована)")
    return tools / "orb_window.py"


def _pidfile():
    d = resolve("data")
    d.mkdir(parents=True, exist_ok=True)
    return d / "orb.pid"


# ─────────────────────────── большое окно ───────────────────────────
# Окно программы рисует WebView2 через pywebview, заголовок у него
# «ANAMORF» (см. launcher/main.py: webview.create_window("ANAMORF", …)).
# Прячем ПО ЗАГОЛОВКУ, а не по процессу: сервер живёт отдельным
# процессом от окна, и своего hwnd у него нет вообще.
_TITLES = ("ANAMORF",)


def _main_windows(visible_only: bool = True) -> list:
    """Верхнеуровневые окна программы.

    visible_only=False нужен ровно в одном случае: сервер перезапустился,
    пока окно было спрятано. Память о спрятанном (_HIDDEN) при этом
    пропала вместе с процессом, а окно осталось невидимым — и достать его
    человеку нечем. Тогда ищем и невидимые тоже.""" 
    if sys.platform != "win32":
        return []
    out = []
    u = ctypes.windll.user32
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p,
                                  ctypes.c_void_p)

    def _cb(hwnd, _lp):
        try:
            if visible_only and not u.IsWindowVisible(hwnd):
                return True
            n = u.GetWindowTextLengthW(hwnd)
            if not n:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.strip() not in _TITLES:
                return True
            # ЧУЖИЕ ОКНА НЕ НАШЕ ДЕЛО (2026-08-23, владелец: «сделай окна
            # не привязанные друг к другу»). Заголовок — слабая примета:
            # «ANAMORF» может стоять на папке в проводнике, на редакторе с
            # открытым проектом, на чём угодно. Прятать по имени значит
            # однажды спрятать человеку не то, и он даже не поймёт, что
            # это сделали мы. Спрашиваем ещё и процесс: наше окно рисует
            # ANAMORF.exe (или python, когда запущено из исходников).
            if not _ours(hwnd):
                return True
            out.append(hwnd)
        except Exception:
            pass
        return True

    try:
        u.EnumWindows(EnumProc(_cb), None)
    except Exception as e:
        log.warning("не смогла перебрать окна: %s", e)
    return out


def _ours(hwnd) -> bool:
    """Окно принадлежит нашей программе, а не чужой с похожим именем."""
    try:
        pid = ctypes.wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd,
                                                      ctypes.byref(pid))
        if not pid.value:
            return False
        try:
            import psutil
            nm = (psutil.Process(pid.value).name() or "").lower()
        except Exception:
            return False
        return nm.startswith("anamorf") or nm.startswith("python") \
            or nm.startswith("pythonw")
    except Exception:
        return False


def hide_main() -> int:
    """Спрятать большое окно. Возвращает, сколько окон спрятала."""
    if sys.platform != "win32":
        return 0
    u = ctypes.windll.user32
    n = 0
    for hwnd in _main_windows():
        try:
            u.ShowWindow(hwnd, 0)          # SW_HIDE
            _HIDDEN.append(hwnd)
            n += 1
        except Exception as e:
            log.warning("окно не спряталось: %s", e)
    log.info("Режим исчезновения: спрятала окон — %d", n)
    return n


def show_main() -> int:
    """Вернуть большое окно и поднять его наверх."""
    if sys.platform != "win32":
        return 0
    u = ctypes.windll.user32
    hwnds = list(_HIDDEN) or _main_windows(visible_only=False)
    n = 0
    for hwnd in hwnds:
        try:
            u.ShowWindow(hwnd, 5)          # SW_SHOW
            u.ShowWindow(hwnd, 9)          # SW_RESTORE — вдруг было свёрнуто
            u.SetForegroundWindow(hwnd)
            n += 1
        except Exception as e:
            log.warning("окно не вернулось: %s", e)
    _HIDDEN.clear()
    if n:
        log.info("Вернула большое окно (%d)", n)
    return n


# ─────────────────────────── окно ядра ───────────────────────────
def available() -> bool:
    try:
        import PySide6  # noqa: F401
        return True
    except Exception:
        return False


def is_running() -> bool:
    p = _PROC["p"]
    return p is not None and p.poll() is None


def state() -> dict:
    # w отдаём странице: пока человек тянет ядро наружу, призрак под
    # курсором обязан быть РОВНО того размера, каким окно откроется.
    # Иначе в момент отпускания ядро скакнёт — а это то самое движение,
    # после которого перестаёшь верить, что попал куда целился.
    try:
        w = int((CFG.get("ui.orb", {}) or {}).get("w", 190))
    except Exception:
        w = 190
    return {"on": bool(CFG.get("ui.orb.on", False)) and is_running(),
            "running": is_running(),
            "w": max(96, min(560, w)),
            "ready": available()}


def kill_stale():
    """Прибить ядро, оставшееся от прошлого запуска (оно переживает сервер)."""
    f = _pidfile()
    pid = 0
    if f.exists():
        try:
            pid = int(f.read_text().strip() or 0)
        except Exception:
            pid = 0
        f.unlink(missing_ok=True)
    try:
        import psutil
    except Exception:
        return
    me = os.getpid()
    for pr in psutil.process_iter(["pid", "cmdline"]):
        try:
            if pr.info["pid"] == me:
                continue
            cmd = " ".join(pr.info.get("cmdline") or [])
            if "orb_window" in cmd or "orb_qml" in cmd:
                pr.terminate()
                log.info("Смела старое ядро (pid %s)", pr.info["pid"])
        except Exception:
            continue
    if pid:
        log.debug("пид старого ядра был %s", pid)


def start(x=None, y=None, follow: bool = False) -> str:
    """Включить режим: открыть ядро и спрятать большое окно.

    x, y — куда его положить (центр окна, экранные координаты). Это путь
    «выдернул ядро мышью из интерфейса»: человек показал место рукой, и
    спрашивать его ещё раз или ставить окно в свой угол было бы
    издевательством.
    follow — ядро открывается прямо под курсором и едет за ним, пока
    кнопка мыши зажата. Жест начался в одном процессе, а заканчивается в
    другом: перехватить чужое нажатие нельзя, зато можно честно смотреть,
    отпущена ли кнопка, — окно так и делает."""
    with _lock:
        if is_running():
            CFG.set("ui.orb.on", True)
            return "ядро уже на столе"
        if not available():
            # Ставить PySide6 отсюда не будем: этим занимается окно с
            # моделью, и два места установки одного пакета — это два
            # места, где она ломается. Говорим прямо, чем лечится.
            log.error("Ядро на столе не открылось: нет PySide6. Открой "
                      "«Окно с моделью» один раз — оно его поставит.")
            return ("нет PySide6 — открой один раз «Окно с моделью», "
                    "оно поставит, и возвращайся")
        sc = _script()
        if not sc.exists():
            log.error("Ядро на столе не открылось: нет файла %s. В сборку не "
                      "приехала папка tools — положи туда orb_window.py.", sc)
            return f"нет файла окна ({sc.name})"
        kill_stale()
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            logdir = resolve("logs")
            logdir.mkdir(parents=True, exist_ok=True)
            out = open(logdir / "orb.log", "a", encoding="utf-8",
                       errors="replace")
            env = dict(os.environ)
            try:
                env["ANAMORF_PORT"] = str(int(CFG.get("server.port", 8765)))
            except Exception:
                pass
            if x is not None and y is not None:
                try:
                    env["ANAMORF_ORB_XY"] = f"{int(x)},{int(y)}"
                except Exception:
                    pass
            if follow:
                env["ANAMORF_ORB_FOLLOW"] = "1"
            env["QTWEBENGINE_CHROMIUM_FLAGS"] = (
                env.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
                + " --enable-transparent-visuals --disable-gpu-compositing"
                  " --allow-no-sandbox-job").strip()
            _PROC["p"] = subprocess.Popen([runtime_env.PY, str(sc)],
                                          cwd=str(resolve(".")),
                                          creationflags=flags,
                                          stdout=out, stderr=out, env=env)
            _pidfile().write_text(str(_PROC["p"].pid), encoding="utf-8")
            CFG.set("ui.orb.on", True)
            log.info("Ядро на столе запущено (pid %s)", _PROC["p"].pid)
            _announce(True)
        except Exception as e:
            log.exception("ядро не запустилось")
            return f"ядро не запустилось: {e}"
    # ПРЯЧЕМ НЕ СРАЗУ. Окно ядра поднимается секунду-полторы (Qt плюс
    # страница), и если спрятать большое окно раньше, человек это время
    # смотрит на пустой стол и думает, что программа закрылась.
    threading.Thread(target=_hide_when_ready, daemon=True).start()
    _watch()
    return "ядро на столе"


def _hide_when_ready():
    for _ in range(40):                    # до 10 секунд
        time.sleep(0.25)
        if not is_running():
            log.warning("Ядро закрылось на старте — большое окно не трогаю")
            return
        if _seen():
            break
    hide_main()


_SEEN = {"ts": 0.0}


def seen():
    """Окно ядра доложило, что страница открылась."""
    _SEEN["ts"] = time.time()


def _seen() -> bool:
    return time.time() - _SEEN["ts"] < 3.0


def stop() -> str:
    """Выключить режим: вернуть большое окно, закрыть ядро."""
    with _lock:
        CFG.set("ui.orb.on", False)
        had = is_running()
        if had:
            try:
                _PROC["p"].terminate()
                _PROC["p"].wait(timeout=5)
            except Exception:
                try:
                    _PROC["p"].kill()
                except Exception:
                    pass
        _PROC["p"] = None
        _pidfile().unlink(missing_ok=True)
        kill_stale()
    show_main()
    _announce(False)
    return "вернулась в окно" if had else "режим и так выключен"


def toggle() -> str:
    return stop() if is_running() else start()


def _watch():
    """Сторож: ядро умерло, а окно спрятано — вернуть окно немедленно.

    Спрятанное окно человеку нечем достать. Падение ядра без сторожа
    выглядело бы как «программа пропала целиком», и это худшая из всех
    возможных поломок в этом режиме."""
    if _WATCH["on"]:
        return
    _WATCH["on"] = True

    def _loop():
        try:
            while True:
                time.sleep(1.0)
                if not CFG.get("ui.orb.on", False):
                    break
                if not is_running():
                    log.warning("Ядро на столе закрылось само — возвращаю "
                                "большое окно")
                    CFG.set("ui.orb.on", False)
                    show_main()
                    _announce(False)
                    break
        finally:
            _WATCH["on"] = False

    threading.Thread(target=_loop, daemon=True).start()


def boot():
    """При старте сервера: ядер от прошлого раза быть не должно, а окно
    обязано быть видимым. Режим не восстанавливаем намеренно — программа,
    которая запускается невидимой, неотличима от незапустившейся."""
    try:
        kill_stale()
        CFG.set("ui.orb.on", False)
        show_main()
        _announce(False)
    except Exception as e:
        log.debug("подготовка ядра пропущена: %s", e)
