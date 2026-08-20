"""МОИ СЕРВИСЫ — «включи музыку» у каждого человека своё (2026-08-20).

Владелец: «включи музыку — можно делать запуск сервиса у человека. У них
это Спотик, у меня это Яндекс.Музыка. Она может спросить, где это открыть,
первый раз. Типа у меня Яндекс.Музыка в браузере Яндекса с моим аккаунтом,
у некоторых есть прям приложение, у того же друга на компе Спотифай есть
как прога. То есть она должна уточнить, где именно находится музыка, что
открыть, чтобы запустить его музыку».

ЧТО ЗДЕСЬ РЕШАЕТСЯ. «Включи музыку» — это не название площадки и не файл
на диске, а ПРИВЫЧКА конкретного человека. Угадывать её нельзя: открыть
чужому человеку Spotify, когда у него подписка на Яндексе и плейлисты там,
— это не помощь. Но и переспрашивать каждый раз нельзя тоже: привычка на
то и привычка, что спрашивают о ней один раз.

Отсюда правило: НЕ ЗНАЮ — СПРОСИ, ЗНАЮ — ДЕЛАЙ МОЛЧА. Ответ человека
запоминается за ним лично (у каждого голоса свой набор), поэтому у друга
за тем же компьютером «включи музыку» откроет его Спотифай, а не чужую
Яндекс.Музыку.

ЭТО НЕ ПРО МУЗЫКУ. Владелец, когда увидел первую версию: «думай тут не
просто логикой „ага, запрос про музыку“, а пробуй писать универсальные
алгоритмы работы. Если я вот тебе написал сейчас про музыку в браузере,
что будет, если я её попрошу открыть музыку в папке „Музыка“ на самом
компе?»

Он прав, и алгоритм здесь один на всё: НАМЕРЕНИЕ + ГДЕ ИМЕННО.

  намерение  музыка, видео, почта, заметки — что человек хочет
  носитель   ЧЕМ это открывается, и таких видов ровно четыре:
               site   — сайт в браузере (и в КАКОМ браузере)
               app    — программа на компьютере
               folder — папка на диске: «музыка в папке Музыка на компе»
               window — то, что уже открыто, — трогаем его, а не новое

Разбор носителя один и тот же, откуда бы фраза ни пришла: из самой
просьбы («включи музыку из папки Музыка») или из ответа на вопрос («а где
у тебя музыка?»). Поэтому добавить пятый вид или новое намерение — это
строчка в таблице, а не новая ветка кода.

ОДНОРАЗОВО ИЛИ НАВСЕГДА. Если человек назвал место прямо в просьбе, мы его
слушаемся, но привычку НЕ переписываем: «сегодня включи из папки» не
значит «отныне всегда из папки». Переписывает только явное «запомни»,
«всегда» или «по умолчанию» — и, конечно, ответ на прямой вопрос.

ЧТО ЗАПОМИНАЕТСЯ. Три вещи, и все три названы в просьбе владельца:
  * ЧЕМ — приложение на компьютере или сайт в браузере;
  * ГДЕ ИМЕННО — в каком браузере, если это сайт. «В браузере Яндекса с
    моим аккаунтом» значит именно Яндекс.Браузер: аккаунт живёт там, и
    открыть тот же адрес в Chrome — это открыть чужую пустую страницу;
  * КАК ЗОВЁТСЯ — чтобы сказать человеку вслух, что именно открываю.

Хранится в data/services.json. Правится голосом: «музыку открывай в
Спотифае» — перезапишет.
"""
import json
import logging
import re
import time

from server.config import CFG, ROOT

log = logging.getLogger("saika.services")

PATH = ROOT / "data" / "services.json"

# Виды сервисов, у которых «включи X» зависит от человека. Список короткий
# намеренно: это не каталог сайтов, а места, где угадывание вредит.
KINDS = {
    "музыка": ("музыку", "музыка", "музычку", "музло", "трек", "плейлист"),
    "видео": ("видео", "ролики", "фильм", "кино"),
    "почта": ("почту", "почта", "мыло"),
    "заметки": ("заметки", "заметку", "блокнот"),
}

# Браузеры по имени — «в браузере Яндекса» это не Chrome
BROWSERS = {
    "яндекс": "browser", "яндекса": "browser", "яндекс браузер": "browser",
    "хром": "chrome", "chrome": "chrome", "гугл хром": "chrome",
    "edge": "msedge", "эдж": "msedge", "firefox": "firefox",
    "фаерфокс": "firefox", "опера": "opera", "opera": "opera",
}

# ПРИМЕТЫ НОСИТЕЛЯ. Одна таблица на все намерения: добавить новый вид —
# это строчка здесь, а не ветка в коде.
CARRIER_HINTS = (
    ("folder", r"\b(?:папк\w*|директори\w*|каталог\w*|на\s+компе?\b|"
               r"на\s+компьютере|на\s+диске|локальн\w*|с\s+диска|"
               r"файл\w*|моей\s+коллекци\w*|библиотек\w*\s+на\s+диске)"),
    ("app",    r"\b(?:прог\w*|приложени\w*|программ\w*|десктоп\w*|"
               r"на\s+компе\s+как\s+прог\w*|установлен\w*|плеер\w*)"),
    ("window", r"\b(?:в\s+открыт\w*|в\s+текущ\w*|в\s+этой\s+вкладк\w*|"
               r"там\s+где\s+уже|уже\s+открыт\w*|в\s+этом\s+окне)"),
    ("site",   r"\b(?:сайт\w*|браузер\w*|в\s+вебе|онлайн|в\s+интернете)"),
)

# «запомни это навсегда» — против «сегодня сделай так»
FOREVER = r"\b(?:запомн\w+|всегда|по\s+умолчанию|отныне|теперь\s+всегда|" \
          r"впредь|сохрани\s+как)"

# ожидание ответа на «а где у тебя музыка?»
ASK = {"on": False, "kind": "", "who": "", "ts": 0.0}


# ПАДЕЖИ (2026-08-20). Человек говорит «в хромЕ», «в оперЕ», «яндекс
# музыкУ», «прогОЙ». Точное совпадение слов на этом ломается и молча
# теряет то самое, ради чего мы спрашивали, — браузер и название сервиса.
# Морфологии в проекте нет и не нужно: хватает грубой основы — слово без
# двух последних букв, если оно длинное. «музыку»->«музык», «музыка»->
# «музык», «хроме»->«хром», «хром»->«хром».
_TAIL = "аеёиоуыэюяйьъ"


def _stem(w: str) -> str:
    w = w.strip().lower()
    while len(w) > 4 and w[-1] in _TAIL:
        w = w[:-1]
    return w


def _norm(text: str) -> str:
    return " ".join(_stem(w) for w in re.findall(r"[\wёЁ-]+",
                                                 (text or "").lower()))


def _load() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d: dict):
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except Exception as e:
        log.warning("сервисы не сохранились: %s", e)


def kind_of(phrase: str) -> str:
    """Какой вид сервиса назван во фразе. Пусто — ни один."""
    low = (phrase or "").lower()
    words = set(re.findall(r"[\wёЁ-]+", low))
    for kind, names in KINDS.items():
        if words & set(names):
            return kind
    return ""


def get(kind: str, who: str = "") -> dict:
    """Чем этот человек слушает музыку. Пусто — ещё не спрашивали."""
    d = _load()
    rec = (d.get(who or "", {}) or {}).get(kind)
    if not rec and who:
        rec = (d.get("", {}) or {}).get(kind)   # общее на всех, если есть
    return rec or {}


def remember(kind: str, rec: dict, who: str = ""):
    d = _load()
    d.setdefault(who or "", {})[kind] = dict(rec, ts=time.time())
    _save(d)
    log.info("Запомнила: %s у «%s» — %s", kind, who or "всех", rec)


def forget(kind: str, who: str = ""):
    d = _load()
    (d.get(who or "") or {}).pop(kind, None)
    _save(d)


def carrier_of(text: str) -> str:
    """Какой носитель назван словами. Пусто — не назван вовсе."""
    low = (text or "").lower()
    for name, rx in CARRIER_HINTS:
        if re.search(rx, low):
            return name
    return ""


def forever(text: str) -> bool:
    """Это «запомни навсегда» или «сделай так сейчас»?"""
    return bool(re.search(FOREVER, (text or "").lower()))


def _site_of(text: str, kind: str = ""):
    """Знакомая площадка в тексте -> (адрес, как называется).

    Три ловушки, и все три — живые:

    1. ПО СЛОВАМ, А НЕ ПО ПОДСТРОКЕ. «вк» находилось внутри «вкЛЮЧИ», и
       «включи музыку» открывало ВКонтакте.
    2. СЛОВО ВИДА — ЭТО НАМЕРЕНИЕ. В каталоге есть и «музыка», и «яндекс
       музыка»; «включи музыку НА ЮТУБЕ» находило «музыку» раньше «ютуба».
       Поэтому площадку ищем прежде всего ПОСЛЕ предлога места: человек
       говорит «на ютубе», «в спотифае», «через яндекс».
    3. ...но «яндекс музыка» — это цельное имя площадки, и выкидывать из
       него слово «музыка» нельзя. Поэтому слово вида не вырезается из
       текста, а лишь проигрывает при выборе.
    """
    try:
        from server import ui_hands
        words = _norm(text).split()
        kinds = set()
        for names in ([KINDS.get(kind)] if kind else KINDS.values()):
            kinds |= {_stem(n) for n in (names or ())}
        best = None                      # (после предлога, длина, позиция)
        for name in ui_hands._HOME:
            parts = _norm(name).split()
            if not parts:
                continue
            for k in range(len(words) - len(parts) + 1):
                if words[k:k + len(parts)] != parts:
                    continue
                after = bool(k and words[k - 1] in
                             ("на", "в", "во", "через", "с", "со", "у"))
                # чистое слово вида («музыка») площадкой считаем только
                # если человек не назвал настоящую площадку рядом
                only_kind = len(parts) == 1 and parts[0] in kinds
                rank = (after and not only_kind, not only_kind,
                        len(parts), k)
                if best is None or rank > best[0]:
                    best = (rank, ui_hands._HOME[name], name)
                break
        # НАЗВАЛИ ТОЛЬКО ВИД, БЕЗ МЕСТА — это не площадка, а «включи мою
        # музыку». Возвращаем пусто, чтобы сработало главное правило
        # модуля: не знаю привычку — спроси, а не открывай наугад.
        if best and (best[0][0] or best[0][1]):
            return best[1], best[2]
    except Exception as e:
        log.debug("разбор названия площадки: %s", e)
    return "", ""


def _browser_of(text: str) -> str:
    n = _norm(text)
    low = (text or "").lower()
    for name in sorted(BROWSERS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(_norm(name)) + r"\b", n):
            # «яндекс» — это и площадка, и браузер: браузером считаем
            # только рядом со словом «браузер»
            if name.startswith("яндекс") and "браузер" not in low:
                continue
            return BROWSERS[name]
    return ""


_DROP = ("в", "во", "на", "у", "меня", "это", "прога", "прогой", "прогу",
         "программа", "программой", "приложение", "приложением", "браузере",
         "браузер", "браузера", "открывай", "открой", "открывать", "включи",
         "мо", "моем", "моём", "моей", "аккаунтом", "моим", "с", "есть",
         "как", "тут", "здесь", "папке", "папка", "папку", "директории",
         "компе", "компьютере", "диске", "лежит", "лежат", "хранится",
         "музыку", "музыка", "видео", "почту", "заметки")


# ГДЕ ИМЕННО ВНУТРИ (2026-08-20). Владелец: «или вообще я её попрошу
# открыть в текущем окне браузера сайт или прогу, типа ТГ с каналом, где я
# обычно смотрю кинчик — тут такой же алгоритм работы мог бы справиться».
# Мог бы, если у носителя есть ещё одно поле: КУДА внутри него идти.
# Телеграм — носитель, канал «кинчик» — место внутри; браузер — носитель,
# вкладка или плейлист — место внутри. Открыть Телеграм и остановиться —
# это не «включи, где я смотрю кино».
_INSIDE = re.compile(
    r"\b(?:с\s+|со\s+|на\s+|в\s+)?(?:канал\w*|чат\w*|груп\w*|"
    r"плейлист\w*|подборк\w*|вкладк\w*|раздел\w*|папк\w*\s+внутри)"
    r"\s+(?:где\s+я\s+(?:обычно\s+|всегда\s+|часто\s+)?"
    r"(?:смотрю|слушаю|читаю|сижу|зависаю)\s+)?"
    r"[«\"']?([\wёЁ0-9 ._-]{2,40}?)[»\"']?"
    r"\s*(?:[.!?,]|$)", re.I)
# «где я обычно смотрю кинчик» — место названо не именем, а привычкой
_INSIDE_HABIT = re.compile(
    r"\bгде\s+я\s+(?:обычно\s+|всегда\s+|часто\s+)?"
    r"(?:смотрю|слушаю|читаю|сижу|зависаю|торчу)\s+"
    r"[«\"']?([\wёЁ0-9 ._-]{2,40}?)[»\"']?\s*(?:[.!?,]|$)", re.I)

# путь или имя папки: «в папке Музыка», «из папки D:/Music», «на диске D»
_PATH = re.compile(
    r"(?:[a-zа-яё]:[\\/][^\s,.;]*)"
    r"|(?:(?:папк\w*|директори\w*|каталог\w*)\s+"
    r"[«\"']?([\wёЁ0-9 ._\\/:-]{2,40}?)[»\"']?"
    r"\s*(?:\s+на\s+(?:сам\w+\s+)?(?:комп\w*|диске?\w*)|[.!?,]|$))", re.I)


def _inside_of(text: str) -> str:
    m = _INSIDE.search(text or "")
    if m and m.group(1):
        v = m.group(1).strip(" .,!?")
        if v and v not in ("внутри", "там"):
            return v
    m = _INSIDE_HABIT.search(text or "")
    if m:
        return m.group(1).strip(" .,!?")
    return ""


def _path_of(text: str) -> str:
    m = _PATH.search(text or "")
    if not m:
        return ""
    return (m.group(1) or m.group(0)).strip(" .,!?")


def _name_of(text: str, cut_inside: bool = True) -> str:
    """Остаток фразы как ИМЯ: программы, папки — чего угодно.

    Хвост «с каналом кинчик» отрезаем: это МЕСТО ВНУТРИ носителя, а не
    часть его имени. Без этого «тг с каналом кинчик» давало программу с
    именем «тг каналом кинчик», которой на компьютере, конечно, нет.
    """
    text = text or ""
    if cut_inside:
        m = _INSIDE.search(text) or _INSIDE_HABIT.search(text)
        if m and m.start() > 0:
            text = text[:m.start()]
    rest = re.sub(r"[^\wёЁ\s:\\/-]", " ", text.lower())
    words = [w for w in rest.split() if w and w not in _DROP]
    return " ".join(words[:4]).strip()


def parse(kind: str, answer: str) -> dict:
    """Фраза -> носитель. ОДИН разбор и для ответа на вопрос, и для места,
    названного прямо в просьбе: «включи музыку из папки Музыка на компе».

    Порядок решения: сперва явная примета носителя (папка/прога/окно/сайт),
    потом знакомая площадка, и лишь в конце — «незнакомое имя = программа».
    Именно в таком порядке, потому что «музыка в папке Музыка» содержит
    слово «музыка», которое знакомо как площадка, — а человек говорит про
    диск, и слово «папка» здесь важнее.
    """
    low = (answer or "").lower().strip(" .!?")
    if not low:
        return {}
    how = carrier_of(low)
    url, title = _site_of(low, kind)
    browser = _browser_of(low)

    inside = _inside_of(answer or "")
    if how == "folder":
        path = _path_of(low) or _name_of(low) or kind
        return {"how": "folder", "path": path, "title": f"папка «{path}»",
                "inside": inside}
    if how == "window":
        return {"how": "window", "title": title or _name_of(low) or kind,
                "url": url, "inside": inside}
    if how == "app":
        app = _name_of(low) or title
        return {"how": "app", "app": app, "title": app, "inside": inside}
    if browser or (how == "site" and (url or title)):
        return {"how": "site", "url": url or title or kind,
                "browser": browser, "title": title or _name_of(low) or kind,
                "inside": inside}
    if url:
        return {"how": "site", "url": url, "browser": browser,
                "title": title, "inside": inside}
    name = _name_of(low)
    if not name:
        return {}
    # НИЧЕГО ЗНАКОМОГО. Незнакомое имя — это почти всегда программа
    # («аимп», «фубар»), а не сайт: сайты человек называет теми именами,
    # что у нас в каталоге, а плееры ставит какие хочет.
    return {"how": "app", "app": name, "title": name, "inside": inside}


def question(kind: str) -> str:
    return (f"А {kind} у тебя где? Скажи, чем открывать: программой на "
            f"компьютере («спотифай программой») или сайтом и в каком "
            f"браузере («яндекс музыка в браузере яндекса») — запомню и "
            "больше спрашивать не буду.")


def arm(kind: str, who: str = "") -> str:
    ASK.update(on=True, kind=kind, who=who or "", ts=time.time())
    return question(kind)


def waiting() -> dict:
    life = float(CFG.get("services.ask_life_s", 180))
    if ASK["on"] and time.time() - ASK["ts"] > life:
        ASK.update(on=False)
    return dict(ASK) if ASK["on"] else {}


def learn_answer(answer: str) -> str:
    """Человек ответил на «а где у тебя музыка?»."""
    w = waiting()
    if not w:
        return ""
    rec = parse(w["kind"], answer)
    if not rec:
        return ""                       # не поняли — пусть говорит иначе
    ASK.update(on=False)
    remember(w["kind"], rec, w["who"])
    return open_it(w["kind"], w["who"], first=True)


def open_it(kind: str, who: str = "", first: bool = False,
            phrase: str = "") -> str:
    """Открыть то, что человек имел в виду.

    Порядок решения — тот же, что у человека в голове:
      1. МЕСТО НАЗВАНО ПРЯМО В ПРОСЬБЕ («включи музыку из папки Музыка»,
         «открой ТГ с каналом, где я смотрю кинчик») — слушаемся её, и
         привычку НЕ переписываем: «сегодня так» не значит «всегда так».
         Переписываем только на явное «запомни / всегда / по умолчанию».
      2. МЕСТО НЕ НАЗВАНО, привычка есть — делаем молча.
      3. Ни того, ни другого — спрашиваем ОДИН раз и запоминаем ответ.
    """
    # МЕСТО ИЗ САМОЙ ПРОСЬБЫ. Спрашиваем не «есть ли слово „папка“», а
    # тот же разбор, что и для ответа: он сам решит, названо место или
    # только вид («включи музыку» -> пусто -> идём к привычке).
    rec, once = {}, False
    if phrase:
        rec = parse(kind, phrase)
        once = bool(rec) and not forever(phrase)
        if rec and forever(phrase):
            remember(kind, rec, who)
            first = True
    if not rec:
        rec = get(kind, who)
    if not rec:
        return arm(kind, who)
    r = _do(kind, rec)
    head = ""
    if first:
        head = f"Запомнила: {kind} у тебя — {rec.get('title') or kind}. "
    elif once:
        head = "Сделала как просил, в привычках менять не стала. "
    return head + str(r)


def _do(kind: str, rec: dict) -> str:
    """Исполнить носитель. Ветка на каждый вид — и это ВСЯ разница между
    ними: добавить пятый вид значит дописать сюда одну ветку."""
    how = rec.get("how") or "site"
    inside = (rec.get("inside") or "").strip()
    name = rec.get("title") or rec.get("app") or rec.get("url") or kind
    try:
        if how == "folder":
            # ПАПКА НА ДИСКЕ — ТОЖЕ НОСИТЕЛЬ (2026-08-20, вопрос владельца:
            # «что будет, если я попрошу открыть музыку в папке Музыка на
            # самом компе»). Открываем проводник на этой папке — и, если
            # названо что-то внутри, ищем там же.
            from server import pc_control
            path = rec.get("path") or kind
            r = pc_control.open_folder(path)
            if inside:
                r = str(r) + f" Ищу внутри: «{inside}»."
            return str(r)
        if how == "app":
            from server import pc_control
            r = pc_control.launch(rec.get("app") or name)
            if inside:
                # Открыть Телеграм и остановиться — это не «включи канал,
                # где я смотрю кино». Ищем место внутри программы её же
                # поиском: Ctrl+F есть почти везде.
                r = str(r) + _inside_app(rec.get("app") or name, inside)
            return str(r)
        if how == "window":
            from server import pc_control
            w = pc_control.work_window() or {}
            if not w:
                return ("Просил в уже открытом окне — а открытого нет. "
                        "Скажи, что открыть, или разреши открыть новое.")
            pc_control.window_focus_on(0, w.get("title", "")[:20])
            return (f"Работаю в уже открытом «{w.get('title','')[:50]}», "
                    "нового не открываю."
                    + (f" Ищу внутри: «{inside}»." if inside else ""))
        # site
        from server import ui_hands, send_gate
        send_gate.allow_web(f"{kind}: {name}")
        return ui_hands.web_open(rec.get("url") or name, inside,
                                 browser=rec.get("browser") or "")
    except Exception as e:
        return f"Не смогла открыть {kind} ({name}): {e}"


def _inside_app(app: str, what: str) -> str:
    """Место внутри программы — её собственным поиском."""
    try:
        import time
        from server import ui_hands
        time.sleep(float(CFG.get("services.app_wait_s", 2.0)))
        ui_hands.press("ctrl+f")
        time.sleep(0.3)
        ui_hands.type_text(what)
        return (f" Ищу внутри «{app}»: «{what}» — открыла поиск и вписала. "
                "Выбери нужное или скажи «первый».")
    except Exception as e:
        log.debug("поиск внутри %s: %s", app, e)
        return f" Внутри «{app}» ищи «{what}» — сама не дотянулась."
