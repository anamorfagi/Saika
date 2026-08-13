"""
СВОИ ГЛАЗА (2026-08-05). Инструменты «прочитай, что получилось» и «читай
исходник, а не гадай».

Зачем. До сих пор Сайка действовала вслепую: инструмент отработал — она
видела только человеческую строчку результата, а что при этом упало в
logs/saika.log, ей недоступно. Отсюда классика «я же починила» при
неработающем движке. И второе: когда что-то ведёт себя не так, она может
только перебирать варианты — своего кода она не видит, хотя он лежит рядом.

Четыре инструмента, все ТОЛЬКО ЧИТАЮЩИЕ:
    fs_log      — хвост технического лога, с фильтром
    fs_lasterr  — последняя ошибка + человеческая причина
    fs_grep     — поиск по своим исходникам
    fs_slice    — кусок файла вокруг строки

Имена начинаются на fs_ намеренно: main.py ловит «похоже на инструмент, но
такого нет» по списку префиксов (строка ~641), и fs_ там уже есть. Иначе
маркер [fs_log:...] от мелкой модели проглотился бы молча — ровно тот баг,
ради которого тот блок и писали.

Почему не переиспользован file_hands: он заперт в files.roots (рабочая
папка), а логи и исходники лежат в корне проекта. Здесь свой белый список
корней и НИ ОДНОЙ операции записи.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from server.config import CFG

log = logging.getLogger("saika.selfread")

ROOT = Path(__file__).resolve().parents[1]

# Читаемые зоны. Только код и логи — личное сюда не входит.
_CODE_DIRS = ("server", "ui", "setup", "tools", "HandsPC", "workshop",
              "workers", "training")

# Никогда не отдавать, даже если путь формально попал в корень.
_DENY_NAMES = {"secrets.json", "config.local.json"}
_DENY_DIRS = {"voice", "data", "models", ".git", "_to_delete", "logs_private",
              "__pycache__", ".pip_cache", ".pip_tmp"}

_MAX_CHARS = 2800          # потолок отдаваемого текста (лимит tools ~3000)
_MAX_HITS = 40             # сколько совпадений показывать в поиске


def _roots() -> list[Path]:
    """Куда пускаем. Плюс то, что владелец добавил в selfread.extra_roots."""
    out = [ROOT / "logs"]
    for d in _CODE_DIRS:
        p = ROOT / d
        if p.is_dir():
            out.append(p)
    # библиотеки собственного окружения: когда падает faster-whisper или
    # torch, ответ лежит в их коде, а не в догадках.
    for venv in ROOT.glob(".venv*"):
        sp = venv / "Lib" / "site-packages"
        if sp.is_dir():
            out.append(sp)
    for extra in CFG.get("selfread.extra_roots", []) or []:
        try:
            p = Path(str(extra)).expanduser().resolve()
            if p.is_dir():
                out.append(p)
        except Exception:
            pass
    return out


def _resolve(user_path: str) -> Path:
    """Путь -> абсолютный, с проверкой белого списка. Только чтение."""
    if not user_path:
        raise PermissionError("пустой путь")
    p = Path(str(user_path).strip().strip('"'))
    if not p.is_absolute():
        p = ROOT / p
    p = p.resolve()          # схлопываем .. и симлинки ДО проверки
    if p.name in _DENY_NAMES:
        raise PermissionError(f"{p.name} — личное, не отдаю")
    if any(part in _DENY_DIRS for part in p.parts):
        raise PermissionError("эта папка закрыта для чтения")
    # корневые .md и .py читать можно — карта проекта живёт там
    if p.parent == ROOT and p.suffix.lower() in (".md", ".py", ".bat", ".txt"):
        return p
    for r in _roots():
        if p == r or r in p.parents:
            return p
    raise PermissionError("путь вне читаемых зон проекта")


def _cut(text: str) -> str:
    if len(text) <= _MAX_CHARS:
        return text
    return text[:_MAX_CHARS] + "\n…(обрезано)"


def _log_path() -> Path:
    return ROOT / "logs" / "saika.log"


def _tail_lines(path: Path, limit: int = 4000) -> list[str]:
    """Последние строки файла. Лог не ротируется и растёт вечно — читаем
    хвост через seek, а не файл целиком."""
    if not path.is_file():
        return []
    size = path.stat().st_size
    window = min(size, 900_000)
    with open(path, "rb") as fh:
        fh.seek(size - window)
        raw = fh.read()
    text = raw.decode("utf-8", errors="replace")
    if window < size:
        text = text.split("\n", 1)[-1]     # выбрасываем обрезанную строку
    return text.split("\n")[-limit:]


_ERR_RE = re.compile(r"\b(ERROR|CRITICAL|Traceback|Exception|PROBLEM)\b")


# ─────────────────────────── инструменты ───────────────────────────

def fs_log(filter_: str = "", lines: int = 60) -> str:
    """Хвост технического лога сервера. Не дев-доска — именно logs/saika.log."""
    path = _log_path()
    rows = _tail_lines(path)
    if not rows:
        return f"лога пока нет: {path}"

    if filter_:
        try:
            rx = re.compile(filter_, re.I)
            rows = [r for r in rows if rx.search(r)]
        except re.error:
            rows = [r for r in rows if filter_.lower() in r.lower()]
        if not rows:
            return (f"совпадений нет: по «{filter_}» в хвосте лога пусто. "
                    "Попробуй другое слово или посмотри лог без фильтра.")

    try:
        n = max(1, min(int(lines), 200))
    except Exception:
        n = 60
    rows = [r for r in rows[-n:] if r.strip()]

    # Самое важное — первым: путь текстовых маркеров обрезает результат
    # до 300 символов, и шапка «прочитала лог, всё хорошо» была бы бесполезна.
    errs = [r for r in rows if _ERR_RE.search(r)]
    head = f"последняя ошибка в логе: {errs[-1].strip()}" if errs \
        else "ошибок в этом куске лога нет"

    body = "\n".join(reversed(rows))      # свежее сверху
    return _cut(f"{head}\n--- {path.name}, {len(rows)} строк, свежие сверху ---\n"
                + body)


def fs_lasterr() -> str:
    """Последняя ошибка с человеческим объяснением причины."""
    # Сначала оперативная лента: там ошибка уже разобрана и снабжена
    # действием, которое предприняла самопочинка.
    try:
        from server.main import PROBLEMS
        if PROBLEMS:
            it = PROBLEMS[-1]
            comp = it.get("component", "?")
            err = (it.get("error") or "").strip()
            act = (it.get("action") or "").strip()
            why = ""
            try:
                from server import diagnostics
                d = diagnostics.short(comp, err)
                if isinstance(d, dict):
                    why = d.get("human") or d.get("action") or ""
                elif d:
                    why = str(d)
            except Exception:
                pass
            out = [f"последняя проблема: {comp} — {err or '(починилось)'}"]
            if why:
                out.append(f"причина: {why}")
            if act:
                out.append(f"что предприняла: {act}")
            out.append(f"всего в ленте проблем: {len(PROBLEMS)}")
            return _cut("\n".join(out))
    except Exception as e:
        log.debug("лента проблем недоступна: %s", e)

    # Фолбэк: последний трейсбек из лога.
    rows = _tail_lines(_log_path())
    idx = None
    for i in range(len(rows) - 1, -1, -1):
        if "Traceback" in rows[i]:
            idx = i
            break
    if idx is None:
        errs = [r for r in rows if _ERR_RE.search(r)]
        if errs:
            return _cut("последняя ошибка: " + errs[-1].strip())
        return "ошибок нет: ни в ленте проблем, ни в хвосте лога."
    block = [r for r in rows[idx:idx + 30] if r.strip()]
    return _cut("последний трейсбек из лога:\n" + "\n".join(block))


def fs_grep(pattern: str, where: str = "server") -> str:
    """Поиск по своим исходникам. Отвечает на «почему так работает»."""
    if not pattern:
        return "нужен текст для поиска"
    try:
        rx = re.compile(pattern, re.I)
    except re.error:
        rx = re.compile(re.escape(pattern), re.I)

    base = _resolve(where) if where else ROOT / "server"
    if base.is_file():
        files = [base]
    else:
        files = [p for p in base.rglob("*")
                 if p.is_file()
                 and p.suffix.lower() in (".py", ".js", ".html", ".css",
                                          ".json", ".md", ".bat", ".cs")
                 and not any(part in _DENY_DIRS for part in p.parts)
                 and p.name not in _DENY_NAMES]

    hits = []
    for f in files:
        try:
            if f.stat().st_size > 3_000_000:
                continue
            for i, line in enumerate(
                    f.read_text(encoding="utf-8", errors="replace").split("\n"), 1):
                if rx.search(line):
                    rel = f.relative_to(ROOT) if ROOT in f.parents else f
                    hits.append(f"{rel}:{i}: {line.strip()[:140]}")
                    if len(hits) >= _MAX_HITS:
                        break
        except Exception:
            continue
        if len(hits) >= _MAX_HITS:
            break

    if not hits:
        return (f"совпадений нет: «{pattern}» в {base} не встречается. "
                "Проверь написание или поищи в другой папке.")
    head = f"нашла {len(hits)}{'+' if len(hits) >= _MAX_HITS else ''} "\
           f"совпадений по «{pattern}»; первое: {hits[0]}"
    return _cut(head + "\n--- все совпадения ---\n" + "\n".join(hits))


def fs_slice(path: str, line: int = 0, around: int = 20) -> str:
    """Кусок файла вокруг строки. Продолжение fs_grep: нашла — прочитай."""
    p = _resolve(path)
    if not p.is_file():
        return f"нет такого файла: {p}"
    try:
        rows = p.read_text(encoding="utf-8", errors="replace").split("\n")
    except Exception as e:
        return f"не читается: {e}"

    try:
        line = int(line)
        around = max(2, min(int(around), 120))
    except Exception:
        line, around = 0, 20

    if line <= 0:
        a, b = 0, min(len(rows), around * 2)
    else:
        a = max(0, line - 1 - around)
        b = min(len(rows), line - 1 + around)

    body = "\n".join(f"{i + 1}: {rows[i]}" for i in range(a, b))
    rel = p.relative_to(ROOT) if ROOT in p.parents else p
    return _cut(f"{rel}, строки {a + 1}-{b} из {len(rows)}:\n{body}")


# ─────────────────────────── экспорт ───────────────────────────

def _fn(name, desc, props, required):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props,
                       "required": required}}}


SCHEMAS = [
    _fn("fs_log",
        "Заглянуть в СВОЙ технический лог (logs/saika.log) — что реально "
        "произошло внутри. Это НЕ дев-доска. Зови, когда что-то не сработало, "
        "спрашивают «что случилось», «почему не получилось», или ты сама "
        "не уверена, отработал ли инструмент. Не гадай — посмотри.",
        {"filter": {"type": "string",
                    "description": "слово или регулярка для фильтра "
                                   "(например: tts, ERROR, whisper)"},
         "lines": {"type": "integer",
                   "description": "сколько строк показать, по умолчанию 60"}},
        []),
    _fn("fs_lasterr",
        "Последняя ошибка с объяснением причины и тем, что предприняла "
        "самопочинка. Зови первым делом, когда говорят «сломалось», "
        "«не работает», «что у тебя случилось».",
        {}, []),
    _fn("fs_grep",
        "Найти текст в СВОИХ исходниках: почему что-то работает именно так, "
        "где принимается решение, какие есть настройки. Читать код надёжнее, "
        "чем гадать. Ищет в server/, ui/, setup/, tools/ и в библиотеках "
        "своего окружения.",
        {"pattern": {"type": "string",
                     "description": "что искать: имя функции, ключ конфига, "
                                    "кусок текста ошибки"},
         "where": {"type": "string",
                   "description": "где искать: server, ui, setup или путь. "
                                  "По умолчанию server"}},
        ["pattern"]),
    _fn("fs_slice",
        "Прочитать кусок файла вокруг строки — продолжение fs_grep: нашла "
        "совпадение, теперь посмотри, что там рядом.",
        {"path": {"type": "string", "description": "путь к файлу"},
         "line": {"type": "integer",
                  "description": "номер строки; 0 — читать с начала"},
         "around": {"type": "integer",
                    "description": "сколько строк вокруг, по умолчанию 20"}},
        ["path"]),
]

CALLS = {
    "fs_log": lambda a: fs_log(a.get("filter", "") or a.get("filter_", ""),
                               a.get("lines", 60) or 60),
    "fs_lasterr": lambda a: fs_lasterr(),
    "fs_grep": lambda a: fs_grep(a.get("pattern", ""),
                                 a.get("where", "server") or "server"),
    "fs_slice": lambda a: fs_slice(a.get("path", ""), a.get("line", 0) or 0,
                                   a.get("around", 20) or 20),
}

NAMES = set(CALLS)
