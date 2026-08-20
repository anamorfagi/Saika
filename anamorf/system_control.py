"""Системное управление ПК: статус, список/поиск/завершение/запуск процессов.

Используется коннекторами мессенджеров (anamorf/messengers.py), чтобы можно
было с телефона сказать «закрой VPN на домашнем ПК». Опасные действия
(kill/launch) вызываются только после подтверждения и только владельцем —
эта проверка на стороне мессенджера. Здесь — сами действия + защита:
- критические системные процессы не трогаем никогда (не подвесить винду);
- запуск — только из белого списка в config (messengers.launch_allowlist),
  произвольные пути с телефона не запускаем (безопасность).
"""
import logging
import os
import subprocess
import time

log = logging.getLogger("saika.sysctl")

# эти процессы не убиваем ни при каких условиях — иначе система ляжет
_PROTECTED = {
    "system", "system idle process", "registry", "smss.exe", "csrss.exe",
    "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe", "svchost.exe",
    "fontdrvhost.exe", "dwm.exe", "explorer.exe", "python.exe",  # сама Сайка
    # llama-server — её мозги (2026-07-28): убить его = Сайка замолкает на
    # полуслове и «думает» бесконечно. Выключается он сам, вместе с ней.
    "llama-server.exe",
}


def _psutil():
    import psutil
    return psutil


def _fmt_gb(n):
    return f"{n / 2**30:.1f} ГБ"


def status_text() -> str:
    """Короткая сводка: ЦП, ОЗУ, аптайм, топ по памяти, GPU если есть."""
    try:
        ps = _psutil()
    except Exception:
        return "psutil не установлен — статус недоступен."
    vm = ps.virtual_memory()
    cpu = ps.cpu_percent(interval=0.3)
    up = time.time() - ps.boot_time()
    h, m = int(up // 3600), int((up % 3600) // 60)
    lines = [f"ЦП: {cpu:.0f}%",
             f"ОЗУ: {_fmt_gb(vm.total - vm.available)} / {_fmt_gb(vm.total)} ({vm.percent:.0f}%)",
             f"Аптайм: {h}ч {m}м"]
    g = _gpu_line()
    if g:
        lines.append(g)
    return "\n".join(lines)


def _gpu_line():
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,"
             "utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        name, mu, mt, util, temp = [s.strip() for s in
                                    r.stdout.strip().splitlines()[0].split(",")]
        return f"GPU: {name} — {util}%, {mu}/{mt} МБ VRAM, {temp}°C"
    except Exception:
        return ""


def gpu_mem():
    """(free_mb, total_mb) видеопамяти NVIDIA или (None, None)."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        free, total = [int(x) for x in
                       r.stdout.strip().splitlines()[0].split(",")]
        return free, total
    except Exception:
        return None, None


def gpu_top_processes(n=5):
    """Процессы, занимающие VRAM: [(name, pid, mb)] по убыванию — что закрыть."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory,process_name",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = []
        for line in r.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3 and parts[1].isdigit():
                name = ",".join(parts[2:])
                out.append((name, parts[0], int(parts[1])))
        out.sort(key=lambda x: -x[2])
        return out[:n]
    except Exception:
        return []


# собственный «мозг» Сайки — просить закрыть ЭТО глупо (это её же LLM/движок).
# Такие процессы не советуем закрывать; их она при желании выгружает сама.
_OWN_BRAIN = ("python", "ollama", "lm studio", "lmstudio", "lms.exe",
              "llmster", "koboldcpp")


def vram_advice(need_mb=4000) -> str:
    """Совет по нехватке VRAM. Логика: НЕ предлагаем закрывать собственные
    компоненты (LLM/Ollama/LM Studio/сам процесс) — только лишнее внешнее
    (браузеры, игры, приложения). Если всю память держит её же мозг — честно
    говорим об этом, а не «закрой сам себя». Пусто, если памяти хватает."""
    free, total = gpu_mem()
    if free is None or free >= need_mb:
        return ""
    procs = gpu_top_processes(8)
    external = [(n, m) for n, _, m in procs
                if not any(o in n.lower() for o in _OWN_BRAIN)]
    if external:
        hog = "; ".join(f"{n} ({m} МБ)" for n, m in external[:4])
        return (f"чтобы нормально пообщаться голосом, освободи видеопамять: "
                f"свободно {free} из {total} МБ, мне нужно ~{need_mb}. Закрой "
                f"лишнее (браузеры/приложения, Диспетчер задач): {hog}. Как "
                f"освободится — сама подхвачу клон-голос.")
    # всю VRAM держит её же LLM — закрывать себя смысла нет
    return (f"почти вся видеопамять ({total - free} из {total} МБ) занята моей "
            f"же LLM. Возьми модель полегче или дай мне выгрузить текущую — "
            f"тогда хватит и на клон-голос. Себя закрывать смысла нет.")


def list_top(n=8) -> str:
    """Топ процессов по памяти — «что вообще запущено»."""
    try:
        ps = _psutil()
    except Exception:
        return "psutil не установлен."
    procs = []
    for p in ps.process_iter(["name", "memory_info"]):
        try:
            mem = p.info["memory_info"].rss if p.info["memory_info"] else 0
            procs.append((mem, p.info["name"] or "?", p.pid))
        except Exception:
            pass
    procs.sort(reverse=True)
    out = ["Топ по памяти:"]
    for mem, name, pid in procs[:n]:
        out.append(f"  {name} — {_fmt_gb(mem)} (pid {pid})")
    return "\n".join(out)


def find(query: str):
    """Список процессов, чьё имя содержит query (без регистра)."""
    try:
        ps = _psutil()
    except Exception:
        return []
    q = query.lower().strip()
    hits = []
    for p in ps.process_iter(["name"]):
        try:
            nm = (p.info["name"] or "").lower()
            if q and q in nm:
                hits.append((p.pid, p.info["name"]))
        except Exception:
            pass
    return hits


def kill(queries, allow=None, deny=None) -> str:
    """Завершить процессы. queries — строка/pid ИЛИ список подстрок имён
    (напр. алиас «впн» -> ['amnezia','hupp','bluc']). Пул доступа:
    - deny: имена, которые НЕЛЬЗЯ трогать (плюс всегда критические системные);
    - allow: если непусто — трогаем ТОЛЬКО совпадающие с этим списком.
    Возвращает человеческий отчёт."""
    try:
        ps = _psutil()
    except Exception:
        return "psutil не установлен — не могу завершать процессы."

    if isinstance(queries, str):
        queries = [queries]
    protected = set(_PROTECTED) | {d.lower() for d in (deny or [])}
    allow = [a.lower() for a in (allow or [])]

    targets = []
    for q in queries:
        q = str(q).strip()
        if q.isdigit():
            try:
                targets.append(ps.Process(int(q)))
            except Exception:
                pass
            continue
        ql = q.lower()
        for p in ps.process_iter(["name"]):
            try:
                if ql and ql in (p.info["name"] or "").lower():
                    targets.append(p)
            except Exception:
                pass

    # уникализируем по pid
    seen, uniq = set(), []
    for p in targets:
        if p.pid not in seen:
            seen.add(p.pid)
            uniq.append(p)
    targets = uniq
    if not targets:
        return f"Не нашла процессов по запросу «{', '.join(map(str, queries))}»."

    import os as _os
    _self = {_os.getpid(), _os.getppid()}   # сервер и консоль start.bat
    killed, skipped, to_wait = [], [], []
    for p in targets:
        try:
            if p.pid in _self:
                skipped.append(f"pid {p.pid} (это я сама)")
                continue
            nm = (p.name() or "").lower()
            if nm in protected:
                skipped.append(nm + " (защищён)")
                continue
            if allow and not any(a in nm for a in allow):
                skipped.append(nm + " (не в списке разрешённых)")
                continue
            p.terminate()
            to_wait.append(p)
            killed.append(f"{p.name()} (pid {p.pid})")
        except Exception as e:
            skipped.append(f"{getattr(p, 'pid', '?')}: {e}")

    gone, alive = ps.wait_procs(to_wait, timeout=3)
    for p in alive:
        try:
            p.kill()
        except Exception:
            pass

    msg = []
    if killed:
        msg.append("Закрыла: " + ", ".join(killed))
    if skipped:
        msg.append("Не тронула: " + ", ".join(skipped))
    return "\n".join(msg) or "Ничего не закрыла."


def launch(key: str, allowlist: dict) -> str:
    """Запуск ТОЛЬКО из белого списка (config.messengers.launch_allowlist:
    имя -> путь к exe). Произвольные пути с телефона не запускаем."""
    key = key.lower().strip()
    path = None
    for k, v in (allowlist or {}).items():
        if k.lower() == key or key in k.lower():
            path = v
            break
    if not path:
        avail = ", ".join(allowlist.keys()) if allowlist else "список пуст"
        return (f"«{key}» нет в белом списке запуска. Доступно: {avail}. "
                "Добавь путь в config.json → messengers.launch_allowlist.")
    if not os.path.exists(path):
        return f"Путь для «{key}» не найден на диске: {path}"
    try:
        subprocess.Popen([path], creationflags=getattr(
            subprocess, "CREATE_NO_WINDOW", 0))
        return f"Запустила {key} ({os.path.basename(path)})."
    except Exception as e:
        return f"Не смогла запустить {key}: {e}"
