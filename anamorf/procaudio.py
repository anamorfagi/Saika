# -*- coding: utf-8 -*-
"""ЗВУК ПО ПРОЦЕССАМ — ДВЕ ДОРОЖКИ ВМЕСТО ОДНОЙ ПЕТЛИ (2026-09-06).

Владелец: «если они там вдвоём пиздят — сразу научи писать две дорожки»,
«нам нужны алгоритмы предопределения: из какого приложения звук».

Windows 11 умеет отдавать loopback ОДНОГО процесса (и «всех, кроме него»).
Помощник tools/proclb (C#, см. Program.cs) льёт в stdout PCM int16 16 кГц.
Здесь: на каждое «приложение в фокусе» (procaudio.focus, по умолчанию
Discord) — свой поток include → канал «app:Discord»; плюс один поток
exclude первого приложения → канал «sys» (всё остальное: ролик, музыка).
Замер 16:53: ролик ушёл в «sys» (rms 0.035), Discord-канал остался тихим
(0.0005) — разделение физическое, без нейросетей.

Каналы идут в ту же очередь слуха, что и микрофон; нарезка у каждого
своя, отпечатки и облачка — свои. Если помощника нет или процесс не
запущен — молча работает старая общая петля.
"""
import logging
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from anamorf.config import CFG, ROOT

log = logging.getLogger("saika.procaudio")

EXE = ROOT / "tools" / "proclb" / "bin" / "proclb.exe"
STATE = {"on": False, "streams": {}, "err": "", "q": None}
_LOCK = threading.Lock()
_STOP = threading.Event()


def enabled() -> bool:
    return bool(CFG.get("procaudio.enabled", True)) and EXE.exists()


def _root_pid(name: str):
    """Корень дерева процессов с таким именем (include берёт всё дерево)."""
    try:
        import psutil
    except Exception:
        return None
    pids = []
    low = name.lower()
    for p in psutil.process_iter(["name"]):
        n = (p.info.get("name") or "").lower()
        if n == low or n == low + ".exe":
            pids.append(p.pid)
    for q in pids:
        try:
            pp = psutil.Process(q).parent()
            if pp is None or (pp.name() or "").lower() not in (low, low + ".exe"):
                return q
        except Exception:
            continue
    return pids[0] if pids else None


class _Stream:
    def __init__(self, key, pid, mode, src):
        self.key, self.pid, self.mode, self.src = key, pid, mode, src
        self.proc = None
        self.frames = 0
        self.loud_ts = 0.0
        self.err = ""
        self.t = threading.Thread(target=self._run, daemon=True, name="proclb-" + key)
        self.t.start()

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def _run(self):
        try:
            self.proc = subprocess.Popen([str(EXE), str(self.pid), self.mode, "16000"],
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            self.err = str(e)[:120]
            return
        step = 1600 * 2  # 100 мс int16
        buf = b""
        while not _STOP.is_set():
            d = self.proc.stdout.read(step - len(buf)) if len(buf) < step else b""
            if not d and len(buf) < step:
                break
            buf += d
            if len(buf) < step:
                continue
            chunk, buf = buf[:step], buf[step:]
            a = np.frombuffer(chunk, np.int16)
            self.frames += 1
            if float(np.abs(a).max()) > 60:
                self.loud_ts = time.time()
            qg = STATE.get("qget")
            q = qg() if qg else None
            if q is not None:
                try:
                    q.put_nowait((self.src, a.copy()))
                except Exception:
                    pass
        try:
            self.err = (self.proc.stderr.read() or b"").decode("utf-8", "replace")[-200:]
        except Exception:
            pass

    def stop(self):
        try:
            if self.proc:
                self.proc.kill()
        except Exception:
            pass


def _supervise():
    while not _STOP.is_set():
        try:
            focus = [str(x) for x in (CFG.get("procaudio.focus", ["Discord"]) or [])]
            want = {}
            first = None
            for name in focus:
                pid = _root_pid(name)
                if pid:
                    want["app:" + name] = (pid, "include", "app:" + name)
                    if first is None:
                        first = (name, pid)
            if first is not None:
                want["sys"] = (first[1], "exclude", "sys")
            with _LOCK:
                cur = STATE["streams"]
                for k in list(cur):
                    s = cur[k]
                    if k not in want or want[k][0] != s.pid or not s.alive():
                        s.stop()
                        cur.pop(k, None)
                        log.info("Звук по процессам: канал %s остановлен", k)
                for k, (pid, mode, src) in want.items():
                    if k not in cur:
                        cur[k] = _Stream(k, pid, mode, src)
                        log.info("Звук по процессам: канал %s ← pid %d (%s)", k, pid, mode)
                STATE["on"] = "sys" in cur and cur["sys"].alive()
        except Exception as e:
            STATE["err"] = str(e)[:160]
        time.sleep(5.0)


def start(qget):
    """qget — функция, отдающая текущую очередь слуха (она меняется с вкладкой)."""
    STATE["qget"] = qget
    if not enabled():
        log.info("Звук по процессам выключен (%s)", "нет помощника proclb.exe" if not EXE.exists() else "ручка")
        return False
    if STATE.get("thread"):
        return True
    STATE["thread"] = True
    threading.Thread(target=_supervise, daemon=True, name="procaudio").start()
    return True


def active() -> bool:
    """Идёт ли звук раздельно — тогда общую петлю в очередь не кладём."""
    return bool(STATE.get("on"))


def status():
    with _LOCK:
        return {"on": STATE["on"], "err": STATE["err"],
                "streams": {k: {"pid": s.pid, "mode": s.mode, "alive": s.alive(),
                                "frames": s.frames, "loud_ago": round(time.time() - s.loud_ts, 1) if s.loud_ts else None,
                                "err": s.err}
                            for k, s in STATE["streams"].items()}}
