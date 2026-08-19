"""Git-синк: кнопка в правом верхнем углу UI — закоммитить/запушить
текущее состояние проекта на GitHub, и подтянуть обновления, если проект
запущен на нескольких ПК (пуш с одного, пул на другом).

Работает поверх обычного git в PATH и уже настроенных на этой машине
учётных данных (credential manager / SSH-ключ, user.name/user.email) —
сам ничего не авторизует и не настраивает, просто дёргает
git add/commit/push/fetch/pull в корне проекта. Если push/pull отклонён
(конфликт, расхождение веток) — просто возвращает ошибку git как есть, не
пытается самостоятельно ребейзить/мержить (это осознанно, чтобы не
наломать дров на несколько ПК сразу).

Новые компоненты (venv, воркеры), которые появляются после pull — не
ставятся сами по себе сразу: как и DreamPC/Voxtral, каждый ставится лениво,
по клику на свою кнопку в UI (осознанный выбор — на другом ПК может не
быть смысла тянуть гигабайты того, что там не нужно)."""
import logging
import re
import subprocess
import time

from server.config import ROOT

log = logging.getLogger("saika.git")

_fetch_cache = {"t": 0.0}
FETCH_INTERVAL_S = 90  # не долбим GitHub на каждый опрос статуса из UI


def _run(args, timeout=30):
    """git с ЯВНОЙ кодировкой UTF-8 (2026-08-19, живой обвал).

    Было text=True без encoding — значит Python декодировал вывод кодировкой
    системы, а на русской Windows это cp1251. git отдаёт UTF-8, и первая же
    кириллическая «И» (байты D0 98) роняла поток-читатель:
    'charmap' codec can't decode byte 0x98. Поток умирал, r.stdout
    оставался None, и .strip() валил ВЕСЬ /api/git/status — панель git в
    интерфейсе отваливалась с 500. Всплыло, когда в сообщении последнего
    коммита появилась кириллица (мы её сами туда и положили, показав HEAD).
    errors=replace: лучше «крякозябра» в одном символе, чем мёртвая ручка."""
    try:
        r = subprocess.run(
            ["git", *args], cwd=str(ROOT), capture_output=True,
            encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", "git не найден в PATH"
    except subprocess.TimeoutExpired:
        return 124, "", "git завис (таймаут)"


def _maybe_fetch():
    """git fetch не чаще раза в FETCH_INTERVAL_S — сам статус UI поллит
    каждые 15с, а дёргать GitHub так часто незачем. Ошибку (нет сети)
    намеренно игнорируем — ahead/behind просто останутся по last-known."""
    if time.time() - _fetch_cache["t"] < FETCH_INTERVAL_S:
        return
    _fetch_cache["t"] = time.time()
    _run(["fetch", "--quiet"], timeout=20)


def status() -> dict:
    """Ветка, незакоммиченные изменения, remote, и ahead/behind (сколько
    коммитов можно запушить / подтянуть)."""
    code, branch, _ = _run(["rev-parse", "--abbrev-ref", "HEAD"])
    if code != 0:
        return {"is_repo": False}
    code2, porcelain, _ = _run(["status", "--porcelain"])
    _, remote, _ = _run(["remote"])
    changed = len([ln for ln in porcelain.splitlines() if ln.strip()]) if code2 == 0 else 0
    has_remote = bool(remote.strip())

    ahead = behind = 0
    if has_remote:
        _maybe_fetch()
        code3, counts, _ = _run(
            ["rev-list", "--left-right", "--count", f"HEAD...origin/{branch}"])
        if code3 == 0:
            parts = counts.split()
            if len(parts) == 2:
                ahead, behind = int(parts[0]), int(parts[1])

    # ГДЕ Я СЕЙЧАС. Без этого панель показывала только «ветка dev · ⬇164»:
    # после ручного пула в терминале она молчала о том, что уже приехало, и
    # понять «я на fix7 или нет» было негде. Теперь отдаём сам HEAD.
    head = {}
    code4, line, _ = _run(["log", "-1", "--pretty=%h|%ad|%s",
                           "--date=format:%d.%m %H:%M"])
    if code4 == 0 and "|" in line:
        parts = line.split("|", 2)
        head = {"hash": parts[0], "date": parts[1],
                "msg": parts[2] if len(parts) > 2 else ""}

    return {"is_repo": True, "branch": branch, "changed": changed,
            "has_remote": has_remote, "ahead": ahead, "behind": behind,
            "head": head,
            "synced": has_remote and ahead == 0 and behind == 0}


# Файлы, которые Сайка переписывает САМА на каждой машине, но которые лежат
# в репозитории. Из-за них «Подтянуть обновления» упиралось в «Your local
# changes to the following files would be overwritten by merge … Aborting» —
# кнопка не могла ничего, и человек шёл в терминал.
AUTO_STASH = ("config.json", "DEVBOARD.md", "devboard.json")
# Из отложенного возвращаем своё: config.json машинно-специфичен (окно
# контекста под VRAM, микрофон, выбранные движки). Доску пусть приезжает
# общая — её ведут с обеих машин.
KEEP_LOCAL = ("config.json",)


def _porcelain_paths(out: str) -> list:
    """Пути из `git status --porcelain`. ВАЖНО: _run() отдаёт stdout уже
    .strip()-нутым, поэтому у ПЕРВОЙ строки съеден ведущий пробел статуса —
    наивный ln[3:] откусывал первую букву имени файла («onfig.json»). Режем
    по регэкспу и разворачиваем переименования «R old -> new»."""
    paths = []
    for ln in out.splitlines():
        if not ln.strip():
            continue
        name = re.sub(r"^\s*[A-Z?!ADMRCU ]{1,2}\s+", "", ln, count=1)
        name = name.split(" -> ")[-1].strip().strip('"')
        if name:
            paths.append(name)
    return sorted(set(paths))


def _dirty_among(files) -> list:
    """Изменённые (в индексе или в дереве) из перечисленных — именно они и
    мешают перемотке. Через diff, без разбора статусных префиксов."""
    _, out, _ = _run(["diff", "--name-only", "HEAD", "--", *files])
    return sorted({ln.strip().strip('"') for ln in out.splitlines()
                   if ln.strip()})


def _pull_autostash(files) -> dict:
    """Отложить свои правки в этих файлах → перемотать → вернуть своё.
    Стеш НЕ сбрасываем, если что-то пошло не так: лучше «лежит в stash»,
    чем «потерялось»."""
    code, out, err = _run(["stash", "push", "--", *files], timeout=60)
    if code != 0:
        return {"ok": False, "error": "не смогла отложить свои правки: "
                                      + (err or out)}
    _, sha, _ = _run(["rev-parse", "stash@{0}"])

    code, out, err = _run(["pull", "--ff-only"], timeout=120)
    if code != 0:
        _run(["stash", "pop"], timeout=60)   # вернули как было
        return {"ok": False, "error": err or out}

    kept, lost = [], []
    for f in files:
        if f not in KEEP_LOCAL:
            continue
        c, o, e = _run(["checkout", sha, "--", f])
        if c == 0:
            _run(["reset", "--quiet", "--", f])   # не оставлять в индексе
            kept.append(f)
        else:
            lost.append(f + ": " + (e or o))

    if lost:
        return {"ok": True, "message": out, "note":
                "своё осталось в git stash (вернуть: git stash pop) — "
                + "; ".join(lost)}

    _run(["stash", "drop"])
    _fetch_cache["t"] = time.time()
    msg = out or "обновлено"
    tail = ", ".join(f for f in files if f not in KEEP_LOCAL)
    if kept:
        msg += "\nсвой " + ", ".join(kept) + " оставила как был"
    if tail:
        msg += "\n" + tail + " — взяла с GitHub"
    return {"ok": True, "message": msg, "stash_sha": sha}


def pull() -> dict:
    """git pull --ff-only — только перемотка вперёд. Если история разошлась
    (например, коммитили на обоих ПК без синка) — честно отказывается и
    отдаёт ошибку git, не пытается сама мержить/ребейзить.

    Единственное, что делает сама: если перемотке мешают ТОЛЬКО файлы из
    AUTO_STASH (их Сайка и переписывает), откладывает их в stash, тянет и
    возвращает своё. Всё остальное — по-прежнему честный отказ."""
    code, out, err = _run(["pull", "--ff-only"], timeout=120)
    if code != 0:
        low = (out + err).lower()
        blocked = ("would be overwritten by merge" in low
                   or "would be overwritten by checkout" in low
                   or "local changes to the following files" in low)
        if blocked:
            dirty = _dirty_among(AUTO_STASH)
            others = [f for f in _dirty_among(["."]) if f not in AUTO_STASH]
            mentioned = [f for f in AUTO_STASH if f.lower() in low]
            if dirty and mentioned and not any(
                    f.lower() in low for f in others):
                log.info("git pull: мешают только мои файлы %s — откладываю",
                         dirty)
                return _pull_autostash(dirty)
        return {"ok": False, "error": err or out}
    _fetch_cache["t"] = time.time()
    log.info("git pull: %s", out)
    return {"ok": True, "message": out or "уже актуально"}


def _push() -> tuple[int, str, str]:
    """git push с авто-привязкой ветки. Если ветка ещё не связана с origin
    (частая ошибка «The current branch X has no upstream branch» — то самое
    «неправильная ветка привязки»), повторяем с --set-upstream origin <ветка>,
    чтобы дальше пуш работал обычным кликом."""
    code, out, err = _run(["push"], timeout=120)
    low = (out + err).lower()
    if code != 0 and ("no upstream" in low or "set-upstream" in low
                      or "has no upstream" in low):
        _, branch, _ = _run(["rev-parse", "--abbrev-ref", "HEAD"])
        log.info("git: ветка %s без upstream — привязываю к origin и пушу",
                 branch)
        code, out, err = _run(
            ["push", "--set-upstream", "origin", branch], timeout=120)
    return code, out, err


def sync(message: str = "") -> dict:
    """git add -A && commit && push. Возвращает {"ok":bool,...}.
    Пуш выполняется ВСЕГДА — даже если коммитить нечего: на прошлом разе
    push мог упасть (например, ветка без upstream), и локальный коммит
    «завис» неотправленным. Повторный клик его доотправит."""
    code, out, err = _run(["add", "-A"])
    if code != 0:
        return {"ok": False, "step": "add", "error": err or out}

    msg = message.strip() or "Sync from Saika UI"
    committed = False
    code, out, err = _run(["commit", "-m", msg])
    if code == 0:
        committed = True
    elif "nothing to commit" not in (out + err).lower():
        return {"ok": False, "step": "commit", "error": err or out}

    # пушим в любом случае (доотправить прежние неотправленные коммиты)
    code, out, err = _push()
    if code != 0:
        low = (out + err).lower()
        if "up-to-date" in low or "up to date" in low:
            return {"ok": True, "committed": committed, "pushed": False,
                    "message": "всё уже на GitHub — отправлять нечего"}
        return {"ok": False, "step": "push", "error": err or out,
                "committed": committed,
                "message": ("закоммитила локально, но push не прошёл — "
                            "смотри ошибку ниже" if committed
                            else "push не прошёл — смотри ошибку ниже")}

    log.info("git sync: %s", msg)
    if not committed:
        return {"ok": True, "committed": False, "pushed": True,
                "message": "новых изменений не было — доотправила прежние коммиты"}
    return {"ok": True, "committed": True, "pushed": True,
            "message": "запушено: " + msg}


# ═══════════════ УМНЫЙ ПУЛЛ (2026-07-28, просьба владельца) ═══════════════
# «Подтянуть обновления» было одной кнопкой с --ff-only: при разошедшейся
# истории она честно отказывалась — и всё, тупик без git-знаний. Теперь UI
# показывает СПИСОК входящих коммитов, даёт выбрать до какого тянуть и КАК:
# слить / перемотать / затереть / отложить своё. Каждый пункт подписан
# настоящей командой git — панель работает и как шпаргалка для запоминания.

def incoming() -> dict:
    """Входящие коммиты (есть на GitHub, нет здесь) + незакоммиченное своё."""
    _run(["fetch", "--quiet"], timeout=20)
    _fetch_cache["t"] = time.time()
    code, branch, _ = _run(["rev-parse", "--abbrev-ref", "HEAD"])
    if code != 0:
        return {"ok": False, "error": "не git-репозиторий"}
    code, out, err = _run(
        ["log", "--pretty=%h|%ad|%an|%s", "--date=format:%d.%m %H:%M",
         "-n", "30", f"HEAD..origin/{branch}"])
    commits = []
    if code == 0:
        for ln in out.splitlines():
            parts = ln.split("|", 3)
            if len(parts) == 4:
                commits.append({"hash": parts[0], "date": parts[1],
                                "author": parts[2], "msg": parts[3]})
    _, porcelain, _ = _run(["status", "--porcelain"])
    dirty = _porcelain_paths(porcelain)
    # исходящие — для честной картины «мы разошлись», а не просто «их N»
    _, ahead_out, _ = _run(["log", "--pretty=%h %s", "-n", "10",
                            f"origin/{branch}..HEAD"])
    return {"ok": code == 0, "branch": branch, "commits": commits,
            "dirty": dirty, "outgoing": ahead_out.splitlines(),
            "error": err if code != 0 else ""}


def conflict_files() -> list:
    _, out, _ = _run(["diff", "--name-only", "--diff-filter=U"])
    return [f.strip() for f in out.splitlines() if f.strip()]


def smart_pull(mode: str, target: str = "") -> dict:
    """Подтянуть выбранным способом. mode:
    ff    — git pull --ff-only          (только перемотка, безопасно)
    merge — git merge <цель>            (слить их коммиты с моими)
    hard  — git reset --hard <цель>     (ЗАТЕРЕТЬ моё, стать как на GitHub)
    stash — git stash -u → merge → pop  (отложить своё, слить, вернуть)
    target — хэш коммита, до которого тянем; пусто = весь origin/<ветка>."""
    _, branch, _ = _run(["rev-parse", "--abbrev-ref", "HEAD"])
    tgt = (target or f"origin/{branch}").strip()

    if mode == "ff":
        cmd = "git pull --ff-only"
        code, out, err = _run(["pull", "--ff-only"], timeout=120)
        return {"ok": code == 0, "message": out, "cmd": cmd,
                "error": (err or out) if code != 0 else ""}

    if mode == "hard":
        # затираем ЛОКАЛЬНОЕ — но не молча в пропасть: снапшот в stash,
        # чтобы «ой, не то затёр» лечилось git stash pop, а не слезами
        _run(["stash", "push", "-u", "-m", "до reset --hard (страховка)"],
             timeout=60)
        cmd = f"git reset --hard {tgt}"
        code, out, err = _run(["reset", "--hard", tgt], timeout=60)
        return {"ok": code == 0, "message": out, "cmd": cmd,
                "note": "своё незакоммиченное лежит в git stash — вернуть: "
                        "git stash pop",
                "error": (err or out) if code != 0 else ""}

    if mode == "stash":
        code, out, err = _run(["stash", "push", "-u", "-m",
                               "smart-pull: отложенное своё"], timeout=60)
        if code != 0:
            return {"ok": False, "cmd": "git stash push -u",
                    "error": err or out}
        r = smart_pull("merge", target)
        code2, out2, err2 = _run(["stash", "pop"], timeout=60)
        r["cmd"] = "git stash push -u → " + r.get("cmd", "") + " → git stash pop"
        if code2 != 0:
            r["conflicts"] = conflict_files()
            r["note"] = ("отложенное вернулось с конфликтами — разбор ниже"
                         if r.get("conflicts") else
                         "stash pop не прошёл: " + (err2 or out2))
        return r

    # merge (по умолчанию)
    cmd = f"git merge --no-edit {tgt}"
    code, out, err = _run(["merge", "--no-edit", tgt], timeout=120)
    if code != 0:
        files = conflict_files()
        if files:
            return {"ok": False, "cmd": cmd, "conflicts": files,
                    "error": "конфликты — реши по каждому файлу ниже"}
        return {"ok": False, "cmd": cmd, "error": err or out}
    return {"ok": True, "cmd": cmd, "message": out or "слито"}


def resolve_conflict(file: str, side: str) -> dict:
    """Решить конфликт файла: side=ours (моя версия) / theirs (с GitHub)."""
    if side not in ("ours", "theirs"):
        return {"ok": False, "error": "side: ours|theirs"}
    cmd = f"git checkout --{side} -- {file} && git add {file}"
    code, out, err = _run(["checkout", "--" + side, "--", file])
    if code != 0:
        return {"ok": False, "cmd": cmd, "error": err or out}
    code, out, err = _run(["add", "--", file])
    left = conflict_files()
    return {"ok": code == 0, "cmd": cmd, "conflicts": left,
            "error": (err or out) if code != 0 else ""}


def finish_merge() -> dict:
    """Все конфликты решены — завершить слияние коммитом."""
    left = conflict_files()
    if left:
        return {"ok": False, "conflicts": left,
                "error": "остались нерешённые файлы"}
    cmd = "git commit --no-edit"
    code, out, err = _run(["commit", "--no-edit"], timeout=60)
    return {"ok": code == 0, "cmd": cmd, "message": out,
            "error": (err or out) if code != 0 else ""}


def abort_merge() -> dict:
    """Передумал: отменить слияние, вернуться как было до него."""
    cmd = "git merge --abort"
    code, out, err = _run(["merge", "--abort"], timeout=60)
    return {"ok": code == 0, "cmd": cmd,
            "message": "слияние отменено, всё как было",
            "error": (err or out) if code != 0 else ""}
