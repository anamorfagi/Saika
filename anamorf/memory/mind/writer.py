# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
  WRITER — дневная запись в L1 RAW. Дёшево и быстро,
  осмысление — ночью (consolidation.py).

  Биология: миндалина ставит тег важности В МОМЕНТ записи.
  salience = эмоция×W1 + новизна×W2 + бонус_владельца (+onboarding)
═══════════════════════════════════════════════════════════════════
"""
import time
from . import config, db


def compute_salience(emotion: float, novelty: float,
                     source_type: str, onboarding: bool = False) -> float:
    """Миндалина: насколько сильно записать это событие."""
    s = emotion * config.EMOTION_WEIGHT + novelty * config.NOVELTY_WEIGHT
    if source_type == "owner":
        s += config.SALIENCE_OWNER_BONUS           # голос владельца важнее фона
    if onboarding and source_type == "owner":
        s += config.ONBOARDING_SALIENCE_BONUS      # «критический период» первых дней
    return round(min(s, 1.0), 3)


def write_raw(con, text: str, source_type: str,
              person_id: int | None = None,
              emotion: float = 0.0, novelty: float = 0.5,
              темп: float | None = None, тон: float | None = None,
              пауза: float | None = None) -> int:
    """Единственная дверь в память. source_type обязателен — прививка от Сары.

    темп/тон/пауза необязательны: у текста из чата их нет и не будет.
    Портрет умеет и без них — просто с ними он точнее."""
    if source_type not in config.SOURCE_TYPES:
        raise ValueError(f"неизвестный source_type: {source_type}")
    sal = compute_salience(emotion, novelty, source_type, _is_onboarding(con))
    cur = con.execute(
        "INSERT INTO raw_events(ts, source_type, person_id, text, emotion,"
        " novelty, salience, темп, тон, пауза) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (time.time(), source_type, person_id, text, emotion, novelty, sal,
         темп, тон, пауза))
    con.commit()
    return cur.lastrowid


def _is_onboarding(con) -> bool:
    """Окно импринтинга считаем от ДАТЫ РОЖДЕНИЯ (meta), а не от RAW:
    RAW чистится каждые 36 часов, и по нему окно «открывалось бы» заново."""
    row = con.execute("SELECT value FROM meta WHERE key='birth_ts'").fetchone()
    if row is None:
        con.execute("INSERT INTO meta(key, value) VALUES ('birth_ts', ?)",
                    (str(time.time()),))
        con.commit()
        return True
    return (time.time() - float(row["value"])) < config.ONBOARDING_DAYS * 86400
