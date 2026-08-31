# -*- coding: utf-8 -*-
"""МОСТ: конец слухового тракта → L1 RAW разума (anamorf/memory/mind).

Куда врезано: anamorf/main.py, voice_phrase() — сразу после стенограммы.
Это последняя точка, где про фразу известно ВСЁ: текст после пересчёта,
кто сказал (voiceprint), с какой уверенностью, и как это звучало
(просодика). И это ещё ДО развилок «наблюдаю» и «отвечаю только
владельцу»: память обязана помнить всё услышанное, включая то, на что
Сайка молчит. Иначе в памяти останется половина жизни — та, где
говорили с ней.

Три правила моста:
  1. Он не имеет права уронить слух. Любая ошибка — в debug-лог и мимо.
  2. Он ничего не решает. Значимость считает mind.writer
     (миндалина), мост только подаёт ей честные входы.
  3. source_type берётся из БИОМЕТРИИ, а не из текста — это и есть
     прививка от «телевизор сказал = владелец сказал».

Ручки в config.json: memory2.*
"""
import logging
import re
import threading
import time
from collections import deque
from difflib import SequenceMatcher

from anamorf.config import CFG, DATA_ROOT

log = logging.getLogger(__name__)

# ── Куда кладём базу ──────────────────────────────────────────────
# Пакет по умолчанию пишет в ./saika_data относительно текущей папки —
# для приложения это лотерея (служба стартует откуда угодно, а сборка
# вообще заменяет папку кода при обновлении). Прибиваем к DATA_ROOT,
# туда же, где живут остальные данные человека.
_DATA_DIR = DATA_ROOT / "data" / "memory2"

_local = threading.local()      # sqlite-соединение живёт по потоку
_lock = threading.Lock()
_pid_cache: dict = {}           # имя из реестра голосов → person_id
_recent: deque = deque(maxlen=64)   # свежие фразы для оценки новизны
_последняя = {"ts": 0.0}            # когда слышали прошлую фразу — для паузы
_РЕЦЕПТ: dict = {}                  # person_id → активная линия поведения
_STATE = {"broken": False}      # пакет не завёлся — больше не дёргаем

_WORD = re.compile(r"[^\wёЁ]+", re.UNICODE)


def _pkg():
    """Ленивый импорт пакета с подменой путей. Один раз за процесс."""
    mod = getattr(_local, "pkg", None)
    if mod is not None:
        return mod
    from anamorf.memory import mind as sm
    sm.config.DATA_DIR = _DATA_DIR
    sm.config.DB_PATH = _DATA_DIR / "memory.db"
    sm.config.VALUES_PATH = _DATA_DIR / "identity_values.json"
    sm.config.NARRATIVE_PATH = _DATA_DIR / "narrative.log"
    _local.pkg = sm
    return sm


def _con():
    """Соединение текущего потока. sqlite нельзя таскать между потоками,
    а слух живёт в своём — поэтому по одному на поток, не одно общее."""
    con = getattr(_local, "con", None)
    if con is None:
        sm = _pkg()
        con = sm.db.connect()
        _local.con = con
    return con


# ── Кто это был ───────────────────────────────────────────────────
def _person_id(con, name: str, is_owner: bool) -> int:
    """Имя из реестра голосов → карта личности. Карта заводится один раз."""
    key = (name, is_owner)
    with _lock:
        pid = _pid_cache.get(key)
    if pid is not None:
        return pid
    sm = _pkg()
    row = con.execute("SELECT id FROM persons WHERE name=?", (name,)).fetchone()
    if row is None:
        pid = sm.persons.create_person(con, name, is_creator=is_owner)
        if is_owner:
            con.execute("UPDATE persons SET is_owner=1 WHERE id=?", (pid,))
            con.commit()
    else:
        pid = int(row["id"])
    with _lock:
        _pid_cache[key] = pid
    return pid


def _source_and_person(con, r: dict):
    """Разложить фразу на (source_type, person_id, вопрос-Создателю).

    Владелец — только по золотой метке отпечатка. Знакомый — только при
    уверенном узнавании. Всё остальное, включая разбивку по тону
    (by_pitch_group — это разметка, а не узнавание), считается чужим
    голосом и карту НЕ создаёт: он копится в буфере кандидатов и на
    третий раз превращается в вопрос «кто это?»."""
    name = (r.get("speaker") or "").strip()
    conf = float(r.get("speaker_conf") or 0)
    named = bool(name) and not r.get("by_pitch_group")
    if r.get("speaker_owner") and named:
        return "owner", _person_id(con, name, True), None
    min_conf = float(CFG.get("mind.known_min_conf", 0.6))
    if named and conf >= min_conf:
        return "known_person", _person_id(con, name, False), None
    ask = None
    if name:                      # хоть какая-то ручка, чтобы считать встречи
        try:
            ask = _pkg().persons.hear_unknown_voice(con, name)
        except Exception as e:
            log.debug("буфер кандидатов: %s", e)
    return "unknown_voice", None, ask


# ── Как это звучало ───────────────────────────────────────────────
def _число(x):
    """Слух отдаёт нули там, где померить не вышло. Ноль в темпе речи —
    это не «говорил бесконечно медленно», это «не знаю», и в базе он
    должен быть NULL, иначе портрет посчитает его за измерение."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _emotion(pr: dict) -> float:
    """Эмоциональный заряд 0..1 из просодики — громкость плюс отход тона
    от собственного спокойного диапазона говорящего. Нарочно грубо: тонкие
    оттенки по двум числам были бы выдумкой (см. transcript.mood_of)."""
    energy = float(pr.get("energy") or 0)
    if not energy:
        return 0.0
    pitch = float(pr.get("pitch") or 0)
    lo, hi = float(pr.get("plo") or 0), float(pr.get("phi") or 0)
    rel = 0.5
    if hi > lo > 0 and pitch:
        rel = min(1.0, max(0.0, (pitch - lo) / max(1e-6, hi - lo)))
    return round(min(1.0, 0.6 * energy + 0.4 * abs(rel - 0.5) * 2), 3)


def _novelty(text: str) -> float:
    """Новизна 0..1: насколько фраза не похожа на то, что уже слышали.

    Дешёвая защита от телевизора и повторов — заезженная реплика получает
    низкий вес и умрёт при ночной чистке, не съев место у живого разговора."""
    norm = " ".join(w for w in _WORD.split(text.lower()) if w)
    if not norm:
        return 0.0
    best = 0.0
    with _lock:
        seen = list(_recent)
        _recent.append(norm)
    for old in seen:
        best = max(best, SequenceMatcher(None, norm, old).ratio())
        if best > 0.95:
            break
    return round(max(0.0, 1.0 - best), 3)


# ── Единственная дверь наружу ─────────────────────────────────────
def remember_heard(r: dict, prosody: dict | None = None) -> int | None:
    """Положить услышанную фразу в L1 RAW. Возвращает id записи или None.

    prosody можно передать готовой (её уже считает стенограмма) — иначе
    возьмём сами. Молчит про любые свои беды: слух важнее памяти, и
    падение здесь не должно стоить человеку ответа."""
    if _STATE["broken"] or not CFG.get("mind.enabled", True):
        return None
    try:
        text = (r.get("text") or "").strip()
        if len(text) < int(CFG.get("mind.min_chars", 2)):
            return None
        con = _con()
        source_type, person_id, ask = _source_and_person(con, r)
        pr = prosody
        if pr is None:
            try:
                from anamorf import voiceprint
                pr = voiceprint.prosody() if hasattr(voiceprint, "prosody") else {}
            except Exception:
                pr = {}
        # КАК это было сказано. Слух уже посчитал темп и тон на этой
        # фразе, а пауза берётся от прошлой услышанной: «ответил сразу»
        # и «думал десять секунд» — разные люди при одних и тех же
        # словах, и до сих пор эта разница просто пропадала.
        сейчас = time.time()
        пауза = None
        if _последняя["ts"]:
            пауза = round(min(600.0, сейчас - _последняя["ts"]), 2)
        _последняя["ts"] = сейчас
        rid = _pkg().writer.write_raw(
            con, text, source_type, person_id=person_id,
            emotion=_emotion(pr), novelty=_novelty(text),
            темп=_число(r.get("rate_wps")), тон=_число(r.get("voice_hz")),
            пауза=пауза)
        if ask:
            log.info("Память: %s", ask)
        return rid
    except Exception as e:
        # Один раз громко, дальше тихо: если пакет не встал, лог не должен
        # превращаться в стену из одинаковых строк на каждую фразу.
        if not _STATE.get("warned"):
            _STATE["warned"] = True
            log.warning("Разум не пишет (дальше молча): %s", e)
        else:
            log.debug("разум: %s", e)
        return None


def stats() -> dict:
    """Что накопилось — для панели и для тестов."""
    try:
        con = _con()
        raw = con.execute("SELECT COUNT(*) c, AVG(salience) s FROM raw_events").fetchone()
        одно = lambda sql: con.execute(sql).fetchone()[0]      # noqa: E731
        row = con.execute("SELECT value FROM meta WHERE key='last_night'").fetchone()
        return {"сырьё": raw["c"], "значимость_средняя": round(raw["s"] or 0, 3),
                "эпизоды": одно("SELECT COUNT(*) FROM episodes"),
                "факты": одно("SELECT COUNT(*) FROM semantic_facts WHERE status='fact'"),
                "гипотезы": одно("SELECT COUNT(*) FROM semantic_facts"
                                 " WHERE status='hypothesis'"),
                "люди": одно("SELECT COUNT(*) FROM persons"),
                "неопознанные_голоса": одно("SELECT COUNT(*) FROM voice_candidates"),
                "просрочено": одно("SELECT COUNT(*) FROM promises"
                                   " WHERE status='просрочено'"),
                "последняя_ночь": float(row["value"]) if row else 0.0,
                "база": str(_DATA_DIR / "memory.db"),
                "включена": bool(CFG.get("mind.enabled", True))}
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════
#  НОЧЬ, СВОИ РЕПЛИКИ И ЧАСЫ ПАМЯТИ
#  Всё, чем эта память включается в общую жизнь программы.
# ══════════════════════════════════════════════════════════════════
def remember_self(text: str) -> int | None:
    """Свой собственный ответ — тоже событие дня (source_type=self_thought).

    Без этого в памяти лежат одни вопросы: ночь сшивает эпизод из фраз
    человека, а что она на них ответила — неизвестно, и через неделю
    «поговорили про сборку» невозможно отличить от «он спросил, я
    отмолчалась». Учиться фактам у самой себя при этом нельзя —
    self_thought не входит в config.FACT_SOURCES, иначе получится
    классическое «сама придумала, сама поверила».
    """
    if _STATE["broken"] or not CFG.get("mind.enabled", True):
        return None
    try:
        text = (text or "").strip()
        if len(text) < int(CFG.get("mind.min_chars", 2)):
            return None
        return _pkg().writer.write_raw(
            _con(), text, "self_thought", person_id=None,
            emotion=0.0, novelty=_novelty(text))
    except Exception as e:
        log.debug("разум (своя реплика): %s", e)
        return None


def run_night() -> dict:
    """Сон: RAW → эпизоды → факты → чистка → архетипы → просрочки.
    Зовётся из ночного потока и из панели («поспать сейчас»)."""
    return _pkg().consolidation.run_night(_con())


def _night_loop():
    """Ночной поток. Не «раз в сутки по таймеру», а «в тихий час, если
    с прошлого сна прошло достаточно»: машину выключают, будят, переводят
    время, и жёсткий интервал в такой жизни пропускает ночи целыми
    неделями. Проверка каждые 10 минут стоит ноль."""
    import datetime
    while True:
        try:
            time.sleep(600)
            if not CFG.get("mind.enabled", True):
                continue
            con = _con()
            row = con.execute(
                "SELECT value FROM meta WHERE key='last_night'").fetchone()
            прошло_ч = (time.time() - float(row["value"])) / 3600 if row else 1e9
            час = datetime.datetime.now().hour
            тихо = час == int(CFG.get("mind.night_hour", 4))
            давно = прошло_ч >= float(CFG.get("mind.night_max_gap_h", 30))
            if not (тихо and прошло_ч >= 20) and not давно:
                continue
            отчёт = run_night()
            log.info("Разум, ночь: %s", отчёт)
        except Exception as e:
            log.warning("разум, ночь сорвалась: %s", e)


def start_night():
    """Запустить ночной поток один раз за процесс."""
    if _STATE.get("night") or not CFG.get("mind.enabled", True):
        return
    _STATE["night"] = True
    threading.Thread(target=_night_loop, daemon=True,
                     name="memory2-night").start()


def due_promises(limit: int = 3) -> list[dict]:
    """Часы памяти: обещания, срок которых истёк, а разговора не было.

    Это единственное место, где память просит СЛОВА, а не отдаёт данные:
    просроченное обещание — законный повод заговорить первой. Отдаём
    по одному-двум, иначе она превратится в коллектора."""
    if _STATE["broken"] or not CFG.get("mind.enabled", True):
        return []
    try:
        rows = _con().execute(
            "SELECT pr.id, pr.text, pr.due, p.name FROM promises pr"
            " LEFT JOIN persons p ON p.id = pr.person_id"
            " WHERE pr.status='просрочено' ORDER BY pr.due LIMIT ?",
            (limit,)).fetchall()
        out = []
        for r in rows:
            try:
                дней = max(0, int((time.time() - float(r["due"])) / 86400))
            except (TypeError, ValueError):
                дней = 0
            out.append({"id": r["id"], "кто": r["name"] or "кто-то",
                        "что": r["text"], "дней": дней})
        return out
    except Exception as e:
        log.debug("разум (просрочки): %s", e)
        return []


def mark_reminded(ids) -> None:
    """Напомнила — больше не поднимаем. Обещание не закрыто, но и не висит
    поводом заговорить: закрыть его может только человек."""
    try:
        con = _con()
        for i in ids:
            con.execute("UPDATE promises SET status='напомнено' WHERE id=?", (i,))
        con.commit()
    except Exception as e:
        log.debug("разум (пометка напоминания): %s", e)


# ══════════════════════════════════════════════════════════════════
#  L4: ЯДРО ЦЕННОСТЕЙ И ЦИТАТНИК
#  Ценности — пять жёстких строк, которые не меняются никогда.
#  Цитатник — путеводитель хорошего тона: мягче, шире и однажды
#  станет её собственным. Обе вещи рождаются один раз и живут в
#  файлах рядом с базой, а не в ней: файл можно положить под
#  read-only средствами ОС, строку в SQLite — нет.
# ══════════════════════════════════════════════════════════════════
def ensure_identity() -> dict:
    """Родить L4, если его ещё нет. Зовётся один раз при запуске."""
    try:
        sm = _pkg()
        накатано = sm.tuning.применить()   # сдвиги поверх умолчаний
        if накатано:
            log.info("Калибровка накатана: %s", накатано)
        sm.identity.init_values()
        родился = sm.codex.init()
        if родился:
            log.info("Цитатник заведён: %d строк", len(sm.codex.всё()))
        return {"ok": True, "цитатник_создан": родился}
    except Exception as e:
        log.warning("L4 не поднялся: %s", e)
        return {"ok": False, "error": str(e)}


def config_idle_window(sm) -> int:
    """Сколько последних фраз смотреть на «крутится ли на месте»."""
    return max(8, int(getattr(sm.config, "IDLE_MIN_PHRASES", 6)) * 3)


def person_id_of(имя: str) -> int | None:
    """Имя из реестра голосов → id карты, если она уже заведена.

    Отдельно от _person_id: тот СОЗДАЁТ карту, а этот только смотрит.
    Заводить человека ради того, чтобы спросить, как с ним держаться, —
    значит плодить пустые карты на каждый ход."""
    try:
        r = _con().execute("SELECT id FROM persons WHERE name=?",
                           (str(имя),)).fetchone()
        return int(r["id"]) if r else None
    except Exception:
        return None


def stance_block(person_id: int | None, реплика: str = "") -> str:
    """Как держаться с ЭТИМ человеком — блок промпта на текущий ход.

    Пусто в подавляющем большинстве случаев, и это правильно: особый
    стиль нужен там, где разговор перекосило, а не всегда."""
    if _STATE["broken"] or not person_id or not CFG.get("mind.stance", True):
        return ""
    try:
        sm = _pkg()
        con = _con()
        карта = sm.persons.compact_card(con, int(person_id))
        приёмы = sm.patterns.сводка(con, int(person_id))["паттерны"]
        блок = sm.stance.для_промпта(карта, приёмы)
        # Лестница — про ЭТУ секунду, а не про портрет: она включается
        # от конкретной реплики и остывает сама, если наезда больше нет.
        шаг = sm.ladder.ступень(int(person_id),
                                sm.stance.наезд_сейчас(реплика or ""))
        лест = sm.ladder.для_промпта(шаг)
        # «Иногда лучше промолчать, и шелуха отпадёт сама» — оценка
        # РАНЬШЕ любой ступени: сначала есть ли ради чего держаться.
        последние = con.execute(
            "SELECT text FROM raw_events WHERE person_id=?"
            " ORDER BY ts DESC LIMIT ?",
            (int(person_id), config_idle_window(sm))).fetchall()
        итог_х = sm.ladder.вхолостую(последние, шаг)
        тишина = sm.ladder.молчание_для_промпта(итог_х)
        рец = sm.stance.рецепт(карта, приёмы, шаг,
                               bool(итог_х.get("вхолостую")))
        _РЕЦЕПТ[int(person_id)] = рец      # для панели: что включено сейчас
        шапка = (f"### Сейчас ты держишься линии «{рец['имя']}»\n"
                 f"Почему: {рец['почему']}. Линия одна за раз — остальное "
                 f"подстраивается под неё, а не спорит с ней. Если "
                 f"спросят, чем руководствуешься, можешь ответить прямо.")
        ходы = sm.moves.для_промпта(рец["ключ"])
        куски = [x for x in (шапка, блок, лест, тишина, ходы) if x]
        return "\n".join(куски)
    except Exception as e:
        log.debug("стиль общения: %s", e)
        return ""


def codex_block(реплика: str = "", коротко: bool = False) -> str:
    """Строка цитатника к случаю — в промпт. Молчит при любой беде."""
    if _STATE["broken"] or not CFG.get("mind.codex", True):
        return ""
    try:
        return _pkg().codex.для_промпта(реплика, коротко=коротко)
    except Exception as e:
        log.debug("цитатник: %s", e)
        return ""


def codex_state() -> dict:
    """Свод целиком + возраст и право на правку — для панели."""
    try:
        sm = _pkg()
        можно, осталось = sm.codex.может_переписывать(_con())
        return {"цитаты": sm.codex.всё(),
                "целостность": sm.codex.load().get("_целостность"),
                "прожито_дней": round(sm.codex.возраст(_con()), 1),
                "может_переписывать": можно,
                "дней_до_права": осталось,
                "журнал": sm.codex.история(20)}
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════
#  СПАРРИНГ И КАРТИНА РАЗУМА
#  Всё, что нужно панели «Разум»: люди, качели, лента и ручки весов.
# ══════════════════════════════════════════════════════════════════
def spar_start(person_id: int, зачем: str = "") -> dict:
    """Открыть стресс-тест: выводы о человеке уходят в песочницу."""
    try:
        sm = _pkg()
        sid = sm.spar.начать(_con(), int(person_id), зачем)
        log.info("Спарринг открыт (сессия %s): %s", sid, зачем or "без повода")
        return {"ok": True, **sm.spar.состояние(_con())}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def spar_stop() -> dict:
    """Закрыть и показать, что записалось бы всерьёз."""
    try:
        return {"ok": True, **_pkg().spar.закончить(_con())}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def spar_state() -> dict:
    try:
        return _pkg().spar.состояние(_con())
    except Exception as e:
        return {"идёт": False, "error": str(e)}


def spar_calibrate(запись_id: int, вердикт: str, почему: str = "") -> dict:
    """Поправка по одной реакции: перебор / в точку / недобор.
    Двигает чувствительность Сайки, а не карту человека."""
    try:
        return _pkg().spar.калибровать(_con(), int(запись_id), вердикт, почему)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def set_circle(person_id: int, круг: int) -> dict:
    """Владелец поправил догадку о круге. Его слово выше эвристики."""
    try:
        return _pkg().circles.назначить_круг(_con(), int(person_id), int(круг))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def score_state() -> dict:
    """Копилка опыта: за день, всего, серия. Для панели и будущих игр."""
    try:
        sm = _pkg()
        con = _con()
        return {**sm.score.всего(con), "по_людям": sm.score.по_людям(con)}
    except Exception as e:
        return {"error": str(e)}


def tuning_state() -> dict:
    """Где стоят ручки: родное значение, текущее, сколько раз двигали."""
    try:
        sm = _pkg()
        return {"ручки": sm.tuning.состояние(), "журнал": sm.tuning.история(30)}
    except Exception as e:
        return {"error": str(e)}


def tuning_set(имя: str, значение, почему: str = "") -> dict:
    try:
        return _pkg().tuning.задать(имя, значение, почему)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tuning_reset(имя: str | None = None) -> dict:
    try:
        return _pkg().tuning.сброс(имя)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def mind(limit_people: int = 12, limit_tape: int = 40) -> dict:
    """Вся картина одним запросом — для панели «Разум».

    Один вызов, а не пять: панель рисует связанную сцену (человек ↔ его
    качели ↔ фразы, из которых они выросли), и подтягивать это тремя
    запросами значит однажды нарисовать чужие качели над чужой головой.
    """
    if _STATE["broken"]:
        return {"error": "память не поднялась"}
    try:
        sm = _pkg()
        con = _con()
        люди = []
        for p in con.execute(
                "SELECT id, name, archetype, is_owner, is_creator, entity_type"
                " FROM persons ORDER BY is_creator DESC, is_owner DESC, id"
                " LIMIT ?", (limit_people,)):
            в = sm.balance.весы(con, p["id"])
            в.pop("_улики", None)
            домены = {r["domain"]: {"доверие": round(r["trust"]),
                                    "компетентность": round(r["competence"]),
                                    "улик": r["evidence"],
                                    "тренд": round(r["trend"], 1)}
                      for r in con.execute(
                          "SELECT * FROM person_domains WHERE person_id=?",
                          (p["id"],))}
            оси = {r["axis"]: round(r["value"]) for r in con.execute(
                "SELECT * FROM person_axes WHERE person_id=?", (p["id"],))}
            люди.append({
                "id": p["id"], "имя": p["name"], "архетип": p["archetype"],
                "свой": bool(p["is_owner"] or p["is_creator"]),
                "тип": p["entity_type"], "домены": домены, "оси": оси,
                "весы": в, "разбор": sm.balance.разбор(con, p["id"]),
                "портрет": sm.temper.профиль(con, p["id"]),
                "маркеры": sm.temper.на_чём_основано(con, p["id"]),
                "круг": sm.circles.угадать_круг(con, p["id"]),
                "влияние": sm.circles.влияние(con, p["id"]),
                "приёмы": sm.patterns.сводка(con, p["id"]),
                "стиль": sm.stance.для_панели(
                    sm.persons.compact_card(con, p["id"]),
                    sm.patterns.сводка(con, p["id"])["паттерны"])})

        лента = [{"ts": r["ts"], "текст": r["text"][:120],
                  "источник": r["source_type"], "кто": r["person_id"],
                  "эмоция": round(r["emotion"], 2),
                  "новизна": round(r["novelty"], 2),
                  "значимость": round(r["salience"], 3)}
                 for r in con.execute(
                     "SELECT * FROM raw_events ORDER BY ts DESC LIMIT ?",
                     (limit_tape,))]

        return {"люди": люди, "лента": лента[::-1],
                "окружение": sm.circles.карта_окружения(con),
                "спарринг": sm.spar.состояние(con),
                "метки": {"эмоция": sm.config.EMOTION_WEIGHT,
                          "новизна": sm.config.NOVELTY_WEIGHT,
                          "бонус_владельца": sm.config.SALIENCE_OWNER_BONUS,
                          "порог_забвения": sm.config.SALIENCE_MIN_KEEP},
                "ручки": sm.tuning.состояние(),
                "очки": sm.score.всего(con),
                "ходы": sm.moves.описание(),
                "сводка": stats()}
    except Exception as e:
        log.debug("картина разума: %s", e)
        return {"error": str(e)}


def set_weights(эмоция=None, новизна=None, бонус=None, порог=None) -> dict:
    """Крутилки эмоциональных меток — вживую, без перезапуска.

    Меняют, КАК миндалина взвешивает будущие фразы. Уже записанное не
    пересчитывается: прошлое взвешено тем, чем взвешивалось, и
    переписывать его задним числом значит подделывать собственную
    биографию под сегодняшние настройки.
    """
    try:
        sm = _pkg()
        c = sm.config
        # через tuning, а не напрямую в config: иначе настройка живёт до
        # перезапуска и обновление кода стирает её вместе с умолчаниями
        for имя, знач in (("вес_эмоции", эмоция), ("вес_новизны", новизна),
                          ("бонус_владельца", бонус),
                          ("порог_забвения", порог)):
            if знач is not None:
                sm.tuning.задать(имя, знач, "ползунок в панели «Разум»")
        return {"ok": True, "эмоция": c.EMOTION_WEIGHT,
                "новизна": c.NOVELTY_WEIGHT,
                "бонус_владельца": c.SALIENCE_OWNER_BONUS,
                "порог_забвения": c.SALIENCE_MIN_KEEP}
    except Exception as e:
        return {"ok": False, "error": str(e)}
