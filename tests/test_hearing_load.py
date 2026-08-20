"""ПРЕДОХРАНИТЕЛЬ СЛУХА: жертвуем анализом, а не самим слухом.

Живой лог 20.08.2026, первая минута после запуска: «Слух не успевает:
уронила 401 чанков», счётчик рос на 10 в секунду — терялось СТО процентов
звука. Виноват был не движок слуха: Qwen3-TTS компилировался и держал
видеокарту, а мы на каждый стомиллисекундный кусок звали PANNs и ECAPA на
той же видеокарте.

Проверяем правило из anamorf/hear_load.py, а не горячий цикл: живьём это
воспроизводится только пересборкой перегрузки ГПУ.
"""


def run():
    rows = []
    from anamorf.hear_load import Lag

    q = {"n": 0}
    warm = {"on": False}
    said, logged = [], []

    def make():
        return Lag(lambda: q["n"], lambda: warm["on"], limit=25,
                   tell=said.append, log=logged.append)

    t = 1000.0
    lag = make()

    # 1. Пустая очередь и остывший голос — работаем в полную силу.
    q["n"], warm["on"] = 0, False
    rows.append(("в покое анализ не выключаем", lag.behind(t) is False,
                 f"очередь {q['n']}, порог {lag.limit}"))

    # 2. Очередь выше порога — экономим.
    q["n"] = 100
    rows.append(("очередь растёт — экономим", lag.behind(t) is True,
                 f"очередь {q['n']} > {lag.limit}"))

    # 3. ГЛАВНОЕ ИЗ ЖИВОГО ЛОГА: очередь пуста, но тяжёлый голос греется и
    #    держит видеокарту — уши и отпечаток всё равно молчат.
    lag = make()
    q["n"], warm["on"] = 0, True
    rows.append(("прогрев голоса — тоже повод экономить",
                 lag.behind(t) is True,
                 f"очередь {q['n']}, греется={warm['on']}"))

    # 4. Человеку говорим — но не сразу и не каждую секунду.
    lag = make()
    said.clear()
    q["n"], warm["on"] = 100, False
    lag.behind(t)
    lag.behind(t + 5)                    # рано — молчим
    early = len(said)
    lag.behind(t + 25)                   # пора — один раз
    once = len(said)
    for k in range(30):                  # ещё полминуты — не повторяемся
        lag.behind(t + 26 + k)
    rows.append(("сообщаем один раз, а не каждый кусок",
                 early == 0 and once == 1 and len(said) == 1,
                 f"через 5с {early}, через 25с {once}, через минуту {len(said)}"))

    # 5. Причину называем ту, что есть на самом деле.
    lag = make()
    said.clear()
    q["n"], warm["on"] = 0, True
    lag.behind(t)
    lag.behind(t + 25)
    rows.append(("причина в сообщении — настоящая",
                 bool(said) and "прогрева" in said[0],
                 said[0][:70] if said else "ничего не сказала"))

    # 6. Догнали — возвращаемся сами и говорим об этом в лог.
    lag = make()
    logged.clear()
    q["n"], warm["on"] = 100, False
    lag.behind(t)
    q["n"] = 0
    back = lag.behind(t + 30)
    rows.append(("догнали — возвращаем анализ сами",
                 back is False and bool(logged),
                 (logged[0][:60] if logged else "в лог ничего не написала")))

    # 7. Мигание не считается: короткий всплеск не тревожит человека.
    lag = make()
    said.clear()
    warm["on"] = False
    for k in range(20):
        q["n"] = 100 if k % 2 else 0
        lag.behind(t + k)
    rows.append(("короткий всплеск человека не дёргает",
                 len(said) == 0, f"сообщений {len(said)} за 20 секунд качелей"))

    return rows
