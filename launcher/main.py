"""ANAMORF.exe — тонкий лаунчер.

Он не делает почти ничего, и это осознанно. Всё, что он умеет:

    1. применить скачанное обновление, пока приложение ещё не запущено;
    2. найти интерпретатор в runtime\\ и поднять сервер;
    3. открыть окно;
    4. если сервер не встал — вернуть предыдущую версию и сказать об этом.

Почему лаунчер отдельно и почему тонкий. Заморозить весь проект в один exe
нельзя: torch с CUDA, comtypes с генерацией COM-обёрток и pywinauto в
PyInstaller — это гарантированные многодневные раскопки и ложные
срабатывания антивирусов. Поэтому код и интерпретатор лежат обычными
файлами, а замораживается только вот этот файл — полтора мегабайта, которые
нечему ломать.

Второе следствие: обновление — это подмена папки app\\, а не переустановка
двенадцати гигабайт. Подменять её может только тот, кто сам не запущен из
неё. Отсюда правило: обновление применяется ДО старта сервера.

Раскладка:

    ANAMORF.exe        мы
    runtime\\           интерпретатор и пакеты
    app\\               код, только он и обновляется
    app.new\\           скачанное обновление, ждёт перезапуска
    app.prev\\          предыдущая версия, страховка на один шаг назад
    models\\ data\\      модели и всё личное — обновление их не касается
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HERE = Path(getattr(sys, "_MEIPASS", "")).parent if getattr(sys, "frozen", False) \
    else Path(__file__).resolve().parent
ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else HERE.parent

APP = ROOT / "app"
APP_NEW = ROOT / "app.new"
APP_PREV = ROOT / "app.prev"
RUNTIME = ROOT / "runtime"
LOGS = ROOT / "data" / "logs"

START_TIMEOUT = 90        # столько ждём, пока сервер займёт порт
HEALTHY_AFTER = 60        # прожил столько — считаем обновление удачным


def say(msg: str) -> None:
    print(f"[ANAMORF] {msg}", flush=True)
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with open(LOGS / "launcher.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


# ------------------------------------------------------------- обновление

def apply_update() -> None:
    """Подменить app\\ скачанным обновлением. Только здесь и только сейчас.

    Папку, из которой работает запущенный Python, на Windows не
    переименовать: файлы держатся открытыми. Поэтому апдейтер лишь кладёт
    рядом app.new\\, а подмена происходит до старта — то есть здесь.
    """
    if not APP_NEW.is_dir():
        return
    say("найдено обновление, применяю")
    try:
        if APP_PREV.is_dir():
            shutil.rmtree(APP_PREV, ignore_errors=True)
        if APP.is_dir():
            APP.rename(APP_PREV)
        APP_NEW.rename(APP)
        say("обновление применено")
    except Exception as e:
        say(f"обновление не применилось ({e}) — остаюсь на прежней версии")
        if not APP.is_dir() and APP_PREV.is_dir():
            try:
                APP_PREV.rename(APP)
            except Exception:
                pass


def rollback() -> bool:
    """Вернуть предыдущую версию. Один шаг назад, дальше — переустановка."""
    if not APP_PREV.is_dir():
        return False
    say("откатываюсь на предыдущую версию")
    try:
        broken = ROOT / "app.broken"
        shutil.rmtree(broken, ignore_errors=True)
        if APP.is_dir():
            APP.rename(broken)
        APP_PREV.rename(APP)
        return True
    except Exception as e:
        say(f"откат не удался: {e}")
        return False


def version() -> str:
    for p in (APP / "VERSION", ROOT / "VERSION"):
        try:
            return p.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return "?"


# ----------------------------------------------------------------- запуск

def python_exe() -> Path | None:
    exe = "python.exe" if os.name == "nt" else "python"
    p = RUNTIME / exe
    return p if p.exists() else None


def port() -> int:
    for name in ("config.user.json", "config.json", "config.default.json"):
        try:
            d = json.loads((ROOT / name).read_text(encoding="utf-8"))
            return int(d.get("server", {}).get("port", 8765))
        except Exception:
            continue
    return 8765


def alive(p: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", p)) == 0


def start_server() -> subprocess.Popen | None:
    py = python_exe()
    if py is None:
        say("не нашла интерпретатор в runtime\\ — установка повреждена")
        return None
    env = dict(os.environ)
    env["PYTHONPATH"] = str(APP)
    # Кэш COM-обёрток: в папке приложения его писать нельзя (Program Files
    # закрыт на запись), а без своего места comtypes попробует и упадёт.
    env.setdefault("COMTYPES_CACHE_DIR", str(ROOT / "data" / "comtypes"))
    env.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
    env.setdefault("TORCH_HOME", str(ROOT / "models" / "torch"))
    say(f"запускаю сервер, версия {version()}")
    flags = 0x08000000 if os.name == "nt" else 0        # без чёрного окна
    return subprocess.Popen([str(py), "-m", "anamorf.main"],
                            cwd=str(APP), env=env, creationflags=flags)


def wait_ready(proc: subprocess.Popen, p: int) -> bool:
    t0 = time.time()
    while time.time() - t0 < START_TIMEOUT:
        if alive(p):
            say(f"сервер поднялся за {time.time() - t0:.0f}с")
            return True
        if proc.poll() is not None:
            say(f"сервер завершился сам, код {proc.returncode}")
            return False
        time.sleep(0.4)
    say("сервер не ответил за отведённое время")
    return False


def open_window(url: str) -> None:
    """Своё окно, если есть чем. Нет — обычная вкладка браузера.

    Окно приятнее, но падать из-за его отсутствия было бы глупо: человеку
    нужна Сайка, а не именно окно.
    """
    try:
        import webview
    except ImportError:
        say("окна нет, открываю вкладку в браузере")
        webbrowser.open(url)
        return
    say("открываю окно")
    webview.create_window("ANAMORF", url, width=1360, height=900,
                          min_size=(900, 620), text_select=True)
    webview.start()


# ------------------------------------------------------------------ ход

def main() -> int:
    apply_update()

    if not APP.is_dir():
        say("нет папки app\\ — установка повреждена, переустанови приложение")
        return 1

    p = port()
    if alive(p):
        say("уже запущено — открываю окно")
        open_window(f"http://127.0.0.1:{p}")
        return 0

    proc = start_server()
    if proc is None:
        return 1

    if not wait_ready(proc, p):
        # Не встал сразу после обновления — виновато обновление.
        if APP_PREV.is_dir() and rollback():
            proc2 = start_server()
            if proc2 and wait_ready(proc2, p):
                say("вернулась на предыдущую версию, она работает")
                open_window(f"http://127.0.0.1:{p}")
                return 0
        say("запустить не получилось. Загляни в data\\logs\\launcher.log")
        return 1

    started = time.time()
    open_window(f"http://127.0.0.1:{p}")

    # Окно закрыли — гасим сервер. Прожил дольше HEALTHY_AFTER — считаем
    # версию удачной и убираем страховку, чтобы не копить старые копии.
    if time.time() - started > HEALTHY_AFTER and APP_PREV.is_dir():
        shutil.rmtree(APP_PREV, ignore_errors=True)
    try:
        proc.terminate()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
