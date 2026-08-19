"""СТУПЕНИ РАЗГРУЗКИ: гасим по одному и возвращаем сами.

Живой случай 19.08.2026: защита железа при 96% VRAM снесла слух, голос и
мозги разом, посреди разговора, и повторила это через минуту.
"""
import time


def run():
    rows = []
    from server import triage
    from server.config import CFG

    steps = []
    down = dict(triage.DOWN)
    up = dict(triage.UP)
    try:
        for k, name in ((1, "лишние"), (2, "озвучка"), (3, "мозги"), (4, "всё")):
            triage.DOWN[k] = (lambda n: (lambda: steps.append("гашу:" + n) or True))(name)
        for k, name in ((4, "слух"), (3, "мозги"), (2, "голос"), (1, "—")):
            triage.UP[k] = (lambda n: (lambda: steps.append("возврат:" + n) or True))(name)
        say = triage._say
        triage._say = lambda t: None
        CFG.set("guard.step_s", 0)
        CFG.set("guard.calm_s", 0)
        triage.ST.update(level=0, ts=0.0, calm_since=0.0)

        def g(pct, temp=50):
            return {"vram_mb": 160.0 * pct, "vram_total_mb": 16000.0,
                    "temp": temp}

        levels_down = []
        for pct in (85, 91, 97, 97, 97):
            triage.tick(g(pct))
            levels_down.append(triage.ST["level"])
        ok_down = levels_down == [0, 1, 2, 3, 4]
        rows.append(("порядок гашения", ok_down,
                     f"ступени: {levels_down}"))

        levels_up = []
        for _ in range(5):
            triage.tick(g(60, 45))
            time.sleep(0.01)
            levels_up.append(triage.ST["level"])
        ok_up = levels_up[-1] < 4 and levels_up == sorted(levels_up, reverse=True)
        rows.append(("возврат по одной ступени", ok_up,
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
    return rows
