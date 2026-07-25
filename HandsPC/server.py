"""HandsPC — «руки» Сайки: отдельный сервис инструментов.

Из коробки (без API-ключей, работает на любом ПК):
  web_search  — поиск в интернете (DuckDuckGo через ddgs, с фолбэками)
  fetch_page  — открыть страницу и вытащить чистый текст (trafilatura)

Сюда же позже добавляются браузер (browser-use) и управление мышью — Сайка
подхватит новые инструменты автоматически: она читает их список с /tools.

Протокол:
  GET  /health -> {"ok": true, "tools": [...имена...]}
  GET  /tools  -> [{...схемы в формате OpenAI/Ollama function calling...}]
  POST /call   {"name": "...", "arguments": {...}} -> {"result": "текст"}

Запуск: run.bat (сам создаст venv и поставит зависимости) или из start.bat
Сайки — он поднимает HandsPC автоматически, если папка есть рядом.
"""
import json
import logging
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parent
(ROOT / "logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(),
              logging.FileHandler(ROOT / "logs" / "handspc.log",
                                  encoding="utf-8")])
log = logging.getLogger("handspc")

PORT = 8767
app = FastAPI(title="HandsPC")

# ---------------- инструменты ----------------

def web_search(query: str, max_results: int = 5) -> str:
    """Поиск без ключей через ddgs. Быстрые движки, короткий таймаут и один
    ретрай: сеть у пользователя может моргать на секунды (os error 10051)."""
    import time
    from ddgs import DDGS
    last = None
    for attempt in (1, 2):
        try:
            rows = []
            with DDGS(timeout=6) as d:
                try:
                    results = d.text(query, max_results=int(max_results),
                                     backend="duckduckgo, yandex, google")
                except TypeError:  # старые ddgs без параметра backend
                    results = d.text(query, max_results=int(max_results))
                for r in results:
                    rows.append(f"- {r.get('title')}\n  {r.get('href')}\n"
                                f"  {r.get('body', '')[:300]}")
            if rows:
                return "\n".join(rows)
            last = "пусто"
        except Exception as e:
            last = str(e)
            log.warning("web_search попытка %s: %s", attempt, e)
        time.sleep(2)
    return (f"Поиск не удался (сеть моргает или движки недоступны): {last}. "
            f"Скажи пользователю, что сеть шалит, и предложи повторить.")


def get_weather(city: str) -> str:
    """Погода через Open-Meteo — без ключей и без поисковиков."""
    import requests as rq
    g = rq.get("https://geocoding-api.open-meteo.com/v1/search",
               params={"name": city, "count": 1, "language": "ru"},
               timeout=8).json()
    if not g.get("results"):
        return f"Не нашёл город «{city}»."
    loc = g["results"][0]
    w = rq.get("https://api.open-meteo.com/v1/forecast",
               params={"latitude": loc["latitude"], "longitude": loc["longitude"],
                       "current": "temperature_2m,apparent_temperature,"
                                  "relative_humidity_2m,wind_speed_10m,"
                                  "weather_code",
                       "timezone": "auto"}, timeout=8).json()
    c = w.get("current", {})
    codes = {0: "ясно", 1: "почти ясно", 2: "переменная облачность",
             3: "пасмурно", 45: "туман", 48: "изморозь", 51: "морось",
             53: "морось", 55: "сильная морось", 61: "небольшой дождь",
             63: "дождь", 65: "ливень", 66: "ледяной дождь", 67: "ледяной дождь",
             71: "небольшой снег", 73: "снег", 75: "сильный снег",
             77: "снежная крупа", 80: "кратковременный дождь", 81: "ливни",
             82: "сильные ливни", 85: "снегопад", 86: "сильный снегопад",
             95: "гроза", 96: "гроза с градом", 99: "гроза с сильным градом"}
    return (f"{loc['name']}: {codes.get(c.get('weather_code'), '')}, "
            f"{c.get('temperature_2m')}°C (ощущается "
            f"{c.get('apparent_temperature')}°C), влажность "
            f"{c.get('relative_humidity_2m')}%, ветер "
            f"{c.get('wind_speed_10m')} км/ч.")


def fetch_page(url: str, max_chars: int = 4000) -> str:
    """Скачивает страницу и возвращает чистый текст статьи."""
    import trafilatura
    html = trafilatura.fetch_url(url)
    if not html:
        return f"Не удалось скачать {url}"
    text = trafilatura.extract(html) or ""
    return text[:int(max_chars)] or "Текст извлечь не удалось."


def browser_task(task: str, max_steps: int = 15) -> str:
    """Выполнить задачу в браузере (browser-use + Playwright Chromium).
    Окно браузера ОТКРЫТО — пользователь видит каждый клик агента."""
    import asyncio
    from browser_use import Agent, ChatOllama

    model = os.environ.get("HANDSPC_BROWSER_MODEL", "qwen3.6:latest")
    host = os.environ.get("HANDSPC_OLLAMA_URL", "http://127.0.0.1:11434")
    llm = ChatOllama(model=model, host=host)

    async def _run():
        # llm_timeout: локальной модели с забитой VRAM надо больше 75с на шаг;
        # max_failures: если браузер закрыли, не мучиться шестью ретраями
        kw = dict(task=task, llm=llm)
        for extra in ({"use_vision": False, "llm_timeout": 180,
                       "max_failures": 2},
                      {"llm_timeout": 180, "max_failures": 2},
                      {"max_failures": 2}, {}):
            try:
                agent = Agent(**kw, **extra)
                break
            except TypeError:  # параметры зависят от версии browser-use
                continue
        history = await agent.run(max_steps=min(int(max_steps), 25))
        result = None
        for attr in ("final_result", "last_action_result"):
            try:
                result = getattr(history, attr)()
                break
            except Exception:
                continue
        return str(result) if result else "Сделал, но итог получился пустым."

    CLOSED_MARKERS = ("target closed", "browser is closed", "browser closed",
                      "connection closed", "websocket", "disconnected",
                      "no such window", "target crashed", "cdp")

    log.info("browser_task: %s", task)
    try:
        return asyncio.run(_run())
    except Exception as e:
        s = str(e).lower()
        if any(k in s for k in CLOSED_MARKERS):
            log.info("browser_task: пользователь закрыл браузер")
            return ("ПОЛЬЗОВАТЕЛЬ ЗАКРЫЛ ОКНО БРАУЗЕРА — задача прервана на "
                    "середине, результата нет. Отреагируй на это живо и в "
                    "своём характере (удивись/возмутись/пошути — как тебе "
                    "свойственно), и спроси, нужно ли продолжить.")
        raise


def _browser_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("browser_use") is not None


TOOLS = {
    "web_search": {
        "fn": web_search,
        "schema": {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": ("Поиск в интернете (DuckDuckGo). Используй для "
                                "актуального: новости, погода, цены, курсы, "
                                "события и факты, которых можешь не знать."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string",
                                  "description": "поисковый запрос"},
                        "max_results": {"type": "integer",
                                        "description": "сколько результатов (1-10)"},
                    },
                    "required": ["query"],
                },
            },
        },
    },
    "get_weather": {
        "fn": get_weather,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": ("Текущая погода в городе (Open-Meteo). "
                                "Для вопросов о погоде используй ЭТОТ "
                                "инструмент, а не web_search."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string",
                                 "description": "название города"},
                    },
                    "required": ["city"],
                },
            },
        },
    },
    "fetch_page": {
        "fn": fetch_page,
        "schema": {
            "type": "function",
            "function": {
                "name": "fetch_page",
                "description": ("Открыть веб-страницу по URL и получить её "
                                "текст. Используй после web_search, чтобы "
                                "прочитать подробности по ссылке."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "адрес страницы"},
                    },
                    "required": ["url"],
                },
            },
        },
    },
}

# браузерные руки — опциональны (ставятся add_browser.bat);
# регистрируем инструмент только если browser-use установлен
if _browser_available():
    TOOLS["browser_task"] = {
        "fn": browser_task,
        "schema": {
            "type": "function",
            "function": {
                "name": "browser_task",
                "description": (
                    "Выполнить задачу в реальном браузере: открыть сайт, "
                    "кликать, заполнять формы, что-то найти и сделать. "
                    "Пользователь видит окно браузера и твои действия. "
                    "Используй для многошаговых задач на сайтах; для простого "
                    "поиска информации бери web_search — он быстрее. "
                    "Задачу формулируй подробно, на английском или русском."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string",
                                 "description": "что сделать в браузере, подробно"},
                        "max_steps": {"type": "integer",
                                      "description": "лимит шагов (по умолчанию 15)"},
                    },
                    "required": ["task"],
                },
            },
        },
    }

# ---------------- API ----------------

@app.get("/health")
def health():
    return {"ok": True, "tools": list(TOOLS)}


@app.get("/tools")
def tools():
    return [t["schema"] for t in TOOLS.values()]


@app.post("/call")
def call(payload: dict):
    name = payload.get("name")
    args = payload.get("arguments") or {}
    opts = payload.get("options") or {}
    # Сайка может задать модель для браузера (config tools.browser_model)
    if opts.get("browser_model"):
        os.environ["HANDSPC_BROWSER_MODEL"] = str(opts["browser_model"])
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    tool = TOOLS.get(name)
    if not tool:
        return {"result": f"Нет такого инструмента: {name}"}
    log.info("call %s %s", name, args)
    try:
        return {"result": str(tool["fn"](**args))}
    except Exception as e:
        log.exception("tool %s failed", name)
        return {"result": f"Ошибка инструмента {name}: {e}"}


if __name__ == "__main__":
    # уже запущен (start.bat Сайки стартует нас не глядя) — тихо выходим
    import socket
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", PORT))
        probe.close()
    except OSError:
        log.info("Порт %s занят — HandsPC уже работает, выходим.", PORT)
        raise SystemExit(0)
    log.info("HandsPC слушает на 127.0.0.1:%s, инструменты: %s",
             PORT, ", ".join(TOOLS))
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
