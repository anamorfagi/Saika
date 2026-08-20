"""Бэкенд инженерной вкладки обучения: сводка по локальному датасету,
запуск self-instruct расширения, поиск/превью/импорт готовых датасетов с
Hugging Face — то, что дёргает anamorf/main.py по HTTP из UI.

Переиспользует логику из training/dataset/fetch_dataset.py (тот же
best-effort маппинг произвольных полей в общий messages-формат), но здесь
это библиотека, вызываемая напрямую из процесса сервера — а не отдельный
CLI-скрипт, у сервера есть нормальный доступ в интернет (в отличие от
песочницы, где это разрабатывалось и где выхода к huggingface.co нет)."""
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from anamorf.config import CFG, resolve
from anamorf import runtime_env

log = logging.getLogger("saika.dataset_hub")

HF_API_SEARCH = "https://huggingface.co/api/datasets"
HF_ROWS_API = "https://datasets-server.huggingface.co/rows"


def _dataset_dir() -> Path:
    return resolve(CFG.get("training.dataset_dir", "training/dataset"))


def open_dataset_folder() -> dict:
    """Открыть training/dataset в Проводнике — кнопка 📂 в UI."""
    d = _dataset_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(str(d))  # noqa: S606 — локальный десктоп-хелпер, не веб-эндпоинт
        else:
            subprocess.Popen(["xdg-open", str(d)])
        return {"ok": True, "path": str(d)}
    except Exception as e:
        return {"error": f"не удалось открыть папку: {e}"}


# ------------------------------------------------------------ локальный обзор

def summary() -> dict:
    d = _dataset_dir()
    files = {}
    total = 0
    by_category = {}
    for name in ("seed_dialogues.jsonl", "expanded_dialogues.jsonl", "full_dataset.jsonl"):
        p = d / name
        if not p.exists():
            files[name] = {"exists": False, "count": 0}
            continue
        count = 0
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                count += 1
                if name != "full_dataset.jsonl":
                    try:
                        cat = json.loads(line).get("category", "other")
                        by_category[cat] = by_category.get(cat, 0) + 1
                    except Exception:
                        pass
        files[name] = {"exists": True, "count": count}
        if name != "full_dataset.jsonl":
            total += count

    imports_dir = d / "raw_imports"
    imports = []
    if imports_dir.exists():
        for p in sorted(imports_dir.glob("*.messages.jsonl")):
            count = sum(1 for line in p.open(encoding="utf-8") if line.strip())
            imports.append({"name": p.name, "count": count})

    return {
        "files": files,
        "by_category": by_category,
        "total_own": total,
        "imports": imports,
    }


# ------------------------------------------------------------- self-instruct

_expand_proc = None
_expand_log = None

# Переживает перезапуск сервера: PID/цель/модель пишутся на диск, поэтому
# expand_status()/stop_expand() видят реально запущенный процесс, даже если
# start.bat перезапустил сервер и глобальные _expand_proc обнулились (баг
# 2026-07-18: процесс расширения продолжал жить и долбить Ollama, а «Стоп»
# в UI даже не появлялся — кнопка восстанавливалась только по _expand_proc
# в памяти текущего процесса сервера).
_STATE_NAME = "dataset_expand_state.json"


def _state_path() -> Path:
    return resolve("logs") / _STATE_NAME


def _write_state(pid: int, target: int, model: str):
    p = _state_path()
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps({"pid": pid, "target": target, "model": model,
                             "started_at": time.time()}), encoding="utf-8")


def _read_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _clear_state():
    try:
        _state_path().write_text("{}", encoding="utf-8")
    except Exception:
        pass


def _pid_is_our_worker(pid: int) -> bool:
    """PID из state-файла жив и это правда expand_with_ollama.py, а не
    случайно переиспользованный Windows-ом номер процесса под что-то другое."""
    if not pid:
        return False
    try:
        import psutil
        if not psutil.pid_exists(pid):
            return False
        proc = psutil.Process(pid)
        cmdline = " ".join(proc.cmdline()).lower()
        return "expand_with_ollama" in cmdline
    except Exception:
        # psutil недоступен или процесс исчез между проверками — считаем,
        # что не наш (лучше дать перезапустить, чем врать «занято» вечно)
        return False


def _find_worker_pid() -> int | None:
    """PID реально работающего expand_with_ollama.py. Сперва быстрый путь —
    PID из state-файла; если его нет или он не наш (процесс запущен ДО
    того, как появился state-файл — «доисторический» сирота с прошлой
    версии, встречалось на практике 2026-07-18), перебираем все процессы
    по командной строке. Медленнее, зато находит зомби любого возраста."""
    state = _read_state()
    pid = state.get("pid")
    if pid and _pid_is_our_worker(pid):
        return pid
    try:
        import psutil
    except Exception:
        return None
    for proc in psutil.process_iter(["pid"]):
        try:
            cmdline = " ".join(proc.cmdline()).lower()
        except Exception:
            continue
        if "expand_with_ollama" in cmdline:
            return proc.pid
    return None


def _dataset_counts() -> tuple[int, int]:
    """(seed, expanded) — считаем напрямую из файлов, не из хвоста лога:
    надёжнее, лог может быть буферизован/обрезан."""
    d = _dataset_dir()

    def _count(name):
        p = d / name
        if not p.exists():
            return 0
        return sum(1 for line in p.open(encoding="utf-8") if line.strip())

    return _count("seed_dialogues.jsonl"), _count("expanded_dialogues.jsonl")


def expand_status() -> dict:
    state = _read_state()
    if _expand_proc is not None and _expand_proc.poll() is None:
        running = True
        done = False
        ok = False
    elif _expand_proc is not None:
        # умер сам, но это точно наш процесс этого же сервера — знаем код возврата
        running = False
        done = True
        ok = _expand_proc.returncode == 0
    else:
        # сервер перезапускался после старта расширения (или процесс вообще
        # старше state-файла — сирота с прошлой версии) — ищем по всем
        # процессам, не полагаясь только на PID из state
        pid = _find_worker_pid()
        running = pid is not None
        done = not running  # если что-то когда-то нашли — есть что показать
        ok = done  # код возврата потерян вместе со старым процессом сервера

    tail = ""
    if _expand_log is None:
        _log = resolve("logs") / "dataset_expand.log"
    else:
        _log = _expand_log
    if _log.exists():
        try:
            lines = _log.read_text(encoding="utf-8", errors="ignore").splitlines()
            tail = "\n".join(lines[-20:])
        except Exception:
            pass

    seed_n, expanded_n = _dataset_counts()
    current = seed_n + expanded_n
    target = state.get("target", 0)
    pct = min(100, round(100 * current / target)) if target else 0

    return {"running": running, "done": done, "ok": ok, "log_tail": tail,
            "current": current, "target": target,
            "model": state.get("model", ""), "pct": pct}


def start_expand(target: int, model: str) -> dict:
    global _expand_proc, _expand_log
    if (_expand_proc is not None and _expand_proc.poll() is None) or \
            _find_worker_pid() is not None:
        return {"error": "расширение уже идёт"}
    d = _dataset_dir()
    script = d / "expand_with_ollama.py"
    if not script.exists():
        return {"error": f"не найден {script}"}
    _expand_log = resolve("logs") / "dataset_expand.log"
    _expand_log.parent.mkdir(exist_ok=True)
    logf = open(_expand_log, "w", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # -u / PYTHONUNBUFFERED: без них python копит stdout в буфере и лог
    # остаётся пустым — в UI не видно хода выполнения (баг 2026-07-16)
    cmd = [runtime_env.PY, "-u", str(script),
           "--target", str(target), "--model", model]
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    log.info("dataset_hub: запускаю расширение датасета: %s", " ".join(cmd))
    _expand_proc = subprocess.Popen(cmd, cwd=str(d), stdout=logf,
                                    stderr=subprocess.STDOUT,
                                    creationflags=flags, env=env)
    _write_state(_expand_proc.pid, target, model)
    return {"ok": True}


def stop_expand() -> dict:
    global _expand_proc
    killed = False
    if _expand_proc is not None and _expand_proc.poll() is None:
        _expand_proc.terminate()
        killed = True
    else:
        # процесс сервера перезапускался (или это вообще сирота старше
        # state-файла) — находим PID полным перебором и глушим напрямую
        pid = _find_worker_pid()
        if pid is not None:
            try:
                import psutil
                psutil.Process(pid).kill()
                killed = True
            except Exception as e:
                return {"error": f"не удалось остановить процесс (PID {pid}): {e}"}
    _clear_state()
    return {"ok": True, "killed": killed}


# ------------------------------------------------------------------ HF-поиск

def hf_search(query: str, limit: int = 15) -> dict:
    """Поиск датасетов по названию через официальный HF Hub API."""
    url = (f"{HF_API_SEARCH}?search={urllib.parse.quote(query)}"
           f"&limit={limit}&full=false")
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": f"поиск на Hugging Face не удался: {e}"}

    results = []
    for item in data:
        results.append({
            "id": item.get("id"),
            "downloads": item.get("downloads", 0),
            "likes": item.get("likes", 0),
            "tags": item.get("tags", [])[:6],
        })
    results.sort(key=lambda r: r["downloads"], reverse=True)
    return {"results": results}


def _fetch_hf_rows(name: str, config: str, split: str, limit: int) -> list[dict]:
    rows = []
    offset = 0
    page = 100
    while len(rows) < limit:
        url = (f"{HF_ROWS_API}?dataset={urllib.parse.quote(name)}"
               f"&config={config}&split={split}&offset={offset}&length={page}")
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        batch = [r["row"] for r in data.get("rows", [])]
        if not batch:
            break
        rows.extend(batch)
        offset += page
    return rows[:limit]


def _auto_map_to_messages(row: dict):
    keys = {k.lower() for k in row}
    if "conversations" in row and isinstance(row["conversations"], list):
        role_map = {"human": "user", "gpt": "assistant", "system": "system",
                    "user": "user", "assistant": "assistant"}
        messages = []
        for turn in row["conversations"]:
            role = role_map.get(str(turn.get("from", "")).lower())
            value = turn.get("value")
            if role and value:
                messages.append({"role": role, "content": value})
        return {"messages": messages} if len(messages) >= 2 else None
    if "messages" in row and isinstance(row["messages"], list):
        return {"messages": row["messages"]}
    if {"instruction", "output"} <= keys:
        instr = row.get("instruction") or row.get("Instruction", "")
        inp = row.get("input") or row.get("Input", "")
        out = row.get("output") or row.get("Output", "")
        user_content = f"{instr}\n{inp}".strip() if inp else instr
        return {"messages": [{"role": "user", "content": user_content},
                             {"role": "assistant", "content": out}]}
    if {"question", "answer"} <= keys:
        return {"messages": [{"role": "user", "content": row.get("question") or row.get("Question")},
                             {"role": "assistant", "content": row.get("answer") or row.get("Answer")}]}
    if "prompt" in keys and ("response" in keys or "responses" in keys or "chosen" in keys):
        resp = row.get("response") or row.get("chosen") or (row.get("responses") or [None])[0]
        return {"messages": [{"role": "user", "content": row.get("prompt")},
                             {"role": "assistant", "content": resp}]}
    return None


def hf_preview(name: str, config: str = "default", split: str = "train", limit: int = 200) -> dict:
    try:
        raw_rows = _fetch_hf_rows(name, config, split, limit)
    except Exception as e:
        return {"error": f"не удалось скачать превью: {e}"}

    mapped, unmapped = [], 0
    for row in raw_rows:
        m = _auto_map_to_messages(row)
        if m and all(msg.get("content") for msg in m["messages"]):
            mapped.append(m)
        else:
            unmapped += 1

    sample_raw = raw_rows[0] if raw_rows and not mapped else None
    return {
        "raw_count": len(raw_rows),
        "mapped_count": len(mapped),
        "unmapped_count": unmapped,
        "sample": mapped[:5],
        "sample_raw": sample_raw,
    }


def hf_import(name: str, config: str = "default", split: str = "train", limit: int = 300) -> dict:
    try:
        raw_rows = _fetch_hf_rows(name, config, split, limit)
    except Exception as e:
        return {"error": f"не удалось скачать датасет: {e}"}

    mapped = []
    for row in raw_rows:
        m = _auto_map_to_messages(row)
        if m and all(msg.get("content") for msg in m["messages"]):
            m["category"] = "imported"
            mapped.append(m)

    if not mapped:
        return {"error": "ни одной записи не удалось автоматически смаппить "
                          "в формат диалога — структура этого датасета не "
                          "распознана"}

    out_dir = _dataset_dir() / "raw_imports"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{name.replace('/', '__')}.messages.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for m in mapped:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    return {"ok": True, "saved": len(mapped), "path": str(out_path)}


# ---------------------------------------------------------------------- merge

def merge_full_dataset() -> dict:
    d = _dataset_dir()
    parts = [d / "seed_dialogues.jsonl", d / "expanded_dialogues.jsonl"]
    imports_dir = d / "raw_imports"
    if imports_dir.exists():
        parts.extend(sorted(imports_dir.glob("*.messages.jsonl")))

    out_path = d / "full_dataset.jsonl"
    total = 0
    with out_path.open("w", encoding="utf-8") as out_f:
        for p in parts:
            if not p.exists():
                continue
            with p.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        out_f.write(line + "\n")
                        total += 1

    return {"ok": True, "total": total, "path": str(out_path)}
