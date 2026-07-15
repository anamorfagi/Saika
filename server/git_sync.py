"""Git-синк: кнопка в правом верхнем углу UI — закоммитить и запушить
текущее состояние проекта на GitHub одним кликом.

Работает поверх обычного git в PATH и уже настроенных на этой машине
учётных данных (credential manager / SSH-ключ, user.name/user.email) —
сам ничего не авторизует и не настраивает, просто дёргает git add/commit/push
в корне проекта. Если push отклонён (например, на GitHub есть коммиты,
которых нет локально) — просто возвращает ошибку git как есть, не пытается
самостоятельно ребейзить/мержить (это осознанно, чтобы не наломать дров)."""
import logging
import subprocess

from server.config import ROOT

log = logging.getLogger("saika.git")


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


def status() -> dict:
    """Ветка, есть ли незакоммиченные изменения, настроен ли remote."""
    code, branch, _ = _run(["rev-parse", "--abbrev-ref", "HEAD"])
    if code != 0:
        return {"is_repo": False}
    code2, porcelain, _ = _run(["status", "--porcelain"])
    _, remote, _ = _run(["remote"])
    changed = len([ln for ln in porcelain.splitlines() if ln.strip()]) if code2 == 0 else 0
    return {"is_repo": True, "branch": branch, "changed": changed,
            "has_remote": bool(remote.strip())}


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
