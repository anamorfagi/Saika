# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
  RECALL — вспоминание. Две биологические механики:

  1) Spaced repetition: каждый recall подкрепляет след —
     часто нужное само становится «долгосрочным».
  2) Реконсолидация: вызванный эпизод открывается на обновление,
     НО менять можно только эмоциональный тег и связи —
     сами факты (summary) заморожены. Иначе получим человеческий
     баг ложных воспоминаний в чистом виде.
═══════════════════════════════════════════════════════════════════
"""
import time
from . import config

# Здесь у тебя в проде — векторный поиск ChromaDB.
# В заглушке ищем подстрокой, механика подкрепления та же самая.


def recall(con, query: str, limit: int = 5) -> list[dict]:
    """Найти эпизоды и подкрепить их след (сам факт вспоминания = тренировка)."""
    rows = con.execute(
        "SELECT * FROM episodes WHERE summary LIKE ? ORDER BY strength DESC LIMIT ?",
        (f"%{query}%", limit)).fetchall()
    now = time.time()
    out = []
    for r in rows:
        con.execute(
            "UPDATE episodes SET recall_count=recall_count+1, last_recall=?,"
            " strength=MIN(1.0, strength + ?) WHERE id=?",
            (now, config.RECALL_BOOST, r["id"]))
        out.append({"id": r["id"], "пересказ": r["summary"],
                    "сила": round(r["strength"], 2),
                    "вспоминаний": r["recall_count"] + 1})
    con.commit()
    return out


def reconsolidate(con, episode_id: int,
                  new_emotion: float | None = None) -> bool:
    """Безопасная реконсолидация: после диалога, где эпизод был вызван,
    разрешаем обновить ТОЛЬКО эмоциональный тег. Summary неприкосновенен."""
    if new_emotion is None:
        return False
    con.execute("UPDATE episodes SET emotion=? WHERE id=?",
                (max(0.0, min(1.0, new_emotion)), episode_id))
    con.commit()
    return True
