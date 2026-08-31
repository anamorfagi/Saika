# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
  DEMO — один «день из жизни» памяти Сайки. Запусти: python demo.py
  Показывает весь цикл: рождение ядра → день → ночь → вспоминание.
═══════════════════════════════════════════════════════════════════
"""
import json
import sys, pathlib
# запускается и как скрипт из своей папки, и из корня проекта:
# кладём на путь родителя пакета, а не сам пакет
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from mind import config, db, identity, writer, consolidation, recall, persons


def показать(заголовок, данные):
    print(f"\n──── {заголовок} " + "─" * max(0, 50 - len(заголовок)))
    print(json.dumps(данные, ensure_ascii=False, indent=2, default=str))


# ═══ ШАГ 0: рождение — ядро ценностей (read-only) ═════════════════
identity.init_values()
показать("L4: ядро ценностей (файл + SHA-256)", identity.load_values())

con = db.connect()

# ═══ ШАГ 1: Создатель — вшитый архетип ════════════════════════════
if not con.execute("SELECT id FROM persons WHERE is_creator=1").fetchone():
    creator_id = persons.create_person(con, "Виталя", voice_id="voice_vitalya", is_creator=True)
else:
    creator_id = con.execute("SELECT id FROM persons WHERE is_creator=1").fetchone()["id"]

# ═══ ШАГ 2: день — дешёвая запись в RAW ═══════════════════════════
writer.write_raw(con, "факт: Виталя работает в CorelDRAW над тактильными табличками",
                 "owner", person_id=creator_id, emotion=0.3, novelty=0.6)
writer.write_raw(con, "Виталя рассказал смешную историю про UV-принтер",
                 "owner", person_id=creator_id, emotion=0.8, novelty=0.7)
writer.write_raw(con, "реклама зубной пасты по телевизору",     # мусор: низкая значимость
                 "web", emotion=0.0, novelty=0.1)
writer.write_raw(con, "факт: все люди — эгоисты, людям нельзя доверять",
                 "web", emotion=0.4, novelty=0.5)               # ценностный мусор → фильтр
писано = con.execute("SELECT COUNT(*) c FROM raw_events").fetchone()["c"]
print(f"\nЗа день в RAW записано событий: {писано}")

# ═══ ШАГ 3: неизвестный голос — буфер кандидатов ══════════════════
существующий = con.execute("SELECT id FROM persons WHERE voice_id='voice_abc123'").fetchone()
if существующий:
    nik_id = существующий["id"]          # повторный запуск демо — карта уже есть
else:
    for _ in range(3):
        вопрос = persons.hear_unknown_voice(con, "voice_abc123")
    print(f"\nСайка спрашивает: «{вопрос}»")
    nik_id = persons.confirm_candidate(con, "voice_abc123", "Николай")
    print("Создатель ответил: «это Николай» → карта создана")

# ═══ ШАГ 4: наблюдения о Николае ══════════════════════════════════
persons.verified_claim(con, nik_id, "факты", ok=True)     # проверила его слова — совпало
persons.add_karma(con, nik_id, "помог разобраться с макетом", +1, "дело")
persons.observe_inner(con, nik_id, "кажется, не любит созвоны", event_id=1)
persons.observe_inner(con, nik_id, "кажется, не любит созвоны", event_id=2)  # 2-е событие
persons.set_state(con, nik_id, {"устал": 0.6, "доброжелателен": 0.8})

# ═══ ШАГ 5: НОЧЬ — консолидация («сон») ═══════════════════════════
отчёт = consolidation.run_night(con)
показать("Отчёт ночной консолидации", отчёт)

# ═══ ШАГ 6: утро — вспоминание с подкреплением ════════════════════
показать("Recall по слову «принтер»", recall.recall(con, "принтер"))

# ═══ ШАГ 7: карты личностей ═══════════════════════════════════════
показать("Карта: Виталя (Создатель)", persons.get_card(con, creator_id))
показать("Карта: Николай", persons.get_card(con, nik_id))

# ═══ ШАГ 8: что попало в семантику (фильтр ценностей!) ════════════
факты = [dict(r) for r in con.execute(
    "SELECT text, status, confidence FROM semantic_facts")]
показать("L3: семантические факты (ценностный мусор отфильтрован)", факты)

identity.append_narrative("Сегодня я познакомилась с Николаем и узнала, "
                          "что Виталя делает тактильные таблички.")
показать("L4: нарратив (последние главы)", identity.read_narrative())
print("\n✅ Полный цикл прошёл: день → ночь → утро. База: saika_data/memory.db")
