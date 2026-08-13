"""Клиент HandsPC — внешнего сервиса инструментов («руки» Сайки).

HandsPC живёт внутри проекта (HandsPC/, до 2026-07-25 — соседняя папка
C:\\AI\\HandsPC) со своим venv и отдаёт
инструменты (web_search, fetch_page, …) по HTTP. Сайка на каждый диалог
спрашивает список схем; если сервис не запущен — просто работает без
инструментов, ничего не ломается. Новые инструменты в HandsPC подхватываются
автоматически, код Сайки менять не надо.
"""
import logging
import re                      # 2026-07-29: маршрутизация команд по фразе
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
                 "change_outfit",
                 # свои глаза (2026-08-05): лог, ошибка и свой код — это
                 # СВОЁ, в импульсе смотреть можно.
                 "fs_log", "fs_lasterr", "fs_grep", "fs_slice"}

# ЛОКАЛЬНЫЕ инструменты Сайки (не через HandsPC): дев-доска — чтобы она могла
# свериться со своей историей разработки и дописывать в блокнот сама.
# ───────────────── РУКИ В САМОЙ WINDOWS (2026-07-26) ─────────────────
# Просьба владельца: «хочется с дивана общаться и чтобы она могла выполнить
# любую команду». Каталог программ собирается сам из меню «Пуск» — белый
# список путей руками никто не заполнял, он так и остался пустым.
# Разрушительного тут нет намеренно: «закрыть» — вежливое WM_CLOSE, снятие
# процесса живёт отдельно и требует подтверждения (server/trust.py).
_PC_SCHEMAS = [
    {"type": "function", "function": {
        "name": "app_launch",
        "description": ("Запустить программу по человеческому названию. "
                        "ВАЖНО: «открой X» = запустить (это создаст НОВОЕ "
                        "окно, даже если программа уже работает). Переключить "
                        "на уже открытое окно — это window_focus, зови его "
                        "только если попросили «переключись/покажи окно». "
                        "Если я не уверена — верну вопрос «это оно?»: задай "
                        "его человеку вслух и позови app_launch ещё раз, "
                        "передав его ответ дословно («да», «второе», «нет») "
                        "— я запомню выбор навсегда."),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string",
                     "description": "название как его назвал человек"}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "apps_list",
        "description": ("Какие программы вообще установлены. Зови, когда "
                        "человек спрашивает «что у меня есть» или ты не "
                        "уверена, как называется нужная."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string",
                      "description": "фильтр по названию, необязательно"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "window_list",
        "description": ("Какие окна сейчас открыты, на каком мониторе и что "
                        "свёрнуто. Зови ПЕРЕД тем, как что-то сворачивать "
                        "или закрывать — иначе будешь гадать."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "window_minimize",
        "description": "Свернуть окно по куску заголовка или имени программы.",
        "parameters": {"type": "object", "properties": {
            "match": {"type": "string"}}, "required": ["match"]}}},
    {"type": "function", "function": {
        "name": "window_focus",
        "description": "Показать окно поверх остальных, развернуть свёрнутое.",
        "parameters": {"type": "object", "properties": {
            "match": {"type": "string"}}, "required": ["match"]}}},
    {"type": "function", "function": {
        "name": "window_close",
        "description": ("Попросить окно закрыться. Программа сама спросит "
                        "про несохранённое — это не принудительное снятие."),
        "parameters": {"type": "object", "properties": {
            "match": {"type": "string"}}, "required": ["match"]}}},
    {"type": "function", "function": {
        "name": "window_maximize",
        "description": ("Развернуть окно во весь экран. Без match — то окно, "
                        "что сейчас впереди. full=true дополнительно жмёт "
                        "F11 (настоящий полноэкранный режим браузеров и "
                        "плееров)."),
        "parameters": {"type": "object", "properties": {
            "match": {"type": "string"},
            "full": {"type": "boolean"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "window_restore",
        "description": ("Вернуть окно из развёрнутого/свёрнутого в обычный "
                        "вид. match=\"все\" (или «разверни всё», «открой все "
                        "окна» от человека) — развернуть ВСЁ свёрнутое "
                        "разом, обратное minimize_all."),
        "parameters": {"type": "object", "properties": {
            "match": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "window_place",
        "description": ("Поставить окно в нужное место экрана и задать "
                        "размер. Для «размести по центру», «в правый нижний "
                        "угол», «на пол-экрана слева». «На втором экране» = "
                        "monitor=2 (номера — как в настройках дисплея "
                        "Windows). «Открой X на втором экране» = сначала "
                        "app_launch/open_folder, потом window_place с "
                        "monitor=2 — само на второй экран ничего не "
                        "открывается."),
        "parameters": {"type": "object", "properties": {
            "match": {"type": "string",
                      "description": "кусок заголовка окна или имя программы"},
            "position": {"type": "string",
                         "enum": ["center", "left", "right", "top", "bottom",
                                  "topleft", "topright", "bottomleft",
                                  "bottomright"],
                         "description": "куда поставить (по умолчанию center)"},
            "width": {"type": "integer",
                      "description": "ширина в % экрана (10-100), 0 = не менять"},
            "height": {"type": "integer",
                       "description": "высота в % экрана, 0 = не менять"},
            "monitor": {"type": "integer",
                        "description": "номер экрана (1, 2…); -1 = на "
                                       "другой экран; 0 = текущий"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "eyes",
        "description": ("Включить или выключить СВОЁ зрение (глаза: кадры "
                        "экрана/вебки). Зови, когда просят «включи глаза», "
                        "«посмотри…», а зрение выключено."),
        "parameters": {"type": "object", "properties": {
            "on": {"type": "boolean",
                   "description": "true = включить, false = выключить"}},
            "required": ["on"]}}},
    {"type": "function", "function": {
        "name": "find_folder",
        "description": ("Найти папку на дисках по человеческому названию: "
                        "«папка с играми», «проекты», «музыка». Возвращает "
                        "несколько вариантов — ПОКАЖИ их человеку списком с "
                        "номерами и спроси, какой нужен. Когда он ответит, "
                        "позови remember_place, чтобы больше не искать."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "что ищем"},
            "drive": {"type": "string",
                      "description": "буква диска, например C — если назвали"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "app_remember",
        "description": ("Запомнить программу по пути. Зови, когда человек "
                        "даёт путь и название: «запомни: аркнайтс — это "
                        "D:\\Games\\GRYPHLINK.exe». Дальше app_launch по "
                        "этому названию откроет её мгновенно."),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string",
                     "description": "как человек называет программу"},
            "path": {"type": "string", "description": "полный путь"}},
            "required": ["name", "path"]}}},
    {"type": "function", "function": {
        "name": "remember_place",
        "description": ("Запомнить папку под понятным именем («игровая», "
                        "«проекты»), чтобы дальше открывать её мгновенно, "
                        "не обыскивая диск заново."),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}, "path": {"type": "string"}},
            "required": ["name", "path"]}}},
    {"type": "function", "function": {
        "name": "minimize_all",
        "description": ("Свернуть всё лишнее, кроме названного окна. "
                        "Для «убери всё, оставь только редактор»."),
        "parameters": {"type": "object", "properties": {
            "keep": {"type": "string",
                     "description": "что НЕ сворачивать, необязательно"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "volume_set",
        "description": ("Громкость системы. Либо процент, либо «громче/тише» "
                        "через delta, либо выключить звук через mute."),
        "parameters": {"type": "object", "properties": {
            "percent": {"type": "integer", "description": "0..100"},
            "delta": {"type": "integer",
                      "description": "на сколько изменить, +10 / -10"},
            "mute": {"type": "boolean"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "tab_control",
        "description": ("Вкладки активного окна браузера: open, close, next, "
                        "prev, go (с номером). Работает клавишами, поэтому "
                        "нужное окно должно быть впереди."),
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["open", "close", "next", "prev", "go"]},
            "index": {"type": "integer", "description": "номер для go, с 1"}},
            "required": ["action"]}}},
    {"type": "function", "function": {
        "name": "open_folder",
        "description": ("Открыть папку в проводнике и ВСТАТЬ в неё: дальше "
                        "пути считаются от этого места. «зайди в Ламоду» = "
                        "path=\"Ламода\" (имя соседней папки, не полный "
                        "путь); «наверх»/«назад»/«домой» — переходы; полный "
                        "путь (D:\\Games) тоже можно. В ответе перечислю, "
                        "что внутри — веди человека дальше по этому списку."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string",
                     "description": "имя подпапки, «наверх», «назад», "
                                    "«домой» или полный путь"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "folder_list",
        "description": ("Что внутри текущей папки (где мы сейчас стоим) или "
                        "указанной. Зови, когда человек спрашивает «что "
                        "тут?» или ты не знаешь, куда шагнуть дальше."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string",
                     "description": "необязательно; пусто = текущая"}},
            "required": []}}},
]
_PC_NAMES = {s["function"]["name"] for s in _PC_SCHEMAS}

# ───────────── РУКИ ВНУТРИ ОКОН (2026-07-29, server/ui_hands.py) ─────────────
# Просьба владельца, дословно: «я вызываю ютуб — она вводит запрос и
# открывает; говорю — она тыкает; найди в чате Виталю и напиши ему, перед
# отправкой спросив: текст готов, отправляем?». Строение по практикам больших
# систем автоматизации: дерево доступности вместо пикселей (как Power
# Automate), глубокие ссылки вместо кликов по строке поиска (как Siri),
# каждое действие возвращает, что реально произошло, а НЕОБРАТИМОЕ (Enter
# в чате) отделено от набора текста и требует подтверждения человека.
_UIH_SCHEMAS = [
    {"type": "function", "function": {
        "name": "web_open",
        "description": ("Открыть сайт в браузере, сразу со страницей "
                        "результатов, если есть запрос. «включи на ютубе X» "
                        "= web_open(site=\"ютуб\", query=\"X\") — ОДИН шаг, "
                        "не открывай главную и не печатай в строку поиска. "
                        "Знаю ютуб, гугл, яндекс, википедию, карты; любой "
                        "другой сайт — по адресу (kinopoisk.ru)."),
        "parameters": {"type": "object", "properties": {
            "site": {"type": "string", "description": "сайт как назвал человек"},
            "query": {"type": "string",
                      "description": "что искать, необязательно"}},
            "required": ["site"]}}},
    {"type": "function", "function": {
        "name": "screen_read",
        "description": ("Прочитать АКТИВНОЕ окно: список его кнопок, ссылок "
                        "и полей по именам. Зови ПЕРЕД screen_click — имена "
                        "элементов берутся только отсюда, не из головы. "
                        "После web_open подожди пару секунд и посмотри."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "screen_click",
        "description": ("Кликнуть по элементу активного окна ПО ИМЕНИ из "
                        "screen_read. «тыкни первый клип», «нажми "
                        "подписаться». Если не уверена в элементе — верну "
                        "варианты, уточни у человека, не гадай."),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "имя элемента"},
            "double": {"type": "boolean",
                       "description": "двойной клик, по умолчанию нет"}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "type_into",
        "description": ("Вписать текст в КОНКРЕТНОЕ поле ввода активного "
                        "окна: найду поле по имени (как в screen_read), "
                        "кликну в него и напечатаю. «впиши в строку поиска "
                        "X» = type_into(field=\"поиск\", text=\"X\"). "
                        "НЕ отправляет — enter отдельно, после "
                        "подтверждения человека."),
        "parameters": {"type": "object", "properties": {
            "field": {"type": "string",
                      "description": "имя поля из screen_read (или пусто, "
                                     "если поле в окне одно)"},
            "text": {"type": "string"}},
            "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "keyboard_type",
        "description": ("Напечатать текст туда, где сейчас курсор (поле "
                        "поиска, чат, документ). НИКОГДА не отправляет: "
                        "Enter — это отдельный key_press, и в чатах его "
                        "можно жать ТОЛЬКО после вопроса человеку «текст "
                        "готов, отправляем?» и его согласия."),
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "key_press",
        "description": ("Нажать клавишу или сочетание в активном окне: "
                        "enter, esc, tab, стрелки, f5, f11, ctrl+t, ctrl+k, "
                        "«полный экран» (f11), «развернуть видео» (f — плеер "
                        "ютуба). enter в чате = ОТПРАВКА, только после "
                        "подтверждения человека."),
        "parameters": {"type": "object", "properties": {
            "combo": {"type": "string"}}, "required": ["combo"]}}},
    {"type": "function", "function": {
        "name": "screen_scroll",
        "description": "Прокрутить активное окно: вниз или вверх.",
        "parameters": {"type": "object", "properties": {
            "direction": {"type": "string", "enum": ["вниз", "вверх"]},
            "times": {"type": "integer", "description": "сколько щелчков, 1-15"}},
            "required": []}}},
]
_UIH_NAMES = {s["function"]["name"] for s in _UIH_SCHEMAS}

# ─────────────── СВОЙ СОБСТВЕННЫЙ ИНТЕРФЕЙС (2026-07-26) ───────────────
# «Прошу её взять модель поумнее — она находит её в списке и переключает».
# Без этого владельцу приходится вставать и лезть мышкой в меню — ровно то,
# от чего он и хотел избавиться.
_UI_SCHEMAS = [
    {"type": "function", "function": {
        "name": "model_list",
        "description": ("Какие модели доступны и насколько они хороши "
                        "(оценка, скорость, влезает ли в видеопамять). "
                        "Зови перед сменой модели, чтобы не гадать."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "model_switch",
        "description": ("Переключиться на другую модель. Можно назвать "
                        "точное имя, а можно намерение: smarter (поумнее), "
                        "faster (побыстрее), vision (со зрением). Если "
                        "человек не назвал конкретную — выбери сама."),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "имя модели"},
            "want": {"type": "string",
                     "enum": ["smarter", "faster", "vision"],
                     "description": "если имя не названо"}},
            "required": []}}},
]
_UI_NAMES = {s["function"]["name"] for s in _UI_SCHEMAS}

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
    # ВЫДАЧА СПИСКОМ (2026-08-13). Отличие от web_search: тот приносит
    # ВЫЖИМКИ, чтобы ты ответила по существу сама; этот показывает человеку
    # НУМЕРОВАННЫЙ список и ждёт, что он выберет номер.
    {"type": "function", "function": {
        "name": "web_list",
        "description": ("Набрать запрос в поисковой строке (сначала очистив "
                        "её) и ПОКАЗАТЬ выдачу человеку нумерованным списком "
                        "в чате. Зови, когда просят «напиши в поиск», "
                        "«поищи и покажи что нашла», «дай список» — то есть "
                        "когда человек хочет ВЫБРАТЬ сайт сам. Список "
                        "показывается ему автоматически: вслух его "
                        "перечислять НЕ надо."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "что набрать в поиск"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "open_result",
        "description": ("Открыть пункт последней выдачи по НОМЕРУ — когда "
                        "человек говорит «открой второй», «зайди на третий», "
                        "«davай первый»."),
        "parameters": {"type": "object", "properties": {
            "n": {"type": "integer", "description": "номер пункта списка"}},
            "required": ["n"]}}},
    {"type": "function", "function": {
        "name": "site_search",
        "description": ("Набрать текст в поисковой строке ОТКРЫТОГО САЙТА "
                        "(YouTube, магазин, форум) и нажать ввод. Это НЕ "
                        "поиск в интернете: ищет ВНУТРИ той страницы, что "
                        "сейчас открыта. Зови на «впиши в поиск на сайте», "
                        "«найди на ютубе», «поищи здесь». Строку чищу перед "
                        "набором сама — дописывать к старому не надо."),
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "что набрать"}},
            "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "close_ad",
        "description": ("Убрать баннер/модалку/окно подписки, висящее ПОВЕРХ "
                        "страницы. Зови, когда видишь пометку про перекрытие "
                        "или когда человек говорит «убери рекламу», «закрой "
                        "это окно»."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "browser_scroll",
        "description": ("Пролистать открытую страницу и прочитать то, что "
                        "оказалось на экране. Зови САМА, когда нужного на "
                        "первом экране нет, и по просьбе «пролистай ниже», "
                        "«прокрути вверх», «промотай в конец»."),
        "parameters": {"type": "object", "properties": {
            "direction": {"type": "string", "description":
                          "down | up | top | bottom (вниз/вверх/начало/конец)"},
            "amount": {"type": "integer", "description":
                       "сколько экранов, 1-10 (по умолчанию 1)"}},
            "required": []}}},
]
_BROWSER_NAMES = {"web_search", "web_research", "open_page", "fetch_page",
                  "close_browser", "web_list", "open_result",
                  "browser_scroll", "site_search", "close_ad"}

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
    # Руки в Windows (2026-07-26). Смотреть (window_list, apps_list) можно
    # свободно — это ничего не меняет. А вот запускать, закрывать и крутить
    # звук — только если человек об этом действительно заговорил: мелкая
    # модель охотно «помогает» закрыть игру посреди разговора о погоде.
    "app_launch":   r"запус|откр|вклю|поигра|стартуй|launch|run|врубb?и",
    "window_close": r"закр|выйд|убер|заверш|close|сверн",
    # + перенос между экранами (2026-07-29, живой отказ: «перенести хром на
    # первый» не содержало ни одного слова из старого списка)
    "window_place": r"центр|угол|слева|справа|сверху|снизу|размест|постав|"
                    r"растян|размер|маштаб|масштаб|полов|экран|перенес|"
                    r"перекин|перемест|перестав|перетащ|монитор|перв|втор|"
                    r"основн|главн",
    "eyes": r"глаз|зрен|смотр|посмотр|включи вид|видеть",
    "window_minimize": r"сверн|убер|спрячь|minimi|скрой|убрать с глаз",
    "minimize_all": r"сверн|убер|спрячь|очист|освободи|всё лишн|все лишн",
    # «открой хром» — это тоже про окно: раньше сюда не попадало «откр», и
    # предохранитель резал window_focus на живой просьбе (лог 2026-07-26)
    "window_focus": r"покаж|подним|перекл|верни|разверн|откр|focus|"
                    r"на передн|сверху|фокус|"
                    # 2026-08-13: «выведи на экран, чтоб я увидел» — это
                    # просьба вынести окно вперёд, а не повод рассуждать
                    r"вывед|выведи|чтоб.{0,12}увид|не вижу|дай посмотреть",
    "window_maximize": r"разверн|полн.{0,4}экран|максим|во весь экран|"
                       r"на весь экран|maximi|fullscreen|f11|растян",
    # + «разверни/открой всё» (2026-07-29): восстановление свёрнутых окон
    # живёт здесь же, а этих слов в списке не было — предохранитель резал
    "window_restore": r"верни|обычн|уменьш|из полного|restore|сверн окно|"
                      r"разверн|откр|подним|покаж|вс[её]",
    "volume_set":   r"громк|тише|громче|звук|тихо|погромч|потише|mute|"
                    r"выключи звук|включи звук|убавь|прибавь",
    "tab_control":  r"вкладк|tab|браузер|страниц|перейди на|закрой вкладк",
    "open_folder":  r"папк|директор|провод|откр|folder|explorer|зайд|"
                    r"наверх|назад|выше|ниже|глубж|внутр|перейд|домой",
    "folder_list":  r"что тут|что там|что внутр|покаж|списк|содержим|"
                    r"папк|файл",
    "find_folder":  r"найд|ищи|поищ|где|искать|find|папк|директор",
    "remember_place": r"запомн|это она|эта|номер|назов|сохрани|remember",
    "app_remember":  r"запомн|путь|это прога|это программ|вот она|"
                     r"находится|лежит|exe|\.exe",
    # Свой интерфейс: переключение модели меняет ход разговора, наугад — нет
    "model_switch": r"модел|умн|быстр|поменяй|перекл|смени|другую|"
                    r"мозг|переобуй|model",
    # Руки внутри окон (2026-07-29). Смотреть (screen_read) и крутить можно
    # свободно. Открыть сайт, кликнуть, напечатать — только когда человек
    # об этом заговорил. key_press нарочно самый строгий: enter — отправка.
    "web_open":     r"откр|вклю|найд|поищ|запус|покаж|ютуб|youtube|гугл|"
                    r"яндекс|вики|сайт|видео|канал|клип|музык|поиск|карт",
    "screen_click": r"нажм|кликн|тыкн|ткни|выбер|вклю|откр|клип|видео|"
                    r"кнопк|ссылк|перв|втор|трет|плейлист|подпис|пункт",
    "keyboard_type": r"напиш|введ|набер|напечат|вбей|вставь|текст|сообщ|"
                     r"запрос|поиск|скажи ему|передай",
    "type_into":     r"впиш|напиш|введ|набер|напечат|вбей|вставь|текст|"
                     r"сообщ|запрос|поиск|строк|поле|передай",
    # короткое «да» после её вопроса «отправляем?» пропускает общее правило
    # согласия в _intent_ok — отдельного слова тут не нужно (и нельзя:
    # хвост «…погода» тоже кончается на «да»)
    "key_press":    r"нажм|энтер|enter|отправ|клавиш|полн.{0,4}экран|"
                    r"разверн|обнов|ввод|эскейп|esc|стрелк|вниз|вверх|готов",
}


def _intent_ok(name: str) -> bool:
    """True, если изменяющий инструмент оправдан намерением в последней
    фразе пользователя (или это внутренний импульс — там свой белый список
    выше по коду)."""
    pat = _MUTATING_INTENT.get(name)
    if not pat:
        return True  # инструмент не в списке изменяющих — не наше дело
    txt = LAST_USER.get("text", "")
    # СОГЛАСИЕ = НАМЕРЕНИЕ (2026-07-28, реальный случай). Она спросила
    # «хочешь, включу глаза?», человек ответил «Да-да» — и предохранитель
    # зарубил вызов: в слове «да» нет корня «глаз». Короткое подтверждение
    # после ЕЁ ЖЕ вопроса — это и есть просьба сделать предложенное; иначе
    # каждый диалог с уточнением упирается в отказ. Осторожность разумная:
    # согласие принимаем только КОРОТКОЕ и чистое — «да, но не сейчас»
    # содержит лишние слова и согласием не считается.
    if _re_guard.fullmatch(
            r"\s*(да+[\s,!.-]*)+|\s*(давай|ага|угу|конечно|ок|окей|"
            r"хорошо|можно|валяй|делай|попробуй|просто)[\s!.]*",
            txt.lower()):
        return True
    # НАМЕРЕНИЕ ЖИВЁТ РАЗГОВОРОМ (2026-07-29, живой отказ: «открой телеграм
    # на втором экране» -> уточнения -> «просто открой десктопный вариант»
    # — и window_place получил отказ, потому что в ПОСЛЕДНЕЙ фразе слова
    # «экран» уже не было). Смотрим на хвост из трёх фраз: уточнение после
    # просьбы — продолжение той же просьбы, а не новая тема.
    tail = " ".join(LAST_USER.get("recent", []) or [txt])
    return bool(_re_guard.search(pat, tail, _re_guard.I))


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
    # РУКИ В WINDOWS и СВОЙ ИНТЕРФЕЙС. Без gating по tier: «сверни окно» и
    # «включи модель поумнее» должна уметь и мелкая модель — ровно ради
    # разговора с дивана это всё и делалось. От глупостей защищает не
    # сокрытие схем, а проверка доверия в call() (server/trust.py).
    if CFG.get("pc.enabled", True):
        local = local + list(_PC_SCHEMAS)
        # руки внутри окон — та же граница доверия, что и окна/программы
        local = local + list(_UIH_SCHEMAS)
    if CFG.get("pc.self_ui", True):
        local = local + list(_UI_SCHEMAS)
    # хоткеи по умолчанию ВЫКЛючены (2026-07-23): abliterated-модель дважды
    # навесила разрушительные бинды без просьбы (пробел→localhost, F8→Alt+F4
    # закрыла приложения). Инструмент не показываем модели вообще, пока
    # владелец сам не включит hotkeys.enabled=true в config.
    if tier == "full" and CFG.get("hotkeys.enabled", False):
        local = local + _hotkey_schemas()
    # мастерская — только сильным (сайты/SVG/скрипты в workshop/)
    if tier == "full" and CFG.get("tools.workshop", True):
        local = local + [_WORKSHOP_SCHEMA]
    # файловые руки (рабочая папка files.roots). Раньше — только сильным
    # моделям, и это дало враньё страшнее любой ошибки (2026-07-29): gemma
    # писала маркер fs_write, сервер молча пропускал НЕЗНАКОМОЕ имя, а она
    # рапортовала «файл создан» — трижды подряд, человеку в глаза. Мелким
    # моделям теперь выдаётся БЕЗОПАСНОЕ подмножество: создать/прочитать/
    # список — всё заперто в рабочей папке. Удаление/перенос — по-прежнему
    # только сильным.
    if CFG.get("files.enabled", True):
        try:
            from server import file_hands
            hands_names = {s["function"]["name"] for s in hands}
            _fs = [s for s in file_hands.SCHEMAS
                   if s["function"]["name"] not in hands_names]
            if tier != "full":
                # fs_delete здесь ОСОЗНАННО (2026-07-29): в file_hands он не
                # стирает, а переносит в _trash внутри рабочей папки —
                # восстановимо руками. Прятать его от мелкой модели значило
                # получать «Удалено. Порядок восстановлен» при нетронутых
                # папках: враньё дороже обратимого переноса. Плюс сверху
                # работает доверие (server/trust.py) и предохранитель
                # намерения. Безвозвратного удаления в проекте нет вообще.
                _safe = {"fs_list", "fs_read", "fs_write", "fs_mkdir",
                         "fs_open", "place_save", "fs_delete", "fs_rename"}
                _fs = [s for s in _fs if s["function"]["name"] in _safe]
            local += _fs
        except Exception as e:
            log.debug("file_hands недоступен: %s", e)
    # СВОИ ГЛАЗА (2026-08-05): лог, последняя ошибка, поиск по своему коду.
    # Отдаём ВСЕМ тирам, включая мелкие модели: это единственные инструменты,
    # которые ничего не меняют, а без них мелкая модель именно что выдумывает
    # («я посмотрела, всё в порядке») — ровно то враньё, от которого мы
    # лечились безопасным подмножеством файловых рук выше.
    if CFG.get("selfread.enabled", True):
        try:
            from server import self_read
            hands_names = {s["function"]["name"] for s in hands}
            local += [s for s in self_read.SCHEMAS
                      if s["function"]["name"] not in hands_names]
        except Exception as e:
            log.debug("self_read недоступен: %s", e)
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
        if name == "web_list":
            return browser_hands.search_list(
                str(arguments.get("query", ""))[:300])
        if name == "open_result":
            return browser_hands.open_result(
                arguments.get("n") or arguments.get("номер")
                or arguments.get("index"))
        if name == "site_search":
            return browser_hands.type_into_search(
                str(arguments.get("text") or arguments.get("query") or "")[:300])
        if name == "close_ad":
            return browser_hands.close_ad()
        if name == "browser_scroll":
            return browser_hands.scroll(
                str(arguments.get("direction") or "down"),
                arguments.get("amount") or 1)
    except Exception as e:
        log.exception("browser tool %s", name)
        return f"браузер споткнулся: {e}"
    return "неизвестный браузерный инструмент"


# Признаки того, что инструмент НЕ справился. Разбираем по тексту, потому
# что все инструменты возвращают человеческую строку, а не код возврата —
# так их читает и модель. Список консервативный: лучше не заметить провал,
# чем записать в провалы успешный ответ.
_FAIL_RE = _re_guard.compile(
    r"^\s*(нельзя|отказ|не\s+смогла|не\s+нашла|не\s+получилось|не\s+вышло|"
    r"не\s+удалось|ошибка|недоступ|не\s+знаю|ничего\s+не\s+наш|"
    r"не\s+поддерж|нет\s+модуля|не\s+могу)", _re_guard.I)


# АНТИ-АМОК МЕЖДУ ХОДАМИ (2026-07-28, просьба владельца). Внутри одного
# ответа от зацикливания защищает seen_calls в chat_stream, но глюкнувшая
# модель может звать одно и то же действие КАЖДЫЙ ход — десять раз открыть
# браузер, десять раз запустить программу. Человек в это время видит только
# мельтешение окон. Правило: одинаковый вызов (имя+аргументы) чаще N раз за
# окно — отказ с прямым текстом; жесты аватара не считаем, они повторяются
# законно. Счётчик общий на процесс, чинится сам по истечении окна.
from collections import deque as _deque
_CALL_HISTORY: "_deque" = _deque(maxlen=64)
_AMOK_EXEMPT = {"avatar_action"}


def _amok_check(name: str, arguments) -> str:
    if name in _AMOK_EXEMPT:
        return ""
    try:
        import json as _json
        key = name + ":" + _json.dumps(arguments, ensure_ascii=False,
                                       sort_keys=True, default=str)
    except Exception:
        key = name + ":" + str(arguments)
    now = time.time()
    window = float(CFG.get("tools.repeat_window_s", 90))
    limit = int(CFG.get("tools.repeat_max", 3))
    recent = [1 for ts, k in _CALL_HISTORY if k == key and now - ts < window]
    _CALL_HISTORY.append((now, key))
    if len(recent) >= limit:
        return (f"отказ: ты уже вызывала {name} с теми же аргументами "
                f"{len(recent)} раза за последние {int(window)} секунд — "
                "это выглядит как зацикливание, действие НЕ выполнено. "
                "Остановись и скажи человеку, что происходит, обычными "
                "словами. Если он попросит ещё раз — можно.")
    return ""


def call(name: str, arguments) -> str:
    """Обёртка над _call: тот же результат, но с отметкой в самочувствии.

    Мастерство — самый сильный источник веры в себя (Бандура), поэтому
    каждый успешный и каждый провальный вызов должен доходить до psyche.
    Разводить это по всем веткам _call было бы десятком копий одного и
    того же — оборачиваем один раз здесь.
    """
    _stop = _amok_check(name, arguments)
    if _stop:
        log.warning("Анти-амок: %s заблокирован (повторы)", name)
        return _stop
    out = _call(name, arguments)
    try:
        from server import psyche
        psyche.on_tool(name, ok=not bool(_FAIL_RE.match(str(out or ""))))
    except Exception:
        pass
    return out


def _call(name: str, arguments) -> str:
    if not _intent_ok(name):
        log.warning("Инструмент %s заблокирован предохранителем: в фразе "
                    "пользователя (%r) нет намерения его звать",
                    name, LAST_USER.get("text", "")[:60])
        return (f"отказ: пользователь не просил делать это ({name}) — "
                "команда НЕ выполнена, ничего на его машине не изменено. "
                "Просто ответь словами, без вызова инструмента.")
    # ДОВЕРИЕ (2026-07-26). Пока у неё были только поиск и дев-доска, вопрос
    # «спрашивать или делать» не стоял. С руками в системе он стал главным:
    # мелкая модель на низком доверии обязана сперва проговорить план.
    try:
        from server import trust as _trust
        ok, why = _trust.allowed(name, LAST_USER.get("text", ""))
        if not ok:
            log.info("Доверие не пустило %s: %s", name, why[:120])
            return "нельзя без подтверждения: " + why
    except ImportError:
        pass
    except Exception as e:
        log.warning("проверка доверия сломалась (%s) — пропускаю", e)
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
    if name in _PC_NAMES:
        import json as _json
        from server import pc_control as _pc
        a = arguments if isinstance(arguments, dict) else (
            _json.loads(arguments) if arguments else {})
        a = a or {}
        try:
            if name == "app_launch":
                _q = str(a.get("name", "")).strip()
                if not _q:
                    # пустой маркер [app_launch] — берём фразу человека:
                    # именно в ней и написано, что запускать (живой вечер
                    # 2026-07-29: gemma стабильно роняла аргументы, и
                    # «Не расслышала, что запускать» шло по кругу)
                    _q = LAST_USER.get("text", "").strip()
                return _pc.launch(_q)
            if name == "apps_list":
                items = _pc.apps(str(a.get("query", "")), limit=60)
                if not items:
                    return "ничего не нашла в каталоге программ"
                return "; ".join(x["name"] for x in items)
            if name == "window_list":
                return _pc.screen_map()
            if name == "window_minimize":
                return _pc.window_minimize(str(a.get("match", "")))
            if name == "window_focus":
                return _pc.window_focus(str(a.get("match", "")))
            if name == "window_close":
                return _pc.window_close(str(a.get("match", "")))
            if name == "window_maximize":
                return _pc.window_maximize(str(a.get("match", "")),
                                           bool(a.get("full")))
            if name == "window_restore":
                _mt = str(a.get("match", "")).strip().lower()
                # «разверни всё» (2026-07-29): и в аргументе, и в фразе
                # человека — если речь про ВСЕ окна, это restore_all
                _utxt = LAST_USER.get("text", "").lower()
                if re.search(r"\bвс[её]х?\b", _mt) or (
                        not _mt and re.search(
                            r"(разверни|открой|верни).{0,12}\bвс[её]\b",
                            _utxt)):
                    return _pc.restore_all()
                return _pc.window_restore(_mt)
            if name == "window_place":
                # monitor может прийти словом («другой», «второй») — мелкие
                # модели пишут как говорят, принимаем
                _mraw = str(a.get("monitor") or "0").strip().lower()
                _mon = None
                for _k, _v in (("друг", -1), ("other", -1), ("перв", 1),
                               ("втор", 2), ("трет", 3), ("основ", 1),
                               ("главн", 1)):
                    if _mraw.startswith(_k):
                        _mon = _v
                        break
                if _mon is None:
                    try:
                        _mon = int(float(_mraw))
                    except ValueError:
                        _mon = 0
                return _pc.window_place(str(a.get("match", "")),
                                        str(a.get("position", "center")),
                                        int(a.get("width") or 0),
                                        int(a.get("height") or 0),
                                        _mon)
            if name == "eyes":
                # СВОИ ГЛАЗА (2026-07-28): «включи глаза» голосом раньше
                # упиралось в философствование — тумблер был только в UI.
                # Настройка та же, что дёргает тумблер (vision.enabled),
                # поэтому интерфейс увидит смену состояния сам.
                _on = bool(a.get("on", True))
                CFG.set("vision.enabled", _on)
                if _on:
                    # ВЗВОДИМ ВЗГЛЯД (2026-08-13): включить глаза просят не
                    # ради самого тумблера, а чтобы посмотреть. Раньше
                    # тумблер щёлкал, а кадра не было ни в этом ходу, ни в
                    # следующем — и она рассказывала про экран по памяти.
                    try:
                        from server import vision as _v
                        _v.want_look_next()
                    except Exception:
                        pass
                    return ("зрение ВКЛЮЧЕНО. Кадра в ЭТОМ ответе ещё нет — "
                            "он появится со следующей фразой человека. "
                            "Поэтому СЕЙЧАС не описывай ничего увиденного: "
                            "скажи коротко, что открыла глаза и смотрю.")
                return "зрение выключено"
            if name == "find_folder":
                hits = _pc.find_folder(str(a.get("query", "")),
                                       str(a.get("drive", "")))
                if not hits:
                    return ("ничего похожего не нашла — уточни название или "
                            "назови диск")
                return ("нашла варианты (покажи их человеку списком с "
                        "номерами и спроси, какой нужен):\n"
                        + "\n".join(f"{i + 1}. {h}"
                                    for i, h in enumerate(hits)))
            if name == "app_remember":
                from server import app_memory as _am
                from pathlib import Path as _P
                _nm = str(a.get("name", "")).strip()
                _pt = str(a.get("path", "")).strip().strip('"')
                if not _nm or not _pt:
                    return "нужны и название, и путь"
                if not _P(_pt).exists():
                    return (f"такого пути нет на диске: {_pt} — проверь, "
                            "человек мог опечататься")
                _am.remember(_nm.lower(), _P(_pt).stem, _pt)
                return (f"Запомнила: «{_nm}» — это {_pt}. Теперь открою по "
                        "одному слову.")
            if name == "remember_place":
                return _pc.remember_place(str(a.get("name", "")),
                                          str(a.get("path", "")))
            if name == "minimize_all":
                # ЗАЩИТА ОТ ЗАЛПА (2026-07-29, живой случай: «сверни
                # диспетчер задач» -> модель позвала minimize_all и смела
                # ВЕСЬ стол). Если человек назвал КОНКРЕТНОЕ окно — это
                # window_minimize, а не ковровое сворачивание.
                _ut = LAST_USER.get("text", "").lower()
                _mm = re.search(r"сверн\w*\s+(.+)", _ut)
                if _mm and not re.search(r"\bвс[её]\b|окна\b|лишн",
                                         _mm.group(1)):
                    return _pc.window_minimize(_mm.group(1).strip(" .!?"))
                return _pc.minimize_all(str(a.get("keep", "")))
            if name == "volume_set":
                return _pc.volume(percent=a.get("percent"),
                                  delta=a.get("delta"), mute=a.get("mute"))
            if name == "tab_control":
                return _pc.tab(str(a.get("action", "")),
                               int(a.get("index") or 0))
            if name == "open_folder":
                return _pc.open_folder(str(a.get("path", "")))
            if name == "folder_list":
                return _pc.folder_list(str(a.get("path", "")))
        except Exception as e:
            log.exception("pc tool %s", name)
            return f"не получилось: {e}"
    if name in _UIH_NAMES:
        import json as _json
        from server import ui_hands as _uh
        a = arguments if isinstance(arguments, dict) else (
            _json.loads(arguments) if arguments else {})
        a = a or {}
        try:
            if name == "web_open":
                _site = str(a.get("site", "")).strip()
                _q = str(a.get("query", "")).strip()
                if not _site:
                    # аргументы потеряны — достаём из фразы человека (в ней
                    # всё сказано: «открой ютуб и включи музычку»)
                    _site, _gq = _uh.guess_from_phrase(
                        LAST_USER.get("text", ""))
                    _q = _q or _gq
                    if not _site:
                        return ("не поняла, какой сайт — назови его "
                                "(ютуб, гугл, кинопоиск...)")
                return _uh.web_open(_site, _q)
            if name == "screen_read":
                return _uh.see()
            if name == "screen_click":
                return _uh.click(str(a.get("name", "")),
                                 bool(a.get("double")))
            if name == "keyboard_type":
                return _uh.type_text(str(a.get("text", "")))
            if name == "type_into":
                return _uh.type_into(str(a.get("field", "")),
                                     str(a.get("text", "")))
            if name == "key_press":
                return _uh.press(str(a.get("combo", "")))
            if name == "screen_scroll":
                return _uh.scroll(str(a.get("direction", "вниз")),
                                  int(a.get("times") or 3))
        except Exception as e:
            log.exception("ui_hands %s", name)
            return f"не получилось: {e}"
    if name in _UI_NAMES:
        import json as _json
        from server import ui_control as _ui
        a = arguments if isinstance(arguments, dict) else (
            _json.loads(arguments) if arguments else {})
        a = a or {}
        try:
            if name == "model_list":
                return _ui.model_list()
            return _ui.model_switch(str(a.get("name", "")),
                                    str(a.get("want", "")))
        except Exception as e:
            log.exception("ui tool %s", name)
            return f"не получилось переключить: {e}"
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
    # свои глаза: лог, ошибка, свой код (2026-08-05). Только чтение —
    # предохранителя намерения им не нужно.
    try:
        from server import self_read
        if name in self_read.NAMES:
            import json as _json
            args = arguments
            if isinstance(args, str):
                try:
                    args = _json.loads(args)
                except Exception:
                    args = {}
            try:
                return str(self_read.CALLS[name](args or {}))
            except PermissionError as e:
                return f"нельзя: {e}"
            except Exception as e:
                log.exception("self_read %s", name)
                return f"посмотреть не вышло: {e}"
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


# ═══════════ КАРТОЧКИ ИНСТРУМЕНТОВ: инструкции как RAG (2026-07-28) ═══════════
# Просьба владельца: инструкции по инструментам должны читаться ЛЮБОЙ моделью
# моментально, как раг-файл, и работать даже там, где function calling сломан.
# Карточки СТРОЯТСЯ ИЗ ЖИВЫХ СХЕМ (не пишутся руками — не протухают), в промпт
# уходит не вся простыня, а 1-3 карточки, релевантные фразе человека. Каждая
# показывает ОБА способа вызова: настоящий tool_call и текстовый маркер
# [имя:парам="значение"] — сервер исполняет оба (см. main.py, текст-протокол).

# фраза человека -> какие инструменты ему сейчас могут понадобиться
_TOOL_HINTS = {
    "open_folder":  ("папк", "проводник", "директори", "каталог"),
    "find_folder":  ("найди папк", "поищи папк", "где папк", "найти папк"),
    "app_launch":   ("запусти", "открой программ", "включи программ"),
    "apps_list":    ("какие программ", "список программ"),
    "window_close": ("закрой окно", "закрой прог"),
    "window_focus": ("переключись на", "покажи окно", "разверни"),
    "window_place": ("по центру", "в угол", "размести", "поставь окно",
                     "масштаб", "маштаб", "пол-экрана", "слева", "справа"),
    "window_maximize": ("разверни", "полный экран", "на весь экран",
                        "максимизируй"),
    "eyes": ("включи глаза", "выключи глаза", "включи зрение", "посмотри"),
    "minimize_all": ("сверни", "убери окна"),
    "volume_set":   ("громк", "звук", "тише", "громче"),
    "tab_control":  ("вкладк",),
    "web_search":   ("загугли", "найди в интернете", "поищи в", "погугли"),
    # 2026-08-13
    "web_list":     ("напиши в поиск", "введи в поиск", "набери в поиск",
                     "покажи что нашла", "дай список", "покажи список",
                     "покажи ссылки", "поищи и покажи"),
    "open_result":  ("открой первый", "открой второй", "открой третий",
                     "зайди на первый", "зайди на второй", "зайди на третий",
                     "открой номер", "давай второй", "давай третий"),
    "site_search":  ("впиши в поиск", "вписать в поиск", "найди на сайте",
                     "найди на ютубе", "поищи здесь", "поищи на этом сайте",
                     "в поисковую строку", "набери в строке"),
    "close_ad":     ("убери рекламу", "закрой рекламу", "закрой баннер",
                     "убери это окно", "закрой это окно", "мешает окно"),
    "window_focus": ("выведи на экран", "не вижу его", "не вижу её",
                     "покажи окно", "подними окно", "чтоб я увидел",
                     "дай посмотреть", "выведи вперёд"),
    "browser_scroll": ("пролистай", "прокрути", "промотай", "скролл",
                       "листай ниже", "ниже посмотри", "промотай вниз",
                       "промотай вверх", "в конец страницы"),
    "web_research": ("изучи", "исследуй", "разберись про"),
    "open_page":    ("открой сайт", "открой страниц", "зайди на"),
    "close_browser": ("закрой браузер",),
    "model_switch": ("модель", "поумнее", "побыстрее"),
    "remember_place": ("запомни папк", "запомни мест"),
    # руки внутри окон (2026-07-29)
    "web_open":     ("ютуб", "твич", "рутуб", "кинопоиск", "спотифай",
                     "включи на", "найди на сайте", "открой в браузере",
                     "озон", "авито", "маркет", "стим"),
    "type_into":    ("впиши", "введи в", "напиши в", "набери в",
                     "в строк", "в поле", "в поиск"),
    "keyboard_type": ("напечатай", "напиши текст", "введи текст"),
    "key_press":    ("нажми", "энтер", "отправь", "полный экран"),
    "screen_read":  ("что на экране", "что в окне", "прочитай окно",
                     "какие кнопки"),
    "screen_click": ("кликни", "тыкни", "ткни", "нажми на", "выбери"),
    "app_remember": ("запомни путь", "вот путь", "она находится", "лежит в",
                     ".exe", "это прога", "запомни программу"),
    # свои глаза (2026-08-05)
    "fs_lasterr":   ("сломал", "не работает", "что случилось", "почему упал",
                     "почему не получилось", "ошибка", "что у тебя"),
    "fs_log":       ("в логе", "лог сервера", "что в логах", "покажи лог",
                     "что там произошло", "проверь лог"),
    "fs_grep":      ("в своём коде", "в твоём коде", "как у тебя устроено",
                     "где это настраивается", "найди в коде", "почему так"),
    "fs_slice":     ("покажи код", "что там в файле", "открой строку"),
}

# СВЯЗКИ (2026-07-29, живой провал: «введи в поисковую строку в телеграме
# привет» — gemma РАССУЖДАЛА про экраны и переключения вместо двух вызовов).
# Карточка одного инструмента не учит порядку действий — а мелкой модели
# нужен именно готовый порядок. Фраза попала — подкладываем рецепт целиком.
_RECIPES = (
    # «ВЫБЕРИ САМА» (2026-08-13, живой вечер: на «давай найдём какой-нибудь
    # степ» и «выбери на своё усмотрение» она выдала два абзаца расспросов
    # про жанр, настроение и исполнителя — вместо того чтобы включить
    # музыку. Правило 10б в персоне про это есть почти дословно, но 13к
    # символов системного промпта мелкая модель не дочитывает. Связка
    # подкладывается прямо под фразу и потому срабатывает.)
    ((("выбери", "выбирай", "на твоё", "на своё", "сама реши", "сам реши",
       "какой-нибудь", "какую-нибудь", "что-нибудь", "чё-нибудь",
       "любой", "любую", "на усмотрение", "как хочешь", "тебе виднее",
       "давай найдём", "давай поищем"), ()),
     "### Тебе дали свободу выбора. Это НЕ приглашение к опросу.\n"
     "1. выбери сама — конкретное, не «что-нибудь нейтральное»;\n"
     "2. сделай это инструментом ПРЯМО СЕЙЧАС (открой, включи, найди);\n"
     "3. скажи ОДНОЙ короткой живой фразой, что выбрала и делаешь.\n"
     "Запрещено: спрашивать жанр/настроение/исполнителя, перечислять "
     "варианты, объяснять, почему выбор сложен, предупреждать, что «это не "
     "всегда то самое». Не угадала — он поправит одним словом, и ты "
     "переделаешь. Это дешевле анкеты.\n"
     "Не понравилось выбранное — тоже нормально: смени, а не оправдывайся."),
    # БРАУЗЕР: ПОРЯДОК ДЕЙСТВИЙ (2026-08-13, живой вечер — она умела только
    # ЗАПУСКАТЬ поиск. Дальше не шла: выдачу зачитывала вслух, по сайтам не
    # ходила, баннер её останавливал, прокрутки не существовало. Карточка
    # одного инструмента этому не учит — нужен готовый порядок.)
    ((("найди", "поищи", "посмотри", "узнай", "что нового", "проверь",
       "разузнай", "загугли", "погугли"),
      ("в интернете", "в сети", "новост", "патч", "обновлен", "вышл",
       "релиз", "цена", "стоит", "отзыв", "что за", "кто так")),
     "### Рецепт «разобраться в теме» (делай по шагам, не описывай план):\n"
     "1. [web_research:query=\"суть вопроса\"] — сама прочитает десяток "
     "сайтов и вернёт сводку С ДАТАМИ, а нужный абзац откроет и подсветит "
     "человеку на экране;\n"
     "2. если в сводке сказано, что ответа в материалах НЕТ — так и скажи. "
     "Пересказывать общие ожидания вместо фактов НЕЛЬЗЯ, это враньё;\n"
     "3. мало — уточни запрос другими словами и повтори, а не выдумывай.\n"
     "web_search бери только для короткого факта (дата, курс, погода)."),
    ((("покажи", "дай", "выведи", "напиши", "впиши", "введи", "набери"),
      ("список", "ссылк", "в поиск", "поисковую строку", "что нашла",
       "варианты", "сайты")),
     "### Рецепт «человек хочет ВЫБРАТЬ сам» (по шагам):\n"
     "1. поиск в интернете — [web_list:query=\"запрос\"]: список с "
     "номерами покажется ему сам, вслух его НЕ перечисляй;\n"
     "2. поиск ВНУТРИ открытого сайта (ютуб, магазин) — "
     "[site_search:text=\"запрос\"], строку он чистит сам;\n"
     "3. человек назвал номер — [open_result:n=2].\n"
     "Не зачитывай заголовки: он их уже видит, ему нужен только твой "
     "короткий комментарий."),
    ((("прочитай", "почитай", "посмотри", "изучи", "что там", "открой",
       "разбери", "мешает", "не видно", "ниже", "дальше"),
      ("страниц", "сайт", "статью", "реклам", "баннер", "окно", "текст")),
     "### Рецепт «читать открытую страницу» (по шагам):\n"
     "1. поверх страницы висит баннер или окно подписки — [close_ad], "
     "иначе не прочитаешь и не кликнешь;\n"
     "2. нужного на первом экране нет — [browser_scroll:direction=\"down\"], "
     "вернётся ТЕКСТ, который оказался на экране; повторяй, пока не "
     "найдёшь, а не гадай;\n"
     "3. промахнулась — [browser_scroll:direction=\"top\"] и заново.\n"
     "Прокручивать и закрывать баннеры — твоя работа, спрашивать "
     "разрешения на это не надо."),
    ((("впиши", "введи", "напиши", "набери"),
      ("телеграм", "телег", "дискорд", "чат", "браузер", "поиск", "строк")),
     "### Рецепт «вписать текст в программу» (выполняй по шагам, без "
     "рассуждений):\n"
     "1. [window_focus:match=\"телеграм\"] — окно вперёд (экран НЕ важен, "
     "фокус работает на любом);\n"
     "2. [type_into:field=\"поиск\",text=\"привет\"] — найдёт поле, кликнет, "
     "впишет;\n"
     "3. отправка ТОЛЬКО после вопроса человеку «текст готов, отправляем?» "
     "и его «да»: [key_press:combo=\"enter\"].\n"
     "Не спрашивай, на каком экране программа. Не описывай план — делай."),
    ((("включи", "найди", "открой", "запусти"),
      ("ютуб", "твич", "рутуб", "кинопоиск", "спотифай", "музык")),
     "### Рецепт «включить что-то на сайте» (по шагам):\n"
     "1. [web_open:site=\"ютуб\",query=\"что ищем\"] — откроется сразу "
     "страница результатов;\n"
     "2. подожди пару секунд, [screen_read] — увидишь элементы;\n"
     "3. [screen_click:name=\"имя из списка\"] — открыть нужное.\n"
     "Не открывай главную и не печатай в строку поиска сайта — web_open "
     "уже ищет сам."),
    ((("запусти", "открой"), ("на втором экране", "на первом экране",
                              "на второй экран", "на первый экран")),
     "### Рецепт «открыть на нужном экране» (по шагам):\n"
     "1. открой программу ([app_launch:name=\"...\"] или "
     "[open_folder:path=\"...\"]);\n"
     "2. [window_place:match=\"её окно\",monitor=2] — перенос на экран 2 "
     "(номера — как в настройках дисплея Windows).\n"
     "Само на второй экран ничего не открывается — нужен второй шаг."),
    ((("перенеси", "перекинь", "перемести", "переставь", "перетащи",
       "перенос"), ("экран", "монитор")),
     "### Рецепт «перенести окно на экран» (ОДИН вызов, сразу):\n"
     "[window_place:match=\"хром\",monitor=2] — на экран 2; "
     "monitor=-1 — на противоположный («на другой экран»); monitor=1 — на "
     "основной. match можно опустить — возьмётся активное окно.\n"
     "ЗРЕНИЕ (eyes) для окон НЕ нужно: положение окон я и так знаю, "
     "[window_list] покажет карту. Параметр monitor ОБЯЗАТЕЛЬНО передай — "
     "без него окно останется на своём экране."),
)


def _recipes(t: str) -> list:
    out = []
    for (verbs, ctx), text in _RECIPES:
        if any(v in t for v in verbs) and any(c in t for c in ctx):
            out.append(text)
    return out


def _one_card(sc: dict) -> str:
    f = sc.get("function", {})
    name = f.get("name", "?")
    desc = (f.get("description") or "").split("\n")[0][:160]
    params = (f.get("parameters") or {}).get("properties") or {}
    req = set((f.get("parameters") or {}).get("required") or [])
    lines = [f"• {name} — {desc}"]
    if params:
        ps = []
        for k, v in list(params.items())[:4]:
            mark = "*" if k in req else ""
            ps.append(f"{k}{mark} ({(v.get('description') or v.get('type') or '')[:40]})")
        lines.append("  параметры: " + "; ".join(ps) + ("  (* — обязателен)" if req else ""))
        k0 = (sorted(req)[0] if req else list(params)[0])
        # без слова «вызов» перед скобкой: gemma однажды склеила его ВНУТРЬ
        # маркера ([вызов:window_place]) и все действия улетали в никуда
        lines.append(f'  напиши в ответе: [{name}:{k0}="значение"]')
    else:
        lines.append(f"  напиши в ответе: [{name}]")
    return "\n".join(lines)


def usage_cards(user_text: str, limit: int = 3) -> str:
    """1-3 карточки инструментов, релевантных фразе. Пусто = фраза не про
    инструменты, промпт не раздуваем."""
    t = (user_text or "").lower()
    if not t:
        return ""
    hits = [n for n, keys in _TOOL_HINTS.items()
            if any(k in t for k in keys)]
    recipes = _recipes(t)
    if not hits and not recipes:
        return ""
    cards, known = [], {}
    for sc in schemas():
        known[sc.get("function", {}).get("name")] = sc
    for n in hits[:limit]:
        if n in known:
            cards.append(_one_card(known[n]))
    if not cards and not recipes:
        return ""
    out = ""
    if recipes:
        # рецепт главнее карточек: он уже содержит порядок и имена
        out += "\n".join(recipes[:2]) + "\n"
    if cards:
        out += ("### Как вызвать нужный инструмент (инструкция, факт):\n"
                + "\n".join(cards) +
                "\nЗови как настоящую функцию (tool_call), а если не умеешь "
                "— напиши маркер в квадратных скобках прямо в ответе: сервер "
                "исполнит его сам и покажет результат.")
    return out.strip()


def write_guide() -> str:
    """Полный справочник ВСЕХ инструментов в data/tools_guide.md — для
    дообучения, внешнего RAG и любой модели, которой дадут файл целиком.
    Перегенерируется на каждом старте: источник — живые схемы."""
    from server.config import resolve as _resolve
    lines = ["# Инструменты Сайки — как вызывать (автогенерация, не править)",
             "",
             "Два равноправных способа: настоящий tool_call (если модель "
             "умеет) или текстовый маркер [имя:парам=\"значение\"] прямо в "
             "ответе — сервер исполняет оба.", ""]
    for sc in schemas():
        lines.append(_one_card(sc))
        lines.append("")
    p = _resolve("data/tools_guide.md")
    try:
        p.parent.mkdir(exist_ok=True)
        p.write_text("\n".join(lines), encoding="utf-8")
        log.info("Справочник инструментов обновлён: %s (%d шт.)",
                 p, len(schemas()))
    except Exception as e:
        log.warning("справочник инструментов не записался: %s", e)
    return str(p)
