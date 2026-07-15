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


def _url():
    return CFG.get("tools.handspc_url", "http://127.0.0.1:8767").rstrip("/")


def schemas() -> list:
    """Схемы инструментов (формат function calling). [] = HandsPC недоступен."""
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


def call(name: str, arguments) -> str:
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
        return str(r.json().get("result", ""))
    except Exception as e:
        return f"HandsPC недоступен: {e}"
