"""ПРОГУЛКА ПО КОМПЬЮТЕРУ: дошёл — увидел — запомнил (2026-08-14).

ВЛАДЕЛЕЦ ОПИСАЛ ЭТО СЦЕНАРИЕМ, дословно по шагам:

    «я говорю открой проводник — она моментально открывает PC.
     я говорю найди на диске C папки с играми — она находит все возможные
     игры и пути к ним, может ориентироваться по памяти на знакомые игры:
     если тут лежит хотя бы одна знакомая, потенциально тут лежат и другие.
     прописывает мне в чат под номерами папки и пути.
     я говорю либо название, либо номер, либо просто куда шагаем дальше.
     …она моментально просто переходит по пути, НЕ ПИЗДЯ ИЗЛИШНЕ, типа
     ага-угу-зашла.
     …вон зибраш добавь как прогу: если я попрошу запустить в будущем — ты
     знаешь, где она лежит. — поняла, записала.
     …ок, обратно на диск C — она сразу спускается в C:\\»

Отсюда ЧЕТЫРЕ правила, которые тут важнее любого кода:

 1. ШАГ — ЭТО ШАГ, А НЕ РАЗГОВОР. Переход отвечает путём и, если есть,
    короткой строкой содержимого. Ни «сейчас открою», ни «уже открыла»,
    ни встречных вопросов. Комментирует она сама, поверх факта.
 2. ВЫБОР ИДЁТ НОМЕРОМ. Всё, что показано человеку, пронумеровано и лежит
    в памяти списка. «Третий», «зибраш», «второй запусти» — один разбор.
 3. НАЙДЕННОЕ НЕ ТЕРЯЕТСЯ. Дошли до программы — «добавь как прогу», и
    дальше запуск идёт рефлексом, мимо думанья.
 4. ОРИЕНТИР — ЗНАКОМОЕ ИМЯ. Гнездо с играми узнаётся не по названию
    папки (она может зваться как угодно), а по СОСЕДЯМ: увидели внутри
    Genshin или steamapps — значит это гнездо, и рядом лежит остальное.

ЧЕГО ЗДЕСЬ НАМЕРЕННО НЕТ. Никаких «а вы уверены?» и подтверждений на
переход: открыть папку — действие без последствий. Спрашиваем ровно один
раз и только там, где вариантов правда несколько.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path

from anamorf import pc_control as _pc
from anamorf.config import CFG

log = logging.getLogger("saika.explorer")

_IS_WIN = os.name == "nt"

# ─────────────────────────── память списка ───────────────────────────
# Последнее, что мы показали человеку под номерами. Живёт пять минут:
# «третий» через полчаса относится уже к другому разговору, и молча
# выполнить его хуже, чем переспросить.
_OFFER: dict = {"kind": "", "items": [], "ts": 0.0, "title": ""}
_OFFER_TTL = 300.0


def offer_alive() -> bool:
    return bool(_OFFER["items"]) and (time.time() - _OFFER["ts"]) < _OFFER_TTL


def offer() -> dict:
    return dict(_OFFER) if offer_alive() else {}


def _remember_offer(kind: str, items: list, title: str = "") -> None:
    _OFFER.update(kind=kind, items=list(items), ts=time.time(), title=title)


def _drop_offer() -> None:
    _OFFER.update(kind="", items=[], ts=0.0, title="")


def _numbered(items: list, limit: int = 12) -> str:
    """Пронумерованный список — ровно то, что владелец просил видеть в чате."""
    out = []
    for i, it in enumerate(items[:limit], 1):
        tail = f" — {it['note']}" if it.get("note") else ""
        out.append(f"{i}. {it['path']}{tail}")
    if len(items) > limit:
        out.append(f"…и ещё {len(items) - limit}")
    return "\n".join(out)


# ──────────────────────── куда шагаем: разбор ────────────────────────
# «Этот компьютер» — корень всего, с него начинается любая прогулка.
_PC_WORDS = re.compile(
    r"^\s*(?:в\s+|на\s+|открой\s+|покажи\s+)*"
    r"(?:пк|pc|мой\s+компьютер|этот\s+компьютер|компьютер|комп|"
    r"проводник|explorer|диски|список\s+дисков|верх|самый\s+верх)\s*[.!]?\s*$",
    re.I)

# «диск ц», «диск си», «на диск D», «C:\» — человек произносит букву
# по-русски, а иногда и вовсе называет её словом
_DRIVE_SPOKEN = {
    "ц": "C", "си": "C", "цэ": "C", "с": "C", "c": "C",
    "д": "D", "дэ": "D", "ди": "D", "d": "D",
    "е": "E", "и": "E", "е:": "E", "e": "E",
    "эф": "F", "ф": "F", "f": "F", "джи": "G", "г": "G", "g": "G",
    "аш": "H", "h": "H",
}
# «ДИСКЕ» НЕ ОТДАЁТ СВОЮ ПОСЛЕДНЮЮ БУКВУ (2026-08-14, живой лог: на «найди
# мне игры на диске» ушло scan_disk drive='е'. Причина — «диск\w*\s*»:
# движок откатывался, брал «диск», а «е» из окончания записывал в букву
# диска. После «диск» ОБЯЗАН стоять пробел, иначе буквы нет вообще.)
_DRIVE_RE = re.compile(
    r"^\s*(?:на\s+|в\s+|обратно\s+(?:на|в)\s+|перейди\s+(?:на|в)\s+|"
    r"спустись\s+(?:на|в)\s+|зайди\s+(?:на|в)\s+)*"
    r"(?:диск\w*\s+)?([a-zа-яё]{1,2})\s*:?\s*[\\/]*\s*[.!]?\s*$", re.I)

# Личные папки: человек говорит «музыку открой», а где она лежит — забота
# системы, а не его. Здесь И русские имена, потому что в русской Windows
# они действительно так и называются на экране.
_SHELL_DIRS = {
    "музык": ("Music", "Музыка"),
    "music": ("Music", "Музыка"),
    "загруз": ("Downloads", "Загрузки"),
    "download": ("Downloads", "Загрузки"),
    "документ": ("Documents", "Документы"),
    "картинк": ("Pictures", "Изображения"),
    "изображен": ("Pictures", "Изображения"),
    "фото": ("Pictures", "Изображения"),
    "видео": ("Videos", "Видео"),
    "рабоч": ("Desktop", "Рабочий стол"),
    "стол": ("Desktop", "Рабочий стол"),
}


def _home() -> Path | None:
    h = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    p = Path(h) if h else None
    return p if p and p.is_dir() else None


def _shell_dir(word: str) -> Path | None:
    """Личная папка по слову. Проверяем оба имени: файловая система хранит
    английское, а глазами человек видит русское."""
    w = (word or "").strip().lower()
    home = _home()
    if not home or not w:
        return None
    for stem, names in _SHELL_DIRS.items():
        if not (w.startswith(stem) or stem.startswith(w[:5])):
            continue
        for n in names:
            p = home / n
            if p.is_dir():
                return p
    return None


def _drive_of(text: str) -> str:
    """«диск ц», «на D», «e:\\» -> «C:\\». Пусто — если это не про диск."""
    m = _DRIVE_RE.match(text or "")
    if not m:
        return ""
    tok = m.group(1).lower()
    letter = _DRIVE_SPOKEN.get(tok, tok.upper() if len(tok) == 1 else "")
    if not letter or not letter.isascii() or not letter.isalpha():
        return ""
    root = f"{letter.upper()}:\\"
    return root if (not _IS_WIN or Path(root).exists()) else ""


# ──────────────────────────── сам переход ────────────────────────────
_MYPC = "::{20D04FE0-3AEA-1069-A2D8-08002B30309D}"     # «Этот компьютер»
_SSF_DRIVES = 17                                        # он же, номером


def _explorer_windows():
    """Живые окна проводника через тот же COM, которым он сам и рулит."""
    if not _IS_WIN:
        return []
    try:
        import win32com.client
        shell = win32com.client.Dispatch("Shell.Application")
        return [w for w in shell.Windows()
                if "explorer" in str(w.FullName).lower()]
    except Exception as e:
        log.debug("Shell.Application недоступен: %s", e)
        return []


def _navigate(target: str) -> bool:
    """Перевести СУЩЕСТВУЮЩЕЕ окно проводника. Новых окон не плодим.

    2026-07-29, владелец: «зашла в Ламоду, но нафиг в новой папке?» — за
    прогулку из пяти шагов их набиралось пять. Человек ходит по одной
    папке, значит и окно должно быть одно."""
    for w in _explorer_windows():
        for attempt in (lambda: w.Navigate2(target) if target != _MYPC
                        else w.Navigate2(_SSF_DRIVES),
                        lambda: w.Navigate(target),
                        lambda: w.Navigate2(target)):
            try:
                attempt()
                try:
                    _, _, user32 = _pc._win32()
                    user32.SetForegroundWindow(int(w.HWND))
                except Exception:
                    pass
                return True
            except Exception:
                continue
    return False


def _open_new(target: str) -> bool:
    try:
        if _IS_WIN:
            if target == _MYPC:
                subprocess.Popen(["explorer.exe", "shell:MyComputerFolder"])
            else:
                os.startfile(target)            # noqa: S606
        else:
            subprocess.Popen(["xdg-open", target])
        # ПРИЦЕЛ НА ОТКРЫТОЕ (2026-08-19): окно появится через мгновение —
        # обводим его рамкой в фоне, чтобы человек видел, куда она пришла.
        try:
            from anamorf import pc_control as _pcs
            _name = os.path.basename(str(target).rstrip("\\/")) or "проводник"
            _pcs._spot(_name, f"папка: {_name}", wait_s=3.0,
                       proc="explorer.exe")
        except Exception as _se:
            log.debug("прицел на папку: %s", _se)
        return True
    except Exception as e:
        log.warning("не открыла %s: %s", target, e)
        return False


def _show(target: str) -> bool:
    """Показать путь в проводнике: сперва в текущем окне, иначе новым."""
    if _navigate(target):
        return True
    return _open_new(target)


def _peek(p: Path, dirs: int = 8, files: int = 6) -> str:
    """Одна короткая строка о содержимом. Не отчёт — ориентир для шага."""
    try:
        subs, fs = [], []
        for e in os.scandir(p):
            try:
                (subs if e.is_dir(follow_symlinks=False) else fs).append(e.name)
            except OSError:
                continue
    except OSError:
        return ""
    subs.sort(key=str.lower)
    fs.sort(key=str.lower)
    bits = []
    if subs:
        bits.append(", ".join(subs[:dirs]) + ("…" if len(subs) > dirs else ""))
    if fs:
        bits.append(", ".join(fs[:files]) + ("…" if len(fs) > files else ""))
    return " | ".join(bits)


def go(where: str = "") -> str:
    """ШАГ. Отвечает путём, а не рассказом о пути.

    Понимает: пусто и «пк» = «Этот компьютер»; «диск C», «ц», «e:»; личные
    папки словом («музыку»); «наверх», «назад»; полный путь; имя соседней
    папки (нечётко — человек диктует на слух)."""
    q = (where or "").strip().strip('"')

    # 1. «Этот компьютер» — и по умолчанию тоже
    if not q or _PC_WORDS.match(q):
        _show(_MYPC)
        _pc.remember_app("проводник")
        ds = ", ".join(_pc.drives()) if _IS_WIN else "/"
        _drop_offer()
        return f"Этот компьютер. Диски: {ds}."

    # 2. корень диска
    root = _drive_of(q)
    if root:
        p = Path(root)
        _show(str(p))
        _pc._go(p)
        _pc.remember_app("проводник")
        _drop_offer()
        inner = _peek(p)
        return f"{p}" + (f" — {inner}" if inner else "")

    # 3. наверх / назад — у прогулки они уже есть, не дублируем
    cur = Path(_pc.here()) if _pc.here() else None
    if _pc._NAV_UP.match(q) and cur is not None:
        target = cur.parent
    elif _pc._NAV_BACK.match(q):
        if not _pc._cwd["back"]:
            return "Назад некуда."
        target = Path(_pc._cwd["back"].pop())
        _pc._cwd.update(path=str(target), ts=time.time())
    else:
        target = _resolve(q, cur)
        if target is None:
            near = _peek(cur) if cur else ""
            return (f"«{q}» тут нет." + (f" Рядом: {near}" if near else "")
                    + " Скажи номер или полный путь.")

    if target.is_file():                      # «зайди в файл» = показать его
        target = target.parent
    _show(str(target))
    _pc._go(target)
    _pc.remember_app("проводник")
    _drop_offer()
    inner = _peek(target)
    return f"{target}" + (f" — {inner}" if inner else "")


def _resolve(q: str, cur: Path | None) -> Path | None:
    """Строчка -> папка на диске. Порядок дешевле→дороже."""
    # полный путь
    p = Path(q)
    if p.is_absolute() and p.exists():
        return p
    # личная папка словом: «музыку», «загрузки»
    sd = _shell_dir(q)
    if sd is not None:
        return sd
    # КОРЕНЬ ТЕКУЩЕГО ДИСКА — ТОЖЕ МЕСТО, ГДЕ ИЩУТ (2026-08-14, живой лог:
    # «зайди на диск C, Program Files» -> «Папки C:\Files тут нет. Здесь
    # (SteamLibrary) есть: steamapps». Она стояла в чужой библиотеке на E:,
    # а человек говорил про системную папку. Он называет ориентир, а не
    # соседа по текущей папке — и корень диска ближе к его карте мира.)
    bases = [b for b in (cur, _home()) if b is not None]
    if cur is not None:
        try:
            root = Path(cur.anchor)
            if root.is_dir() and root != cur:
                bases.append(root)
        except Exception:
            pass
    for d in (_pc.drives() if _IS_WIN else []):
        rp = Path(d + "\\")
        if rp.is_dir() and rp not in bases:
            bases.append(rp)
    try:
        from anamorf import file_hands
        bases += [Path(r) for r in file_hands.roots()]
    except Exception:
        pass
    # точное имя рядом
    for b in bases:
        cand = b / q
        if cand.exists():
            return cand
    # нечётко: человек диктует на слух, «зибраш» против «Maxon ZBrush 2026»
    best, bs = None, 0
    for b in bases:
        try:
            entries = [e for e in os.scandir(b) if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue
        for e in entries:
            s = max(_pc._score(e.name, q), _pc.phon_score(e.name, q))
            if s > bs:
                best, bs = Path(e.path), s
    return best if bs >= 30 else None


# ─────────────────── поиск гнёзд: игры и программы ───────────────────
# ЗНАКОМЫЕ ИМЕНА — ЭТО КОМПАС (владелец: «может ориентироваться на какие-то
# игры по памяти, чтобы определить: если тут лежит одна знакомая,
# потенциально тут лежат и другие»). Список не обязан быть полным и не
# обязан совпадать с тем, что стоит у человека: он нужен, чтобы УЗНАТЬ
# ГНЕЗДО. Дальше в гнезде берём всё подряд, включая незнакомое.
_GAME_MARKS = (
    "steamapps", "steam", "epic games", "gog galaxy", "riot games",
    "battle.net", "ubisoft", "origin", "ea games", "hoyoplay", "minihoyo",
    "genshin", "honkai", "zenless", "wuthering", "wuwa", "league of legends",
    "valorant", "dota", "counter-strike", "cs2", "csgo", "minecraft",
    "the witcher", "cyberpunk", "gta", "grand theft", "elden ring",
    "dark souls", "sekiro", "resident evil", "stellar blade", "war thunder",
    "world of tanks", "warframe", "destiny", "fallout", "skyrim", "starfield",
    "baldur", "divinity", "frostpunk", "metro ", "space marine", "pragmata",
    "f.e.a.r", "beat saber", "vrchat", "phasmophobia", "terraria", "rust",
    "palworld", "helldivers", "black myth", "nikke", "arknights",
)
# папка-гнездо часто зовётся именно так
_NEST_NAMES = ("games", "игры", "steamapps", "common", "epic games",
               "riot games", "gog games", "hoyoplay", "game", "gamefolder")
# признак «внутри лежит именно игра/программа», когда имя незнакомое
_EXE_HINT = (".exe", ".lnk", ".bat", ".url")

_PROG_MARKS = ("program files", "programs", "software", "soft", "portable",
               "apps", "приложения", "программы")


def _looks_game(name: str) -> bool:
    low = name.lower()
    return any(m in low for m in _GAME_MARKS)


def _has_exe(p: Path, budget: int = 400) -> bool:
    """Есть ли внутри что-то запускаемое — на один-два уровня вглубь."""
    n = 0
    stack = [(p, 0)]
    while stack and n < budget:
        cur, lvl = stack.pop()
        try:
            for e in os.scandir(cur):
                n += 1
                if n > budget:
                    break
                try:
                    if e.is_file(follow_symlinks=False):
                        if e.name.lower().endswith(_EXE_HINT):
                            return True
                    elif lvl < 2:
                        stack.append((Path(e.path), lvl + 1))
                except OSError:
                    continue
        except OSError:
            continue
    return False


def scan(what: str = "игры", drive: str = "", depth: int = 4) -> str:
    """НАЙТИ ГНЁЗДА и показать их пронумерованным списком.

    Не «папки, чьё имя похоже на запрос» — так искал старый find_folder, и
    на «где игры» он честно отдавал папку с названием games, промахиваясь
    мимо C:\\Program Files (x86)\\Games, где лежат одиннадцать штук. Гнездо
    узнаётся по содержимому: сколько внутри знакомых имён и сколько вообще
    запускаемых папок."""
    want_games = bool(re.search(r"игр|game|стим|steam|лаунч", what or "",
                                re.I)) or not (what or "").strip()
    roots = []
    # «НАЙДИ ЗДЕСЬ ИГРЫ» — ЗДЕСЬ, А НЕ ПО ВСЕМУ ДИСКУ (2026-08-14, живой
    # лог: человек стоял в Program Files (x86) и просил найти игры, а в
    # ответ получил лекцию «обычно они лежат в папках издательств». Он
    # уже привёл её на нужную полку — искать надо оттуда.)
    if re.search(r"\b(здесь|тут|в\s+этой\s+папке|отсюда)\b",
                 f"{drive} {what}", re.I):
        _cur = _pc.here()
        if _cur and Path(_cur).is_dir():
            roots = [Path(_cur)]
    d = "" if roots else (_drive_of(drive) or _drive_of(what))
    if d:
        roots = [Path(d)]
    elif drive and not roots:
        # человек мог назвать не букву, а прямо папку — «поищи игры в
        # D:\SteamLibrary». Ограничить обзор куском диска дешевле и точнее
        dd = drive.strip().strip('"')
        if Path(dd).is_dir():
            roots = [Path(dd)]
        else:
            dd = dd.rstrip(":\\/") + ":\\"
            roots = [Path(dd)] if Path(dd).is_dir() else []
    if not roots and not drive:
        # «по всем дискам» — только когда место НЕ названо. Иначе непонятое
        # «здесь» превращалось в обход всей машины (2026-08-14, стенд).
        roots = [Path(x + "\\") for x in _pc.drives()] if _IS_WIN else [Path("/")]
    if not roots:
        _cur2 = _pc.here()
        roots = [Path(_cur2)] if _cur2 and Path(_cur2).is_dir() else []
        if not roots:
            return f"Не поняла, где искать «{what}». Скажи диск или зайди в папку."

    deadline = time.time() + float(CFG.get("pc.scan_timeout_s", 8.0))
    nests: dict[str, dict] = {}
    seen_budget = 0

    for root in roots:
        stack = [(root, 0)]
        while stack:
            if time.time() > deadline or seen_budget > 60000:
                log.info("Обзор «%s» остановлен по лимиту", what)
                break
            cur, lvl = stack.pop()
            try:
                entries = [e for e in os.scandir(cur)
                           if e.is_dir(follow_symlinks=False)]
            except (PermissionError, OSError):
                continue
            seen_budget += len(entries)
            known = [e.name for e in entries if _looks_game(e.name)]
            nest_by_name = cur.name.lower() in _NEST_NAMES
            # ГНЕЗДО: либо внутри знакомое имя, либо папка так и называется
            # и внутри есть что запускать
            if entries and (known or (nest_by_name and len(entries) >= 2)):
                if want_games or not known:
                    score = len(known) * 10 + len(entries)
                    if nest_by_name:
                        score += 15
                    score -= lvl * 2
                    nests[str(cur)] = {
                        "path": str(cur), "score": score,
                        "count": len(entries),
                        "known": known[:4],
                        "names": [e.name for e in entries[:6]],
                    }
            for e in entries:
                low = e.name.lower()
                if low in _pc._SKIP_DIRS or low.startswith("."):
                    continue
                if lvl < depth:
                    stack.append((Path(e.path), lvl + 1))

    if not nests:
        return (f"Не нашла ничего похожего на «{what}»"
                + (f" на {roots[0]}" if len(roots) == 1 else "") + ".")

    ranked = sorted(nests.values(), key=lambda n: -n["score"])
    # ВЫКИДЫВАЕМ РОДНЮ (2026-08-14, поймано на стенде). Попали и Steam, и
    # steamapps\common — человеку нужна ПОЛКА С ИГРАМИ, а не общий предок;
    # а корень диска в этот список пролезал просто потому, что где-то в
    # нём лежит Riot Games. «Иди на C:\» — это не адрес игр.
    def _kin(a: str, b: str) -> bool:
        """Одна семья: один путь внутри другого (в любую сторону)."""
        a = a.lower().rstrip("\\/")
        b = b.lower().rstrip("\\/")
        return a == b or a.startswith(b + os.sep) or b.startswith(a + os.sep) \
            or a.startswith(b + "\\") or b.startswith(a + "\\") \
            or a.startswith(b + "/") or b.startswith(a + "/")

    out = []
    for n in ranked:
        if len(Path(n["path"]).parts) <= 1:      # C:\ — не гнездо, а диск
            continue
        # ranked уже отсортирован: от семьи остаётся лучший, а не первый
        # попавшийся. Иначе в списке оказывались и Steam, и steamapps, и
        # steamapps\common — три строки про одну полку.
        if any(_kin(n["path"], o["path"]) for o in out):
            continue
        out.append(n)
        if len(out) >= 10:
            break

    items = []
    for n in out:
        ex = n["known"] or n["names"][:3]
        items.append({"path": n["path"], "kind": "dir",
                      "note": f"{n['count']} шт.: " + ", ".join(ex)})
    _remember_offer("dir", items, title=what or "игры")
    head = f"Нашла {len(items)}:"
    return head + "\n" + _numbered(items) + \
        "\nСкажи номер или название — зайду."


# ───────────────────── поиск файлов там, где стоим ─────────────────────
_AUDIO = (".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus", ".wma", ".aac")
_RUN = (".exe", ".bat", ".cmd", ".lnk", ".ps1", ".url")
# «ТАМ ЕСТЬ КОМФИ ЮАЙ БАТ» — «бат» ЭТО РАСШИРЕНИЕ (2026-08-14, стенд: без
# этого сверху оказывался install-comfyui.ps1, а человек прямым текстом
# назвал .bat). Слово о типе файла — самая сильная подсказка, какая
# бывает: имя он помнит примерно, а тип — точно.
_EXT_WORDS = (
    (r"\bбат\w*\b|\bbat\b|батник", (".bat", ".cmd")),
    (r"\bexe\b|экзеш\w*|исполняем\w*", (".exe",)),
    (r"\bярлык\w*|\blnk\b", (".lnk",)),
    (r"\bps1\b|скрипт\w*\s*powershell|пауэршелл", (".ps1",)),
    (r"\bтрек\w*|\bпесн\w*|\bмузык\w*|\bmp3\b|аудио", _AUDIO),
    (r"\bвидео\b|\bролик\w*|\bmp4\b|\bфильм\w*",
     (".mp4", ".mkv", ".avi", ".webm", ".mov")),
    (r"\bкартинк\w*|\bфотк\w*|\bpng\b|\bjpg\b|изображени\w*",
     (".png", ".jpg", ".jpeg", ".webp", ".gif")),
    (r"\bтекстов\w*|\btxt\b|заметк\w*", (".txt", ".md")),
)


# ФАЙЛЫ ПОДПИСАНЫ ПО-АНГЛИЙСКИ, А ЧЕЛОВЕК ГОВОРИТ ПО-РУССКИ (2026-08-14,
# стенд: «трек из ЖЕЛЕЗНОГО ЧЕЛОВЕКА» против Iron_man_-_Gold_St.mp3).
# Транслит тут бессилен: «железный» никак не превратится в «iron» — это
# ПЕРЕВОД. Полный словарь не нужен и невозможен; нужен маленький список
# слов, которые действительно встречаются в названиях. Он будет расти —
# добавляй сюда всё, на чём она реально споткнулась.
_WORD_EN = {
    "железн": "iron", "человек": "man", "мэн": "man", "мен": "man",
    "звёздн": "star", "звездн": "star", "звезд": "star", "войн": "war",
    "ведьмак": "witcher", "кольц": "ring", "мертв": "dead", "мёртв": "dead",
    "город": "city", "ночь": "night", "ноч": "night", "огон": "fire",
    "огн": "fire", "лёд": "ice", "лед": "ice", "красн": "red",
    "чёрн": "black", "черн": "black", "бел": "white", "дом": "home",
    "любов": "love", "сердц": "heart", "кров": "blood", "смерт": "death",
    "жизн": "life", "сон": "dream", "мечт": "dream", "неб": "sky",
    "солнц": "sun", "лун": "moon", "тень": "shadow", "корол": "king",
    "королев": "queen", "бог": "god", "дьявол": "devil", "ангел": "angel",
    "паук": "spider", "летуч": "bat", "мыш": "mouse", "капитан": "captain",
    "америк": "america", "мстител": "avengers", "стражи": "guardians",
    "галактик": "galaxy", "последн": "last", "перв": "first",
    "велик": "great", "тёмн": "dark", "темн": "dark", "свет": "light",
}


def _to_en(q: str) -> str:
    """Английский вариант запроса по словарю. Пусто — переводить нечего."""
    words = re.findall(r"[\w-]+", (q or "").lower())
    out, hit = [], False
    for w in words:
        rep = None
        for stem, en in _WORD_EN.items():
            if w.startswith(stem):
                rep = en
                break
        out.append(rep or w)
        hit = hit or rep is not None
    return " ".join(out) if hit else ""


def _wanted_ext(q: str) -> tuple:
    """Расширения, которые человек назвал словом. Пусто — не называл."""
    out = []
    for rx, exts in _EXT_WORDS:
        if re.search(rx, q or "", re.I):
            out.extend(exts)
    return tuple(dict.fromkeys(out))


def look(query: str = "", depth: int = 2, limit: int = 12) -> str:
    """Найти файлы ЗДЕСЬ (и чуть вглубь) и показать номерами.

    Именно то место сценария, где человек говорит «запусти какой-нибудь
    трек из железного человека» или «там есть комфи юай бат»: она смотрит
    файлы, коротко перечисляет и ждёт номер."""
    base = Path(_pc.here()) if _pc.here() else None
    if base is None or not base.is_dir():
        return "Мы никуда не заходили — скажи, где искать."
    q = (query or "").strip()
    want_ext = _wanted_ext(q)
    # слово о типе файла своё дело сделало — в сравнении имён оно только
    # мешает: «комфи юай бат» против «START_COMFYUI» лишний слог портит
    qname = q
    for rx, _e in _EXT_WORDS:
        qname = re.sub(rx, " ", qname, flags=re.I)
    qname = re.sub(r"\s+", " ", qname).strip()
    qvars = [x for x in (qname, _to_en(qname)) if x]
    hits = []
    stack = [(base, 0)]
    deadline = time.time() + 4.0
    while stack and time.time() < deadline:
        cur, lvl = stack.pop()
        try:
            entries = list(os.scandir(cur))
        except (PermissionError, OSError):
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    if lvl < depth and e.name.lower() not in _pc._SKIP_DIRS:
                        stack.append((Path(e.path), lvl + 1))
                    continue
            except OSError:
                continue
            name = e.name
            low = name.lower()
            stem = Path(name).stem
            ext_ok = bool(want_ext) and low.endswith(want_ext)
            if not qname:
                s = 40 if (not want_ext or ext_ok) else 0
            else:
                s = 0
                ts = _pc.translit(stem).replace(" ", "").replace("_", "")
                for qv in qvars:
                    s = max(s, _pc._score(stem, qv), _pc.phon_score(stem, qv))
                    # совпадение по КУСКУ имени тоже считается:
                    # Iron_man_-_Gold_St… против «айрон мэн»
                    tq = _pc.translit(qv).replace(" ", "")
                    if tq and len(tq) >= 3 and tq in ts:
                        s = max(s, 60)
                    # …и по отдельному слову: «iron man» найдётся в
                    # Iron_man_-_Mark_II, где всё остальное — про другое
                    for w in qv.split():
                        tw = _pc.translit(w)
                        if len(tw) >= 3 and tw in ts:
                            s = max(s, 45)
            # ПОРОГ, А НЕ «ЛИШЬ БЫ БОЛЬШЕ НУЛЯ» (2026-08-14, стенд: в
            # список «треки железного человека» пролезали promptgenix и
            # PROMPTING-RU.md — одна общая буква давала им балл. Мусор в
            # пронумерованном списке страшнее короткого списка: человек
            # выбирает НОМЕР, не глядя.)
            # ПОРОГ ДЕЙСТВУЕТ ДАЖЕ ПРИ СОВПАВШЕМ ТИПЕ (2026-08-14, стенд:
            # «трек из железного человека» тащил promptgenix — он же mp3.
            # Названный тип сужает выбор, но не отменяет имя.)
            if qname and s < 28:
                continue
            if want_ext:
                s += 45 if ext_ok else -25   # тип назван — он решает
            elif low.endswith(_RUN):
                s += 15
            elif low.endswith(_AUDIO):
                s += 10
            if s <= 0:
                continue
            hits.append((s - lvl * 3, str(Path(e.path))))
    if not hits:
        return (f"В {base.name} ничего похожего на «{q}» нет."
                if q else f"В {base.name} файлов нет.")
    hits.sort(key=lambda h: -h[0])
    # НАЗВАЛ ТИП — ЗНАЧИТ ТИП (2026-08-14): «комфи юай БАТ» не должен
    # показывать .ps1 рядом с .bat. Если по типу вообще ничего не нашлось,
    # показываем что есть — молчать хуже.
    if want_ext:
        only = [h for h in hits if h[1].lower().endswith(want_ext)]
        if only:
            hits = only
    seen, items = set(), []
    # СКУДНЫЙ УЛОВ — ПОКАЖИ ВСЮ ПОЛКУ (владелец: «она проверяет файлы,
    # говорит, что нашла несколько, может озвучить коротко, какие треки
    # есть, какую запустить»). Один вариант в ответ на «какой-нибудь трек
    # из…» — это не выбор, а угадайка; лучше показать всё того же типа.
    if want_ext and len({h[1].lower() for h in hits}) < 2:
        extra = []
        try:
            for e in os.scandir(base):
                if e.is_file() and e.name.lower().endswith(want_ext):
                    extra.append((0, str(Path(e.path))))
        except OSError:
            pass
        known = {h[1].lower() for h in hits}
        hits = hits + [x for x in extra if x[1].lower() not in known]
    for _s, path in hits:
        if path.lower() in seen:
            continue
        seen.add(path.lower())
        items.append({"path": path, "kind": "file",
                      "note": Path(path).parent.name
                      if Path(path).parent != base else ""})
        if len(items) >= limit:
            break
    _remember_offer("file", items, title=q or base.name)
    if len(items) == 1:
        return "Одно: " + items[0]["path"]
    return (f"Нашла {len(items)}:\n"
            + "\n".join(f"{i}. {Path(it['path']).name}"
                        for i, it in enumerate(items, 1))
            + "\nКакой?")


# ───────────────────────── выбор из списка ─────────────────────────
_ORD = (("перв", 1), ("втор", 2), ("трет", 3), ("четв", 4), ("пят", 5),
        ("шест", 6), ("седьм", 7), ("восьм", 8), ("девят", 9), ("десят", 10))
_NUM_WORD = {"один": 1, "одна": 1, "два": 2, "две": 2, "три": 3,
             "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8,
             "девять": 9, "десять": 10}


def index_of(choice: str) -> int:
    """Номер из речи: «3», «номер три», «третий», «второй запусти». 0 — нет."""
    t = (choice or "").strip().lower()
    if not t:
        return 0
    m = re.search(r"\b(\d{1,2})\b", t)
    if m:
        return int(m.group(1))
    for stem, n in _ORD:
        if re.search(r"\b" + stem, t):
            return n
    for w, n in _NUM_WORD.items():
        if re.search(r"\b" + w + r"\b", t):
            return n
    return 0


def resolve_choice(choice: str) -> dict | None:
    """Что человек выбрал из последнего списка. None — не поняли."""
    if not offer_alive():
        return None
    items = _OFFER["items"]
    n = index_of(choice)
    if 1 <= n <= len(items):
        return items[n - 1]
    q = (choice or "").strip()
    if len(q) < 2:
        return None
    # СРАВНИВАЕМ ВЕСЬ ПУТЬ, А НЕ ПОСЛЕДНЕЕ ИМЯ (2026-08-14, стенд: человек
    # сказал «steam», и выбор ушёл в Riot Games — потому что у нужного
    # пункта последняя папка зовётся common, а слово steam стоит в
    # середине пути. Человек называет то, что ВИДИТ в строке).
    ql = q.lower()
    best, bs = None, 0
    for it in items:
        parts = [x for x in re.split(r"[\\/]+", it["path"]) if x]
        cand = parts[-3:] + [it.get("note", "")]
        s = 0
        for nm in cand:
            if not nm:
                continue
            s = max(s, _pc._score(nm, q), _pc.phon_score(nm, q))
        if ql and ql in it["path"].lower():
            s = max(s, 70)                    # слово прямо в пути — это оно
        if s > bs:
            best, bs = it, s
    return best if bs >= 30 else None


def pick(choice: str = "", run: bool = False) -> str:
    """Пойти по выбранному пункту: папка — зайти, файл — запустить."""
    it = resolve_choice(choice)
    if it is None:
        if not offer_alive():
            return "Списка нет — скажи, что искать."
        return ("Не поняла, какой именно. Список:\n"
                + _numbered(_OFFER["items"]))
    p = Path(it["path"])
    if it.get("kind") == "file" or p.is_file():
        return start(str(p)) if (run or p.suffix.lower() in _RUN
                                 or p.suffix.lower() in _AUDIO) else go(str(p))
    return go(str(p))


# ───────────────────────── запуск и память ─────────────────────────
def start(path: str = "") -> str:
    """Запустить файл. Пусто — то, что выбрано из списка."""
    p = Path(path) if path else None
    if p is None:
        it = resolve_choice("")
        p = Path(it["path"]) if it else None
    if p is None or not p.exists():
        return f"Нечего запускать: «{path}»."
    try:
        if _IS_WIN:
            os.startfile(str(p))              # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except Exception as e:
        return f"Не запустилось: {e}"
    _pc.remember_app(p.stem)
    try:
        _pc._spot(p.stem, f"запустила: {p.name}", wait_s=6.0)
    except Exception as _se:
        log.debug("прицел на запуск: %s", _se)
    return f"Запустила {p.name}."


def _main_exe(folder: Path) -> Path | None:
    """Главный запускаемый файл папки: тот, чьё имя ближе к имени папки, и
    точно не деинсталлятор с распаковщиком."""
    bad = ("unins", "setup", "install", "update", "crash", "vcredist",
           "redist", "helper", "service", "report", "launcher_repair")
    best, bs = None, -1
    n = 0
    for cur, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d.lower() not in _pc._SKIP_DIRS][:20]
        for f in files:
            low = f.lower()
            if not low.endswith((".exe", ".bat", ".cmd")):
                continue
            if any(b in low for b in bad):
                continue
            st = Path(f).stem
            s = _pc._score(st, folder.name)
            if low.endswith(".exe"):
                s += 10
            if Path(cur) == folder:
                s += 20                       # в корне папки — обычно главный
            # ZBRUSH.EXE, А НЕ ZBRUSHCORE.EXE (2026-08-14, стенд). Имя
            # главного файла — самое КОРОТКОЕ из семьи: всё, что длиннее,
            # это довесок (Core, Setup, Helper, Launcher_repair).
            if st.lower() in folder.name.lower():
                s += 15
            s -= max(0, len(st) - 6)
            if s > bs:
                best, bs = Path(cur) / f, s
            n += 1
            if n > 3000:
                return best
        if n > 3000:
            break
    return best


def learn(name: str = "", path: str = "") -> str:
    """«ВОН ЗИБРАШ — ДОБАВЬ КАК ПРОГУ» (владелец, дословно: «если я тебя
    попрошу запустить в будущем, ты знаешь, где она лежит»).

    Берём то, где стоим (или выбранное из списка), находим внутри главный
    запускаемый файл и кладём в память программ под ЕГО словом. Дальше
    «запусти зибраш» уходит рефлексом, мимо всякого думанья."""
    from anamorf import app_memory

    src = Path(path) if path else None
    if src is None:
        it = resolve_choice(name) if name else None
        src = Path(it["path"]) if it else None
    if src is None:
        cur = _pc.here()
        src = Path(cur) if cur else None
    if src is None or not src.exists():
        return "Не поняла, что запоминать — зайди в папку программы."

    exe = src if src.is_file() else _main_exe(src)
    if exe is None:
        return f"В {src.name} не нашла, что запускать (.exe/.bat)."
    key = (name or "").strip() or exe.stem
    # чистим служебные слова: «зибраш добавь как прогу» -> «зибраш»
    key = re.sub(r"\b(добавь|запомни|как|прог\w*|программ\w*|это|её|ее|"
                 r"в\s+память|себе)\b", " ", key, flags=re.I)
    key = re.sub(r"\s+", " ", key).strip(" .,!") or exe.stem
    app_memory.remember(key.lower(), exe.stem, str(exe))
    return f"Запомнила: «{key}» = {exe}. Дальше запускаю сразу."


def note() -> str:
    """Короткая шпаргалка о состоянии прогулки — для промпта."""
    cur = _pc.here()
    bits = []
    if cur:
        bits.append(f"стоим в {cur}")
    if offer_alive():
        bits.append(f"показан список из {len(_OFFER['items'])} "
                    f"({_OFFER['kind']}), человек может назвать номер")
    return "; ".join(bits)
