"""ОТДЕЛЬНОЕ ОКНО С МОДЕЛЬЮ (2026-08-14).

Владелец, после моей первой версии: «вкладка с моделькой начала лагать и
исчезать как вкладка, я же говорил тут её не трогать. просто добавь кнопку
которая запустит окно отдельное где будет отображаться моделька, чтобы это
окно можно было масштабировать, и когда всё поставлено куда нужно я мог у
себя в интерфейсе сделать так чтобы она стояла поверх всех окон, и добавь
кнопку блокировки движения чтобы окно случайно не передвигалось».

Отсюда весь дизайн:
  * панель аватара в интерфейсе НЕ ТРОГАЕМ ВООБЩЕ — она работает, это чужая
    решённая задача. Окно на столе живёт рядом, а не вместо;
  * никаких режимов «ui/desk/both» — просто три выключателя:
        on   — окно открыто или нет
        top  — держать поверх всех окон
        lock — замок: окно нельзя сдвинуть и отмасштабировать;
  * управление из интерфейса, а не только из меню окна: человек ставит
    модель куда надо, а потом фиксирует её кнопкой, не целясь мышью.

Окно — отдельный процесс (tools/desk_avatar.py): Qt нужен свой цикл событий
в главном потоке, а он занят uvicorn. Состояние top/lock окно забирает само,
опрашивая /api/avatar/desk — так кнопка в интерфейсе доходит до уже
запущенного окна без всякого IPC.
"""
import json
import logging
import os
import subprocess
import sys
import threading

from anamorf import desk_slots as slots
from anamorf import runtime_env
from anamorf.config import CFG, CONFIG_PATH, resolve

log = logging.getLogger("saika.desk")

_PROC = {"p": None}
_lock = threading.Lock()
# ЧТО СЕЙЧАС ПРОИСХОДИТ (2026-08-14). Первая версия ставила PySide6 прямо
# внутри HTTP-запроса: человек жал кнопку, и она молча висела полторы
# минуты — ровно так это и читается, «кнопка не работает». Теперь установка
# идёт фоном, а кнопка сразу получает честное «ставлю, это займёт минуту» и
# дальше видит ход дела.
_STEP = {"busy": False, "note": ""}


def _script():
    return resolve("tools") / "desk_avatar.py"


def _pidfile():
    d = resolve("data")
    d.mkdir(parents=True, exist_ok=True)
    return d / "desk_avatar.pid"


def kill_all() -> int:
    """Прибить ВСЕ окна аватара, включая осиротевшие.

    2026-08-14, живой тупик: после перезапуска сервера на столе осталось
    окно от прошлого раза — с ошибкой внутри, без рамки, без крестика и без
    строки в панели задач (мы сами сделали его Qt.Tool). Закрыть его человеку
    было НЕЧЕМ: кнопка «закрыть» знала только про свой процесс, а этот был
    чужой. Поэтому ищем по командной строке, а не по номеру процесса."""
    n = 0
    try:
        import psutil
    except Exception:
        return 0
    me = os.getpid()
    for pr in psutil.process_iter(["pid", "cmdline"]):
        try:
            if pr.info["pid"] == me:
                continue
            cmd = " ".join(pr.info["cmdline"] or [])
            if "desk_avatar" in cmd:
                pr.terminate()
                n += 1
        except Exception:
            continue
    if n:
        log.info("Закрыла окон аватара: %d", n)
    return n


def kill_stale():
    """Прибить окно, оставшееся от прошлого запуска.

    2026-08-14, живой случай: сервер перезапустили — старое окно осталось
    висеть (оно отдельный процесс и переживает сервер), и на столе оказалось
    ДВА окна: новое с моделью и прошлое с «Not Found». Пид пишем на диск,
    чтобы после перезапуска было кого искать."""
    f = _pidfile()
    if not f.exists():
        return
    try:
        pid = int(f.read_text().strip() or 0)
    except Exception:
        pid = 0
    f.unlink(missing_ok=True)
    if not pid:
        return
    try:
        import psutil
        p = psutil.Process(pid)
        # проверяем, что это ИМЕННО наше окно, а не чужой процесс, которому
        # система уже переиспользовала номер
        if "desk_avatar" in " ".join(p.cmdline()):
            p.terminate()
            log.info("Прибила окно от прошлого запуска (pid %s)", pid)
    except Exception as e:
        log.debug("старое окно не нашлось (%s)", e)
    _sweep_strays()


def _sweep_strays():
    """Добить ВСЕ окна модели, сколько бы их ни расплодилось.

    2026-08-15, живое «как нах два окна запустилось, я же уже делал
    механику». Пид-файл — одноместная память: он помнит ОДНО окно.
    Стоит серверу упасть на старте (сегодня — мой же сломанный
    main.py) и подняться снова, как первый заход съедает пид-файл
    (kill_stale его unlink-ает), спавнит окно, падает — а второй
    заход уже не находит ни файла, ни окна, и спавнит ВТОРОЕ.
    Одноместной памяти на многоместную проблему не хватает по
    построению. Поэтому после пид-файла проходим по списку процессов
    и гасим ВСЁ, что запущено из tools/desk_avatar.py: перед спавном
    нового окна живых старых быть не должно ни одного."""
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
            if "desk_avatar" in cmd and "python" in cmd.lower():
                pr.terminate()
                log.info("Смела лишнее окно модели (pid %s)", pr.info["pid"])
        except Exception:
            continue


def available() -> bool:
    try:
        import PySide6  # noqa: F401
        return True
    except Exception:
        return False


def ensure_pyside() -> tuple[bool, str]:
    """Поставить PySide6 при первом запуске окна.

    Ставим ПО ТРЕБОВАНИЮ, а не при старте системы: пакет с QtWebEngine — под
    150 МБ, и тянуть его тем, кто окном не пользуется, неуважение к диску."""
    if available():
        return True, ""
    log.info("Ставлю PySide6 для окна с моделью…")
    ok, why = runtime_env.ensure(
        "desk_avatar", ["PySide6-Essentials", "PySide6-Addons"])
    if ok and available():
        return True, "поставила PySide6, открываю окно"
    return False, "не смогла поставить PySide6: " + why[-140:]


def is_running() -> bool:
    p = _PROC["p"]
    return p is not None and p.poll() is None


def start() -> str:
    """Открыть окно. Если PySide6 ещё нет — ставим ФОНОМ и возвращаемся
    сразу: держать кнопку нажатой полторы минуты нельзя."""
    if not available():
        if _STEP["busy"]:
            return _STEP["note"] or "ставлю PySide6, подожди"
        _STEP.update(busy=True,
                     note="ставлю PySide6 (~150 МБ) — минута-полторы, "
                          "окно откроется само")
        threading.Thread(target=_install_then_start, daemon=True).start()
        return _STEP["note"]
    return _start_now()


def _install_then_start():
    try:
        ok, why = ensure_pyside()
        _STEP["note"] = why or ("PySide6 поставлен" if ok else "не вышло")
        if ok:
            _STEP["note"] = _start_now()
    except Exception as e:
        _STEP["note"] = f"установка сорвалась: {e}"
        log.exception("установка PySide6")
    finally:
        _STEP["busy"] = False


def _start_now() -> str:
    with _lock:
        if is_running():
            return "окно уже открыто"
        _desk_fresh()       # подтянуть положение, записанное окном прошлый раз
        kill_stale()        # вдруг с прошлого раза висит чужое окно
        # ОТКРЫТИЕ ВСЕГДА ДАЁТ ВИДИМОЕ ОКНО (2026-08-14, живое «либо я
        # просто окна не вижу»). Настройки копятся между запусками, и
        # достаточно одной неудачной пары — замок при снятом «поверх
        # всех» — чтобы окно оказалось под браузером и без реакции на
        # мышь. Искать его человеку нечем. Поэтому кнопка «открыть»
        # всегда возвращает окно в состояние, в котором его видно и
        # можно схватить: поверх всех, с рамкой, без замка. Захочет
        # спрятать — нажмёт сам, уже видя, что нажимает.
        # СПАСАЕМ ТОЛЬКО ОТ НЕНАХОДИМОГО, А НЕ ОТ ВСЕГО ПОДРЯД
        # (2026-08-15, владелец: «какого хера рамка постоянно
        # отображается, я для чего писал запоминать состояния»). Он прав:
        # тут сбрасывались ВСЕ три настройки при каждом открытии, а окно
        # открывается само при запуске — значит его выбор жил ровно до
        # ближайшей перезагрузки. Настоящая ловушка только одна: замок
        # ВМЕСТЕ со снятым «поверх всех» — окно не ловит мышь и лежит под
        # браузером, найти его человеку нечем. Её и разряжаем. Рамка к
        # находимости отношения не имеет: фигуру видно, за неё же и
        # таскают, а на крайний случай есть правая кнопка, Shift+Esc и
        # оба спасательных срока (8 с и 90 с) в самом окне.
        if CFG.get("avatar.desk.lock", False) and not CFG.get(
                "avatar.desk.top", True):
            CFG.set("avatar.desk.top", True)
            CFG.set("avatar.desk.lock", False)
            log.info("Окно модели было заперто и не поверх всех — вернула "
                     "видимое состояние, иначе его не найти")
        sc = _script()
        if not sc.exists():
            return f"нет файла окна ({sc.name})"
        try:
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            # СВОЙ ЛОГ ДОЧЕРНЕМУ ПРОЦЕССУ (2026-08-14). Запускали с
            # CREATE_NO_WINDOW и без перенаправления — весь его вывод
            # пропадал в никуда. Когда окно открылось и показало 404,
            # искать причину было негде: в логе сервера «окно запущено», а
            # что случилось внутри — тишина.
            logdir = resolve("logs")
            logdir.mkdir(parents=True, exist_ok=True)
            out = open(logdir / "desk_avatar.log", "a", encoding="utf-8",
                       errors="replace")
            env = dict(os.environ)
            # прозрачность QtWebEngine на Windows надёжнее без GPU-композитора
            env["QTWEBENGINE_CHROMIUM_FLAGS"] = (
                env.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
                + " --enable-transparent-visuals").strip()
            if not bool((CFG.get("avatar.desk", {}) or {}).get("gpu", False)):
                # ПРОЗРАЧНОСТЬ ПРОТИВ ВИДЕОКАРТЫ (2026-08-14, живой чёрный
                # прямоугольник вместо прозрачного фона). QtWebEngine на
                # Windows не отдаёт альфа-канал, пока композитингом занята
                # видеокарта: окно получается непрозрачным, каким бы
                # прозрачным ни был сам холст. Отключаем GPU-композитор —
                # WebGL продолжает работать, просто рисует программно.
                # Кому важнее плавность, чем прозрачность: avatar.desk.gpu
                # = true в config вернёт видеокарту.
                    # --disable-gpu убивает и WebGL: модель тогда рисуется
                # программно и еле шевелится. Нужен точечный флаг — он
                # отключает КОМПОЗИТИНГ (из-за которого теряется альфа),
                # оставляя саму видеокарту рисовать сцену.
                env["QTWEBENGINE_CHROMIUM_FLAGS"] += (
                    " --disable-gpu-compositing --allow-no-sandbox-job")
            # runtime_env.PY, а не sys.executable: в собранном
            # приложении sys.executable — это сам ANAMORF.exe, и вместо
            # окна аватара запустился бы второй экземпляр программы.
            _PROC["p"] = subprocess.Popen([runtime_env.PY, str(sc)],
                                          cwd=str(resolve(".")),
                                          creationflags=flags,
                                          stdout=out, stderr=out, env=env)
            try:
                _pidfile().write_text(str(_PROC["p"].pid), encoding="utf-8")
            except Exception:
                pass
            CFG.set("avatar.desk.on", True)
            log.info("Окно с моделью запущено (pid %s)", _PROC["p"].pid)
            return "окно открыто"
        except Exception as e:
            log.exception("окно не запустилось")
            return f"окно не запустилось: {e}"


def stop() -> str:
    with _lock:
        CFG.set("avatar.desk.on", False)
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
        # и подметаем осиротевшие окна прошлых запусков — их закрыть больше
        # нечем, у них нет ни рамки, ни крестика
        extra = kill_all()
        if had or extra:
            return ("окно закрыто" if not extra
                    else f"окна закрыты (в том числе {extra} от прошлых запусков)")
        return "окна и так нет"


def _desk_fresh() -> dict:
    """avatar.desk, где положение окна взято С ДИСКА.

    2026-08-14. Окно — отдельный процесс и пишет свои x/y/w/h прямо в
    config.json. Сервер держит слепок конфига в памяти и при следующей
    записи (нажали «поверх всех», страница сохранила масштаб) честно
    склеивал диск со слепком, где положение осталось прошлогодним, — и
    только что подвинутое окно прыгало назад. Правило простое: чьё
    хозяйство, того и правда. Положение и слоты — с диска, выключатели
    (on/top/lock/frame/span) — из памяти, их ставит сервер."""
    disk = {}
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        disk = ((raw.get("avatar") or {}).get("desk") or {})
    except Exception as e:
        log.debug("конфиг с диска не прочёлся (%s)", e)
    live = CFG.get("avatar.desk", {})        # это САМ узел конфига, не копия
    d = dict(live or {})
    for k in ("x", "y", "w", "h", "slots"):
        if k in disk:
            d[k] = disk[k]
            # чиним и слепок в памяти — без записи на диск. Иначе любая
            # чужая CFG.set(...) отсюда до перезапуска утащила бы за собой
            # устаревшее положение окна, а его тут спрашивают дважды в
            # секунду, так что слепок всегда свежий
            if isinstance(live, dict):
                live[k] = disk[k]
    return d


def model_key() -> str:
    """Ключ текущей модели — под ним лежит её собственная настройка окна."""
    return slots.key_of(CFG.get("avatar.web.model", ""))


def state() -> dict:
    """То, что читает и интерфейс, и само окно (оно опрашивает раз в полсекунды)."""
    d = _desk_fresh()
    key = model_key()
    return {"on": is_running(),
            # КАКАЯ МОДЕЛЬ СЕЙЧАС НАДЕТА (2026-08-14). Окно следит за этим
            # полем: сменили аватар — оно подтягивает размеры и положение,
            # запомненные ИМЕННО для него, и перечитывает страницу. Иначе
            # чиби приезжала в рамку от высокой модели и висела в воздухе.
            "model": key,
            "top": bool(d.get("top", True)),
            "lock": bool(d.get("lock", False)),
            "frame": bool(d.get("frame", True)),
            "span": bool(d.get("span", False)),
            # как стояла модель ВНУТРИ окна: масштаб и смещение. Хранится
            # здесь, а не в localStorage окна — у него профиль временный.
            "view": slots.view_for(d, key),
            "available": available(),
            "busy": bool(_STEP["busy"]),
            "step": _STEP["note"] if _STEP["busy"] else ""}


def apply(patch: dict) -> dict:
    """Применить то, что нажали в интерфейсе."""
    p = patch or {}
    note = ""
    _desk_fresh()           # см. выше: сперва забираем правки окна, потом пишем
    if "top" in p:
        CFG.set("avatar.desk.top", bool(p["top"]))
        # снимая «поверх всех», снимаем и замок — иначе окно потеряется
        if not p["top"] and (CFG.get("avatar.desk", {}) or {}).get("lock"):
            CFG.set("avatar.desk.lock", False)
            note = ("сняла и замок: иначе окно ушло бы под другие и "
                    "поймать его было бы нечем")
    if "lock" in p:
        CFG.set("avatar.desk.lock", bool(p["lock"]))
        # ЗАМКНУТОЕ ОКНО ОБЯЗАНО БЫТЬ ПОВЕРХ ВСЕХ (2026-08-14, живой тупик:
        # top=false и lock=true одновременно — окно лежит под браузером и
        # при этом не ловит мышь. Достать его нечем вообще: ни кликнуть, ни
        # найти. Замок означает «она просто стоит на столе», а стоять на
        # столе под чужими окнами бессмысленно.)
        if p["lock"]:
            CFG.set("avatar.desk.top", True)
        # замок означает ровно одно: окно не ловит мышь совсем — ни
        # перетаскивания, ни колеса, ни кликов. Сквозь него работают.
        note = ("замок: окно не ловит мышь, кликай сквозь неё"
                if p["lock"] else "замок снят, окно снова двигается")
    if "view" in p and isinstance(p["view"], dict):
        src = p["view"]
        v = {k: float(src.get(k, 0) or 0)
             for k in ("x", "y", "z", "rx", "ry", "rz",
                       "az", "el", "dist", "ox", "oy", "oz",
                       "lean")}
        v["zoom"] = float(src.get("zoom", 1) or 1)
        v["snap"] = float(src.get("snap", 0) or 0)
        v["ortho"] = bool(src.get("ortho", False))
        v["headFollow"] = bool(src.get("headFollow", True))
        # пишем СРАЗУ В ДВА МЕСТА: в слот этой модели и в общий «последний
        # раз» — общий нужен как стартовое приближение для модели, которую
        # ещё ни разу не ставили
        d = _desk_fresh()
        slots.remember(d, model_key(), view=v)
        CFG.set("avatar.desk", d)
        return state()          # это фоновая запись, ответ никому не нужен
    if "span" in p:
        CFG.set("avatar.desk.span", bool(p["span"]))
        note = ("окно на всю ширину стола — она может ходить по обоим "
                "экранам" if p["span"] else "окно вернётся к обычному размеру")
    if "frame" in p:
        # РАМКА — ЭТО РУЧКИ ОКНА (2026-08-14, владелец: «прозрачность логика
        # должна быть такой: когда она выключена, видно рамки окна, в
        # которых она стоит, чтобы это окно можно было масштабировать»).
        # Прозрачное окно без рамки невозможно ухватить за край: границы не
        # видно, целиться некуда. Рамка включена — видно, где окно, и края
        # тянутся; выключена — на столе остаётся только фигура.
        CFG.set("avatar.desk.frame", bool(p["frame"]))
        note = ("рамка показана — тяни за края" if p["frame"]
                else "рамка убрана, осталась только модель")
    if "ghost" in p:            # старое имя того же самого — принимаем
        CFG.set("avatar.desk.lock", bool(p["ghost"]))
        note = ("замок: клики проходят насквозь" if p["ghost"]
                else "замок снят")
    if "on" in p:
        note = start() if p["on"] else stop()
    st = state()
    st["note"] = note
    # «не получилось» только если окно просили открыть, оно не открылось И
    # установка при этом не идёт — иначе честное «ставлю» выглядело бы
    # ошибкой
    st["ok"] = (not p.get("on")) or st["on"] or st["busy"]
    return st


def autostart():
    """Окно было открыто, когда систему выключали — открыть снова."""
    # Сперва подметаем всё, что осталось с прошлого раза: такие окна нельзя
    # закрыть ни крестиком, ни с панели задач — только отсюда.
    kill_all()
    kill_stale()
    if (CFG.get("avatar.desk", {}) or {}).get("on"):
        threading.Thread(target=start, daemon=True).start()
