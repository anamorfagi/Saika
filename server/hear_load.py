"""КОГДА НЕ УСПЕВАЕМ — ЖЕРТВУЕМ АНАЛИЗОМ, А НЕ СЛУХОМ (2026-08-20).

Живой лог запуска 20.08: «Слух не успевает: уронила 401 чанков» — счётчик
рос ровно на 10 в секунду, то есть терялось СТО процентов звука, сорок
секунд подряд. При этом ни одной строки «слух отстаёт, пропускаю
шумодав»: старый предохранитель стоял ВНУТРИ микрофонной ветки горячего
цикла, ниже `continue` системной, и до него просто не доходили.

Причина перегрузки в том же логе видна выше: Qwen3-TTS в этот момент
компилировался (inductor, минуты) и держал видеокарту. А на каждый
стомиллисекундный кусок мы зовём PANNs (уши) и ECAPA (отпечаток) — обе на
той же видеокарте. Пока идёт компиляция, они не укладываются в реальное
время физически, и никакой «движок слуха» тут ни при чём.

ЧТО РЕШАЕТ ЭТОТ МОДУЛЬ. Один вопрос — «мы отстаём?» — с одним ответом на
оба звуковых канала. Отстаём, если очередь растёт ИЛИ тяжёлый голос ещё
греется. Пока отстаём, всё необязательное (уши, отпечаток, битбокс,
паспорт микрофона) выключено, а то, ради чего слух и нужен, — уровень,
VAD и нарезка фраз — работает. Она в это время слышит и исполняет
команды, просто не пишет, что вокруг лает собака.

ПОЧЕМУ ОТДЕЛЬНЫМ МОДУЛЕМ, А НЕ ЗАМЫКАНИЕМ В main.py. Правило с
гистерезисом и «сказать человеку не чаще раза в N минут» проверяется
тестом за миллисекунды, а живьём — только пересборкой перегрузки
видеокарты. См. tests/test_hearing_load.py.

МОЛЧАЛИВОГО ОТКАЗА НЕТ. Если экономим дольше tell_after секунд, человек
должен узнать об этом, а не гадать, почему она вдруг перестала замечать
звуки вокруг.
"""
import time


class Lag:
    """Отстаём ли мы от реального времени и что с этим сказать человеку.

    depth_fn() -> int   глубина очереди слуха прямо сейчас
    warm_fn()  -> bool  греется ли тяжёлый голос (держит видеокарту)
    """

    def __init__(self, depth_fn, warm_fn, limit=25, tell=None, log=None,
                 tell_after=20.0, tell_every=300.0):
        self._depth = depth_fn
        self._warm = warm_fn
        self.limit = int(limit)
        self.tell_after = float(tell_after)
        self.tell_every = float(tell_every)
        self._tell = tell
        self._log = log
        self.on = False
        self.since = 0.0
        self.told = 0.0
        self._warm_ts = 0.0
        self._warm_val = False

    def warming(self, now=None) -> bool:
        """Ответ кэшируем на секунду: вопрос дешёвый, но задаётся десять
        раз в секунду, а лезет он в чужой модуль."""
        now = time.time() if now is None else now
        if now - self._warm_ts < 1.0:
            return self._warm_val
        self._warm_ts = now
        try:
            self._warm_val = bool(self._warm())
        except Exception:
            self._warm_val = False
        return self._warm_val

    def behind(self, now=None) -> bool:
        now = time.time() if now is None else now
        try:
            deep = int(self._depth()) > self.limit
        except Exception:
            deep = False
        warm = self.warming(now)
        on = deep or warm

        if on and not self.on:
            self.on, self.since = True, now
        elif not on and self.on:
            self.on = False
            if now - self.since > 5 and self._log:
                self._log("Слух догнал реальное время за %.0fс — возвращаю "
                          "уши и отпечаток голоса" % (now - self.since))

        if (on and now - self.since > self.tell_after
                and now - self.told > self.tell_every):
            self.told = now
            why = ("голос ещё прогревается и держит видеокарту" if warm
                   else "звук идёт быстрее разбора")
            if self._tell:
                self._tell("Слышу и понимаю команды, но пока не разбираю "
                           f"звуки вокруг: {why}. Верну сама, как только "
                           "догоню.")
        return on
