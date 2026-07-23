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
    ctx = {"pw": None, "browser": None, "page": None}
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


def _reset_ctx(ctx):
    try:
        if ctx["browser"]:
            ctx["browser"].close()
    except Exception:
        pass
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
    if ctx["browser"] is None or not ctx["browser"].is_connected():
        _reset_ctx(ctx)
        ctx["browser"] = ctx["pw"].chromium.launch(
            headless=False, args=["--window-size=1200,800", "--lang=ru-RU"])
    if ctx["page"] is None or ctx["page"].is_closed():
        bctx = ctx["browser"].new_context(
            viewport={"width": 1180, "height": 760}, locale="ru-RU")
        ctx["page"] = bctx.new_page()
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


def _do_search(ctx, query):
    """Видимый поиск -> список {title,url,snippet}. Два эшелона парсинга:
    обычная выдача, а если не распарсилась — статичная html-версия DDG."""
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
    box.press_sequentially(query, delay=35)   # набор по-человечески
    box.press("Enter")
    try:
        page.wait_for_selector("article, [data-testid=result], .result",
                               timeout=12000)
    except Exception:
        pass
    page.wait_for_timeout(600)
    items = page.evaluate(_JS_RESULTS) or []
    if not items:
        # запасная статичная выдача (тоже в видимом окне)
        page.goto("https://duckduckgo.com/html/?q=" + quote(query),
                  wait_until="domcontentloaded")
        page.wait_for_timeout(400)
        items = page.evaluate(_JS_RESULTS) or []
    return items


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
        return f"[{page.title()}] {url}\n\n" + _page_text(page, 4000)

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
    p = _Text()
    p.feed(r.text)
    text = " ".join(" ".join(p.parts).split())
    return text[:cap]


def research(query: str) -> str:
    """Умный поиск: искать -> ОТКРЫТЬ и ПРОЧИТАТЬ топ-страницы (видимо,
    в том же окне) -> собрать структурированную сводку с источниками.
    Суммаризацию делает LLM отдельным сфокусированным запросом, поэтому
    качество сводки не зависит от размера болтающей модели."""
    query = _clean_query(query)
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
    cands = [r for r in items if not any(b in r["url"].lower()
                                         for b in skip)][:6]

    # ПАРАЛЛЕЛЬНОЕ чтение: все страницы качаются одновременно обычным HTTP
    # (пара секунд на всё), а видимое окно тем временем открывает первый
    # результат — «театр» для пользователя без потери скорости
    from concurrent.futures import ThreadPoolExecutor
    pages = []
    with ThreadPoolExecutor(max_workers=6) as pool:
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
    pages = pages[:5]   # глубина сводки: 5 источников вместо 3 (2026-07-23)

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
             "воды. Пиши на русском."},
            {"role": "user", "content":
             f"Вопрос: {query}\n\nМатериалы:\n{materials[:12000]}"}])
    except Exception as e:
        log.warning("research: сводка не удалась (%s)", e)
        return ("Собрала тексты, но сводка не удалась — вот сырьё:\n"
                + materials[:2500] + "\n\nИсточники:\n" + sources)
    return (f"Изучила {len(pages)} страниц по запросу «{query}».\n\n{digest}"
            f"\n\nИсточники:\n{sources}")


def close() -> str:
    def job(ctx):
        if ctx["browser"]:
            try:
                ctx["browser"].close()
            except Exception:
                pass
        ctx["browser"] = None
        ctx["page"] = None
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
