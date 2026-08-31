# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
  ONBOARDING + DIGITAL — два новых входа в систему личностей.

  1) Первый запуск: Сайка спрашивает имя → Владелец (is_owner=1),
     первый уверенный голос привязывается к нему = ИМПРИНТИНГ.
     Создатель (Виталя) ≠ Владелец: Создатель вшит в веса/ценности,
     Владелец — тот, на кого копия импринтится при рождении.

  2) Цифровые каналы (Twitch/Discord/Telegram): тег ТОЧНЫЙ,
     поэтому карта создаётся автоматически, но:
     • базовое доверие ниже голосового (аккаунт можно увести);
     • entity_type определяется эвристиками: human / bot / ai.
═══════════════════════════════════════════════════════════════════
"""
import time
from . import config, persons

# Доверие по типу канала: биометрия > верифицированный тег > просто тег
CHANNEL_BASE_TRUST = {"voice": 30, "telegram": 20, "discord": 15, "twitch": 10}


# ── БЛОК 1: первый запуск (импринтинг на Владельца) ───────────────
def first_run(con, ask=input, say=print) -> int:
    """Скрипт первого запуска. ask/say подменяемы — в UE5 это будет
    голосовой диалог, здесь консоль. Возвращает id Владельца."""
    row = con.execute("SELECT id FROM persons WHERE is_owner=1").fetchone()
    if row:
        return row["id"]                      # онбординг уже прошёл
    say("Привет! Я Сайка. Кажется, мы ещё не знакомы.")
    name = ""
    while not name.strip():
        name = ask("Как тебя зовут? → ")
    pid = persons.create_person(con, name.strip())
    con.execute("UPDATE persons SET is_owner=1 WHERE id=?", (pid,))
    con.commit()
    say(f"Приятно познакомиться, {name.strip()}! "
        f"Первый голос, который я услышу уверенно, я запомню как твой.")
    return pid


def bind_first_voice(con, voice_id: str) -> bool:
    """Первый УВЕРЕННЫЙ голос после онбординга → голос Владельца.
    Вызывается из saika_ears, когда диаризация даёт стабильный кластер."""
    owner = con.execute(
        "SELECT id, voice_id FROM persons WHERE is_owner=1").fetchone()
    if owner is None or owner["voice_id"] is not None:
        return False                          # владельца нет или голос уже привязан
    con.execute("UPDATE persons SET voice_id=? WHERE id=?", (voice_id, owner["id"]))
    con.execute(
        "INSERT OR IGNORE INTO identities(person_id, channel, tag, verified,"
        " first_seen, last_seen) VALUES (?,?,?,1,?,?)",
        (owner["id"], "voice", voice_id, time.time(), time.time()))
    con.commit()
    return True


# ── БЛОК 2: цифровые идентичности ─────────────────────────────────
def see_tag(con, channel: str, tag: str, display_name: str | None = None) -> int:
    """Сообщение с меткой платформы. Тег точный → карта создаётся сразу
    (в отличие от голосов!), но со сниженным стартовым доверием.
    Возвращает person_id."""
    row = con.execute("SELECT * FROM identities WHERE channel=? AND tag=?",
                      (channel, tag)).fetchone()
    now = time.time()
    if row:
        con.execute("UPDATE identities SET last_seen=?, msg_count=msg_count+1"
                    " WHERE id=?", (now, row["id"]))
        con.commit()
        return row["person_id"]
    # новая метка → новая карта со стартовым доверием канала
    pid = persons.create_person(con, display_name or f"{channel}:{tag}")
    base = CHANNEL_BASE_TRUST.get(channel, 10)
    con.execute("UPDATE person_domains SET trust=? WHERE person_id=?", (base, pid))
    con.execute("INSERT INTO identities(person_id, channel, tag, first_seen,"
                " last_seen, msg_count) VALUES (?,?,?,?,?,1)",
                (pid, channel, tag, now, now))
    con.commit()
    return pid


def link_identity(con, person_id: int, channel: str, tag: str) -> None:
    """Владелец сказал «в телеге @nick — это Николай» → склейка каналов.
    Если у тега уже была авто-карта, она СЛИВАЕТСЯ в основную:
    журналы перевешиваются, оси усредняются по уликам (merge_persons)."""
    row = con.execute("SELECT person_id FROM identities WHERE channel=? AND tag=?",
                      (channel, tag)).fetchone()
    if row and row["person_id"] != person_id:
        old = con.execute("SELECT is_creator, is_owner FROM persons WHERE id=?",
                          (row["person_id"],)).fetchone()
        if old and not (old["is_creator"] or old["is_owner"]):
            persons.merge_persons(con, keep_id=person_id, absorb_id=row["person_id"])
    con.execute("UPDATE identities SET person_id=?, verified=1"
                " WHERE channel=? AND tag=?", (person_id, channel, tag))
    con.commit()


# ── БЛОК 3: детекция сущности (human / bot / ai) ──────────────────
def classify_entity(con, person_id: int,
                    avg_reply_sec: float | None = None,
                    active_hours_per_day: float | None = None,
                    template_ratio: float | None = None) -> str:
    """Эвристики по поведению (копятся из логов канала):
    • отвечает за <1 сек стабильно → bot;
    • активен 24/7 без сна → bot/ai;
    • template_ratio — доля шаблонных ответов: высокая у ботов,
      низкая у людей; у продвинутого ИИ низкая, но реакция быстрая
      и без суточного ритма → ai.
    Вердикт пишется в карту; «ai» — не приговор, а метка подхода:
    с ИИ можно общаться, но проверять факты и не считать его человеком."""
    score_bot, score_ai = 0, 0
    if avg_reply_sec is not None and avg_reply_sec < 1.0:
        score_bot += 1; score_ai += 1
    if active_hours_per_day is not None and active_hours_per_day > 20:
        score_bot += 1; score_ai += 1
    if template_ratio is not None:
        if template_ratio > 0.6:
            score_bot += 2
        elif template_ratio < 0.2:
            score_ai += 1
    verdict = "human"
    if score_bot >= 3:
        verdict = "bot"
    elif score_ai >= 2:
        verdict = "ai"
    con.execute("UPDATE persons SET entity_type=? WHERE id=?", (verdict, person_id))
    con.commit()
    return verdict
