"""Внешний STT-движок: отдельный процесс со своим venv.

Решает конфликты зависимостей (например, Voxtral требует transformers>=5.2,
а Qwen3-TTS пинит ==4.57.3). Для пользователя всё выглядит как обычная смена
движка в веб-UI:

- venv есть -> сервер сам запускает воркер и шлёт ему аудио по HTTP
- venv нет  -> открывается окно установщика (.bat), Сайка остаётся на
  fallback-движке; когда установка закончится — просто выбери движок ещё раз

Конфиг в stt.engines.<name>:
  venv      папка отдельного окружения (напр. ".venv_voxtral")
  worker    скрипт воркера (напр. "workers/voxtral_worker.py")
  setup     установщик (напр. "setup/install_voxtral.bat")
  port      порт воркера
  model     передаётся воркеру как --model
  timeout_s таймаут транскрипции (первая может ждать загрузку модели)

Протокол воркера: GET /health; POST /transcribe?sr=16000 (тело — raw int16 LE)
-> {"text": "..."}.
"""
import logging
import os
import subprocess
import time

import numpy as np

from server.config import CFG, resolve
from server.stt.base import STTEngine

log = logging.getLogger("saika.stt")


class ExternalEngine(STTEngine):
    kind = "buffered"

    _setup_started = False  # чтобы автопочинка не плодила окна установщика

    def __init__(self):
        self.proc = None

    @property
    def cfg(self):
        return CFG.get(f"stt.engines.{self.name}", {})

    def _url(self, path):
        return f"http://127.0.0.1:{self.cfg.get('port', 8766)}{path}"

    def _alive(self):
        import requests
        try:
            return requests.get(self._url("/health"), timeout=2).ok
        except Exception:
            return False

    def _venv_python(self):
        venv = resolve(self.cfg.get("venv", f".venv_{self.name}"))
        if os.name == "nt":
            return venv / "Scripts" / "python.exe"
        return venv / "bin" / "python"

    def load(self):
        if self._alive():
            return  # воркер уже работает (наш или с прошлого запуска)

        venv_py = self._venv_python()
        if not venv_py.exists():
            setup = resolve(self.cfg.get("setup", ""))
            if os.name == "nt" and setup.exists():
                # авто-установка: открываем окно (один раз), а сами честно
                # падаем — менеджер переключится на fallback и сообщит в UI
                if not type(self)._setup_started:
                    type(self)._setup_started = True
                    subprocess.Popen(["cmd", "/c", "start",
                                      f"Установка {self.name}", str(setup)])
                raise RuntimeError(
                    f"{self.name}: окружения ещё нет — открыл окно установки. "
                    f"Когда закончится, выбери движок «{self.name}» ещё раз.")
            raise RuntimeError(
                f"{self.name}: нет окружения ({venv_py.parent.parent}) — "
                f"запусти {self.cfg.get('setup', 'установщик')}")

        worker = resolve(self.cfg.get("worker"))
        cmd = [str(venv_py), str(worker),
               "--port", str(self.cfg.get("port", 8766))]
        if self.cfg.get("model"):
            cmd += ["--model", self.cfg["model"]]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log.info("%s: запускаю воркер: %s", self.name, " ".join(cmd))
        self.proc = subprocess.Popen(cmd, cwd=str(resolve(".")),
                                     creationflags=flags)

        deadline = time.time() + 60
        while time.time() < deadline:
            if self._alive():
                return
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"{self.name}: воркер упал при старте "
                    f"(код {self.proc.returncode}), см. logs/{self.name}_worker.log")
            time.sleep(1)
        raise RuntimeError(f"{self.name}: воркер не ответил за 60 с")

    def transcribe(self, pcm16, sample_rate):
        import requests
        self.load()
        r = requests.post(
            self._url(f"/transcribe?sr={sample_rate}"),
            data=np.asarray(pcm16, dtype=np.int16).tobytes(),
            headers={"Content-Type": "application/octet-stream"},
            timeout=self.cfg.get("timeout_s", 180))
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            raise RuntimeError(f"{self.name}: {data['error']}")
        return data.get("text", "").strip()

    def unload(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None

    def is_loaded(self):
        # наш воркер жив? (чужой с прошлого запуска ловится при load())
        return self.proc is not None and self.proc.poll() is None
