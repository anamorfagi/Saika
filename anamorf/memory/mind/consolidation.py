# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
  CONSOLIDATION — «сон» Сайки. Отдельный ночной batch-процесс:

  1) кластеризует RAW за день по времени и источнику;
  2) LLM пересказывает кластер → эпизод (L2);
  3) LLM извлекает голые факты → L3 (через ФИЛЬТР ЦЕННОСТЕЙ);
  4) мусор ниже порога salience — удаляется;
  5) старые эпизоды затухают по Эббингаузу, слабые — стираются;
  6) пересчёт архетипов людей из осей (persons.recompute).

  Биология: гиппокамп ночью «проигрывает» день коре.
═══════════════════════════════════════════════════════════════════
"""
import time
from . import config, db
from .llm import summarize_cluster, extract_facts
from . import persons

# ── БЛОК: фильтр ценностей ────────────────────────────────────────
# Правило ядра: в L3 попадают ТОЛЬКО факты о мире и людях.
# Ценностные обобщения не проходят — они живут в весах и character_core.
VALUE_MARKERS = ("нельзя доверять", "все люди", "всегда нужно", "никогда не стоит",
                 "значит, люди", "мир жесток", "добро это", "зло это")


def _is_value_generalization(fact: str) -> bool:
    low = fact.lower()
    return any(m in low for m in VALUE_MARKERS)


# ── БЛОК: где кончается одно событие и начинается другое ──────────
# Переделано 2026-08-25 по теории сегментации событий (Zacks & Radvansky:
# граница события — скачок ошибки предсказания, а её вызывает смена
# ВРЕМЕНИ, МЕСТА, СОСТАВА УЧАСТНИКОВ, ЦЕЛИ или причинности).
#
# БЫЛО: новый кластер при смене source_type. Логика на вид разумная —
# «сменился говорящий, значит сменилось событие», — но она рвёт ровно то,
# ради чего эпизоды и заводят. Разговор двоих это ОДНО событие с двумя
# участниками, а не двадцать событий по реплике: чередование реплик в
# диалоге не удивляет никого, ошибка предсказания там не скачет. Стенд
# показывал двадцать эпизодов на двадцать фраз — то есть эпизодов не было
# вовсе, была переименованная стенограмма.
#
# СТАЛО: границу дают время и два предохранителя, а состав участников и
# источники живут ВНУТРИ события. Прививка от кейса Сары не потерялась —
# она переехала на шаг ниже: факты извлекаются отдельно по каждому
# источнику внутри кластера (см. run_night). Телевизор, бубнивший рядом
# с владельцем, остаётся частью сцены — но знанием о мире не становится.
#
# ЧЕГО ЗДЕСЬ ЧЕСТНО НЕТ. Главный сигнал у человека — не время, а
# неожиданность; в памяти для LLM её считают как байесовскую неожиданность
# по самой модели (EM-LLM). Дёшево и без модели она не берётся: наша
# novelty меряет непохожесть на последние фразы вообще, а не разрыв темы,
# и порогом по ней всё режется в лапшу. Поэтому пока стоит осторожная
# лексическая проверка, а место для настоящего сигнала обозначено —
# _тема_сменилась. Появятся эмбеддинги — менять только её.

_СЛУЖЕБНЫЕ = {"это", "вот", "как", "что", "так", "они", "она", "оно",
              "мне", "тебе", "если", "меня", "тебя", "ещё", "уже", "там",
              "тут", "был", "была", "быть", "надо", "нет", "да"}


def _слова(текст: str) -> set:
    return {w for w in "".join(c if c.isalnum() else " "
                               for c in (текст or "").lower()).split()
            if len(w) > 3 and w not in _СЛУЖЕБНЫЕ}


def _тема_сменилась(строка, кластер, пауза_с: float) -> bool:
    """Осторожная замена настоящему сигналу неожиданности.

    Режем, только когда совпало ВСЁ сразу: была ощутимая пауза, во фразе
    есть за что зацепиться, и с последними фразами события у неё нет ни
    одного общего значимого слова. По любому признаку поодиночке
    получается лапша из односложных эпизодов — проверено стендом."""
    if пауза_с < 300:
        return False
    свои = _слова(строка["text"])
    if len(свои) < 3:
        return False
    хвост = set()
    for r in кластер[-3:]:
        хвост |= _слова(r["text"])
    if len(хвост) < 3:
        return False
    return not (свои & хвост)


def _cluster_raw(rows, gap_sec: int = 1800, max_span_sec: int = 7200,
                 max_rows: int = 40):
    """Сырьё дня → события. Границы: пауза, смена темы и два
    предохранителя — событие не может тянуться весь день и не может быть
    бесконечно длинным, иначе ночной пересказ получит на вход простыню."""
    clusters, cur = [], []
    for r in rows:
        if cur:
            пауза = r["ts"] - cur[-1]["ts"]
            if (пауза > gap_sec
                    or r["ts"] - cur[0]["ts"] > max_span_sec
                    or len(cur) >= max_rows
                    or _тема_сменилась(r, cur, пауза)):
                clusters.append(cur)
                cur = []
        cur.append(r)
    if cur:
        clusters.append(cur)
    return clusters


def run_night(con) -> dict:
    """Главная функция «сна». Возвращает отчёт — что произошло за ночь."""
    report = {"эпизодов_создано": 0, "фактов": 0, "гипотез_обновлено": 0,
              "raw_удалено": 0, "эпизодов_стёрто": 0, "ценностей_отфильтровано": 0,
              "фактов_не_из_доверенных": 0, "обещаний_просрочено": 0}
    now = time.time()
    # Отметка прошлой ночи нужна ДВАЖДЫ (затухание и архетипы) —
    # читаем один раз здесь, до всякой работы.
    _last = con.execute("SELECT value FROM meta WHERE key='last_night'").fetchone()
    since = float(_last["value"]) if _last else 0.0

    # ── Шаг 1–3: RAW → эпизоды → факты ────────────────────────────
    rows = con.execute("SELECT * FROM raw_events WHERE processed=0 ORDER BY ts").fetchall()
    for cluster in _cluster_raw(rows):
        # мусор ниже порога значимости не осмысляем вообще
        strong = [r for r in cluster if r["salience"] >= config.SALIENCE_MIN_KEEP]
        if not strong:
            continue
        texts = [r["text"] for r in strong]
        # Событие теперь бывает смешанным: сцена «владелец говорит, рядом
        # работает телевизор» — это одно событие с двумя источниками.
        по_источникам: dict = {}
        for r in strong:
            по_источникам.setdefault(r["source_type"], []).append(r)
        src = max(по_источникам, key=lambda k: len(по_источникам[k]))
        источники = sorted(по_источникам)
        pids = sorted({r["person_id"] for r in strong if r["person_id"]})
        emotion = max(r["emotion"] for r in strong)
        strength = max(r["salience"] for r in strong)

        summary = summarize_cluster(texts, src)              # LLM-крючок
        con.execute(
            "INSERT INTO episodes(ts_start, ts_end, summary, persons, source_type,"
            " sources, emotion, strength, last_recall) VALUES (?,?,?,?,?,?,?,?,?)",
            (strong[0]["ts"], strong[-1]["ts"], summary,
             ",".join(map(str, pids)), src, ",".join(источники),
             emotion, strength, now))
        ep_id = con.execute("SELECT last_insert_rowid() i").fetchone()["i"]
        report["эпизодов_создано"] += 1

        # ФАКТЫ ИЗВЛЕКАЮТСЯ ПО КАЖДОМУ ИСТОЧНИКУ ОТДЕЛЬНО. Здесь и живёт
        # прививка от кейса Сары: событие общее, а знание — именное. Даже
        # оказавшись в одной сцене с владельцем, чужой голос не научит её
        # ничему, и у каждого факта в базе записано, от кого он узнан.
        for исток, строки in по_источникам.items():
            if исток not in config.FACT_SOURCES:
                report["фактов_не_из_доверенных"] += 1
                continue
            их_тексты = [r["text"] for r in строки]
            их_pids = sorted({r["person_id"] for r in строки if r["person_id"]})
            for fact, pid in extract_facts(их_тексты, исток, их_pids):
                if _is_value_generalization(fact):
                    report["ценностей_отфильтровано"] += 1
                    continue
                n = _upsert_fact(con, fact, pid, ep_id, исток)
                report["фактов" if n == "new" else "гипотез_обновлено"] += 1

    con.execute("UPDATE raw_events SET processed=1 WHERE processed=0")

    # ── Шаг 4: чистка RAW старше срока жизни ──────────────────────
    cutoff = now - config.DECAY_TAU_RAW_H * 3600
    report["raw_удалено"] = con.execute(
        "DELETE FROM raw_events WHERE processed=1 AND ts < ?", (cutoff,)).rowcount

    # ── Шаг 5: Эббингауз — затухание эпизодов ─────────────────────
    # Считаем в Python, НЕ в SQL: exp() есть не во всех сборках SQLite
    # (на Windows математика часто выключена — упало бы молча).
    # ВОЗРАСТ СЧИТАЕТСЯ С ПРОШЛОЙ НОЧИ, А НЕ С РОЖДЕНИЯ (2026-08-25).
    # Было: age от last_recall — но strength при этом уже перезаписывался
    # каждую ночь, и затухание накладывалось на само себя. За N ночей
    # экспонента копила не N, а N(N+1)/2 суток: стенд показал смерть
    # проходного эпизода на 11-ю ночь вместо заявленных ~40.
    import math
    for ep in con.execute("SELECT id, ts_end, strength, recall_count,"
                          " last_recall FROM episodes").fetchall():
        база = max(ep["last_recall"] or ep["ts_end"], since)
        age_h = max(0.0, (now - база) / 3600.0)
        tau = config.DECAY_TAU_EPISODE_H * (1 + ep["recall_count"])
        new_strength = ep["strength"] * math.exp(-age_h / tau)
        con.execute("UPDATE episodes SET strength=? WHERE id=?",
                    (new_strength, ep["id"]))
    report["эпизодов_стёрто"] = con.execute(
        "DELETE FROM episodes WHERE strength < ?",
        (config.STRENGTH_FLOOR_DELETE,)).rowcount

    # ── Шаг 6: пересчёт архетипов — ТОЛЬКО активным ───────────────
    # Оптимизация «мёртвых душ»: через год в базе тысячи твич-ников,
    # молотить всех каждую ночь незачем — только тех, у кого были события.
    persons.recompute_archetypes(con, since_ts=since)

    # ── Шаг 6б: портреты по речи ──────────────────────────────────
    # Ночью, а не на каждой фразе: маркеры считаются по сотням реплик,
    # и трогать их в горячем пути значит платить за портрет на каждом
    # слове. Портрет меняется медленно — он и должен.
    from . import temper, circles
    for p in con.execute("SELECT DISTINCT person_id FROM raw_events"
                         " WHERE person_id IS NOT NULL").fetchall():
        try:
            temper.пересчитать(con, p["person_id"])
            circles.пересчитать(con, p["person_id"])
        except Exception:
            continue

    # ── Шаг 6в: очки за вчерашний баланс ──────────────────────────
    try:
        from . import score as _score
        report["очки"] = _score.начислить(con)
    except Exception as e:
        report["очки"] = {"error": str(e)}

    # ── Шаг 7: ЧАСЫ ПАМЯТИ — обещания с истёкшим сроком ───────────
    # Обещание без срока годности — это не обещание, а запись в блокнот.
    # Ночь единственная, кто регулярно смотрит на календарь, поэтому
    # просрочки ловит она: ставит статус и отдаёт список наверх, чтобы
    # Сайка могла ЗАГОВОРИТЬ первой, а не ждать, пока человек придёт сам.
    for pr in con.execute("SELECT id, person_id, text, due FROM promises"
                          " WHERE status='открыто'").fetchall():
        try:
            срок = float(pr["due"])
        except (TypeError, ValueError):
            continue                     # срок словами («в четверг») — не наше дело
        if срок < now:
            con.execute("UPDATE promises SET status='просрочено' WHERE id=?",
                        (pr["id"],))
            report.setdefault("просрочки", []).append(
                {"person_id": pr["person_id"], "text": pr["text"]})
            report["обещаний_просрочено"] += 1
    con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('last_night', ?)",
                (str(now),))
    con.commit()
    return report


def _upsert_fact(con, fact: str, person_id, event_id,
                 source_type: str = "") -> str:
    """Гипотеза → факт по механике confidence.
    Подтверждение засчитывается только НОВЫМ событием (last_event_id!) —
    защита от подтверждательного искажения «сам себя убедил»."""
    row = con.execute(
        "SELECT * FROM semantic_facts WHERE text=? AND person_id IS ?",
        (fact, person_id)).fetchone()
    now = time.time()
    if row is None:
        con.execute(
            "INSERT INTO semantic_facts(person_id, source_type, text, confidence,"
            " support_count, last_event_id, created, updated)"
            " VALUES (?,?,?,?,1,?,?,?)",
            (person_id, source_type, fact, config.HYPOTHESIS_START,
             event_id, now, now))
        return "new"
    if row["last_event_id"] == event_id:
        return "same"                       # то же событие — не подтверждение
    conf = min(1.0, row["confidence"] + config.HYPOTHESIS_STEP)
    status = "fact" if conf >= config.HYPOTHESIS_FACT_THRESHOLD else row["status"]
    con.execute(
        "UPDATE semantic_facts SET confidence=?, status=?, support_count=support_count+1,"
        " last_event_id=?, updated=? WHERE id=?",
        (conf, status, event_id, now, row["id"]))
    return "upd"


def contradict_fact(con, fact_id: int) -> None:
    """Противоречащее наблюдение: факт может деградировать обратно в гипотезу —
    люди меняются, память должна уметь передумывать."""
    row = con.execute("SELECT * FROM semantic_facts WHERE id=?", (fact_id,)).fetchone()
    if not row:
        return
    conf = max(0.0, row["confidence"] - config.CONTRADICTION_STEP)
    status = "hypothesis" if conf < config.HYPOTHESIS_FACT_THRESHOLD else row["status"]
    con.execute("UPDATE semantic_facts SET confidence=?, status=?,"
                " contradict_count=contradict_count+1, updated=? WHERE id=?",
                (conf, status, time.time(), row["id"]))
    con.commit()
