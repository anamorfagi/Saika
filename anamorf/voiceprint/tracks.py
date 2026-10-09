# -*- coding: utf-8 -*-
"""ДОРОЖКИ ГОВОРЯЩИХ — онлайн-кластеризация по отпечаткам фраз (2026-08-31).

ПОВОД. Замер на ролике Snailkick: из 40 реплик 32 вообще без метки голоса,
и «Дорожки пересобраны: людей 1» при заведённых восьми. Виноват не
кодировщик (ReDimNet2 уже стоит и даёт 192-мерный отпечаток за 20 мс), а
логика заведения: старый auto_meet копит 22 незнакомых вектора, берёт их
ОБЩИЙ центр и заводит одного «Голос N» из всех, кто говорил. Двое, трое —
всё равно один блин.

ЧТО ДЕЛАЕМ ВМЕСТО. Классическая онлайн-кластеризация в духе diart, но на
уровне ФРАЗЫ, а не окна: каждый отпечаток ищет ближайший центроид; далеко
от всех — рождается НОВЫЙ кластер, а не вливается в среднее. Три ручки, как
у diart: link (примкнуть), merge (слить два кластера), и rho — минимальная
длительность фразы, которой доверяем двигать центроид.

ПРАВИЛО ТРЁХ СЕКУНД (GIST, 2025; и наш собственный симптом «один человек =
несколько облачков»). На односекундном куске ошибка отпечатка ~2.3% у ЛЮБОЙ
модели, на трёхсекундном — 0.8%. Поэтому кластер становится ЧЕЛОВЕКОМ
(получает имя «Голос N», цвет, место в реестре) только когда накопил ≥3 с
речи. До этого он «в очереди»: реплики уходят без имени, но с номером
дорожки — интерфейс может показать «?», а не врать именем.

Знакомые (реестр, паспорт владельца) решаются ДО этого модуля — сюда
приходят только те, кого реестр не узнал. Как только кластер подтверждён,
он заводится в реестр как автоголос, и дальше его узнаёт сам реестр.
"""
import threading
import time

import numpy as np

from anamorf.config import CFG

import logging
log = logging.getLogger("saika.tracks")


def _learn(evt: dict):
    """Событие учёбы — в чат. Отдельная функция, потому что дорожки не
    должны ничего знать ни про веб-сокеты, ни про интерфейс: они считают
    голоса. Кому рассказывать — забота того, кто их запустил."""
    try:
        from anamorf import voiceprint as _vp
        if _vp.S.sink:
            _vp.S.sink(evt)
    except Exception:
        pass


def _cfg(k, d):
    """Ручка дорожек. ДВА НАПИСАНИЯ (2026-08-31): владелец (и я) правил
    voiceprint.link_cos, а читалось voiceprint.tracks.link_cos — порог
    молча оставался прежним, и весь вечер калибровки ушёл в пустоту, при
    том что в журнале честно стояло «link 0.45». Теперь принимаем оба
    написания и приводим к числу: панель знобов отдаёт строки."""
    v = CFG.get("voiceprint.tracks." + k, None)
    if v is None:
        v = CFG.get("voiceprint." + k, None)
    if v is None:
        return d
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


class _Cluster:
    __slots__ = ("id", "vecs", "raw", "secs", "sec", "n", "ts", "name",
                 "visits", "born_ts")

    def __init__(self, cid, vec, sec, ts, raw=None):
        self.id = cid
        self.vecs = [vec]
        # СЫРОЙ ОТПЕЧАТОК ХРАНИМ ОТДЕЛЬНО. Сравниваем мы в отбелённом
        # пространстве (см. Tracks.observe), а в реестр голос должен
        # уехать в обычном — там лежат все прежние эталоны.
        self.raw = [raw if raw is not None else vec]
        self.secs = [sec]
        self.sec = sec
        self.n = 1
        self.ts = ts
        self.born_ts = ts
        # ВИЗИТЫ, А НЕ РЕПЛИКИ (05.09). На ролике ДНК завелось 14 голосов
        # при пяти живых людях, и у девяти из них в панели стояло
        # «2 образца · слышала 0 раз»: кластер рождался один раз посреди
        # смеха или наложения голосов, набирал за десять секунд свои две
        # реплики подряд, объявлялся человеком — и больше не совпадал
        # никогда. Две реплики подряд — это ОДИН эпизод звука, а не
        # знакомство. Человек тоже не запоминает голос с одной фразы: он
        # узнаёт его, когда услышит СНОВА, отдельно, потом. Считаем
        # возвраты: подряд идущие реплики — один визит.
        self.visits = 1
        self.name = ""          # пусто — ещё не человек

    def centroid(self):
        w = np.asarray(self.secs, np.float32)[:, None]
        c = (np.asarray(self.vecs, np.float32) * w).sum(0)
        n = float(np.linalg.norm(c))
        return c / n if n > 1e-9 else c

    def add(self, vec, sec, keep=40, ts=None, gap_s=20.0, raw=None):
        if ts is not None and (ts - self.ts) >= gap_s:
            self.visits += 1
        self.vecs.append(vec)
        self.raw.append(raw if raw is not None else vec)
        self.secs.append(sec)
        if len(self.vecs) > keep:
            self.vecs = self.vecs[-keep:]
            self.raw = self.raw[-keep:]
            self.secs = self.secs[-keep:]
        self.sec += sec
        self.n += 1


class Tracks:
    def __init__(self, to_registry: bool = True, tag: str = ""):
        # to_registry=False — считать честно, но НИЧЕГО не записывать в
        # общий реестр: так вторая (сравнительная) ветка не спорит с
        # основной за имена голосов
        self.to_registry = to_registry
        self.tag = tag
        self._lock = threading.Lock()
        self.clusters = []
        self.next_id = 1
        self.stat = {"seen": 0, "assigned": 0, "born": 0, "confirmed": 0,
                     "merged": 0, "short": 0}
        # ═══ ОБЩЕЕ ВЫЧИТАЕМ (05.09.2026) ═══
        # Замер на куске ролика 10:00–13:00 (tools/who_whiten.py):
        #   как есть                    медиана 0.918 · 10% 0.831 · мин 0.630
        #   минус среднее записи        медиана -0.022 · 10% -0.502 · мин -0.868
        # Косинусы между ЛЮБЫМИ двумя окнами тембра лежали в полосе
        # шириной 0.13 — все говорящие в одном тесном конусе, и никакой
        # порог их не делит: при 0.84 всё ещё один человек, при 0.88 уже
        # крошево из обрывков. Отсюда и «Голос 5» на всех подряд.
        # После вычитания среднего полоса раскрылась до 1.03 — в восемь
        # раз. Это ровно тот же приём, что вытащил карту звуков из шара
        # (docs/АТЛАС_ЗВУКА.md, причина 3): у всех записей одного канала
        # общая форма, и пока она внутри описания, различие тонет.
        # Среднее считаем по ходу, скользящим: комната и микрофон
        # меняются, а «общее» у них своё в каждой обстановке.
        self.mu = None
        self.mu_n = 0

    # ------------------------------------------------------------ ручки
    @property
    def link(self):      # примкнуть к кластеру, если косинус ≥
        return float(_cfg("link_cos", 0.45))

    @property
    def merge_cos(self):  # два кластера — один человек, если ≥
        return float(_cfg("merge_cos", 0.60))

    @property
    def rho(self):       # фраза короче — центроид не двигает
        return float(_cfg("rho_s", 0.8))

    @property
    def confirm_s(self):  # человек — с этой суммы секунд
        return float(_cfg("confirm_s", 3.0))

    @property
    def min_s(self):     # короче — вообще не смотрим
        return float(_cfg("min_s", 0.6))

    @property
    def confirm_n(self):  # реплик до объявления человеком
        return int(_cfg("confirm_n", 3))

    @property
    def confirm_visits(self):  # РАЗНЫХ заходов (см. _Cluster.visits)
        return int(_cfg("confirm_visits", 2))

    @property
    def visit_gap(self):  # пауза, после которой это уже другой заход
        return float(_cfg("visit_gap_s", 20.0))

    @property
    def whiten(self):
        # ВЫКЛЮЧЕНО ПО УМОЛЧАНИЮ, И ВОТ ПОЧЕМУ (05.09, вечер).
        # Замер, на котором строился вывод «конус шириной 0.13», был
        # сделан НЕ ТЕМ кодировщиком: отдельный процесс не поднял
        # ReDimNet2 и молча свалился на лёгкий запасной — в отчёте это
        # видно строкой «размерность 68» вместо честных 192. В живом
        # слухе тем временем стоят настоящие цифры: «ближайший cos=0.12»,
        # «0.33», «0.37» — то есть настоящий кодировщик людей РАЗДЕЛЯЕТ,
        # и лечить было нечего. Механизм оставлен и проверяем ручкой,
        # но включать его можно только после замера на ReDimNet2.
        return bool(_cfg("whiten", 0))

    # ------------------------------------------------------------ работа
    def observe(self, vec, sec: float, ts: float = None):
        """Один отпечаток фразы -> (имя или "", уверенность, id дорожки).

        Имя пустое, пока кластер не набрал confirm_s секунд."""
        ts = ts or time.time()
        v = np.asarray(vec, np.float32).ravel()
        n = float(np.linalg.norm(v))
        if n < 1e-9:
            return "", 0.0, 0
        v = v / n
        with self._lock:
            self.stat["seen"] += 1
            if sec < self.min_s:
                self.stat["short"] += 1
                return "", 0.0, 0
            raw = v
            if self.whiten:
                if self.mu is None:
                    self.mu = v.astype(np.float32).copy()
                    self.mu_n = 1
                else:
                    k = 1.0 / min(self.mu_n + 1, 200)
                    self.mu += (v - self.mu) * k
                    self.mu_n += 1
                # пока среднее не набралось, сравнивать в отбелённом
                # пространстве нельзя — оно ещё пляшет
                if self.mu_n >= int(_cfg("whiten_warm", 6)):
                    w = v - self.mu
                    wn = float(np.linalg.norm(w))
                    if wn > 1e-6:
                        v = w / wn
            best, bc = None, -1.0
            for c in self.clusters:
                s = float(np.dot(v, c.centroid()))
                if s > bc:
                    best, bc = c, s
            link = self.link
            # короткая фраза примыкает только к ОЧЕНЬ похожему и никогда не
            # рождает новый кластер — на секунде отпечаток слишком шаткий
            if sec < self.rho:
                if best is not None and bc >= link + 0.10:
                    self.stat["assigned"] += 1
                    return best.name, self._conf(bc, link), best.id
                # КОРОТКАЯ И НЕПОХОЖАЯ — БЕЗ ДОРОЖКИ (2026-09-06). Раньше сюда
                # отдавался id ближайшего кластера, даже когда сходство было
                # никакое; лента вешала чужой голос на облачко. Нет сходства —
                # нет дорожки, пусть решает высота тона.
                return "", 0.0, 0
            if best is not None and bc >= link:
                best.add(v, sec, ts=ts, gap_s=self.visit_gap, raw=raw)
                best.ts = ts
                self.stat["assigned"] += 1
                self._maybe_confirm(best)
                self._maybe_merge(best)
                return best.name, self._conf(bc, link), best.id
            c = _Cluster(self.next_id, v, sec, ts, raw=raw)
            self.next_id += 1
            self.clusters.append(c)
            self.stat["born"] += 1
            # КАЛИБРОВКА ПОРОГОВ ПО ЖИВЫМ ЦИФРАМ: пишем, насколько далеко
            # был ближайший, — по этим строкам и подбираются link/merge
            if best is not None:
                # КТО ИМЕННО ПИШЕТ (2026-08-31): на один кластер в журнале
                # выходило три одинаковые строки — основная ветка и обе
                # головы панели сравнения пишут одним логгером. Владелец
                # читал это как «за секунду выстрелило пять голосов».
                log.info("Дорожки%s: новый кластер %d (%.1fс) — ближайший %s "
                         "cos=%.2f < link %.2f",
                         (" [%s]" % self.tag) if self.tag else
                         ("" if self.to_registry else " [сравнение]"),
                         c.id, sec, best.name or ("#%d" % best.id), bc, link)
            self._maybe_confirm(c)
            return c.name, 0.0, c.id

    @staticmethod
    def _conf(s, link):
        return float(np.clip((s - link) / max(1.0 - link, 1e-6) * 2.0, 0.0, 1.0))

    def _maybe_confirm(self, c):
        if c.name:
            return
        _why = ""
        if c.sec < self.confirm_s:
            _why = "речи %.1f из %.1fс" % (c.sec, self.confirm_s)
        elif c.n < self.confirm_n:
            _why = "реплик %d из %d" % (c.n, self.confirm_n)
        elif (c.visits < self.confirm_visits
              and not (c.sec >= self.confirm_s * 4 and c.n >= self.confirm_n * 3)):
            # ЛИБО ВЕРНУЛСЯ, ЛИБО НАГОВОРИЛ МНОГО (05.09, вторая правка).
            # Требовать РАЗНЫХ заходов правильно против кластера-призрака,
            # родившегося на одном обрывке. Но на замере по куску ролика
            # это дало перегиб в другую сторону: человек говорит три
            # минуты подряд, это честно один заход — и он не признавался
            # человеком вовсе. Поэтому второй путь: много речи и много
            # реплик внутри одного захода — тоже доказательство. Обрывок
            # на две реплики под него не попадёт, а собеседник в кадре —
            # попадёт.
            _why = "заходов %d из %d и речи мало (%.1fс, %d реплик)" % (
                c.visits, self.confirm_visits, c.sec, c.n)
        if _why:
            return
        if not self.to_registry:
            c.name = "%sГолос %d" % (self.tag, c.id)
            self.stat["confirmed"] += 1
            return
        try:
            from anamorf import voiceprint as vp
            reg = vp.S.reg
            # имя — по свободному номеру реестра, чтобы не спорить с тем,
            # что там уже лежит
            k = 1
            while f"Голос {k}" in reg.speakers:
                k += 1
            name = f"Голос {k}"
            reg.enroll(name, np.asarray(c.raw, np.float32))
            reg.speakers[name]["auto"] = True
            reg.dirty = True
            c.name = name
            self.stat["confirmed"] += 1
            log.info("Дорожки%s: кластер %d стал человеком — «%s» "
                     "(%.1fс речи, %d реплик)",
                     (" [%s]" % self.tag) if self.tag else
                     ("" if self.to_registry else " [сравнение]"),
                     c.id, name, c.sec, c.n)
            # ═══ УЧЁБА ВИДНА ЧЕЛОВЕКУ (2026-09-05) ═══
            # Владелец: «пусть прямо в чате пишет, чтобы я видел, как она
            # обучается узнавать голоса». До этого вся учёба шла в лог,
            # то есть никуда: снаружи голоса просто однажды начинали
            # называться по именам, и понять, откуда взялся «Голос 3» и
            # почему он вдруг стал «Голосом 2», было нельзя.
            _learn({"type": "voice_learn", "what": "new",
                    "who": name, "sec": round(float(c.sec), 1), "n": int(c.n),
                    "text": "новый голос: «%s» (набрала %.1f с речи, "
                            "%d реплик — этого хватает, чтобы отличать)"
                            % (name, c.sec, c.n)})
        except Exception as e:
            log.debug("дорожки: не смогла завести голос: %s", e)

    def _maybe_merge(self, c):
        """Два подтверждённых кластера сошлись — сливаем в старший."""
        if not c.name:
            return
        cc = c.centroid()
        for o in list(self.clusters):
            if o is c or not o.name:
                continue
            if float(np.dot(cc, o.centroid())) >= self.merge_cos:
                keep, drop = (o, c) if o.id < c.id else (c, o)
                keep.vecs += drop.vecs
                keep.secs += drop.secs
                keep.sec += drop.sec
                keep.n += drop.n
                if self.to_registry:
                    try:
                        from anamorf import voiceprint as vp
                        vp.S.reg.rename(drop.name, keep.name, pin=False)
                    except Exception:
                        pass
                log.info("Дорожки: «%s» и «%s» — один человек, слила в «%s»",
                         drop.name, keep.name, keep.name)
                _learn({"type": "voice_learn", "what": "merge",
                        "who": keep.name, "from": drop.name,
                        "text": "поняла, что «%s» и «%s» — один человек; "
                                "оставила «%s»"
                                % (drop.name, keep.name, keep.name)})
                self.clusters.remove(drop)
                self.stat["merged"] += 1
                return

    def reset(self):
        with self._lock:
            self.clusters, self.next_id = [], 1

    def snapshot(self):
        with self._lock:
            return {"stat": dict(self.stat),
                    "clusters": [{"id": c.id, "name": c.name, "sec": round(c.sec, 1),
                                  "n": c.n} for c in self.clusters]}


TRACKS = Tracks()
