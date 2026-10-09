"""Открыть новую оболочку в браузере по умолчанию.

Автооткрытие при старте молчит, если к серверу уже подключено хоть одно
окно (data/ui_seen.txt + EVENT_CLIENTS): защита от четырёх вкладок при
перезапуске. Любая подключённая страница — даже служебная — считается
«вкладка уже есть», и своего браузера человек не получает. Этот скрипт
открывает её принудительно и сразу на /app.
"""
import webbrowser
import json
import pathlib

port = 8765
try:
    cfg = json.loads(pathlib.Path("config.json").read_text(encoding="utf-8"))
    port = int(cfg.get("server.port", cfg.get("server", {}).get("port", 8765)))
except Exception:
    pass

url = f"http://127.0.0.1:{port}/app"
print("открываю", url)
print("получилось:", webbrowser.open(url))
