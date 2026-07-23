"""Клиент HandsPC — внешнего сервиса инструментов («руки» Сайки).

HandsPC живёт в соседней папке (C:\\AI\\HandsPC) со своим venv и отдаёт
инструменты (web_search, fetch_page, …) по HTTP. Сайка на каждый диалог
спрашивает список схем; если сервис не запущен — просто работает без
инструментов, ничего не ломается. Новые инструменты в HandsPC подхватываются
автоматически, код Сайки менять не надо.
"""
import logging
import time

import requests

from server.config import CFG

log = logging.getLogger("saika.tools")
_cache = {"t": 0.0, "schemas": []}

# Режим внутреннего импульса (мысль самой себе, пользователь не писал).
# В нём Сайке можно трогать ТОЛЬКО СВОЁ: закрыть свой браузер, выключить
# себя, глянуть дев-доску. Окна/файлы пользователя — под жёстким запретом
# на уровне кода (однажды в idle она «прибралась» и закрыла проводник
# пользователя — смешно, но нельзя).
IMPULSE_MODE = {"on": False}
_IMPULSE_SAFE = {"close_browser", "shutdown_self",
                 "devboard_read", "devboard_add"}

# ЛОКАЛЬНЫЕ инструменты Сайки (не через HandsPC): дев-доска — чтобы она могла
# свериться со своей историей разработки и дописывать в блокнот сама.
_LOCAL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "devboard_read",
        "description": ("Прочитать свою дев-доску (карту разработки): что "
                        "готово, что в работе, что багует, планы, идеи, лог. "
                        "Вызывай, когда спрашивают про разработку, что сделано, "
                        "что нового, что сломано, логи."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "devboard_add",
        "description": ("Дописать пункт в дев-доску. Используй, когда просят "
                        "записать сделанное/идею/план/баг, или ты замечаешь "
                        "новое, чего в доске ещё нет."),
        "parameters": {"type": "object", "properties": {
            "col": {"type": "string",
                    "enum": ["doing", "bugs", "planned", "ideas", "done"],
                    "description": "колонка"},
            "text": {"type": "string", "description": "суть пункта"},
            "note": {"type": "string", "description": "уточнение (необязательно)"}},
            "required": ["col", "text"]}}},
]
_LOCAL_NAMES = {"devboard_read", "devboard_add"}

# Встроенный видимый браузер (server/browser_hands.py). Подключается, только
# если внешний HandsPC НЕ запущен — дома он главнее, конфликтов нет.
_BROWSER_SCHEMAS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": ("Поиск в интернете в твоём ВИДИМОМ окне браузера — "
                        "пользователь видит, как ты ищешь. Используй для "
                        "всего, чего не знаешь или что могло измениться: "
                        "события, люди, цены, погода, термины."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "поисковый запрос"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "open_page",
        "description": ("Открыть страницу по URL в том же видимом окне и "
                        "прочитать её текст (после web_search — чтобы изучить "
                        "результат подробнее)."),
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "web_research",
        "description": ("ГЛУБОКИЙ поиск: сама ищет, открывает и читает "
                        "несколько лучших страниц в видимом окне и приносит "
                        "готовую сводку с источниками. Используй, когда "
                        "нужен содержательный ответ (кто такой X, что за "
                        "проект Y, сравнение, обзор). Для быстрых фактов "
                        "(дата, курс, погода) хватает web_search."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "вопрос/запрос"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "close_browser",
        "description": ("Закрыть своё окно браузера. Зови, когда пользователь "
                        "сказал закрыть/что окно больше не нужно."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]
_BROWSER_NAMES = {"web_search", "web_research", "open_page", "fetch_page",
                  "close_browser"}

# Хоткеи: Сайка заводит быстрые действия по просьбе в диалоге
def _hotkey_schemas():
    try:
        from server import hotkeys
        acts = ", ".join(f"{k} ({v})" for k, v in hotkeys.ACTION_DESC.items())
    except Exception:
        acts = ""
    return [
        {"type": "function", "function": {
            "name": "bind_create",
            "description": ("Завести быстрый хоткей по просьбе пользователя "
                            "(«забинди на слово капуста открытие ютуба», "
                            "«повесь на F8 закрытие окна»). trigger — слово "
                            "или клавиша; kind — voice (слово-триггер) или "
                            "key (клавиша). Действия: " + acts),
            "parameters": {"type": "object", "properties": {
                "trigger": {"type": "string", "description": "слово или клавиша (напр. capslock, f8)"},
                "action": {"type": "string", "description": "имя действия из списка"},
                "params": {"type": "string", "description": "для open — URL/приложение"},
                "kind": {"type": "string", "enum": ["voice", "key"]}},
                "required": ["trigger", "action"]}}},
        {"type": "function", "function": {
            "name": "bind_list",
            "description": "Показать заведённые хоткеи.",
            "parameters": {"type": "object", "properties": {}, "required": []}}},
        {"type": "function", "function": {
            "name": "bind_delete",
            "description": "Убрать хоткей по его триггеру.",
            "parameters": {"type": "object", "properties": {
                "trigger": {"type": "string"}}, "required": ["trigger"]}}},
    ]


_HOTKEY_NAMES = {"bind_create", "bind_list", "bind_delete"}

# Самовыключение: Сайка может выключить себя сама — попрощаться и уйти
# (напр. по прощальному импульсу, когда её надолго оставили одну, или по
# прямой просьбе «выключайся»). Сервер гаснет ПОСЛЕ того, как она
# договорит прощание. start.bat код 0 не перезапускает — чистый выход.
_SHUTDOWN_SCHEMA = {"type": "function", "function": {
    "name": "shutdown_self",
    "description": ("Выключить себя (сервер Сайки) после прощания. Зови "
                    "ТОЛЬКО если пользователь прямо попросил выключиться, "
                    "или по внутреннему прощальному импульсу, когда тебя "
                    "надолго оставили одну. Сначала скажи прощание, вызов "
                    "делай в том же ответе — выключение произойдёт после "
                    "твоих слов."),
    "parameters": {"type": "object", "properties": {}, "required": []}}}


# последняя фраза пользователя — предохранитель для shutdown_self
LAST_USER = {"text": ""}

# ПРЕДОХРАНИТЕЛЬ ИЗМЕНЯЮЩИХ ИНСТРУМЕНТОВ (2026-07-23). abliterated-модель
# склонна выдумывать себе задачи и ВЫПОЛНЯТЬ разрушительные действия без
# просьбы — реальный инцидент: на «что ты умеешь» она сама повесила пробел
# на открытие localhost (bind_create). Правило: читающие инструменты
# (поиск, просмотр, list, read) — свободны; всё, что МЕНЯЕТ состояние
# машины (бинды, запись/удаление/перемещение файлов, папки), выполняется
# ТОЛЬКО если в последней фразе пользователя есть явное намерение. Иначе —
# отказ на уровне кода, модель просто отвечает словами. Работает для любой
# модели, не зависит от её дисциплины.
import re as _re_guard
_MUTATING_INTENT = {
    "bind_create":  r"бинд|хоткей|горяч|клавиш|назнач|повес|привяж|закреп|на пробел|на клавиш",
    "bind_delete":  r"бинд|хоткей|горяч|клавиш|удали|сними|убер|отвяж",
    "fs_write":     r"файл|запиши|сохран|созда|впиши|запис|блокнот|txt|документ",
    "fs_delete":    r"удали|снеси|убер|сотри|delete|стереть",
    "fs_move":      r"перемест|перенес|move|в папку|переклад",
    "fs_rename":    r"переимен|переназов|rename|назов",
    "fs_mkdir":     r"папк|директор|созда|mkdir|каталог",
    "fs_open":      r"откр|запус|покаж файл|open",
    "place_save":   r"сохран|запомни мест|закладк|место",
}


def _intent_ok(name: str) -> bool:
    """True, если изменяющий инструмент оправдан намерением в последней
    фразе пользователя (или это внутренний импульс — там свой белый список
    выше по коду)."""
    pat = _MUTATING_INTENT.get(name)
    if not pat:
        return True  # инструмент не в списке изменяющих — не наше дело
    return bool(_re_guard.search(pat, LAST_USER.get("text", ""), _re_guard.I))


def _shutdown_call() -> str:
    import os
    import re as _re
    import threading
    import time as _t

    # ПРЕДОХРАНИТЕЛЬ: мелкие модели зовут shutdown_self наугад (llama3.2
    # дёрнула его на «ты тут» — чуть не выключила себя). Выключение только
    # если пользователь явно попросил ИЛИ это прощальный импульс.
    asked = bool(_re.search(r"выключ|отключ|гаси|спать|заверша",
                            LAST_USER.get("text", ""), _re.I))
    if not asked and not IMPULSE_MODE.get("on"):
        return ("отказ: пользователь не просил выключаться — команда "
                "игнорирована. Продолжай обычный разговор.")

    delay = CFG.get("idle.shutdown_delay_s", 25)

    def bye():
        _t.sleep(delay)   # дать договорить прощание голосом
        try:
            from server import browser_hands
            if browser_hands.is_open():
                browser_hands.close()
        except Exception:
            pass
        try:
            from server import main as _m
            _m.log.info("Сайка выключила себя сама (shutdown_self)")
            _m._unload_llms()
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=bye, daemon=True).start()
    return (f"принято: выключусь через ~{delay} секунд — договори "
            f"прощание, оно успеет прозвучать")


def _url():
    return CFG.get("tools.handspc_url", "http://127.0.0.1:8767").rstrip("/")


def _hands_schemas() -> list:
    if not CFG.get("tools.enabled", True):
        return []
    if time.time() - _cache["t"] < 30:
        return _cache["schemas"]
    try:
        r = requests.get(_url() + "/tools", timeout=1.5)
        _cache["schemas"] = r.json()
    except Exception:
        _cache["schemas"] = []
    _cache["t"] = time.time()
    return _cache["schemas"]


def schemas() -> list:
    """Схемы инструментов (function calling): HandsPC + (опц.) дев-доска.

    Дев-доску модели по умолчанию НЕ отдаём: слабые модели (напр. llama3.2)
    дёргают devboard_read на каждое сообщение и залипают. Чтение доски делает
    сервер сам (см. _is_dev_query в main.py — подкладывает доску только на
    вопросы про разработку). Хочешь дать инструменты модели (для крупной с
    хорошим function-calling) — включи tools.devboard_tools в config."""
    local = list(_LOCAL_SCHEMAS) if CFG.get("tools.devboard_tools", False) else []
    hands = _hands_schemas()
    if not hands and CFG.get("browser.enabled", True):
        # HandsPC нет — даём встроенный видимый браузер (те же имена
        # инструментов, промпты Сайки про web_search работают как есть)
        local = local + _BROWSER_SCHEMAS
    if CFG.get("idle.allow_self_shutdown", True):
        local = local + [_SHUTDOWN_SCHEMA]
    if CFG.get("hotkeys.enabled", True):
        local = local + _hotkey_schemas()
    # файловые руки (рабочая папка files.roots) — всегда локальные;
    # если у HandsPC вдруг есть инструменты с теми же именами, он главнее
    if CFG.get("files.enabled", True):
        try:
            from server import file_hands
            hands_names = {s["function"]["name"] for s in hands}
            local += [s for s in file_hands.SCHEMAS
                      if s["function"]["name"] not in hands_names]
        except Exception as e:
            log.debug("file_hands недоступен: %s", e)
    return local + hands


def _local_call(name: str, arguments) -> str:
    import json as _json
    from server import devboard
    if isinstance(arguments, str):
        try:
            arguments = _json.loads(arguments)
        except Exception:
            arguments = {}
    arguments = arguments or {}
    if name == "devboard_read":
        return devboard._render_md(devboard.get())
    if name == "devboard_add":
        col = arguments.get("col", "doing")
        text = arguments.get("text", "")
        note = arguments.get("note", "")
        if not text:
            return "нужен текст пункта"
        devboard.add_item(col, text, note)
        return f"записала в доску ({col}): {text}"
    return "неизвестный локальный инструмент"


def _browser_call(name: str, arguments) -> str:
    import json as _json
    from server import browser_hands
    if isinstance(arguments, str):
        try:
            arguments = _json.loads(arguments)
        except Exception:
            arguments = {}
    arguments = arguments or {}
    try:
        if name == "web_search":
            return browser_hands.search(str(arguments.get("query", ""))[:300])
        if name == "web_research":
            return browser_hands.research(
                str(arguments.get("query", ""))[:300])
        if name in ("open_page", "fetch_page"):
            return browser_hands.open_url(str(arguments.get("url", ""))[:2000])
        if name == "close_browser":
            return browser_hands.close()
    except Exception as e:
        log.exception("browser tool %s", name)
        return f"браузер споткнулся: {e}"
    return "неизвестный браузерный инструмент"


def call(name: str, arguments) -> str:
    if not _intent_ok(name):
        log.warning("Инструмент %s заблокирован предохранителем: в фразе "
                    "пользователя (%r) нет намерения его звать",
                    name, LAST_USER.get("text", "")[:60])
        return (f"отказ: пользователь не просил делать это ({name}) — "
                "команда НЕ выполнена, ничего на его машине не изменено. "
                "Просто ответь словами, без вызова инструмента.")
    if IMPULSE_MODE.get("on") and name not in _IMPULSE_SAFE:
        return ("нельзя: это твой внутренний импульс, а не просьба "
                "пользователя — его окна, файлы и интернет не трогаем. "
                "Сейчас доступны только close_browser (своё окно), "
                "shutdown_self и дев-доска.")
    if name in _LOCAL_NAMES:
        return _local_call(name, arguments)
    if name == "shutdown_self":
        if not CFG.get("idle.allow_self_shutdown", True):
            return "самовыключение отключено в настройках"
        return _shutdown_call()
    if name in _HOTKEY_NAMES:
        import json as _json
        from server import hotkeys
        a = arguments if isinstance(arguments, dict) else (
            _json.loads(arguments) if arguments else {})
        if name == "bind_create":
            return hotkeys.add_bind(a.get("trigger", ""), a.get("action", ""),
                                    a.get("params", ""), a.get("kind", "voice"))
        if name == "bind_list":
            binds = hotkeys.list_binds()
            if not binds:
                return "хоткеев пока нет"
            return "; ".join(f"{b['trigger']}({b['kind']})->{b['action']}"
                             for b in binds)
        if name == "bind_delete":
            return hotkeys.del_bind(a.get("trigger", ""))
    if name in _BROWSER_NAMES and not _hands_schemas():
        return _browser_call(name, arguments)
    # файловые руки: локальные, если HandsPC не заявил такое же имя
    try:
        from server import file_hands
        if name in file_hands.NAMES and not any(
                s["function"]["name"] == name for s in _hands_schemas()):
            import json as _json
            args = arguments
            if isinstance(args, str):
                try:
                    args = _json.loads(args)
                except Exception:
                    args = {}
            try:
                return str(file_hands.CALLS[name](args or {}))
            except PermissionError as e:
                return f"нельзя: {e}"
            except Exception as e:
                log.exception("file tool %s", name)
                return f"файловая операция не удалась: {e}"
    except ImportError:
        pass
    # браузерные задачи многошаговые — им нужен большой таймаут
    timeout = CFG.get("tools.timeout_s", 60)
    if name == "browser_task":
        timeout = max(timeout, CFG.get("tools.browser_timeout_s", 420))
    options = {}
    if name == "browser_task" and CFG.get("tools.browser_model"):
        options["browser_model"] = CFG.get("tools.browser_model")
    try:
        r = requests.post(_url() + "/call",
                          json={"name": name, "arguments": arguments,
                                "options": options},
                          timeout=timeout)
        result = str(r.json().get("result", ""))
        # длинные результаты (веб-поиск с несколькими источниками) раздувают
        # контекст за пару раундов и валят локальную модель в переполнение
        # окна — а это ловилось как ошибка и тихо подсовывало ДРУГУЮ модель
        # посреди уже начатого ответа. Режем с запасом.
        cap = CFG.get("tools.max_result_chars", 3000)
        if len(result) > cap:
            result = result[:cap] + "\n…(обрезано, слишком длинный результат)"
        return result
    except Exception as e:
        return f"HandsPC недоступен: {e}"
