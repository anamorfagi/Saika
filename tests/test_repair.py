"""ПОЧИНКА И ПРОХОД «ПОДНЯТЬ ВСЁ»: не врать и не крутиться по кругу.

Оба правила проверяемы без микрофона, Windows и видеокарты — значит должны
быть проверены здесь, а не в живом разговоре ценой вечера.

Что именно ловим:

* ВЕРДИКТ СОБИРАЕТСЯ ИЗ ШАГОВ. «Подняла всё» имеет право появиться только
  тогда, когда ВСЕ шаги отчитались успехом. Один провал — и в вердикте
  обязана быть его причина. Это первый этап плана билда буквально: фраза о
  результате строится из результата, а не из намерения.
* СТУПЕНЬ РАЗГРУЗКИ ТРАТИТСЯ ОДИН РАЗ. Проход, который освобождает память
  и пробует снова без счётчика, — это бесконечный круг на живой машине.
* ПАМЯТЬ ОСВОБОЖДАЕМ, ТОЛЬКО ЕСЛИ ДЕЛО В ПАМЯТИ. Движка нет в сборке —
  никакая разгрузка не поможет, а голос она снимет.
* ЧИНИТЬ НЕЧЕГО — ГОВОРИМ ЭТО, А НЕ «ПОЧИНИЛА».

Модули слуха и голоса живут в anamorf.main (девять тысяч строк, торч и
FastAPI), поэтому здесь они подменяются заглушками: проверяем ЛОГИКУ
решений, а не способность машины поднять GigaAM.
"""


def run():
    rows = []
    from anamorf import bringup, repair

    # ── 1. вердикт не врёт ──────────────────────────────────────────
    bringup.STATE["steps"] = [
        {"key": "hear", "title": "слух", "ok": True, "why": ""},
        {"key": "free", "title": "освободила: лёгкий голос", "ok": True,
         "why": ""},
        {"key": "brain", "title": "мозги", "ok": False,
         "why": "не влезла в память"},
    ]
    v = bringup._verdict()
    ok = ("Подняла всё" not in v) and ("мозги" in v) and \
         ("не влезла в память" in v)
    rows.append(("вердикт называет провал", ok, v.splitlines()[0]))

    bringup.STATE["steps"] = [
        {"key": "hear", "title": "слух", "ok": True, "why": ""},
        {"key": "voice", "title": "голос", "ok": True, "why": ""},
    ]
    v2 = bringup._verdict()
    rows.append(("всё поднялось — так и сказано",
                 v2.startswith("Подняла всё"), v2))

    # служебные шаги «освободила» не должны считаться подсистемами
    bringup.STATE["steps"] = [{"key": "free", "title": "освободила: x",
                               "ok": True, "why": ""}]
    rows.append(("один только сброс памяти — это не «подняла всё»",
                 "Подняла всё" not in bringup._verdict(),
                 bringup._verdict()))

    # ── 2. ступени тратятся по одной и кончаются ────────────────────
    used = []

    class _L(bringup._Ladder):
        def __init__(self):
            self.steps = [("первая", lambda: used.append(1) or True),
                          ("вторая", lambda: used.append(2) or True)]
            self.i = 0

    lad = _L()
    got = [lad.free_one(), lad.free_one(), lad.free_one(), lad.free_one()]
    rows.append(("ступени кончаются, круга нет",
                 got == ["первая", "вторая", "", ""] and used == [1, 2],
                 str(got)))

    # пустая ступень (гасить нечего) не засчитывается, идём к следующей
    lad2 = _L()
    lad2.steps = [("пустая", lambda: False), ("рабочая", lambda: True)]
    rows.append(("пустая ступень не съедает ход",
                 lad2.free_one() == "рабочая", ""))

    # ── 3. память освобождаем только по делу ────────────────────────
    # ТЕСТ НЕ ДОЛЖЕН ЗАВИСЕТЬ ОТ ТОГО, ЧТО ЛЕЖИТ НА ЭТОЙ МАШИНЕ
    # (2026-08-22): разбор ошибок теперь СНАЧАЛА смотрит на диск, и на
    # машине без весов GigaAM любая ошибка честно становится «нет файла
    # модели». Здесь проверяется другое — счётчик ступеней, — поэтому
    # диск подменяем: «веса на месте».
    from anamorf import diagnostics as _dg0
    _wasw0 = _dg0._weights_missing
    _dg0._weights_missing = lambda n: ""
    tries = []

    def fake_load(kind, name):
        tries.append(name)
        return (False, "No module named 'gigaam'")

    was = repair._try_load
    try:
        repair._try_load = fake_load
        lad3 = _L()
        ok3, why3 = bringup._load_with_room("stt", "gigaam", lad3)
        rows.append(("движка нет в сборке — память не трогаем",
                     (not ok3) and lad3.i == 0 and len(tries) == 1,
                     f"попыток {len(tries)}, ступеней потрачено {lad3.i}"))

        tries.clear()
        repair._try_load = lambda k, n: (tries.append(n),
                                         (False, "CUDA out of memory"))[1]
        lad4 = _L()
        ok4, _ = bringup._load_with_room("stt", "gigaam", lad4)
        rows.append(("не влезло — ровно одна ступень и ровно две попытки",
                     (not ok4) and lad4.i == 1 and len(tries) == 2,
                     f"попыток {len(tries)}, ступеней потрачено {lad4.i}"))

        # со второй попытки поднялось — значит успех, а не «не вышло»
        tries.clear()
        repair._try_load = lambda k, n: (tries.append(n),
                                         (len(tries) > 1, "" if len(tries) > 1
                                          else "CUDA out of memory"))[1]
        lad5 = _L()
        ok5, _ = bringup._load_with_room("stt", "gigaam", lad5)
        rows.append(("освободила и подняла — это успех",
                     ok5 and lad5.i == 1, f"попыток {len(tries)}"))
    finally:
        repair._try_load = was
        _dg0._weights_missing = _wasw0

    # ── 4. чинить нечего — так и говорим ────────────────────────────
    r = repair.run("llm")
    rows.append(("чужой модуль не чиним молча",
                 (not r["ok"]) and "не умею" in r.get("why", ""),
                 r.get("why", "")))

    wasd = repair.diag_for
    try:
        repair.diag_for = lambda c: {"category": "absent", "fix": "absent",
                                     "human": "нет в этой сборке"}
        r2 = repair.run("tts.omni")
        rows.append(("«нет в сборке» — не поломка и не починка",
                     (not r2["ok"]) and r2["state"] == "broken"
                     and "сборке" in r2["why"], r2["why"]))
    finally:
        repair.diag_for = wasd
        repair._BUSY.clear()

    # ── 5. у каждого движка свой адрес ──────────────────────────────
    # Живой случай 22.08: «gigaam не работает — huggingface.co не
    # отвечает». GigaAM в сторону huggingface даже не смотрит, его веса
    # лежат на CDN Сбера. Неверный адрес хуже отсутствия адреса: человек
    # идёт проверять VPN до HF, а сломано другое.
    from anamorf import diagnostics as dg

    wasw = dg._weights_missing
    try:
        dg._weights_missing = lambda n: ""        # веса на месте
        d = dg.classify("stt.gigaam", "HTTPSConnectionPool: Read timed out")
        rows.append(("сетевая беда GigaAM не валится на huggingface",
                     d["category"] == "network"
                     and "sberdevices" in d["human"]
                     and "huggingface.co не отвечает" not in d["human"],
                     d["human"][:70]))

        d2 = dg.classify("tts.edge", "cannot connect to host")
        rows.append(("адрес edge не потерялся",
                     "speech.platform.bing.com" in d2["human"], ""))

        # а теперь весов нет — и это уже не сетевая беда
        dg._weights_missing = lambda n: "C:\\Users\\x\\.cache\\gigaam\\v3.ckpt"
        d3 = dg.classify("stt.gigaam", "HTTPSConnectionPool: Read timed out")
        rows.append(("нет файла модели — качать, а не «проверь VPN»",
                     d3["category"] == "nomodel" and d3["fix"] == "download",
                     d3["human"][:70]))

        # устаревший диагноз «уйти на запасной» не должен пересиливать диск
        wasd2 = repair.diag_for
        calls = []
        wasdl = repair._download
        wastl = repair._try_load
        try:
            repair.diag_for = lambda c: {"category": "network",
                                         "fix": "switch", "human": "сеть"}
            repair._download = lambda k, n, note=None: (
                calls.append(n), {"ok": True, "did": "скачала"})[1]
            repair._try_load = lambda k, n: (True, "")
            r3 = repair.run("stt.gigaam")
            rows.append(("весов нет — чиню закачкой, а не переключением",
                         r3["ok"] and calls == ["gigaam"], str(calls)))
        finally:
            repair.diag_for, repair._download = wasd2, wasdl
            repair._try_load = wastl
            repair._BUSY.clear()
    finally:
        dg._weights_missing = wasw

    # ── 6. старый пакет — это не сеть и не веса ─────────────────────
    # Живой вечер 22.08: слух валился «Model 'v3_e2e_rnnt' not found»
    # (в сборке стоял gigaam с pypi, знающий только v1/v2), а голос —
    # «'Qwen3TTSModel' object has no attribute
    # 'stream_generate_voice_clone'» (форк подложили ПОСЛЕ старта, и в
    # памяти жил старый модуль). Разбор называл первое «проблемой с
    # сетью» и слал проверять VPN.
    d4 = dg.classify("stt.gigaam", "Model 'v3_e2e_rnnt' not found. "
                     "Available model names: ['ctc', 'rnnt', 'v2_rnnt']")
    rows.append(("«пакет не знает такой модели» — не сеть",
                 d4["category"] == "oldpkg" and d4["fix"] == "pkg"
                 and "что-то с сетью" not in d4["human"]
                 and "VPN" not in d4["action"], d4["human"][:70]))

    d5 = dg.classify("tts.qwen3", "'Qwen3TTSModel' object has no attribute "
                     "'stream_generate_voice_clone'")
    rows.append(("пакет в памяти старее диска — тоже пакет, а не «незнакомая "
                 "ошибка»",
                 d5["category"] == "oldpkg" and d5["fix"] == "pkg", ""))

    # и починка идёт именно подменой пакета, а не закачкой весов
    seen = []
    wasp, wasd3, wastl2 = repair._pkg_fix, repair.diag_for, repair._try_load
    wasdl2 = repair._download
    try:
        repair.diag_for = lambda c: d4
        repair._pkg_fix = lambda k, n: (seen.append(("pkg", n)),
                                        {"ok": True, "did": "подменила"})[1]
        repair._download = lambda k, n, note=None: (
            seen.append(("download", n)), {"ok": True})[1]
        repair._try_load = lambda k, n: (True, "")
        r4 = repair.run("stt.gigaam")
        rows.append(("лечим подменой пакета, а не закачкой весов",
                     r4["ok"] and seen == [("pkg", "gigaam")], str(seen)))
    finally:
        repair._pkg_fix, repair.diag_for = wasp, wasd3
        repair._try_load, repair._download = wastl2, wasdl2
        repair._BUSY.clear()

    # выкидывание пакета из памяти — то, без чего подмена бессмысленна
    import sys, types
    sys.modules["зряпакет"] = types.ModuleType("зряпакет")
    sys.modules["зряпакет.часть"] = types.ModuleType("зряпакет.часть")
    n = repair.drop_modules("зряпакет")
    rows.append(("пакет выкидывается из памяти целиком",
                 n == 2 and "зряпакет" not in sys.modules, f"{n} модулей"))

    return rows
