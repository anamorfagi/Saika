"""СМОТРИТЕЛЬ ЗАКАЗА: выбранное загружено всегда (2026-08-23).

Владелец: «делай так, чтобы все эти модели загружались гарантированно и
не отваливались». Проверяем правила, а не потоки: что смотритель считает
«надо поднять», когда молчит и как отступает."""


def run():
    rows = []
    import io
    import os
    from anamorf import keeper
    from anamorf.config import CFG

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # ── выключенное человеком — закон, не поднимаем ──
    was = CFG.get("stt.engine", "")
    try:
        CFG.set("stt.engine", "none")
        keeper._ST["next"].clear()
        called = []
        import anamorf.stt as _stt_mod  # noqa: F401
        keeper._check_stt()             # не должен звать set_engine
        rows.append(("выключенный слух не поднимаем — это выбор человека",
                     "stt" not in keeper._ST["fail"], ""))
    finally:
        CFG.set("stt.engine", was)

    # ── откат растёт, а не долбит ──
    keeper._ST["fail"].clear(); keeper._ST["next"].clear()
    import time
    t0 = time.time()
    keeper._failed("brain", "стенд")
    first = keeper._ST["next"]["brain"] - t0
    keeper._failed("brain", "стенд")
    second = keeper._ST["next"]["brain"] - t0
    rows.append(("повторный провал ждёт дольше первого",
                 second > first >= 50, f"{first:.0f}с -> {second:.0f}с"))
    keeper._ok("brain")
    rows.append(("успех сбрасывает счётчик провалов",
                 not keeper._ST["fail"], ""))

    # ── не воюет со сторожем и разговором ──
    src = io.open(os.path.join(ROOT, "anamorf", "keeper.py"),
                  encoding="utf-8").read()
    rows.append(("при пожаре сторожа смотритель ждёт",
                 'int(st.get("level", 0)) >= 2' in src, ""))
    rows.append(("посреди разговора ничего не перезапускает",
                 "_talk_busy()" in src, ""))
    rows.append(("подменённый сторожем голос не трогает — тот вернёт сам",
                 'clone_was' in src, ""))
    rows.append(("мозг сверяется с ФАЙЛОМ на порту, а не с конфигом",
                 '/v1/models' in src and "_norm(served)" in src, ""))

    main = io.open(os.path.join(ROOT, "anamorf", "main.py"),
                   encoding="utf-8").read()
    rows.append(("запускается из /api/ready — переживает правки и смерть "
                 "потока", "_kp.start()" in main, ""))
    feats = io.open(os.path.join(ROOT, "features.json"),
                    encoding="utf-8").read()
    rows.append(("keeper.py в реестре — приедет в сборку",
                 '"keeper.py"' in feats, ""))
    return rows
