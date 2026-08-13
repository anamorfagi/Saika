"""Встроенный видимый браузер — «руки» Сайки в её же процессе.

Не отдельный сервис и не вторая копия: обычный модуль, как память или TTS.
Сайка зовёт web_search/open_page как function-calling инструменты
(server/llm/tools.py подключает их, только если внешний HandsPC не запущен —
дома ничего не конфликтует).

Окно Chromium настоящее (headless=False): видно, как она набирает запрос
и ходит по страницам. Жизненный цикл окна — как у человека за компом:
поискала → окно осталось; тема закончилась → сама спрашивает, нужно ли ещё;
«закрой» → close_browser. Плюс страховка: простой > browser.idle_close_min —
закрывает молча сама.

Технически: sync-Playwright требует жить в одном потоке — здесь выделенный
поток с очередью заданий, снаружи обычные блокирующие функции.
"""
import logging
import queue
import re
import subprocess
import sys
import threading
import time

from server.config import CFG

log = logging.getLogger("saika.browser")

SEARCH_URL = "https://duckduckgo.com/"

_jobs: "queue.Queue" = queue.Queue()
_thread = None
_lock = threading.Lock()
STATE = {"open": False, "last_used": 0.0, "installing": False,
         "used_in_dialog": False}


def available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _chromium_present() -> bool:
    """Пакет может стоять, а сам Chromium — нет (загрузка рвалась):
    проверяем бинарник, не пакет."""
    import glob
    import os
    base = os.environ.get("LOCALAPPDATA", "")
    return bool(glob.glob(os.path.join(
        base, "ms-playwright", "chromium-*", "chrome-win*", "chrome.exe")))


INSTALLING_MSG = (
    "Мой браузер ещё докачивается (загрузку рвала сеть — теперь качаю "
    "с автоожиданием сети, это несколько минут). Честно скажи "
    "пользователю, что браузер ставится, и предложи повторить позже. "
    "Не выдумывай результаты поиска.")


def ensure_ready_bg(report=None):
    """Проактивная проверка при старте сервера: пакет есть, а бинарника
    нет — сразу докачиваем в фоне, не дожидаясь первой просьбы."""
    if not available() or not _chromium_present():
        _install_bg(report)


def _net_ok() -> bool:
    import socket as s
    try:
        s.create_connection(("duckduckgo.com", 443), timeout=5).close()
        return True
    except OSError:
        return False


def _wait_net():
    """Сеть рвётся (перезапуск VPN и т.п.) — не падаем, а ждём её возврата."""
    if _net_ok():
        return
    log.info("Сети нет — жду её возвращения (VPN перезапускается?)…")
    while not _net_ok():
        time.sleep(10)
    log.info("Сеть вернулась — продолжаю")
    time.sleep(3)   # дать VPN устаканиться, чтобы не сорваться на 1%


def _install_bg(report=None):
    """Playwright + Chromium (~150 МБ) в фоне. Устойчиво к обрывам сети:
    сорвалась загрузка — ждём сеть и пробуем снова, до победного."""
    if STATE["installing"]:
        return
    STATE["installing"] = True

    def run():
        attempt = 0
        try:
            while True:
                attempt += 1
                _wait_net()
                try:
                    try:
                        import playwright  # noqa: F401
                    except ImportError:
                        log.info("Ставлю пакет playwright…")
                        subprocess.run(
                            [sys.executable, "-m", "pip", "install",
                             "playwright", "--timeout", "120",
                             "--retries", "10"], check=True)
                    log.info("Качаю Chromium (попытка %s)…", attempt)
                    subprocess.run([sys.executable, "-m", "playwright",
                                    "install", "chromium"], check=True)
                    log.info("Браузер готов (с попытки %s)", attempt)
                    if report:
                        report("browser", "",
                               "видимый браузер установлен и готов")
                    return
                except Exception as e:
                    log.warning("Загрузка браузера сорвалась (попытка %s): "
                                "%s — жду сеть и повторяю", attempt, e)
                    if report and attempt == 1:
                        report("browser", "загрузка рвётся вместе с сетью",
                               "не падаю: жду сеть и докачиваю сама, "
                               "попыток не ограничено")
                    time.sleep(15)
        finally:
            STATE["installing"] = False

    threading.Thread(target=run, daemon=True).start()


# ---------------- поток-владелец Playwright ----------------
def _thread_main():
    from playwright.sync_api import sync_playwright
    ctx = {"pw": None, "browser": None, "ctx": None, "page": None}
    while True:
        fn, done, holder = _jobs.get()
        try:
            holder["result"] = fn(ctx)
        except Exception as e:
            holder["error"] = e
        done.set()


def _post(fn, timeout=90):
    global _thread
    with _lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_thread_main, daemon=True,
                                       name="browser-hands")
            _thread.start()
    done = threading.Event()
    holder = {}
    _jobs.put((fn, done, holder))
    if not done.wait(timeout):
        raise TimeoutError("браузер не ответил за %sс" % timeout)
    if "error" in holder:
        raise holder["error"]
    return holder.get("result")


def _ublock_dir():
    """Папка распакованного uBlock Origin (setup/install_ublock.py).
    Нет — работаем без него, просто с баннерами."""
    from pathlib import Path
    d = Path(__file__).resolve().parent.parent / "third_party" / "ublock"
    return str(d) if (d / "manifest.json").exists() else None


def _profile_dir():
    """Расширения Playwright умеет ТОЛЬКО в persistent-контексте, а тому
    нужен профиль на диске. Заодно переживают куки и «согласия» — меньше
    стен на каждой второй странице."""
    from pathlib import Path
    d = Path(__file__).resolve().parent.parent / "data" / "browser_profile"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def _reset_ctx(ctx):
    for key in ("ctx", "browser"):
        try:
            if ctx.get(key):
                ctx[key].close()
        except Exception:
            pass
    ctx["ctx"] = None
    ctx["browser"] = None
    ctx["page"] = None


def _ensure_page(ctx):
    from playwright.sync_api import sync_playwright
    if ctx["pw"] is None:
        ctx["pw"] = sync_playwright().start()
    # живость проверяем ДЕЛОМ, а не флагами: пользователь мог закрыть окно
    # крестиком — is_connected()/is_closed() при этом иногда врут, и все
    # вызовы валятся TargetClosedError по кругу
    if ctx["page"] is not None:
        try:
            ctx["page"].evaluate("1")
        except Exception:
            _reset_ctx(ctx)
    alive = ctx.get("ctx") is not None
    if alive and ctx.get("browser") is not None:
        alive = ctx["browser"].is_connected()
    if not alive:
        _reset_ctx(ctx)
        args = ["--window-size=1200,800", "--lang=ru-RU"]
        ext = _ublock_dir()
        if ext:
            # РЕЖЕМ БАННЕРЫ ЧУЖИМИ РУКАМИ (2026-08-13). Баннеры, куки-стены
            # и окна подписки — гонка вооружений, которую годами ведут
            # другие люди. Свой close_ad остаётся страховкой на то, что
            # uBlock пропустит, но основную работу делает он.
            args += [f"--disable-extensions-except={ext}",
                     f"--load-extension={ext}"]
            try:
                ctx["ctx"] = ctx["pw"].chromium.launch_persistent_context(
                    _profile_dir(), headless=False, args=args, locale="ru-RU",
                    viewport={"width": 1180, "height": 760})
                ctx["browser"] = None
                log.info("браузер: uBlock Origin подключён")
            except Exception as e:
                log.warning("uBlock не подключился (%s) — иду без него", e)
                ext = None
        if not ext:
            ctx["browser"] = ctx["pw"].chromium.launch(
                headless=False, args=["--window-size=1200,800",
                                      "--lang=ru-RU"])
            ctx["ctx"] = ctx["browser"].new_context(
                viewport={"width": 1180, "height": 760}, locale="ru-RU")
    if ctx["page"] is None or ctx["page"].is_closed():
        pages = [pg for pg in ctx["ctx"].pages if not pg.is_closed()]
        ctx["page"] = pages[0] if pages else ctx["ctx"].new_page()
    try:
        ctx["page"].bring_to_front()
    except Exception:
        pass
    return ctx["page"]


def _page_text(page, cap):
    try:
        text = page.evaluate("() => document.body ? document.body.innerText : ''")
        text = " ".join(text.split())
        return text[:cap] + ("…" if len(text) > cap else "")
    except Exception as e:
        return f"(текст не прочитался: {e})"


def _mark_used():
    STATE["open"] = True
    STATE["last_used"] = time.time()
    STATE["used_in_dialog"] = True


# ---------------- публичные операции ----------------
def _launch_failed(e: Exception) -> bool:
    s = str(e)
    return "Executable doesn't exist" in s or "playwright install" in s


# Универсальный сборщик результатов: не завязан на конкретные data-testid
# (русская/новая вёрстка DDG их меняет — на этом и сломался первый вариант)
_JS_RESULTS = """
() => {
  const seen = new Set(); const out = [];
  const arts = document.querySelectorAll('article, [data-testid=result], .result');
  for (const a of arts) {
    const h = a.querySelector('h2, .result__a');
    let link = a.querySelector('a[data-testid=result-title-a]')
            || (h && (h.closest('a') || h.querySelector('a')))
            || a.querySelector('a[href^="http"]');
    if (!h || !link) continue;
    const url = link.href || '';
    if (!url.startsWith('http') || url.includes('duckduckgo.com/y.js') ||
        seen.has(url)) continue;
    seen.add(url);
    const sn = a.querySelector('[data-result=snippet], .result__snippet');
    out.push({title: h.innerText.trim(), url,
              snippet: sn ? sn.innerText.trim().slice(0, 250) : ''});
    if (out.length >= 8) break;
  }
  return out;
}"""


def _ddgs_results(query, n=12):
    """Выдача через библиотеку ddgs — без разбора вёрстки.

    Свой парсер DDG ломался при каждом редизайне («выдача не распарсилась» —
    живая жалоба), да и отдавал 5-8 ссылок. Здесь их десятки и мгновенно.
    Видимое окно всё равно набирает запрос руками — это театр ДЛЯ ЧЕЛОВЕКА,
    чтобы он видел, что она ищет; но данные берём отсюда."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS      # старое имя пакета
        except ImportError:
            return []
    try:
        with DDGS() as d:
            rows = list(d.text(query, region="ru-ru", max_results=n))
        return [{"title": r.get("title") or "",
                 "url": r.get("href") or r.get("url") or "",
                 "snippet": (r.get("body") or "")[:200]}
                for r in rows if (r.get("href") or r.get("url"))]
    except Exception as e:
        log.info("ddgs не ответила (%s) — беру выдачу из окна", e)
        return []


def _do_search(ctx, query):
    """Видимый поиск -> список {title,url,snippet}. Данные берём из ddgs,
    вёрстку окна разбираем только как запаску."""
    from urllib.parse import quote
    page = _ensure_page(ctx)
    try:
        page.goto(SEARCH_URL, wait_until="domcontentloaded")
    except Exception:
        # окно убили под нами (закрыл пользователь) — пересоздаём и ещё раз
        _reset_ctx(ctx)
        page = _ensure_page(ctx)
        page.goto(SEARCH_URL, wait_until="domcontentloaded")
    box = page.locator("#searchbox_input, input[name=q]").first
    box.click()
    # ЧИСТИМ СТРОКУ ПЕРЕД НАБОРОМ (2026-08-13, просьба владельца: «удаляет в
    # строке поиска всё и пишет то, что я попрошу найти»). На странице выдачи
    # в поле лежит ПРОШЛЫЙ запрос, и набор поверх него давал склейку двух тем.
    try:
        box.fill("")
    except Exception:
        pass
    box.press_sequentially(query, delay=35)   # набор по-человечески
    box.press("Enter")
    try:
        page.wait_for_selector("article, [data-testid=result], .result",
                               timeout=12000)
    except Exception:
        pass
    page.wait_for_timeout(600)
    items = _ddgs_results(query) or page.evaluate(_JS_RESULTS) or []
    if not items:
        # запасная статичная выдача (тоже в видимом окне)
        page.goto("https://duckduckgo.com/html/?q=" + quote(query),
                  wait_until="domcontentloaded")
        page.wait_for_timeout(400)
        items = page.evaluate(_JS_RESULTS) or []
    return items


# ═══════════════════════════════════════════════════════════════════
# СБОРКА ЗАПРОСА (2026-08-13, живой позор: в поисковую строку уехало
# «Ну, поищи саму игру.» — реплика человека целиком. Тема «Stellar Blade»
# прозвучала ходом раньше и никуда не перенеслась, поэтому нашлись Яндекс
# Игры и японский блог 2017 года.)
#
# Человек НЕ формулирует поисковый запрос. Он говорит «поищи саму игру»,
# имея в виду то, о чём шла речь минуту назад. Значит запрос надо СОБИРАТЬ:
# снять командную обвязку, а если после неё осталась одна пустая ссылка
# («саму игру», «его», «это») — достать предмет из недавнего разговора.
# ═══════════════════════════════════════════════════════════════════

# командная обвязка: ею человек обращается к Сайке, а не к поисковику
_CMD_WORDS = (
    r"ну|а|и|так|вот|давай|давайка|плиз|пожалуйста|слушай|слышь|сайка|"
    r"поищ\w*|найд\w*|ищи|искать|погугл\w*|загугл\w*|посмотр\w*|глян\w*|"
    r"узна\w*|провер\w*|расскаж\w*|покаж\w*|что\s+знаешь|что\s+ты\s+знаешь|"
    r"инфу|информаци\w*|подробн\w*|поподробнее|ещё|еще|там|же|-?ка|"
    r"сам|сама|саму|само|самого|саму\w*|конкретн\w*|именно|про|об|о"
)
# ГРАНИЦЫ ОБЯЗАТЕЛЬНЫ. Без них односимвольные «а», «о», «и» из списка
# отгрызают последнюю букву у нормальных слов: «босса» -> «босс»,
# «вышло» -> «вышл». Ищем целые слова, а не куски.
_CMD_RE = re.compile(r"^(?:\s*(?:%s)(?![\wа-яёА-ЯЁ])[\s,]*)+" % _CMD_WORDS,
                     re.I)
_TAIL_RE = re.compile(
    r"(?:^|(?<=[\s,]))(?:%s)(?![\wа-яёА-ЯЁ])\s*[.!?]*$" % _CMD_WORDS, re.I)

# слова-пустышки: сами по себе предмета не задают, это ссылка на прошлое
_HOLLOW = {
    "игру", "игра", "игры", "игре", "фильм", "фильма", "фильме", "песню",
    "песня", "книгу", "книга", "сериал", "сериала", "видео", "ролик",
    "это", "этого", "эту", "этот", "эта", "его", "её", "ее", "их", "он",
    "она", "оно", "они", "там", "тут", "туда", "штуку", "вещь", "тему",
    "статью", "сайт", "страницу", "человека", "модель", "программу",
}

_STOP_TOPIC = {"что", "как", "где", "когда", "почему", "зачем", "кто",
               "какой", "какая", "какие", "ты", "мне", "мы", "вы", "нам"}

# вопросительная обвязка: «что нового», «когда выйдет» — это НЕ предмет, а
# уточнение к нему. Без предмета из разговора такой запрос бесполезен.
_ASKING = {"что", "чего", "когда", "где", "сколько", "какой", "какая",
           "какие", "почему", "зачем", "кто", "нового", "новое", "там"}


def _topic_from_history() -> str:
    """Предмет разговора из недавних фраз. Ищем имя собственное: слова с
    заглавной НЕ в начале предложения или латиницу — «Стеллар Блейд»,
    «Stellar Blade», «Blender». Берём последнее упомянутое: разговор
    движется вперёд, и свежее вернее."""
    try:
        from server.llm import tools as _t
        phrases = list(_t.LAST_USER.get("recent") or [])
        if _t.LAST_USER.get("text"):
            phrases.append(_t.LAST_USER["text"])
    except Exception:
        return ""
    best = ""
    for ph in phrases:
        for sent in re.split(r"[.!?]+", ph or ""):
            words = sent.split()
            for i, w in enumerate(words):
                cw = w.strip("«»\"'(),:;-")
                if len(cw) < 3 or cw.lower() in _STOP_TOPIC:
                    continue
                # заглавная не в начале предложения, либо латиница
                cap = cw[:1].isupper() and i > 0
                lat = bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9\-]{2,}", cw))
                if not (cap or lat):
                    continue
                run = [cw]
                for nxt in words[i + 1:i + 3]:
                    cn = nxt.strip("«»\"'(),:;-")
                    if cn[:1].isupper() or re.fullmatch(
                            r"[A-Za-z][A-Za-z0-9\-]{2,}", cn):
                        run.append(cn)
                    else:
                        break
                cand = " ".join(run)
                if len(cand) > len(best):
                    best = cand
    return best


def smart_query(raw: str) -> str:
    """Собрать поисковый запрос из реплики. Возвращает то, что не стыдно
    напечатать в строку поиска."""
    q = " ".join(str(raw or "").split())
    if not q:
        return ""
    core = _TAIL_RE.sub("", _CMD_RE.sub("", q)).strip(" ,.!?-")
    words = [w for w in re.split(r"[\s,]+", core) if w]
    meaty = [w for w in words if w.lower().strip(".,!?") not in _HOLLOW]
    # осталась одна пустая ссылка («саму игру») или вообще ничего —
    # предмет живёт в разговоре, а не в этой фразе
    if len(meaty) < 1 or (len(meaty) == 1 and len(meaty[0]) < 4):
        topic = _topic_from_history()
        if topic:
            kind = next((w for w in words
                         if w.lower().strip(".,!?") in _HOLLOW), "")
            built = (topic + " " + kind).strip() if kind else topic
            log.info("Запрос собран из разговора: %r -> %r", q, built)
            return _clean_query(built)
    if not core:
        return _clean_query(q)
    # предмет из истории добавляем и когда фраза осмысленная, но КОРОТКАЯ
    # («что нового», «когда выйдет») — без него это не запрос, а обрывок
    if len(meaty) < 3 or all(
            w.lower().strip(".,!?") in _ASKING for w in meaty):
        topic = _topic_from_history()
        if topic and topic.lower() not in core.lower():
            core = topic + " " + core
            log.info("Запрос дополнен темой разговора: %r", core)
    return _clean_query(core)


def _clean_query(q: str) -> str:
    """Модели иногда суют в query простыню (кусок страницы, весь диалог) —
    печатать её в поисковую строку 10 секунд и бессмысленно, и смешно.
    Схлопываем пробелы и режем до вменяемой длины по границе слова.
    Плюс фильтр ЭХО-ЗАПРОСОВ: мелкие модели гуглят буквально служебные
    тексты из контекста («внутренний импульс…», «Тишина уже ~18 мин…») —
    такое не поиск, а попугайство, отбиваем с объяснением."""
    import re as _re
    q = " ".join(str(q).split())
    if _re.search(r"внутренний импульс|тишина уже|спроси легко|служебн|"
                  r"пользователь просит|этого не писал|твоя собственная",
                  q, _re.I):
        return ""
    if len(q) > 120:
        q = q[:120].rsplit(" ", 1)[0]
    return q


def search(query: str) -> str:
    query = _clean_query(query)
    if not query:
        return ("это не поисковый запрос (пусто или служебный текст из "
                "контекста). Если реально нужно искать — сформулируй "
                "короткую тему поиска сама; если нет — просто ответь "
                "словами, без инструментов")
    if not available() or not _chromium_present():
        _install_bg()
        return INSTALLING_MSG

    def job(ctx):
        items = _do_search(ctx, query)
        if not items:
            return ("Выдача не распарсилась (капча/новая вёрстка). Видимый "
                    "текст страницы: " + _page_text(ctx["page"], 1200))
        out = [f"{i+1}. {r['title']}\n   {r['url']}\n   {r['snippet']}"
               for i, r in enumerate(items[:6])]
        # ГЛУБЖЕ ПЕРВОЙ СТРАНИЦЫ (2026-07-23): модели останавливались на
        # сниппетах выдачи и отвечали поверхностно. Теперь web_search сам
        # приносит выжимки двух верхних страниц (параллельный HTTP, ~1-2с) —
        # даже «ленивая» модель отвечает по содержимому, а не по заголовкам.
        try:
            from concurrent.futures import ThreadPoolExecutor
            top = [r for r in items[:3]
                   if not any(b in r["url"].lower()
                              for b in ("youtube.com", "youtu.be", ".pdf"))][:2]
            if top:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futs = {pool.submit(_http_fetch, r["url"], 900): r
                            for r in top}
                    ext = []
                    for fut, r in futs.items():
                        try:
                            t = fut.result(timeout=6)
                            if t and len(t) > 150:
                                ext.append(f"— выжимка «{r['title']}»: {t}")
                        except Exception:
                            pass
                if ext:
                    out.append("\nПрочитала верхние страницы:\n"
                               + "\n".join(ext))
        except Exception as e:
            log.info("web_search: выжимки не получились (%s)", e)
        return ("Нашла (окно браузера открыто, могу открыть любой пункт "
                "через open_page; для глубокой сводки есть web_research):\n"
                + "\n".join(out))

    try:
        result = _post(job)
    except Exception as e:
        if _launch_failed(e):
            _install_bg()
            return INSTALLING_MSG
        raise
    _mark_used()
    return result


def open_url(url: str) -> str:
    if not available() or not _chromium_present():
        _install_bg()
        return INSTALLING_MSG
    # 2026-07-23: было `if not url.startswith("http"): url = "https://"+url` —
    # рассчитано на голое «ютуб.com» из голоса, но калечило УЖЕ полные URI с
    # другой схемой: workshop_create отдавал file:///C:/AI/Saika/workshop/x.svg
    # (Path.as_uri()), и это превращалось в «https://file:///C:/...» — Chrome
    # читал «file» как ИМЯ ХОСТА и падал с ERR_NAME_NOT_RESOLVED (реальный
    # инцидент: картинка от Kimi не открылась, хотя файл создался нормально).
    # Теперь трогаем только то, что вообще без схемы — есть двоеточие-схема
    # (http/https/file/data/…) — оставляем как есть.
    if not re.match(r"^[a-z][a-z0-9+.\-]*://", url, re.I):
        url = "https://" + url

    def job(ctx):
        page = _ensure_page(ctx)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(700)
        # ЗАМЕЧАЕТ САМА (2026-08-13): если поверх страницы висит баннер —
        # это факт о происходящем, и она должна его ВИДЕТЬ, а не узнавать
        # только когда попросят. Реакцию не подсказываем: отдаём голый факт,
        # словами распорядится её характер.
        note = ""
        try:
            ov = _overlays(page)
            if ov:
                big = max(o.get("area", 0) for o in ov)
                note = (f"\n\n(поверх страницы висит баннер/модалка, "
                        f"закрывает ~{big}% экрана — можешь убрать его "
                        f"инструментом close_ad)")
        except Exception:
            pass
        return f"[{page.title()}] {url}\n\n" + _page_text(page, 4000) + note

    try:
        result = _post(job)
    except Exception as e:
        if _launch_failed(e):
            _install_bg()
            return INSTALLING_MSG
        raise
    _mark_used()
    return result


def _http_fetch(url: str, cap: int = 2800) -> str:
    """Быстрое фоновое чтение страницы обычным HTTP (без браузера).
    Так «читается куча сайтов одновременно»: сеть — не GPU, параллельные
    запросы почти бесплатны. Текст выдирается стандартным html.parser."""
    import requests as rq
    from html.parser import HTMLParser

    class _Text(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts, self.skip = [], 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "noscript", "svg"):
                self.skip += 1

        def handle_endtag(self, tag):
            if tag in ("script", "style", "noscript", "svg") and self.skip:
                self.skip -= 1

        def handle_data(self, data):
            if not self.skip:
                self.parts.append(data)

    r = rq.get(url, timeout=12, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/126.0 Safari/537.36"),
        "Accept-Language": "ru,en;q=0.8"})
    r.raise_for_status()
    # ЧИТАЕМ СТАТЬЮ, А НЕ СТРАНИЦУ (2026-08-13). html.parser ниже тащит в
    # сводку меню, футер, «читайте также» и текст баннеров — модель потом
    # честно пересказывает этот мусор. trafilatura выдирает основной текст
    # и, что важнее, ДАТУ ПУБЛИКАЦИИ: без неё Сайка выдавала прошлогоднюю
    # статью за свежую новость (живой случай с патчем Genshin).
    try:
        import trafilatura
        got = trafilatura.extract(
            r.text, url=url, favor_precision=True,
            include_comments=False, include_tables=True,
            with_metadata=True, output_format="json")
        if got:
            import json as _j
            d = _j.loads(got)
            body = " ".join((d.get("text") or "").split())
            if len(body) > 200:
                head = ""
                when = d.get("date") or ""
                if when:
                    head = f"(дата публикации: {when}) "
                ttl = (d.get("title") or "").strip()
                if ttl:
                    head = f"{ttl} {head}"
                return (head + body)[:cap]
    except ImportError:
        pass
    except Exception as e:
        log.debug("trafilatura не справилась с %s: %s", url, e)
    p = _Text()
    p.feed(r.text)
    text = " ".join(" ".join(p.parts).split())
    return text[:cap]


# ═══════════════════════════════════════════════════════════════════
# «ПОКАЖИ, ГДЕ ТЫ ЭТО ВЗЯЛА» (2026-08-13, просьба владельца: «чтобы она
# скролила на нужное место для меня, чтобы я прочитать тоже мог»)
#
# Своя прокрутка тут не нужна вообще: Chrome нативно понимает Text
# Fragments — адрес вида  страница#:~:text=начало,конец  открывается СРАЗУ
# на нужном абзаце и подсвечивает его жёлтым. Ноль кода, ноль зависимостей,
# работает на любом сайте. Мы лишь выбираем, какой кусок показать.
# ═══════════════════════════════════════════════════════════════════

def _fragment_url(url: str, quote: str) -> str:
    from urllib.parse import quote as q
    words = (quote or "").split()
    if len(words) < 4:
        return url
    start = " ".join(words[:6])
    end = " ".join(words[-4:])
    base = url.split("#")[0]
    return f"{base}#:~:text={q(start)},{q(end)}"


def _best_passage(text: str, query: str) -> str:
    """Кусок текста, теснее всего связанный с вопросом. Без эмбеддингов:
    пересечение слов работает достаточно и стоит ноль."""
    import re as _re
    keys = {w.lower() for w in _re.findall(r"\w{4,}", query or "")}
    if not keys:
        return ""
    best, score = "", 0
    parts = _re.split(r"(?<=[.!?])\s+", text or "")
    for i, sent in enumerate(parts):
        chunk = " ".join(parts[i:i + 2]).strip()
        if not 60 <= len(chunk) <= 400:
            continue
        low = chunk.lower()
        hit = sum(1 for k in keys if k in low)
        if hit > score:
            best, score = chunk, hit
    return best if score >= 2 else ""


def show_passage(url: str, quote: str) -> str:
    """Открыть страницу СРАЗУ на нужном месте и подсветить его."""
    if not url:
        return "нечего показывать — нет адреса"
    target = _fragment_url(url, quote)
    out = open_url(target)
    if target != url:
        return ("Открыла страницу на нужном абзаце и подсветила его — "
                "человек видит это место у себя на экране.\n\n" + out)
    return out


def research(query: str) -> str:
    """Умный поиск: искать -> ОТКРЫТЬ и ПРОЧИТАТЬ топ-страницы (видимо,
    в том же окне) -> собрать структурированную сводку с источниками.
    Суммаризацию делает LLM отдельным сфокусированным запросом, поэтому
    качество сводки не зависит от размера болтающей модели."""
    query = smart_query(query)
    if not query:
        return "пустой запрос — сформулируй, что искать"
    if not available() or not _chromium_present():
        _install_bg()
        return INSTALLING_MSG

    def sjob(ctx):
        return _do_search(ctx, query)

    try:
        items = _post(sjob, timeout=60)
    except Exception as e:
        if _launch_failed(e):
            _install_bg()
            return INSTALLING_MSG
        raise
    _mark_used()
    if not items:
        return "Выдача не распарсилась — попробуй web_search или другой запрос."

    skip = ("youtube.com", "youtu.be", ".pdf", "vk.com/video")
    # ДЕСЯТКИ САЙТОВ, А НЕ ШЕСТЬ (2026-08-13): сеть не GPU, параллельные
    # запросы почти бесплатны, а качество сводки упирается именно в число
    # прочитанных источников
    cands = [r for r in items if not any(b in r["url"].lower()
                                         for b in skip)][:12]

    # ПАРАЛЛЕЛЬНОЕ чтение: все страницы качаются одновременно обычным HTTP
    # (пара секунд на всё), а видимое окно тем временем открывает первый
    # результат — «театр» для пользователя без потери скорости
    from concurrent.futures import ThreadPoolExecutor
    pages = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_http_fetch, r["url"]): r for r in cands}
        if cands:
            def show(ctx, u=cands[0]["url"]):
                page = _ensure_page(ctx)
                page.goto(u, wait_until="domcontentloaded", timeout=20000)
                return True
            try:
                _post(show, timeout=30)
            except Exception:
                pass
        for fut, r in futures.items():
            try:
                text = fut.result(timeout=15)
                if text and len(text) > 200:
                    pages.append((r, text))
            except Exception as e:
                log.info("research: %s не скачалась (%s)", r["url"], e)
    pages = pages[:8]   # 3 -> 5 (2026-07-23) -> 8 (2026-08-13)

    # если параллельный HTTP ничего не принёс (капчи/JS-сайты) — читаем
    # первую страницу медленно, но честно, через видимый браузер
    if not pages and cands:
        def pjob(ctx, u=cands[0]["url"]):
            page = _ensure_page(ctx)
            page.goto(u, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(600)
            return _page_text(page, 2800)
        try:
            text = _post(pjob, timeout=45)
            if text and len(text) > 200:
                pages.append((cands[0], text))
        except Exception as e:
            log.info("research: браузерное чтение не удалось (%s)", e)
    _mark_used()

    if not pages:
        # хотя бы выдача есть — вернём её
        return ("Страницы не открылись, но вот выдача:\n" + "\n".join(
            f"{i+1}. {r['title']} — {r['url']}" for i, r in enumerate(items[:5])))

    materials = "\n\n".join(
        f"[{i+1}] {r['title']} ({r['url']}):\n{text}"
        for i, (r, text) in enumerate(pages))
    sources = "\n".join(f"[{i+1}] {r['url']}" for i, (r, _) in enumerate(pages))
    try:
        from server.llm import manager as llm
        digest = llm.chat_once([
            {"role": "system", "content":
             "Ты — исследовательский модуль. Составь СЖАТУЮ структурированную "
             "сводку по вопросу пользователя строго из предоставленных "
             "материалов. Только факты из текстов, без выдумок; помечай "
             "факты номерами источников [1][2]. 6-10 коротких строк, без "
             "воды. Пиши на русском.\n"
             "ДАТЫ (2026-08-13): у части материалов первой строкой указана "
             "дата публикации. Свежее — важнее: если источники противоречат, "
             "верь новому и скажи об этом. Слух, анонс и уже вышедшее — РАЗНЫЕ "
             "вещи, не смешивай их в одну строку.\n"
             "ЕСЛИ ОТВЕТА В МАТЕРИАЛАХ НЕТ — так и напиши одной строкой. "
             "Пересказ общих ожиданий вместо фактов — это враньё, а не "
             "сводка."},
            {"role": "user", "content":
             f"Вопрос: {query}\n\nМатериалы:\n{materials[:12000]}"}])
    except Exception as e:
        log.warning("research: сводка не удалась (%s)", e)
        return ("Собрала тексты, но сводка не удалась — вот сырьё:\n"
                + materials[:2500] + "\n\nИсточники:\n" + sources)
    # ПОКАЗАТЬ ГЛАЗАМИ, А НЕ ТОЛЬКО ПЕРЕСКАЗАТЬ: открываем лучший источник
    # ровно на том абзаце, откуда взят ответ, и подсвечиваем его.
    shown = ""
    try:
        top_r, top_t = pages[0]
        passage = _best_passage(top_t, query)
        if passage:
            _post(lambda c, u=_fragment_url(top_r["url"], passage): (
                _ensure_page(c).goto(u, wait_until="domcontentloaded",
                                     timeout=25000)), timeout=35)
            shown = ("\n\n(открыла источник [1] прямо на нужном абзаце и "
                     "подсветила его — человек видит это место на экране)")
    except Exception as e:
        log.debug("подсветка фрагмента не удалась: %s", e)
    return (f"Изучила {len(pages)} страниц по запросу «{query}».\n\n{digest}"
            f"\n\nИсточники:\n{sources}{shown}")


# ═══════════════════════════════════════════════════════════════════
# ВЫДАЧА СПИСКОМ + ПРОКРУТКА (2026-08-13, просьба владельца)
#
# Замысел: «напиши в поиск X» -> она чистит строку, набирает запрос, и
# НЕ ПЕРЕСКАЗЫВАЕТ выдачу голосом, а показывает её в чате пронумерованным
# списком. Человек говорит «открой второй» — она открывает. Раньше любой
# поиск заканчивался тем, что модель зачитывала вслух заголовки, а выбрать
# из них было нечем: номеров не существовало, ссылки жили только в тексте
# инструмента, которого человек вообще не видит.
# ═══════════════════════════════════════════════════════════════════

LAST_RESULTS: list = []


def _remember(items):
    LAST_RESULTS.clear()
    LAST_RESULTS.extend(items[:8])


def _push_links(query, items):
    """Отправить нумерованный список в чат отдельным событием. Именно
    событием, а не текстом ответа: текст ответа уходит в озвучку, а список
    ссылок читать вслух незачем."""
    try:
        from server.main import broadcast_event
        broadcast_event({"type": "links", "query": query, "items": [
            {"n": i + 1, "title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": (r.get("snippet") or "")[:180]}
            for i, r in enumerate(items[:8])]})
    except Exception as e:
        log.debug("список ссылок не ушёл в UI: %s", e)


def search_list(query: str) -> str:
    """Поиск с показом выдачи списком в чате. Модели возвращаем НЕ содержимое
    списка, а инструкцию: человек уже всё видит, перечислять вслух не надо."""
    query = smart_query(query)
    if not query:
        return "пустой запрос — скажи, что искать"
    if not available() or not _chromium_present():
        _install_bg()
        return INSTALLING_MSG

    def job(ctx):
        return _do_search(ctx, query)

    try:
        items = _post(job, timeout=60)
    except Exception as e:
        if _launch_failed(e):
            _install_bg()
            return INSTALLING_MSG
        raise
    _mark_used()
    if not items:
        return ("выдача не распарсилась (капча или новая вёрстка) — "
                "скажи человеку честно и предложи другой запрос")
    _remember(items)
    _push_links(query, items)
    return (f"Готово: набрала «{query}», нашла {len(LAST_RESULTS)} ссылок — "
            "СПИСОК УЖЕ ПОКАЗАН человеку в чате, с номерами. "
            "НЕ перечисляй их вслух и не пересказывай заголовки. "
            "Скажи одной живой фразой, что список перед ним и можно назвать "
            "номер, — а дальше зови open_result с этим номером.")


def open_result(n) -> str:
    """Открыть N-й пункт последней выдачи («открой второй»)."""
    try:
        n = int(str(n).strip())
    except Exception:
        return "нужен номер пункта из списка (например 2)"
    if not LAST_RESULTS:
        return ("списка ещё нет — сначала поищи (web_list), потом можно "
                "открывать по номеру")
    if not 1 <= n <= len(LAST_RESULTS):
        return (f"в списке {len(LAST_RESULTS)} пунктов, номера {n} там нет — "
                "скажи это человеку, не выдумывай страницу")
    r = LAST_RESULTS[n - 1]
    return f"Открываю пункт {n} — {r.get('title','')}\n\n" + open_url(r["url"])


_SCROLL_UP = ("up", "вверх", "верх", "назад", "выше")
_SCROLL_TOP = ("top", "начало", "наверх", "самый верх", "в начало")
_SCROLL_END = ("bottom", "end", "конец", "низ", "в конец", "самый низ")


def scroll(direction: str = "down", amount=1) -> str:
    """Прокрутка видимой страницы. Экран за раз — то же движение, что делает
    человек колесом: модель читает страницу кусками, а не глотает целиком."""
    if not available() or not _chromium_present():
        return "браузер ещё не готов"
    d = str(direction or "down").strip().lower()
    try:
        steps = max(1, min(int(float(str(amount).replace(",", "."))), 10))
    except Exception:
        steps = 1

    def job(ctx):
        page = _ensure_page(ctx)
        if d in _SCROLL_TOP:
            page.evaluate("window.scrollTo({top:0,behavior:'smooth'})")
            where = "в самое начало"
        elif d in _SCROLL_END:
            page.evaluate(
                "window.scrollTo({top:document.body.scrollHeight,"
                "behavior:'smooth'})")
            where = "в самый низ"
        else:
            sign = -1 if d in _SCROLL_UP else 1
            for _ in range(steps):
                page.mouse.wheel(0, sign * 700)
                page.wait_for_timeout(120)
            where = ("вверх" if sign < 0 else "вниз") + f" на {steps} экрана"
        page.wait_for_timeout(400)
        # отдаём КУСОК, который теперь на экране: иначе прокрутка бессмысленна —
        # модель не увидит того, ради чего листала
        seen = page.evaluate(
            "() => {const y=window.scrollY,h=window.innerHeight;"
            "return [...document.body.querySelectorAll('p,li,h1,h2,h3,td')]"
            ".filter(e=>{const r=e.getBoundingClientRect();"
            "return r.top<h && r.bottom>0;})"
            ".map(e=>e.innerText.trim()).filter(Boolean).join(' ').slice(0,2500);}")
        pos = page.evaluate(
            "() => Math.round(100*(window.scrollY+window.innerHeight)/"
            "Math.max(1,document.body.scrollHeight))")
        return where, (seen or "").strip(), pos

    try:
        where, seen, pos = _post(job, timeout=45)
    except Exception as e:
        return f"прокрутить не вышло: {e}"
    _mark_used()
    if not seen:
        return f"Пролистала {where} ({pos}% страницы), текста на экране нет."
    return (f"Пролистала {where} — сейчас видно {pos}% страницы:\n\n{seen}")


# ═══════════════════════════════════════════════════════════════════
# ПОИСК ВНУТРИ САЙТА + БАННЕРЫ (2026-08-13, живой отказ)
#
# Владелец: «попросил вписать — она поставила курсор в поисковую строку и
# ничего не смогла сделать». Так и было: web_list умеет ТОЛЬКО DuckDuckGo,
# а он просил набрать в строке ОТКРЫТОГО сайта (YouTube, AppleInsider).
# Разные вещи: искать в интернете и искать ВНУТРИ сайта.
#
# Про «удалять инфу из строки» — да, всегда. Человек говорит «впиши X», а
# не «допиши X к тому, что там лежит». Чистим молча, это единственное
# разумное прочтение просьбы.
# ═══════════════════════════════════════════════════════════════════

_SEARCH_SEL = ", ".join([
    "input#search", "input[type=search]", "input[name=q]",
    "input[name=search]", "input[name=query]", "input[name=text]",
    "input[name=s]", "[role=searchbox]", "[role=combobox][type=text]",
    "input[placeholder*='оиск' i]", "input[placeholder*='earch' i]",
    "input[aria-label*='оиск' i]", "input[aria-label*='earch' i]",
])

# кнопка-лупа: на половине сайтов строка спрятана, пока не ткнёшь
_SEARCH_TOGGLE_SEL = ", ".join([
    "button[aria-label*='оиск' i]", "button[aria-label*='earch' i]",
    "a[aria-label*='оиск' i]", "[class*='search-toggle']",
    "[class*='search-button']", "[class*='searchIcon']",
])

# ЗАКРЫТЬ БАННЕР. Ищем не «рекламу» (её никак формально не опознать), а
# ПЕРЕКРЫТИЕ: фиксированный блок поверх страницы, занимающий заметную долю
# экрана и лежащий выше всего по z-index. Именно оно мешает и читать, и
# кликать — неважно, реклама это, подписка или куки.
_JS_OVERLAYS = """
() => {
  const vw = innerWidth, vh = innerHeight, found = [];
  const all = document.querySelectorAll('div,section,aside,ins,iframe,dialog');
  for (const el of all) {
    let cs; try { cs = getComputedStyle(el); } catch (e) { continue; }
    if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    if (parseFloat(cs.opacity || '1') < 0.1) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 80 || r.height < 60) continue;
    if (r.width * r.height < vw * vh * 0.12) continue;
    const z = parseInt(cs.zIndex) || 0;
    if (z < 50) continue;
    const txt = (el.innerText || '').trim().slice(0, 80);
    found.push({ z: z, area: Math.round(100 * r.width * r.height / (vw * vh)),
                 tag: el.tagName.toLowerCase(), text: txt });
  }
  return found.sort((a, b) => b.z - a.z).slice(0, 4);
}
"""

_JS_CLOSE_OVERLAY = """
() => {
  const vw = innerWidth, vh = innerHeight;
  const words = ['закрыть', 'close', 'скрыть', 'нет спасибо', 'no thanks',
                 'принять', 'accept', 'понятно', 'ok', 'хорошо'];
  const all = [...document.querySelectorAll('div,section,aside,ins,dialog')];
  let killed = 0, how = '';
  for (const el of all) {
    let cs; try { cs = getComputedStyle(el); } catch (e) { continue; }
    if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width * r.height < vw * vh * 0.12) continue;
    if ((parseInt(cs.zIndex) || 0) < 50) continue;
    const btns = [...el.querySelectorAll('button,a,span,div,svg,i')];
    let hit = null;
    for (const b of btns) {
      const lab = ((b.getAttribute('aria-label') || '') + ' ' +
                   (b.getAttribute('title') || '') + ' ' +
                   (b.className && b.className.baseVal !== undefined
                    ? b.className.baseVal : (b.className || '')) + ' ' +
                   (b.innerText || '')).toLowerCase();
      const t = (b.innerText || '').trim();
      if (t === '\u00d7' || t === 'x' || t === 'X' || t === '\u2715' ||
          lab.includes('close') || lab.includes('закрыть') ||
          lab.includes('dismiss') || /(^|[^a-z])close([^a-z]|$)/.test(lab)) {
        hit = b; break;
      }
      if (words.some(w => t.toLowerCase() === w)) { hit = b; break; }
    }
    if (hit) { try { hit.click(); killed++; how = 'кнопкой'; } catch (e) {} }
    else { try { el.style.display = 'none'; killed++; how = 'спрятала'; } catch (e) {} }
  }
  return { killed: killed, how: how };
}
"""


def _overlays(page):
    try:
        return page.evaluate(_JS_OVERLAYS) or []
    except Exception:
        return []


def close_ad() -> str:
    """Закрыть баннер/модалку, висящую поверх страницы."""
    if not available() or not _chromium_present():
        return "браузер ещё не готов"

    def job(ctx):
        page = _ensure_page(ctx)
        before = _overlays(page)
        if not before:
            return None, None
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
        except Exception:
            pass
        res = page.evaluate(_JS_CLOSE_OVERLAY) or {}
        page.wait_for_timeout(300)
        return before, res

    try:
        before, res = _post(job, timeout=30)
    except Exception as e:
        return f"не вышло убрать перекрытие: {e}"
    if not before:
        return "поверх страницы ничего не висит — закрывать нечего"
    _mark_used()
    n = (res or {}).get("killed", 0)
    if not n:
        return ("перекрытие вижу, но закрыть не получилось — скажи человеку "
                "честно, пусть ткнёт крестик сам")
    return (f"Убрала {n} перекрытие(й) поверх страницы "
            f"({(res or {}).get('how', '')}). Можешь читать дальше.")


def type_into_search(text: str, submit: bool = True) -> str:
    """Набрать текст в поисковую строку ОТКРЫТОГО САЙТА (не в интернете).
    Строку перед набором ВСЕГДА чистим — «впиши X» значит «пусть там будет
    X», а не «допиши к тому, что лежало»."""
    text = (text or "").strip()
    if not text:
        return "не поняла, что вписывать"
    if not available() or not _chromium_present():
        _install_bg()
        return INSTALLING_MSG

    def job(ctx):
        page = _ensure_page(ctx)
        # баннер поверх страницы перехватывает клики — сперва убираем его,
        # иначе «поставила курсор и ничего не смогла» повторится
        if _overlays(page):
            try:
                page.keyboard.press("Escape")
                page.evaluate(_JS_CLOSE_OVERLAY)
                page.wait_for_timeout(250)
            except Exception:
                pass
        box = None
        for _ in range(2):
            loc = page.locator(_SEARCH_SEL)
            for i in range(min(loc.count(), 6)):
                c = loc.nth(i)
                try:
                    if c.is_visible() and c.is_enabled():
                        box = c
                        break
                except Exception:
                    continue
            if box is not None:
                break
            # строка спрятана за лупой — ткнём её и посмотрим ещё раз
            try:
                t = page.locator(_SEARCH_TOGGLE_SEL).first
                if t.count() and t.is_visible():
                    t.click(timeout=3000)
                    page.wait_for_timeout(500)
                    continue
            except Exception:
                pass
            break
        if box is None:
            return None
        box.click(timeout=5000)
        try:
            box.fill("")                       # ЧИСТИМ — всегда
        except Exception:
            page.keyboard.press("Control+a")
            page.keyboard.press("Delete")
        box.press_sequentially(text, delay=40)
        if submit:
            box.press("Enter")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=12000)
            except Exception:
                pass
            page.wait_for_timeout(900)
        return _page_text(page, 2500)

    try:
        out = _post(job, timeout=60)
    except Exception as e:
        if _launch_failed(e):
            _install_bg()
            return INSTALLING_MSG
        return f"вписать не вышло: {e}"
    _mark_used()
    if out is None:
        return ("поисковой строки на этой странице не нашла — скажи человеку "
                "честно. Если он имел в виду поиск В ИНТЕРНЕТЕ, зови web_list.")
    return f"Вписала «{text}» в поиск сайта. Что на странице:\n\n{out}"


def close() -> str:
    def job(ctx):
        _reset_ctx(ctx)
        return "закрыто"

    try:
        if STATE["open"]:
            _post(job, timeout=15)
    finally:
        STATE["open"] = False
        STATE["used_in_dialog"] = False
    return "Окно браузера закрыла."


def is_open() -> bool:
    return STATE["open"]


def idle_watchdog():
    """Фоновая страховка: окно висит без дела дольше N минут — закрыть молча
    (вдруг пользователь ушёл, а «оставь» сказал час назад)."""
    idle_min = CFG.get("browser.idle_close_min", 15)

    def loop():
        while True:
            time.sleep(60)
            if STATE["open"] and time.time() - STATE["last_used"] > idle_min * 60:
                log.info("Браузер простаивает %s мин — закрываю", idle_min)
                try:
                    close()
                except Exception:
                    pass

    threading.Thread(target=loop, daemon=True).start()
