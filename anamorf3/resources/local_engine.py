"""Свой llama-server для anamorf3 — один владелец, проверяемая смерть.

ЗАЧЕМ (2026-10-09, аудит Codex п.5 + REQUESTS): старое ядро v2 поднимало
движок, а разгрузка и выход гасили ДРУГОЙ менеджер; «усыновлённый» после
перезапуска процесс stop() вообще не трогал — 9+ ГБ оставались занятыми.

Как здесь:
  * у нашего процесса МЕТКА в командной строке: --alias anamorf3-local.
    По ней находим и свои «потерянные» процессы (пережившие перезапуск),
    и только их — старая Сайка (alias saika-core, порт 8781) не наша;
  * stop() убивает дерево процесса (taskkill /T /F) и ПРОВЕРЯЕТ, что он
    умер и порт свободен. Не умер — так и говорит (survivors), а не «ок»;
  * свой порт 8791: старые сторожа его не знают.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

from . import settings as S

ALIAS = "anamorf3-local"
_NOWIN = 0x08000000 if os.name == "nt" else 0


class LocalEngine:
    def __init__(self, cfg: dict, state_dir: Path):
        self.cfg = cfg
        self.state = "stopped"          # stopped | starting | ready | error
        self.error = ""
        self.proc: subprocess.Popen | None = None
        self.pid: int | None = None
        self.started_s: float | None = None    # сколько поднимался
        self._lock = threading.RLock()
        self._log = state_dir / "llama_local.log"
        state_dir.mkdir(parents=True, exist_ok=True)

    # ── адрес и здоровье ───────────────────────────────────────────
    @property
    def port(self) -> int:
        return int(self.cfg["port"])

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def healthy(self, timeout: float = 1.0) -> bool:
        import http.client
        try:
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
            c.request("GET", "/health")
            r = c.getresponse()
            ok = r.status == 200 and b'"ok"' in r.read(200)
            c.close()
            return ok
        except Exception:
            return False

    def _args(self) -> list[str]:
        c = self.cfg
        a = [str(S.path(c["binary"])), "-m", str(S.path(c["model"])),
             "--host", "127.0.0.1", "--port", str(self.port), "--alias", ALIAS,
             # слот 0 — разговор, слот 1 — служебное; у каждого своя память
             # (стенд v2g 09.10: общий кэш обнулял разговор запросом глаз)
             "--ctx-size", str(int(c["ctx"]) * 2), "--parallel", "2",
             "-ngl", "999", "--n-cpu-moe", str(int(c["n_cpu_moe"])),
             "-fa", "on", "--no-mmap",
             "--batch-size", str(int(c["batch"])), "--ubatch-size", str(int(c["ubatch"])),
             "--cache-type-k", c["kv"], "--cache-type-v", c["kv"],
             "--jinja", "--reasoning-format", "deepseek", "--reasoning-budget", "0",
             "--metrics"]
        mm = c.get("mmproj")
        if mm and S.path(mm).exists():
            a += ["--mmproj", str(S.path(mm))]
        return a + [str(x) for x in c.get("extra") or []]

    # ── поиск своих процессов (в т.ч. переживших перезапуск) ───────
    @staticmethod
    def find_llama() -> list[dict]:
        """Все llama-server в системе: pid, наш ли, порт из командной строки."""
        if os.name != "nt":
            return []
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='llama-server.exe'\" | "
              "Select ProcessId,CommandLine | ConvertTo-Json -Compress")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=15,
                                 creationflags=_NOWIN).stdout.strip()
            items = json.loads(out) if out else []
            items = [items] if isinstance(items, dict) else items
        except Exception:
            return []
        res = []
        for it in items:
            cmd = it.get("CommandLine") or ""
            port = None
            parts = cmd.split()
            if "--port" in parts:
                try:
                    port = int(parts[parts.index("--port") + 1])
                except Exception:
                    pass
            res.append({"pid": it.get("ProcessId"), "ours": ALIAS in cmd,
                        "port": port, "alias": _after(parts, "--alias")})
        return res

    # ── запуск ─────────────────────────────────────────────────────
    def ensure(self, on_event=None) -> bool:
        with self._lock:
            if self.state == "ready" and self.healthy():
                return True
            # свой процесс пережил наш перезапуск — берём, а не плодим второй
            for p in self.find_llama():
                if p["ours"] and p["port"] == self.port and self.healthy():
                    self.pid, self.state, self.proc = p["pid"], "ready", None
                    return True
                if p["ours"]:              # наш, но не тот порт/не здоров — добить
                    _kill_tree(p["pid"])
            if _port_busy(self.port):
                self.state, self.error = "error", f"порт {self.port} занят чужим процессом"
                return False
            model = S.path(self.cfg["model"])
            if not model.exists():
                self.state, self.error = "error", f"нет файла модели: {model}"
                return False
            self.state, self.error = "starting", ""
            if on_event:
                on_event("model.loading", {"model": model.name, "port": self.port})
            t0 = time.monotonic()
            logf = open(self._log, "ab")
            self.proc = subprocess.Popen(self._args(), stdout=logf, stderr=logf,
                                         creationflags=_NOWIN)
            self.pid = self.proc.pid
            while time.monotonic() - t0 < float(self.cfg.get("start_timeout_s", 240)):
                if self.proc.poll() is not None:
                    self.state = "error"
                    self.error = f"движок упал при старте (код {self.proc.returncode}), лог: {self._log}"
                    return False
                if self.healthy():
                    self.state = "ready"
                    self.started_s = round(time.monotonic() - t0, 1)
                    if on_event:
                        on_event("model.loaded", {"model": model.name, "load_s": self.started_s,
                                                  "pid": self.pid})
                    return True
                time.sleep(0.5)
            self.state, self.error = "error", "движок не поднялся за отведённое время"
            self.stop()
            return False

    # ── остановка с проверкой ──────────────────────────────────────
    def stop(self) -> dict:
        """-> {"killed": [...], "survivors": [...]} — по фактам, не по намерению."""
        with self._lock:
            pids = {p["pid"] for p in self.find_llama() if p["ours"]}
            if self.pid:
                pids.add(self.pid)
            killed, survivors = [], []
            for pid in pids:
                _kill_tree(pid)
            deadline = time.monotonic() + 10
            alive = set(pids)
            while alive and time.monotonic() < deadline:
                alive = {p for p in alive if _alive(p)}
                time.sleep(0.3)
            for pid in pids:
                (survivors if pid in alive else killed).append(f"llama-server pid {pid}")
            if _port_busy(self.port):
                survivors.append(f"порт {self.port} всё ещё занят")
            self.proc, self.pid = None, None
            self.state = "stopped" if not survivors else "error"
            self.error = "" if not survivors else "не всё остановилось: " + ", ".join(survivors)
            return {"killed": killed, "survivors": survivors}

    def status(self) -> dict:
        return {"state": self.state, "error": self.error, "pid": self.pid,
                "port": self.port, "model": Path(self.cfg["model"]).name,
                "load_s": self.started_s}


def _after(parts: list[str], flag: str):
    try:
        return parts[parts.index(flag) + 1]
    except Exception:
        return None


def _kill_tree(pid: int):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=15, creationflags=_NOWIN)
    else:
        try:
            os.kill(pid, 9)
        except Exception:
            pass


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=_NOWIN).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _port_busy(port: int) -> bool:
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()
