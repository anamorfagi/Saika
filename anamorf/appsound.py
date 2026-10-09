# -*- coding: utf-8 -*-
"""КТО ИЗДАЁТ ЗВУК — ПО ПРИЛОЖЕНИЯМ WINDOWS (2026-09-06).

Идея владельца, дословно: «сейчас чувак явно пиздит из дискорда — ты бы
мог предположить, из какого приложения и какая частота звука, и
гарантированно записать его слова… нам нужно больше умных алгоритмов
ПРЕДОПРЕДЕЛЕНИЯ на слабом железе».

Windows ведёт отдельную звуковую сессию на каждое приложение и отдаёт по
ней пиковый уровень (IAudioMeterInformation). Опрашиваем все сессии десять
раз в секунду и помним последние минуты: для любого куска речи [t0, t1]
можно сказать, ЧЬЯ это была громкость — Discord, браузер, плеер. Это
не догадка по тембру, а измерение: звук физически шёл из этого процесса.

Что это даёт слуху:
  • подпись источника у каждой реплики («из Discord», «из браузера»);
  • дорожки голосов не смешиваются между приложениями — друг из дискорда
    и женщина из ролика никогда не станут одним «Голосом N»;
  • когда в дискорде говорит один собеседник, его личность известна по
    источнику, даже если он нарочно меняет голос — тембр тогда лишь
    добавляет пометку «голос изменён».

Цена: COM-опрос ~1 мс на сессию, поток спит 100 мс. Нет pycaw / не Windows —
модуль молча выключен, who_played() отдаёт «».
"""
import collections
import logging
import threading
import time

log = logging.getLogger("saika.appsound")

_RING = collections.deque(maxlen=6000)     # (monotonic, {app: peak}) — 10 минут
_LOCK = threading.Lock()
STATE = {"on": False, "err": "", "apps": {}, "ts": 0.0}
_NICE = {"discord": "Discord", "chrome": "Chrome", "msedge": "Edge",
         "yandex": "Яндекс", "browser": "Яндекс", "firefox": "Firefox",
         "mpc-hc64": "MPC-HC", "mpc-hc": "MPC-HC", "vlc": "VLC",
         "telegram": "Telegram", "spotify": "Spotify", "steam": "Steam",
         "python": "Сайка", "obs64": "OBS", "zoom": "Zoom", "skype": "Skype"}


def nice(proc: str) -> str:
    p = (proc or "").lower().replace(".exe", "")
    for k, v in _NICE.items():
        if k in p:
            return v
    return p or "?"


def _loop():
    try:
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
    except Exception as e:
        STATE["err"] = "нет pycaw: %s" % e
        log.info("Звук по приложениям выключен (%s)", STATE["err"])
        return
    STATE["on"] = True
    sessions, last_enum = [], 0.0
    while True:
        try:
            now = time.monotonic()
            if now - last_enum > 2.0:          # список сессий меняется редко
                try:
                    sessions = []
                    for s in AudioUtilities.GetAllSessions():
                        try:
                            name = s.Process.name() if s.Process else (s.DisplayName or "")
                            meter = s._ctl.QueryInterface(IAudioMeterInformation)
                            sessions.append((nice(name), meter))
                        except Exception:
                            continue
                except Exception as e:
                    STATE["err"] = str(e)[:120]
                last_enum = now
            row = {}
            for name, meter in sessions:
                try:
                    pk = float(meter.GetPeakValue())
                except Exception:
                    continue
                if pk > 0.002 and name != "Сайка":
                    row[name] = max(row.get(name, 0.0), pk)
            with _LOCK:
                _RING.append((now, row))
            STATE["apps"] = row
            STATE["ts"] = time.time()
        except Exception as e:
            STATE["err"] = str(e)[:120]
        time.sleep(0.1)


def start():
    if STATE.get("thread"):
        return
    t = threading.Thread(target=_loop, daemon=True, name="appsound")
    STATE["thread"] = True
    t.start()


def who_played(t0_mono: float, t1_mono: float):
    """Кто звучал в окне [t0, t1] по monotonic-времени.
    -> (приложение, доля его громкости 0..1, {приложение: сумма пиков})

    ЧЕСТНОСТЬ (2026-09-06, замер): pycaw через QueryInterface на сессии
    отдал ОДИНАКОВЫЕ пики для Chrome и Discord — это уровень устройства,
    а не приложения. Пока не найден настоящий сессионный счётчик, подпись
    источника выключена (appsound.enabled=false): врать «из Discord» хуже,
    чем молчать."""
    try:
        from anamorf.config import CFG
        if not CFG.get("appsound.enabled", False):
            return "", 0.0, {}
    except Exception:
        pass
    acc = {}
    with _LOCK:
        for ts, row in _RING:
            if t0_mono <= ts <= t1_mono:
                for k, v in row.items():
                    acc[k] = acc.get(k, 0.0) + v
    if not acc:
        return "", 0.0, {}
    tot = sum(acc.values()) or 1.0
    best = max(acc, key=acc.get)
    return best, acc[best] / tot, {k: round(v, 2) for k, v in acc.items()}


def status():
    return {"on": STATE["on"], "err": STATE["err"], "apps": STATE["apps"]}
