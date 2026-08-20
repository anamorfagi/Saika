"""Самотест модуля отпечатка голоса (2026-07-28).

ЗАЧЕМ ОТДЕЛЬНЫЙ СТЕНД. Проверить распознавание голоса «на слух» нельзя:
садишься, говоришь, точка куда-то поехала — и не понять, работает механика
или это совпадение. Здесь три СИНТЕТИЧЕСКИХ голоса с заведомо разными
параметрами (высота тона, форманты, придыхание), и мерятся честные числа:
- разделяет ли энкодер голоса (свои-чужие по косинусу);
- узнаёт ли реестр записанный эталон на НЕВИДАННЫХ кусках;
- расходятся ли кластеры после проекции в 2D.

Запуск:  python -m tools.voiceprint_selftest
Ключ --light — принудительно лёгкий энкодер (без torch/ECAPA).
"""
import sys
import time

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from anamorf.config import CFG          # noqa: E402
from anamorf.voiceprint.encoder import Encoder, cosine   # noqa: E402
from anamorf.voiceprint.projector import Projector       # noqa: E402
from anamorf.voiceprint.registry import Registry         # noqa: E402

SR = 16000


def synth(f0, formants, breath, seconds, seed, wobble=0.0, noise=0.0):
    """Грубая модель голоса: пилообразный источник на f0 -> резонаторы
    (форманты) -> придыхание. Разные наборы формант = разные «люди».

    wobble — насколько «съезжают» параметры в этом куске. Синтетика без
    разброса даёт косинус ровно 1.000 у своих, и тест становится враньём:
    настоящий человек утром, вечером и простуженным звучит по-разному.
    noise — фон комнаты."""
    rng = np.random.default_rng(seed)
    if wobble:
        f0 = f0 * (1 + rng.uniform(-wobble, wobble))
        formants = [(fc * (1 + rng.uniform(-wobble, wobble)),
                     bw * (1 + rng.uniform(-wobble, wobble)), g)
                    for fc, bw, g in formants]
        breath = breath * (1 + rng.uniform(-wobble * 3, wobble * 3))
    n = int(SR * seconds)
    t = np.arange(n) / SR
    # источник: f0 с живым дрожанием (без него звук мёртвый и слишком лёгкий)
    jit = 1.0 + 0.02 * np.sin(2 * np.pi * 4.7 * t) + 0.01 * rng.normal(size=n)
    phase = np.cumsum(2 * np.pi * f0 * jit / SR)
    src = 2.0 * (phase / (2 * np.pi) % 1.0) - 1.0
    src += breath * rng.normal(size=n)
    # резонаторы: полюса второго порядка на каждой форманте
    out = np.zeros(n, dtype=np.float64)
    for fc, bw, gain in formants:
        r = np.exp(-np.pi * bw / SR)
        a1, a2 = -2 * r * np.cos(2 * np.pi * fc / SR), r * r
        y = np.zeros(n)
        y1 = y2 = 0.0
        for i in range(n):
            y[i] = src[i] - a1 * y1 - a2 * y2
            y2, y1 = y1, y[i]
        out += gain * y
    # огибающая слогов: речь, а не гудение
    env = 0.6 + 0.4 * np.sin(2 * np.pi * 3.1 * t + rng.uniform(0, 6))
    out *= np.clip(env, 0, None)
    out /= (np.abs(out).max() + 1e-9)
    if noise:
        out += noise * rng.normal(size=n)
    return (np.clip(out, -1, 1) * 0.35 * 32767).astype(np.int16)


VOICES = {
    "низкий":  dict(f0=105, formants=[(520, 80, 1.0), (1180, 100, .7),
                                      (2500, 140, .4)], breath=0.02),
    "высокий": dict(f0=205, formants=[(760, 90, 1.0), (1650, 110, .7),
                                      (2900, 150, .4)], breath=0.03),
    "хриплый": dict(f0=138, formants=[(430, 130, 1.0), (1450, 190, .8),
                                      (3300, 220, .5)], breath=0.12),
}


def windows(pcm, win_s=1.2, hop_s=0.4):
    w, h = int(SR * win_s), int(SR * hop_s)
    return [pcm[i:i + w] for i in range(0, max(1, len(pcm) - w), h)]


def main():
    if "--light" in sys.argv:
        CFG.set("voiceprint.encoder", "light")
    enc = Encoder()
    enc.warmup()
    print(f"движок: {enc.backend} ({enc.dim} измерений)"
          + (f" | ECAPA не встала: {enc.last_error}" if enc.last_error else ""))

    # --- 1. кодируем
    t0 = time.monotonic()
    embs, per_win = {}, 0
    for vi, (name, p) in enumerate(VOICES.items()):
        # 6 «сессий»: разное настроение, микрофон, самочувствие
        ws = []
        for k in range(6):
            pcm = synth(seconds=3.2, seed=1000 * vi + k, wobble=0.07,
                        noise=0.004 * (k % 3), **p)
            ws += windows(pcm)
        embs[name] = np.vstack([enc.encode(w)[0] for w in ws])
        per_win = (time.monotonic() - t0) / max(1, sum(len(v) for v in embs.values()))
    print(f"окон закодировано: {sum(len(v) for v in embs.values())}, "
          f"{per_win * 1000:.0f}мс на окно")

    # --- 2. свои-чужие
    print("\nкосинус (среднее):")
    ok = True
    names = list(embs)
    for a in names:
        same = float(np.mean([cosine(u, v) for i, u in enumerate(embs[a])
                              for v in embs[a][i + 1:]]))
        others = [float(np.mean([cosine(u, v) for u in embs[a] for v in embs[b]]))
                  for b in names if b != a]
        worst = max(others)
        mark = "OK " if same - worst > 0.02 else "!! "
        ok &= same - worst > 0.02
        print(f"  {mark}{a:9s} свои {same:+.3f}  чужие(худший) {worst:+.3f}  "
              f"отрыв {same - worst:+.3f}")

    # --- 3. реестр: эталон по половине, проверка по второй
    reg = Registry()
    reg.speakers.clear()
    reg.pts = None
    reg.pts_who, reg.pts_ts = [], []
    for name in names[:2]:
        reg.enroll(name, embs[name][:len(embs[name]) // 2])
    print("\nузнавание на НЕвиданных кусках "
          f"(нижняя планка {_thr(enc.dim)}, порог считается из записи; записаны: {', '.join(names[:2])}):")
    hits = total = 0
    for name in names:
        tail = embs[name][len(embs[name]) // 2:]
        got = [reg.match(e)[0] for e in tail]
        want = name if name in names[:2] else ""
        good = sum(1 for g in got if g == want)
        hits += good
        total += len(got)
        label = want or "(незнакомый -> пусто)"
        print(f"  {'OK ' if good == len(got) else '!! '}{name:9s} "
              f"{good}/{len(got)} -> {label}")
    ok &= hits == total

    # --- 4. проекция: расходятся ли кластеры в 2D
    X = np.vstack([embs[n] for n in names])
    lbl = sum([[n] * len(embs[n]) for n in names], [])
    proj = Projector()
    kind = proj.fit(X)
    P = proj.transform(X)
    cent = {n: P[[i for i, l in enumerate(lbl) if l == n]].mean(axis=0) for n in names}
    spread = float(np.mean([np.linalg.norm(P[i] - cent[l])
                            for i, l in enumerate(lbl)]))
    between = float(np.mean([np.linalg.norm(cent[a] - cent[b])
                             for i, a in enumerate(names) for b in names[i + 1:]]))
    ratio = between / max(spread, 1e-6)
    print(f"\nпроекция: {kind}, разброс внутри {spread:.3f}, "
          f"между центрами {between:.3f}, отношение {ratio:.2f} "
          f"({'OK' if ratio > 1.5 else 'слабо'})")
    ok &= ratio > 1.5

    # --- 5. скорость transform (она в реальном времени на каждый чанк)
    t0 = time.monotonic()
    for _ in range(200):
        proj.transform(X[0])
    print(f"transform одной точки: {(time.monotonic() - t0) / 200 * 1000:.2f}мс")

    ok &= _noise_test()
    ok &= _pipeline_test()
    print("\n" + ("ИТОГ: всё сходится" if ok else "ИТОГ: есть провалы (см. !!)"))
    return 0 if ok else 1


def _noise_test():
    """Щелчки, стуки и шипение НЕ должны становиться «незнакомым голосом».

    Это была живая жалоба: клац мышкой — и на карте появляется точка с
    подписью «незнакомый голос». Порог громкости про строение звука ничего
    не знает, поэтому проверяем именно его — отдельно от всего остального."""
    from anamorf.voiceprint.encoder import speechiness
    print("\nотсев не-голоса (порог 0.5):")
    rng = np.random.default_rng(5)
    n = int(SR * 1.2)
    t = np.arange(n) / SR
    cases = []
    for nm in ("низкий", "высокий"):
        cases.append((f"голос {nm}", True,
                      synth(seconds=1.2, seed=1, wobble=.05, **VOICES[nm])
                      .astype(np.float32) / 32768))
    click = np.zeros(n, np.float32)
    for pos in (3000, 9000):
        click[pos:pos + 90] = rng.normal(size=90) * np.hanning(90) * 0.8
    cases.append(("клик мыши", False, click))
    kb = np.zeros(n, np.float32)
    for pos in range(1000, n - 200, 2600):
        kb[pos:pos + 120] = rng.normal(size=120) * np.hanning(120) * 0.5
    cases.append(("клавиатура", False, kb))
    knock = np.zeros(n, np.float32)
    knock[5000:5600] = (rng.normal(size=600)
                        * np.exp(-np.arange(600) / 120) * 0.9).astype(np.float32)
    cases.append(("стук по столу", False, knock))
    cases.append(("белый шум", False,
                  (rng.normal(size=n) * 0.05).astype(np.float32)))
    cases.append(("гул 50Гц", False,
                  (0.15 * np.sin(2 * np.pi * 50 * t)
                   + 0.05 * np.sin(2 * np.pi * 100 * t)).astype(np.float32)))
    cases.append(("шип кулера", False,
                  (np.convolve(rng.normal(size=n), np.hanning(64), "same")
                   / 8 * 0.6).astype(np.float32)))
    ok = True
    for name, want, x in cases:
        sc, _ = speechiness(x)
        got = sc >= 0.5
        ok &= got == want
        print(f"  {'OK ' if got == want else '!! '}{name:<16} оценка {sc:.2f} -> "
              f"{'голос' if got else 'не голос'}")
    return ok


def _pipeline_test():
    """Прогон ЖИВОГО пути: feed() -> очередь -> рабочий поток -> события.
    Проверяет то, чего не видно в поштучных вызовах: VAD, скользящее окно,
    запись эталона, отсутствие блокировок."""
    from anamorf import voiceprint as vp
    print("\nживой путь (feed -> поток -> события):")
    got = []
    vp.S.reg.speakers.clear()
    vp.S.reg.pts, vp.S.reg.pts_who, vp.S.reg.pts_ts = None, [], []
    vp.start(sink=got.append)
    time.sleep(0.3)

    def talk(voice, seconds, seed):
        pcm = synth(seconds=seconds, seed=seed, wobble=0.05, **VOICES[voice])
        for i in range(0, len(pcm) - 1600, 1600):      # чанки по 100мс, как из UI
            vp.feed(pcm[i:i + 1600])
            time.sleep(0.012)                          # быстрее реального времени
        time.sleep(1.2)

    vp.enroll_start("тест", need=10)
    talk("низкий", 6, 77)
    for _ in range(40):
        if not vp.S.enroll_name:
            break
        time.sleep(0.1)
    if vp.S.enroll_name:
        vp.enroll_finish()
    talk("низкий", 3, 78)
    talk("высокий", 3, 79)
    time.sleep(0.5)
    vp.stop()

    pts = [e for e in got if e.get("state") == "voice"]
    idle = [e for e in got if e.get("state") == "idle"]
    mine = sum(1 for e in pts[-14:] if e.get("who") == "тест")
    alien = sum(1 for e in pts[-7:] if e.get("who") == "")
    inbox = all(-1.7 <= e["x"] <= 1.7 and -1.7 <= e["y"] <= 1.7 for e in pts)
    checks = [
        ("точки пришли", len(pts) >= 10, f"{len(pts)}"),
        ("тишина гасит точку", len(idle) >= 2, f"{len(idle)}"),
        ("эталон записан", "тест" in vp.S.reg.speakers,
         str(list(vp.S.reg.speakers))),
        ("свой голос узнан", mine >= 4, f"{mine}/14 последних"),
        ("чужой не приписан", alien >= 3, f"{alien}/7 последних"),
        ("координаты в кадре", inbox, ""),
    ]
    ok = True
    for name, good, extra in checks:
        ok &= good
        print(f"  {'OK ' if good else '!! '}{name:22s} {extra}")
    return ok


def _thr(dim):
    from anamorf.voiceprint.registry import _floor as _default_threshold
    return _default_threshold(dim)


if __name__ == "__main__":
    sys.exit(main())
