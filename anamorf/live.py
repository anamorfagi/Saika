"""ЖИВАЯ ЗАМЕНА КОДА — БЕЗ ПЕРЕЗАПУСКА, КАКОГО БЫ УРОВНЯ НИ БЫЛА ПРАВКА.

Владелец, 23.08.2026, дословно: «ты меня просишь перезапустить — значит,
технология без перезапусков не работает, переделывай. Я не должен ни при
каких условиях трогать перезагрузку приложения, оно должно само
обновляться в реальном времени, неважно какого уровня правка».

Он прав, и прав дважды. Во-первых, просьба нажать кнопку — это признание,
что живого обновления нет. Во-вторых, у ПЕРЕЗАПУСКА здесь чудовищная
цена: модели слуха и голоса живут в этом же процессе, и любой переезд —
это минута прогрева, оборванный разговор и «звук завис».

ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ importlib.reload. Обычный reload создаёт НОВЫЕ
объекты функций и классов, а старые ссылки — в замыканиях, в реестрах
инструментов, в уже зарегистрированных маршрутах, в потоках — продолжают
звать СТАРЫЙ код. Снаружи это выглядит как «правка не подхватилась»,
причём выборочно: где-то новая, где-то старая. Поэтому мы не подменяем
объекты, а ПЕРЕПИСЫВАЕМ ИХ ВНУТРЕННОСТИ: у функции меняем __code__ и
умолчания, у класса — методы. Объект остаётся тем же самым, и все ссылки
на него — все до единой — начинают исполнять новый код. Так же поступает
autoreload в IPython, и по той же причине.

ГЛАВНЫЙ МОДУЛЬ (anamorf/main.py) перечитать целиком нельзя: его верхний
уровень поднимает сервер, вебсокеты, очереди и BOOT_ID — выполнить это
второй раз значит получить второе приложение внутри первого. Но 95%
правок в нём — это тело функции или новый маршрут. Поэтому для него
делаем хирургию: сравниваем ФАЙЛ с живым модулем по каждому определению
верхнего уровня и исполняем только изменившиеся — прямо в его же
глобальном пространстве. Декоратор маршрута при этом отрабатывает сам, а
старый маршрут с тем же адресом мы снимаем, иначе FastAPI продолжит
звать первый.

ЧЕГО МЫ НЕ УМЕЕМ И НЕ ПРИТВОРЯЕМСЯ. Изменение верхнего уровня модуля
(новая константа, новый импорт, изменённый список) в главном модуле не
применяется — там мы трогаем только функции и классы. Такое честно
называется вслух: человек должен знать, что именно не доехало, а не
гадать, почему правка не работает.
"""
import ast
import importlib
import io
import logging
import sys
import types

log = logging.getLogger("saika.live")

try:
    from anamorf.config import CFG
except Exception:      # живая правка не должна зависеть
    class _NoCfg:      # от настроек, если их ещё нет
        @staticmethod
        def get(k, d=None):
            return d
    CFG = _NoCfg()


# ─────────────────────── перепрошивка объектов ───────────────────────
def _graft_func(old, new) -> bool:
    """Переписать нутро функции, сохранив сам объект.

    Именно это делает замену честной: все, кто держит ссылку на старую
    функцию (реестры инструментов, маршруты, потоки, замыкания), после
    этого исполняют новый код — потому что объект тот же."""
    try:
        old.__code__ = new.__code__
        old.__defaults__ = new.__defaults__
        old.__kwdefaults__ = new.__kwdefaults__
        old.__doc__ = new.__doc__
        try:
            old.__dict__.update(new.__dict__)
        except Exception:
            pass
        return True
    except Exception as e:
        log.debug("не смогла перепрошить %s: %s", getattr(old, "__name__", "?"), e)
        return False


def _unwrap(f):
    """Снять функцию с метода/статикметода — прошивать надо саму функцию."""
    return getattr(f, "__func__", f)


def _graft_class(old, new) -> bool:
    """Обновить методы класса, сохранив сам класс.

    Класс сохраняем намеренно: у живых экземпляров (менеджеры слуха и
    голоса, движки) остаётся их состояние — загруженные модели, сокеты,
    счётчики, — и меняется только поведение."""
    ok = True
    for name, val in list(vars(new).items()):
        if name in ("__dict__", "__weakref__", "__doc__"):
            continue
        cur = old.__dict__.get(name)
        if isinstance(val, (types.FunctionType, staticmethod, classmethod)) \
                and isinstance(cur, (types.FunctionType, staticmethod,
                                     classmethod)):
            if not _graft_func(_unwrap(cur), _unwrap(val)):
                ok = False
            continue
        try:
            setattr(old, name, val)          # константы, поля, новые методы
        except Exception:
            ok = False
    return ok


def reload_module(name: str) -> tuple:
    """Перечитать обычный модуль и перепрошить его функции и классы.

    Возвращает (получилось, что сделали словами)."""
    mod = sys.modules.get(name)
    if mod is None:
        return True, "модуль ещё не загружен — подхватится при первом обращении"
    old_ns = dict(vars(mod))
    try:
        importlib.reload(mod)
    except Exception as e:
        return False, f"перечитать не вышло: {e}"
    grafted, added, kept = 0, 0, 0
    fixed = []
    for key, new_val in list(vars(mod).items()):
        old_val = old_ns.get(key)
        if old_val is None:
            added += 1
            continue
        if isinstance(new_val, types.FunctionType) \
                and isinstance(old_val, types.FunctionType):
            if _graft_func(old_val, new_val):
                # в самом модуле оставляем СТАРЫЙ объект: он уже
                # перепрошит, и на него смотрят все прежние ссылки
                setattr(mod, key, old_val)
                grafted += 1
        elif isinstance(new_val, type) and isinstance(old_val, type):
            if _graft_class(old_val, new_val):
                setattr(mod, key, old_val)
                grafted += 1
        elif _same_kind(old_val, new_val):
            # ЖИВОЙ ОДИНОЧКА ПЕРЕЖИВАЕТ ПРАВКУ (2026-08-31).
            #
            # importlib.reload переисполняет модуль целиком, а значит
            # строка вида `S = Manager()` внизу файла СОЗДАЁТ НОВЫЙ
            # объект. Классу мы аккуратно перепрошиваем методы, чтобы
            # живой экземпляр не терял состояние, — и тут же меняем сам
            # экземпляр на пустой. Модели, поднятые в видеопамяти,
            # счётчики, накопленные отпечатки, открытые сокеты — всё
            # молча обнулялось на каждой правке файла.
            #
            # Теперь одиночку оставляем СТАРУЮ: её класс уже перепрошит,
            # поведение новое, состояние на месте. А чтобы объект мог
            # починить сам себя (добавить поле, которого не было в его
            # версии, пересоздать захваченный замок), класс может
            # объявить __live_after__ — вызовем сразу после правки.
            setattr(mod, key, old_val)
            kept += 1
            hook = getattr(type(old_val), "__live_after__", None)
            if hook is not None:
                try:
                    hook(old_val)
                    fixed.append(key)
                except Exception as e:
                    log.warning("%s.%s не пережил правку: %s", name, key, e)
    tail = f"перепрошито {grafted}, новых имён {added}"
    if kept:
        tail += f", живых объектов сохранено {kept}"
    if fixed:
        tail += " (починили себя: " + ", ".join(fixed[:6]) + ")"
    return True, tail


def _same_kind(old_val, new_val) -> bool:
    """Один ли это по сути объект — чтобы отличить живого одиночку от
    обычной константы. Сравниваем классы по имени и модулю: после
    reload класс уже другой объект, хотя это тот же самый класс."""
    if isinstance(old_val, (str, bytes, int, float, bool, type(None),
                            tuple, frozenset)):
        return False
    to, tn = type(old_val), type(new_val)
    if to is tn:
        return True
    return (getattr(to, "__qualname__", "?") == getattr(tn, "__qualname__", "!")
            and getattr(to, "__module__", "?") == getattr(tn, "__module__", "!"))


# ─────────────────── верхний уровень тоже живой ───────────────────
# ХОЛОДНЫХ ПРАВОК БЫТЬ НЕ ДОЛЖНО (2026-08-31, владелец: «я не должен
# трогать этот перезапуск, ты должен уметь обновлять весь код — горячий,
# холодный, любой»). Раньше всё, что лежит ВНЕ функций и классов —
# константы, словари настроек, импорты, таблицы — обновить на ходу было
# нельзя, и живая правка честно писала «функции обновлены, эти строки
# нет». А это ровно та строчка, после которой человека просят нажать
# кнопку.
#
# Теперь верхний уровень тоже применяется, но не слепо. Модуль нельзя
# переисполнить целиком: там поднимается сервер, вешаются вебсокеты,
# стартуют потоки — второй раз это не запуск, а катастрофа. Поэтому
# берём ПООПЕРАТОРНО только то, что изменилось, и пропускаем операторы,
# которые что-то ЗАПУСКАЮТ. Пропущенное не замалчиваем — пишем в журнал
# поимённо, чтобы было видно, что именно осталось от старого запуска.
_TOP_UNSAFE = ("FastAPI(", "uvicorn", "add_middleware", ".mount(",
               "Thread(", ".start()", "atexit", "signal.signal",
               "basicConfig", "app.include_router", "asyncio.run")


def _top_stmts(src: str) -> dict:
    """Операторы верхнего уровня: ключ -> исходник.

    Ключ у присваивания — имена, которым оно присваивает: тогда правка
    значения видна как ИЗМЕНЕНИЕ той же строки, а не как новая."""
    out = {}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    lines = src.splitlines(keepends=True)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            continue
        piece = "".join(lines[node.lineno - 1:node.end_lineno])
        names = []
        if isinstance(node, ast.Assign):
            for t in node.targets:
                names += [n.id for n in ast.walk(t) if isinstance(n, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target,
                                                            ast.Name):
            names = [node.target.id]
        key = ("=" + ",".join(names)) if names else piece
        out[key] = piece
    return out


def apply_top(mod, old_src: str, new_src: str) -> tuple:
    """Применить изменившийся верхний уровень. -> (что сделали, что нет).

    ═══ ПО УМОЛЧАНИЮ ВЫКЛЮЧЕНО (2026-09-01) ═══

    Живой разбор: включённым это подняло ВТОРУЮ КОПИЮ СИСТЕМЫ поверх
    первой. В журнале запуск шёл дважды в одном процессе — два
    голосовых цикла, два планировщика, два PANNs, два llama-server, — а
    затем kill_by_port убивал первую копию по занятому порту, и
    start.bat видел падение с кодом 15. Владелец ловил это как «окно
    исчезло» и бесконечный круг перезапусков.

    Причина в самой затее. На верхнем уровне main.py лежит не только
    список констант, но и ЗАПУСК ВСЕГО. Отличить одно от другого
    списком опасных слов нельзя: запуск прячется за любым вызовом,
    который на вид безобиден. Чёрный список тут принципиально дырявый,
    а цена дырки — вторая копия системы.

    Поэтому верхний уровень снова НЕ применяется, а честно называется в
    журнале как недоехавший. Функции и классы обновляются на лету, как и
    раньше, — этого хватает почти всегда. Включить можно осознанно
    (dev.hot_top_level), но только для модулей, где на верхнем уровне
    заведомо одни константы.
    """
    if not CFG.get("dev.hot_top_level", False):
        changed = [k for k, v in _top_stmts(new_src).items()
                   if (_top_stmts(old_src) if old_src else {}).get(k) != v]
        if changed:
            return [], ["верхний уровень (%d строк) — функции обновлены, "
                        "эти нет: включается dev.hot_top_level, но там же "
                        "лежит запуск системы" % len(changed)]
        return [], []
    new_t = _top_stmts(new_src)
    old_t = _top_stmts(old_src) if old_src else {}
    g = vars(mod)
    done, skipped = [], []
    for key, piece in new_t.items():
        if old_t.get(key) == piece:
            continue
        short = piece.strip().splitlines()[0][:60]
        if any(u in piece for u in _TOP_UNSAFE):
            skipped.append(short + "  (запускает — трогать на ходу нельзя)")
            continue
        before = {n: g.get(n) for n in _names_of(piece) if n in g}
        try:
            exec(compile(piece, "<live-top:%s>" % getattr(mod, "__name__", "?"),
                         "exec"), g, g)
        except Exception as e:
            skipped.append("%s  (%s)" % (short, e))
            continue
        # живой объект пересоздавать нельзя — вернём прежний (см. _same_kind)
        for n, old_val in before.items():
            new_val = g.get(n)
            if old_val is not new_val and _same_kind(old_val, new_val):
                g[n] = old_val
                hook = getattr(type(old_val), "__live_after__", None)
                if hook is not None:
                    try:
                        hook(old_val)
                    except Exception as e:
                        log.warning("%s не пережил правку: %s", n, e)
        done.append(short)
    return done, skipped


def _names_of(piece: str) -> list:
    try:
        return [n.id for st in ast.parse(piece).body
                for n in ast.walk(st) if isinstance(n, ast.Name)]
    except Exception:
        return []


# ─────────────────────── хирургия главного модуля ───────────────────────
def _defs(src: str) -> dict:
    """Определения верхнего уровня: имя -> исходник (с декораторами)."""
    out = {}
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        raise
    lines = src.splitlines(keepends=True)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        start = min([d.lineno for d in node.decorator_list] + [node.lineno]) - 1
        end = node.end_lineno
        out[node.name] = "".join(lines[start:end])
    return out


def _routes_of(src_piece: str) -> list:
    """Какие маршруты объявляет этот кусок: [(метод, путь)]."""
    out = []
    try:
        for node in ast.parse(src_piece).body:
            for d in getattr(node, "decorator_list", []):
                f = d.func if isinstance(d, ast.Call) else d
                if not isinstance(f, ast.Attribute):
                    continue
                obj = getattr(f.value, "id", "")
                if obj != "app":
                    continue
                path = ""
                if isinstance(d, ast.Call) and d.args and \
                        isinstance(d.args[0], ast.Constant):
                    path = str(d.args[0].value)
                out.append((f.attr.upper(), path))
    except Exception:
        pass
    return out


def _drop_route(app, method: str, path: str):
    """Снять живой маршрут: иначе FastAPI оставит старый обработчик.

    Маршруты хранятся списком и матчатся по порядку — новый, добавленный
    в конец, до вызова просто не доживёт."""
    try:
        keep = []
        for r in app.router.routes:
            if getattr(r, "path", None) != path:
                keep.append(r)
                continue
            meths = getattr(r, "methods", None)
            # У ВЕБСОКЕТА НЕТ methods (2026-08-31): условие «метод входит в
            # methods» на нём всегда ложно, старый маршрут оставался в
            # списке первым и продолжал звать снятый обработчик. Совпал
            # путь и методов нет — это тот самый вебсокет, снимаем.
            same = (method in meths) if meths else (method == "WEBSOCKET")
            if not same:
                keep.append(r)
        app.router.routes = keep
    except Exception as e:
        log.debug("старый маршрут %s %s не снялся: %s", method, path, e)


def remember(name: str) -> bool:
    """Запомнить исходник модуля, каким он СЕЙЧАС работает.

    Зовётся на старте: без этого снимка живая правка не сможет отличить
    изменившееся определение от нетронутого (файл к тому моменту уже
    переписан)."""
    mod = sys.modules.get(name)
    if mod is None:
        return False
    try:
        mod.__live_src__ = io.open(getattr(mod, "__file__", ""),
                                   encoding="utf-8").read()
        return True
    except Exception as e:
        log.debug("снимок %s не снялся: %s", name, e)
        return False


def patch_module(name: str, path) -> tuple:
    """Применить правки к живому модулю ПОФУНКЦИОННО, не выполняя его
    верхний уровень. Для главного модуля это единственный честный путь.

    Возвращает (что применили, что не смогли) — списками имён."""
    mod = sys.modules.get(name)
    if mod is None:
        return [], ["модуль не загружен"]
    done, failed = _patch_single(mod, path)
    # ДВОЙНИК __main__ (поймано живым вечером 23.08: правки main
    # «применялись» по логу, а /api/ready как отдавал старый код, так и
    # отдавал). Главный модуль живёт в памяти ДВАЖДЫ: __main__ — тот, чей
    # app реально слушает порт, и anamorf.main — теневая копия от импорта.
    # Патчить только копию — красить забор у соседа. Если __main__ собран
    # из того же файла — прошиваем и его, НАСТОЯЩЕГО.
    try:
        import os as _os
        f1 = _os.path.abspath(getattr(mod, "__file__", "") or "")
        m2 = sys.modules.get("__main__")
        f2 = _os.path.abspath(getattr(m2, "__file__", "") or "") \
            if m2 is not None else ""
        if m2 is not None and m2 is not mod and f1 and f1 == f2:
            d2, x2 = _patch_single(m2, path)
            done += [f"{n}@__main__" for n in d2]
            failed += [f"{n}@__main__" for n in x2
                       if not n.startswith("верхний уровень")]
    except Exception as e:
        failed.append(f"двойник __main__: {e}")
    return done, failed


def _patch_single(mod, path) -> tuple:
    try:
        new_src = io.open(path, encoding="utf-8").read()
    except Exception as e:
        return [], [f"файл не прочитался: {e}"]
    try:
        new_defs = _defs(new_src)
    except SyntaxError as e:
        # НЕДОПИСАННЫЙ ФАЙЛ — НЕ ПОВОД ЛОМАТЬСЯ. Правка может быть поймана
        # на середине сохранения; вернёмся к ней на следующем круге.
        return [], [f"файл пока не разбирается ({e.lineno}: {e.msg})"]
    # ⚠️ СНИМОК ДЕЛАЕТСЯ ЗАРАНЕЕ, А НЕ В МОМЕНТ ПРАВКИ (поймано стендом
    # 23.08: применилось ноль изменений). Сюда мы приходим ПОСЛЕ того, как
    # файл на диске уже переписан, — значит, прочитать по __file__ «как
    # было» невозможно, там уже новое, и разница всегда пустая. Правду о
    # работающем коде хранит только снимок, снятый на старте (см.
    # live.remember в main.py). Снимка нет — считаем изменившимся ВСЁ:
    # переисполнить определения безопасно (объекты те же, маршруты
    # снимаются и ставятся заново), зато ни одна правка не потеряется.
    old_src = getattr(mod, "__live_src__", None)
    try:
        old_defs = _defs(old_src) if old_src else {}
    except SyntaxError:
        old_defs = {}

    done, failed = [], []
    g = vars(mod)
    for fname, piece in new_defs.items():
        if old_defs.get(fname) == piece:
            continue                          # не менялось
        # маршруты: снимаем старый адрес, чтобы новый не оказался вторым
        for method, rpath in _routes_of(piece):
            app = g.get("app")
            if app is not None and rpath:
                _drop_route(app, method, rpath)
        tmp = {}
        try:
            exec(compile(piece, f"<live:{fname}>", "exec"), g, tmp)
        except Exception as e:
            # MIDDLEWARE НЕ ПЕРЕВЕШИВАЮТ НА ХОДУ: Starlette запрещает
            # add_middleware после старта. Но тело функции обновить можно
            # и без декоратора — старая обёртка уже стоит в конвейере и
            # зовёт функцию по ссылке, а ссылку мы прошиваем graft'ом.
            if "middleware" in str(e).lower():
                bare = "\n".join(l for l in piece.splitlines()
                                 if not l.lstrip().startswith("@"))
                try:
                    exec(compile(bare, f"<live:{fname}>", "exec"), g, tmp)
                except Exception as e2:
                    failed.append(f"{fname}: {e2}")
                    continue
            else:
                failed.append(f"{fname}: {e}")
                continue
        new_obj = tmp.get(fname, g.get(fname))
        old_obj = g.get(fname)
        if isinstance(new_obj, types.FunctionType) \
                and isinstance(old_obj, types.FunctionType) \
                and old_obj is not new_obj:
            _graft_func(old_obj, new_obj)     # старые ссылки — на новый код
            g[fname] = old_obj
        elif isinstance(new_obj, type) and isinstance(old_obj, type) \
                and old_obj is not new_obj:
            _graft_class(old_obj, new_obj)
            g[fname] = old_obj
        else:
            g[fname] = new_obj                # новое имя — просто добавилось
        done.append(fname)

    # верхний уровень: если изменилось что-то ВНЕ функций, честно скажем
    t_done, t_skip = apply_top(mod, old_src or "", new_src)
    done += ["верх: " + d for d in t_done]
    failed += ["верх: " + s2 for s2 in t_skip]
    mod.__live_src__ = new_src
    return done, failed


def _top_level(src: str) -> str:
    """Строки верхнего уровня без определений — чтобы заметить их правку."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ""
    lines = src.splitlines(keepends=True)
    skip = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            start = min([d.lineno for d in node.decorator_list]
                        + [node.lineno]) - 1
            for i in range(start, node.end_lineno):
                skip.add(i)
    return "".join(l for i, l in enumerate(lines)
                   if i not in skip and l.strip()
                   and not l.lstrip().startswith("#"))
