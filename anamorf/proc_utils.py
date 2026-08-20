"""Мелкие общие утилиты работы с процессами — используются и dreampc
(убить зависший воркер с прошлого запуска), и main.py (убить HandsPC при
закрытии окна Сайки), чтобы не дублировать один и тот же psutil-поиск."""
import logging
import os

log = logging.getLogger("saika.proc")


def kill_by_port(port: int, label: str = "процесс") -> bool:
    """Находит процесс, слушающий данный TCP-порт, и убивает его.
    Возвращает True, если что-то нашла и убила."""
    try:
        import psutil
    except Exception:
        return False
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            conns_fn = getattr(proc, "net_connections", None) or proc.connections
            conns = conns_fn(kind="inet")
        except Exception:
            continue
        for c in conns:
            if (c.laddr and c.laddr.port == port
                    and c.status == psutil.CONN_LISTEN):
                log.info("kill_by_port: убиваю %s (pid %s, порт %s)",
                         label, proc.info.get("pid"), port)
                try:
                    proc.kill()
                except Exception:
                    pass
                return True
    return False


def register_console_close_handler(callback):
    """Windows: закрытие консоли крестиком шлёт CTRL_CLOSE_EVENT, который
    НЕ ловится обычными signal.signal()/atexit (это отдельный механизм
    консоли, у Python для него нет штатной ручки) — обычный SIGINT из
    signal-модуля покрывает только Ctrl+C. Единственный надёжный способ
    поймать именно закрытие окна — низкоуровневый
    kernel32.SetConsoleCtrlHandler через ctypes (в стандартной библиотеке,
    pywin32 не нужен). Даёт ~5 секунд на callback, дальше Windows убьёт
    процесс принудительно — поэтому callback должен быть быстрым.

    На не-Windows ничего не делает (там штатный atexit и так работает)."""
    if os.name != "nt":
        return
    import ctypes
    import ctypes.wintypes

    HANDLER = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.DWORD)

    def _handler(ctrl_type):
        # 0=CTRL_C, 1=CTRL_BREAK, 2=CTRL_CLOSE, 5=CTRL_LOGOFF, 6=CTRL_SHUTDOWN
        if ctrl_type in (0, 1, 2, 5, 6):
            try:
                callback()
            except Exception:
                log.exception("register_console_close_handler: callback упал")
        return False  # не мешаем системе продолжить обычное завершение

    # ссылку на обёртку держим в глобальной переменной модуля — если её
    # соберёт GC, ctypes-коллбэк станет висячим указателем и уронит процесс
    global _handler_ref
    _handler_ref = HANDLER(_handler)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(_handler_ref, True)


_handler_ref = None
