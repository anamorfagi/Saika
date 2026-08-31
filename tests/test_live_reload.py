"""ЖИВАЯ ЗАМЕНА КОДА: правка любого уровня — без единого перезапуска.

Владелец 23.08: «ты меня просишь перезапустить — значит, технология без
перезапусков не работает, переделывай. Я не должен ни при каких условиях
трогать перезагрузку приложения».

Проверяем то, из-за чего обычный importlib.reload не годится: старые
ссылки. Реестр инструментов, зарегистрированный маршрут, поток, живой
менеджер с моделью в видеопамяти — все они держат ССЫЛКУ на функцию или
класс, и после reload продолжают звать старый код. Мы вместо подмены
объектов переписываем их нутро, поэтому проверка простая: взять ссылку ДО
правки и убедиться, что после правки она исполняет НОВОЕ.
"""
import importlib
import io
import os
import sys
import tempfile

V1 = '''
COUNT = 1


def hello(name):
    return "старое " + name


class Manager:
    def __init__(self):
        self.state = "живое состояние"

    def act(self):
        return "старый ответ: " + self.state
'''

V2 = '''
COUNT = 2


def hello(name):
    return "НОВОЕ " + name


def brand_new():
    return "новая функция"


class Manager:
    def __init__(self):
        self.state = "живое состояние"

    def act(self):
        return "НОВЫЙ ответ: " + self.state
'''


def run():
    rows = []
    from anamorf import live

    tmp = tempfile.mkdtemp(prefix="saika_live_")
    mod_path = os.path.join(tmp, "saika_toy_mod.py")
    io.open(mod_path, "w", encoding="utf-8").write(V1)
    sys.path.insert(0, tmp)
    try:
        toy = importlib.import_module("saika_toy_mod")
        held = toy.hello                 # ссылка, как у реестра инструментов
        mgr = toy.Manager()              # живой объект с состоянием
        io.open(mod_path, "w", encoding="utf-8").write(V2)

        ok, note = live.reload_module("saika_toy_mod")
        rows.append(("модуль перечитан", ok, note))
        rows.append(("СТАРАЯ ссылка исполняет новый код",
                     held("раз") == "НОВОЕ раз", held("раз")))
        rows.append(("живой объект остался жив, а метод стал новым",
                     mgr.state == "живое состояние"
                     and mgr.act().startswith("НОВЫЙ"), mgr.act()))
        rows.append(("новая функция появилась",
                     getattr(toy, "brand_new", None) is not None
                     and toy.brand_new() == "новая функция", ""))
        rows.append(("константа обновилась", toy.COUNT == 2, str(toy.COUNT)))

        # ── хирургия по определениям (путь главного модуля) ──
        io.open(mod_path, "w", encoding="utf-8").write(V1)
        importlib.reload(toy)
        live.remember("saika_toy_mod")    # снимок «как работает сейчас»
        held2 = toy.hello
        io.open(mod_path, "w", encoding="utf-8").write(V2)
        done, failed = live.patch_module("saika_toy_mod", mod_path)
        rows.append(("пофункциональная правка нашла изменившееся",
                     "hello" in done and "Manager" in done, str(done)))
        rows.append(("и её тоже видно по старой ссылке",
                     held2("два") == "НОВОЕ два", held2("два")))
        rows.append(("правка верхнего уровня названа вслух, а не скрыта",
                     any("верхний уровень" in f for f in failed), str(failed)))

        # ⚠️ ЛОВУШКА, ПОЙМАННАЯ СТЕНДОМ: без снимка «как было» разница
        # всегда пустая — файл на диске к моменту правки уже новый.
        io.open(mod_path, "w", encoding="utf-8").write(V2)
        m = sys.modules["saika_toy_mod"]
        if hasattr(m, "__live_src__"):
            del m.__live_src__
        done2, _ = live.patch_module("saika_toy_mod", mod_path)
        rows.append(("без снимка применяем ВСЁ, а не молча ничего",
                     bool(done2), str(done2)))
    finally:
        try:
            sys.path.remove(tmp)
            sys.modules.pop("saika_toy_mod", None)
        except Exception:
            pass

    # и сам сторож кода больше не просит человека нажимать кнопку
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main = io.open(os.path.join(root, "anamorf", "main.py"),
                   encoding="utf-8").read()
    # ЖИВОЙ ПРОВАЛ 23.08: функция сторожа была, а СТАРТЕРА не было —
    # правки полдня молча не применялись. Функция без запуска — мёртвый код.
    rows.append(("сторож кода ЗАПУСКАЕТСЯ, а не только определён",
                 "threading.Thread(target=_code_watch" in main, ""))
    rows.append(("сторож кода зовёт живую замену, а не переезд",
                 "_live.patch_module" in main and "_live.reload_module" in main,
                 ""))
    rows.append(("просьбы «нажми перезапустить» в сторожe больше нет",
                 "Нажми «⟳ Перезапустить»" not in main
                 or "_hot_restart()" not in main.split("def _code_watch")[1],
                 ""))
    return rows
