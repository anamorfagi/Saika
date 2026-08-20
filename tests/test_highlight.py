"""СВЕЧЕНИЕ ВНИМАНИЯ: контур не смеет закрывать работу.

История в трёх поломках 19.08.2026: сперва подсветка залила ВЕСЬ экран
чёрным, потом ловила мышь, потом выглядела чёрными полосками вместо
оранжевого градиента. Здесь проверяется то, что можно проверить без
Windows: геометрия и цвет получившейся картинки.
"""


def run():
    rows = []
    try:
        import numpy as np
    except Exception as e:
        return [("свечение", None, f"нет numpy ({e})")]
    from anamorf import highlight as hl

    w, h, t = 400, 300, 16
    bits = hl._contour_bits(w, h, t, (255, 154, 60), 1.0, 8)
    if len(bits) != w * h * 4:
        return [("размер картинки", False,
                 f"{len(bits)} байт вместо {w * h * 4}")]
    arr = np.frombuffer(bits, dtype=np.uint8).reshape(h, w, 4)
    a = arr[..., 3].astype(int)

    rows.append(("середина цели свободна", int(a[h // 2, w // 2]) == 0,
                 f"альфа в центре {a[h // 2, w // 2]}"))
    rows.append(("край светится", int(a[0, w // 2]) > 180,
                 f"альфа у края {a[0, w // 2]}"))

    prof = [int(a[i, w // 2]) for i in range(t + 2)]
    monotone = all(prof[i] >= prof[i + 1] for i in range(len(prof) - 1))
    rows.append(("градиент гаснет внутрь без ступенек", monotone,
                 f"профиль {prof[:6]}…{prof[-2:]}"))
    rows.append(("за контуром пусто", prof[-1] == 0,
                 f"на глубине {t + 1}px альфа {prof[-1]}"))

    # премультипликация: цветовой канал не бывает ярче альфы, иначе
    # Windows рисует ореол
    px = arr[0, w // 2]
    rows.append(("цвет премультиплицирован",
                 all(int(c) <= int(px[3]) for c in px[:3]),
                 f"BGRA {tuple(int(v) for v in px)}"))

    # маленькое окно не должно превратиться в сплошное пятно
    sw, sh = 120, 90
    small = np.frombuffer(hl._contour_bits(sw, sh, 40, (255, 154, 60), 1.0, 0),
                          dtype=np.uint8).reshape(sh, sw, 4)
    rows.append(("у маленького окна середина тоже свободна",
                 int(small[sh // 2, sw // 2, 3]) == 0,
                 f"альфа в центре {small[sh // 2, sw // 2, 3]}"))

    # затухание: половинная яркость даёт вдвое меньше альфы у края
    half = np.frombuffer(hl._contour_bits(w, h, t, (255, 154, 60), 0.5, 8),
                         dtype=np.uint8).reshape(h, w, 4)
    edge_full, edge_half = int(a[0, w // 2]), int(half[0, w // 2, 3])
    rows.append(("затухание уменьшает яркость",
                 edge_half < edge_full * 0.7,
                 f"{edge_full} -> {edge_half}"))
    return rows
