"""ОТПРАВКА — ТОЛЬКО ПО ПОДТВЕРЖДЕНИЮ (2026-08-20, правило владельца).

Дословно: «отправка любого диалога ввода должна быть через подтверждение
отправить. Единственная механика, где не нужны подтверждения, — когда явно
просят открыть ту или иную инфу в браузере: там она относительно запроса
простраивает цикл работы и работает с поиском».

ПОВОД. В окне чата с ИИ-соавтором она напечатала ссылку и НАЖАЛА ENTER —
сообщение ушло живому собеседнику от имени человека. Владелец, увидев его:
«по поводу отправки сообщения — как ей удалось в целом отправить тебе».

Технически это было позволено всегда. Запрет существовал только в
докстринге ui_hands.press: «Enter здесь — ОТПРАВКА, модель зовёт его
только после подтверждения человека. Это правило протокола, не кода: код
не знает, чат перед ним или блокнот». Правило, которое знает только
модель, — это не запрет, а пожелание: одна модель его читает, другая нет,
третья читает и всё равно жмёт. Отправленное сообщение не отзывается.

Код может знать больше, чем думал прежний комментарий:

  * мы сами только что печатали в это окно — значит, там поле ввода;
  * какая это программа — мессенджер, почта, чат с ИИ или блокнот;
  * просил ли человек ИМЕННО СЕЙЧАС открыть что-то в интернете.

Третий пункт и есть исключение владельца. Когда он сказал «найди то-то в
гугле», Enter в адресной строке — это часть цикла поиска, а не отправка
сообщения человеку. Такой цикл открывается явной просьбой, живёт минуту и
касается только браузера.

ЧТО СЧИТАЕТСЯ ОТПРАВКОЙ. Enter и его родня (ctrl+enter, shift+enter) —
в окне, где мы печатали, или в программе-разговоре. Всё остальное
(«ctrl+s», «f5», стрелки) правила не касается: это не отправка.

КАК ВЫГЛЯДИТ ЖИВЬЁМ. «Напечатала: „...“ в Telegram. Отправлять?» — и она
ждёт. Человек говорит «отправляй» — уходит. Говорит «не надо» — стирает.
Молчит — через две минуты предложение само протухает: несказанное «да» не
считается согласием.
"""
import logging
import time

from anamorf.config import CFG

log = logging.getLogger("saika.send")

# Программы, где Enter почти всегда отправляет ЖИВОМУ ЧЕЛОВЕКУ.
TALK_APPS = {
    "telegram", "whatsapp", "discord", "slack", "teams", "viber", "skype",
    "thunderbird", "outlook", "claude", "cowork", "chatgpt", "codex",
    "zapzap", "signal", "element", "vk", "messenger",
}

# что мы печатали и куда — ставит ui_hands.type_text
TYPED = {"hwnd": 0, "title": "", "proc": "", "text": "", "ts": 0.0}
# открытый цикл работы с браузером — ставит web_open и поиск по просьбе
WEB = {"until": 0.0, "why": ""}
# предложение отправить, которое ждёт человека
PEND = {"on": False, "text": "", "where": "", "ts": 0.0}

SEND_KEYS = {"enter", "ctrl+enter", "shift+enter", "ввод", "энтер"}


def _life() -> float:
    return float(CFG.get("hands.send_ask_life_s", 120))


def note_typed(text: str, w: dict = None):
    """ui_hands.type_text зовёт это после каждой печати."""
    w = w or {}
    TYPED.update(hwnd=int(w.get("hwnd") or 0),
                 title=str(w.get("title") or ""),
                 proc=str(w.get("proc") or "").lower().replace(".exe", ""),
                 text=str(text or "")[:200], ts=time.time())


def allow_web(why: str = "", seconds: float = 0.0):
    """Человек попросил открыть/найти что-то в интернете — на это время
    Enter в браузере не спрашивает подтверждения. Исключение владельца."""
    WEB.update(until=time.time() + (seconds or float(
        CFG.get("hands.web_cycle_s", 60))), why=why)


def web_open_now() -> bool:
    return time.time() < WEB["until"]


def _is_browser(proc: str) -> bool:
    return proc in ("chrome", "msedge", "firefox", "browser", "opera",
                    "brave", "yandex", "vivaldi", "chromium")


def _target() -> dict:
    """Куда сейчас уйдёт нажатие."""
    try:
        from anamorf import pc_control
        return pc_control._foreground() or {}
    except Exception:
        return {}


def check(combo: str) -> str:
    """Пусто — жать можно. Иначе — текст, который надо сказать человеку
    вместо нажатия."""
    key = (combo or "").strip().lower()
    if key not in SEND_KEYS:
        return ""
    if not CFG.get("hands.confirm_send", True):
        return ""
    w = _target()
    proc = str(w.get("proc") or "").lower().replace(".exe", "")
    title = str(w.get("title") or "")[:50]

    # ИСКЛЮЧЕНИЕ: открытый цикл работы с браузером по прямой просьбе
    if _is_browser(proc) and web_open_now():
        return ""

    fresh = (time.time() - TYPED["ts"]) < _life()
    typed_here = fresh and (not TYPED["hwnd"] or not w.get("hwnd")
                            or int(TYPED["hwnd"]) == int(w.get("hwnd") or 0))
    talk = proc in TALK_APPS
    if not (typed_here or talk):
        return ""                      # блокнот, редактор, консоль — не отправка

    PEND.update(on=True, text=(TYPED["text"] if typed_here else ""),
                where=(title or proc or "это окно"), ts=time.time())
    what = f": «{PEND['text'][:80]}»" if PEND["text"] else ""
    log.info("Отправку придержала: %s (%s)", PEND["where"], key)
    return (f"Готово к отправке в «{PEND['where']}»{what}. "
            "ОТПРАВЛЯТЬ? Сама не отправляю — скажи «отправляй» или "
            "«не надо».")


def pending() -> dict:
    if PEND["on"] and time.time() - PEND["ts"] > _life():
        PEND.update(on=False)          # несказанное «да» — не согласие
    return dict(PEND) if PEND["on"] else {}


def confirm() -> str:
    """Человек сказал «отправляй»."""
    if not pending():
        return "А отправлять нечего — я ничего не держу наготове."
    where = PEND["where"]
    PEND.update(on=False)
    try:
        from anamorf import ui_hands
        r = ui_hands.press("enter", _confirmed=True)
    except Exception as e:
        return f"Не смогла нажать ввод: {e}"
    log.info("Отправила по подтверждению: %s", where)
    return f"Отправила в «{where}». ({r})"


def cancel(why: str = "") -> str:
    if not pending():
        return "Нечего отменять."
    where = PEND["where"]
    PEND.update(on=False)
    log.info("Отправку отменил человек: %s (%s)", where, why or "без причины")
    return f"Не отправляю. Текст так и остался в «{where}» — сотри или поправь."
