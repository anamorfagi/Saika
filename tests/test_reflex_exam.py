"""БОЛЬШОЙ ЭКЗАМЕН РЕФЛЕКСОВ: список команд + скорость + обучение + защита.

Владелец 23.08: «чистые команды должны отрабатывать за 100мс ± … мы
работаем над рефлекторными командами, которые нейронка должна учиться
понимать» и «замути тест — помнишь, мы делали список команд, который она
должна отработать».

Список ниже — это и есть тот список: живые формулировки владельца из
логов этой недели плюс их очевидные варианты. Каждая должна попадать в
мгновенный путь (разбор — доли миллисекунды, бюджет всего пути 100 мс
занят самим действием, а не раздумьями).
"""
import json
import os
import time

EXAM = {
    # ── пульт ──
    "поставь на паузу": "media_control", "пауза": "media_control",
    "останови": "media_control", "стоп": "media_control",
    "продолжай": "media_control", "играй": "media_control",
    "включи обратно": "media_control",
    "следующий трек": "media_control", "следующая песня": "media_control",
    "переключи на следующий": "media_control",
    "переключи на след": "media_control",
    "предыдущий трек": "media_control",
    "мотни назад": "media_control", "отмотай назад": "media_control",
    "перемотай назад": "media_control", "промотай вперёд": "media_control",
    "включи музыку в браузере": "media_control",
    "включи музыку, она уже открыта": "media_control",
    # ── звук ──
    "сделай погромче": "volume_set", "сделай потише": "volume_set",
    "громче": "volume_set", "тише": "volume_set",
    # ── окна ──
    "покажи браузер": "window_focus", "покажи мне хром": "window_focus",
    "выведи телеграм": "window_focus",
    "сверни браузер": "window_minimize",
    "сверни всё": "minimize_all", "разверни все окна": "window_restore_all",
    "сделай браузер слева на экране": "window_place",
    "поставь хром справа": "window_place",
    "перенеси браузер на второй экран": "window_place",
    "перенеси проводник на второй экран": "window_place",
    "сделай её справа на экране": "window_place",
    "поставь его слева": "window_place",
    # ── прогулка ──
    "открой проводник": "go_to", "зайди на диск C": "go_to",
    "открой блокнот": "app_launch", "запусти калькулятор": "app_launch",
    # ── вкладки ──
    "следующая вкладка": "tab_control", "закрой вкладку": "tab_control",
    # ── сервисы ──
    "включи музыку": "service_open", "лисни музыку": "service_open",
    # ── режим ядра ──
    "исчезни": "orb_mode", "вернись в окно": "orb_mode",
    # ── её собственные окна ──
    "закрой браузер": "close_browser",
    "встань на стол": "avatar_window",
}


def run():
    rows = []
    from anamorf import reflex, reflex_learn
    from anamorf.config import CFG

    # ── 1. ВЕСЬ СПИСОК, ОДНОЙ СТРОКОЙ НА ПРОВАЛ ──
    bad = []
    for phrase, tool in EXAM.items():
        h = reflex.match(phrase)
        if not h or h[0] != tool:
            bad.append(f"«{phrase}» -> {h and h[0]}")
    rows.append((f"экзамен: {len(EXAM)} команд попадают в мгновенный путь",
                 not bad, "; ".join(bad[:6]) or f"все {len(EXAM)}"))

    # ── 2. СКОРОСТЬ: сам разбор обязан укладываться в доли бюджета ──
    reflex.match("прогрев")
    t0 = time.perf_counter()
    for phrase in EXAM:
        reflex.match(phrase)
    per = (time.perf_counter() - t0) * 1000 / len(EXAM)
    rows.append(("разбор фразы дешевле 5 мс (бюджет 100 мс — на действие)",
                 per < 5.0, f"{per:.2f} мс на фразу"))

    # ── 3. ОБУЧЕНИЕ: дважды через LLM — дальше мгновенно ──
    import anamorf.reflex_learn as rl
    p = rl._path()
    bak = p.read_text(encoding="utf-8") if p.exists() else None
    try:
        # не unlink, а перезапись: на машине владельца удаление файлов
        # программе запрещено, и тест обязан жить по тем же правилам
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"pending": {}, "learned": {}}', encoding="utf-8")
        rl._cache["rules"] = None
        born1 = rl.consider("врубни тот плейлист", "media_control",
                            {"action": "играй"}, True)
        born2 = rl.consider("врубни тот плейлист", "media_control",
                            {"action": "играй"}, True)
        rows.append(("фраза заучивается со второго совпадения",
                     not born1 and bool(born2)
                     and rl.lookup("Врубни тот плейлист!")
                     == ("media_control", {"action": "играй"}),
                     born2 or "не выучилась"))

        # защита 1: на неисполнившемся не учимся
        for _ in range(3):
            rl.consider("сделай красиво", "look_screen", {}, False)
        rows.append(("выдумка модели (не исполнилось) не заучивается",
                     rl.lookup("сделай красиво") is None, ""))

        # защита 2: опасный инструмент не заучивается никогда
        for _ in range(3):
            rl.consider("прибери тут", "fs_delete", {"path": "C:/"}, True)
        rows.append(("опасный инструмент не заучивается",
                     rl.lookup("прибери тут") is None, ""))

        # защита 3: та же фраза с ДРУГИМ вызовом сбрасывает счёт
        rl.consider("сделай штуку", "media_control", {"action": "пауза"}, True)
        rl.consider("сделай штуку", "volume_set", {"delta": 10}, True)
        rl.consider("сделай штуку", "media_control", {"action": "пауза"}, True)
        rows.append(("неоднозначная фраза не заучивается",
                     rl.lookup("сделай штуку") is None, ""))

        # защита 4: точная фраза, не подстрока
        rows.append(("выученное не ловит похожие фразы",
                     rl.lookup("врубни тот плейлист погромче") is None, ""))

        # защита 5: длинную речь не заучиваем
        long = "включи пожалуйста ту самую музыку которую мы слушали " \
               "вчера вечером когда сидели"
        for _ in range(3):
            rl.consider(long, "media_control", {"action": "играй"}, True)
        rows.append(("длинная фраза (контекст) не заучивается",
                     rl.lookup(long) is None, ""))

        # забывание руками
        note = rl.forget("забудь команду врубни тот плейлист")
        rows.append(("«забудь команду …» стирает выученное",
                     rl.lookup("врубни тот плейлист") is None, note))
    finally:
        p.write_text(bak if bak is not None
                     else '{"pending": {}, "learned": {}}',
                     encoding="utf-8")
        rl._cache["rules"] = None

    # ── 4. сцепка с main: выученное зовётся из диалога ──
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    import io as _io
    main = _io.open(os.path.join(root, "anamorf", "main.py"),
                    encoding="utf-8").read()
    rows.append(("диалог спрашивает выученные рефлексы",
                 "_rl.lookup(user_text)" in main
                 and "забудь команду" in main, ""))
    mgr = _io.open(os.path.join(root, "anamorf", "llm", "manager.py"),
                   encoding="utf-8").read()
    rows.append(("каждый вызов через LLM идёт в обучение",
                 "_rl.consider(" in mgr, ""))
    rows.append(("обучение отличает успех от отказа инструмента",
                 '"не нашла"' in mgr, ""))
    return rows
