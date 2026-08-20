"""ДИКТОВКА В ПОЛЕ: СМОТРИТ НА СТРОКУ И ЖДЁТ ГОЛОС (2026-08-19).

Владелец: «например, когда я её попрошу ввести что-то в поисковую строку —
понятно дело, что она туда переводит взгляд и, удаляя оттуда ввод, ждёт мой
голос, что я туда хочу вписать. Ну так должно в идеале работать с любыми
прогами».

Так и сделано, и именно в этом порядке:
  1. находим поле (UI Automation — это система, а не браузер, поэтому
     работает в любой программе: браузер, телега, проводник, игра-лаунчер);
  2. ставим в него курсор и по просьбе чистим;
  3. обводим ЕГО свечением с подписью «жду, что вписать» — человек видит,
     куда именно уедет его следующая фраза;
  4. следующая фраза человека не идёт в модель, а печатается в поле.

ПОЧЕМУ НЕ ЧЕРЕЗ МОДЕЛЬ. Если фразу «ужин на двоих» отдать модели, она
ответит на неё как на реплику в разговоре — и в поле не попадёт ничего.
Здесь диктовка перехватывает ход раньше всех, как рефлекс.

Ждём недолго (TTL): человек мог передумать и заговорить о другом. Слова
отмены разрывают ожидание сразу.
"""
import logging
import re
import time

log = logging.getLogger("saika.dictation")

TTL_S = 45.0

_ST = {"on": False, "field": "", "rect": None, "win": "", "ts": 0.0,
       "submit": False}

_CANCEL = re.compile(
    r"^\s*(отмена|отмени|не надо|неважно|забудь|стоп|хватит|потом|"
    r"передумал\w*|отставить|ничего)\b", re.I)


def arm(field: str, rect=None, win: str = "", submit: bool = False):
    _ST.update(on=True, field=str(field or "поле"), rect=rect,
               win=str(win or ""), ts=time.time(), submit=bool(submit))
    log.info("Жду диктовку в «%s» (%s)", _ST["field"], _ST["win"][:40])


def armed() -> bool:
    if not _ST["on"]:
        return False
    if time.time() - _ST["ts"] > TTL_S:
        cancel("время вышло")
        return False
    return True


def cancel(why: str = ""):
    if _ST["on"]:
        log.info("Диктовка отменена: %s", why or "без причины")
    _ST.update(on=False, field="", rect=None, win="", ts=0.0, submit=False)


def is_cancel(text: str) -> bool:
    return bool(_CANCEL.match(text or ""))


def state() -> dict:
    return {**_ST, "left": max(0, int(TTL_S - (time.time() - _ST["ts"])))
            if _ST["on"] else 0}


def note() -> str:
    """Строка в промпт — чтобы модель не пыталась «ответить» на диктовку."""
    if not armed():
        return ""
    return (f"Сейчас ты ждёшь, ЧТО вписать в «{_ST['field']}»"
            + (f" (окно «{_ST['win'][:40]}»)" if _ST["win"] else "")
            + ". Следующая фраза человека — это ТЕКСТ ДЛЯ ПОЛЯ, а не "
              "реплика в разговоре. Отвечать на неё по смыслу не нужно.")


def feed(text: str) -> str:
    """Напечатать сказанное в поле, которое ждёт. Возвращает, что вышло."""
    if not armed():
        return ""
    field, win, submit = _ST["field"], _ST["win"], _ST["submit"]
    rect = _ST["rect"]
    cancel("вписала")
    t = (text or "").strip()
    if not t:
        return ""
    try:
        from server import highlight
        if rect:
            highlight.show(rect, f"вписываю: {t[:40]}", ms=6000)
    except Exception as e:
        log.debug("подсветка поля: %s", e)
    try:
        from server import ui_hands
        r = ui_hands.type_text(t)
    except Exception as e:
        return f"не смогла напечатать: {e}"
    if submit:
        # ОТПРАВКА — ЧЕРЕЗ ПОДТВЕРЖДЕНИЕ (2026-08-20). Здесь Enter жался
        # сразу, если модель прислала submit=True, — то есть диктовка была
        # ещё одной дверцей мимо правила. press() теперь спрашивает сам
        # (server/send_gate.py) и возвращает вопрос вместо нажатия; если
        # спрашивать не о чем (адресная строка в открытом цикле браузера,
        # блокнот) — жмёт как раньше.
        try:
            from server import ui_hands
            r = ui_hands.press("enter")
            if str(r).startswith("Нажала"):
                return f"Вписала в «{field}»: «{t[:60]}» и отправила."
            return f"Вписала в «{field}»: «{t[:60]}». {r}"
        except Exception as e:
            log.debug("enter не нажался: %s", e)
    if str(r).startswith("Напечатала"):
        return (f"Вписала в «{field}»: «{t[:60]}». НЕ отправляла — скажи "
                "«отправь», если готово.")
    return str(r)
