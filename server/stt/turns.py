"""СМЕНА ГОВОРЯЩЕГО ВНУТРИ ОДНОЙ ФРАЗЫ — разрезание перед распознаванием.

(2026-08-15, задача владельца: «включу аниме на фон, будем смотреть, как он
будет определять голоса персонажей… чтобы мог определить по тембру, даже
если два человека вместе говорят».)

ЧТО ЭТО ЧИНИТ. Нарезка по паузам считает фразой всё от тишины до тишины.
Живой диалог — аниме, спор, перебивание — пауз между репликами не имеет:
«Ты куда пошёл?Я в магазин.Купи молока» приезжает ОДНИМ куском, движок
пишет его одной строкой, отпечаток вешает на кусок ОДНОГО говорящего —
второй персонаж исчезает из стенограммы как человек.

КАК РЕЖЕМ. По тембру, тем же энкодером, что узнаёт голоса (ECAPA из
voiceprint — он уже в памяти, ничего нового не грузится): скользящим окном
~1.2с с шагом 0.4с считаем эмбеддинги, между соседними окнами — косинус.
Провал ниже порога = в этом месте сменился голос. Режем по центру провала,
куски короче 0.8с не рождаем (это не реплика, это придыхание).

ЧЕСТНОСТЬ ГРАНИЦ. Метод ловит СМЕНУ голоса, а не наложение: когда двое
говорят строго одновременно, эмбеддинг смеси не похож ни на кого — такие
куски помечаются crowd=True («несколько голосов разом»), и это правда,
которую мы знаем, а не выдумка. Полное разделение наложенной речи — это
source separation, отдельная тяжёлая модель; пометка честнее плохой догадки.

ЦЕНА. Эмбеддинг окна — миллисекунды на GPU и десятки на CPU; окон в фразе
единицы. Живёт в потоке распознавания, горячий цикл слуха не трогает.
Выключается: stt.turns = false.
"""
import logging

import numpy as np

from server.config import CFG

log = logging.getLogger("saika.turns")

SR = 16000
WIN_S = 1.2          # окно эмбеддинга
HOP_S = 0.4          # шаг
MIN_PART_S = 0.8     # короче — не реплика


def _cos(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _encoder():
    """Боевой энкодер тембра из voiceprint. Нет его (выключен, не встал) —
    разрезание молча выключается: слух работает как работал."""
    try:
        from server import voiceprint as vp
        enc = getattr(vp.S, "enc", None)
        if enc is not None and hasattr(enc, "encode"):
            return enc
    except Exception:
        pass
    return None


def split(pcm16: np.ndarray, sr: int = SR, encoder=None):
    """-> [ {start, end, crowd} ] в сэмплах. Один говорящий -> один кусок.

    encoder пробрасывается только стендом (tools/hear_lab.py) — в бою он
    берётся из voiceprint сам."""
    n = len(pcm16)
    whole = [{"start": 0, "end": n, "crowd": False}]
    if not CFG.get("stt.turns", True):
        return whole
    win, hop = int(WIN_S * sr), int(HOP_S * sr)
    # КОРОТКУЮ ФРАЗУ НЕ ТРОГАЕМ (2026-08-15, живой прокол в первый же час:
    # «Твоя задача определить, сколько человек в аниме» — хвост «в аниме»
    # отрезало и ослышало как «Да». В двух секундах речи смене голоса
    # взяться неоткуда, а вреда от ложного разреза много: обрезок в
    # полсекунды движок дослышивает до случайного слова.)
    if n < int(float(CFG.get("stt.turns_min_s", 2.5)) * sr):
        return whole
    if n < win + hop:               # короче двух окон — резать нечего
        return whole
    enc = encoder or _encoder()
    if enc is None:
        return whole
    try:
        # ТИХОЕ ОКНО НЕ ЭМБЕДДИТСЯ (баг пойман стендом tools/hear_lab:
        # окно на хвостовой тишине даёт мусорный вектор, косинус с ним
        # проваливается — и «смена голоса» рисовалась там, где человек
        # просто ЗАМОЛЧАЛ). Эмбеддинг тембра имеет смысл только на речи.
        x = np.asarray(pcm16, np.float32) / 32768.0
        peak_rms = 0.0
        rms_of = {}
        i = 0
        while i + win <= n:
            r = float(np.sqrt(np.mean(x[i:i + win] ** 2)))
            rms_of[i] = r
            peak_rms = max(peak_rms, r)
            i += hop
        floor = peak_rms * 0.2
        embs, marks = [], []
        i = 0
        while i + win <= n:
            if rms_of.get(i, 0.0) < floor:
                i += hop
                continue
            e = enc.encode(pcm16[i:i + win])
            # боевой encode отдаёт (vec, pitch); стендовый может отдать vec
            vec = e[0] if isinstance(e, tuple) else e
            if vec is None:
                return whole
            embs.append(np.asarray(vec, dtype=np.float32))
            marks.append(i + win // 2)          # центр окна
            i += hop
        if len(embs) < 3:
            return whole
        # ПОРОГ 0.35, А НЕ 0.60 (2026-08-15, тот же прокол). ECAPA-косинус
        # ОДНОГО человека между соседними окнами гуляет 0.5-0.8 — порог
        # 0.60 резал монологи. Разные голоса дают 0.1-0.4. Режем только
        # там, где непохожесть НЕОСПОРИМА; спорные места пусть живут одной
        # фразой — это дешевле, чем осколки со случайными словами.
        thr = float(CFG.get("stt.turns_cos", 0.35))
        # косинус соседних окон; провал = смена голоса. Ищем ЛОКАЛЬНЫЕ
        # минимумы ниже порога, а не все подряд: одна смена даёт 2-3
        # низких пары подряд (окна перекрывают границу), резать надо раз.
        sims = [_cos(embs[k], embs[k + 1]) for k in range(len(embs) - 1)]
        cuts = []
        for k in range(len(sims)):
            if sims[k] >= thr:
                continue
            if (k == 0 or sims[k] <= sims[k - 1]) and \
               (k == len(sims) - 1 or sims[k] <= sims[k + 1]):
                cut = (marks[k] + marks[k + 1]) // 2
                if not cuts or cut - cuts[-1] >= int(MIN_PART_S * sr):
                    cuts.append(cut)
        if not cuts:
            return whole
        # ПРОВЕРКА КАЖДОГО РАЗРЕЗА ПО ГРУППАМ (2026-08-15). Пара соседних
        # окон — слишком шаткое основание: одно кашлянутое окно роняет
        # косинус. Разрез остаётся, только если СРЕДНИЕ тембры слева и
        # справа от него тоже непохожи — то есть голос сменился надолго,
        # а не мигнул на полсекунды.
        kept = []
        for cut in cuts:
            left = [e for e, m in zip(embs, marks) if m < cut]
            right = [e for e, m in zip(embs, marks) if m >= cut]
            if len(left) >= 1 and len(right) >= 1:
                cl = np.mean(np.stack(left), axis=0)
                cr = np.mean(np.stack(right), axis=0)
                if _cos(cl, cr) < thr + 0.1:
                    kept.append(cut)
        cuts = kept
        if not cuts:
            return whole
        # РАЗНОБОЙ ВНУТРИ КУСКА = НЕСКОЛЬКО ГОЛОСОВ РАЗОМ. Если окна и
        # ПОСЛЕ разреза не похожи друг на друга, это не смена — это смесь:
        # честная пометка вместо уверенной подписи одним именем.
        parts = []
        edges = [0] + cuts + [n]
        wi = 0
        for s0, s1 in zip(edges[:-1], edges[1:]):
            if s1 - s0 < int(MIN_PART_S * sr):
                # слишком короткий — приклеиваем к соседу
                if parts:
                    parts[-1]["end"] = s1
                    continue
                s1 = min(n, s0 + int(MIN_PART_S * sr))
            ws = [e for e, m in zip(embs, marks) if s0 <= m < s1]
            crowd = False
            if len(ws) >= 2:
                inner = [_cos(ws[k], ws[k + 1]) for k in range(len(ws) - 1)]
                crowd = (float(np.mean(inner)) < thr)
            parts.append({"start": int(s0), "end": int(s1), "crowd": crowd})
            wi += 1
        if len(parts) > 1:
            log.info("Смена голоса внутри фразы: режу на %d куска(ов) "
                     "(пороговый косинус %.2f)", len(parts), thr)
        return parts or whole
    except Exception as e:
        log.debug("разрезание по голосам пропущено: %s", e)
        return whole


def who(pcm16: np.ndarray, sr: int = SR):
    """Чей это кусок: имя из карты голосов + уверенность, или ("", 0).
    Для подписи разрезанных кусков: who_now() тут не годится — он про
    «прямо сейчас в комнате», а кусок мог прозвучать три секунды назад."""
    try:
        from server import voiceprint as vp
        enc = getattr(vp.S, "enc", None)
        reg = getattr(vp.S, "reg", None)
        if enc is None or reg is None:
            return "", 0.0
        e = enc.encode(pcm16)
        vec = e[0] if isinstance(e, tuple) else e
        if vec is None:
            return "", 0.0
        name, _sim, conf, _near = reg.match(vec)
        return name, float(conf)
    except Exception:
        return "", 0.0
