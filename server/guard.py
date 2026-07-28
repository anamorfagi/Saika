"""ЗАЩИТА ЖЕЛЕЗА И ЧЁРНЫЙ ЯЩИК (2026-07-28).

ПОВОД. У товарища владельца ПК с 12 ГБ видеопамяти ВЫКЛЮЧАЕТСЯ через
10–20 минут после запуска: гемма набирала до 11 ГБ, дальше либо блок
питания уходит в защиту от скачка тока, либо перегрев VRM/GPU — и система
гаснет без синего экрана и без единой строчки в логах. В этом и беда:
после жёсткого выключения НЕЧЕГО читать, диагноз ставится гаданием.

ДВЕ ЗАДАЧИ, ОБЕ ПРОСТЫЕ:

1. ЧЁРНЫЙ ЯЩИК. Раз в несколько секунд писать температуру, VRAM, ОЗУ и
   загрузку в файл С НЕМЕДЛЕННЫМ fsync — чтобы запись пережила внезапное
   отключение питания. После перезагрузки Сайка сама читает хвост прошлого
   ящика и говорит, что было в последние секунды: «GPU был 92°C» — это
   диагноз, а «комп просто вырубился» — это загадка.

2. ЗАЩИТА. Пороги по температуре и VRAM. Мягкий порог — предупреждение в
   интерфейс. Жёсткий — выгрузка всех моделей: минус сотни ватт нагрузки
   за секунду. Лучше остаться на минуту без мозгов, чем уронить весь ПК:
   жёсткое выключение под нагрузкой опасно и для диска, и для БП.

ПОЧЕМУ NVIDIA-SMI, А НЕ PYNVML. Утилита есть на любой машине с драйвером,
не требует пакета и не держит контекст в чужом процессе. Раз в 5 секунд
подпроцесс стоит миллисекунды — тут не место экономить на простоте.
"""
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

from server.config import CFG, ROOT

log = logging.getLogger("saika.guard")

BOX = ROOT / "logs" / "blackbox.jsonl"
BOX_PREV = ROOT / "logs" / "blackbox.prev.jsonl"
MAX_BOX_BYTES = 2 * 2**20        # ~2 МБ ≈ несколько часов записей


def _read_gpu():
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used,"
             "utilization.gpu,temperature.gpu,power.draw",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        row = [s.strip() for s in r.stdout.strip().splitlines()[0].split(",")]
        mt, mu, util, temp = (float(row[0]), float(row[1]),
                              float(row[2]), float(row[3]))
        try:
            power = float(row[4])
        except Exception:
            power = 0.0          # у некоторых карт power.draw «[N/A]»
        return {"vram_total_mb": mt, "vram_mb": mu, "util": util,
                "temp": temp, "power_w": power}
    except Exception:
        return None


def _read_sys():
    try:
        import psutil
        vm = psutil.virtual_memory()
        return {"ram_pct": vm.percent,
                "cpu_pct": psutil.cpu_percent(interval=None)}
    except Exception:
        return {}


class Guard:
    def __init__(self):
        self._thread = None
        self._stop = threading.Event()
        self.last = {}
        self.warn_state = ""     # "" | "warn" | "critical"
        self.trips = 0           # сколько раз срабатывала жёсткая защита
        self.on_warn = None      # callback(dict) — сообщение в интерфейс
        self.on_critical = None  # callback(dict) — выгрузить всё
        self.prev_tail = []      # что было в ящике ПЕРЕД прошлым выключением

    # ------------------------------------------------------------- пороги
    # Пороги нарочно консервативные и настраиваемые без правки кода.
    # 83°C для GPU — это уже троттлинг у большинства карт; 90+ — та зона,
    # где дешёвые БП и VRM начинают сдаваться. По VRAM критично не число
    # само по себе, а «впритык»: когда свободно меньше ~6%, драйвер начинает
    # свопить в ОЗУ, латентность скачет и потребление дёргается пиками.
    def _thresholds(self):
        return {
            "temp_warn": float(CFG.get("guard.temp_warn", 83)),
            "temp_crit": float(CFG.get("guard.temp_crit", 90)),
            "vram_warn": float(CFG.get("guard.vram_warn", 0.90)),
            "vram_crit": float(CFG.get("guard.vram_crit", 0.96)),
        }

    # ---------------------------------------------------------- чёрный ящик
    def _box_write(self, rec):
        try:
            BOX.parent.mkdir(parents=True, exist_ok=True)
            # ротация: ящик не должен съесть диск за месяц
            if BOX.exists() and BOX.stat().st_size > MAX_BOX_BYTES:
                BOX_PREV.unlink(missing_ok=True)
                BOX.rename(BOX_PREV)
            with open(BOX, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())   # ← ради этой строки ящик и существует
        except Exception:
            pass

    def read_prev_tail(self, n=6):
        """Последние записи ПРОШЛОГО запуска — что было перед выключением."""
        out = []
        try:
            if BOX.exists():
                lines = BOX.read_text(encoding="utf-8").strip().splitlines()
                out = [json.loads(x) for x in lines[-n:]]
        except Exception:
            pass
        return out

    def autopsy(self):
        """Диагноз по хвосту прошлого ящика — человеческим языком."""
        tail = self.prev_tail
        if not tail:
            return ""
        last = tail[-1]
        gap = time.time() - float(last.get("ts", 0))
        # сервер выключили штатно меньше двух минут назад — не о чем говорить
        if last.get("bye") or gap < 0:
            return ""
        t = self._thresholds()
        temp = float(last.get("temp") or 0)
        vt, vu = float(last.get("vram_total_mb") or 0), float(last.get("vram_mb") or 0)
        frac = (vu / vt) if vt else 0.0
        msgs = []
        if temp >= t["temp_crit"]:
            msgs.append(f"GPU был {temp:.0f}°C — похоже на защиту от перегрева")
        elif temp >= t["temp_warn"]:
            msgs.append(f"GPU грелся до {temp:.0f}°C")
        if frac >= t["vram_crit"]:
            msgs.append(f"видеопамять была забита на {frac * 100:.0f}% "
                        f"({vu:.0f} из {vt:.0f} МБ) — модель впритык, "
                        "потребление дёргалось пиками")
        elif frac >= t["vram_warn"]:
            msgs.append(f"видеопамять {frac * 100:.0f}%")
        if not msgs:
            return ""
        return ("Перед прошлым выключением: " + "; ".join(msgs) +
                ". Полная запись — logs/blackbox.prev.jsonl и blackbox.jsonl")

    # ------------------------------------------------------------- цикл
    def _loop(self):
        period = float(CFG.get("guard.period_s", 5))
        while not self._stop.wait(period):
            gpu = _read_gpu()
            rec = {"ts": round(time.time(), 1), **(_read_sys())}
            if gpu:
                rec.update(gpu)
            self.last = rec
            self._box_write(rec)
            if not gpu or not bool(CFG.get("guard.protect", True)):
                continue
            t = self._thresholds()
            frac = gpu["vram_mb"] / max(gpu["vram_total_mb"], 1)
            crit = gpu["temp"] >= t["temp_crit"] or frac >= t["vram_crit"]
            warn = gpu["temp"] >= t["temp_warn"] or frac >= t["vram_warn"]
            if crit and self.warn_state != "critical":
                self.warn_state = "critical"
                self.trips += 1
                log.warning("ЗАЩИТА: GPU %.0f°C, VRAM %.0f%% — выгружаю всё, "
                            "чтобы не уронить ПК", gpu["temp"], frac * 100)
                self._box_write({"ts": round(time.time(), 1), "trip": True,
                                 "temp": gpu["temp"], "vram_frac": round(frac, 3)})
                if self.on_critical:
                    try:
                        self.on_critical(dict(gpu, vram_frac=frac))
                    except Exception as e:
                        log.warning("Защита не смогла выгрузить: %s", e)
            elif warn and self.warn_state == "":
                self.warn_state = "warn"
                log.warning("Железо на пределе: GPU %.0f°C, VRAM %.0f%%",
                            gpu["temp"], frac * 100)
                if self.on_warn:
                    try:
                        self.on_warn(dict(gpu, vram_frac=frac))
                    except Exception:
                        pass
            elif not warn and not crit:
                self.warn_state = ""

    # ------------------------------------------------------------ управление
    def start(self, on_warn=None, on_critical=None):
        if self._thread is not None:
            return
        self.on_warn, self.on_critical = on_warn, on_critical
        # хвост прошлой жизни читаем ДО того, как начнём писать свою
        self.prev_tail = self.read_prev_tail()
        self._thread = threading.Thread(target=self._loop, name="guard",
                                        daemon=True)
        self._thread.start()
        log.info("Защита железа: слежу за температурой и VRAM (ящик %s)",
                 BOX.name)

    def stop(self):
        # прощальная запись: после штатного выключения диагноз не нужен
        self._box_write({"ts": round(time.time(), 1), "bye": True})
        self._stop.set()

    def status(self):
        return {"last": self.last, "state": self.warn_state,
                "trips": self.trips, "thresholds": self._thresholds(),
                "protect": bool(CFG.get("guard.protect", True)),
                "autopsy": self.autopsy()}


GUARD = Guard()
