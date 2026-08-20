"""СТУПЕНИ РАЗГРУЗКИ: гасим по одному и возвращаем сами.

Живой случай 19.08.2026: защита железа при 96% VRAM снесла слух, голос и
мозги разом, посреди разговора, и повторила это через минуту.

ВАЖНО ПРО КОНФИГ. Тесту нужны нулевые выдержки (guard.step_s, calm_s),
иначе он ждал бы реальные секунды. CFG.set пишет в config.json — то есть
прогон теста МЕНЯЕТ настройки машины. Первая версия этого файла так и
сделала: оставила в конфиге нули, и живая защита железа осталась без
выдержки, задёргавшись на каждом замере. Поэтому здесь всё, что тест
трогает в конфиге, он обязан вернуть в finally.
"""
import time


def run():
    rows = []
    from anamorf import triage
    from anamorf.config import CFG

    steps = []
    down = dict(triage.DOWN)
    up = dict(triage.UP)
    say = triage._say
    was_step = CFG.get("guard.step_s", 12)
    was_calm = CFG.get("guard.calm_s", 45)
    try:
        for k, name in triage.STEPS.items():
            triage.DOWN[k] = (lambda n: (lambda: steps.append("гашу:" + n)
                                         or True))(name)
            triage.UP[k] = (lambda n: (lambda: steps.append("возврат:" + n)
                                       or True))(name)
        triage._say = lambda t: None
        CFG.set("guard.step_s", 0)
        CFG.set("guard.calm_s", 0)
        triage.ST.update(level=0, ts=0.0, calm_since=0.0)

        def g(pct, temp=50):
            return {"vram_mb": 160.0 * pct, "vram_total_mb": 16000.0,
                    "temp": temp}

        last = triage.LAST
        levels_down = []
        for pct in [85] + [97] * last:
            triage.tick(g(pct))
            levels_down.append(triage.ST["level"])
        rows.append(("порядок гашения",
                     levels_down == list(range(0, last + 1)),
                     f"ступени: {levels_down}"))

        # ступень «лёгкий голос» идёт РАНЬШЕ полного молчания: голос —
        # последнее, что человек готов потерять (19.08.2026)
        order = list(triage.STEPS.values())
        rows.append(("лёгкий голос раньше молчания",
                     order.index("лёгкий голос") < order.index("озвучка")
                     < order.index("мозги"),
                     " -> ".join(order)))

        # по ПРЕДУПРЕЖДЕНИЮ (не критично) глубже второй ступени не лезем
        triage.ST.update(level=0, ts=0.0, calm_since=0.0)
        warn = []
        for _ in range(4):
            triage.tick(g(91))
            warn.append(triage.ST["level"])
        rows.append(("предупреждение не рубит голос",
                     max(warn) <= 2, f"ступени: {warn}"))

        triage.ST.update(level=last, ts=0.0, calm_since=0.0)
        levels_up = []
        for _ in range(last + 1):
            triage.tick(g(60, 45))
            time.sleep(0.01)
            levels_up.append(triage.ST["level"])
        rows.append(("возврат по одной ступени",
                     levels_up[-1] == 0
                     and levels_up == sorted(levels_up, reverse=True),
                     f"ступени: {levels_up}"))

        # гистерезис: на «тёплом, но не спокойном» железе ничего не двигаем
        triage.ST.update(level=2, ts=0.0, calm_since=0.0)
        before = triage.ST["level"]
        triage.tick(g(88, 60))
        rows.append(("гистерезис: между порогами не дёргаемся",
                     triage.ST["level"] == before,
                     f"было {before}, стало {triage.ST['level']}"))
    finally:
        triage.DOWN.clear(), triage.DOWN.update(down)
        triage.UP.clear(), triage.UP.update(up)
        triage._say = say
        triage.ST.update(level=0, ts=0.0, calm_since=0.0)
        CFG.set("guard.step_s", was_step)
        CFG.set("guard.calm_s", was_calm)
    return rows
