# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
  DB — схема хранения. Уровни памяти:

  L0 SENSORY  — живёт в saika_ears (сюда не входит)
  L1 RAW      — сырой буфер дня (гиппокамп до сна)
  L2 EPISODES — события «что/когда/с кем/эмоция» (эпизодическая)
  L3 SEMANTIC — факты без времени (семантическая кора)
  L4 IDENTITY — values (READ-ONLY, файл) + narrative (append-only)

  + Карты личностей: черты / состояние / отношения / внутренний мир
═══════════════════════════════════════════════════════════════════
"""
import sqlite3
from . import config

SCHEMA = """
-- Служебное: дата рождения, время последней консолидации и т.п.
CREATE TABLE IF NOT EXISTS meta(
    key TEXT PRIMARY KEY, value TEXT
);

-- ═══ L1: RAW — сырые события дня ═══════════════════════════════
CREATE TABLE IF NOT EXISTS raw_events(
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,                -- unix time
    source_type TEXT NOT NULL,       -- owner/known_person/unknown_voice/web/self_thought
    person_id INTEGER,               -- NULL, если источник не человек/не опознан
    text TEXT NOT NULL,
    emotion REAL DEFAULT 0.0,        -- 0..1: эмоциональный заряд момента (с просодики)
    novelty REAL DEFAULT 0.0,        -- 0..1: новизна (из salience-слоя saika_ears)
    salience REAL NOT NULL,          -- итоговый вес записи (миндалина)
    -- КАК это было сказано. Слух всё это уже мерит на каждой фразе, но
    -- до памяти данные не доезжали — а темперамент читается по ним куда
    -- честнее, чем по одному тексту: «быстро, высоко, без пауз» и
    -- «медленно, ровно, с раздумьем» это разные люди при одних словах.
    темп REAL,                       -- слов в секунду
    тон REAL,                        -- основная частота, Гц
    пауза REAL,                      -- сколько молчал перед этой фразой, с
    processed INTEGER DEFAULT 0      -- 0 = ждёт ночной консолидации
);

-- ═══ L2: EPISODES — осмысленные события ════════════════════════
CREATE TABLE IF NOT EXISTS episodes(
    id INTEGER PRIMARY KEY,
    ts_start REAL, ts_end REAL,
    summary TEXT NOT NULL,           -- краткий пересказ (пишет LLM ночью)
    persons TEXT DEFAULT '',         -- id участников через запятую
    source_type TEXT NOT NULL,       -- преобладающий источник (для показа)
    sources TEXT DEFAULT '',         -- ВСЕ источники сцены через запятую:
                                     -- разговор двоих под работающий
                                     -- телевизор это одно событие с тремя
    emotion REAL DEFAULT 0.0,
    strength REAL NOT NULL,          -- сила следа (затухает по Эббингаузу)
    recall_count INTEGER DEFAULT 0,
    last_recall REAL                 -- когда последний раз вспоминали
);

-- ═══ L3: SEMANTIC — факты о мире и людях ═══════════════════════
-- ВАЖНО (правило ядра): сюда попадают ТОЛЬКО факты.
-- Ценностные обобщения («людям нельзя доверять») сюда НЕ пишутся —
-- фильтр стоит в consolidation.py.
CREATE TABLE IF NOT EXISTS semantic_facts(
    id INTEGER PRIMARY KEY,
    person_id INTEGER,               -- NULL = факт о мире, иначе — о человеке
    source_type TEXT DEFAULT '',     -- ОТ КОГО он узнан. Держать при факте,
                                     -- а не при эпизоде: эпизод бывает
                                     -- смешанный, и «чей это факт» тогда
                                     -- становится недоказуемым
    text TEXT NOT NULL,
    status TEXT DEFAULT 'hypothesis',-- hypothesis | fact
    confidence REAL DEFAULT 0.3,
    support_count INTEGER DEFAULT 0,
    contradict_count INTEGER DEFAULT 0,
    last_event_id INTEGER,           -- защита от «сам себя убедил»:
                                     -- подтверждение только НОВЫМ событием
    created REAL, updated REAL
);

-- ═══ КАРТЫ ЛИЧНОСТЕЙ ═══════════════════════════════════════════
CREATE TABLE IF NOT EXISTS persons(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    voice_id TEXT UNIQUE,            -- хэш биометрии из диаризации
    archetype TEXT DEFAULT 'нейтрал',
    is_creator INTEGER DEFAULT 0,    -- Создатель: вшит в веса (Виталя)
    is_owner INTEGER DEFAULT 0,      -- Владелец: кто установил прогу (импринтинг)
    entity_type TEXT DEFAULT 'human',-- human | bot | ai | unknown
    created REAL
);

-- ═══ ЦИФРОВЫЕ ИДЕНТИЧНОСТИ ═════════════════════════════════════
-- Один человек = много каналов: голос + tg + discord + twitch.
-- Тег ТОЧНЫЙ (не биометрия), поэтому карту можно создавать сразу,
-- но базовое доверие ниже: аккаунт могут увести/передать.
CREATE TABLE IF NOT EXISTS identities(
    id INTEGER PRIMARY KEY,
    person_id INTEGER NOT NULL,
    channel TEXT NOT NULL,           -- 'twitch' | 'discord' | 'telegram' | 'voice'
    tag TEXT NOT NULL,               -- точная метка платформы
    verified INTEGER DEFAULT 0,      -- Владелец подтвердил «это реально он»
    first_seen REAL, last_seen REAL,
    msg_count INTEGER DEFAULT 0,
    UNIQUE(channel, tag)
);

-- Этаж 1: ЧЕРТЫ (медленные) — компетентность/доверие ПО ДОМЕНАМ
CREATE TABLE IF NOT EXISTS person_domains(
    person_id INTEGER, domain TEXT,
    competence REAL DEFAULT 50, trust REAL DEFAULT 30,
    evidence INTEGER DEFAULT 0,
    trend REAL DEFAULT 0.0,          -- рос/падал за последние периоды
    PRIMARY KEY(person_id, domain)
);
CREATE TABLE IF NOT EXISTS person_axes(
    person_id INTEGER, axis TEXT, value REAL DEFAULT 50,
    PRIMARY KEY(person_id, axis)
);

-- Журнал кармы: события с датой и знаком (не одно число!)
CREATE TABLE IF NOT EXISTS karma_journal(
    id INTEGER PRIMARY KEY, person_id INTEGER, ts REAL,
    event TEXT, sign INTEGER,        -- +1 / -1
    domain TEXT
);

-- Этаж 2: СОСТОЯНИЕ (быстрое) — перезаписывается, не копится
CREATE TABLE IF NOT EXISTS person_state(
    person_id INTEGER PRIMARY KEY,
    ts REAL, mood TEXT               -- json: {устал:0.7, раздражён:0.2,...} с просодики
);

-- Этаж 3: ОТНОШЕНИЯ — граф + обещания + история с Сайкой
CREATE TABLE IF NOT EXISTS relations(
    person_a INTEGER, person_b INTEGER, kind TEXT,   -- 'друг', 'конфликт', 'коллега'
    PRIMARY KEY(person_a, person_b, kind)
);
CREATE TABLE IF NOT EXISTS promises(
    id INTEGER PRIMARY KEY, person_id INTEGER,
    text TEXT, due TEXT, status TEXT DEFAULT 'открыто'
);

-- ВНУТРЕННИЙ МИР: цели/страхи/табу/стиль — с уверенностью
CREATE TABLE IF NOT EXISTS inner_world(
    id INTEGER PRIMARY KEY, person_id INTEGER,
    text TEXT NOT NULL,
    status TEXT DEFAULT 'hypothesis',
    confidence REAL DEFAULT 0.3,
    last_event_id INTEGER,
    created REAL, updated REAL
);

-- ═══ ОЧКИ ЗА БАЛАНС ════════════════════════════════════════════
-- Оценка ЕЁ работы за день по каждому человеку, а не оценка людей.
-- Ключ (день, person_id) — чтобы повторный запуск ночи не платил
-- дважды: ночь может сорваться и запуститься снова.
CREATE TABLE IF NOT EXISTS score(
    день INTEGER, person_id INTEGER,
    перекос_конец REAL, улик INTEGER, проверок INTEGER,
    очки INTEGER, почему TEXT,
    PRIMARY KEY(день, person_id)
);

-- ═══ КРУГИ ОКРУЖЕНИЯ ═══════════════════════════════════════════
-- Кто этот человек ВЛАДЕЛЬЦУ: семья, друзья, работа, знакомые.
-- Угадка живёт здесь же, где и назначение: «назначен» отличает то,
-- что владелец сказал прямо, от того, что система предположила, —
-- и второе никогда не затирает первое.
CREATE TABLE IF NOT EXISTS circle(
    person_id INTEGER PRIMARY KEY,
    круг INTEGER,                    -- 0 владелец … 5 чужие
    уверенность REAL DEFAULT 0,
    основания TEXT,                  -- на чём построена догадка
    назначен INTEGER DEFAULT 0,      -- 1 = владелец сказал прямо
    обновлено REAL
);

-- ═══ ТЕМПЕРАМЕНТ: портрет по речи ══════════════════════════════
-- Отдельно от person_axes нарочно. Там оси — это ОЦЕНКИ САЙКИ
-- (честность, симпатия), здесь — описание человека (Big Five). Одна
-- таблица на два разных смысла однажды даст ответ «доброжелательность
-- 40» на вопрос «доверяю ли я ему».
CREATE TABLE IF NOT EXISTS temper(
    person_id INTEGER, ось TEXT,
    значение REAL,                   -- 0..100
    уверенность REAL DEFAULT 0,      -- 0..TEMPER_MAX_CONFIDENCE
    наблюдений INTEGER DEFAULT 0,    -- фраз, на которых это посчитано
    обновлено REAL,
    PRIMARY KEY(person_id, ось)
);

-- ═══ СПАРРИНГ: стресс-тесты владельца ══════════════════════════
-- Владелец нарочно устраивает сцены, чтобы проверить её поведение.
-- Без песочницы разыгранная грубость записалась бы ему в характер, и
-- через месяц карта владельца стала бы картой его же испытаний.
CREATE TABLE IF NOT EXISTS spar_sessions(
    id INTEGER PRIMARY KEY, person_id INTEGER, зачем TEXT,
    начало REAL, конец REAL
);
CREATE TABLE IF NOT EXISTS spar_journal(
    id INTEGER PRIMARY KEY, session_id INTEGER, ts REAL,
    вид TEXT,                        -- карма | вспышка | флаг
    описание TEXT, sign INTEGER, domain TEXT, axis TEXT,
    delta REAL, comp REAL,
    вердикт TEXT,                    -- перебор | в_точку | недобор |
                                     -- это_было_всерьёз (пусто = не размечено)
    зачтено INTEGER DEFAULT 0        -- перенесено в настоящую карту руками
);

-- Буфер кандидатов: повторяющиеся неопознанные голоса
CREATE TABLE IF NOT EXISTS voice_candidates(
    voice_id TEXT PRIMARY KEY,
    seen_count INTEGER DEFAULT 1,
    first_ts REAL, last_ts REAL,
    asked INTEGER DEFAULT 0          -- уже спрашивали Создателя «кто это?»
);
"""


# Схема создаётся через CREATE TABLE IF NOT EXISTS — новые СТОЛБЦЫ в уже
# существующую базу она не дописывает, и на живой машине это выглядит как
# «на чистой всё работает, у владельца всё падает». Поэтому недостающие
# столбцы доливаются руками; ALTER TABLE ADD COLUMN в SQLite дешёвый.
MIGRATIONS = [
    ("episodes", "sources", "TEXT DEFAULT ''"),
    ("semantic_facts", "source_type", "TEXT DEFAULT ''"),
    ("spar_journal", "вердикт", "TEXT"),
    ("raw_events", "темп", "REAL"),
    ("raw_events", "тон", "REAL"),
    ("raw_events", "пауза", "REAL"),
]


def _migrate(con) -> None:
    for table, column, decl in MIGRATIONS:
        есть = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        if есть and column not in есть:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    con.commit()


def connect() -> sqlite3.Connection:
    """Открыть базу, создать схему при первом запуске."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _migrate(con)
    return con
