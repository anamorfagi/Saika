"""РАЗБОР ЖИВЫХ ФРАЗ: экран, программа, сайт, вкладка.

Всё это ломалось вживую 19.08.2026 и чинилось по одной поломке за раз.
Здесь зафиксировано, как оно должно себя вести, чтобы не сломалось снова.
"""


def run():
    rows = []
    from server import pc_control as pc
    from server import ui_hands as uh

    # ── номер экрана из фразы (живой провал: «на втором экране включи
    #    Пинтерест» уходило в окно на первом) ─────────────────────────
    cases = [
        ("На втором экране сейчас открыт браузер Хром", 2),
        ("так, на втором монике включи ролик", 2),
        ("Окно браузера находится на экране 2", 2),
        ("открой на первом экране блокнот", 1),
        ("на третьем мониторе видео", 3),
        ("На каком экране сейчас браузер?", 0),   # вопрос, а не указание
        ("открой пинтерест", 0),
    ]
    bad = [c for c, want in cases if pc.screen_from_phrase(c) != want]
    rows.append(("номер экрана из фразы", not bad,
                 f"не разобрались: {bad}" if bad else f"{len(cases)} фраз"))

    # ── имя программы должно ПРОЗВУЧАТЬ (живой провал: агент-цикл
    #    запустил After Effects и лаунчер игры, которых никто не называл)
    said = {"t": ""}
    orig = pc._phrase
    pc._phrase = lambda: said["t"].lower()
    try:
        cases = [
            ("открой гугл хром", "Google Chrome", True),
            ("открой хром", "Google Chrome", True),
            ("запусти браузер", "Google Chrome", True),
            ("открой блендер", "Blender", True),
            ("открой телегу", "Telegram", True),
            ("ну ты запустишь ролик или нет?", "Adobe After Effects", False),
            ("тебе надо руки научиться использовать", "Beat Saber.exe", False),
            ("сделай потише", "Adobe Photoshop", False),
            ("а у тебя ещё голос не запустился", "All in One Launcher", False),
        ]
        bad = []
        for phrase, app, want in cases:
            said["t"] = phrase
            if pc._asked_by_human(app) != want:
                bad.append((phrase[:28], app))
    finally:
        pc._phrase = orig
    rows.append(("программу называет человек, а не модель", not bad,
                 f"разошлось: {bad}" if bad else f"{len(cases)} фраз"))

    # ── «ещё одно окно» — единственный повод запускать вторую копию ──
    cases = [("открой гугл хром", False), ("открой ещё одно окно хрома", True),
             ("запусти хром заново", True), ("перезапусти хром", True),
             ("открой новое окно браузера", True), ("открой браузер", False)]
    bad = [c for c, want in cases if bool(pc._WANT_NEW.search(c)) != want]
    rows.append(("вторая копия — только по прямой просьбе", not bad,
                 f"разошлось: {bad}" if bad else f"{len(cases)} фраз"))

    # ── сайт словами -> адрес ────────────────────────────────────────
    checks = [("пинтерест", "pinterest"), ("Pintrest", "pinterest"),
              ("ютуб", "youtube"), ("kinopoisk.ru", "kinopoisk")]
    bad = [(w, uh.site_url(w)) for w, part in checks
           if part not in uh.site_url(w)]
    rows.append(("название площадки -> адрес", not bad,
                 f"мимо: {bad}" if bad else f"{len(checks)} названий"))

    # ── слух коверкает имя вкладки: «Pintros» -> pinterest ───────────
    checks = [("Pintros", "pinterest", True), ("Пинтрест", "pinterest", True),
              ("ютуб", "youtube", True), ("Джарвис", "джарвис", False)]
    bad = []
    for spoken, want, known_want in checks:
        canon, known = pc._canon_tab_name(spoken)
        if known != known_want or (known and want not in canon.lower()):
            bad.append((spoken, canon, known))
    rows.append(("имя вкладки по звучанию", not bad,
                 f"мимо: {bad}" if bad else f"{len(checks)} имён"))

    # ── «включи музыку на ютубе» должен ловить рефлекс, а не модель ──
    from server import reflex
    # «включи музыку на YouTube» с 20.08 уходит в service_open — площадку
    # разберёт носитель, и откроется тот же YouTube (tests/test_services).
    cases = [("Сайка, включи музыку на YouTube", "service_open"),
             ("открой ютуб и найди дабстепчик", "web_open"),
             ("найди в гугле как варить борщ", "web_open"),
             ("закрой ютуб", None), ("что там на ютубе играет", None)]
    bad = []
    for phrase, want in cases:
        hit = reflex.match(phrase)
        got = hit[0] if hit else None
        if want and got != want:
            bad.append((phrase[:30], got))
        if want is None and got == "web_open":
            bad.append((phrase[:30], "поймал зря"))
    rows.append(("открыть сайт — рефлексом", not bad,
                 f"разошлось: {bad}" if bad else f"{len(cases)} фраз"))
    rows += run_windows_and_browser()
    return rows


def run_windows_and_browser():
    """ЖИВОЙ РАЗНОС 20.08.2026 — три промаха подряд в одном разговоре."""
    rows = []
    from server import reflex
    from server.ui_hands import guess_from_phrase

    # 1. «Перенеси» — это переезд, а не перепланировка. Было: «размещено
    #    по центру экрана 1, занимает 80% ширины и высоты».
    hit = reflex.match("Перенеси хром со второго экрана на первый")
    ok = (hit and hit[0] == "window_place"
          and hit[1].get("position") == "same"
          and hit[1].get("monitor") == 1
          and not hit[1].get("width") and not hit[1].get("height"))
    rows.append(("перенести — не расставить", bool(ok), str(hit)))

    # 2. Экран назван дважды: «со второго ... на первый». Цель — первый.
    hit = reflex.match("перенеси проводник на второй экран")
    rows.append(("экран без «откуда» тоже читается",
                 bool(hit) and hit[1].get("monitor") == 2, str(hit)))

    # 3. «Google Hrome» — это БРАУЗЕР, а не поиск в гугле. Было:
    #    google.com/search?q=ролик+hrome
    site, q = guess_from_phrase("Запусти ролик на в Google Hrome.")
    rows.append(("«гугл хром» — программа, а не площадка",
                 site == "" and q == "", f"site={site!r} query={q!r}"))
    rows.append(("и в поиск такое не уходит",
                 reflex.match("Запусти ролик на в Google Hrome.") is None,
                 "рефлекс молчит — фразу разбирает тот, кто умеет окна"))

    # 4. …но обычные фразы про площадки не сломались
    # «включи музыку на YouTube» с 20.08 идёт в service_open: площадка
    # названа прямо в просьбе, разбор носителя её увидит и откроет тот же
    # YouTube — но по дороге ещё и не перепишет привычку человека.
    for phrase, want in (("Сайка, включи музыку на YouTube", "service_open"),
                         ("включи какой-нибудь трек из железного человека",
                          "find_here"),
                         ("найди комфи юай бат", "find_here")):
        hit = reflex.match(phrase)
        rows.append((f"«{phrase[:34]}…» -> {want}",
                     bool(hit) and hit[0] == want,
                     str(hit)))
    return rows
