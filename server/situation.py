"""ГДЕ Я СЕЙЧАС — картина происходящего для промпта.

2026-08-13, слова владельца после инцидента с переключённым чатом: «не в
предохранителе дело, а в понимании, что она делает и где».

И это точнее. Предохранитель говорит «не бей вслепую» — но бить вслепую
приходится потому, что ГЛАЗ НЕТ. Она отправляла Ctrl+Tab «в браузер», не
зная, что впереди десктопное приложение. Искала папку, не зная, что
рабочий корень указывает на несуществующий диск. Открывала окно и не
понимала, видит ли его человек. Каждый раз догадка вместо факта.

Здесь факты. Дёшево (список окон — вызов ctypes, остальное уже посчитано)
и КОРОТКО: это не отчёт, а то, что человек знает про свой стол не глядя —
какое окно впереди, что у него открыто, где он стоит.

Почему в dyn_parts, а не в системный промпт: обстановка меняется каждую
минуту, а системная часть должна лежать в KV-кэше неподвижно.
"""
import logging

from server.config import CFG

log = logging.getLogger("saika.situation")

_BROWSERS = ("chrome", "chromium", "firefox", "edge", "opera", "yandex",
             "brave", "vivaldi", "safari", "tor browser")


def _front():
    try:
        from server import pc_control as pc
        w = pc._foreground()
        if not w:
            return "", "", False
        title = str(w.get("title") or "")
        proc = str(w.get("proc") or "")
        hay = (title + " " + proc).lower()
        return title, proc, any(b in hay for b in _BROWSERS)
    except Exception as e:
        log.debug("переднее окно: %s", e)
        return "", "", False


def _own_browser():
    """Своё окно Playwright: открыто ли и что в нём."""
    try:
        from server import browser_hands as bh
        if not bh.is_open():
            return ""
        try:
            # СПРАВКА НИЧЕГО НЕ ОТКРЫВАЕТ (2026-08-14, владелец: «она
            # конкретно так троит с этим браузером, нахер она постоянно
            # его вызывает… причём как будто просто так иногда»). И правда
            # просто так: строчка «в твоём браузере открыто вот это»
            # спрашивала заголовок через _ensure_page — а тот, не найдя
            # живой страницы, СОЗДАЁТ её. Отсюда about:blank, всплывающий
            # сам по себе посреди разговора: браузер открывала не модель,
            # а сборка промпта, каждый ход.
            #
            # Смотреть можно, трогать нельзя: берём заголовок ТОЛЬКО у
            # уже существующей страницы, ничего не создавая и не
            # поднимая. Нет её — так и пишем.
            page = bh._post(lambda c: c.get("page"), timeout=0.5)
            if page is None:
                return "открыто"
            return (page.title() or page.url or "")[:70]
        except Exception:
            return "открыто"
    except Exception:
        return ""


def _where_in_files():
    try:
        from server import pc_control as pc
        return str(pc.here() or "")
    except Exception:
        return ""


def _windows_short(limit=6):
    try:
        from server import pc_control as pc
        ws = pc.windows(include_minimized=False) or []
    except Exception:
        return []
    out, seen = [], set()
    for w in ws:
        name = (str(w.get("proc") or "").replace(".exe", "")
                or str(w.get("title") or "")[:20])
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(name)
        if len(out) >= limit:
            break
    return out


def block() -> str:
    """Строка для промпта. Пусто — значит сказать нечего."""
    if not CFG.get("situation.enabled", True):
        return ""
    try:
        title, proc, is_br = _front()
        own = _own_browser()
        here = _where_in_files()
        wins = _windows_short()
    except Exception as e:
        log.debug("обстановка не собралась: %s", e)
        return ""
    lines = []
    if title:
        kind = "браузер" if is_br else "НЕ браузер"
        lines.append(f"- впереди окно: «{title[:60]}»"
                     + (f" ({proc})" if proc else "") + f" — это {kind}")
    if own:
        lines.append(f"- ТВОЁ окно браузера: открыто, там «{own}»")
    else:
        lines.append("- твоего окна браузера сейчас нет "
                     "(web_open/web_list его откроют)")
    if here:
        lines.append(f"- в файлах ты стоишь в: {here}")
    if wins:
        lines.append("- ещё открыто: " + ", ".join(wins))
    if not lines:
        return ""
    return (
        "### Где ты сейчас (факт, обновляется каждый ход):\n"
        + "\n".join(lines) + "\n"
        "Действия попадают В ТО ОКНО, ЧТО ВПЕРЕДИ. Нужно другое — сначала "
        "выведи его вперёд (window_focus), а не жми вслепую. Вкладки и "
        "клавиши в чужом окне — это чужая работа человека, туда нельзя. "
        "Свой браузер — твой, в нём можно всё.")
