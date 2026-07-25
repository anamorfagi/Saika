"""Клиент HandsPC — внешнего сервиса инструментов («руки» Сайки).

HandsPC живёт внутри проекта (HandsPC/, до 2026-07-25 — соседняя папка
C:\\AI\\HandsPC) со своим venv и отдаёт
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
_cache = {"t": 0.0, "schemas": [], "checking": False, "fail_until": 0.0}

# Режим внутреннего импульса (мысль самой себе, пользователь не писал).
# В нём Сайке можно трогать ТОЛЬКО СВОЁ: закрыть свой браузер, выключить
# себя, глянуть дев-доску. Окна/файлы пользователя — под жёстким запретом
# на уровне кода (однажды в idle она «прибралась» и закрыла проводник
# пользователя — смешно, но нельзя).
IMPULSE_MODE = {"on": False}
_IMPULSE_SAFE = {"close_browser", "shutdown_self",
                 "devboard_read", "devboard_add", "avatar_action",
                 "change_outfit"}

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

# Библиотека анимаций веб-аватара (server/anim_hub.py, 2026-07-25)
_ANIM_SCHEMAS = [
    {"type": "function", "function": {
        "name": "anim_search",
        "description": ("Найти готовые VRMA-анимации для своего аватара на "
                        "GitHub (танцы, эмоции, позы). Возвращает нумерованный "
                        "список для anim_download."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string",
                      "description": "что искать: dance, greeting, emote…"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "anim_download",
        "description": ("Скачать анимацию по номеру из результата anim_search "
                        "в свою библиотеку жестов. После скачивания жест "
                        "доступен как [жест:имя] и через avatar_action."),
        "parameters": {"type": "object", "properties": {
            "num": {"type": "integer", "description": "номер из anim_search"},
            "name": {"type": "string",
                     "description": "своё имя жеста (латиницей, опц.)"}},
            "required": ["num"]}}},
    {"type": "function", "function": {
        "name": "anim_from_url",
        "description": ("Разобрать ЛЮБУЮ веб-страницу и найти на ней ссылки "
                        "на .vrma-анимации (или скачать, если url — сам "
                        ".vrma файл). Связка: найди страницу через "
                        "web_search/open_page -> передай её адрес сюда -> "
                        "скачай номер через anim_download."),
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "адрес страницы/файла"},
            "name": {"type": "string",
                     "description": "своё имя жеста (для прямого файла)"}},
            "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "anim_list",
        "description": "Показать анимации, уже скачанные в библиотеку жестов.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "anim_hints",
        "description": ("Показать проверенные прямые ссылки на источники "
                        "VRMA-анимаций (VRoid Hub, BOOTH и др.) — вызывай, "
                        "если anim_search ничего не нашёл (это обычное дело: "
                        "GitHub ищет репозитории по имени, а не по содержимому). "
                        "Из результата — либо скажи ссылку владельцу, либо "
                        "сразу передай в anim_from_url."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]
_ANIM_NAMES = {"anim_search", "anim_download", "anim_from_url", "anim_list", "anim_hints"}

# АВАТАР (2026-07-23): даёт модели САМОЙ решать, когда показать эмоцию/жест
# на VRM-аватаре — по контексту разговора, а не только когда её прямо
# попросили «улыбнись»/«станцуй». В отличие от хоткеев/файлов это НЕ
# изменяющий инструмент (ничего не трогает на машине пользователя, только
# посылает жест своему же аватару) — поэтому не в _MUTATING_INTENT и
# разрешён даже во внутреннем импульсе (см. _IMPULSE_SAFE выше). Показываем
# ВСЕМ моделям (без gating по _model_tier), включая мелкие локальные —
# именно с ними и был замечен провал («не умею показывать эмоции»).
def _avatar_schema():
    from server import avatar
    names = CFG.get("avatar.gestures.slot_names", avatar.DEFAULT_SLOT_NAMES)
    gestures = [n for n in names if n != "reset"]
    opts = ", ".join(f"{n} ({avatar.ACTION_DESC.get(n, n)})" for n in gestures)
    return {"type": "function", "function": {
        "name": "avatar_action",
        "description": ("Показать эмоцию или жест на своём VRM-аватаре — это "
                        "настоящее физическое действие, а не описание "
                        "словами. Зови по смыслу разговора, не только когда "
                        "прямо попросили: доступны " + opts + ". Не зови на "
                        "каждую реплику — только когда жест реально уместен."),
        "parameters": {"type": "object", "properties": {
            "gesture": {"type": "string", "enum": gestures,
                        "description": "имя жеста/эмоции"}},
            "required": ["gesture"]}}}


def _outfit_schema():
    """Смена наряда (2026-07-25) — список нарядов динамический: «default»
    плюс все .vrm из models/avatar/outfits/. Пока владелец не положил туда
    ничего своего, доступен только default — это ожидаемо, не баг."""
    from server import avatar
    names = avatar.list_outfits()
    return {"type": "function", "function": {
        "name": "change_outfit",
        "description": ("Переодеть свой VRM-аватар целиком (другая модель "
                        "с другой одеждой) — доступно: " + ", ".join(names) +
                        ". Зови по смыслу разговора (попросили переодеться, "
                        "сама решила к случаю), не изменяет ничего на "
                        "компьютере владельца — только картинку своего же "
                        "аватара."),
        "parameters": {"type": "object", "properties": {
            "outfit": {"type": "string", "enum": names,
                       "description": "имя наряда из списка"}},
            "required": ["outfit"]}}}

# МАСТЕРСКАЯ (2026-07-23): сильная модель (Kimi и т.п.) умеет не только
# болтать — может сверстать страницу, нарисовать SVG, написать скрипт.
# Инструмент даёт ей творить ФАЙЛАМИ в отдельной папке workshop/ и сразу
# показывать результат в видимом браузере. Мелким моделям не выдаётся
# (см. _model_tier) — они с ним сходят с ума.
_WORKSHOP_SCHEMA = {"type": "function", "function": {
    "name": "workshop_create",
    "description": ("Создать файл в своей мастерской (папка workshop/): "
                    "HTML-страницу/мини-сайт, SVG-картинку, скрипт, текст. "
                    "HTML и SVG сразу открываются в твоём видимом браузере — "
                    "пользователь видит результат. Используй, когда просят "
                    "сделать сайт/страницу/картинку/визуализацию/код-файл. "
                    "HTML пиши самодостаточным (CSS/JS внутри одного файла)."),
    "parameters": {"type": "object", "properties": {
        "filename": {"type": "string",
                     "description": "имя файла, напр. page.html / logo.svg / tool.py"},
        "content": {"type": "string", "description": "полное содержимое файла"}},
        "required": ["filename", "content"]}}}


def _model_tier() -> str:
    """'full' или 'lite' — насколько богатый набор инструментов показывать
    активной модели. Система подстраивается под возможности модели:
    - сильные (облако; локальные с натуральным function-calling и нормальной
      скоростью) получают ПОЛНЫЙ набор: файлы, мастерская, (опц.) доска;
    - мелкие/медленные — только базу (поиск/браузер), чтобы не сходили с ума
      от десятка схем и не дёргали опасное. Принудительно: tools.grade в
      config ("full"/"lite"), по умолчанию "auto"."""
    grade = CFG.get("tools.grade", "auto")
    if grade in ("full", "lite"):
        return grade
    model = CFG.get("llm.model", "")
    if not model or model in set(CFG.get("llm.tools_broken", [])):
        return "lite"
    if CFG.get("llm.backend") == "cloud":
        return "full"          # облачные мозги (Kimi, Claude…) тянут всё
    try:
        from server.llm import passport
        p = passport.get(model) or {}
    except Exception:
        p = {}
    if (p.get("tools_native") and p.get("big_prompt_ok", True)
            and (p.get("tps") or 0) >= 12):
        return "full"
    return "lite"

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
    # скачивание файла на диск — только по явной просьбе про анимации
    "anim_download": r"аним|скача|загруз|жест|танц|движен|vrma",
    "bind_create":  r"бинд|хоткей|горяч|клавиш|назнач|повес|привяж|закреп|на пробел|на клавиш",
    "bind_delete":  r"бинд|хоткей|горяч|клавиш|удали|сними|убер|отвяж",
    "fs_write":     r"файл|запиши|сохран|созда|впиши|запис|блокнот|txt|документ",
    "fs_delete":    r"удали|снеси|убер|сотри|delete|стереть",
    "fs_move":      r"перемест|перенес|move|в папку|переклад",
    "fs_rename":    r"переимен|переназов|rename|назов",
    "fs_mkdir":     r"папк|директор|созда|mkdir|каталог",
    "fs_open":      r"откр|запус|покаж файл|open",
    "place_save":   r"сохран|запомни мест|закладк|место",
    "workshop_create": r"сдела|созда|сгенери|нарису|сверста|сайт|страниц|"
                       r"макет|визуализ|график|картинк|svg|html|напиши код|"
                       r"скрипт|программ",
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


def _refresh_hands_schemas():
    """Фоновое обновление схем HandsPC. НИКОГДА не зовётся из горячего пути:
    раньше requests.get с timeout=1.5 стоял прямо в сборке промпта, и когда
    HandsPC не запущен (обычный случай), КАЖДОЕ протухание кэша (30с)
    добавляло ровно ~1.5с к ответу («промпт 1516мс» в логах — это оно)."""
    try:
        r = requests.get(_url() + "/tools", timeout=1.5)
        _cache["schemas"] = r.json()
        _cache["fail_until"] = 0.0
    except Exception:
        _cache["schemas"] = []
        # HandsPC нет — не дёргаем его чаще, чем раз в 2 минуты
        _cache["fail_until"] = time.time() + 120
    _cache["t"] = time.time()
    _cache["checking"] = False


def _hands_schemas() -> list:
    if not CFG.get("tools.enabled", True):
        return []
    now = time.time()
    ttl = 120 if now < _cache["fail_until"] else 30
    if now - _cache["t"] >= ttl and not _cache["checking"]:
        _cache["checking"] = True
        import threading as _th
        _th.Thread(target=_refresh_hands_schemas, daemon=True).start()
    # отдаём то, что есть (пусть слегка устаревшее) — промпт не ждёт сеть;
    # пока HandsPC не объявился, работает встроенный браузер (см. schemas())
    return _cache["schemas"]


def schemas() -> list:
    """Схемы инструментов (function calling): HandsPC + (опц.) дев-доска.

    Дев-доску модели по умолчанию НЕ отдаём: слабые модели (напр. llama3.2)
    дёргают devboard_read на каждое сообщение и залипают. Чтение доски делает
    сервер сам (см. _is_dev_query в main.py — подкладывает доску только на
    вопросы про разработку). Хочешь дать инструменты модели (для крупной с
    хорошим function-calling) — включи tools.devboard_tools в config."""
    tier = _model_tier()
    local = (list(_LOCAL_SCHEMAS)
             if tier == "full" and CFG.get("tools.devboard_tools", False)
             else [])
    hands = _hands_schemas()
    if not hands and CFG.get("browser.enabled", True):
        # HandsPC нет — даём встроенный видимый браузер (те же имена
        # инструментов, промпты Сайки про web_search работают как есть)
        local = local + _BROWSER_SCHEMAS
    if CFG.get("idle.allow_self_shutdown", True):
        local = local + [_SHUTDOWN_SCHEMA]
    # аватар: намеренно БЕЗ gating по tier — даём даже мелким локальным
    # моделям, их же и просили осознавать, что тело у них есть
    if CFG.get("avatar.enabled", False) and CFG.get("avatar.llm_gestures", True):
        try:
            local = local + [_avatar_schema()]
        except Exception as e:
            log.debug("avatar_schema недоступна: %s", e)
        # библиотека анимаций веб-аватара: поиск/скачивание .vrma с GitHub
        # (просьба владельца 2026-07-25: «не ползать по прогам»)
        local = local + list(_ANIM_SCHEMAS)
        # смена наряда (2026-07-25) — показываем всегда, даже если пока
        # доступен только «default»: список сам вырастет, когда владелец
        # добавит .vrm в models/avatar/outfits/
        try:
            local = local + [_outfit_schema()]
        except Exception as e:
            log.debug("outfit_schema недоступна: %s", e)
    # хоткеи по умолчанию ВЫКЛючены (2026-07-23): abliterated-модель дважды
    # навесила разрушительные бинды без просьбы (пробел→localhost, F8→Alt+F4
    # закрыла приложения). Инструмент не показываем модели вообще, пока
    # владелец сам не включит hotkeys.enabled=true в config.
    if tier == "full" and CFG.get("hotkeys.enabled", False):
        local = local + _hotkey_schemas()
    # мастерская — только сильным (сайты/SVG/скрипты в workshop/)
    if tier == "full" and CFG.get("tools.workshop", True):
        local = local + [_WORKSHOP_SCHEMA]
    # файловые руки (рабочая папка files.roots) — только сильным моделям;
    # если у HandsPC вдруг есть инструменты с теми же именами, он главнее
    if tier == "full" and CFG.get("files.enabled", True):
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


def _workshop_call(arguments) -> str:
    """Создать файл в workshop/ и показать результат в видимом браузере."""
    import json as _json
    import re as _re
    from server.config import resolve
    if isinstance(arguments, str):
        try:
            arguments = _json.loads(arguments)
        except Exception:
            arguments = {}
    arguments = arguments or {}
    fname = str(arguments.get("filename", "")).strip()
    content = arguments.get("content", "")
    if not fname or not content:
        return "нужны filename и content"
    # только имя файла, без путей и фокусов с ..\
    fname = _re.sub(r"[^\w.\-]", "_", fname.replace("\\", "/").split("/")[-1])
    if not _re.search(r"\.[a-z0-9]{1,8}$", fname, _re.I):
        fname += ".txt"
    if _re.search(r"\.(exe|bat|cmd|ps1|vbs|scr|msi|lnk)$", fname, _re.I):
        return "нельзя: исполняемые файлы в мастерской запрещены"
    wdir = resolve(CFG.get("tools.workshop_dir", "workshop"))
    wdir.mkdir(parents=True, exist_ok=True)
    path = wdir / fname
    path.write_text(str(content), encoding="utf-8")
    log.info("Мастерская: создала %s (%d байт)", path, len(str(content)))
    shown = ""
    if fname.lower().endswith((".html", ".htm", ".svg")):
        try:
            from server import browser_hands
            browser_hands.open_url(path.as_uri())
            shown = " и открыла в браузере — результат на экране"
        except Exception:
            try:
                import os as _os
                _os.startfile(str(path))  # системный браузер как запасной
                shown = " и открыла в системном браузере"
            except Exception:
                pass
    return f"создала workshop/{fname}{shown}"


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
    if name == "workshop_create":
        try:
            return _workshop_call(arguments)
        except Exception as e:
            log.exception("workshop_create")
            return f"мастерская споткнулась: {e}"
    if name == "shutdown_self":
        if not CFG.get("idle.allow_self_shutdown", True):
            return "самовыключение отключено в настройках"
        return _shutdown_call()
    if name == "avatar_action":
        import json as _json
        from server import avatar
        a = arguments if isinstance(arguments, dict) else (
            _json.loads(arguments) if arguments else {})
        try:
            return avatar.fire_named(str((a or {}).get("gesture", "")))
        except Exception as e:
            log.exception("avatar_action")
            return f"аватар споткнулся: {e}"
    if name == "change_outfit":
        import json as _json
        from server import avatar
        a = arguments if isinstance(arguments, dict) else (
            _json.loads(arguments) if arguments else {})
        try:
            return avatar.change_outfit(str((a or {}).get("outfit", "")))
        except Exception as e:
            log.exception("change_outfit")
            return f"переодевание споткнулось: {e}"
    if name in _ANIM_NAMES:
        import json as _json
        from server import anim_hub
        a = arguments if isinstance(arguments, dict) else (
            _json.loads(arguments) if arguments else {})
        if name == "anim_search":
            return anim_hub.search((a or {}).get("query", ""))
        if name == "anim_download":
            return anim_hub.download((a or {}).get("num"),
                                     (a or {}).get("name", ""))
        if name == "anim_from_url":
            return anim_hub.from_url((a or {}).get("url", ""),
                                     (a or {}).get("name", ""))
        if name == "anim_hints":
            return anim_hub.hints()
        return anim_hub.list_local()
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
