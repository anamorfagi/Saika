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
import subprocess
import time

from server.config import ROOT

log = logging.getLogger("saika.git")

_fetch_cache = {"t": 0.0}
FETCH_INTERVAL_S = 90  # не долбим GitHub на каждый опрос статуса из UI


def _run(args, timeout=30):
    try:
        r = subprocess.run(
            ["git", *args], cwd=str(ROOT), capture_output=True, text=True,
            timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode, r.stdout.strip(), r.stderr.strip()
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

    return {"is_repo": True, "branch": branch, "changed": changed,
            "has_remote": has_remote, "ahead": ahead, "behind": behind}


def pull() -> dict:
    """git pull --ff-only — только перемотка вперёд. Если история разошлась
    (например, коммитили на обоих ПК без синка) — честно отказывается и
    отдаёт ошибку git, не пытается сама мержить/ребейзить."""
    code, out, err = _run(["pull", "--ff-only"], timeout=120)
    if code != 0:
        return {"ok": False, "error": err or out}
    _fetch_cache["t"] = time.time()
    log.info("git pull: %s", out)
    return {"ok": True, "message": out or "уже актуально"}


def sync(message: str = "") -> dict:
    """git add -A && commit && push. Возвращает {"ok":bool,...}."""
    code, out, err = _run(["add", "-A"])
    if code != 0:
        return {"ok": False, "step": "add", "error": err or out}

    msg = message.strip() or "Sync from Saika UI"
    code, out, err = _run(["commit", "-m", msg])
    if code != 0:
        if "nothing to commit" in (out + err).lower():
            return {"ok": True, "committed": False, "pushed": False,
                    "message": "нечего коммитить — рабочая копия чистая"}
        return {"ok": False, "step": "commit", "error": err or out}

    code, out, err = _run(["push"], timeout=120)
    if code != 0:
        return {"ok": False, "step": "push", "error": err or out,
                "committed": True,
                "message": "закоммитила локально, но push не прошёл — "
                          "смотри ошибку ниже"}

    log.info("git sync: %s", msg)
    return {"ok": True, "committed": True, "pushed": True,
            "message": "запушено: " + msg}
