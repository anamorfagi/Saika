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
    return local + _hands_schemas()


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


def call(name: str, arguments) -> str:
    if name in _LOCAL_NAMES:
        return _local_call(name, arguments)
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
