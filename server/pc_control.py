"""Руки Сайки в самой Windows: программы, окна, звук, вкладки браузера.

ЗАЧЕМ. Владелец хочет разговаривать с ней с дивана: «запусти Blender»,
«сверни всё лишнее», «сделай потише», «закрой эту вкладку». До сих пор из
системного у неё были только просмотр процессов и запуск строго из белого
списка путей, который надо было заполнять руками — на практике он так и
остался пустым.

ЧТО ЗДЕСЬ ЕСТЬ
  каталог программ  — сам собирается из меню «Пуск» и рабочего стола
  окна              — список, свернуть, закрыть, показать поверх
  звук              — громче/тише/выключить
  вкладки           — открыть, закрыть, перейти к N-й (клавишами в активное окно)
  папки             — открыть в проводнике

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. Ничего, что стирает данные. Файлы, папки и код —
отдельный модуль file_hands, и он заперт в рабочей директории (files.roots).
Здесь только запуск и окна. «Закрыть» — это WM_CLOSE, вежливая просьба:
программа успеет спросить про несохранённое. Принудительное снятие процесса
живёт в system_control.kill и требует подтверждения — тут его нет намеренно.

КАК СОБИРАЕТСЯ КАТАЛОГ. Ярлыки .lnk из меню «Пуск» (общесистемного и
пользовательского) и с рабочего стола. Запускаем САМ ЯРЛЫК через
os.startfile — так не нужно разбирать бинарный формат .lnk ради пути к exe,
и заодно сохраняются рабочая папка и аргументы, прописанные в ярлыке.
Игры Steam и Epic попадают сюда же: их установщики кладут ярлыки в «Пуск».
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

from server.config import CFG, ROOT

log = logging.getLogger("saika.pc")

_IS_WIN = os.name == "nt"
INDEX_PATH = ROOT / "data" / "app_index.json"
_index: dict = {"apps": [], "built": 0.0}

# Что в каталог не берём никогда: деинсталляторы, «прочитай меня», ссылки на
# сайты производителя. Владелец с дивана просит «запусти игру», а не
# «удали игру» — и промахнуться голосом тут очень легко.
_SKIP_RE = re.compile(
    r"uninstall|удал|деинстал|remove|repair|readme|help|справк|"
    r"документац|manual|license|лиценз|website|веб-?сайт|support|"
    r"поддержк|report a (bug|problem)|crash",
    re.I)


# ─────────────────────────── каталог программ ───────────────────────────
def _scan_dirs() -> list[Path]:
    out = []
    for env, sub in (("ProgramData", "Microsoft/Windows/Start Menu/Programs"),
                     ("APPDATA", "Microsoft/Windows/Start Menu/Programs"),
                     ("USERPROFILE", "Desktop"),
                     ("PUBLIC", "Desktop")):
        base = os.environ.get(env)
        if base:
            p = Path(base) / sub
            if p.exists():
                out.append(p)
    for extra in (CFG.get("pc.extra_scan_dirs", []) or []):
        p = Path(str(extra))
        if p.exists():
            out.append(p)
    return out


def build_index(force=False) -> dict:
    """Собрать каталог программ. Кэшируем на диск: обход «Пуска» это
    несколько тысяч файлов, дёргать его на каждую фразу незачем."""
    ttl = float(CFG.get("pc.index_ttl_h", 24)) * 3600
    if not force and _index["apps"] and time.time() - _index["built"] < ttl:
        return _index
    if not force and not _index["apps"] and INDEX_PATH.exists():
        try:
            data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            if time.time() - float(data.get("built", 0)) < ttl:
                _index.update(apps=data.get("apps", []),
                              built=float(data.get("built", 0)))
                return _index
        except Exception as e:
            log.debug("каталог программ не прочитался: %s", e)

    apps, seen = [], set()
    for d in _scan_dirs():
        try:
            for f in d.rglob("*"):
                if f.suffix.lower() not in (".lnk", ".url"):
                    continue
                name = f.stem.strip()
                if not name or _SKIP_RE.search(name) or _SKIP_RE.search(str(f)):
                    continue
                low = name.lower()
                if low in seen:
                    continue
                seen.add(low)
                apps.append({"name": name, "path": str(f),
                             "kind": f.suffix.lower().lstrip(".")})
        except Exception as e:
            log.debug("не смогла обойти %s: %s", d, e)
    apps.sort(key=lambda a: a["name"].lower())
    _index.update(apps=apps, built=time.time())
    try:
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(json.dumps(_index, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    except Exception as e:
        log.debug("каталог программ не сохранился: %s", e)
    log.info("Каталог программ собран: %d ярлыков", len(apps))
    return _index


def blocked() -> set:
    return {str(x).lower() for x in (CFG.get("pc.blocked_apps", []) or [])}


def set_blocked(name: str, on: bool) -> str:
    """Вычеркнуть программу из каталога (или вернуть). Список правится в
    интерфейсе: каталог собирается сам, но последнее слово за владельцем."""
    cur = [str(x) for x in (CFG.get("pc.blocked_apps", []) or [])]
    low = [x.lower() for x in cur]
    if on and name.lower() not in low:
        cur.append(name)
    if not on:
        cur = [x for x in cur if x.lower() != name.lower()]
    CFG.set("pc.blocked_apps", cur)
    return f"«{name}» " + ("скрыта от Сайки" if on else "снова доступна")


def apps(query: str = "", limit: int = 40) -> list:
    """Программы каталога, при желании отфильтрованные."""
    idx = build_index()
    bad = blocked()
    q = (query or "").strip().lower()
    out = []
    for a in idx["apps"]:
        if a["name"].lower() in bad:
            continue
        if q and q not in a["name"].lower():
            continue
        out.append(a)
    return out[:limit] if limit else out


def _score(name: str, q: str) -> int:
    """Насколько ярлык похож на то, что попросили. Голосом просят коротко
    («блендер», «стим»), а в «Пуске» лежат «Blender 4.2» и «Steam Client»."""
    n = name.lower()
    if n == q:
        return 100
    if n.startswith(q):
        return 80 - min(20, len(n) - len(q))
    if q in n:
        return 55 - min(20, len(n) - len(q))
    words = set(re.findall(r"\w+", n))
    qw = set(re.findall(r"\w+", q))
    if qw and qw <= words:
        return 45
    if qw & words:
        return 25
    return 0


def find_app(query: str) -> list:
    q = (query or "").strip().lower()
    if not q:
        return []
    scored = [(a, _score(a["name"], q)) for a in apps(limit=0)]
    scored = [(a, s) for a, s in scored if s > 0]
    scored.sort(key=lambda p: -p[1])
    return [a for a, _s in scored[:8]]


def launch(query: str) -> str:
    """Запустить программу по человеческому названию."""
    hits = find_app(query)
    if not hits:
        # каталог мог собраться до установки — пересобираем и пробуем ещё раз
        build_index(force=True)
        hits = find_app(query)
    if not hits:
        return (f"Не нашла «{query}» среди установленных программ. "
                "Открой «Управление компом» в настройках и посмотри, что "
                "вообще есть в каталоге — или назови иначе.")
    # Несколько похожих — не гадаем молча: запускаем лучшее, но честно
    # называем, что именно, чтобы промах был слышен сразу.
    best = hits[0]
    others = [h["name"] for h in hits[1:4]]
    try:
        if _IS_WIN:
            os.startfile(best["path"])          # noqa: S606 — ярлык из «Пуска»
        else:
            subprocess.Popen(["xdg-open", best["path"]])
    except Exception as e:
        return f"Не смогла запустить «{best['name']}»: {e}"
    # проверка результата: ждём до 3с, появилось ли ОКНО этой программы —
    # «запустила» без окна на экране человек читает как «ничего не произошло»
    seen = ""
    try:
        want = (best["name"] or "").lower().split()[0]
        for _ in range(6):
            time.sleep(0.5)
            for w in windows(include_minimized=False):
                hay = (w["title"] + " " + (w["proc"] or "")).lower()
                if want and want in hay:
                    seen = w["title"][:50]
                    break
            if seen:
                break
    except Exception:
        pass
    msg = (f"Запустила {best['name']} — окно «{seen}» уже на экране." if seen
           else f"Запустила {best['name']}, но окна пока не вижу — она может "
                "грузиться или живёт в трее. Скажи человеку как есть.")
    if others:
        msg += " Похожие, если промахнулась: " + ", ".join(others) + "."
    return msg


# ──────────────────────────────── окна ────────────────────────────────
def _win32():
    import ctypes
    from ctypes import wintypes
    return ctypes, wintypes, ctypes.windll.user32


def _monitors() -> list:
    """Прямоугольники мониторов по порядку — чтобы сказать, на каком экране
    висит окно. Владелец просил именно это: «понимала, что на первом
    экране, что на втором»."""
    if not _IS_WIN:
        return []
    ctypes, wintypes, user32 = _win32()
    rects = []

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.POINTER(wintypes.RECT), ctypes.c_double)

    def cb(hmon, hdc, lprc, data):
        r = lprc.contents
        rects.append((r.left, r.top, r.right, r.bottom))
        return 1

    try:
        user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(cb), 0)
    except Exception as e:
        log.debug("мониторы не перечислились: %s", e)
    # слева направо, сверху вниз — так же, как их видит человек
    rects.sort(key=lambda r: (r[1], r[0]))
    return rects


def _monitor_of(rect, mons) -> int:
    cx = (rect[0] + rect[2]) // 2
    cy = (rect[1] + rect[3]) // 2
    for i, m in enumerate(mons):
        if m[0] <= cx < m[2] and m[1] <= cy < m[3]:
            return i + 1
    return 0


def windows(include_minimized=True) -> list:
    """Видимые окна с заголовком: чей процесс, на каком мониторе, свёрнуто ли."""
    if not _IS_WIN:
        return []
    ctypes, wintypes, user32 = _win32()
    mons = _monitors()
    out = []

    ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p,
                                  ctypes.c_void_p)

    def cb(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value.strip()
            if not title:
                return True
            # служебные окна оболочки — не то, что человек называет «окном»
            if title in ("Program Manager", "Windows Input Experience",
                         "Настройки", "搜索"):
                return True
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            rect = (r.left, r.top, r.right, r.bottom)
            mini = bool(user32.IsIconic(hwnd))
            if mini and not include_minimized:
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc = ""
            try:
                import psutil
                proc = psutil.Process(pid.value).name()
            except Exception:
                pass
            out.append({"hwnd": int(hwnd), "title": title, "proc": proc,
                        "pid": int(pid.value), "minimized": mini,
                        # окна от администратора нам не подчиняются — знать
                        # об этом надо ЗАРАНЕЕ, иначе модель будет долбиться
                        # в них раз за разом (живой случай с диспетчером
                        # задач: три захода подряд и три «готово»)
                        "admin": _elevated(int(pid.value)),
                        "monitor": 0 if mini else _monitor_of(rect, mons),
                        "w": rect[2] - rect[0], "h": rect[3] - rect[1]})
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(ENUMPROC(cb), 0)
    except Exception as e:
        log.warning("не смогла перечислить окна: %s", e)
    # крупные и не свёрнутые — выше: обычно про них и спрашивают
    out.sort(key=lambda w: (w["minimized"], -(w["w"] * w["h"])))
    return out


def screen_map() -> str:
    """Текстовая карта рабочего стола для промпта. Дешевле картинки на
    порядок и не жрёт зрение: модель понимает расклад по словам, а кадр
    берёт только если действительно надо посмотреть глазами."""
    ws = windows()
    if not ws:
        return "Окон не видно."
    mons = _monitors()
    lines = [f"Мониторов: {len(mons) or 1}."]
    by = {}
    for w in ws:
        by.setdefault(w["monitor"], []).append(w)
    for m in sorted(k for k in by if k):
        items = by[m][:8]
        lines.append(f"Экран {m}: " + "; ".join(
            f"{w['title'][:60]}" + (f" ({w['proc']})" if w["proc"] else "")
            + (" [от администратора — сворачивать и закрывать НЕЛЬЗЯ]"
               if w.get("admin") else "")
            for w in items))
    mini = by.get(0, [])
    if mini:
        lines.append("Свёрнуто: " + "; ".join(w["title"][:40]
                                              for w in mini[:8]))
    if any(w.get("admin") for w in ws):
        lines.append("Окна с пометкой «от администратора» я тронуть не могу: "
                     "Windows не даёт обычной программе командовать ими. "
                     "Не пытайся — скажи об этом человеку сразу.")
    return "\n".join(lines)


# ИНСТИНКТ САМОСОХРАНЕНИЯ (2026-07-28, реальный инцидент). Гость попросил
# «закрой всё» — Сайка честно закрыла и СВОЁ окно: консоль сервера и вкладку
# собственного интерфейса. WM_CLOSE консоли = смерть процесса, она
# «минуснула сама себя» посреди разговора. Живое существо не отрезает себе
# голову, выполняя просьбу прибраться: свои жизненно важные окна — не цель
# для window_close/kill. Явное «выключись» при этом работает как и раньше —
# для этого есть shutdown_self с собственным предохранителем и прощанием.
import os as _os


def _is_self_window(w: dict) -> bool:
    """Окно, без которого Сайка умрёт или ослепнет: её собственная консоль
    (тот же PID, что у сервера, или родительский cmd из start.bat) и
    вкладка/окно её интерфейса (порт 8765 в заголовке)."""
    try:
        if int(w.get("pid", 0)) == _os.getpid():
            return True
    except Exception:
        pass
    title = (w.get("title") or "").lower()
    # окно её веб-интерфейса: заголовок вкладки содержит адрес или имя
    if "127.0.0.1:8765" in title or "сайка —" in title \
            or title.startswith("сайка"):
        return True
    # консоль, из которой запущен start.bat (заголовок задаёт start.bat)
    if "start.bat" in title or "saika" in title:
        return True
    return False


# РУССКИЕ ИМЕНА ПРОГРАММ (2026-07-28, реальный случай). «Разверни
# проводник» не находило окно: заголовок окна проводника — имя ПАПКИ
# («Saika», «Загрузки»), а процесс — explorer.exe; слова «проводник» нет
# нигде. Голосом говорят по-русски — переводим на имена процессов.
_APP_ALIASES = {
    "проводник": "explorer", "папка": "explorer",
    "хром": "chrome", "гугл хром": "chrome", "браузер": "chrome",
    "блокнот": "notepad", "калькулятор": "calc",
    "телеграм": "telegram", "телега": "telegram",
    "диспетчер": "taskmgr", "диспетчер задач": "taskmgr",
    "корзина": "explorer",
}


def _match(query: str):
    """Найти окно по куску заголовка или имени процесса (+русские алиасы)."""
    q = (query or "").strip().lower()
    if not q:
        return None
    ws = windows()
    for w in ws:                       # точное вхождение в заголовок
        if q in w["title"].lower():
            return w
    for w in ws:                       # иначе по имени процесса
        if q in (w["proc"] or "").lower():
            return w
    alias = _APP_ALIASES.get(q) or next(
        (v for k, v in _APP_ALIASES.items() if k in q), "")
    if alias:
        for w in ws:
            if alias in (w["proc"] or "").lower() \
                    or alias in w["title"].lower():
                return w
    return None


_elev_cache: dict = {}


def _elevated(pid: int) -> bool:
    """Запущен ли процесс с правами администратора.

    Windows защищает такие окна от чужих команд (UIPI): обычная программа
    физически не может свернуть или закрыть окно процесса, поднятого выше
    себя по правам. ShowWindow при этом НЕ ругается — просто молча ничего
    не делает. Проверяем косвенно: у поднятого процесса нам не дадут даже
    прочитать путь к исполняемому файлу.
    """
    # список окон перечитывается часто, а права процесса не меняются —
    # держим ответ до его завершения
    if pid in _elev_cache:
        return _elev_cache[pid]
    try:
        import psutil
        psutil.Process(pid).exe()
        out = False
    except Exception as e:
        out = type(e).__name__ == "AccessDenied"
    if len(_elev_cache) > 400:
        _elev_cache.clear()
    _elev_cache[pid] = out
    return out


def _verify(hwnd, want: str) -> bool:
    """Действительно ли окно оказалось в нужном состоянии."""
    if not _IS_WIN:
        return True
    ctypes, _wt, user32 = _win32()
    time.sleep(0.12)                # окну нужен кадр, чтобы перерисоваться
    try:
        if want == "min":
            return bool(user32.IsIconic(hwnd))
        if want == "max":
            return bool(user32.IsZoomed(hwnd))
        if want == "gone":
            return not bool(user32.IsWindow(hwnd))
        if want == "front":
            return int(user32.GetForegroundWindow()) == int(hwnd)
        if want == "normal":
            return not (user32.IsIconic(hwnd) or user32.IsZoomed(hwnd))
    except Exception:
        pass
    return True


def _blocked_note(w: dict, verb: str) -> str:
    """Честное объяснение, почему не вышло. Раньше здесь врали «готово» —
    и владелец справедливо ловил на этом (живой случай с диспетчером
    задач 2026-07-26)."""
    if _elevated(w.get("pid", 0)):
        return (f"Не смогла {verb} «{w['title'][:50]}»: это окно запущено от "
                "администратора, а я — нет. Windows не даёт обычной "
                "программе командовать поднятыми окнами. Сделай это сам или "
                "запусти меня от администратора.")
    return (f"Не смогла {verb} «{w['title'][:50]}» — окно не послушалось. "
            "Бывает у полноэкранных игр и окон, которые держат себя "
            "поверх остальных.")


def window_minimize(query: str) -> str:
    w = _match(query)
    if not w:
        return f"Не нашла окно «{query}»."
    _, _, user32 = _win32()
    user32.ShowWindow(w["hwnd"], 6)                # SW_MINIMIZE
    if not _verify(w["hwnd"], "min"):
        return _blocked_note(w, "свернуть")
    return f"Свернула «{w['title'][:60]}»."


def window_focus(query: str) -> str:
    w = _match(query)
    if not w:
        return f"Не нашла окно «{query}»."
    _, _, user32 = _win32()
    user32.ShowWindow(w["hwnd"], 9)                # SW_RESTORE
    user32.SetForegroundWindow(w["hwnd"])
    if not _verify(w["hwnd"], "front"):
        # вывод окна вперёд Windows ограничивает и без всяких прав: чужому
        # процессу нельзя перехватывать фокус у активного
        return (f"Показала «{w['title'][:50]}», но вперёд она не вышла — "
                "Windows не даёт чужой программе перехватывать фокус. "
                "Кликни по ней на панели задач.")
    return f"Показала «{w['title'][:60]}»."


def window_maximize(query: str = "", full: bool = False) -> str:
    """Развернуть окно. Просьба владельца: «развернуть на полный экран не
    могла». Без query берём то окно, что сейчас впереди — «разверни это»
    произносится куда чаще, чем «разверни блокнот»."""
    w = _match(query) if query else _foreground()
    if not w:
        return f"Не нашла окно «{query}»." if query else "Не вижу активного окна."
    _, _, user32 = _win32()
    user32.ShowWindow(w["hwnd"], 3)                # SW_MAXIMIZE
    user32.SetForegroundWindow(w["hwnd"])
    if not _verify(w["hwnd"], "max"):
        return _blocked_note(w, "развернуть")
    if full:
        # Настоящий полноэкранный режим — это внутреннее дело программы
        # (у браузеров и плееров это F11), снаружи его не включить.
        # Разворачиваем и жмём F11 в активное окно.
        try:
            import keyboard
            keyboard.send("f11")
        except Exception:
            return (f"Развернула «{w['title'][:60]}». Полный экран без "
                    "модуля keyboard не переключу — нажми F11 сам.")
    return ("Развернула «" + w["title"][:60] + "»"
            + (" на полный экран." if full else "."))


def window_restore(query: str = "") -> str:
    """Вернуть окно из развёрнутого в обычный размер."""
    w = _match(query) if query else _foreground()
    if not w:
        return "Не нашла такое окно."
    _, _, user32 = _win32()
    user32.ShowWindow(w["hwnd"], 9)                # SW_RESTORE
    if not _verify(w["hwnd"], "normal"):
        return _blocked_note(w, "вернуть в обычный размер")
    return f"Вернула «{w['title'][:60]}» в обычный размер."


def _foreground():
    """Окно, которое сейчас впереди."""
    if not _IS_WIN:
        return None
    _, _, user32 = _win32()
    try:
        h = int(user32.GetForegroundWindow())
    except Exception:
        return None
    for w in windows(include_minimized=False):
        if w["hwnd"] == h:
            return w
    return None


def window_close(query: str) -> str:
    """WM_CLOSE — вежливая просьба закрыться. Программа успеет спросить про
    несохранённое; принудительно ничего не снимаем (это system_control.kill,
    и он требует подтверждения)."""
    w = _match(query)
    if not w:
        return f"Не нашла окно «{query}»."
    if _is_self_window(w):
        return ("отказ: это моё собственное окно — закрыв его, я умру "
                "посреди разговора. Если нужно меня выключить, попроси "
                "прямо: «выключись» — я попрощаюсь и выйду сама.")
    _, _, user32 = _win32()
    user32.PostMessageW(w["hwnd"], 0x0010, 0, 0)   # WM_CLOSE
    if _elevated(w.get("pid", 0)) and not _verify(w["hwnd"], "gone"):
        return _blocked_note(w, "закрыть")
    # САМА ПРОВЕРЯЕТ РЕЗУЛЬТАТ (2026-07-28, просьба владельца). Раньше ответ
    # был «попросила закрыться» — и она искренне считала дело сделанным,
    # пока человек видел живое окно (реальный случай: VPN ушёл в трей и
    # проигнорировал просьбу). Секунду ждём и смотрим правде в глаза.
    time.sleep(1.2)
    try:
        gone = (not user32.IsWindow(w["hwnd"])
                or not user32.IsWindowVisible(w["hwnd"]))
    except Exception:
        gone = True
    if gone:
        return (f"Закрыла «{w['title'][:60]}» — проверила, окна на экране "
                "больше нет.")
    return (f"Попросила «{w['title'][:60]}» закрыться, но окно ВСЁ ЕЩЁ на "
            "экране — проверила сама. Либо оно спрашивает про несохранённое, "
            "либо игнорирует просьбы (VPN и трей-программы так любят). "
            "Скажи это человеку честно; жёстко снять можно только по его "
            "прямой просьбе — «убей процесс такой-то».")


def minimize_all(keep: str = "") -> str:
    """Свернуть всё, кроме названного. Просьба владельца: «что можно
    свернуть, пока работаем»."""
    _, _, user32 = _win32()
    k = (keep or "").strip().lower()
    done, stuck = [], []
    todo = [w for w in windows(include_minimized=False)
            if not (k and (k in w["title"].lower()
                           or k in (w["proc"] or "").lower()))
            and not _is_self_window(w)]   # своё окно не прячем от владельца
    for w in todo:
        try:
            user32.ShowWindow(w["hwnd"], 6)
        except Exception:
            pass
    time.sleep(0.15)                      # один общий кадр на все окна
    elevated_stuck = 0
    for w in todo:
        try:
            if user32.IsIconic(w["hwnd"]):
                done.append(w["title"][:40])
            else:
                # Диспетчер задач и прочие окна «от администратора» Windows
                # защищает от команд обычного процесса (UIPI): ShowWindow
                # молча не срабатывает. Это не наша поломка — говорим прямо.
                if _elevated(w.get("pid", 0)):
                    elevated_stuck += 1
                    stuck.append(w["title"][:40] + " (админ)")
                else:
                    stuck.append(w["title"][:40])
        except Exception:
            stuck.append(w["title"][:40])
    if not done and not stuck:
        return "Сворачивать было нечего."
    msg = (f"Свернула {len(done)}: " + ", ".join(done[:6])
           + ("…" if len(done) > 6 else "")) if done else "Ничего не свернулось."
    if stuck:
        msg += ". Не поддались: " + ", ".join(stuck[:4])
        if elevated_stuck:
            msg += (" — окна с пометкой (админ) Windows защищает от обычных "
                    "программ. start.bat при запуске просит права "
                    "администратора — согласись в окне UAC, и я смогу "
                    "командовать и ими.")
        else:
            msg += " — обычно это полноэкранные игры."
    return msg


def window_place(query: str, position: str = "center",
                 width: int = 0, height: int = 0) -> str:
    """РАССТАВИТЬ ОКНО (2026-07-28, просьба владельца): «по центру», «слева»,
    «в правый нижний угол», опционально с размером в процентах экрана.
    Рабочая область берётся без панели задач (SPI_GETWORKAREA) — окно не
    залезает под панель. Своё окно двигать можно — это не закрытие."""
    w = _match(query)
    if not w:
        return f"Не нашла окно «{query}»."
    import ctypes
    _, _, user32 = _win32()
    if _elevated(w.get("pid", 0)):
        return _blocked_note(w, "двигать")

    class RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                    ("r", ctypes.c_long), ("b", ctypes.c_long)]
    ra = RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0,
                                               ctypes.byref(ra), 0)
    sw, sh = ra.r - ra.l, ra.b - ra.t

    # размер: проценты экрана; 0 = не менять текущий
    cur = RECT()
    user32.GetWindowRect(w["hwnd"], ctypes.byref(cur))
    ww = int(sw * max(10, min(100, width)) / 100) if width else cur.r - cur.l
    wh = int(sh * max(10, min(100, height)) / 100) if height else cur.b - cur.t
    ww, wh = min(ww, sw), min(wh, sh)

    pos = (position or "center").strip().lower()
    # русские и английские имена позиций — голосом говорят по-русски
    aliases = {
        "центр": "center", "по центру": "center", "середина": "center",
        "лево": "left", "слева": "left", "право": "right", "справа": "right",
        "верх": "top", "сверху": "top", "низ": "bottom", "снизу": "bottom",
        "левый верхний": "topleft", "правый верхний": "topright",
        "левый нижний": "bottomleft", "правый нижний": "bottomright",
    }
    pos = aliases.get(pos, pos)
    cx, cy = ra.l + (sw - ww) // 2, ra.t + (sh - wh) // 2
    coords = {
        "center":      (cx, cy),
        "left":        (ra.l, cy),
        "right":       (ra.r - ww, cy),
        "top":         (cx, ra.t),
        "bottom":      (cx, ra.b - wh),
        "topleft":     (ra.l, ra.t),
        "topright":    (ra.r - ww, ra.t),
        "bottomleft":  (ra.l, ra.b - wh),
        "bottomright": (ra.r - ww, ra.b - wh),
    }
    if pos not in coords:
        return (f"не знаю позицию «{position}» — умею: центр, слева, справа, "
                "сверху, снизу и четыре угла")
    x, y = coords[pos]
    user32.ShowWindow(w["hwnd"], 9)            # SW_RESTORE: из свёрнутого
    if not user32.SetWindowPos(w["hwnd"], 0, x, y, ww, wh, 0x0004 | 0x0010):
        return _blocked_note(w, "двигать")
    return (f"Поставила «{w['title'][:50]}» {position}"
            + (f", размер {max(10, min(100, width))}%x"
               f"{max(10, min(100, height))}%" if width or height else "")
            + ".")


# ──────────────────────────────── звук ────────────────────────────────
def _pycaw_volume():
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    dev = AudioUtilities.GetSpeakers()
    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    import comtypes
    return comtypes.cast(iface, comtypes.POINTER(IAudioEndpointVolume))


def _tap_key(vk: int, times: int = 1):
    import ctypes
    for _ in range(max(1, times)):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


def volume(percent=None, mute=None, delta=None) -> str:
    """Громкость системы. Точное значение — через pycaw; если его нет,
    работаем клавишами громкости (шаг ~2%) и говорим об этом честно."""
    if not _IS_WIN:
        return "Управление звуком есть только в Windows."
    try:
        vol = _pycaw_volume()
        if mute is not None:
            vol.SetMute(bool(mute), None)
            return "Звук выключен." if mute else "Звук включён."
        cur = round(vol.GetMasterVolumeLevelScalar() * 100)
        if delta is not None:
            percent = cur + int(delta)
        if percent is None:
            return f"Громкость {cur}%."
        percent = max(0, min(100, int(percent)))
        vol.SetMasterVolumeLevelScalar(percent / 100.0, None)
        return f"Громкость {percent}%."
    except Exception as e:
        log.debug("pycaw недоступен (%s) — работаю клавишами", e)
    VK_MUTE, VK_DOWN, VK_UP = 0xAD, 0xAE, 0xAF
    if mute is not None:
        _tap_key(VK_MUTE)
        return "Переключила звук (точное состояние без pycaw не знаю)."
    step = int(delta if delta is not None else (10 if percent is None else 0))
    if percent is not None:
        # без pycaw абсолютное значение не выставить — честно говорим
        return ("Без библиотеки pycaw умею только «громче/тише». "
                "Поставь её — тогда смогу выставлять точный процент "
                "(setup/install_pc_control.bat).")
    _tap_key(VK_UP if step > 0 else VK_DOWN, abs(step) // 2 or 1)
    return "Сделала " + ("громче." if step > 0 else "тише.")


# ───────────────────────── вкладки активного окна ─────────────────────────
# Через клавиатуру, а не через API конкретного браузера: работает в Chrome,
# Edge, Firefox и вообще везде, где есть вкладки, и не требует расширения.
def tab(action: str, index: int = 0) -> str:
    if not _IS_WIN:
        return "Управление вкладками есть только в Windows."
    try:
        import keyboard
    except Exception:
        return ("Нет модуля keyboard — не могу нажимать клавиши. "
                "Поставь его: setup/install_pc_control.bat")
    a = (action or "").lower()
    if a in ("open", "new", "открыть"):
        keyboard.send("ctrl+t")
        return "Открыла новую вкладку."
    if a in ("close", "закрыть"):
        keyboard.send("ctrl+w")
        return "Закрыла вкладку."
    if a in ("next", "следующая"):
        keyboard.send("ctrl+tab")
        return "Перешла на следующую."
    if a in ("prev", "previous", "предыдущая"):
        keyboard.send("ctrl+shift+tab")
        return "Перешла на предыдущую."
    if a in ("go", "перейти", "switch"):
        n = int(index or 1)
        if n < 1:
            return "Номер вкладки считается с единицы."
        # Ctrl+9 в браузерах это ВСЕГДА последняя вкладка, а не девятая
        keyboard.send("ctrl+9" if n >= 9 else f"ctrl+{n}")
        return f"Перешла на вкладку {n}." if n < 9 else "Перешла на последнюю."
    if a in ("pin", "закрепить", "открепить"):
        # У закрепления нет своего сочетания ни в одном браузере — только
        # правая кнопка по вкладке. Честно говорим, а не делаем вид.
        return ("Закрепление вкладки браузеры не отдают горячей клавишей — "
                "это только правой кнопкой по вкладке. Могу открыть, "
                "закрыть, перелистнуть или перейти к нужной по номеру.")
    if a in ("move", "перенести", "переместить"):
        # Ctrl+Shift+PgUp/PgDn двигает ТЕКУЩУЮ вкладку по ленте
        n = int(index or 1)
        key = "ctrl+shift+page down" if n >= 0 else "ctrl+shift+page up"
        for _ in range(min(abs(n) or 1, 20)):
            keyboard.send(key)
        return f"Подвинула вкладку на {abs(n) or 1} позиций."
    if a in ("restore", "вернуть", "reopen"):
        keyboard.send("ctrl+shift+t")
        return "Вернула закрытую вкладку."
    return f"Не знаю действия «{action}» для вкладок."


# ──────────────────── ПОИСК ПАПОК ПО ДИСКАМ ────────────────────
# Владелец: «я ей говорю найти папку с играми на диске C, она ищет, видит
# варианты и спрашивает, какая из них — я называю, она запоминает».
# Ровно это здесь и сделано. Запомненное живёт в file_hands.places, там уже
# есть механика закладок; сюда она приходит готовой.
#
# ПОЧЕМУ ГЛУБИНА ОГРАНИЧЕНА. Полный обход диска — это минуты и сотни тысяч
# папок. Всё, что человек называет словами («игры», «проекты», «музыка»),
# лежит близко к корню: C:\Games, D:\Steam\steamapps, Документы\Проекты.
# Три уровня закрывают это, а поиск занимает секунды.
_SKIP_DIRS = {"windows", "$recycle.bin", "system volume information",
              "programdata", "appdata", "node_modules", ".git", "__pycache__",
              "temp", "tmp", "cache", "recovery", "boot"}


def drives() -> list:
    """Буквы дисков, доступных для поиска."""
    if not _IS_WIN:
        return ["/"]
    out = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        p = Path(f"{letter}:/")
        try:
            if p.exists():
                out.append(f"{letter}:")
        except OSError:
            pass
    return out


# Человек говорит по-русски, а папки на диске почти всегда по-английски.
# Живой случай: «найди папку с играми» не нашло НИЧЕГО, а «Games» нашло
# одиннадцать штук. Поэтому запрос сам разворачивается в оба языка.
_SYNONYMS = {
    "игр": ("games", "game"),
    "музык": ("music", "музыка"),
    "видео": ("video", "videos", "movies"),
    "фильм": ("movies", "films", "video"),
    "картинк": ("pictures", "images", "img"),
    "фото": ("photos", "pictures", "camera"),
    "документ": ("documents", "docs"),
    "загруз": ("downloads", "download"),
    "проект": ("projects", "project", "work"),
    "работ": ("work", "projects"),
    "рабочий стол": ("desktop",),
    "модел": ("models", "assets"),
    "текстур": ("textures", "materials"),
    "рендер": ("render", "renders", "output"),
    "скрин": ("screenshots", "screenshot"),
    "сохранен": ("saves", "saved", "savegames"),
    "музыка": ("music",),
    "книг": ("books", "library"),
    "сцен": ("scenes", "levels"),
}
# Мусорные слова, которые человек говорит, а в имени папки их нет:
# «найди папку С ИГРАМИ» — «папка» и «с» только сбивают поиск.
_STOP_WORDS = {"папка", "папку", "папке", "папки", "директория", "каталог",
               "найди", "найти", "поищи", "ищи", "где", "мою", "мои", "моя",
               "с", "со", "на", "в", "для", "по", "folder", "directory",
               "find", "the", "my"}


def _expand(query: str) -> list:
    """Слова, по которым реально стоит искать: очищенный запрос + переводы."""
    q = (query or "").strip().lower()
    words = [w for w in re.findall(r"[\w-]+", q) if w not in _STOP_WORDS]
    out = [" ".join(words)] if words else []
    for w in words:
        out.append(w)
        for stem, alts in _SYNONYMS.items():
            if w.startswith(stem) or stem.startswith(w[:5] or "\0"):
                out.extend(alts)
    # длинные варианты вперёд: точное совпадение ценнее одиночного слова
    seen, res = set(), []
    for x in out:
        x = x.strip()
        if x and len(x) > 1 and x not in seen:
            seen.add(x)
            res.append(x)
    return res[:8]


def find_folder(query: str, drive: str = "", depth: int = 3) -> list:
    """Папки, похожие на запрос. Возвращает список путей, самые «главные»
    (ближе к корню, точнее совпадение) — первыми.

    Ограничена по времени намеренно (2026-07-26: в живом диалоге обход всех
    дисков занимал 30 секунд, и человек успевал переспросить трижды). Лучше
    отдать хорошие варианты за пару секунд, чем идеальные за полминуты.
    """
    terms = _expand(query)
    if not terms:
        return []
    q = terms[0]
    deadline = time.time() + float(CFG.get("pc.find_timeout_s", 4.0))
    roots = []
    if drive:
        d = drive.strip().rstrip(":\\/") + ":/"
        roots = [Path(d)] if Path(d).exists() else []
    else:
        roots = [Path(x + "/") for x in drives()]
        home = os.environ.get("USERPROFILE")
        if home:
            roots.append(Path(home))
    hits = []
    for root in roots:
        stack = [(root, 0)]
        while stack:
            if time.time() > deadline:
                log.info("Поиск папок «%s» остановлен по времени", query)
                break
            cur, lvl = stack.pop()
            if lvl > depth:
                continue
            try:
                entries = list(os.scandir(cur))
            except (PermissionError, OSError):
                continue
            for e in entries:
                try:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                name = e.name
                low = name.lower()
                if low in _SKIP_DIRS or low.startswith("."):
                    continue
                # берём лучшее совпадение по всем вариантам запроса —
                # русскому и английскому
                score = max(_score(name, t) for t in terms)
                if score > 0:
                    # ближе к корню — важнее: C:\Games главнее, чем
                    # C:\Users\...\AppData\...\games_cache
                    hits.append((score - lvl * 6, str(Path(e.path))))
                if lvl < depth:
                    stack.append((Path(e.path), lvl + 1))
    hits.sort(key=lambda h: -h[0])
    seen, out = set(), []
    for _s, path in hits:
        if path.lower() in seen:
            continue
        seen.add(path.lower())
        out.append(path)
        if len(out) >= 12:
            break
    return out


def remember_place(name: str, path: str) -> str:
    """Запомнить папку под человеческим именем — «игровая», «проекты».
    Дальше её не надо искать заново."""
    from server import file_hands
    return file_hands.place_save(name, path)


# ──────────────────────────────── папки ────────────────────────────────
def open_folder(path: str = "") -> str:
    """Открыть папку в проводнике. Рабочую директорию (files.roots) —
    свободно; всё остальное только если владелец разрешил гулять по диску."""
    from server import file_hands
    p = (path or "").strip()
    if not p:
        rs = file_hands.roots()
        if not rs:
            return "Рабочая папка не задана — укажи её в настройках."
        p = str(rs[0])
    target = Path(p)
    inside = any(target == r or r in target.parents
                 for r in file_hands.roots())
    # 2026-07-26. По умолчанию было запрещено — и получалась дичь: Сайка
    # САМА нашла человеку одиннадцать папок с играми, он выбрал первую, а
    # она отказалась её открыть. Открытие проводника ничего не меняет на
    # диске, это просто окно; запрет здесь охранял пустоту. Настоящая
    # защита — в file_hands: создавать, править и удалять она по-прежнему
    # может только внутри рабочей папки. Тумблер оставлен для тех, кому
    # нужно строже.
    if not inside and not CFG.get("pc.open_any_folder", True):
        return (f"«{p}» вне рабочей папки, а открывать посторонние тебе "
                "запрещено настройкой «Открывать любые папки».")
    if not target.exists():
        return f"Папки нет на диске: {p}"
    try:
        if _IS_WIN:
            os.startfile(str(target))       # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(target)])
    except Exception as e:
        return f"Не смогла открыть: {e}"
    return f"Открыла {target}."
