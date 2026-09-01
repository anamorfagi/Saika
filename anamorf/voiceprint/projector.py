"""Вектор голоса -> точка на экране (2026-07-28).

ГЛАВНЫЙ ФОКУС МОДУЛЯ. UMAP нельзя гонять на каждый чанк: обучение проекции —
это секунды, а точка должна ехать за голосом в реальном времени. Поэтому
проекция ОБУЧАЕТСЯ РЕДКО (в фоне, на накопленных векторах) и ПРИМЕНЯЕТСЯ
часто (transform ~1мс). Ровно та же логика, что у ночной консолидации памяти:
тяжёлое — пачкой и не на виду, лёгкое — мгновенно.

ТРИ СТУПЕНИ, переключаются сами по количеству накопленных векторов:
  0..23   — «зеркало»: фиксированная случайная проекция (seed 20260728).
            Кластеров ещё нет, но точка ЕДЕТ с первой же фразы, и человеку
            уже интересно. Детерминированная — при перезапуске картинка та же.
  24..N   — PCA (numpy SVD): две главные оси разброса голосов. Честно
            показывает «где расходятся голоса», считается мгновенно.
  N+      — UMAP, если umap-learn установлен. Кластеры плотнее и красивее.

ПРИ СМЕНЕ СТУПЕНИ ВСЕ СТАРЫЕ ТОЧКИ ПЕРЕСЧИТЫВАЮТСЯ. Иначе облако прошлых
фраз оказалось бы в координатах прошлой проекции — визуально «два разных
мира» на одном экране. Поэтому реестр хранит векторы, а не координаты.
"""
import logging
import threading

import numpy as np

from anamorf.config import CFG

log = logging.getLogger("saika.voiceprint")

PCA_MIN = 24            # с этого числа векторов включается PCA
UMAP_MIN = 60           # с этого — UMAP (если установлен)


class Projector:
    def __init__(self):
        self.kind = "mirror"        # mirror | pca | umap
        self.dim = 0
        self._lock = threading.Lock()
        self._mean = None
        self._scale = None          # поосевая нормировка входа
        self._comp = None           # (2, dim) для mirror/pca
        self._umap = None
        self._lo_lin = None      # запасной размах для линейной проекции
        self._hi_lin = None
        self._lo = np.array([-1.0, -1.0], np.float32)   # границы для растяжки
        self._hi = np.array([1.0, 1.0], np.float32)

    # ---------------------------------------------------------------- utils
    def _mirror(self, dim):
        """Фиксированная случайная проекция. Seed прибит гвоздями: картинка
        не должна меняться от перезапуска к перезапуску."""
        rng = np.random.default_rng(20260728)
        m = rng.normal(size=(2, dim)).astype(np.float32)
        m /= np.linalg.norm(m, axis=1, keepdims=True)
        return m

    def _prep(self, X):
        X = np.asarray(X, dtype=np.float32)
        if X.ndim == 1:
            X = X[None, :]
        # ГРАБЛИ 2026-07-28: сменился энкодер (лёгкий 68 -> ECAPA 192), а
        # проекция осталась обучена на старой длине. Проверка размерности
        # стояла НИЖЕ, в transform, — и до неё дело не доходило: падало
        # прямо здесь, «operands could not be broadcast (1,192) (68,)», по
        # разу на каждый кусок речи. Теперь при несовпадении просто не
        # нормируем: ближайшее переобучение всё равно перезапишет.
        if self._mean is None or len(self._mean) != X.shape[1]:
            return X
        return (X - self._mean) / self._scale

    # ----------------------------------------------------------------- fit
    def fit(self, X):
        """X — (n, dim) накопленные векторы. Возвращает имя ступени."""
        X = np.asarray(X, dtype=np.float32)
        if X.ndim != 2 or len(X) == 0:
            return self.kind
        dim = X.shape[1]
        mean = X.mean(axis=0)
        scale = X.std(axis=0)
        scale[scale < 1e-6] = 1.0            # мёртвые оси не делят на ноль
        Z = (X - mean) / scale

        kind, comp, um = "mirror", self._mirror(dim), None
        if len(X) >= PCA_MIN:
            try:
                # SVD по центрированным данным = PCA без лишних зависимостей
                _, _, vt = np.linalg.svd(Z - Z.mean(axis=0), full_matrices=False)
                comp, kind = vt[:2].astype(np.float32), "pca"
            except Exception as e:
                log.warning("PCA не сошлась (%s) — остаюсь на зеркале", e)
        if len(X) >= UMAP_MIN and CFG.get("voiceprint.umap", True):
            try:
                import umap
                n = min(15, max(2, len(X) // 3))
                um = umap.UMAP(n_components=2, n_neighbors=n, min_dist=0.12,
                               metric="cosine", random_state=20260728).fit(Z)
                kind = "umap"
            except ImportError:
                pass                          # не установлен — это норма
            except Exception as e:
                log.warning("UMAP не обучилась (%s) — остаюсь на %s", e, kind)

        # растяжка в [-1, 1] по 2..98 перцентилям: одиночный выброс не должен
        # сплющивать всё облако в точку по центру
        with self._lock:
            self._mean, self._scale = mean, scale
            self._comp, self._umap, self.kind, self.dim = comp, um, kind, dim
        # ═══ МАСШТАБ СВОЙ У КАЖДОЙ ПРОЕКЦИИ (2026-08-31) ═══
        # Здесь считался ОДИН размах — по той проекции, которая обучилась
        # (обычно UMAP). А в работе `um.transform` падает на известном баге
        # umap-learn (NNDescent без _rp_forest), код честно откатывается на
        # линейную — и натягивает её на UMAP-овский размах. У PCA он в разы
        # меньше, поэтому всё облако сжималось в полоску и упиралось в
        # зажим: владелец увидел «жёстко расплющило». Держим оба размаха.
        def _range(P):
            lo = np.percentile(P, 2, axis=0)
            hi = np.percentile(P, 98, axis=0)
            span = np.maximum(hi - lo, 1e-6)
            return lo.astype(np.float32), (lo + span).astype(np.float32)

        P = self.transform(X, _raw=True)
        lo, hi = _range(P)
        with self._lock:
            self._lo, self._hi = lo, hi
            # запасной размах — по линейной проекции тех же данных
            try:
                self._lo_lin, self._hi_lin = _range(Z @ comp.T)
            except Exception:
                self._lo_lin, self._hi_lin = lo, hi
        log.info("Проекция голосов обучена: %s, векторов %d", kind, len(X))
        return kind

    # ----------------------------------------------------------- transform
    def transform(self, X, _raw=False):
        """(n, dim) -> (n, 2). ~1мс, зовётся на каждый чанк речи."""
        with self._lock:
            kind, comp, um = self.kind, self._comp, self._umap
            lo, hi = self._lo, self._hi
        Z = self._prep(X)
        if comp is None or Z.shape[1] != comp.shape[1]:
            comp = self._mirror(Z.shape[1])
            kind = "mirror"
        if kind == "umap" and um is not None:
            try:
                P = np.asarray(um.transform(Z), dtype=np.float32)
            except Exception as e:
                # ПАДАЕТ — ЗНАЧИТ ПАДАЕТ НАВСЕГДА (2026-08-31). Это не
                # случайный сбой, а состояние модели: NNDescent внутри
                # UMAP теряет _rp_forest и уже не восстановится. Раньше мы
                # ловили исключение на КАЖДОМ чанке речи, писали в лог и
                # считали линейно — но по UMAP-овскому размаху, отчего
                # картинку плющило. Переключаемся один раз, честно, и
                # берём линейный размах.
                with self._lock:
                    if self.kind == "umap":
                        self.kind = "pca"
                        log.warning("UMAP.transform больше не работает (%s) "
                                    "— перехожу на линейную проекцию с её "
                                    "собственным масштабом", e)
                    if self._lo_lin is not None:
                        lo, hi = self._lo_lin, self._hi_lin
                P = Z @ comp.T
        else:
            P = Z @ comp.T
        P = np.nan_to_num(P, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
        if _raw:
            return P
        # в [-1, 1] с мягким зажимом: точка, вылетевшая за облако, остаётся
        # видимой у края, а не пропадает с экрана
        out = 2.0 * (P - lo) / np.maximum(hi - lo, 1e-6) - 1.0
        return np.clip(out, -1.6, 1.6).astype(np.float32)

    def state(self):
        return {"kind": self.kind, "dim": int(self.dim),
                "pca_min": PCA_MIN, "umap_min": UMAP_MIN}
