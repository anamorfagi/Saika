"""РЕЖИМ ИСЧЕЗНОВЕНИЯ И ПОНИМАНИЕ ФРАЗ ПРО ОКНА.

Владелец 23.08.2026: «можно прогу сделать с режимом исчезновения чтобы
чисто ядро с полосками осталось и уменьшилось чтобы я его мог перемещать
по системе».

Проверяем ровно то, что ломается молча:
  * короткие фразы про режим доходят рефлексом, а не через раздумья;
  * «вернись» БЕЗ уточнения в режим не лезет — это фраза про аватара;
  * страница знает про ?orb=1 и прячет лишнее;
  * окно ядра и модуль на месте, а сборка их кладёт;
  * «сделай браузер слева» — живая фраза владельца, которая однажды уже
    молчала: слово «браузер» лежит в списке «это не имя окна» ради
    «закрой браузер», и для расстановки запрет снят.
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run():
    rows = []
    from anamorf import reflex

    def hit(t):
        return reflex.match(t)

    for phrase in ("исчезни", "сожмись", "оставь только ядро",
                   "спрячься", "уйди в угол"):
        h = hit(phrase)
        rows.append((f"«{phrase}» -> режим исчезновения",
                     h == ("orb_mode", {"on": True}), str(h)))

    for phrase in ("вернись в окно", "разожмись", "верни интерфейс",
                   "выйди из режима"):
        h = hit(phrase)
        rows.append((f"«{phrase}» -> обратно в окно",
                     h == ("orb_mode", {"on": False}), str(h)))

    h = hit("вернись")
    rows.append(("голое «вернись» режим не трогает — это про аватара",
                 h is None or h[0] != "orb_mode", str(h)))

    # ── имя окна ──
    h = hit("Сделай браузер слева на экране.")
    rows.append(("«сделай браузер слева» — расстановка по виду программы",
                 h and h[0] == "window_place" and h[1].get("match") == "браузер"
                 and h[1].get("position") == "left", str(h)))
    h = hit("закрой браузер")
    rows.append(("«закрой браузер» остался про её собственный браузер",
                 h and h[0] == "close_browser", str(h)))
    h = hit("покажи что на экране")
    rows.append(("вопрос про экран окном не считается",
                 h is None or h[0] != "window_place", str(h)))
    h = hit("Сделай её справа на экране.")
    rows.append(("местоимение вместо имени — тоже расстановка",
                 h and h[0] == "window_place" and h[1].get("position") == "right",
                 str(h)))

    # ── файлы режима ──
    orb_py = os.path.join(ROOT, "anamorf", "orb.py")
    win_py = os.path.join(ROOT, "tools", "orb_window.py")
    rows.append(("модуль режима на месте", os.path.exists(orb_py), orb_py))
    rows.append(("окно ядра на месте", os.path.exists(win_py), win_py))

    feats = io.open(os.path.join(ROOT, "features.json"),
                    encoding="utf-8").read()
    rows.append(("orb.py записан в реестр — иначе не приедет в сборку",
                 '"orb.py"' in feats, ""))
    build = io.open(os.path.join(ROOT, "tools", "build_client.py"),
                    encoding="utf-8").read()
    rows.append(("сборка кладёт окно ядра в tools\\",
                 "orb_window.py" in build, ""))

    # ── страница знает про режим ──
    html = io.open(os.path.join(ROOT, "ui", "index.html"),
                   encoding="utf-8").read()
    rows.append(("страница различает ?orb=1", "window.ORBMODE" in html, ""))
    rows.append(("в режиме прячется всё, кроме ядра",
                 "html.orbmode #shell" in html and "html.orbmode #zorb" in html,
                 ""))
    rows.append(("микрофон в ядре не поднимается",
                 "!window.ORBMODE && localStorage.autoMic" in html, ""))
    rows.append(("полоски передаются окну ядра",
                 "zBandsSend" in html and "zBandsTake" in html, ""))
    # ЛОВУШКА ЗАМЫКАНИЯ (поймано стендом 23.08): разбор сообщений и сцена
    # живут в разных блоках, прямой вызов давал ReferenceError на каждом
    # кадре звука — то есть «полоски просто не работают».
    rows.append(("приём полосок вынесен в window",
                 "window.saikaBandsTake = zBandsTake" in html
                 and "window.saikaBandsTake) window.saikaBandsTake(m)" in html,
                 ""))
    rows.append(("расчёт полосок зовётся из звукового потока",
                 "window.saikaPushBands = function" in html
                 and "if (window.saikaPushBands) window.saikaPushBands();" in html,
                 ""))
    rows.append(("подложка приложения в режиме скрыта",
                 "html.orbmode #aurora" in html, ""))
    # ЛИШНЕЕ ПРЯЧЕТСЯ ПО СТРОЕНИЮ, А НЕ ПО СПИСКУ id: список проигрывает
    # гонку любой новой панели, и она вылезет в окне чёрным прямоугольником
    rows.append(("в окне видна ровно одна ветка — сцена с ядром",
                 "html.orbmode body > *:not(#shell)" in html
                 and "html.orbmode #shell > *:not(#zstage)" in html
                 and "html.orbmode #zstage > *:not(#zscene)" in html, ""))
    rows.append(("предки ядра ничего не рисуют",
                 "background:none!important;border:0!important" in html, ""))
    rows.append(("виджет живой: появление, дыхание, наведение",
                 "@keyframes orb-in" in html and "@keyframes orb-breath" in html
                 and "html.orbmode #zcore:hover" in html, ""))
    rows.append(("слушает / думает / говорит показаны формой",
                 "orb-hear" in html and "orb-think" in html
                 and "orb-talk" in html and "window.orbPulse" in html, ""))
    rows.append(("полос столько, сколько влезает — иначе мех вместо звука",
                 "const step = Math.max(1, Math.round(NB" in html
                 and "i+=step" in html, ""))
    # ЖИВОЙ ПРОВАЛ 23.08: вернул окно — а там одна шапка и пустота
    rows.append(("интерфейс собирается обратно, когда режим выключен",
                 "m.type==='orb' && !m.on && window.saikaPullReset" in html
                 and "window.saikaPullReset = pullReset" in html
                 and "visibilitychange" in html, ""))

    # ── ВЫДЕРНУТЬ ЯДРО ЗА КОЛЬЦО ──
    rows.append(("кольцо различает нажатие и тягу",
                 "function pullBegin" in html and "function ringTap" in html
                 and "if (pullBegin(ev, ringTap)) return;" in html, ""))
    rows.append(("нажатие по кольцу осталось прежним (замолчать/шумодав)",
                 "if (!hit('#btn-mic-ns')) return;" in html
                 and "замолчала" in html, ""))
    rows.append(("при тяге уходит всё, кроме ядра",
                 "body.zpull #zfield" in html and "body.zpull .zlab" in html,
                 ""))
    rows.append(("на время тяги гасится перспектива — иначе шар и кольцо "
                 "едут врозь",
                 "body.zpull #zstage{perspective:none!important}" in html, ""))
    # МЯГКИЙ ОТРЫВ: внутри окна ядро только «в руке», программа уходит
    # ровно тогда, когда рука вышла за её край
    rows.append(("внутри окна интерфейс отступает, а не исчезает",
                 "body.zpull #zsvg, body.zpull .zlab{opacity:.14" in html
                 and "drop-shadow(0 26px 34px" in html, ""))
    rows.append(("передача на краю окна, а не в начале движения",
                 "e.clientX >= innerWidth - 2" in html
                 and "handed = true;" in html, ""))
    rows.append(("отпустил внутри — ядро возвращается на место",
                 "function pullBack" in html and "body.zback #zfield" in html,
                 ""))
    rows.append(("место передаётся экранными координатами",
                 "pullSend(e.screenX, e.screenY)" in html
                 and "follow:true, x:sx, y:sy" in html, ""))
    rows.append(("заказ уходит В НАЧАЛЕ движения — приложение исчезает "
                 "сразу, а не после отпускания",
                 "if (!pulling){" in html
                 and html.index("pullSend(e.screenX")
                 < html.index("const done = e =>"), ""))
    rows.append(("ядро прилипает к краю экрана, как пузырь на телефоне",
                 "_snap_edges" in io.open(win_py, encoding="utf-8").read(),
                 ""))
    rows.append(("призрак ровно того размера, каким откроется окно",
                 "pullW / Math.max(1, orb.clientWidth" in html, ""))
    rows.append(("интерфейс не остаётся свёрнутым, если сервер промолчал",
                 "pullReset" in html and "}, 4000);" in html, ""))

    # ── НАТИВНЫЙ ВИДЖЕТ (2026-08-23): веб-движок в окне на столе заменён
    #    на QML — там прозрачность штатная, а не борьба ──
    qml_py = os.path.join(ROOT, "tools", "orb_qml.py")
    qml = os.path.join(ROOT, "ui", "orb.qml")
    rows.append(("окно ядра на QML на месте", os.path.exists(qml_py), qml_py))
    rows.append(("рисунок ядра на месте", os.path.exists(qml), qml))
    qsrc = io.open(qml_py, encoding="utf-8").read()
    rows.append(("альфа-буфер выставлен до создания окна — без него "
                 "прозрачности не будет",
                 qsrc.index("setAlphaBufferSize")
                 < qsrc.index("QApplication(sys.argv)"), ""))
    rows.append(("окно прозрачное и без рамки",
                 "setColor(QColor(0, 0, 0, 0))" in qsrc
                 and "FramelessWindowHint" in qsrc, ""))
    rows.append(("меню правой кнопки живёт на QApplication",
                 "app = QApplication(sys.argv)" in qsrc, ""))
    rows.append(("данные — опросом одной ручки, без необязательных модулей",
                 "/api/orb/live" in qsrc and "QWebSocket" not in qsrc, ""))
    rows.append(("опрос адаптивный: в тишине реже",
                 "setInterval(50 if b else 220)" in qsrc, ""))
    qml_src = io.open(qml, encoding="utf-8").read()
    rows.append(("виджет показывает состояние органов, а не выдумывает",
                 "root.organs[key]" in qml_src and "broken" in qml_src
                 and "loading" in qml_src, ""))
    rows.append(("дыхание, поворот при раздумье, свечение при речи",
                 "breath" in qml_src and "spin" in qml_src
                 and "talkGlow" in qml_src, ""))
    rows.append(("риски, полосы и дуги стоят в разных поясах",
                 "u * 0.232" in qml_src and "u * 0.375" in qml_src, ""))
    win = io.open(win_py, encoding="utf-8").read()
    rows.append(("окно открывается там, куда положили",
                 "ANAMORF_ORB_XY" in win, ""))
    rows.append(("и едет за курсором, пока зажата кнопка",
                 "ANAMORF_ORB_FOLLOW" in win and "GetAsyncKeyState" in win, ""))
    rows.append(("слежение за курсором не вечное",
                 "_follow_left" in win, ""))
    rows.append(("наведение мыши доходит до страницы — иначе шар «мёртвый»",
                 "if t == QEvent.MouseMove and self._press is None:" in win, ""))
    rows.append(("окно докладывает в лог, что реально видно на странице",
                 "страница ядра:" in win, ""))

    import inspect
    from anamorf import orb as _orb
    sig = str(inspect.signature(_orb.start))
    rows.append(("start принимает место и слежение",
                 "x=None" in sig and "y=None" in sig and "follow" in sig, sig))
    rows.append(("состояние отдаёт размер окна для призрака",
                 "w" in _orb.state(), str(_orb.state())))

    # ── сервер ──
    main = io.open(os.path.join(ROOT, "anamorf", "main.py"),
                   encoding="utf-8").read()
    for route in ('@app.get("/api/orb")', '@app.post("/api/orb")',
                  '@app.post("/api/orb/seen")'):
        rows.append((f"ручка {route.split('(')[1].strip(')')} есть",
                     route in main, ""))
    rows.append(("реле полосок в вебсокете", 'mtype == "bands"' in main, ""))
    rows.append(("сервер отдаёт кадр для виджета",
                 '@app.get("/api/orb/live")' in main
                 and "ORB_LIVE" in main, ""))
    rows.append(("устаревший кадр не показываем — застывшая картинка "
                 "читается как «повисло»",
                 'fresh = (now - ORB_LIVE["ts"]) < 0.5' in main, ""))
    osrc = io.open(orb_py, encoding="utf-8").read()
    rows.append(("сборка берёт QML-окно, если оно приехало",
                 'qml = tools / "orb_qml.py"' in osrc, ""))
    rows.append(("сборка кладёт оба окна",
                 "orb_qml.py" in build, ""))

    rows.append(("при старте режим сбрасывается, окно возвращается",
                 "_orb.boot()" in main, ""))

    src = io.open(orb_py, encoding="utf-8").read()
    # ОКНА НЕ ПРИВЯЗАНЫ ДРУГ К ДРУГУ (2026-08-23)
    rows.append(("прячем только СВОИ окна, а не всё с похожим заголовком",
                 "def _ours(" in src and "_ours(hwnd)" in src, ""))
    da = io.open(os.path.join(ROOT, "anamorf", "desk_avatar.py"),
                 encoding="utf-8").read()
    rows.append(("живое окно с моделью перезапуск сервера не трогает",
                 "_alive_window" in da
                 and "уже стоит на столе" in da, ""))
    rows.append(("сервер объявляет смену режима вслух",
                 "_announce" in src and '"type": "orb"' in src, ""))
    rows.append(("сторож возвращает окно, если ядро упало",
                 "_watch" in src and "show_main()" in src, ""))
    rows.append(("окно прячем только после доклада ядра",
                 "_hide_when_ready" in src, ""))

    from anamorf import self_control as sc
    rows.append(("голосовой инструмент зарегистрирован",
                 "orb_mode" in sc.CALLS and "orb_mode" in sc.NAMES, ""))
    rows += run_windows()
    rows += run_no_type()
    return rows


def run_windows():
    """Отдельный набор — про руки, а не про ядро (зовётся из run())."""
    import io
    import os
    rows = []
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # ⚠️ ЖИВОЙ ПРОВАЛ 23.08: «перенеси браузер на второй экран» -> ctypes
    # ArgumentError в GetWindowRect. Причина: highlight_win объявил argtypes
    # на ОБЩЕМ ctypes.windll.user32, и сломался чужой вызов той же функции.
    for f in ("highlight_win.py", "highlight.py"):
        src = io.open(os.path.join(ROOT, "anamorf", f), encoding="utf-8").read()
        rows.append((f"{f}: типы объявляются на своём экземпляре библиотеки",
                     'ctypes.WinDLL("user32"' in src, ""))

    from anamorf.pc_control import _is_mine
    rows.append(("свои окна не попадают в список целей",
                 _is_mine("ANAMORF") and _is_mine("Ядро")
                 and _is_mine("Сайка") and _is_mine("ANAMORF — Google Chrome"),
                 ""))
    rows.append(("чужие окна остаются целями",
                 not _is_mine("Google Chrome") and not _is_mine("Проводник")
                 and not _is_mine("Twitch — Chrome"), ""))
    return rows


def run_no_type():
    """Печать в чужой чат запрещена НА УРОВНЕ ФУНКЦИИ ПЕЧАТИ (23.08)."""
    import io
    import os
    rows = []
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    from anamorf import pc_control as pc

    cases = [({"title": "Claude", "proc": "claude.exe"}, True),
             ({"title": "ANAMORF", "proc": "ANAMORF.exe"}, True),
             ({"title": "Ядро", "proc": "python.exe"}, True),
             ({"title": "Claude — Google Chrome", "proc": "chrome.exe"}, False),
             ({"title": "YouTube — Google Chrome", "proc": "chrome.exe"}, False),
             ({"title": "Проводник", "proc": "explorer.exe"}, False)]
    was = pc._foreground
    try:
        for win, forbidden in cases:
            pc._foreground = lambda w=win: w
            got = bool(pc._type_forbidden())
            rows.append((f"печать при «{win['title']}» "
                         + ("запрещена" if forbidden else "разрешена"),
                         got == forbidden, ""))
    finally:
        pc._foreground = was
    src = io.open(os.path.join(ROOT, "anamorf", "pc_control.py"),
                  encoding="utf-8").read()
    rows.append(("открытие адреса сперва выводит браузер вперёд",
                 "_ensure_browser_front" in src
                 and "_bok, _bwhere = _ensure_browser_front()" in src, ""))
    return rows
