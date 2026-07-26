"""Глаза Сайки: экран, вебки и непрерывное наблюдение (2026-07-25).

ПОЧЕМУ НЕ «ПОТОКОВОЕ ВИДЕО».
Разведка июля 2026 (workshop/SAIKA_VISION_2026-07-25.md): настоящего
потокового видеовхода на 16 ГБ VRAM локально нет, а в облаке он есть у
Google (заблокирован из РФ, сессия 2 минуты) и Alibaba. Рабочий вариант —
СОБЫТИЙНАЯ выборка кадров: кадр уходит модели по явной просьбе человека
либо когда сцена реально изменилась. Дорого не сравнение кадров (0.06 мс),
а отправка в модель (сотни мс) — ради этого и детектор.

Всё open source: dxcam (MIT), windows-capture (MIT), mss (MIT),
OpenCV (Apache-2.0). Смотрит любая vision-модель из парка.

ТРИ БЭКЕНДА ЗАХВАТА, как у слуха (stt/manager.py): dxcam(dxgi) ->
dxcam(winrt) -> windows-capture -> mss. Причина ровно та же, что со
слухом: они ломаются молча и по-разному (HDR пересвечивает кадр, DXGI
отваливается при смене разрешения и в полноэкранных играх), поэтому
здоровье каждого держим отдельно и чиним по одному, а не «зрение упало».

ПРЕДОХРАНИТЕЛЬ. Захват экрана ничего не меняет на машине, но ЧИТАЕТ
приватное: пароли, переписку, банк. Поэтому здесь свой замок, независимый
от _MUTATING_INTENT в llm/tools.py:
  1) глобальный тумблер vision.enabled — «глаза выключены» (кнопка 👁 в UI);
  2) экран — только по явному намерению в последней фразе человека;
  3) чёрный список окон по заголовку: если впереди банк/менеджер паролей —
     кадр не делаем вообще и честно об этом говорим;
  4) режим наблюдения (watch) по умолчанию ВЫКЛЮЧЕН и включается только
     руками владельца.
Импульсный режим (Сайка думает сама с собой) к экрану не допущен —
см. _IMPULSE_SAFE в llm/tools.py, look_screen туда намеренно НЕ добавлен.
"""
import base64
import logging
import re
import threading
import time

from server.config import CFG

log = logging.getLogger("saika.vision")

_ST = {
    "screen_backend": None,     # какой бэкенд экрана сейчас живой
    "screen_err": "",
    "cam_err": "",
    "last_grab_ts": 0.0,
    "last_source": "",
    "grabs": 0,
    "blocked": 0,               # сколько раз предохранитель не дал смотреть
    "watch_on": False,
    "watch_src": "",
    "watch_events": 0,
}

# Заголовки окон, на которые не смотрим никогда. Дополняется из config
# (vision.window_blocklist) — список подстрок, регистр не важен.
_BLOCK_DEFAULT = [
    "keepass", "bitwarden", "1password", "lastpass", "порол", "password",
    "сбербанк", "тинькоф", "т-банк", "альфа-банк", "vtb", "банк", "bank",
    "приватный просмотр", "инкогнито", "incognito", "private browsing",
    "wallet", "кошелёк", "metamask", "seed phrase", "секретн",
]


# ═══════════════════════════ тумблеры ═══════════════════════════
def enabled() -> bool:
    return bool(CFG.get("vision.enabled", True))


def _cfg_set(key, val):
    """CFG.set есть не во всех сборках — не падаем, живём до перезапуска."""
    try:
        CFG.set(key, val)
        return
    except Exception:
        pass
    try:
        node = CFG.data
        parts = key.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = val
    except Exception as e:
        log.debug("не смогла сохранить %s: %s", key, e)


def set_enabled(on: bool) -> bool:
    _cfg_set("vision.enabled", bool(on))
    if not on:
        watch_stop()
        camera_stop()
    log.info("Глаза Сайки: %s", "ВКЛ" if on else "ВЫКЛ")
    return bool(on)


def state() -> dict:
    """Для UI и диагностики."""
    missing = not deps_ok()
    return {
        "enabled": enabled(),
        "deps_ok": not missing,
        "hint": _MISSING_DEPS if missing else "",
        "screen_backend": _ST["screen_backend"],
        "screen_err": _ST["screen_err"],
        "cam_err": _ST["cam_err"],
        "monitor": int(CFG.get("vision.monitor", 0)),
        "camera_index": int(CFG.get("vision.camera_index", 0)),
        "camera_on": camera_enabled(),
        "camera_live": any(st.get("run") for st in _cams.values()),
        # {индекс: {'ok': bool, 'error': str}} — что уже пробовали открыть
        "camera_probe": {str(k): v for k, v in _cam_probe.items()},
        "monitors": list_monitors(),
        "cameras": list_cameras(),
        "grabs": _ST["grabs"],
        "last_source": _ST["last_source"],
        "last_grab_s_ago": (round(time.time() - _ST["last_grab_ts"], 1)
                            if _ST["last_grab_ts"] else None),
        "blocked": _ST["blocked"],
        "watch_on": _ST["watch_on"],
        "watch_src": _ST["watch_src"],
        "watch_events": _ST["watch_events"],
    }


# ═════════════════════ перечисление устройств ═════════════════════
_devcache = {"mon": None, "mon_ts": 0.0, "cam": None, "cam_ts": 0.0}


def list_monitors() -> list:
    """[{id, name, w, h}] — все дисплеи. Кэш 30 с: перечисление стоит
    открытия mss, дёргать на каждый рендер UI незачем."""
    if _devcache["mon"] is not None and time.time() - _devcache["mon_ts"] < 30:
        return _devcache["mon"]
    out = []
    try:
        import mss
        with mss.mss() as sct:
            # sct.monitors[0] — «все мониторы разом», его показываем отдельно
            for i, m in enumerate(sct.monitors[1:]):
                out.append({"id": i, "name": f"Дисплей {i + 1}",
                            "w": m["width"], "h": m["height"]})
            if len(sct.monitors) > 2:
                a = sct.monitors[0]
                out.append({"id": -1, "name": "Все дисплеи",
                            "w": a["width"], "h": a["height"]})
    except Exception as e:
        log.debug("перечисление дисплеев: %s", e)
        out = [{"id": 0, "name": "Дисплей 1", "w": 0, "h": 0}]
    _devcache["mon"], _devcache["mon_ts"] = out, time.time()
    return out


def list_cameras(force=False) -> list:
    """[{id, name}] — подключённые камеры. Перебор индексов дорогой
    (открытие устройства), поэтому кэш 60 с и не чаще по требованию.
    Имена берём через pygrabber, если он есть; иначе просто номера."""
    if (not force and _devcache["cam"] is not None
            and time.time() - _devcache["cam_ts"] < 60):
        return _devcache["cam"]
    names = {}
    try:    # необязательная зависимость, даёт человеческие имена устройств
        from pygrabber.dshow_graph import FilterGraph
        for i, n in enumerate(FilterGraph().get_input_devices()):
            names[i] = n
    except Exception:
        pass
    out = []
    if names:
        out = [{"id": i, "name": n} for i, n in sorted(names.items())]
    else:
        try:
            import cv2
            for i in range(int(CFG.get("vision.camera_probe", 4))):
                cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                ok = cap.isOpened()
                cap.release()
                if ok:
                    out.append({"id": i, "name": f"Камера {i}"})
        except Exception as e:
            log.debug("перечисление камер: %s", e)
    _devcache["cam"], _devcache["cam_ts"] = out, time.time()
    return out


# ═══════════════════════ чёрный список окон ═══════════════════════
def foreground_title() -> str:
    """Заголовок активного окна. ctypes, без лишних зависимостей."""
    try:
        import ctypes
        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        if not h:
            return ""
        n = u.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, buf, n + 1)
        return buf.value or ""
    except Exception:
        return ""


def _window_blocked() -> str:
    """Вернуть подстроку из чёрного списка, если смотреть нельзя."""
    title = foreground_title().lower()
    if not title:
        return ""
    for w in list(_BLOCK_DEFAULT) + list(CFG.get("vision.window_blocklist", [])):
        w = str(w).strip().lower()
        if w and w in title:
            return w
    return ""


# ═══════════════════════════ экран ═══════════════════════════
_screen = {"obj": None, "kind": None, "mon": None}
_screen_lock = threading.RLock()


def _open_dxcam(mon: int, _alt: bool):
    import dxcam
    idx = max(0, mon)
    # output_color="BGR" ОБЯЗАТЕЛЕН (2026-07-25). По умолчанию dxcam отдаёт
    # RGB, а cv2.imencode ждёт BGR — без этого R и B меняются местами, и
    # кадр уезжает в чужие цвета: синий интерфейс становится красноватым.
    # Выглядит как «наложили фильтр», а не как баг, поэтому ловится глазами,
    # а не исключением. Один раз уже поймали на пробном кадре.
    cam = dxcam.create(output_idx=idx, output_color="BGR")
    if cam is None:
        raise RuntimeError(f"dxcam.create(output_idx={idx}) вернул None")
    return cam


def _grab_dxcam(cam, force_shot=False):
    """grab() отдаёт None, когда кадр НЕ ИЗМЕНИЛСЯ с прошлого раза — это не
    ошибка, а протокол Desktop Duplication. Поэтому пробуем несколько раз,
    потом падаем на shot(), который отдаёт кадр всегда.

    force_shot — второй заход бэкенда: только shot(), без grab(). Помогает,
    когда DXGI-очередь разъехалась (смена разрешения, выход из
    полноэкранной игры) и grab() возвращает None бесконечно."""
    if force_shot:
        return cam.shot()
    for _ in range(3):
        f = cam.grab()
        if f is not None:
            return f
        time.sleep(0.03)
    return cam.shot()


def _grab_windows_capture():
    from windows_capture import WindowsCapture
    box = {"img": None}
    cap = WindowsCapture(cursor_capture=False, draw_border=False)

    @cap.event
    def on_frame_arrived(frame, ctl):
        # frame_buffer — BGRA, отбрасываем альфу и получаем BGR под cv2.
        # Порядок каналов НЕ разворачиваем, см. грабли в _grab_mss.
        box["img"] = frame.frame_buffer[:, :, :3].copy()
        ctl.stop()

    @cap.event
    def on_closed():
        pass

    cap.start()                       # блокирующе до ctl.stop()
    if box["img"] is None:
        raise RuntimeError("windows-capture не отдал кадр")
    return box["img"]


def _grab_mss(mon: int):
    import mss
    import numpy as np
    with mss.mss() as sct:
        # mon == -1 -> monitors[0] («все дисплеи разом»)
        idx = 0 if mon < 0 else min(mon + 1, len(sct.monitors) - 1)
        raw = sct.grab(sct.monitors[idx])
        # mss отдаёт BGRA, cv2 ждёт BGR — достаточно отбросить альфу.
        # Разворачивать порядок каналов НЕ надо (2026-07-25: было
        # [:, :, ::-1] и давало ровно тот же перекос R/B, что и dxcam).
        return np.array(raw)[:, :, :3].copy()


# Порядок фолбэка. Меняется в config (vision.screen_order), как
# stt.fallback_order — та же идея, тот же способ отладки.
_SCREEN_ORDER = ["dxcam", "dxcam_winrt", "windows_capture", "mss"]


def _is_washed_out(img) -> bool:
    """Признак HDR-пересвета: почти весь кадр близок к белому. Такой кадр
    выглядит как «захват работает», а модель видит белую простыню."""
    try:
        small = img[::16, ::16]
        return float((small > 250).mean()) > 0.9
    except Exception:
        return False


def _release_screen():
    try:
        if _screen["obj"] is not None:
            _screen["obj"].release()
    except Exception:
        pass
    _screen.update(obj=None, kind=None, mon=None)


def grab_screen(monitor=None):
    """Кадр экрана как numpy BGR. Перебирает бэкенды, помнит живой."""
    mon = int(CFG.get("vision.monitor", 0) if monitor is None else monitor)
    order = list(CFG.get("vision.screen_order", _SCREEN_ORDER))
    if mon < 0:
        # «все дисплеи разом» умеет только mss — DXGI работает по одному
        order = ["mss"]
    elif _ST["screen_backend"] in order:
        order.remove(_ST["screen_backend"])
        order.insert(0, _ST["screen_backend"])
    errs = []
    with _screen_lock:
        for kind in order:
            try:
                if kind in ("dxcam", "dxcam_winrt"):
                    if (_screen["kind"] != kind or _screen["obj"] is None
                            or _screen["mon"] != mon):
                        _release_screen()
                        _screen["obj"] = _open_dxcam(mon, kind == "dxcam_winrt")
                        _screen["kind"], _screen["mon"] = kind, mon
                    img = _grab_dxcam(_screen["obj"],
                                      force_shot=(kind == "dxcam_winrt"))
                elif kind == "windows_capture":
                    img = _grab_windows_capture()
                elif kind == "mss":
                    img = _grab_mss(mon)
                else:
                    continue
                if img is None:
                    raise RuntimeError("пустой кадр")
                if _is_washed_out(img):
                    raise RuntimeError("кадр пересвечен (похоже на HDR) — "
                                       "нужен другой бэкенд")
                _ST["screen_backend"] = kind
                _ST["screen_err"] = ""
                _ST["grabs"] += 1
                _ST["last_grab_ts"] = time.time()
                _ST["last_source"] = f"экран {mon}/{kind}"
                return img
            except Exception as e:
                errs.append(f"{kind}: {e}")
                if kind.startswith("dxcam"):
                    _release_screen()
                log.debug("захват экрана %s не смог: %s", kind, e)
    _ST["screen_err"] = " | ".join(errs)[:400]
    _ST["screen_backend"] = None
    # 2026-07-25: если ВСЕ бэкенды упали на ImportError — это не поломка
    # захвата, а «зависимости не поставлены». Показываем ровно то, что
    # надо сделать, иначе владелец видит четыре «No module named» подряд
    # и лезет гуглить имена пакетов.
    if all("No module named" in e for e in errs):
        _ST["screen_err"] = _MISSING_DEPS
        raise RuntimeError(_MISSING_DEPS)
    raise RuntimeError("ни один бэкенд захвата экрана не сработал: "
                       + _ST["screen_err"])


_MISSING_DEPS = ("библиотеки захвата не установлены — запусти "
                 "setup\\install_vision.bat (поставит opencv, mss, dxcam). "
                 "Пока их нет, смотреть нечем.")


def deps_ok() -> bool:
    """Есть ли хоть чем захватывать. Дешёвая проверка для UI и Беймакса."""
    for mod in ("mss", "dxcam", "windows_capture"):
        try:
            __import__(mod)
            return True
        except Exception:
            continue
    return False


# ═══════════════════════════ вебки ═══════════════════════════
# CAP_PROP_BUFFERSIZE на Windows фактически не работает: очередь драйвера
# копится и отдаёт кадр 0.5-2 с давности. Единственное лечение — поток,
# который читает непрерывно и перезаписывает одну переменную.
# Камер может быть несколько, поэтому держим словарь по индексу.
_cams: dict = {}
_cam_lock = threading.RLock()


def _cam_open(idx: int):
    try:
        import cv2
    except ImportError:
        raise RuntimeError(_MISSING_DEPS)
    # MSMF на Windows открывает камеру от 20 секунд до нескольких минут
    # (перебор нативных медиатипов, у части вебок их 300+), да ещё и
    # конфликтует с DSHOW, когда камер несколько. Поэтому только DSHOW.
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"камера {idx} не открылась (CAP_DSHOW)")
    # ПОРЯДОК ВАЖЕН: FOURCC ставится ДО разрешения. Без MJPG большинство
    # USB-вебок на USB 2.0 отдают несжатый YUY2 и режут 720p до 5-10 fps.
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    except Exception:
        pass
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(CFG.get("vision.camera_w", 1280)))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(CFG.get("vision.camera_h", 720)))
    return cap


# Что pygrabber перечислил — ещё не значит, что оно откроется. Виртуальные
# устройства (Meta Quest Link, OBS, NVIDIA Broadcast) висят в списке
# DirectShow всегда, даже когда программа не запущена: тогда VideoCapture
# честно возвращает isOpened()==False. Поэтому результат пробы помним и
# показываем в интерфейсе, а не даём владельцу выбирать вслепую.
_cam_probe: dict = {}

# Виртуальные камеры регистрируются в DirectShow навсегда, а создаются
# только когда работает их программа. «Не открывается» тут почти всегда
# значит «включи источник», а не «драйвер сломан». Подсказка по названию
# полезнее общей фразы: владельцу сразу видно, что именно запустить.
_CAM_HINTS = (
    ("iriun",    "запусти клиент Iriun Webcam на ПК И приложение на "
                 "телефоне, они должны быть в одной сети"),
    ("droidcam", "запусти DroidCam Client на ПК и приложение на телефоне"),
    ("epoccam",  "запусти EpocCam на телефоне и драйвер на ПК"),
    ("obs",      "в OBS нажми «Запустить виртуальную камеру» "
                 "(Start Virtual Camera)"),
    ("nvidia",   "запусти NVIDIA Broadcast — без него его камера мертва"),
    ("broadcast", "запусти NVIDIA Broadcast — без него его камера мертва"),
    ("quest",    "нужен Meta Quest Link, гарнитура подключена и Link "
                 "запущен; иначе эти камеры в списке просто висят"),
    ("virtual",  "включи источник этой виртуальной камеры в её программе"),
)


def _cam_hint(name: str) -> str:
    low = (name or "").lower()
    for key, hint in _CAM_HINTS:
        if key in low:
            return hint
    return ""


def _cam_name(idx: int) -> str:
    for c in list_cameras():
        if int(c["id"]) == int(idx):
            return c.get("name", "")
    return ""


def test_camera(idx: int, force=False) -> dict:
    """Открыть камеру, взять кадр, закрыть. {'ok': bool, 'error': str}."""
    idx = int(idx)
    if not force and idx in _cam_probe:
        return _cam_probe[idx]
    live = _cams.get(idx)
    if live and live.get("frame") is not None:      # уже снимает — очевидно ок
        _cam_probe[idx] = {"ok": True, "error": ""}
        return _cam_probe[idx]
    res = {"ok": False, "error": ""}
    cap = None
    try:
        import cv2
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            hint = _cam_hint(_cam_name(idx))
            res["error"] = ("устройство не открывается — " + hint) if hint \
                else "устройство не открывается (занято или драйвер не готов)"
        else:
            ok, frame = cap.read()
            if ok and frame is not None:
                res["ok"] = True
                res["shape"] = f"{frame.shape[1]}x{frame.shape[0]}"
                # Iriun, DroidCam, OBS Virtual Camera и им подобные ОТКРЫВАЮТСЯ
                # всегда, а пока источник не подключён, честно отдают чёрный
                # кадр. Формально всё работает, а на экране пустота — и это
                # выглядит как баг захвата, хотя надо просто запустить
                # приложение на телефоне. Ловим и говорим прямо.
                try:
                    import numpy as _np
                    a = _np.asarray(frame)
                    if float(a.mean()) < 3.0 and float(a.std()) < 3.0:
                        res["black"] = True
                        hint = _cam_hint(_cam_name(idx))
                        res["error"] = ("открывается, но отдаёт чёрный кадр — "
                                        + (hint or "источник не подключён"))
                except Exception:
                    pass
            else:
                res["error"] = "открылась, но не отдаёт кадр (занята другой " \
                               "программой?)"
    except Exception as e:
        res["error"] = str(e)[:200]
    finally:
        try:
            if cap is not None:
                cap.release()
        except Exception:
            pass
    _cam_probe[idx] = res
    log.info("Проба камеры %s: %s", idx,
             "ок" if res["ok"] else res["error"])
    return res


def test_all_cameras() -> dict:
    """Пройтись по всем перечисленным камерам и запомнить, какие живые.
    Дорого (открытие каждого устройства), поэтому только по кнопке."""
    out = {}
    for c in list_cameras():
        out[int(c["id"])] = test_camera(int(c["id"]), force=True)
    alive = [i for i, r in out.items() if r.get("ok") and not r.get("black")]
    log.info("Проба всех камер: живых %d из %d", len(alive), len(out))
    return out


def working_cameras() -> list:
    """Индексы камер, которые уже пробовали и они открылись."""
    return [i for i, r in _cam_probe.items() if r.get("ok")]


def _cam_loop(idx: int):
    """Читает непрерывно (иначе очередь драйвера копит лаг 0.5-2 с) и сам
    гасит камеру, когда её перестали просить: лампочка вебки не должна
    гореть в фоне без причины."""
    idle = float(CFG.get("vision.camera_idle_release_s", 60))
    while True:
        st = _cams.get(idx)
        if not st or not st["run"] or st["cap"] is None:
            break
        if idle > 0 and time.time() - st.get("want_ts", 0) > idle:
            log.info("Вебка %s закрыта по простою (%.0f с без запросов)",
                     idx, idle)
            camera_stop(idx)
            break
        ok, frame = st["cap"].read()
        if ok:
            st["frame"], st["ts"] = frame, time.time()
        else:
            time.sleep(0.05)
    log.debug("поток вебки %s остановлен", idx)


CAMERA_OFF = -1     # vision.camera_index == -1 -> камерой не пользуемся


def camera_enabled() -> bool:
    return int(CFG.get("vision.camera_index", 0)) >= 0


def camera_start(idx=None) -> bool:
    """Поднять вебку и держать живой, пока её просят.

    release() между КАДРАМИ не делаем: повторное открытие стоит секунды и
    иногда камера не отдаётся обратно. Но и держать вечно нельзя — у вебки
    горит лампочка, и «Сайка смотрит на меня» становится правдой даже
    когда никто ничего не просил. Компромисс: поток сам закрывает камеру
    через vision.camera_idle_release_s без запросов (см. _cam_loop)."""
    idx = int(CFG.get("vision.camera_index", 0) if idx is None else idx)
    if idx < 0:
        raise RuntimeError("камера выключена в меню 👁 — включи её там, "
                           "если нужно посмотреть")
    with _cam_lock:
        st = _cams.get(idx)
        if st and st["run"] and st["cap"] is not None:
            st["want_ts"] = time.time()
            return True
        st = {"cap": _cam_open(idx), "frame": None, "ts": 0.0, "run": True,
              "want_ts": time.time()}
        _cams[idx] = st
        st["thread"] = threading.Thread(target=_cam_loop, args=(idx,),
                                        daemon=True)
        st["thread"].start()
    for _ in range(60):               # дать драйверу отдать первый кадр
        if _cams.get(idx, {}).get("frame") is not None:
            return True
        time.sleep(0.05)
    return _cams.get(idx, {}).get("frame") is not None


def camera_stop(idx=None):
    with _cam_lock:
        targets = list(_cams.keys()) if idx is None else [int(idx)]
        for i in targets:
            st = _cams.pop(i, None)
            if not st:
                continue
            st["run"] = False
            try:
                if st["cap"] is not None:
                    st["cap"].release()
            except Exception:
                pass


def grab_camera(idx=None):
    """Свежий кадр с вебки как numpy BGR."""
    idx = int(CFG.get("vision.camera_index", 0) if idx is None else idx)
    if idx < 0:
        _ST["cam_err"] = "камера выключена в меню 👁"
        _ST["blocked"] += 1
        raise RuntimeError(_ST["cam_err"])
    try:
        if not camera_start(idx):
            raise RuntimeError("камера не отдала ни одного кадра")
        f = _cams.get(idx, {}).get("frame")
        if f is None:
            raise RuntimeError("пустой кадр вебки")
        _ST["cam_err"] = ""
        _ST["grabs"] += 1
        _ST["last_grab_ts"] = time.time()
        _ST["last_source"] = f"вебка {idx}"
        return f.copy()
    except Exception as e:
        _ST["cam_err"] = str(e)[:300]
        camera_stop(idx)              # чтобы следующая попытка открывала заново
        _cam_probe[idx] = {"ok": False, "error": str(e)[:200]}
        # Мёртвое устройство в списке — обычное дело (виртуальные камеры
        # Meta Quest / OBS видны всегда). Не сдаёмся молча: пробуем
        # остальные по порядку и запоминаем ту, что открылась.
        if CFG.get("vision.camera_autofallback", True):
            for c in list_cameras():
                j = int(c["id"])
                pr = _cam_probe.get(j, {})
                if j == idx or pr.get("ok") is False or pr.get("black"):
                    continue
                if not test_camera(j)["ok"]:
                    continue
                log.warning("Камера %s не работает — переключаюсь на %s (%s)",
                            idx, j, c.get("name", ""))
                _cfg_set("vision.camera_index", j)
                try:
                    if camera_start(j):
                        f = _cams.get(j, {}).get("frame")
                        if f is not None:
                            _ST["cam_err"] = ""
                            _ST["last_source"] = f"вебка {j}"
                            _ST["last_grab_ts"] = time.time()
                            return f.copy()
                except Exception:
                    camera_stop(j)
        raise


def grab(source: str):
    """Единая точка: 'screen' | 'camera' | 'screen:1' | 'camera:2'."""
    kind, _, num = (source or "screen").partition(":")
    n = int(num) if num.strip().lstrip("-").isdigit() else None
    return grab_camera(n) if kind.startswith("cam") else grab_screen(n)


# ══════════════ кадр -> то, что понимает модель ══════════════
def to_data_url(img, max_side=None, quality=None) -> str:
    """numpy BGR -> 'data:image/jpeg;base64,...' — формат, который уже
    ходит по проекту (см. _attach_image_openai в llm/manager.py)."""
    import cv2
    max_side = int(max_side or CFG.get("vision.max_side", 1280))
    quality = int(quality or CFG.get("vision.jpeg_quality", 80))
    # Аварийный выключатель на случай экзотического бэкенда, который всё же
    # отдаёт RGB. Симптом перепутанных каналов — «как будто наложили
    # фильтр»: синее становится красноватым, кожа синеет. Исключения при
    # этом нет, поэтому ловится только глазами. vision.swap_rb=true в
    # config чинит без правки кода.
    if CFG.get("vision.swap_rb", False):
        img = img[:, :, ::-1]
    h, w = img.shape[:2]
    k = max_side / float(max(h, w))
    if k < 1.0:
        img = cv2.resize(img, (int(w * k), int(h * k)),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img,
                           [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("не удалось закодировать кадр в JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode("ascii")


# ═══════════════ детектор смены сцены ═══════════════
# Двухэтапный dHash: NEAREST до 160x90 (читает 14 400 пикселей), потом
# AREA до 9x8. Замерено: 0.06 мс НЕЗАВИСИМО от исходного разрешения,
# против 10.7 мс у наивного AREA за один шаг и 17 мс у imagehash (там
# одна конверсия numpy->PIL дороже всего хеша). Поэтому imagehash и
# PySceneDetect в зависимости не тащим — только их идеи и пороги.
def dhash(img) -> int:
    import cv2
    small = cv2.resize(img, (160, 90), interpolation=cv2.INTER_NEAREST)
    g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (9, 8), interpolation=cv2.INTER_AREA)
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | int(g[y, x + 1] > g[y, x])
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


class SceneWatch:
    """Сцена изменилась или нет.

    ВАЖНАЯ ТОНКОСТЬ (поймана на тесте 2026-07-25). Сравнивать надо с
    ОПОРНЫМ кадром (той сценой, о которой уже сказали), а не с предыдущим.
    Наивный вариант «изменилось N кадров подряд» требует, чтобы картинка
    менялась НЕПРЕРЫВНО — а настоящая смена сцены выглядит ровно наоборот:
    один скачок и дальше покой. Такой детектор ловил бы только видео и
    анимацию и пропускал переключение окна, то есть главный случай.

    Поэтому правило двойное: кадр должен (1) отличаться от опорного и
    (2) УСТОЯТЬСЯ — держаться похожим на себя debounce опросов подряд.
    Это и отсекает курсор, мигающую каретку и всплывающие подсказки: они
    от опорного отличаются, но не держатся.
    """

    def __init__(self, thresh=None, debounce=None, min_interval_s=None):
        self.thresh = int(thresh or CFG.get("vision.scene_threshold", 6))
        self.debounce = max(1, int(debounce or CFG.get("vision.debounce", 2)))
        self.min_interval = float(
            min_interval_s if min_interval_s is not None
            else CFG.get("vision.min_interval_s", 45))
        self.reset()

    def reset(self):
        self._ref = None        # сцена, о которой уже сказали
        self._prev = None       # предыдущий кадр (для проверки «устоялось»)
        self._streak = 0
        self._last_fire = 0.0

    def feed(self, img) -> bool:
        h = dhash(img)
        prev, self._prev = self._prev, h
        if self._ref is None:
            self._ref = h
            return False
        if hamming(h, self._ref) < self.thresh:
            self._streak = 0            # вернулись к уже виденной сцене
            return False
        # отличается от опорной — ждём, пока новая картинка устоится
        still = prev is not None and hamming(h, prev) <= max(1, self.thresh // 3)
        self._streak = self._streak + 1 if still else 1
        if self._streak < self.debounce:
            return False
        if time.time() - self._last_fire < self.min_interval:
            return False
        self._ref = h                   # новая сцена становится опорной
        self._streak = 0
        self._last_fire = time.time()
        return True


# ═══════════════ режим наблюдения (real-time) ═══════════════
# Фоновый поток смотрит с частотой vision.watch_hz, гоняет детектор и,
# когда сцена реально сменилась, отдаёт кадр наружу. Холостой ход —
# доли процента одного ядра: сам детектор стоит 0.06 мс.
#
# ВЫКЛЮЧЕН ПО УМОЛЧАНИЮ. Это единственный режим, где Сайка смотрит на
# экран без просьбы, поэтому включается только руками владельца, и
# чёрный список окон проверяется на КАЖДОМ кадре, а не один раз.
_watch = {"thread": None, "run": False, "cb": None}


def watch_start(callback, source=None) -> bool:
    """callback(data_url, source, note) вызывается при смене сцены."""
    if not enabled():
        log.warning("watch: глаза выключены — не запускаю")
        return False
    src = source or CFG.get("vision.watch_source", "screen")
    watch_stop()
    _watch["cb"] = callback
    _watch["run"] = True
    _ST["watch_on"], _ST["watch_src"] = True, src
    _watch["thread"] = threading.Thread(target=_watch_loop, args=(src,),
                                        daemon=True)
    _watch["thread"].start()
    log.info("Наблюдение включено: %s, %.1f Гц", src,
             float(CFG.get("vision.watch_hz", 2)))
    return True


def watch_stop():
    _watch["run"] = False
    _ST["watch_on"] = False
    _ST["watch_src"] = ""


def watch_toggle(source=None, callback=None) -> bool:
    if _ST["watch_on"]:
        watch_stop()
        return False
    return watch_start(callback or _watch["cb"], source)


def _watch_loop(src: str):
    hz = max(0.2, float(CFG.get("vision.watch_hz", 2)))
    period = 1.0 / hz
    sw = SceneWatch()
    misses = 0
    while _watch["run"]:
        t0 = time.time()
        try:
            if not enabled():
                break
            if src.startswith("screen"):
                blocked = _window_blocked()
                if blocked:
                    # окно из чёрного списка: не смотрим ВООБЩЕ и сбрасываем
                    # детектор, чтобы после переключения не сработало
                    # «изменилось» на само возвращение к нормальному окну
                    sw.reset()
                    time.sleep(period)
                    continue
            img = grab(src)
            misses = 0
            if sw.feed(img):
                _ST["watch_events"] += 1
                url = to_data_url(img)
                note = ("### Ты смотришь по своей воле (режим наблюдения) и "
                        "ЗАМЕТИЛА, что картинка изменилась — кадр приложен. "
                        "Скажи коротко и по-своему, что видишь и что об этом "
                        "думаешь. Не пересказывай кадр по пунктам и не "
                        "начинай длинный разбор без просьбы.")
                cb = _watch["cb"]
                if cb:
                    try:
                        cb(url, src, note)
                    except Exception as e:
                        log.debug("watch callback: %s", e)
        except Exception as e:
            misses += 1
            log.debug("watch tick: %s", e)
            if misses >= 10:
                log.warning("Наблюдение остановлено: захват не работает (%s)", e)
                break
            time.sleep(1.0)
        dt = time.time() - t0
        if dt < period:
            time.sleep(period - dt)
    _ST["watch_on"] = False
    log.info("Наблюдение выключено")


# ═══════════════ живое окно для интерфейса ═══════════════
def mjpeg(source="camera", fps=None, max_side=480, quality=65):
    """Генератор multipart/x-mixed-replace — обычный <img src> в браузере
    показывает это как живое видео, без WebRTC и без единой зависимости.

    Пока поток читают, camera_start обновляет want_ts, поэтому вебка не
    закроется по простою; закрыл окно — через минуту сама погаснет.
    Кадры мелкие (480 px, q65): это превью «что видит камера», а не
    видеозвонок, и оно не должно отъедать канал у самой Сайки."""
    fps = float(fps or CFG.get("vision.preview_fps", 10))
    period = 1.0 / max(1.0, fps)
    import cv2
    boundary = b"--saikaframe"
    idle_stop = time.time() + float(CFG.get("vision.preview_max_s", 600))
    while time.time() < idle_stop:
        t0 = time.time()
        try:
            if not enabled():
                break
            img = grab(source)
            h, w = img.shape[:2]
            k = max_side / float(max(h, w))
            if k < 1.0:
                img = cv2.resize(img, (int(w * k), int(h * k)),
                                 interpolation=cv2.INTER_AREA)
            if CFG.get("vision.swap_rb", False):
                img = img[:, :, ::-1]
            ok, buf = cv2.imencode(".jpg", img,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), quality])
            if not ok:
                break
            data = buf.tobytes()
            yield (boundary + b"\r\nContent-Type: image/jpeg\r\n"
                   b"Content-Length: " + str(len(data)).encode()
                   + b"\r\n\r\n" + data + b"\r\n")
        except GeneratorExit:
            raise
        except Exception as e:
            log.debug("mjpeg %s: %s", source, e)
            break
        dt = time.time() - t0
        if dt < period:
            time.sleep(period - dt)


# ═══════════════ намерение человека посмотреть ═══════════════
# Экран — приватное, поэтому берём его ТОЛЬКО по явной фразе. Камера мягче
# (смотрит в комнату, а не в переписку), но правило то же.
_SCREEN_INTENT = re.compile(
    r"(экран|монитор|скрин|скриншот|десктоп|рабоч\w+ стол|"
    r"что (?:у меня|тут|здесь|сейчас) (?:на экране|открыт|происходит)|"
    r"(?:посмотр|погляд|глян|взглян|смотр)\w*\s+(?:на\s+)?(?:мой |моё |это )?"
    r"(?:экран|монитор|окно|сюда)|"
    r"видишь\s+(?:что|это|экран|окно)|покажу тебе экран)", re.I)
_CAMERA_INTENT = re.compile(
    r"(камер|вебк|веб-камер|webcam|в объектив|"
    r"(?:посмотр|погляд|глян|взглян|смотр)\w*\s+(?:на\s+)?(?:меня|нас|"
    r"в камеру|через камеру)|"
    r"как я выгляжу|видишь меня|что у меня в комнате|кто тут)", re.I)
# «оцени/как тебе/что скажешь» рядом с просьбой посмотреть — просят не
# описание, а МНЕНИЕ. Отдельный режим промпта, см. auto_look.
_JUDGE_INTENT = re.compile(
    r"(оцен|как теб|что скаж|нравит|красив|норм ли|годно|стоит ли|"
    r"что не так|что поправ|критик|мнение|как получилось|как вышло)", re.I)


# Короткое «посмотри» / «что видишь» без объекта. Живой человек в ответ
# смотрит туда, куда смотрит обычно, а не переспрашивает «куда именно».
# Держим ЖЁСТКО: только когда во фразе больше ничего нет, иначе «посмотри
# что там в интернете» утащит нас в захват экрана.
_BARE_LOOK = re.compile(
    r"^\W*(?:а|ну|давай|сайка|плиз)?\s*"
    r"(?:посмотр\w*|погляд\w*|глян\w*|взглян\w*|смотри)"
    r"(?:[\s-]?ка)?\s*(?:сама|сюда|туда)?\W*$", re.I)
_WHAT_SEE = re.compile(
    r"^\W*(?:а|и|ну|сайка)?\s*(?:сейчас\s+)?(?:что|чего)\s+(?:ты\s+)?"
    r"(?:там\s+|сейчас\s+)?видишь\W*$"
    r"|видишь\s+(?:ли\s+)?что[-\s]?нибудь"
    r"|ты\s+что[-\s]?(?:то|нибудь)\s+видишь", re.I)
# «экран 2», «на втором мониторе», «второй экран»
_MON_NUM = re.compile(
    r"(?:экран|монитор|дисплей)\w*\s*[№#]?\s*(\d)"
    r"|(перв|втор|трет|четверт)\w*\s+(?:экран|монитор|дисплей)", re.I)
_ORD = {"перв": 1, "втор": 2, "трет": 3, "четверт": 4}


def which_monitor(user_text: str):
    """Номер дисплея из фразы (0-based) или None. «экран 2» -> 1."""
    m = _MON_NUM.search(user_text or "")
    if not m:
        return None
    if m.group(1):
        n = int(m.group(1))
    else:
        n = _ORD.get(m.group(2).lower(), 0)
    return max(0, n - 1) if n else None


def wants(user_text: str) -> str:
    """'screen' | 'camera' | '' — чего просит человек."""
    t = (user_text or "").strip()
    if not t:
        return ""
    if _CAMERA_INTENT.search(t):
        return "camera"
    if _SCREEN_INTENT.search(t):
        return "screen"
    # голое «посмотри» / «что видишь» — смотрим туда, куда смотрим обычно
    if _BARE_LOOK.search(t) or _WHAT_SEE.search(t):
        d = str(CFG.get("vision.default_source", "screen"))
        if d.startswith("cam") and not camera_enabled():
            return "screen"
        return "camera" if d.startswith("cam") else "screen"
    return ""


def auto_look(user_text: str):
    """ГЛАВНЫЙ путь зрения: человек попросил посмотреть — сервер сам
    делает кадр и подкладывает его в тот же запрос как обычную картинку.

    Почему так, а не инструментом: работает с ЛЮБОЙ моделью, включая те,
    что не умеют function calling (у нас таких большинство — см.
    llm.tools_broken в config). Инструменты look_* остаются для сильных.

    Возвращает (data_url | None, подсказка-в-промпт | None).
    """
    kind = wants(user_text)
    if not kind:
        return None, None
    if not enabled():
        _ST["blocked"] += 1
        return None, ("### Человек просит посмотреть, но ГЛАЗА ВЫКЛЮЧЕНЫ "
                      "тумблером 👁 в интерфейсе. Скажи об этом честно и "
                      "по-своему, предложи включить. Ничего не выдумывай "
                      "про то, что «видишь».")
    if kind == "camera" and not camera_enabled():
        _ST["blocked"] += 1
        return None, ("### Человек просит взглянуть в камеру, но КАМЕРА "
                      "ВЫКЛЮЧЕНА в меню 👁 — работает только экран. Скажи "
                      "честно и по-своему, предложи включить. Ничего не "
                      "выдумывай про то, что видишь в комнате.")
    if kind == "screen":
        blocked = _window_blocked()
        if blocked:
            _ST["blocked"] += 1
            log.warning("Захват экрана заблокирован: в заголовке окна %r",
                        blocked)
            return None, ("### Человек просит посмотреть на экран, но "
                          f"впереди окно из чёрного списка («{blocked}») — "
                          "банк, пароли или приватный просмотр. Ты НЕ "
                          "СМОТРЕЛА. Скажи честно, что такое окно не "
                          "снимаешь, и предложи переключиться на нужное. "
                          "Ничего не выдумывай про содержимое.")
    try:
        src = kind
        if kind == "screen":
            mon = which_monitor(user_text)     # «глянь на экран 2»
            if mon is not None:
                src = f"screen:{mon}"
        img = grab(src)
        url = to_data_url(img)
        log.info("Зрение: кадр %s (%s), ~%d КБ", src, _ST["last_source"],
                 len(url) // 1400)
    except Exception as e:
        log.warning("Зрение не смогло сделать кадр (%s): %s", kind, e)
        return None, ("### Ты пыталась посмотреть, но захват не удался: "
                      f"{e}. Скажи честно, что глаз сейчас открыть не "
                      "получилось, и не выдумывай содержимое.")
    where = "ЭКРАНА" if kind == "screen" else "ВЕБКИ"
    base = (f"### Ты только что посмотрела СВОИМИ ГЛАЗАМИ: это кадр {where} "
            "прямо сейчас, он приложен к сообщению. Отвечай по тому, что "
            "реально видишь. Не называй это «присланным фото» — ты смотрела "
            "сама, в реальном времени.")
    if _JUDGE_INTENT.search(user_text or ""):
        base += ("\nУ тебя просят МНЕНИЕ, а не опись. Скажи, что цепляет и "
                 "что мешает: композиция, цвет, чёткость, детали, логика "
                 "изображения. Своими словами и со своим вкусом — но только "
                 "про то, что действительно видно на кадре. Пара конкретных "
                 "замечаний ценнее общей похвалы.")
    return url, base


# ═══════════════ инструменты для сильных моделей ═══════════════
SCHEMAS = [
    {"type": "function", "function": {
        "name": "look_screen",
        "description": ("Посмотреть СВОИМИ ГЛАЗАМИ на экран владельца прямо "
                        "сейчас и получить описание того, что там. Зови "
                        "ТОЛЬКО когда человек прямо просит посмотреть на "
                        "экран или спрашивает, что у него открыто. Никогда — "
                        "по своей инициативе."),
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string",
                         "description": "что именно нужно разглядеть"},
            "monitor": {"type": "integer",
                        "description": "номер дисплея, если их несколько"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "look_camera",
        "description": ("Посмотреть в вебку — увидеть комнату и человека "
                        "прямо сейчас. Зови, когда просят взглянуть на них, "
                        "в камеру, или спрашивают, что происходит в комнате."),
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string",
                         "description": "что именно разглядеть"},
            "camera": {"type": "integer",
                       "description": "номер камеры, если их несколько"}},
            "required": []}}},
]
NAMES = {"look_screen", "look_camera"}


def _describe(url: str, question: str) -> str:
    """Описать кадр. Сначала пробуем текущую модель (если она зрячая),
    иначе одалживаем глаза у vision-модели парка — механизм уже есть в
    main.py для OCR присланных картинок, здесь тот же."""
    from server import capabilities as caps
    from server.llm import manager as llm
    q = (question or "").strip() or "Опиши, что видишь. Коротко и по делу."
    cur = CFG.get("llm.model", "")
    tries = []
    if caps.vision(cur) is not False:
        tries.append((CFG.get("llm.backend", "lmstudio"), cur))
    pick = caps.pick_vision_model(llm.list_models(), llm.loaded_models())
    if pick and tuple(pick) not in tries:
        tries.append(tuple(pick))
    for backend, model in tries:
        try:
            txt = llm.ask_specific(backend, model,
                                   [{"role": "user", "content": q}], image=url)
            if txt.strip():
                return txt.strip()
        except Exception as e:
            log.debug("описание кадра через %s/%s: %s", backend, model, e)
    return ""


def call(name: str, arguments) -> str:
    import json as _json
    if isinstance(arguments, str):
        try:
            arguments = _json.loads(arguments)
        except Exception:
            arguments = {}
    arguments = arguments or {}
    if not enabled():
        return ("отказ: глаза выключены тумблером 👁 в интерфейсе. Скажи "
                "человеку об этом и предложи включить. Не выдумывай, что "
                "видишь.")
    if name == "look_camera" and arguments.get("camera") is None \
            and not camera_enabled():
        return ("отказ: камера выключена в меню 👁. Скажи человеку об этом "
                "и предложи включить. Экран при этом смотреть можно.")
    if name == "look_screen":
        blocked = _window_blocked()
        if blocked:
            _ST["blocked"] += 1
            return (f"отказ: впереди окно из чёрного списка («{blocked}») — "
                    "банк, пароли или приватный просмотр. Кадр НЕ сделан. "
                    "Скажи честно и предложи переключить окно.")
    try:
        if name == "look_screen":
            img = grab_screen(arguments.get("monitor"))
        else:
            img = grab_camera(arguments.get("camera"))
        url = to_data_url(img)
    except Exception as e:
        log.warning("%s: %s", name, e)
        return f"не получилось открыть глаза: {e}"
    txt = _describe(url, str(arguments.get("question", ""))[:300])
    if not txt:
        return ("кадр сделан, но описать некому: ни текущая модель, ни одна "
                "модель в парке не умеет смотреть на картинки. Скажи честно.")
    where = "на экране" if name == "look_screen" else "в камере"
    return f"я посмотрела {where} и вижу: {txt}"
