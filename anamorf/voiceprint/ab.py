# -*- coding: utf-8 -*-
"""СРАВНЕНИЕ БОК О БОК: новый кодировщик против старого (2026-08-31).

ПОВОД — просьба владельца: «слева новая технология и её определение
голосов, справа старая и её голоса». Одни и те же фразы, две независимые
головы: ReDimNet2 и ECAPA, у каждой своя кластеризация. Никаких общих
состояний — иначе сравнение врёт.

ПОЧЕМУ ЭТО ВООБЩЕ ВОЗМОЖНО ЧЕСТНО. Оба кодировщика дают по 192 числа, но
из разных пространств: косинусы между ними несравнимы, и пороги у каждого
свои. Поэтому сравниваем не косинусы, а РЕЗУЛЬТАТ: сколько людей завела
каждая, сколько реплик получили метку, держится ли один человек одним
голосом через весь ролик.

СТОРОНА B НИЧЕГО НЕ ПИШЕТ. Реестр голосов, память, лента — всё это
принадлежит основной ветке. Сравнительная считает свои кластеры «в
стороне» (Tracks(to_registry=False)) и живёт только в этой панели.

Гейт: voiceprint.ab_compare. Выключено — не тратим GPU впустую.
"""
import logging
import threading
import time

import numpy as np

from anamorf.config import CFG

log = logging.getLogger("saika.ab")


class Side:
    """Одна голова сравнения: свой кодировщик + своя кластеризация."""

    PALETTE = ["#4dd0e1", "#ffb74d", "#ba68c8", "#81c784", "#f06292",
               "#7986cb", "#ffd54f", "#4db6ac", "#ff8a65", "#9575cd"]

    def __init__(self, backend: str, tag: str):
        self.backend = backend
        self.tag = tag
        self.enc = None
        self.tracks = None
        self.ready = False
        self.error = ""
        self._tried = False
        # сырые отпечатки для картинки: (вектор, id кластера, время)
        self.pts = []
        self.pts_max = 600

    def warm(self):
        """ПОДЪЁМ ГОЛОВЫ — ТОЛЬКО В ФОНЕ (2026-08-31).

        Было: warm() звали прямо из observe(), то есть из потока слуха, и
        ещё под общим замком. ECAPA тянется через speechbrain и может
        висеть минутами (сеть, кэш HF). Живой случай: 20:48:43 сторона
        «старая» полезла грузиться — и слух встал целиком до конца ролика,
        ни одной фразы больше не разобрано, /api/ab не отвечал совсем.

        Теперь warm() только ставит задачу в отдельный поток и сразу
        отдаёт управление. Пока голова не поднялась, observe() возвращает
        None — сторона просто пустая, а слух идёт своим темпом."""
        if self._tried:
            return self.ready
        self._tried = True
        threading.Thread(target=self._warm_now, daemon=True,
                         name="ab-warm-" + (self.tag or self.backend)).start()
        return False

    def _warm_now(self):
        try:
            from anamorf.voiceprint.encoder import Encoder
            from anamorf.voiceprint.tracks import Tracks
            e = Encoder()
            e.force = self.backend
            got = e.warmup()
            if got != self.backend:
                raise RuntimeError("поднялся %s вместо %s" % (got, self.backend))
            self.enc = e
            self.tracks = Tracks(to_registry=False, tag=self.tag)
            self.ready = True
            log.info("Сравнение: сторона «%s» готова (%s, %d измерений)",
                     self.tag or self.backend, e.backend, e.dim)
        except Exception as ex:
            self.error = str(ex)[:160]
            log.warning("Сравнение: сторона «%s» не поднялась: %s",
                        self.backend, self.error)

    def observe(self, pcm16, sec: float):
        if not self.ready:
            return None
        t0 = time.monotonic()
        v, _f0 = self.enc.encode(pcm16)
        self.last_v = np.asarray(v, np.float32).ravel()
        name, conf, tid = self.tracks.observe(v, sec)
        self.pts.append((np.asarray(v, np.float32), tid, time.time()))
        del self.pts[:-self.pts_max]
        return {"enc": self.backend, "name": name, "conf": round(conf, 2),
                "track": tid, "ms": round((time.monotonic() - t0) * 1000)}

    def cloud(self):
        """Облако точек в 2D для панели.

        Проекция считается по СВОИМ векторам этой стороны и только по ним:
        пространства у ECAPA и ReDimNet2 разные, общая проекция была бы
        враньём. Обычный PCA по центрированным данным — он честно
        показывает, насколько далеко разошлись кластеры, и не выдумывает
        структуру, которой нет (в отличие от UMAP, который красиво
        разводит даже случайный шум)."""
        if len(self.pts) < 3:
            return {"pts": [], "names": {}, "colors": {}}
        X = np.stack([p[0] for p in self.pts])
        Z = X - X.mean(axis=0)
        try:
            _u, _s, vt = np.linalg.svd(Z, full_matrices=False)
            P = Z @ vt[:2].T
        except Exception:
            P = Z[:, :2]
        # растяжка по 2..98 перцентилям: одиночный выброс не должен
        # сплющивать всё облако в точку (тот же урок, что и в projector)
        lo = np.percentile(P, 2, axis=0)
        hi = np.percentile(P, 98, axis=0)
        span = np.maximum(hi - lo, 1e-6)
        P = 2.0 * (P - lo) / span - 1.0
        names, colors = {}, {}
        for c in (self.tracks.clusters if self.tracks else []):
            names[c.id] = c.name or ("?%d" % c.id)
            colors[c.id] = self.PALETTE[(c.id - 1) % len(self.PALETTE)]
        now = time.time()
        pts = [{"x": round(float(P[i][0]), 4), "y": round(float(P[i][1]), 4),
                "c": int(self.pts[i][1]), "age": round(now - self.pts[i][2], 1)}
               for i in range(len(self.pts))]
        return {"pts": pts, "names": names, "colors": colors}


class AB:
    def __init__(self):
        self._lock = threading.Lock()
        self.a = Side("redimnet", "")      # новая — слева
        self.b = Side("ecapa", "E")        # старая — справа
        self.log = []                      # последние сравнения, для панели
        # СТАРУЮ ГОЛОВУ НЕ ПОДНИМАЕМ БЕЗ СПРОСА. Владелец просил довести
        # новую, а не кормить GPU обеими. ECAPA просыпается только когда
        # в панели нажали «сравнить со старой» (/api/ab {"old":true}).
        self.want_old = False

    def enabled(self) -> bool:
        return bool(CFG.get("voiceprint.ab_compare", False))

    def observe(self, pcm16, sec: float, text: str = ""):
        """Одну фразу — обеим головам. Возвращает {'a':…, 'b':…} или None."""
        if not self.enabled():
            return None
        # ЗАМОК — ТОЛЬКО ВОКРУГ ЗАПИСИ. Кодирование идёт без него: иначе
        # панель (snapshot) и слух дерутся за один замок, и кто-то ждёт.
        self.a.warm()
        if self.want_old:
            self.b.warm()
        try:
            ra = self.a.observe(pcm16, sec)
            rb = self.b.observe(pcm16, sec) if self.want_old else None
        except Exception as e:
            log.debug("сравнение споткнулось: %s", e)
            return None
        if not (ra or rb):
            return None
        # ПРОВЕРКА ЧЕСТНОСТИ СРАВНЕНИЯ (2026-08-31). Владелец: «мне
        # кажется, они визуально прям один в один». Списки двух голов
        # совпадали до десятой доли секунды, и это законный повод не
        # верить панели. Раз в десять фраз меряем косинус МЕЖДУ векторами
        # двух голов на одной и той же фразе. Если головы разные, число
        # будет случайным (пространства несравнимы) и уж точно не 1.0;
        # единица означала бы, что справа считает та же самая сеть.
        try:
            if ra and rb and len(self.log) % 10 == 0:
                va, vb = self.a.last_v, self.b.last_v
                log.info("Сравнение: головы дали %s и %s, "
                         "косинус между их векторами %.3f "
                         "(1.000 = это одна и та же сеть)",
                         self.a.enc.backend, self.b.enc.backend,
                         float(np.dot(va, vb)))
        except Exception as e:
            log.debug("сверка голов: %s", e)
        with self._lock:
            row = {"t": time.time(), "sec": round(sec, 1),
                   "text": (text or "")[:120], "a": ra, "b": rb}
            self.log.append(row)
            del self.log[:-200]
            return {"a": ra, "b": rb}

    def snapshot(self):
        with self._lock:
            def side(s):
                if not s.ready:
                    return {"ready": False, "error": s.error,
                            "warming": bool(s._tried and not s.error),
                            "backend": s.backend}
                sn = s.tracks.snapshot()
                return {"ready": True, "backend": s.backend,
                        "dim": getattr(s.enc, "dim", 0),
                        "clusters": sn["clusters"], "stat": sn["stat"],
                        "cloud": s.cloud()}
            return {"on": self.enabled(), "old_on": self.want_old,
                    "new": side(self.a), "old": side(self.b),
                    "log": self.log[-80:]}

    def __live_after__(self):
        """Починить саму себя после живой правки кода (2026-08-31).

        Живой объект переживает правку вместе со своим состоянием — и это
        правильно, но состояние бывает битым именно из-за той ошибки,
        которую правка и чинит. Здесь ровно этот случай: старый прогрев
        ECAPA вставал намертво ПОД ЗАМКОМ, и замок оставался захваченным
        навсегда. Новый код на нём же и встал бы. Поэтому: замок делаем
        свежий, а голову, которая ушла греться и не вернулась, помечаем
        непопробованной — пусть попробует ещё раз, теперь уже в фоне.

        Хук вызывает anamorf/live.py сразу после перепрошивки класса.
        Благодаря ему такие правки доезжают без перезапуска приложения."""
        self._lock = threading.Lock()
        if not hasattr(self, "want_old"):
            self.want_old = False
        for sd in (self.a, self.b):
            if getattr(sd, "_tried", False) and not sd.ready and not sd.error:
                sd._tried = False          # зависла на прогреве — дать шанс
        log.info("Сравнение: подхватило правку на ходу, замок пересобран")

    def reset(self):
        with self._lock:
            for s in (self.a, self.b):
                if s.tracks:
                    s.tracks.reset()
                s.pts = []
            self.log = []


AB_COMPARE = AB()
