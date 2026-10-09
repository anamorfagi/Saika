"""Видеопамять — цифрами из драйвера, а не на глаз.

На Windows (WDDM) драйвер не отдаёт память по процессам ([N/A]), поэтому
меряем общий расход до и после действия: разница и есть доказательство.
"""
from __future__ import annotations

import subprocess
import time


def vram_mb() -> tuple[int | None, int | None]:
    """(занято, всего) в МБ; (None, None), если nvidia-smi нет."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000).stdout.strip().splitlines()[0]
        used, total = (int(x.strip()) for x in out.split(","))
        return used, total
    except Exception:
        return None, None


def settle_used_mb(max_wait_s: float = 8.0) -> int | None:
    """Подождать, пока драйвер реально отпустит память (после убийства
    процесса цифра падает не мгновенно), и вернуть установившееся значение."""
    last, _ = vram_mb()
    t0 = time.time()
    while time.time() - t0 < max_wait_s:
        time.sleep(1.0)
        cur, _ = vram_mb()
        if cur is None or last is None or abs(cur - last) < 64:
            return cur
        last = cur
    return last
