# -*- coding: utf-8 -*-
"""
[БЛОК РУКИ] Исполнитель заданий проекта. Живёт внутри HandsPC, поэтому поднимается
вместе с Сайкой из start.bat — отдельный батник и лишние клики не нужны.

Как устроено. Клод (или сама Сайка) кладёт файл задания в C:\\AI\\Saika\\jobs\\,
агент выполняет и кладёт рядом результат: код возврата, весь вывод, сколько секунд шло.
Ничего скрытого: задание видно файлом ДО запуска, результат остаётся файлом ПОСЛЕ,
плюс строка в logs\\handspc.log.

    jobs/<имя>.job.json   {"task": "probe"}            — что просят
    jobs/<имя>.out.json   {"code":0,"sec":12.4,...}    — что вышло на самом деле

Выполняется ТОЛЬКО то, что перечислено в TASKS. Произвольная команда не выполняется
никогда: даже подменённый файл задания максимум пересоберёт студию генома.
"""
import json
import logging
import os
import pathlib
import subprocess
import sys
import threading
import time

log = logging.getLogger("handspc.jobs")

SAIKA = pathlib.Path(__file__).resolve().parent.parent      # C:\AI\Saika
JOBS = SAIKA / "jobs"
GEN = SAIKA / "genome"
PY = [sys.executable]


def _task_list():
    """Задание -> настоящая команда. Ключи этого словаря и есть всё, что разрешено."""
    return {
        "hello":    lambda j: (PY + ["-c", "import sys,datetime;print('руки на месте · python',sys.version.split()[0],'·',datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S'))"], SAIKA, 20),
        "probe":    lambda j: (PY + [str(GEN / "pipeline" / "probe.py"), "--json", "--timeout", "10"], GEN, 240),
        "build":    lambda j: (["bash", str(GEN / "pipeline" / "build.sh")], GEN, 600),
        # Папку AnamorfGenom владелец снёс 18.09 вместе с exe — сборки больше нет.
        # Студия поднимается лаунчером на node: тогда работают /api/probe, /api/keyfind
        # и запись файлов, которых у страницы, открытой как file://, быть не может.
        "studio":   lambda j: (["node", str(GEN / "pipeline" / "launcher.js")], GEN, 30),
        "research": lambda j: (["powershell", "-NoProfile", "-File", str(GEN / "pipeline" / "start_research.ps1")], GEN, 90),
        "ping":     lambda j: (PY + [str(GEN / "pipeline" / "llm.py"), "--provider", str(j.get("provider", "gigachat"))]
                               + (["--model", str(j["model"])] if j.get("model") else []), GEN, 120),
        # Модель сама решает задачу инструментами: смотрит папки, читает, пишет, ищет в
        # интернете, при нехватке — дописывает себе инструмент. Это не «выполни скрипт»,
        # а «разберись». Шаги ограничены, удаления нет, всё пишется в jobs/agent_loop.log.
        "агент":    lambda j: (PY + [str(GEN / "pipeline" / "agent_loop.py"),
                                     "--provider", str(j.get("provider") or "proxyapi"),
                                     "--model", str(j.get("model") or "deepseek/deepseek-v3.2"),
                                     "--steps", str(int(j.get("steps") or 30)),
                                     str(j.get("задача") or j.get("task_text") or "")], GEN, 1800),
        "script":   _script,
        "git":      _git,
    }


def _script(j):
    """Любой скрипт из genome/pipeline — но только оттуда и только .py или .js."""
    name = "".join(c for c in str(j.get("file", "")) if c.isalnum() or c in "._-")
    if not name or not name.endswith((".py", ".js")):
        raise ValueError("script: нужен файл из genome/pipeline с расширением .py или .js")
    full = GEN / "pipeline" / name
    if not full.exists():
        raise FileNotFoundError("script: нет файла pipeline/" + name)
    args = [str(a) for a in (j.get("args") or [])][:20]
    head = PY if name.endswith(".py") else ["node"]
    return (head + [str(full)] + args, GEN, 900)


def _git(j):
    """Только чтение состояния — ничего не коммитит и не переписывает историю."""
    sub = str(j.get("sub", "status"))
    allowed = {"status": ["status", "--short", "--branch"],
               "log": ["log", "--oneline", "-20"],
               "diff": ["diff", "--stat"]}
    if sub not in allowed:
        raise ValueError("git: можно только " + ", ".join(allowed))
    return (["git"] + allowed[sub], SAIKA, 90)


def run_job(job):
    """Выполнить одно задание. Возвращает словарь с настоящими числами, не с обещаниями."""
    name = str(job.get("task", ""))
    tasks = _task_list()
    if name not in tasks:
        return {"task": name, "code": -1,
                "error": "такого задания нет. Доступны: " + ", ".join(sorted(tasks))}
    try:
        cmd, cwd, limit = tasks[name](job)
    except Exception as e:
        return {"task": name, "code": -1, "error": str(e)}
    started = time.monotonic()
    # Windows-python по умолчанию печатает в cp1251, и вывод приходил кракозябрами.
    # Просим дочерний процесс писать в utf-8 — тогда читается ровно то, что напечатано.
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, timeout=limit,
                           text=True, encoding="utf-8", errors="replace", env=env,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out, err, code, killed = p.stdout, p.stderr, p.returncode, False
    except subprocess.TimeoutExpired as e:
        out, err, code, killed = (e.stdout or ""), (e.stderr or ""), -9, True
    except Exception as e:
        return {"task": name, "code": -1, "sec": round(time.monotonic() - started, 1),
                "cmd": " ".join(map(str, cmd)), "error": str(e)[:300]}
    return {"task": name, "cmd": " ".join(map(str, cmd)), "code": code, "killed": killed,
            "sec": round(time.monotonic() - started, 1),
            "stdout": (out or "")[-200000:], "stderr": (err or "")[-40000:],
            "at": time.strftime("%Y-%m-%d %H:%M:%S")}


def _take(path):
    done = path.with_name(path.name.replace(".job.json", ".out.json"))
    if done.exists():
        return
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        done.write_text(json.dumps({"error": "задание не читается: %s" % e}, ensure_ascii=False), encoding="utf-8")
        return
    log.info("задание «%s» (%s)", job.get("task"), path.name)
    result = run_job(job)
    tmp = done.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, done)
    log.info("  → код %s за %s с%s", result.get("code"), result.get("sec", "?"),
             ("; " + result["error"][:90]) if result.get("error") else "")


def _студия():
    """Поднять лаунчер студии, если он не работает. Пока он живёт, загруженные лица
    сразу ложатся на диск и вшиваются в файл персонажа — иначе они остаются только
    в браузере и теряются при смене адреса страницы. 2026-09-18."""
    import socket
    s = socket.socket(); s.settimeout(1.0)
    try:
        s.connect(("127.0.0.1", 8765)); s.close()
        log.info("студия уже работает на 8765")
        return
    except OSError:
        pass
    finally:
        try: s.close()
        except Exception: pass
    script = GEN / "pipeline" / "launcher.js"
    if not script.exists():
        return
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        out = (GEN / "studio.log").open("a", encoding="utf-8")
        env = dict(os.environ, GENOME_NO_OPEN="1")   # без новой вкладки в браузере
        subprocess.Popen(["node", str(script)], cwd=str(GEN), stdout=out, stderr=out,
                         creationflags=flags, close_fds=True, env=env)
        log.info("студия поднята: http://localhost:8765/genome-studio.html")
    except Exception as e:
        log.warning("студию поднять не вышло: %s", e)


def _loop():
    JOBS.mkdir(exist_ok=True)
    try:
        _студия()
    except Exception:
        log.exception("проверка студии не удалась")
    (JOBS / "_руки_на_месте.txt").write_text(
        "Исполнитель заданий работает с " + time.strftime("%d.%m.%Y %H:%M") + "\n"
        "Живёт внутри HandsPC, поднимается вместе с Сайкой.\n"
        "Разрешены только задания: " + ", ".join(sorted(_task_list())) + "\n"
        "Журнал: logs\\handspc.log. Останови Сайку — руки отключатся.\n", encoding="utf-8")
    log.info("руки проекта: слежу за %s, заданий разрешено %d", JOBS, len(_task_list()))
    while True:
        try:
            for f in sorted(JOBS.glob("*.job.json")):
                _take(f)
        except Exception:
            log.exception("обход папки заданий не удался")
        time.sleep(1.5)


def start():
    threading.Thread(target=_loop, daemon=True, name="jobs-agent").start()


# инструмент для самой Сайки: «пересобери геном», «проверь стыки» — голосом, без файлов
def tool_run_job(task: str, file: str = "", provider: str = "", model: str = "", sub: str = "") -> str:
    r = run_job({"task": task, "file": file, "provider": provider, "model": model, "sub": sub})
    if r.get("error"):
        return "Не выполнено: " + r["error"]
    tail = (r.get("stdout") or r.get("stderr") or "").strip()[-1500:]
    return "Задание «%s»: код %s за %s с.\n%s" % (r["task"], r["code"], r.get("sec", "?"), tail)


TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_job",
        "description": "Выполнить служебное задание проекта Сайки на этом ПК: probe — проверить все стыки LLM, "
                       "build — пересобрать студию генома, exe — пересобрать exe, research — поднять воркера "
                       "исследований, ping — проверить модель живым запросом, script — запустить скрипт из "
                       "genome/pipeline, git — показать состояние репозитория, hello — проверка связи.",
        "parameters": {"type": "object", "properties": {
            "task": {"type": "string", "enum": ["hello", "probe", "build", "studio", "research", "ping", "script", "git", "агент"]},
            "file": {"type": "string", "description": "для script: имя файла из genome/pipeline"},
            "provider": {"type": "string", "description": "для ping: id провайдера"},
            "model": {"type": "string", "description": "для ping: имя модели"},
            "sub": {"type": "string", "description": "для git: status, log или diff"}},
            "required": ["task"]}}}


if __name__ == "__main__":
    # прямой запуск из start.bat: журнал в консоль, её перехватывает logs\jobs_agent.log
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    _loop()
