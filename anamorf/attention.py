"""ЧТО СЕЙЧАС ПЕРЕД ГЛАЗАМИ (2026-08-19).

Владелец: «она должна научиться видеть запущенные проги и удерживать
внимание на местах работы — как ты, когда работаешь с файлами: ты же не
запускаешь новый проводник, чтобы что-то сделать. И это должно быть
человеку ВИЗУАЛЬНО видно: что и где она работает, где читает, что видит».

Модуль — витрина, а не логика. Инструменты кладут сюда след («сняла экран
2», «прочитала окно X», «открыла вкладку Y»), а интерфейс это показывает.
Ничего не решает и никуда не лезет: если модуль сломается, руки продолжат
работать как раньше.

Живая причина: в диалоге 19.08 человек трижды спрашивал «что ты видишь на
втором экране» и не мог проверить ответ — снимала-то она первый. Когда
видно, ЧТО именно она сняла и откуда прочитала, враньё становится опечаткой.
"""
import logging
import time

log = logging.getLogger("saika.attention")

MAX_TRACE = 12

_LOOK = {"what": "", "where": "", "detail": "", "ts": 0.0,
         "thumb": "", "thumb_ts": 0.0}
_READ = {"what": "", "where": "", "detail": "", "ts": 0.0}
_TRACE = []          # последние следы: [{kind, what, where, ts}]


def _push(kind: str, what: str, where: str):
    _TRACE.append({"kind": kind, "what": what[:120], "where": where[:80],
                   "ts": time.time()})
    while len(_TRACE) > MAX_TRACE:
        _TRACE.pop(0)


def note_look(what: str, where: str = "", detail: str = ""):
    """Посмотрела: what — «экран 2», «камера»; detail — что разглядела."""
    _LOOK.update(what=str(what or "")[:80], where=str(where or "")[:80],
                 detail=str(detail or "")[:300], ts=time.time())
    _push("глаза", str(what or ""), str(where or ""))
    log.debug("смотрю: %s (%s)", what, where)


def note_read(what: str, where: str = "", detail: str = ""):
    """Прочитала: what — что за текст, where — откуда (окно, страница)."""
    _READ.update(what=str(what or "")[:120], where=str(where or "")[:80],
                 detail=str(detail or "")[:300], ts=time.time())
    _push("чтение", str(what or ""), str(where or ""))
    log.debug("читаю: %s (%s)", what, where)


def note_act(what: str, where: str = ""):
    """Сделала руками: «открыла вкладку», «перешла в папку»."""
    _push("руки", str(what or ""), str(where or ""))


# ВЗГЛЯД СОПРОВОЖДАЕТ ДЕЙСТВИЕ (2026-08-19, владелец: «как бы сопровождая
# действия взглядом»). Когда руки что-то делают в окне, туда же переходит и
# взгляд: пишем место и снимаем МАЛЕНЬКУЮ картинку того экрана — не для
# модели (это дорого), а для человека, чтобы в интерфейсе было видно, где
# она сейчас работает. Не чаще раза в THUMB_EVERY_S и всегда в отдельном
# потоке: рука не должна ждать картинку.
THUMB_EVERY_S = 2.5
_thumb_lock = __import__("threading").Lock()


def _grab_thumb(monitor: int):
    try:
        from anamorf import vision
        if not vision.enabled():
            return
        img = vision.grab_screen(max(0, int(monitor) - 1))
        _LOOK["thumb"] = vision.to_data_url(img, max_side=360, quality=55)
        _LOOK["thumb_ts"] = time.time()
    except Exception as e:
        log.debug("миниатюра не снялась: %s", e)


def follow(place: dict, what: str = ""):
    """Действие в окне -> туда же взгляд. place — окно из pc_control."""
    try:
        title = str(place.get("title") or "")[:60]
        mon = int(place.get("monitor") or 0)
        where = f"экран {mon}" if mon else "рабочий стол"
        note_act(what or "работаю", f"{title} ({where})")
        _LOOK.update(what=f"{title}", where=where, ts=time.time())
        try:
            from anamorf import highlight
            highlight.show_window(place, f"{what or 'работаю'}: {title}")
        except Exception as e:
            log.debug("подсветка окна: %s", e)
        if time.time() - float(_LOOK.get("thumb_ts") or 0) < THUMB_EVERY_S:
            return
        if not _thumb_lock.locked():
            import threading

            def job():
                with _thumb_lock:
                    _grab_thumb(mon)
            threading.Thread(target=job, daemon=True).start()
    except Exception as e:
        log.debug("взгляд за руками не пошёл: %s", e)


def _ago(ts: float) -> int:
    return int(time.time() - ts) if ts else -1


def snapshot() -> dict:
    """Для интерфейса: где работаем, что видим, что читаем."""
    places = []
    try:
        from anamorf import pc_control
        places = pc_control.work_places()
    except Exception as e:
        log.debug("места работы недоступны: %s", e)
    eyes = {}
    try:
        from anamorf import vision
        eyes = {**vision.busy(), "last": dict(vision.LAST),
                "ago": _ago(vision.LAST.get("ts", 0))}
    except Exception as e:
        log.debug("нагрузка зрения недоступна: %s", e)
    glow = {}
    try:
        from anamorf import highlight
        from anamorf.config import CFG as _C
        glow = {**highlight.state(),
                "color": str(_C.get("pc.highlight_color", "#ff9a3c")),
                "px": int(_C.get("pc.highlight_glow", highlight.GLOW_PX)),
                "ms": int(_C.get("pc.highlight_ms", 30000))}
    except Exception as e:
        log.debug("состояние свечения недоступно: %s", e)
    return {
        "glow": glow,
        "eyes": eyes,
        "places": places,
        "look": {**_LOOK, "ago": _ago(_LOOK["ts"])} if _LOOK["ts"] else None,
        "read": {**_READ, "ago": _ago(_READ["ts"])} if _READ["ts"] else None,
        "trace": [{**t, "ago": _ago(t["ts"])} for t in reversed(_TRACE)],
    }
