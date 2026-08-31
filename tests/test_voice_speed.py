"""ГОЛОС, КОТОРЫЙ НЕ УСПЕВАЕТ: что считать аварией, а что — нормой.

Владелец 22.08: «голос зависает так, когда сильная нагрузка происходит».
Владелец 23.08, по живому логу x0.99 / x0.95 / x0.91: «какого хера она
переключается, если движок квен нормально стоит» и «какого хера она
переключается на силеро — самую низкую в рейтинге», и главное: «я не
понимаю, какого чёрта она сейчас аж двумя озвучками говорит».

Три ошибки в одном месте, все три проверяем:

  1. МЕРИЛИ НЕ ТО. Отношение «секунд звука к секундам работы» на одной
     фразе с порогом «строго быстрее речи» объявляло аварией даже x0.99 —
     то есть синтез идёт вровень, пауз не слышно, а голос меняется.
     Слышно НАКОПЛЕННОЕ отставание: пока долг меньше пары секунд, его
     съедает буфер. Быстрая фраза долг гасит.

  2. ВЫБИРАЛИ НЕ ТЕМ. Запасной брался из своего списка, где silero стоял
     первым, — вопреки _priority(), где порядок расставил владелец и где
     silero нарочно в хвосте. Второй источник правды.

  3. МЕНЯЛИ НЕ ТОГДА. Ответ читается по предложениям, и смена движка
     между ними означала две озвучки в одном ответе. Решение принимаем
     сразу, применяем на границе ответа.
"""


def run():
    rows = []
    from anamorf.config import CFG
    from anamorf.tts.manager import TTSManager, _HEAVY

    was_engine = CFG.get("tts.engine", "")
    was_back = CFG.get("tts.engine_was", "")
    said = []
    try:
        m = TTSManager(on_problem=lambda c, e, a, d=None: said.append(c))
        CFG.set("tts.rtf_back_s", 3600)      # возврат в этом тесте не нужен
        CFG.set("tts.engine", "qwen3")

        # ── 0. ПО УМОЛЧАНИЮ ГОЛОС НЕ МЕНЯЕМ ВООБЩЕ ──
        # 2026-08-23, третий заход: «она опять произвольно переключает
        # ттс». На этом железе клон идёт вровень с речью и изредка
        # проседает — значит подмена и возврат будут ходить туда-сюда
        # вечно. Выбор голоса принадлежит человеку, а не нам.
        CFG.set("tts.rtf_guard", False)
        m._debt = 0.0
        for _ in range(6):
            m._note_speed("qwen3", 0.30, 1.0, 3.4)
        rows.append(("по умолчанию голос не меняем сами — только говорим",
                     str(CFG.get("tts.engine")) == "qwen3"
                     and not getattr(m, "_pending", "") and bool(said),
                     f"движок {CFG.get('tts.engine')}, сказано: {said}"))

        # дальше проверяем сам механизм — он остаётся для тех, кому нужен
        CFG.set("tts.rtf_guard", True)
        said.clear()
        m._debt = 0.0

        # ── 1. ВРОВЕНЬ — ЭТО НЕ АВАРИЯ ──
        for _ in range(6):
            m._note_speed("qwen3", 0.95, 3.0, 3.16)
        rows.append(("синтез вровень с речью (x0.95) голос не трогает",
                     str(CFG.get("tts.engine")) == "qwen3" and not said,
                     f"долг {getattr(m, '_debt', 0):.1f}с, движок "
                     f"{CFG.get('tts.engine')}"))

        # ── 2. БЫСТРАЯ ФРАЗА ГАСИТ ДОЛГ ──
        m._note_speed("qwen3", 3.0, 6.0, 2.0)
        rows.append(("быстрая фраза гасит накопленный долг",
                     getattr(m, "_debt", 1.0) <= 0.01,
                     f"долг {getattr(m, '_debt', 0):.2f}с"))

        # ── 3. НАСТОЯЩЕЕ ОТСТАВАНИЕ — РЕШЕНИЕ ЕСТЬ, ГОЛОС ПОКА ТОТ ЖЕ ──
        said.clear()
        m._note_speed("qwen3", 0.35, 1.0, 3.0)
        m._note_speed("qwen3", 0.30, 1.0, 3.4)
        pend = getattr(m, "_pending", "")
        rows.append(("отставание в секунды — решение принято",
                     bool(pend) and bool(said), f"решила уйти на «{pend}»"))
        rows.append(("но посреди ответа голос НЕ меняется — иначе одна "
                     "реплика звучит двумя озвучками",
                     str(CFG.get("tts.engine")) == "qwen3",
                     f"движок {CFG.get('tts.engine')}"))

        # ── 4. ЗАПАСНОЙ — ИЗ ОБЩЕГО ПОРЯДКА, А НЕ ИЗ СВОЕГО СПИСКА ──
        chain = [n for n in m._chain()
                 if n != "qwen3" and not any(h in n.lower() for h in _HEAVY)]
        rows.append(("запасной взят из общей очереди (там же, где порядок "
                     "владельца), а не из своего списка",
                     bool(chain) and pend == chain[0],
                     f"очередь {chain[:3]}, выбрано «{pend}»"))

        # ── 5. ГРАНИЦА ОТВЕТА — ЕДИНСТВЕННОЕ МЕСТО СМЕНЫ ──
        m.begin_answer()
        now = str(CFG.get("tts.engine"))
        rows.append(("на границе ответа голос меняется",
                     now == pend and str(CFG.get("tts.engine_was")) == "qwen3",
                     f"стало «{now}»"))

        # ── 6. ЛЁГКИЙ НЕ ПОНИЖАЕМ: НИЖЕ НЕКУДА ──
        said.clear()
        m._debt = 0.0
        CFG.set("tts.engine", "silero")
        for _ in range(4):
            m._note_speed("silero", 0.3, 1.0, 3.0)
        rows.append(("лёгкий голос не понижаем — ниже некуда",
                     str(CFG.get("tts.engine")) == "silero" and not said, ""))

        # ── 7. ВЫБОР РУКАМИ СТИРАЕТ ИСТОРИЮ ──
        try:
            m.set_engine("silero")
        except Exception:
            pass
        rows.append(("ручной выбор стирает счётчик неудач",
                     not getattr(m, "_slow_hist", {}).get("silero"), ""))
    finally:
        CFG.set("tts.rtf_guard", False)
        CFG.set("tts.engine", was_engine)
        CFG.set("tts.engine_was", was_back)

    return rows
