# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
  PERSONS — карты личностей. Три этажа:
    ЧЕРТЫ (медленно) — оси + компетентность/доверие ПО ДОМЕНАМ
    СОСТОЯНИЕ (быстро) — настроение сессии с просодики
    ОТНОШЕНИЯ — граф связей, обещания, история с Сайкой

  Архетип НЕ назначается вручную (кроме Создателя) —
  он ПЕРЕСЧИТЫВАЕТСЯ из осей ночью. Человек может мигрировать:
  «лидер мнений» → просела конструктивность → карта это покажет
  без чёрно-белых списков.
═══════════════════════════════════════════════════════════════════
"""
import json
import time
from . import config


# ── БЛОК: создание карты ──────────────────────────────────────────
def create_person(con, name: str, voice_id: str | None = None,
                  is_creator: bool = False) -> int:
    """Новая карта: архетип «нейтрал», все оси 50, доверие стартово низкое.
    Создатель — единственный, кто рождается сразу со своим архетипом."""
    cur = con.execute(
        "INSERT INTO persons(name, voice_id, archetype, is_creator, created)"
        " VALUES (?,?,?,?,?)",
        (name, voice_id, "создатель" if is_creator else "нейтрал",
         int(is_creator), time.time()))
    pid = cur.lastrowid
    for d in config.DOMAINS:
        con.execute("INSERT INTO person_domains(person_id, domain) VALUES (?,?)", (pid, d))
    for a in config.AXES:
        con.execute("INSERT INTO person_axes(person_id, axis) VALUES (?,?)", (pid, a))
    con.commit()
    return pid


# ── БЛОК: буфер кандидатов (строгая биометрия) ────────────────────
def hear_unknown_voice(con, voice_id: str) -> str | None:
    """Неопознанный голос НЕ создаёт карту (решение Витали).
    Считаем встречи; на N-й раз возвращаем вопрос Создателю."""
    row = con.execute("SELECT * FROM voice_candidates WHERE voice_id=?",
                      (voice_id,)).fetchone()
    now = time.time()
    if row is None:
        con.execute("INSERT INTO voice_candidates(voice_id, first_ts, last_ts)"
                    " VALUES (?,?,?)", (voice_id, now, now))
        con.commit()
        return None
    con.execute("UPDATE voice_candidates SET seen_count=seen_count+1, last_ts=?"
                " WHERE voice_id=?", (now, voice_id))
    con.commit()
    if row["seen_count"] + 1 >= config.CANDIDATE_ASK_AFTER and not row["asked"]:
        con.execute("UPDATE voice_candidates SET asked=1 WHERE voice_id=?", (voice_id,))
        con.commit()
        return (f"Этот голос ({voice_id[:8]}…) я слышу уже "
                f"{row['seen_count'] + 1}-й раз. Кто это?")
    return None


def confirm_candidate(con, voice_id: str, name: str) -> int:
    """Создатель ответил «это Николай» → рождается настоящая карта."""
    con.execute("DELETE FROM voice_candidates WHERE voice_id=?", (voice_id,))
    return create_person(con, name, voice_id=voice_id)


# ── БЛОК: наблюдения → оси и домены ───────────────────────────────
def add_karma(con, person_id: int, event: str, sign: int, domain: str,
              axis: str | None = None, delta: float = 3.0,
              comp: float = 0.0, обход_спарринга: bool = False) -> None:
    """Событие в журнал кармы + сдвиг оси/домена.
    Карма — это ЖУРНАЛ с историей, не одно число.

    comp — сдвиг КОМПЕТЕНТНОСТИ в домене, отдельно от доверия
    (2026-08-25). Это разные вещи и путать их нельзя: доверие — «не
    врёт ли», компетентность — «разбирается ли». Честный человек может
    ошибаться, лжец может быть мастером. Раньше competence не двигала
    ни одна функция пакета, и архетипы «мастер»/«наставник» были
    недостижимы в принципе — стенд поймал это пустым порогом.
    """
    # ПЕРЕХВАТ СПАРРИНГА (2026-08-25). add_karma — единственная дверь к
    # чертам: через неё идут доверие, компетентность и оси. Ловить режим
    # теста в десяти местах значит однажды забыть одиннадцатое, поэтому
    # ловим здесь. Запись при этом не теряется — она уходит в песочницу
    # целиком, чтобы в конце было видно, что записалось бы всерьёз.
    if not обход_спарринга:
        from . import spar
        сессия = spar.активен(con, person_id)
        if сессия is not None:
            spar.в_песочницу(con, сессия, "карма", event, sign, domain,
                             axis or "", delta, comp)
            return
    con.execute("INSERT INTO karma_journal(person_id, ts, event, sign, domain)"
                " VALUES (?,?,?,?,?)", (person_id, time.time(), event, sign, domain))
    delta = delta * config.KARMA_SCALE      # калибруемая чувствительность
    comp = comp * config.KARMA_SCALE
    con.execute("UPDATE person_domains SET trust = MAX(0, MIN(100, trust + ?)),"
                " evidence = evidence + 1, trend = trend*0.8 + ?*0.2"
                " WHERE person_id=? AND domain=?",
                (sign * delta, sign * delta, person_id, domain))
    if comp:
        con.execute("UPDATE person_domains SET competence ="
                    " MAX(0, MIN(100, competence + ?))"
                    " WHERE person_id=? AND domain=?", (comp, person_id, domain))
    if axis:
        con.execute("UPDATE person_axes SET value = MAX(0, MIN(100, value + ?))"
                    " WHERE person_id=? AND axis=?", (sign * delta, person_id, axis))
    con.commit()


def verified_claim(con, person_id: int, domain: str, ok: bool) -> None:
    """Суперсила Сайки: она МОЖЕТ проверять утверждения.
    Проверила → совпало → «проверяемость» и доверие в домене растут."""
    add_karma(con, person_id,
              f"проверка утверждения: {'подтвердилось' if ok else 'НЕ подтвердилось'}",
              1 if ok else -1, domain, axis="проверяемость",
              delta=2.0 if ok else 4.0,   # ложь бьёт больнее, чем правда греет
              comp=2.0 if ok else -3.0)   # и разбирается он в теме тоже хуже


def set_state(con, person_id: int, mood: dict) -> None:
    """Этаж СОСТОЯНИЕ: перезаписывается каждую сессию, не копится."""
    con.execute("INSERT OR REPLACE INTO person_state(person_id, ts, mood)"
                " VALUES (?,?,?)",
                (person_id, time.time(), json.dumps(mood, ensure_ascii=False)))
    con.commit()


# ── БЛОК: внутренний мир (гипотеза → факт) ────────────────────────
def observe_inner(con, person_id: int, text: str, event_id: int,
                  direct_quote: bool = False,
                  обход_спарринга: bool = False) -> None:
    """«Кажется, он боится X» — гипотеза 0.3. Прямые слова человека — сразу факт.
    Подтверждение — только новым событием (анти-«сам себя убедил»)."""
    # Вторая дверь к выводам о человеке — внутренний мир (страхи, цели,
    # табу). Спарринг закрывает и её: разыгранная сцена не должна
    # оставить в карте «боится X».
    from . import spar
    сессия = None if обход_спарринга else spar.активен(con, person_id)
    if сессия is not None:
        spar.в_песочницу(con, сессия, "внутренний мир", text)
        return
    row = con.execute("SELECT * FROM inner_world WHERE person_id=? AND text=?",
                      (person_id, text)).fetchone()
    now = time.time()
    if row is None:
        con.execute("INSERT INTO inner_world(person_id, text, status, confidence,"
                    " last_event_id, created, updated) VALUES (?,?,?,?,?,?,?)",
                    (person_id, text,
                     "fact" if direct_quote else "hypothesis",
                     1.0 if direct_quote else config.HYPOTHESIS_START,
                     event_id, now, now))
    elif row["last_event_id"] != event_id:
        conf = min(1.0, row["confidence"] + config.HYPOTHESIS_STEP)
        status = "fact" if (direct_quote or conf >= config.HYPOTHESIS_FACT_THRESHOLD) \
            else row["status"]
        con.execute("UPDATE inner_world SET confidence=?, status=?, last_event_id=?,"
                    " updated=? WHERE id=?", (conf, status, event_id, now, row["id"]))
    con.commit()


def contradict_inner(con, person_id: int, text: str) -> bool:
    """Обратный ход для внутреннего мира (2026-08-25).

    У semantic_facts он был с самого начала (contradict_fact), а у
    inner_world — нет, и это опаснее: там лежит самое личное (страхи,
    цели, табу). Один раз решив «он не любит созвоны», Сайка не могла
    передумать НИКОГДА — даже увидев обратное своими глазами.
    Люди меняются; память, которая этого не умеет, лепит из человека
    его прошлую версию и обращается с ней как с настоящей."""
    row = con.execute("SELECT * FROM inner_world WHERE person_id=? AND text=?",
                      (person_id, text)).fetchone()
    if row is None:
        return False
    conf = max(0.0, row["confidence"] - config.CONTRADICTION_STEP)
    status = "hypothesis" if conf < config.HYPOTHESIS_FACT_THRESHOLD else row["status"]
    con.execute("UPDATE inner_world SET confidence=?, status=?, updated=?"
                " WHERE id=?", (conf, status, time.time(), row["id"]))
    con.commit()
    return True


# ── БЛОК: пересчёт архетипов (ночью, только активным) ─────────────
def recompute_archetypes(con, since_ts: float = 0.0) -> None:
    """Архетип — производная от осей. Создателя не трогаем никогда.
    since_ts: пересчитываем только тех, у кого были события кармы
    после этой отметки (иначе через год молотим мёртвые души)."""
    if since_ts > 0:
        active = {r["person_id"] for r in con.execute(
            "SELECT DISTINCT person_id FROM karma_journal WHERE ts > ?",
            (since_ts,))}
    else:
        active = None                      # первый запуск — пересчитать всех
    for p in con.execute("SELECT * FROM persons WHERE is_creator=0").fetchall():
        if active is not None and p["id"] not in active:
            continue
        # .get с умолчанием, а не [] — иначе добавление новой оси или
        # домена в config роняет ВСЮ ночь на первой же старой карте
        # (схема создаётся через IF NOT EXISTS и задним числом строки
        # не дописывает). Ночь должна пережить расширение конфига.
        ax = {a: 50.0 for a in config.AXES}
        ax.update({r["axis"]: r["value"] for r in con.execute(
            "SELECT axis, value FROM person_axes WHERE person_id=?", (p["id"],))})
        dom = {r["domain"]: r for r in con.execute(
            "SELECT * FROM person_domains WHERE person_id=?", (p["id"],))}
        if not dom:
            continue
        best = max(dom.values(), key=lambda r: r["competence"])
        evid = sum(r["evidence"] for r in dom.values())

        # Правила сверху вниз: сначала красные флаги, потом заслуги
        if ax["честность"] < 20 and evid >= 5:
            arch = "манипулятор"        # системно врёт → карантин
        elif ax["конструктивность"] < 25 and evid >= 3:
            arch = "провокатор"         # изучать можно, следовать нельзя
        elif evid < 3:
            arch = "нейтрал"            # мало данных — не судим
        elif best["competence"] >= 85 and ax["честность"] >= 60 \
                and ax["саморефлексия"] >= 60:
            arch = "наставник"          # заслуживаемая роль (БЕЗ доступа к ядру!)
        elif best["competence"] >= 80:
            arch = "мастер"
        elif ax["проверяемость"] >= 70 and ax["честность"] >= 60:
            arch = "эксперт"
        elif ax["конструктивность"] >= 60 and ax["честность"] >= 50 and evid >= 6:
            arch = "лидер_мнений"
        elif ax["симпатия"] >= 70:
            arch = "развлекатель"       # приятен, но эпистемический вес ~0
        else:
            arch = "нейтрал"
        con.execute("UPDATE persons SET archetype=? WHERE id=?", (arch, p["id"]))
    con.commit()


# ── БЛОК: слияние карт (склейка идентичностей) ────────────────────
def merge_persons(con, keep_id: int, absorb_id: int) -> None:
    """«@nick в тг — это Николай»: авто-карта тега вливается в основную.
    Наблюдения НЕ теряются: журналы перевешиваются, оси и домены
    усредняются с весом по количеству улик (evidence)."""
    if keep_id == absorb_id:
        return
    # 1) Журналы и записи просто меняют владельца
    for table in ("karma_journal", "inner_world", "semantic_facts",
                  "promises", "identities"):
        con.execute(f"UPDATE {table} SET person_id=? WHERE person_id=?",
                    (keep_id, absorb_id))
    # person_state: PK по person_id → при конфликте побеждает более свежее
    ka = con.execute("SELECT ts FROM person_state WHERE person_id=?", (keep_id,)).fetchone()
    ab = con.execute("SELECT ts FROM person_state WHERE person_id=?", (absorb_id,)).fetchone()
    if ab and (not ka or ab["ts"] > ka["ts"]):
        con.execute("DELETE FROM person_state WHERE person_id=?", (keep_id,))
        con.execute("UPDATE person_state SET person_id=? WHERE person_id=?",
                    (keep_id, absorb_id))
    else:
        con.execute("DELETE FROM person_state WHERE person_id=?", (absorb_id,))
    con.execute("UPDATE relations SET person_a=? WHERE person_a=?", (keep_id, absorb_id))
    con.execute("UPDATE relations SET person_b=? WHERE person_b=?", (keep_id, absorb_id))
    # ИСТОРИЯ ПЕРЕЕЗЖАЕТ ВМЕСТЕ С ЧЕЛОВЕКОМ (2026-08-25). Журналы
    # перевешивались, а события — нет: после склейки «@nick — это
    # Николай» его эпизоды продолжали указывать на удалённую карту,
    # то есть часть жизни человека повисала в пустоте.
    con.execute("UPDATE raw_events SET person_id=? WHERE person_id=?",
                (keep_id, absorb_id))
    for ep in con.execute("SELECT id, persons FROM episodes"
                          " WHERE persons LIKE ?", (f"%{absorb_id}%",)).fetchall():
        ids = [i for i in (ep["persons"] or "").split(",") if i]
        новые = sorted({str(keep_id) if i == str(absorb_id) else i for i in ids},
                       key=int)
        if новые != ids:
            con.execute("UPDATE episodes SET persons=? WHERE id=?",
                        (",".join(новые), ep["id"]))
    # 2) Домены: среднее, взвешенное количеством улик
    for d in config.DOMAINS:
        a = con.execute("SELECT * FROM person_domains WHERE person_id=? AND domain=?",
                        (keep_id, d)).fetchone()
        b = con.execute("SELECT * FROM person_domains WHERE person_id=? AND domain=?",
                        (absorb_id, d)).fetchone()
        if a and b:
            wa, wb = max(a["evidence"], 0) + 1, max(b["evidence"], 0) + 1
            con.execute(
                "UPDATE person_domains SET trust=?, competence=?, evidence=?"
                " WHERE person_id=? AND domain=?",
                ((a["trust"] * wa + b["trust"] * wb) / (wa + wb),
                 (a["competence"] * wa + b["competence"] * wb) / (wa + wb),
                 a["evidence"] + b["evidence"], keep_id, d))
    # 3) Оси: простое среднее (улики по осям не трекаем)
    for ax in config.AXES:
        a = con.execute("SELECT value FROM person_axes WHERE person_id=? AND axis=?",
                        (keep_id, ax)).fetchone()
        b = con.execute("SELECT value FROM person_axes WHERE person_id=? AND axis=?",
                        (absorb_id, ax)).fetchone()
        if a and b:
            con.execute("UPDATE person_axes SET value=? WHERE person_id=? AND axis=?",
                        ((a["value"] + b["value"]) / 2, keep_id, ax))
    # 4) Поглощённая карта удаляется целиком
    for table in ("person_domains", "person_axes"):
        con.execute(f"DELETE FROM {table} WHERE person_id=?", (absorb_id,))
    con.execute("DELETE FROM persons WHERE id=?", (absorb_id,))
    con.commit()


# ── БЛОК: выборка карт для контекста LLM ──────────────────────────
# Храним ВСЕХ (решение Витали), но в промпт попадают только
# участники разговора + упомянутые. Остальные тысячи лежат молча.
def get_context_cards(con, active_ids: list[int],
                      mentioned_names: list[str] = ()) -> list[dict]:
    ids = set(active_ids)
    for name in mentioned_names:
        row = con.execute(
            "SELECT id FROM persons WHERE name LIKE ? LIMIT 1",
            (f"%{name}%",)).fetchone()
        if row:
            ids.add(row["id"])
    return [compact_card(con, pid) for pid in ids]


def compact_card(con, person_id: int) -> dict:
    """Короткая версия карты для промпта: только то, что влияет на ответ."""
    full = get_card(con, person_id)
    if not full:
        return {}
    top_domains = {d: v for d, v in full["домены"].items()
                   if abs(v["доверие"] - 30) > 5 or abs(v["компетентность"] - 50) > 5}
    из_качелей, портрет = [], {}
    try:
        from . import balance
        из_качелей = balance.для_карточки(con, person_id)
    except Exception:
        из_качелей = []
    круг, влияние, приёмы = {}, {}, []
    try:
        from . import circles
        г = circles.угадать_круг(con, person_id)
        круг = {"кто_он_владельцу": г["имя"],
                "уверенность": г["уверенность"],
                "сказано_владельцем": bool(г.get("назначен"))}
        в = circles.влияние(con, person_id)
        if в.get("есть"):
            # В ПРОМПТ УХОДИТ ФОРМУЛИРОВКА ПРО ВЛАДЕЛЬЦА, а не про
            # человека: «рядом с ним ты обычно…». Если подать это как
            # свойство собеседника, она начнёт тихо ссорить владельца с
            # его окружением на основании совпадения, а не причины.
            влияние = {"на_владельца": в["словами"],
                       "это_про_владельца_а_не_про_него": True}
    except Exception:
        круг, влияние = {}, {}
    try:
        from . import patterns
        приёмы = patterns.сводка(con, person_id)["паттерны"]
    except Exception:
        приёмы = []
    try:
        from . import temper
        п = temper.профиль(con, person_id)
        # в промпт идёт ТОЛЬКО готовый портрет: «рано говорить» это
        # ценный ответ для панели и мусор для промпта
        if п.get("готов"):
            портрет = {"октант": п["круг"]["октант"],
                       # в промпт уходит и живая формулировка: иначе она
                       # скажет «ты уступчивый», а это язык учебника, и
                       # человек услышит диагноз вместо наблюдения
                       "как_сказать": п["круг"].get("как_сказать"),
                       "выраженность": п["круг"]["выраженность"],
                       "темперамент": п.get("темперамент_живой")
                                      or п.get("темперамент"),
                       "уверенность": п["уверенность"],
                       "это_гипотеза": True}
    except Exception:
        портрет = {}
    return {"имя": full["имя"], "архетип": full["архетип"],
            "заметные_домены": top_domains,
            "состояние": full["состояние"],
            "внутренний_мир": full["внутренний_мир"][:5],
            "обещания": full["обещания"],
            # Разбор идёт в карточку, а не в импульс: он должен менять
            # то, КАК она с человеком говорит, а не превращаться в
            # монолог о нём. Подсказка себе, не досье.
            "качели": из_качелей,
            "круг": круг,
            "влияние": влияние,
            # ПРИЁМЫ РЕЧИ, А НЕ ДИАГНОЗЫ. Приём можно посчитать,
            # оспорить и прекратить; диагноз по репликам в микрофон не
            # ставится вообще — см. patterns.py.
            "приёмы_речи": [{"имя": p["имя"], "раз": p["раз"],
                             "из_фраз": p["из_фраз"]} for p in приёмы[:3]],
            # Портрет по речи. Помечен гипотезой не для скромности: по
            # литературе такие оценки слабые, и подавать их как факт
            # значит врать с точностью до ярлыка.
            "портрет": портрет}


# ── БЛОК: карточка целиком (для промпта Сайки) ────────────────────
def get_card(con, person_id: int) -> dict:
    p = con.execute("SELECT * FROM persons WHERE id=?", (person_id,)).fetchone()
    if not p:
        return {}
    card = {"имя": p["name"], "архетип": p["archetype"],
            "создатель": bool(p["is_creator"]),
            "домены": {}, "оси": {}, "состояние": None,
            "внутренний_мир": [], "обещания": [], "связи": []}
    for r in con.execute("SELECT * FROM person_domains WHERE person_id=?", (person_id,)):
        card["домены"][r["domain"]] = {"компетентность": round(r["competence"]),
                                        "доверие": round(r["trust"]),
                                        "тренд": round(r["trend"], 1)}
    for r in con.execute("SELECT * FROM person_axes WHERE person_id=?", (person_id,)):
        card["оси"][r["axis"]] = round(r["value"])
    st = con.execute("SELECT * FROM person_state WHERE person_id=?", (person_id,)).fetchone()
    if st:
        card["состояние"] = json.loads(st["mood"])
    for r in con.execute("SELECT * FROM inner_world WHERE person_id=?", (person_id,)):
        card["внутренний_мир"].append(
            f"[{r['status']} {r['confidence']:.2f}] {r['text']}")
    for r in con.execute("SELECT * FROM promises WHERE person_id=? AND status='открыто'",
                         (person_id,)):
        card["обещания"].append(f"{r['text']} (до {r['due']})")
    for r in con.execute("SELECT * FROM relations WHERE person_a=?", (person_id,)):
        other = con.execute("SELECT name FROM persons WHERE id=?",
                            (r["person_b"],)).fetchone()
        card["связи"].append(f"{r['kind']} → {other['name'] if other else '?'}")
    return card
