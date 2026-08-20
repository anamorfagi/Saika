"""ПОРОГ УЗНАВАНИЯ ГОЛОСА считается по данным, а не из константы.

Живая жалоба 19.08.2026: «Виталя 27%», «голос A/B/C/D» внутри одной
реплики. Причина — порог брался из СВОЕГО же разброса и ничего не знал о
том, как близко подходят чужие голоса.
"""


def run():
    try:
        import numpy as np
    except Exception as e:
        return [("порог голоса", None, f"нет numpy ({e})")]
    from anamorf.voiceprint import passport

    rng = np.random.default_rng(3)

    def cloud(center, n, spread):
        X = center + rng.normal(0, spread, size=(n, 192))
        return (X / np.linalg.norm(X, axis=1, keepdims=True)).astype("float32")

    base = rng.normal(0, 1, 192)
    base /= np.linalg.norm(base)
    far = rng.normal(0, 1, 192)
    far /= np.linalg.norm(far)
    near = 0.9 * base + 0.1 * far
    near /= np.linalg.norm(near)

    class Reg:
        def __init__(self, sp):
            self.speakers = sp

    rows = []
    r = passport._threshold_for(
        Reg({"я": {"embs": cloud(base, 60, 0.05)},
             "другой": {"embs": cloud(far, 60, 0.05)}}), "я")
    rows.append(("разные голоса — уверенный запас", r.get("gap", 0) > 0.2,
                 f"свои≥{r.get('own_lo')}, чужие≤{r.get('imp_hi')}, "
                 f"запас {r.get('gap')}"))

    r2 = passport._threshold_for(
        Reg({"я": {"embs": cloud(base, 60, 0.12)},
             "другой": {"embs": cloud(far, 60, 0.12)}}), "я")
    rows.append(("разболтанная запись — запас меньше, но есть",
                 0 < r2.get("gap", 0) < r.get("gap", 1),
                 f"запас {r2.get('gap')} против {r.get('gap')}"))

    r3 = passport._threshold_for(
        Reg({"я": {"embs": cloud(base, 60, 0.05)},
             "брат": {"embs": cloud(near, 60, 0.05)}}), "я")
    rows.append(("похожий тембр — честный отрицательный запас",
                 r3.get("gap", 1) <= 0 and r3.get("imp_who") == "брат",
                 f"запас {r3.get('gap')}, ближе всех «{r3.get('imp_who')}»"))

    r4 = passport._threshold_for(Reg({"я": {"embs": cloud(base, 5, 0.05)}}), "я")
    rows.append(("мало данных — порога не выдумываем", r4 == {},
                 "вернулось пусто, работает прежнее правило"))
    return rows
