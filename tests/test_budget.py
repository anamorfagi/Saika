"""БЮДЖЕТ ПРОМПТА: сколько разговора помещается в окно модели.

Живой случай 19.08.2026: окно спрашивали у ЛОКАЛЬНОЙ модели даже на
облачном маршруте. Таблица окон её не знает, потолок оставался дефолтным
9000 символов, а системный промпт весит 16.6к — истории не оставалось
вовсе, она падала на аварийный пол в 1500 символов. Каждый облачный ход.
"""

SYSTEM = 16668      # столько весит системный промпт в живом логе
TOOLS = 9712        # столько весили схемы инструментов в том же логе


def _hist(model, cap_cfg=9000, cap_max=40000):
    from anamorf.llm import brains
    win = brains.window_chars_of(model)
    cap = cap_cfg
    if win:
        cap = max(cap, min(int(win * 0.7), cap_max))
    return win, cap, max(1500, cap - SYSTEM - TOOLS)


def run():
    rows = []
    from anamorf.llm import brains

    win, cap, hist = _hist("google/gemma-4-e4b")
    rows.append(("локальная модель в таблице окон не значится",
                 win == 0, f"окно {win}"))
    rows.append(("и потому истории не остаётся — та самая поломка",
                 hist == 1500, f"истории {hist} символов"))

    for model, least in (("GigaChat-2-Pro", 10000),
                         ("mistral-medium-3-5", 10000),
                         ("@cf/qwen/qwen3-30b-a3b-fp8", 5000)):
        win, cap, hist = _hist(model)
        rows.append((f"облачной модели «{model}» хватает места",
                     hist >= least,
                     f"окно {win}, потолок {cap}, истории {hist}"))

    rows.append(("окно берётся по имени модели, а не по бэкенду",
                 brains.window_chars_of("GigaChat-2-Pro") > 100000
                 and brains.window_chars_of("что-то незнакомое") == 0,
                 "знакомая — большое, незнакомая — ноль"))
    return rows
