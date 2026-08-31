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
import threading
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


# ═══ ОДНО ОКНО — А НЕ ДВА (30.08.2026) ═══
# Живой случай: сторож раз в 4-5 минут решал, что Сайка зависла (порт
# отвечает, а logs\saika.log какое-то время не растёт — это бывает и
# на пустом месте, когда просто нет новых событий для лога), и поднимал
# ANAMORF.exe заново. Новый процесс видел, что порт жив, НЕ трогал
# сервер — но безусловно рисовал СВОЁ окно поверх уже открытого. Человек
# видел вторую полупрозрачную копию программы у себя на экране.
#
# Проверка «жив ли сервер» и проверка «есть ли уже окно» — разные вещи,
# а раньше окно опиралось только на первую. Правим это отдельным
# замком: как и сторож (порт 8759), окно занимает свой порт на время
# жизни. Если он уже занят — окно уже где-то открыто, и рисовать второе
# незачем: тихо выходим, ничего не трогая и ничего не показывая.
_WINDOW_LOCK_PORT = 8760
_window_lock_sock: socket.socket | None = None


def _acquire_window_lock() -> bool:
    global _window_lock_sock
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", _WINDOW_LOCK_PORT))
        s.listen(1)
    except OSError:
        s.close()
        return False
    _window_lock_sock = s  # держать открытым весь срок жизни процесса
    return True


_JOB = None            # держать глобально: закроется хэндл — умрёт вся ветка


def adopt(proc) -> None:
    """Привязать сервер и всё, что он породит, к жизни лаунчера.

    Проблема, которую это решает, видна невооружённым глазом: человек
    закрывает окно, а в диспетчере остаются python.exe и llama-server.exe.
    Пересобрать билд поверх них нельзя — Windows держит их DLL. Выглядит
    это как «я всё закрыл, а оно говорит что запущено», и человек прав.

    Почему одного terminate() мало. Мы порождаем python.exe, а тот сам
    порождает llama-server.exe. terminate() убивает только первого; внук
    остаётся сиротой и живёт дальше, потому что в Windows связь
    «родитель-ребёнок» после смерти родителя не значит ничего.

    Job Object значит. Все процессы ветки складываются в одну «job», у
    которой стоит флаг KILL_ON_JOB_CLOSE: закрылся последний хэндл на job
    — ядро убивает всех, кто в ней. Хэндл закрывается, когда умирает наш
    процесс, — ЛЮБОЙ смертью, включая снятие через диспетчер задач и
    падение. Обещание сдерживает ядро, а не наш код в блоке finally,
    который при аварийном выходе просто не выполнится.
    """
    global _JOB
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes as w

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in
                        ("ReadOperationCount", "WriteOperationCount",
                         "OtherOperationCount", "ReadTransferCount",
                         "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", w.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", w.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", w.DWORD),
                        ("SchedulingClass", w.DWORD)]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC),
                        ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9

        k32.CreateJobObjectW.restype = w.HANDLE
        k32.OpenProcess.restype = w.HANDLE
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                    ctypes.byref(info), ctypes.sizeof(info))
        PROCESS_SET_QUOTA, PROCESS_TERMINATE = 0x0100, 0x0001
        h = k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, proc.pid)
        if h:
            k32.AssignProcessToJobObject(job, h)
            k32.CloseHandle(h)
        _JOB = job
        say("сервер привязан к окну — закроется вместе с ним")
    except Exception as e:
        # Не повод не запускаться: без job всё работает как раньше, просто
        # сироты придётся снимать руками.
        say(f"привязать сервер не вышло ({type(e).__name__}: {e})")


def stop(proc) -> None:
    """Погасить ветку целиком, не полагаясь на job.

    Job гарантирует уборку при смерти лаунчера, но при нормальном выходе
    гасить лучше явно и дождаться: так к моменту, когда exe исчезнет из
    диспетчера, DLL уже отпущены и пересборка не упрётся в занятый файл.
    """
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           creationflags=0x08000000,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10)
        else:
            proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


# Код выхода, которым сервер просит поднять его заново (см. _hot_restart
# в anamorf/main.py). Всё остальное — обычная смерть, окно закрывается.
RESTART_CODE = 7


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
    # Вкладку в браузере сервер не открывает: окно откроем мы сами. Без
    # этого на каждый запуск получалось два интерфейса — окно приложения
    # и вкладка поверх него, оба живые и оба слушают один сервер.
    env["SAIKA_AUTO_OPEN"] = "0"
    env["ANAMORF_AUTO_OPEN"] = "0"
    # РУКОПОЖАТИЕ ПРО ПЕРЕЗАПУСК (2026-08-23). Сервер сам не знает, какой
    # лаунчер его поднял: exe у человека может быть собран до того, как мы
    # научились ловить код 7, и тогда «переехать» означало бы тихо убить
    # приложение (так уже было). Поэтому не гадаем — говорим прямо: этот
    # лаунчер умеет поднимать сервер обратно. Нет переменной — сервер
    # честно попросит человека нажать «⟳ Перезапустить».
    env["ANAMORF_RESTART_CODE"] = str(RESTART_CODE)
    env.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
    env.setdefault("TORCH_HOME", str(ROOT / "models" / "torch"))
    say(f"запускаю сервер, версия {version()}")
    flags = 0x08000000 if os.name == "nt" else 0        # без чёрного окна

    # Вывод сервера ОБЯЗАН куда-то деваться. Первый же запуск собранного
    # билда упал за секунду, и разбираться было не с чем: окна нет, поток
    # вывода некуда деть — он и пропал. «Не запустилось, причина неизвестна»
    # — худшее, что программа может сказать человеку.
    LOGS.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / "server.log"
    try:
        out = open(log_path, "a", encoding="utf-8", errors="replace")
        out.write(f"\n{'=' * 60}\n{time.strftime('%Y-%m-%d %H:%M:%S')} "
                  f"запуск {version()}\n{'=' * 60}\n")
        out.flush()
    except Exception:
        out = subprocess.DEVNULL
    proc = subprocess.Popen([str(py), "-m", "anamorf.main"],
                            cwd=str(APP), env=env, creationflags=flags,
                            stdout=out, stderr=subprocess.STDOUT)
    adopt(proc)
    return proc


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


def _patch_webview_media_flag():
    """Флаг браузера --auto-accept-camera-and-microphone-capture должен
    выдавать разрешение на микрофон сразу, без диалога — от него зависит
    и сам звук, и то, видит ли браузер настоящий список устройств вывода,
    а не одно безымянное «по умолчанию» (без разрешения Chromium из
    приватности схлопывает список выходов до одной записи).

    Раньше флаг клали в переменную окружения WEBVIEW2_ADDITIONAL_BROWSER_
    ARGUMENTS. Она не работала НИКОГДА: pywebview сам строит свою строку
    AdditionalBrowserArguments и передаёт её WebView2 явно через
    CoreWebView2CreationProperties — а спецификация WebView2 однозначна:
    явно переданное значение полностью перекрывает переменную окружения,
    та просто не читается.

    Чиним не переменную окружения, а сам pywebview: дописываем наш флаг
    в ту же строку, что строит он сам. Идемпотентно и при каждом
    запуске — переустановка pywebview или пересборка exe когда-нибудь
    сотрёт правку, и тогда она просто наложится заново, никто не заметит.

    Флаг официально документирован Microsoft как штатный способ (см.
    webview-features-flags), но на практике после починки список устройств
    так и не ожил — подозрение, что WebView2 у этой версии рантайма его
    по каким-то причинам не слушает. Поэтому вдобавок, а не вместо,
    ниже включена вторая, уже не флаговая, а событийная выдача разрешения
    — через официальное событие PermissionRequested. Два независимых пути
    к одному результату надёжнее одного непроверяемого."""
    # Импортируем ТОЛЬКО верхний пакет: конкретный backend (edgechromium)
    # pywebview подгружает лениво, изнутри webview.start(), и если
    # затронуть его сейчас — правка в файл на диске на этот же запуск
    # уже не подействует, модуль в памяти останется старым. Путь и так
    # известен: platforms/edgechromium.py рядом с самим пакетом.
    try:
        import webview
    except Exception as e:
        say(f"не смог проверить pywebview для микрофона: {e}")
        return
    pkg_dir = os.path.dirname(getattr(webview, "__file__", "") or "")
    if pkg_dir:
        path = os.path.join(pkg_dir, "platforms", "edgechromium.py")
        needle = "'--disable-features=ElasticOverscroll'"
        fix = "--auto-accept-camera-and-microphone-capture"
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    src = f.read()
                if fix not in src:
                    if needle in src:
                        src = src.replace(
                            needle,
                            "'--disable-features=ElasticOverscroll " + fix + "'", 1)
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(src)
                        say("починил pywebview: флаг микрофона теперь доходит до WebView2")
                    else:
                        say("pywebview изменился — автопочинка флага микрофона больше не подходит по тексту")
            except Exception as e:
                say(f"не смог поправить флаг pywebview для микрофона: {e}")

    # ВТОРОЙ ПУТЬ: выдаём разрешение сами через PermissionRequested,
    # штатное событие CoreWebView2 для хост-приложений (см. WebView2
    # security docs, «программная выдача разрешений»). Оно не зависит от
    # того, слушает ли рантайм флаг командной строки, — мы отвечаем на
    # запрос напрямую. Разрешаем ТОЛЬКО микрофон и камеру: экран (для
    # зрения Сайки) как спрашивал, так и должен спрашивать.
    try:
        import webview.platforms.edgechromium as _ec
    except Exception as e:
        say(f"не смог подключить прямую выдачу разрешений: {e}")
        return
    if getattr(_ec.EdgeChrome, "_saika_permission_patched", False):
        return
    try:
        import clr
        clr.AddReference(_ec.interop_dll_path('Microsoft.Web.WebView2.Core.dll'))
        from Microsoft.Web.WebView2.Core import (
            CoreWebView2PermissionKind, CoreWebView2PermissionState)
    except Exception as e:
        say(f"не смог подключить прямую выдачу разрешений: {e}")
        return

    _ALLOWED = (CoreWebView2PermissionKind.Microphone, CoreWebView2PermissionKind.Camera)

    def _on_permission_requested(sender, args):
        try:
            if args.PermissionKind in _ALLOWED:
                args.State = CoreWebView2PermissionState.Allow
                args.Handled = True
        except Exception as e:
            say(f"не смог ответить на запрос разрешения: {e}")

    _orig_ready = _ec.EdgeChrome.on_webview_ready

    def _patched_ready(self, sender, args):
        _orig_ready(self, sender, args)
        try:
            if args.IsSuccess:
                self.webview.CoreWebView2.PermissionRequested += _on_permission_requested
        except Exception as e:
            say(f"не смог подписаться на запросы разрешений: {e}")

    _ec.EdgeChrome.on_webview_ready = _patched_ready
    _ec.EdgeChrome._saika_permission_patched = True
    say("подключил прямую выдачу разрешений на микрофон/камеру")


def open_window(url: str) -> bool:
    """Своё окно, если есть чем. Нет — обычная вкладка браузера.

    Возвращает True, если окно действительно было. Вызывающему это важно:
    от ответа зависит, гасить сервер после выхода или не трогать его.

    Окно приятнее, но падать из-за его отсутствия было бы глупо: человеку
    нужна Сайка, а не именно окно.

    МИКРОФОН СПРАШИВАЕТСЯ ОДИН РАЗ, А НЕ КАЖДЫЙ ЗАПУСК — И ВООБЩЕ НЕ
    СПРАШИВАЕТСЯ.

    Окно рисует WebView2, и для него наше приложение — обычный сайт. По
    умолчанию pywebview открывает его в приватном режиме: ничего не
    сохраняется между запусками, включая выданные разрешения. Отсюда и
    брало «Сайт 127.0.0.1:8765 хочет использовать микрофон» при каждом
    старте — а человек этот микрофон уже разрешил, и не раз.

    Постоянный профиль окна в data\\webview закрывает это наполовину:
    разрешение, выданное однажды, переживает перезапуск. Но диалог в
    этом безрамочном окне почти не виден, и без него профиль остаётся
    пустым — тогда браузер из соображений приватности схлопывает список
    устройств вывода звука до одного безымянного «по умолчанию» (ровно
    это увидел человек: «Устройство 1» вместо настоящих наушников/
    колонок/кабеля).

    Второй половиной — авто-выдачей разрешения флагом
    --auto-accept-camera-and-microphone-capture — раньше занималась
    переменная окружения WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS. Она не
    работала НИКОГДА: pywebview сам строит свою строку
    AdditionalBrowserArguments и передаёт её WebView2 явно, а явно
    переданное значение полностью перекрывает переменную окружения по
    спецификации. Теперь флаг дописывается прямо в pywebview —
    см. _patch_webview_media_flag() выше — и правда работает.

    Именно этот флаг, а НЕ --use-fake-ui-for-media-stream: второй заодно
    проглатывает запрос на захват экрана, а зрение Сайки работает через
    него, и мы бы молча разрешили ещё и это.
    """
    store = ROOT / "data" / "webview"
    try:
        store.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    _patch_webview_media_flag()

    try:
        import webview
    except Exception as e:
        # Причину пишем полностью. «Окна нет» без причины — это сообщение
        # ни о чём: чаще всего pywebview просто не установлен в том
        # питоне, которым собирали exe, и тогда PyInstaller молча
        # пропускает hiddenimports, а мы полгода думаем, что окно есть.
        say(f"окна нет ({type(e).__name__}: {e}) — открываю вкладку в браузере")
        webbrowser.open(url)
        return False

    say("открываю окно")
    webview.create_window("ANAMORF", url, width=1360, height=900,
                          min_size=(900, 620), text_select=True)
    try:
        webview.start(private_mode=False, storage_path=str(store))
    except TypeError:
        # Старая версия pywebview без этих параметров — не повод не
        # открыть окно. Разрешение будет спрашиваться, но работать будет.
        say("версия окна старая — профиль не сохраняю")
        webview.start()
    return True


# ------------------------------------------------------------------ ход

def main() -> int:
    apply_update()

    if not APP.is_dir():
        say("нет папки app\\ — установка повреждена, переустанови приложение")
        return 1

    if not _acquire_window_lock():
        # Окно уже открыто в другом процессе (см. комментарий у
        # _acquire_window_lock) — новое не рисуем, сервер не трогаем.
        say("окно уже открыто в другом экземпляре — выхожу")
        return 0

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
        # Показываем хвост прямо здесь: человек не должен искать файл,
        # чтобы узнать, почему ничего не произошло.
        try:
            tail = (LOGS / "server.log").read_text(
                encoding="utf-8", errors="replace").strip().split("\n")[-12:]
            say("последнее, что сказал сервер:")
            for line in tail:
                say("   " + line)
        except Exception:
            pass
        say("подробности: data\\logs\\server.log")
        return 1

    started = time.time()

    # ПЕРЕЗАПУСК СЕРВЕРА БЕЗ ЗАКРЫТИЯ ОКНА (2026-08-22). Сервер живёт
    # дочерним процессом и привязан к окну, поэтому сам он себя заменить
    # не может: подмена образа (os.execv) рвёт эту связь, и приложение
    # исчезает наполовину — окно есть, сервера нет. Пусть просит нас:
    # выход с кодом 7 значит «подними меня заново, окно не трогай». Так
    # обновление кода перестаёт стоить человеку закрытия программы.
    holder = {"proc": proc}

    def _watch_restart():
        while True:
            try:
                code = holder["proc"].wait()
            except Exception:
                return
            if code != RESTART_CODE:
                return
            say("сервер попросил перезапуск — поднимаю заново")
            new_proc = start_server()
            if not new_proc or not wait_ready(new_proc, p):
                say("перезапуск не удался — окно осталось без сервера")
                return
            holder["proc"] = new_proc
            say("сервер вернулся, окно не трогали")

    threading.Thread(target=_watch_restart, daemon=True).start()
    windowed = open_window(f"http://127.0.0.1:{p}")

    # Окна не случилось — значит, единственный интерфейс сейчас это вкладка
    # браузера, и гасить сервер нельзя ни в коем случае. Раньше гасили: exe
    # открывал вкладку, тут же возвращался из open_window, убивал сервер, и
    # человек видел «нет доступа к сайту» — приложение убивало само себя
    # через полсекунды после запуска. Ждём, пока сервер не остановят.
    if not windowed:
        say("работаю во вкладке браузера; закрыть — сняв ANAMORF.exe в "
            "диспетчере задач или остановив сервер")
        try:
            while True:
                code = holder["proc"].wait()
                if code != RESTART_CODE:
                    break
                say("сервер попросил перезапуск — поднимаю заново")
                np = start_server()
                if not np or not wait_ready(np, p):
                    break
                holder["proc"] = np
        except KeyboardInterrupt:
            pass
        return 0

    # Окно закрыли — гасим сервер. Прожил дольше HEALTHY_AFTER — считаем
    # версию удачной и убираем страховку, чтобы не копить старые копии.
    if time.time() - started > HEALTHY_AFTER and APP_PREV.is_dir():
        shutil.rmtree(APP_PREV, ignore_errors=True)
    # МЕТКА «ЗАКРЫЛИ РУКАМИ» — ЗДЕСЬ, А НЕ В СЕРВЕРЕ (30.08.2026, живой
    # случай: закрыл оба окна крестиком, ничего не трогал — через
    # несколько секунд появилось новое окно само по себе).
    #
    # Сервер сам умеет класть эту метку на выходе (anamorf/main.py,
    # atexit, _mark_quit_by_human) — но ниже, в stop(), мы гасим его
    # ПРИНУДИТЕЛЬНО (taskkill /F/T), намеренно и по веской причине (см.
    # докстринг stop() — иначе осиротевшие процессы и запертые DLL). А
    # принудительное убийство atexit не запускает НИКОГДА — метка
    # физически не успевала лечь. Сторож видел мёртвый порт без метки,
    # не отличал обычное закрытие от падения и поднимал программу заново
    # после КАЖДОГО закрытия крестиком — не только после сбоя.
    #
    # Лаунчер сам точно знает, что окно закрыли руками (мы буквально
    # только что вышли из webview.start()) — кладём метку сами, не
    # полагаясь на то, что успеет сделать уже приговорённый дочерний
    # процесс.
    try:
        qf = ROOT / "data" / "quit.flag"
        qf.parent.mkdir(parents=True, exist_ok=True)
        qf.write_text(str(time.time()), encoding="utf-8")
    except Exception:
        pass
    stop(holder.get("proc", proc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
