"""Общий помощник: видимый прогресс скачивания HF-репозитория в лог.

Проблема: huggingface_hub скачивает файлы через tqdm — прогресс-бар с
carriage-return перезаписью прямо в stderr. Это НЕ идёт через модуль logging,
поэтому в logs/*_worker.log его не видно вообще, а воркеры к тому же
запускаются без своего окна консоли (CREATE_NO_WINDOW, server/llm/*.py) —
даже живьём в консоли смотреть некуда. Итог: скачивание 16+ ГБ выглядит как
полное зависание процесса ("не видно процесс", жалоба 2026-07-22).

Вместо перехвата tqdm (хрупко, у разных версий huggingface_hub разное API)
просто раз в interval секунд меряем размер каталога HF-кэша для этого репо
и пишем через log.info() — грубо (не видно отдельные файлы), но работает
ОДИНАКОВО для from_pretrained/hf_hub_download/snapshot_download без единого
патча huggingface_hub, и переживёт обновление библиотеки.

Использование (внутри воркера, до вызова from_pretrained/hf_hub_download):

    from _hf_progress import DownloadProgressLogger
    with DownloadProgressLogger(log, ROOT / "models" / "hf", MODEL_REPO):
        model = AutoModelForCausalLM.from_pretrained(MODEL_REPO, ...)

Если скачивать нечего (модель уже в кэше) — поток просто не увидит роста
размера и красиво промолчит после первого же тика (см. _run: rest вывод
только если размер вообще изменился с прошлого замера ИЛИ это первый тик).
"""
import threading
import time
from pathlib import Path


def _dir_size(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _repo_cache_dir(hf_home: Path, repo_id: str) -> Path:
    # models--ORG--NAME — ровно так называет кэш-папки сам huggingface_hub
    name = "models--" + repo_id.replace("/", "--")
    return Path(hf_home) / "hub" / name


class DownloadProgressLogger:
    """Фоновый поток-таймер: пишет в лог размер каталога кэша репозитория и
    скорость прироста с прошлого замера. Не бросает исключений — сбой
    измерения (например, каталог ещё не создан) просто пропускает тик.
    """

    def __init__(self, log, hf_home, repo_id, label=None, interval=10):
        self.log = log
        self.hf_home = Path(hf_home)
        self.repo_id = repo_id
        self.label = label or repo_id
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None

    def _run(self):
        d = _repo_cache_dir(self.hf_home, self.repo_id)
        prev = _dir_size(d)
        prev_t = time.monotonic()
        first = True
        while not self._stop.wait(self.interval):
            cur = _dir_size(d)
            now = time.monotonic()
            dt = max(now - prev_t, 0.001)
            speed_mb_s = (cur - prev) / dt / (1024 * 1024)
            if cur != prev or first:
                self.log.info(
                    "Скачивание %s: ~%.2f ГБ на диске (~%.1f МБ/с)",
                    self.label, cur / (1024 ** 3), max(speed_mb_s, 0))
            prev, prev_t = cur, now
            first = False

    def __enter__(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        return False
