"""Руки ВНУТРИ окон: смотреть, кликать, печатать, жать клавиши (2026-07-29).

ПРОСЬБА ВЛАДЕЛЬЦА, дословно: «я вызываю ютуб и хочу чтобы она в строке
поиска ввела канал и открыла; я говорю — она тыкает; говорю на полный
экран — она делает; потом браузер на пол экрана, запусти тг, найди в чате
Виталю и напиши ему „заходи в дискорд“ — последовательно, перед отправкой
спросив: текст готов, отправляем?»

pc_control умеет ОКНА (запустить, свернуть, разложить). Этот модуль — то,
что ВНУТРИ окна. Строится на практиках больших систем автоматизации:

  1. ДЕРЕВО ДОСТУПНОСТИ, НЕ ПИКСЕЛИ. Microsoft Power Automate, скринридеры
     и Playwright не ищут кнопку по картинке — они спрашивают у окна список
     его элементов (UI Automation). Кнопка находится ПО ИМЕНИ, работает на
     любом разрешении и не ломается от смены темы. У нас: see() отдаёт
     модели список элементов окна, click() нажимает по имени.
  2. ГЛУБОКИЕ ССЫЛКИ ПРЕЖДЕ КЛИКОВ. Siri и Google Assistant не печатают
     запрос в строку поиска ютуба — они открывают сразу адрес результатов.
     Один шаг вместо четырёх, и ломаться нечему. У нас: web_open().
     Кликать по странице надо только ПОСЛЕ этого («какой клип?» — click).
  3. ПОСМОТРЕЛ -> СДЕЛАЛ -> ПРОВЕРИЛ. Каждое действие возвращает, что
     реально произошло; «нажала» без проверки — это враньё с задержкой.
  4. НЕОБРАТИМОЕ — ТОЛЬКО С ПОДТВЕРЖДЕНИЯ. Отправка сообщения в чат не
     откатывается. Поэтому type_text НИКОГДА не жмёт Enter сам: набрать
     текст и отправить его — два разных инструмента, и между ними модель
     обязана спросить «текст готов, отправляем?». Так устроен attended-режим
     в промышленном RPA: робот печатает, человек утверждает.
  5. СЛОВАРЬ ЧЕЛОВЕКА. «Виталя» в телеграме — тот же принцип, что
     «корел» в программах: спросить один раз, запомнить навсегда
     (app_memory уже это умеет, словарь общий).

ЗАВИСИМОСТИ. Печать и клавиши — голый ctypes (SendInput), без установки
чего-либо. Дерево элементов — pywinauto (uia): она в extra фичи «pc», без
неё see()/click() честно объясняют, что поставить, а печать и клавиши
работают всё равно.
"""
from __future__ import annotations

import logging
import os
import re
import time
import urllib.parse

log = logging.getLogger("saika.pc")

_IS_WIN = os.name == "nt"


# ─────────────────────────── клавиши (ctypes) ───────────────────────────
# Виртуальные коды клавиш Windows. Имена — как их говорит человек.
_VK = {
    "enter": 0x0D, "ввод": 0x0D, "энтер": 0x0D,
    "esc": 0x1B, "эскейп": 0x1B, "отмена": 0x1B,
    "tab": 0x09, "таб": 0x09,
    "space": 0x20, "пробел": 0x20,
    "backspace": 0x08,
    "delete": 0x2E, "del": 0x2E,
    "up": 0x26, "вверх": 0x26, "down": 0x28, "вниз": 0x28,
    "left": 0x25, "влево": 0x25, "right": 0x27, "вправо": 0x27,
    "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
    "f5": 0x74, "f11": 0x7A,
    "ctrl": 0x11, "контрол": 0x11, "shift": 0x10, "шифт": 0x10,
    "alt": 0x12, "альт": 0x12, "win": 0x5B,
    "плюс": 0xBB, "минус": 0xBD, "insert": 0x2D, "printscreen": 0x2C,
    # ВСЕ БУКВЫ И ЦИФРЫ (2026-08-13). Раньше в таблице лежало двенадцать
    # букв — те, что понадобились по случаю. Любое сочетание с остальными
    # («ctrl+b» в редакторе, «ctrl+r» перезагрузка) молча упиралось в «не
    # знаю клавишу», и половина программ оставалась неуправляемой.
    **{chr(c): c - 32 for c in range(ord("a"), ord("z") + 1)},
    **{str(d): 0x30 + d for d in range(10)},
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
    # МЕДИА-КЛАВИШИ (2026-08-13, мысль владельца: системными комбинациями
    # можно управлять большинством приложений). Эти — особенные: Windows
    # доставляет их ПЛЕЕРУ НАПРЯМУЮ, минуя фокус. Работают в Chrome с
    # ютубом, в Spotify, в VLC — где угодно, и даже когда впереди чужое
    # окно. Для «останови музыку» это правильный ответ: не надо ни лезть в
    # чужой браузер, ни угадывать, что сейчас играет.
    "медиа_пауза": 0xB3, "медиа_стоп": 0xB2,
    "медиа_следующий": 0xB0, "медиа_предыдущий": 0xB1,
    "громкость_выкл": 0xAD, "громкость_тише": 0xAE, "громкость_громче": 0xAF,
}

# Клавиши, которые НЕ требуют фокуса: система маршрутизирует их сама.
GLOBAL_KEYS = {0xB3, 0xB2, 0xB0, 0xB1, 0xAD, 0xAE, 0xAF}

# Что человек называет словами, а не сочетанием. «полный экран» в браузере
# и на ютубе — разные клавиши: F11 — браузер целиком, F — плеер ютуба.
_COMBOS = {
    "полный экран": "f11", "фулскрин": "f11",
    "полный экран видео": "f", "развернуть видео": "f",
    "обновить": "f5", "обнови страницу": "f5",
    "выдели всё": "ctrl+a", "скопируй": "ctrl+c", "вставь": "ctrl+v",
    "отмени": "ctrl+z", "сохрани": "ctrl+s",
    "новая вкладка": "ctrl+t", "закрой вкладку": "ctrl+w",
    "поиск": "ctrl+k", "найди на странице": "ctrl+f",
}


def _sendinput_keys(vks: list):
    """Нажать и отпустить сочетание через SendInput. Он кладёт события в ту
    же очередь, что и настоящая клавиатура — приложения не отличают."""
    import ctypes
    from ctypes import wintypes

    PUL = ctypes.POINTER(ctypes.c_ulong)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", PUL)]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    def one(vk, up):
        inp = INPUT()
        inp.type = 1                       # INPUT_KEYBOARD
        inp.ki = KEYBDINPUT(vk, 0, 2 if up else 0, 0, None)  # KEYEVENTF_KEYUP
        return inp

    seq = [one(v, False) for v in vks] + [one(v, True) for v in reversed(vks)]
    arr = (INPUT * len(seq))(*seq)
    ctypes.windll.user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))


def press(combo: str) -> str:
    """Нажать клавишу или сочетание: «enter», «ctrl+t», «полный экран».

    Enter здесь — ОТПРАВКА. Модель зовёт press("enter") в чате только после
    того, как человек подтвердил текст. Это правило протокола, не кода:
    код не знает, чат перед ним или блокнот."""
    if not _IS_WIN:
        return "клавиши доступны только в Windows"
    s = (combo or "").strip().lower()
    s = _COMBOS.get(s, s)
    vks = []
    for part in s.replace(" ", "").split("+"):
        vk = _VK.get(part)
        if vk is None:
            return (f"Не знаю клавишу «{part}». Знаю: enter, esc, tab, "
                    "стрелки, f5, f11 и сочетания вида ctrl+t.")
        vks.append(vk)
    if not vks:
        return "пустое сочетание"
    try:
        _sendinput_keys(vks)
        return f"Нажала {s}."
    except Exception as e:
        return f"Не смогла нажать {s}: {e}"


# ═══════════════════════════════════════════════════════════════════
# УПРАВЛЕНИЕ ПРИЛОЖЕНИЯМИ ОБЩИМИ СОЧЕТАНИЯМИ (2026-08-13, мысль владельца:
# «можем полноценно сделать управление приложениями, не обязательно через
# ключ — чисто системными комбинациями можно управлять большинством»).
#
# И это сильнее возни с API каждой программы: сочетания одинаковы почти
# везде, потому что так договорились тридцать лет назад. Ctrl+S сохраняет
# в Word, в Blender, в Photoshop и в блокноте.
#
# Чего этому подходу не хватало раньше — знания, КУДА попадёт нажатие.
# Теперь оно есть (server/situation.py), поэтому сначала выводим нужное
# окно вперёд, УБЕЖДАЕМСЯ, что оно впереди, и только потом жмём. Без этой
# проверки Ctrl+W однажды закрыл человеку чат в чужой программе.
# ═══════════════════════════════════════════════════════════════════

ACTIONS = {
    # правка — работает почти во всём
    "сохранить": "ctrl+s", "сохранить как": "ctrl+shift+s",
    "отменить": "ctrl+z", "вернуть": "ctrl+y", "повторить": "ctrl+y",
    "копировать": "ctrl+c", "вставить": "ctrl+v", "вырезать": "ctrl+x",
    "выделить всё": "ctrl+a", "удалить": "delete",
    "найти": "ctrl+f", "заменить": "ctrl+h",
    "создать": "ctrl+n", "открыть": "ctrl+o", "печать": "ctrl+p",
    "дублировать": "ctrl+d", "группа": "ctrl+g",
    # окно и вид
    "закрыть": "ctrl+w", "выйти": "alt+f4", "закрыть программу": "alt+f4",
    "свернуть": "win+down", "развернуть": "win+up",
    "полный экран": "f11", "обновить": "f5", "жёстко обновить": "ctrl+f5",
    "крупнее": "ctrl+плюс", "мельче": "ctrl+минус", "обычный размер": "ctrl+0",
    "следующая вкладка": "ctrl+tab", "предыдущая вкладка": "ctrl+shift+tab",
    "новая вкладка": "ctrl+t", "вернуть вкладку": "ctrl+shift+t",
    "адресная строка": "ctrl+l", "назад": "alt+left", "вперёд": "alt+right",
    # плеер — ГЛОБАЛЬНЫЕ, фокус не нужен
    "пауза": "медиа_пауза", "играй": "медиа_пауза", "продолжи": "медиа_пауза",
    "стоп": "медиа_стоп", "останови": "медиа_пауза",
    "следующий трек": "медиа_следующий", "следующая песня": "медиа_следующий",
    "предыдущий трек": "медиа_предыдущий",
    "громче": "громкость_громче", "тише": "громкость_тише",
    "без звука": "громкость_выкл", "заглушить": "громкость_выкл",
}


def _is_global(combo: str) -> bool:
    vks = [_VK.get(p) for p in _COMBOS.get(combo, combo).replace(" ", "").split("+")]
    return len(vks) == 1 and vks[0] in GLOBAL_KEYS


def app_action(action: str, app: str = "") -> str:
    """Сделать в программе то, что просят, общим сочетанием клавиш.

    app пустой — действуем в том окне, что впереди (человек смотрит на
    него, значит его и имел в виду)."""
    a = (action or "").strip().lower()
    combo = ACTIONS.get(a) or _COMBOS.get(a) or a
    if _is_global(combo):
        # плееру и громкости фокус не нужен — система доставит сама
        return (press(combo) + " Эта клавиша работает поверх всего — "
                "плеер услышит её в любом окне, даже если впереди "
                "чужая программа.")
    if not _IS_WIN:
        return "клавиши доступны только в Windows"
    from server import pc_control as pc
    if app:
        r = pc.window_focus(app)
        if "не наш" in r.lower() or "нет" in r.lower()[:12]:
            return (f"Окна «{app}» не нашла — нажимать вслепую не буду. "
                    f"{r}")
        time.sleep(0.35)
    w = pc._foreground()
    front = str((w or {}).get("title") or "")
    if app and app.lower() not in front.lower():
        # проверка ГЛАЗАМИ, а не по вере в успех window_focus
        return (f"Хотела нажать «{a}» в «{app}», но впереди сейчас "
                f"«{front[:50]}». Не жму: попадёт не туда. Скажи человеку, "
                "пусть выведет нужное окно.")
    if not front:
        return "не вижу, какое окно впереди — вслепую не жму"
    out = press(combo)
    return f"{out} В окне «{front[:50]}»."


def type_text(text: str) -> str:
    """Напечатать текст в активное окно — куда сейчас стоит курсор.

    Печатает ЮНИКОДОМ (KEYEVENTF_UNICODE): раскладка клавиатуры не важна,
    русский и латиница идут как есть. Enter НЕ нажимает никогда — отправка
    только отдельным press("enter") после подтверждения человека."""
    if not _IS_WIN:
        return "печать доступна только в Windows"
    t = (text or "").replace("\r", "")
    if not t:
        return "нечего печатать"
    import ctypes
    from ctypes import wintypes

    PUL = ctypes.POINTER(ctypes.c_ulong)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", PUL)]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    seq = []
    for ch in t:
        for up in (0, 2):                  # KEYEVENTF_UNICODE (+KEYUP)
            inp = INPUT()
            inp.type = 1
            inp.ki = KEYBDINPUT(0, ord(ch), 4 | up, 0, None)
            seq.append(inp)
    try:
        arr = (INPUT * len(seq))(*seq)
        ctypes.windll.user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))
        short = t if len(t) <= 60 else t[:57] + "..."
        return (f"Напечатала: «{short}». НЕ отправлено — спроси человека, "
                "готов ли текст, и только потом жми enter.")
    except Exception as e:
        return f"Не смогла напечатать: {e}"


# ─────────────────────── глубокие ссылки (браузер) ───────────────────────
# Поиск на сайте — это адрес, а не четыре клика. Открываем сразу результаты.
#
# КАТАЛОГ (2026-07-29, просьба владельца: «добавь все возможные популярные
# сайты, от музыки до платформ»). Одна запись = (адрес поиска с {q}, главная,
# все имена, которыми сайт называют голосом). Имя канала/трека человек
# говорит по-русски, а адреса латинские — поэтому всегда открываем ПОИСК
# сайта, а не гадаем прямой адрес: там найдётся и кириллицей, дальше клик.
# Поиска нет (мессенджеры, почта) — вторым полем главная, первым пустое.
_CATALOG = [
    # видео и стримы
    ("https://www.youtube.com/results?search_query={q}",
     "https://www.youtube.com", ("youtube", "ютуб", "ютюб", "youtube music")),
    ("https://www.twitch.tv/search?term={q}",
     "https://www.twitch.tv", ("twitch", "твич")),
    ("https://rutube.ru/search/?query={q}",
     "https://rutube.ru", ("rutube", "рутуб")),
    ("https://vkvideo.ru/?q={q}",
     "https://vkvideo.ru", ("вк видео", "vk видео", "vkvideo")),
    # кино и сериалы
    ("https://www.kinopoisk.ru/index.php?kp_query={q}",
     "https://www.kinopoisk.ru", ("кинопоиск", "kinopoisk")),
    ("https://www.ivi.ru/search/?q={q}", "https://www.ivi.ru",
     ("иви", "ivi")),
    ("", "https://okko.tv", ("окко", "okko")),
    ("", "https://www.netflix.com", ("нетфликс", "netflix")),
    # музыка
    ("https://music.yandex.ru/search?text={q}", "https://music.yandex.ru",
     ("яндекс музыка", "музыка", "yandex music")),
    ("https://open.spotify.com/search/{q}", "https://open.spotify.com",
     ("spotify", "спотифай")),
    ("https://soundcloud.com/search?q={q}", "https://soundcloud.com",
     ("soundcloud", "саундклауд")),
    ("https://zvuk.com/search?query={q}", "https://zvuk.com",
     ("звук", "zvuk")),
    # поисковики и знания
    ("https://www.google.com/search?q={q}", "https://www.google.com",
     ("google", "гугл")),
    ("https://yandex.ru/search/?text={q}", "https://ya.ru",
     ("яндекс", "yandex")),
    ("https://ru.wikipedia.org/w/index.php?search={q}",
     "https://ru.wikipedia.org", ("википедия", "вики", "wikipedia")),
    ("https://yandex.ru/maps/?text={q}", "https://yandex.ru/maps",
     ("карты", "яндекс карты")),
    ("https://www.google.com/maps/search/{q}", "https://www.google.com/maps",
     ("гугл карты", "google maps")),
    ("https://translate.yandex.ru/?text={q}", "https://translate.yandex.ru",
     ("переводчик", "яндекс переводчик")),
    ("", "https://yandex.ru/pogoda", ("погода",)),
    # соцсети и общение
    ("https://vk.com/search?q={q}", "https://vk.com", ("вк", "вконтакте", "vk")),
    ("", "https://ok.ru", ("одноклассники",)),
    ("https://x.com/search?q={q}", "https://x.com",
     ("твиттер", "twitter", "икс")),
    ("https://www.reddit.com/search/?q={q}", "https://www.reddit.com",
     ("reddit", "реддит")),
    ("https://www.tiktok.com/search?q={q}", "https://www.tiktok.com",
     ("tiktok", "тикток", "тик ток")),
    ("", "https://web.telegram.org", ("телеграм веб", "telegram web")),
    ("", "https://web.whatsapp.com", ("ватсап", "whatsapp")),
    ("", "https://discord.com/app", ("дискорд", "discord")),
    ("https://dzen.ru/search?query={q}", "https://dzen.ru", ("дзен", "dzen")),
    ("https://pikabu.ru/search?q={q}", "https://pikabu.ru",
     ("пикабу", "pikabu")),
    # магазины
    ("https://www.ozon.ru/search/?text={q}", "https://www.ozon.ru",
     ("озон", "ozon")),
    ("https://www.wildberries.ru/catalog/0/search.aspx?search={q}",
     "https://www.wildberries.ru", ("вайлдберриз", "вб", "wildberries")),
    ("https://market.yandex.ru/search?text={q}", "https://market.yandex.ru",
     ("маркет", "яндекс маркет")),
    ("https://www.avito.ru/all?q={q}", "https://www.avito.ru",
     ("авито", "avito")),
    ("https://aliexpress.ru/wholesale?SearchText={q}", "https://aliexpress.ru",
     ("алиэкспресс", "али", "aliexpress")),
    ("https://www.amazon.com/s?k={q}", "https://www.amazon.com",
     ("амазон", "amazon")),
    ("https://www.ebay.com/sch/i.html?_nkw={q}", "https://www.ebay.com",
     ("ебей", "ebay")),
    ("https://www.dns-shop.ru/search/?q={q}", "https://www.dns-shop.ru",
     ("днс", "dns")),
    # игры
    ("https://store.steampowered.com/search/?term={q}",
     "https://store.steampowered.com", ("стим", "steam")),
    ("https://store.epicgames.com/ru/browse?q={q}",
     "https://store.epicgames.com", ("эпик", "epic games", "епик")),
    ("https://stopgame.ru/search/?s={q}", "https://stopgame.ru",
     ("стопгейм", "stopgame")),
    # разработка и статьи
    ("https://github.com/search?q={q}", "https://github.com",
     ("гитхаб", "github", "гит")),
    ("https://habr.com/ru/search/?q={q}", "https://habr.com",
     ("хабр", "habr")),
    ("https://stackoverflow.com/search?q={q}", "https://stackoverflow.com",
     ("stackoverflow", "стековерфлоу")),
    ("https://huggingface.co/models?search={q}", "https://huggingface.co",
     ("хаггингфейс", "huggingface", "обнимашки")),
    # почта
    ("", "https://mail.google.com", ("гугл почта", "gmail", "джимейл")),
    ("", "https://mail.yandex.ru", ("яндекс почта",)),
    ("", "https://mail.ru", ("почта", "майл", "mail")),
]

_SITES, _HOME = {}, {}
for _srch, _home, _names in _CATALOG:
    for _n in _names:
        if _srch:
            _SITES[_n] = _srch
        _HOME[_n] = _home


def guess_from_phrase(phrase: str):
    """Достать (сайт, запрос) из живой фразы: «открой ютуб и включи музычку»
    -> («ютуб», «музычку»). Нужна, когда модель позвала web_open БЕЗ
    аргументов (2026-07-29: gemma写ла [tool_code] web_open [/tool_code] —
    и «ничего не произошло», хотя всё было сказано во фразе человека)."""
    p = (phrase or "").lower()
    site = ""
    for n in sorted(_HOME, key=len, reverse=True):
        if n in p:
            site = n
            break
    if not site:
        return "", ""
    # вырезаем всё СЛОВО с именем сайта: «на твиче» — «твич» внутри
    # словоформы, простой replace оставлял огрызок «е» в запросе
    q = re.sub(r"[\wёЁ'-]*" + re.escape(site) + r"[\wёЁ'-]*", " ", p)
    junk = {"открой", "открыть", "запусти", "включи", "вруби", "поставь",
            "найди", "покажи", "зайди", "перейди", "мне", "и", "на", "в",
            "пожалуйста", "давай", "просто", "какую-нибудь", "какой-нибудь",
            "что-нибудь", "ну", "там", "сайт", "сайте", "страницу"}
    words = [w for w in re.findall(r"[\wёЁ'-]+", q) if w not in junk]
    return site, " ".join(words).strip()


# слова, которые означают МЕСТО, а не предмет поиска
_PLATFORM_WORDS = {
    "youtube", "ютуб", "ютюб", "google", "гугл", "google chrome", "chrome",
    "хром", "яндекс", "yandex", "браузер", "интернет", "сеть", "twitch",
    "твич", "rutube", "рутуб", "vk", "вк", "вконтакте", "telegram",
    "телеграм", "spotify", "спотифай", "кинопоиск", "steam", "стим",
    "discord", "дискорд", "википедия", "wikipedia", "duckduckgo",
}


def web_open(site: str, query: str = "") -> str:
    """Открыть сайт, сразу с поиском, если есть запрос.

    «включи на ютубе музыкальный канал» — это web_open("ютуб",
    "музыкальный канал"): один шаг, страница результатов уже на экране,
    дальше человек говорит «какой клип» — и это уже click()."""
    s = (site or "").strip().lower().rstrip("/")
    q = (query or "").strip()
    if not s:
        return "какой сайт открыть?"
    # НАЗВАНИЕ ПЛОЩАДКИ — НЕ ЗАПРОС (2026-08-13, живой промах: «Открой
    # Google Chrome, э-э, YouTube» превратилось в {query: "youtube",
    # site: "youtube"} — она искала «youtube» НА ютубе и открыла выдачу
    # вместо главной. Человек назвал, КУДА идти, а не ЧТО искать; модель
    # положила это слово в оба поля.)
    _ql = q.lower().strip(" .,!?")
    if _ql and (_ql == s or _ql in _PLATFORM_WORDS
                or _ql.replace(" ", "") == s.replace(" ", "")):
        q = ""
    if q and s in _SITES:
        url = _SITES[s].format(q=urllib.parse.quote_plus(q))
    elif s in _HOME:
        url = _HOME[s]
    elif "." in s:                          # прямой адрес: kinopoisk.ru
        url = s if s.startswith("http") else "https://" + s
        if q:
            url = ("https://www.google.com/search?q=" +
                   urllib.parse.quote_plus(q + " site:" + s))
    else:                                   # неизвестный сайт — через гугл
        url = ("https://www.google.com/search?q=" +
               urllib.parse.quote_plus((q + " " + s).strip()))
    # ОДНО ОКНО, А НЕ ДВА (2026-08-13, живой отказ владельца: «если уж
    # открыла окно, то там и работала»). Было так: web_open запускал
    # СИСТЕМНЫЙ браузер через startfile, а web_research/web_list работали в
    # СВОЁМ окне Playwright. Получалось два разных браузера: она открыла
    # человеку YouTube в его Chrome, а искала музыку у себя — и связи между
    # этими окнами нет никакой. Теперь всё идёт в её окно: там она видит
    # DOM, умеет скроллить, закрывать баннеры и печатать в строку сайта.
    try:
        from server import browser_hands
        if browser_hands.available() and browser_hands._chromium_present():
            return browser_hands.open_url(url)
    except Exception as e:
        log.debug("web_open: своё окно недоступно (%s) — иду системным", e)
    try:
        if _IS_WIN:
            os.startfile(url)               # noqa: S606 — браузер по умолчанию
        else:
            import subprocess
            subprocess.Popen(["xdg-open", url])
        return (f"Открыла {url} в системном браузере (своё окно недоступно). "
                "Подожди секунду-другую, потом see() покажет, что на странице.")
    except Exception as e:
        return f"Не смогла открыть {url}: {e}"


# ──────────────────── дерево элементов окна (UIA) ────────────────────
# ЗАЩИТА ОТ ЗАВИСАНИЯ (2026-07-29, второй живой стоп за вечер: «два запроса
# и умер» — очередь «отвечу следом» копилась минутами). Ограничение обхода
# не спасает, когда виснет САМ вызов COM: UI Automation ходит в чужой
# процесс, и если тот занят или у потока не тот COM-режим — вызов может не
# вернуться никогда. Правило большое и простое, как в промышленной
# автоматизации: чужому процессу НЕ доверяют свой поток. Всё, что трогает
# UIA, выполняется в отдельном потоке с жёстким таймаутом; не успел —
# честный отказ за секунды, поток-висельник остаётся умирать в одиночестве,
# а диалог живёт дальше.
_uia_imported = False


def _guarded(fn, what: str):
    """Выполнить fn() в отдельном потоке. Таймаут щедрее на первый раз:
    первый импорт pywinauto строит кэш comtypes, это десятки секунд."""
    global _uia_imported
    import queue as _q
    import threading
    timeout = 8.0 if _uia_imported else 25.0
    box = _q.Queue()

    def worker():
        global _uia_imported
        try:
            box.put(fn())
            _uia_imported = True
        except Exception as e:      # pragma: no cover
            box.put(f"не вышло ({what}): {e}")

    threading.Thread(target=worker, daemon=True,
                     name=f"uia-{what}").start()
    try:
        return box.get(timeout=timeout)
    except _q.Empty:
        log.warning("UIA завис на «%s» (> %.0fс) — бросаю поток", what,
                    timeout)
        return (f"Окно не ответило за {timeout:.0f} секунд — оно занято или "
                "не отдаёт свои элементы. Я НЕ зависла, просто бросила "
                "попытку. Скажи человеку и предложи попробовать ещё раз "
                "или другим способом (клавишами: tab, стрелки, enter).")
_INTERESTING = {
    "Button": "кнопка", "Hyperlink": "ссылка", "Edit": "поле ввода",
    "ListItem": "пункт", "MenuItem": "меню", "TabItem": "вкладка",
    "CheckBox": "галочка", "ComboBox": "список", "RadioButton": "выбор",
    "Document": "документ", "Image": "картинка", "Text": "текст",
}


def _uia_window():
    """Активное окно как объект pywinauto (uia). None + причина, если
    нельзя."""
    if not _IS_WIN:
        return None, "дерево элементов доступно только в Windows"
    try:
        from pywinauto import Desktop
    except Exception:
        return None, ("нужна библиотека pywinauto — она поставится сама при "
                      "следующем запуске start.bat")
    try:
        import ctypes
        h = ctypes.windll.user32.GetForegroundWindow()
        if not h:
            return None, "нет активного окна"
        return Desktop(backend="uia").window(handle=h), ""
    except Exception as e:
        return None, f"не смогла подключиться к окну: {e}"


def _elements(win, limit=120) -> list:
    """Плоский список интересных элементов окна: (имя, тип, ссылка).

    ОБХОД СВОИМИ НОГАМИ, НЕ descendants() (2026-07-29, живое зависание:
    «введи в поисковую строку в телеграме» — и Сайка замолчала на минуту,
    очередь «отвечу следом» копилась). descendants() у pywinauto сначала
    собирает ВСЕ элементы окна до дна, у телеграма и браузера их тысячи —
    это десятки секунд, и весь диалоговый поток стоит. Идём в ширину сами:
    предел по глубине, по числу узлов и — главное — по ВРЕМЕНИ. Лучше
    отдать 40 элементов за полторы секунды, чем всё дерево за минуту."""
    # СНАЧАЛА СТРАНИЦА, ПОТОМ РАМКА (2026-07-29, живой промах: на ютубе
    # она увидела только «Свернуть, Развернуть, Закрыть» — бюджет обхода
    # уходил на оболочку браузера, а Document с самой страницей лежит
    # глубже и до него дело не доходило). Узел Document — это содержимое
    # вкладки; его поддерево обходим В ПЕРВУЮ очередь.
    from collections import deque
    out = []
    deadline = time.time() + 5.0
    budget = 1500
    try:
        queue = deque([(win, 0, False)])    # (узел, глубина, внутри страницы)
        while queue and budget > 0 and len(out) < limit:
            if time.time() > deadline:
                log.debug("обход элементов остановлен по времени "
                          "(%d найдено)", len(out))
                break
            node, depth, indoc = queue.popleft()
            try:
                kids = list(node.children())
            except Exception:
                continue
            grab = []                       # дети страницы — вперёд очереди
            for el in kids:
                budget -= 1
                if budget <= 0 or len(out) >= limit:
                    break
                try:
                    ct = el.element_info.control_type
                    nm = (el.element_info.name or "").strip()
                except Exception:
                    continue
                if ct in _INTERESTING and nm and len(nm) <= 90:
                    out.append((nm, ct, el))
                if depth < 20:
                    if indoc or ct == "Document":
                        grab.append((el, depth + 1, True))
                    else:
                        queue.append((el, depth + 1, False))
            queue.extendleft(reversed(grab))
    except Exception as e:
        log.debug("обход элементов оборвался: %s", e)
    return out


def see() -> str:
    """Что видно в активном окне: кнопки, ссылки, поля — по именам.

    Это глаза для кликов. Порядок работы модели: see() -> выбрать имя ->
    click(имя). Никогда не выдумывать имя элемента из головы."""
    return _guarded(_see_impl, "прочитать окно")


def _see_impl() -> str:
    win, err = _uia_window()
    if win is None:
        return err
    try:
        title = win.window_text()[:60]
    except Exception:
        title = "?"
    els = _elements(win)
    if not els:
        return (f"Окно «{title}» не отдаёт элементы (бывает у игр и старых "
                "программ). Остаются клавиши: tab, стрелки, enter.")
    lines, seen = [], set()
    for nm, ct, _el in els:
        key = (nm.lower(), ct)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"{_INTERESTING[ct]}: {nm}")
    return f"Окно «{title}». Элементы:\n" + "\n".join(lines[:80])


def click(name: str, double: bool = False) -> str:
    """Кликнуть по элементу активного окна ПО ИМЕНИ (как в see()).

    Ищем нечётко — человек говорит «плейлист лучшее», а элемент зовётся
    «Лучшее — плейлист · 50 видео». Но при слабом совпадении не гадаем:
    честно возвращаем варианты, пусть модель уточнит у человека."""
    q = (name or "").strip()
    if not q:
        return "по чему кликнуть?"
    return _guarded(lambda: _click_impl(q, double), "кликнуть " + q[:20])


def _click_impl(q: str, double: bool) -> str:
    win, err = _uia_window()
    if win is None:
        return err
    els = _elements(win)
    if not els:
        return "окно не отдаёт элементы — попробуй клавишами (tab/стрелки)"

    # «САМЫЙ ПЕРВЫЙ» — это НОМЕР, не имя (2026-07-29, живой промах: человек
    # сказал «включи самый первый плейлист», а мы искали элемент с именем
    # «самый первый»). Порядковые слова выбирают N-ю ссылку/пункт страницы.
    _ordmap = (("перв", 0), ("втор", 1), ("трет", 2), ("четверт", 3),
               ("пят", 4), ("послед", -1))
    _hit = next((i for w, i in _ordmap if w in q.lower()), None)
    if _hit is not None:
        content = [t for t in els if t[1] in ("Hyperlink", "ListItem",
                                              "Image")] or els
        try:
            nm, ct, el = content[_hit]
        except IndexError:
            nm, ct, el = content[-1]
        try:
            el.set_focus()
        except Exception:
            pass
        try:
            try:
                el.invoke()
            except Exception:
                el.click_input()
            return f"Кликнула {_INTERESTING.get(ct, ct)}: «{nm}»."
        except Exception as e:
            return f"Нашла «{nm}», но кликнуть не смогла: {e}"

    from server.pc_control import _score
    scored = [(nm, ct, el, _score(nm, q.lower())) for nm, ct, el in els]
    scored = [t for t in scored if t[3] > 0]
    scored.sort(key=lambda t: -t[3])
    if not scored:
        near = ", ".join(nm for nm, _c, _e in els[:6])
        return f"Не вижу «{q}» в этом окне. Рядом есть: {near}"
    nm, ct, el, sc = scored[0]
    if sc < 40 and len(scored) > 1:
        opts = "; ".join(f"«{t[0]}»" for t in scored[:3])
        return (f"Не уверена, что ты про это. Похожие элементы: {opts}. "
                "Спроси человека, какой именно, и кликни по точному имени.")
    try:
        el.set_focus()
    except Exception:
        pass
    try:
        if double:
            el.double_click_input()
        else:
            try:
                el.invoke()                 # честное «нажать» через UIA
            except Exception:
                el.click_input()            # иначе — курсором по центру
        return f"Кликнула: {_INTERESTING.get(ct, ct)} «{nm}»."
    except Exception as e:
        return f"Нашла «{nm}», но кликнуть не смогла: {e}"


def type_into(field: str, text: str) -> str:
    """Найти ПОЛЕ ВВОДА по имени, кликнуть в него и напечатать текст
    (2026-07-29, просьба владельца: «чтобы можно было голосом просить
    вписывать текст в строки ввода»).

    «Впиши в строку поиска ужин на двоих» — одно действие вместо трёх:
    поле находится по имени из дерева окна (как в see()), клик ставит
    курсор, текст печатается юникодом. Отправки НЕТ — enter отдельно,
    после подтверждения человека, как и всюду."""
    t = (text or "").strip()
    if not t:
        return "нечего вписывать"
    return _guarded(lambda: _type_into_impl(field, t), "вписать в поле")


def _type_into_impl(field: str, t: str) -> str:
    win, err = _uia_window()
    if win is None:
        # дерева нет — печатаем хотя бы туда, где курсор, и говорим об этом
        r = type_text(t)
        return r + f" (поле «{field}» не искала: {err})"
    fields = [(nm, ct, el) for nm, ct, el in _elements(win)
              if ct in ("Edit", "ComboBox", "Document")]
    if not fields:
        return ("В этом окне не вижу полей ввода. Если курсор уже стоит в "
                "нужном месте — просто keyboard_type.")
    q = (field or "").strip().lower()
    target = None
    if q:
        from server.pc_control import _score
        scored = [(nm, ct, el, _score(nm, q)) for nm, ct, el in fields]
        scored.sort(key=lambda x: -x[3])
        if scored[0][3] > 0:
            target = scored[0]
    if target is None:
        if len(fields) == 1:
            # поле одно — очевидно, о нём и речь, даже если имя не совпало
            nm, ct, el = fields[0]
            target = (nm, ct, el, 0)
        else:
            lst = "; ".join(f"«{nm}»" for nm, _c, _e in fields[:5])
            return (f"Не поняла, в какое поле: вижу {lst}. Назови точнее "
                    "или спроси человека.")
    nm, ct, el, _sc = target
    try:
        el.set_focus()
    except Exception:
        pass
    try:
        el.click_input()                    # курсор в поле
        time.sleep(0.15)
    except Exception as e:
        return f"Нашла поле «{nm}», но кликнуть в него не смогла: {e}"
    r = type_text(t)
    if r.startswith("Напечатала"):
        return f"Вписала в «{nm}»: «{t[:60]}». НЕ отправлено — спроси " \
               "человека, готов ли текст, и только потом жми enter."
    return r


def scroll(direction: str = "вниз", times: int = 3) -> str:
    """Прокрутить активное окно колесом."""
    if not _IS_WIN:
        return "прокрутка доступна только в Windows"
    import ctypes
    d = -120 if (direction or "").strip().lower() in ("вниз", "down") else 120
    try:
        for _ in range(max(1, min(int(times or 3), 15))):
            ctypes.windll.user32.mouse_event(0x0800, 0, 0, d, 0)
            time.sleep(0.05)
        return f"Прокрутила {direction}."
    except Exception as e:
        return f"Не смогла прокрутить: {e}"
