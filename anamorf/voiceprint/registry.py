"""Кто это говорит + память облака точек (2026-07-28).

ДВЕ ЗАДАЧИ, которые часто путают:
- ДИАРИЗАЦИЯ — «сколько тут людей и кто когда говорил» при НЕизвестном
  составе. Кластеризация на лету, задача до сих пор исследовательская.
- ИДЕНТИФИКАЦИЯ — «это Виталий или нет» при известном списке. Косинус с
  эталоном, тридцать строк кода, работает надёжно.
Дома у Сайки состав известен (владелец плюс пара регуляров), поэтому здесь
идентификация. Незнакомый голос не разбирается на личности — он просто
«не наш», и на экране падает в пустоту между территориями.

ЭТАЛОН — не одна запись, а СРЕДНЕЕ по многим кускам речи (центроид). Один
кусок ловит одну интонацию; человек за день звучит десятком разных способов,
и центроид это усредняет. Плюс храним разброс: по нему считается, насколько
уверенно опознан голос, — это то самое кольцо вокруг точки в интерфейсе.

ХРАНИМ ВЕКТОРЫ, А НЕ КООРДИНАТЫ. Проекция переобучается (см. projector.py),
и при смене ступени всё облако пересчитывается заново. Координаты на диске
протухли бы в первый же вечер.
"""
import json
import logging
import time

import numpy as np

from anamorf.config import CFG, ROOT
from anamorf.voiceprint.encoder import cosine

log = logging.getLogger("saika.voiceprint")

DIR = ROOT / "data" / "voiceprint"
MAX_POINTS = 4000          # кольцо истории облака (4000 x 192 float32 ≈ 3МБ)
MAX_ENROLL = 120           # эталонных векторов на человека

# Цвета территорий. Владелец всегда первый и всегда бирюзовый — под палитру
# интерфейса; дальше по кругу.
# ЗОЛОТО (#ffd54f) ИЗ РОТАЦИИ УБРАНО (2026-07-28, решение владельца): это
# цвет ГОЛОСА СОЗДАТЕЛЯ, и только его. Обычный голос не может получить его
# ни автоматически, ни руками — иначе метка «создатель» перестаёт читаться.
OWNER_COLOR = "#ffd54f"
PALETTE = ["#4dd0e1", "#ffb74d", "#ba68c8", "#81c784",
           "#f06292", "#9fa8da", "#4db6ac", "#ff8a65"]


class Registry:
    def __init__(self):
        self.speakers: dict = {}    # имя -> {"embs": (n,dim), "color": str}
        self.pts = None             # (n, dim) векторы истории
        self.pts_who: list = []     # имя говорившего для каждой точки
        self.pts_ts: list = []
        self.dirty = False
        self._adapt_ts: dict = {}   # когда эталон в последний раз дописывался
        # ЖИВАЯ СТАТИСТИКА на карточку голоса в интерфейсе (2026-07-28):
        # когда слышала последний раз, сколько кусков насчитала, в каком
        # диапазоне тона говорит. Считается по факту узнавания, не при
        # записи, — поэтому показывает человека в жизни, а не на «пробе».
        self.stat: dict = {}        # имя -> {last, n, plo, phi}
        # скелет: имя -> {hz:[], tract:[], rate:[]} последние 64
        self.skel: dict = {}
        self.load()

    # ------------------------------------------------------------ хранение
    def load(self):
        try:
            meta_p, npz_p = DIR / "meta.json", DIR / "state.npz"
            if not meta_p.exists() or not npz_p.exists():
                return
            meta = json.loads(meta_p.read_text("utf-8"))
            z = np.load(npz_p, allow_pickle=False)
            for name in meta.get("speakers", []):
                key = "sp_" + _safe(name)
                if key in z:
                    self.speakers[name] = {
                        "embs": z[key].astype(np.float32), "_c": None,
                        "color": meta.get("colors", {}).get(name, PALETTE[0]),
                        "pinned": bool(meta.get("pinned", {}).get(name, False)),
                        "auto": bool(meta.get("auto", {}).get(name, False)),
                        "owner": bool(meta.get("owner", {}).get(name, False)),
                        "hyp": dict(meta.get("hyp", {}).get(name, {}))}
            self.stat = dict(meta.get("stat", {}))
            self.skel = dict(meta.get("skel", {}))
            if "pts" in z and len(z["pts"]):
                self.pts = z["pts"].astype(np.float32)
                self.pts_who = list(meta.get("pts_who", []))
                self.pts_ts = list(meta.get("pts_ts", []))
            # размерность энкодера могла смениться (лёгкий <-> ECAPA) —
            # мешать векторы разной природы нельзя, начинаем с чистого листа
            self._drop_mismatched()
            log.info("Отпечаток голоса: загружено голосов %d, точек %d",
                     len(self.speakers), 0 if self.pts is None else len(self.pts))
        except Exception as e:
            log.warning("Не смогла прочитать память отпечатков (%s) — "
                        "начинаю с чистого листа", e)

    def _drop_mismatched(self):
        dims = {v["embs"].shape[1] for v in self.speakers.values() if len(v["embs"])}
        if self.pts is not None:
            dims.add(self.pts.shape[1])
        if len(dims) > 1:
            log.warning("В памяти отпечатков смешались векторы разной длины "
                        "%s — чищу (сменился движок энкодера)", sorted(dims))
            self.speakers, self.pts = {}, None
            self.pts_who, self.pts_ts = [], []

    def save(self):
        if not self.dirty:
            return
        try:
            DIR.mkdir(parents=True, exist_ok=True)
            arrays, colors, pinned, auto, hyp = {}, {}, {}, {}, {}
            owner = {}
            for name, v in self.speakers.items():
                arrays["sp_" + _safe(name)] = v["embs"]
                colors[name] = v["color"]
                pinned[name] = bool(v.get("pinned"))
                auto[name] = bool(v.get("auto"))
                owner[name] = bool(v.get("owner"))
                hyp[name] = {k: round(float(x), 2)
                             for k, x in (v.get("hyp") or {}).items()}
            if self.pts is not None and len(self.pts):
                arrays["pts"] = self.pts
            np.savez_compressed(DIR / "state.npz", **arrays)
            (DIR / "meta.json").write_text(json.dumps({
                "speakers": list(self.speakers.keys()), "colors": colors,
                "stat": self.stat, "skel": self.skel,
                "pinned": pinned, "auto": auto, "hyp": hyp,
                "owner": owner,
                "pts_who": self.pts_who, "pts_ts": self.pts_ts,
                "saved": time.time()}, ensure_ascii=False), "utf-8")
            self.dirty = False
        except Exception as e:
            log.warning("Не смогла сохранить отпечатки: %s", e)

    # ------------------------------------------------------------- голоса
    # ── имена: догадки, закрепление, переименование ──────────────────────
    def note_hyp(self, name: str, guess: str, w: float):
        """Копим догадки об имени голоса. Возвращает новое имя, если пора
        переименовать, иначе пусто.

        ПОЧЕМУ НЕ «УСЛЫШАЛА ИМЯ — НАЗВАЛА»: одно совпадение почти всегда
        случайность, в разговоре имена звучат про третьих лиц, про кота и про
        героя сериала. Держим счёт по каждому кандидату и переименовываем,
        только когда лидер набрал вес И оторвался от второго места вдвое.
        Метка до этого висит как предположение — её видно в интерфейсе с
        процентом уверенности."""
        v = self.speakers.get(name)
        if v is None or v.get("pinned"):
            return ""          # имя задано руками — догадки его не трогают
        h = v.setdefault("hyp", {})
        h[guess] = float(h.get(guess, 0.0)) + float(w)
        self.dirty = True
        top = sorted(h.items(), key=lambda kv: -kv[1])
        best, bw = top[0]
        second = top[1][1] if len(top) > 1 else 0.0
        need = float(CFG.get("voiceprint.name_weight", 6.0))
        if best != name and bw >= need and bw >= second * 2.0:
            return best
        return ""

    def name_guess(self, name: str):
        """-> (кандидат, уверенность 0..1) для показа плавающей метки."""
        v = self.speakers.get(name) or {}
        if v.get("pinned"):
            return "", 1.0
        h = v.get("hyp") or {}
        if not h:
            return "", 0.0
        top = sorted(h.items(), key=lambda kv: -kv[1])
        best, bw = top[0]
        second = top[1][1] if len(top) > 1 else 0.0
        need = float(CFG.get("voiceprint.name_weight", 6.0))
        conf = min(1.0, (bw / need) * (1.0 if not second else
                                       min(1.0, bw / (second * 2.0))))
        return (best if best != name else ""), round(float(conf), 2)

    def rename(self, old: str, new: str, pin: bool = True):
        """Переименовать голос. pin=True — прибить имя: дальше она только
        учится узнавать этот голос, но имя менять не смеет."""
        new = (new or "").strip()[:32]
        if not new or old not in self.speakers:
            return {"ok": False, "error": "нет такого голоса"}
        v = self.speakers.pop(old)
        if new in self.speakers:      # слить с существующим
            cur = self.speakers[new]
            if cur["embs"].shape[1] == v["embs"].shape[1]:
                cur["embs"] = np.vstack([cur["embs"], v["embs"]])[-MAX_ENROLL:]
                cur["_c"] = None
        else:
            v["_c"] = None
            v["pinned"] = bool(pin)
            v["hyp"] = {}
            v["auto"] = False
            self.speakers[new] = v
        if old in self.stat:
            self.stat[new] = self.stat.pop(old)
        self.pts_who = [(new if w == old else w) for w in self.pts_who]
        self._adapt_ts.pop(old, None)
        self.dirty = True
        return {"ok": True, "name": new}

    def owner_name(self) -> str:
        for n, v in self.speakers.items():
            if v.get("owner"):
                return n
        return ""

    def set_color(self, name: str, color: str):
        """Перекрасить голос. Золото не отдаём никому: это цвет создателя."""
        import re as _re
        v = self.speakers.get(name)
        if v is None:
            return {"ok": False, "error": "нет такого голоса"}
        color = (color or "").strip().lower()
        if not _re.fullmatch(r"#[0-9a-f]{6}", color):
            return {"ok": False, "error": "цвет должен быть вида #rrggbb"}
        if color == OWNER_COLOR and not v.get("owner"):
            return {"ok": False, "error": "золотой занят — это цвет создателя"}
        v["color"] = color
        self.dirty = True
        return {"ok": True, "name": name, "color": color}

    def set_owner(self, name: str):
        """Пометить голос создателем: золото, закреплён, единственный."""
        if name not in self.speakers:
            return {"ok": False, "error": "нет такого голоса"}
        for n, v in self.speakers.items():
            was = v.get("owner")
            v["owner"] = (n == name)
            if was and n != name and v.get("color") == OWNER_COLOR:
                v["color"] = PALETTE[0]
        v = self.speakers[name]
        v["pinned"] = True
        v["auto"] = False
        v["color"] = OWNER_COLOR
        self.dirty = True
        return {"ok": True, "name": name}

    def snapshot(self) -> dict:
        """Снимок состояния для отмены (2026-08-13, просьба владельца:
        «сохрани механику отмены Ctrl+Z»). Слияние необратимо по своей
        природе — векторы двух голосов становятся общими. Значит откат
        возможен только через копию ДО: держим её в памяти, недолго и
        дёшево (сотни векторов по 192 числа — единицы мегабайт)."""
        import copy
        return {
            "speakers": {k: {**v, "embs": v["embs"].copy()}
                         for k, v in self.speakers.items()},
            "stat": copy.deepcopy(self.stat),
        }

    def restore(self, snap: dict) -> bool:
        if not snap or not snap.get("speakers"):
            return False
        self.speakers = {k: {**v, "embs": v["embs"].copy()}
                         for k, v in snap["speakers"].items()}
        self.stat = dict(snap.get("stat") or {})
        self.dirty = True
        return True

    def merge(self, src: str, dst: str):
        """Слить два голоса в один (2026-07-28, идея владельца).

        ПОВОД. Тембр одного человека гуляет: сел, встал, отвернулся от
        микрофона, начал дурачиться — и она честно знакомится с «новым»
        голосом. Формально она права: похожесть ниже порога. Но человек-то
        ЗНАЕТ, что это он, и это знание дороже любого порога.

        ПОЧЕМУ ЭТО НЕ ПРОСТО СКЛЕЙКА СПИСКОВ. Эталон после слияния
        становится ШИРЕ — в нём теперь два разных состояния одного голоса.
        Разброс sd вырастет сам, порог опустится, и в следующий раз она
        узнает его в обоих состояниях без переучивания. То есть слияние —
        это не косметика в списке, это настоящее обучение, и самое дешёвое
        из возможных: человек уже сделал всю разметку одним движением.

        Имя-приёмник закрепляется: раз владелец руками сказал «это один и
        тот же», спорить с ним она не будет."""
        src, dst = (src or "").strip(), (dst or "").strip()
        if src == dst or src not in self.speakers or dst not in self.speakers:
            return {"ok": False, "error": "нечего сливать"}
        a, b = self.speakers[dst], self.speakers[src]
        if a["embs"].shape[1] != b["embs"].shape[1]:
            return {"ok": False, "error": "векторы разной длины "
                                         "(сменился движок) — сначала переучи"}
        # берём из обоих ПОРОВНУ: иначе голос, которого наслушалась больше,
        # заглушит второй, и слияние окажется бессмысленным
        half = max(1, MAX_ENROLL // 2)
        a["embs"] = np.vstack([a["embs"][-half:], b["embs"][-half:]])
        a["_c"] = None
        a["pinned"] = True
        a["auto"] = False
        # догадки об имени складываем: обе половины могли слышать одно имя
        hyp = dict(a.get("hyp") or {})
        for k, w in (b.get("hyp") or {}).items():
            hyp[k] = hyp.get(k, 0.0) + float(w)
        a["hyp"] = hyp
        sa = self.stat.get(dst) or {"last": 0.0, "n": 0, "plo": 0.0, "phi": 0.0}
        sb = self.stat.pop(src, None) or {}
        sa["n"] = int(sa.get("n", 0)) + int(sb.get("n", 0))
        sa["last"] = max(float(sa.get("last", 0)), float(sb.get("last", 0)))
        for lo_hi, fn in (("plo", min), ("phi", max)):
            vals = [x for x in (sa.get(lo_hi), sb.get(lo_hi)) if x]
            sa[lo_hi] = fn(vals) if vals else 0.0
        self.stat[dst] = sa
        self.speakers.pop(src, None)
        # облако на карте перекрашиваем: точки исчезнувшего голоса теперь его
        self.pts_who = [(dst if w == src else w) for w in self.pts_who]
        self._adapt_ts.pop(src, None)
        self.dirty = True
        return {"ok": True, "name": dst, "vectors": int(len(a["embs"]))}

    def enroll(self, name: str, embs, color: str = ""):
        """Добавить эталонных векторов. Повторный вызов с тем же именем
        ДОПОЛНЯЕТ эталон, а не затирает: голос утром и вечером разный.
        color — задать цвет явно (её собственный голос всегда акцентный,
        чтобы на карте её ни с кем не спутать)."""
        embs = np.asarray(embs, dtype=np.float32)
        if embs.ndim == 1:
            embs = embs[None, :]
        cur = self.speakers.get(name)
        if cur is not None and cur["embs"].shape[1] == embs.shape[1]:
            embs = np.vstack([cur["embs"], embs])[-MAX_ENROLL:]
            color = color or cur["color"]
        else:
            color = color or PALETTE[len(self.speakers) % len(PALETTE)]
        keep = cur or {}
        self.speakers[name] = {"embs": embs, "color": color, "_c": None,
                               "pinned": bool(keep.get("pinned", False)),
                               "auto": bool(keep.get("auto", False)),
                               "hyp": dict(keep.get("hyp", {}))}
        self.dirty = True
        self._drop_mismatched()
        return len(embs)

    def note_skel(self, name: str, hz=0.0, tract=0.0, rate=0.0):
        """═══ СКЕЛЕТ ГОЛОСА (2026-08-16) ═══

        Владелец: «формировать скелеты голоса у людей, чтобы более чётко
        определять, чей это спектр у слова».

        Скелет — профиль человека, устойчивый там, где отдельная реплика
        врёт. Держим ПОСЛЕДНИЕ 64 измерения каждой величины и берём по
        ним МЕДИАНУ, а не среднее и не EMA. Причина видна на живом логе:
        длина речевого тракта по одной фразе скакала 15 → 31 см у одного
        и того же человека — оценка формант на секунде речи шумная. Ни
        среднее, ни экспоненциальное сглаживание это не лечат: и то и
        другое тянется за выбросом. Медиана выброс просто не замечает,
        и уже на паре десятков реплик даёт число, которому можно верить.

        Что копим:
          hz    — основная частота (кто выше, кто ниже);
          tract — длина речевого тракта в см, физический размер человека;
          rate  — слогов в секунду, почерк речи.
        """
        sk = self.skel.setdefault(name, {"hz": [], "tract": [], "rate": []})
        for key, val, lo, hi in (("hz", hz, 55.0, 420.0),
                                 ("tract", tract, 8.0, 24.0),
                                 ("rate", rate, 0.4, 9.0)):
            try:
                v = float(val or 0)
            except Exception:
                continue
            if lo <= v <= hi:
                sk[key].append(round(v, 2))
                del sk[key][:-64]
        self.dirty = True

    def skeleton(self, name: str) -> dict:
        """Профиль человека числами. Пусто, пока измерений мало: врать
        одной точкой хуже, чем молчать."""
        sk = self.skel.get(name) or {}
        out = {}
        need = 6
        for key in ("hz", "tract", "rate"):
            vals = sorted(sk.get(key) or [])
            if len(vals) < need:
                continue
            n = len(vals)
            med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
            # полоса — межквартильный размах: он показывает, где голос
            # живёт обычно, а не куда он однажды сорвался
            q1, q3 = vals[n // 4], vals[(3 * n) // 4]
            out[key] = {"med": round(med, 1), "lo": round(q1, 1),
                        "hi": round(q3, 1), "n": n}
        return out

    def note(self, name: str, pitch: float):
        """Отметить живое узнавание: время, счётчик, диапазон тона.

        ДИАПАЗОН ДЫШИТ, А НЕ ТОЛЬКО РАСТЁТ (2026-08-16). Владелец:
        «нужно по умному, на основе распознавания частот звучания,
        распределять слова от каждого человека». Чтобы частота вообще
        могла что-то РАСПРЕДЕЛЯТЬ, диапазон обязан быть узким и честным.
        Раньше здесь стояли min и max за всю историю: одна ошибка
        узнавания — и «Голос 3» навсегда получал 91-222 Гц, то есть
        полосу, в которую влезает кто угодно, и как признак она умирала.
        Теперь края расширяются мгновенно (голос и правда бывает выше
        и ниже), но при каждом попадании внутрь полосы медленно
        подтягиваются к текущему тону. Случайный выброс за десяток
        нормальных фраз рассасывается сам, а настоящий разброс человека
        держится, потому что подтверждается заново."""
        st = self.stat.setdefault(name, {"last": 0.0, "n": 0,
                                         "plo": 0.0, "phi": 0.0})
        st["last"] = time.time()
        st["n"] = int(st.get("n", 0)) + 1
        if pitch and pitch > 40:
            lo, hi = float(st.get("plo") or 0), float(st.get("phi") or 0)
            if not lo or not hi:
                lo = hi = pitch
            elif pitch < lo:
                lo = pitch
            elif pitch > hi:
                hi = pitch
            else:
                # тон внутри полосы — края сползаются к нему на 3%
                lo += (pitch - lo) * 0.03
                hi -= (hi - pitch) * 0.03
            # полосе не даём схлопнуться в точку: у живого голоса разброс
            # хотя бы ±6% от тона, иначе он сам себя перестанет узнавать
            mid = (lo + hi) / 2.0
            st["plo"] = round(min(lo, mid * 0.94), 2)
            st["phi"] = round(max(hi, mid * 1.06), 2)
        self.dirty = True

    def forget(self, name: str):
        self.stat.pop(name, None)
        if self.speakers.pop(name, None) is not None:
            # ТОЧКИ ЗАБЫТОГО — ДОЛОЙ, А НЕ В СЕРОЕ (2026-07-28, владелец:
            # «почему при чистке остаются остаточные облачка»). Раньше точки
            # только теряли подпись и оставались висеть безымянным туманом:
            # человек чистил список, а карта выглядела как до чистки. Забыть
            # голос — значит забыть и его след на карте.
            self.drop_points(name)
            self.dirty = True
            return True
        return False

    def drop_points(self, who: str):
        """Убрать с карты точки одного голоса."""
        if self.pts is None or not len(self.pts_who):
            return
        keep = [i for i, w in enumerate(self.pts_who) if w != who]
        if len(keep) == len(self.pts_who):
            return
        self.pts = self.pts[keep] if keep else None
        self.pts_who = [self.pts_who[i] for i in keep]
        self.pts_ts = [self.pts_ts[i] for i in keep]
        self.dirty = True

    def clear_points(self):
        """Полная чистка карты: все накопленные точки, включая безымянные.
        Эталоны голосов НЕ трогаем — она по-прежнему всех узнаёт, просто
        облака начнут расти заново."""
        n = 0 if self.pts is None else len(self.pts)
        self.pts, self.pts_who, self.pts_ts = None, [], []
        self.dirty = True
        return n

    # ПОРОГ СЧИТАЕТСЯ ИЗ САМОЙ ЗАПИСИ, а не берётся из конфига. Почему так:
    # абсолютное значение косинуса ничего не значит само по себе — у ECAPA
    # своя шкала, у лёгких признаков своя, у шумного микрофона третья. Зато
    # при записи эталона мы ЗНАЕМ, как этот человек похож сам на себя:
    # считаем среднее и разброс близости его же кусков к его же центроиду.
    # «Свой» = попал в mu - 3*sd. Это калибруется под каждого и переживает
    # смену движка, микрофона и простуду.
    #
    # ГРАБЛИ (2026-07-28, поймано самотестом): сначала здесь было вычитание
    # общего среднего по всему услышанному. На бумаге красиво, на практике
    # при ОДНОМ записанном голосе общее среднее — это он и есть, вычитание
    # стирало ровно то, что искали, и человек переставал узнаваться (0 из 14).
    def _prof(self, name):
        """-> (центроид, mu, sd). Считается один раз на запись."""
        v = self.speakers[name]
        if v.get("_c") is not None:
            return v["_c"], v["_mu"], v["_sd"]
        e = v["embs"]
        c = e.mean(axis=0)
        n = np.linalg.norm(c)
        c = (c / n if n > 1e-9 else c).astype(np.float32)
        sims = e @ c
        mu, sd = float(sims.mean()), float(sims.std())
        # ЗАПАС НА БУДУЩЕЕ (поймано самотестом): запись идёт секунд за
        # пятнадцать подряд, поэтому разброс в ней ВСЕГДА оптимистичнее
        # реального — завтра тот же человек звучит дальше от своего же
        # центроида, чем сегодня. Без нижней планки на sd порог оказывается
        # уже собственного голоса, и человек перестаёт узнаваться на
        # следующий день. 0.03 — цена одного дня расхождения.
        # СВЕРХУ ТОЖЕ ОГРАНИЧИВАЕМ, и это оказалось важнее нижней планки.
        # ГРАБЛИ (2026-07-28, живой случай): её собственный эталон набрался
        # из синтезированной речи, где разброс большой — sd вышел под 0.15,
        # порог mu-3*sd провалился ниже нижней планки, и «своим» стал ЛЮБОЙ
        # голос. На экране это выглядело так: включили ролик на ютубе, и все
        # реплики диктора подписаны «голос: Сайка». Один рыхлый эталон не
        # должен уметь открыть ворота всем.
        sd = min(max(sd, 0.03), 0.06)
        v["_c"], v["_mu"], v["_sd"] = c, mu, sd
        return c, mu, sd

    def centroid(self, name):
        return self._prof(name)[0]

    def match(self, emb):
        """-> (имя или "", близость, уверенность 0..1, ближайшее имя).

        Четвёртым идёт «ближе всего» — имя лидера ДАЖЕ если он не прошёл
        порог. Без него интерфейс показывает «незнакомый голос, похожесть
        0.89» и это читается как поломка; с ним видно решение целиком:
        «ближе всего Виталий, но не дотянул».

        Уверенность — это не косинус: она показывает, насколько глубоко
        внутрь «своего» разброса попал кусок. В интерфейсе рисуется кольцом
        вокруг точки: туго сжато — уверена, размыто — сомневается."""
        if not self.speakers:
            return "", 0.0, 0.0, ""
        e = np.asarray(emb, dtype=np.float32)
        floor = CFG.get("voiceprint.threshold", 0.0) or _floor(len(emb))
        best = ("", -1.0, 0.0, "")
        for name, v in self.speakers.items():
            if v["embs"].shape[1] != len(e):
                continue
            c, mu, sd = self._prof(name)
            s = cosine(e, c)
            thr = max(floor, mu - 2.5 * sd)
            # ПОРОГ ИЗ ПАСПОРТА (2026-08-19). Общее правило mu-2.5sd берёт
            # разброс ТОЛЬКО своих точек и ничего не знает о том, как
            # близко подходят чужие. Паспорт голоса считает границу по
            # обеим сторонам сразу (см. voiceprint/passport.py) — если она
            # есть, слушаем её: это тот же человек, но проверенный против
            # остальных, а не сам против себя.
            own = v.get("thr")
            if own is not None:
                try:
                    thr = max(floor, float(own))
                except Exception:
                    pass
            conf = (s - thr) / max(mu - thr, 1e-6)
            conf = float(np.clip(conf, 0.0, 1.0))
            if s > best[1]:
                best = (name if s >= thr else "", s, conf, name)
        return (best[0], float(best[1]),
                float(best[2] if best[0] else 0.0), best[3])

    def adapt(self, name: str, emb, conf: float):
        """Дописать эталон живой речью. ЗАЧЕМ: запись при знакомстве ловит
        один вечер и одно настроение, а человек за неделю звучит десятком
        разных способов. Берём только уверенные попадания и не чаще раза в
        полминуты — иначе ошибочное узнавание отравит эталон, и дальше он
        начнёт узнавать не того."""
        if name not in self.speakers or conf < 0.55:
            return False
        if time.time() - self._adapt_ts.get(name, 0.0) < 30.0:
            return False
        v = self.speakers[name]
        if v["embs"].shape[1] != len(emb):
            return False
        self._adapt_ts[name] = time.time()
        v["embs"] = np.vstack([v["embs"],
                               np.asarray(emb, np.float32)[None, :]])[-MAX_ENROLL:]
        v["_c"] = None
        self.dirty = True
        return True

    # -------------------------------------------------------------- облако
    def add_point(self, emb, who: str):
        emb = np.asarray(emb, dtype=np.float32)[None, :]
        if self.pts is None or self.pts.shape[1] != emb.shape[1]:
            self.pts, self.pts_who, self.pts_ts = emb, [who], [time.time()]
        else:
            self.pts = np.vstack([self.pts, emb])[-MAX_POINTS:]
            self.pts_who = (self.pts_who + [who])[-MAX_POINTS:]
            self.pts_ts = (self.pts_ts + [time.time()])[-MAX_POINTS:]
        self.dirty = True

    def training_set(self):
        """Всё, на чём учить проекцию: история + эталоны."""
        parts = []
        if self.pts is not None and len(self.pts):
            parts.append(self.pts)
        for v in self.speakers.values():
            if not parts or v["embs"].shape[1] == parts[0].shape[1]:
                parts.append(v["embs"])
        return np.vstack(parts) if parts else None

    def colors(self):
        return {n: v["color"] for n, v in self.speakers.items()}


def _floor(dim):
    """Нижняя планка косинуса: страховка от «узнала всех подряд», когда у
    человека записано мало и разброс вышел неправдоподобно широким. Шкалы у
    движков разные — ECAPA разводит голоса шире, лёгкие признаки теснее."""
    # 2026-07-28: 0.55 для лёгкого энкодера оказалось дырой — у РАЗНЫХ людей
    # косинус на 68 признаках спокойно доходит до 0.7. Своих это почти не
    # задевает (у них 0.83+), а чужих отсекает.
    return 0.45 if dim >= 128 else 0.72


def _safe(name):
    return "".join(c if c.isalnum() else "_" for c in name)[:40] or "x"
