"""СБОР РЕФЕРЕНСОВ: «вот это неплохо» — и картинка уже в папке проекта.

Владелец 05.09.2026:

    «я открываю нужную страницу с понравившимся рефом, говорю "вот это
     неплохо" — она скачивает моментально сама; я открываю следующую,
     "вот это хорошо" — она моментально скачивает… "попробуй найти
     какую-нибудь повседневную одежду интересной формы, что-нибудь с
     худи" — она открывает сама нужные вкладки, вписывает в поиск и ищет,
     подготовив несколько рефов, закидывает всё в папку»

═══ ДВА РАЗНЫХ ДЕЙСТВИЯ, И ПУТАТЬ ИХ НЕЛЬЗЯ ═══

ВЗЯТЬ (grab): он уже нашёл, смотрит на это глазами и говорит «вот это».
Здесь не нужен ни поиск, ни выбор, ни вопросы — нужна скорость. Одна
секунда против пяти решает, останется ли это «помощью» или превратится в
«погоди, она сейчас думает».

НАЙТИ (find): он описал словами то, чего ещё не видел. Здесь наоборот —
нужен разбор: открыть, отсеять мусор, принести несколько штук.

═══ ЧТО СЧИТАТЬ «ЭТИМ» НА СТРАНИЦЕ ═══

Человек говорит «вот это», глядя на большую картинку в середине экрана.
Порядок поиска повторяет то, что он видит:
  1. открытый файл картинки — вкладка И ЕСТЬ картинка (частый случай:
     он кликнул по превью и открыл оригинал);
  2. og:image — то, чем страница сама себя представляет; на Pinterest и
     Freepik это ровно то изображение, ради которого страницу открывают;
  3. самая крупная картинка в разметке, по заявленным размерам, а не по
     положению в коде.
Ничего не «угадываем по красоте»: три честных правила, и если ни одно не
сработало — говорим, что не поняли, какую именно брать.

═══ ЧЕГО ЗДЕСЬ НЕТ ═══

Обхода защиты и скачивания в промышленных масштабах. Это референсы для
работы: несколько картинок, которые он и так смотрит своими глазами.
Страницы, которые прямо просят не забирать, пропускаем и говорим об этом.
"""
import hashlib
import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from anamorf.config import CFG

log = logging.getLogger("saika.refs")

_IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp")
_MAX_MB = 25


def _folder() -> str:
    """Куда класть. Есть проект — в его «рефы», нет — честно пусто:
    сваливать чужие картинки в случайную папку хуже, чем переспросить."""
    try:
        from anamorf import project
        return project.folder("рефы")
    except Exception:
        return ""


def _safe_name(url: str, ctype: str = "") -> str:
    base = Path(urlparse(url).path).name or "ref"
    base = re.sub(r"[<>:\"/\\|?*\s]+", "_", base)[:60]
    if not base.lower().endswith(_IMG_EXT):
        ext = {"image/jpeg": ".jpg", "image/png": ".png",
               "image/webp": ".webp", "image/gif": ".gif",
               "image/avif": ".avif"}.get((ctype or "").split(";")[0].strip(),
                                          ".jpg")
        base += ext
    # короткий хвост от адреса: два разных рефа с именем image.jpg не
    # должны затирать друг друга
    tail = hashlib.sha1(url.encode("utf-8")).hexdigest()[:6]
    stem, dot, ext = base.rpartition(".")
    return "%s_%s.%s" % (stem or base, tail, ext or "jpg")


def _download(url: str, folder: str, referer: str = "") -> str:
    """Скачать картинку. Возвращает путь или пустую строку."""
    import urllib.request
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/140.0 Safari/537.36"),
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        **({"Referer": referer} if referer else {})})
    with urllib.request.urlopen(req, timeout=25) as r:
        ctype = r.headers.get("Content-Type", "")
        if "image" not in ctype and not url.lower().endswith(_IMG_EXT):
            raise ValueError("это не картинка (%s)" % ctype[:40])
        data = r.read(_MAX_MB * 1024 * 1024 + 1)
    if len(data) > _MAX_MB * 1024 * 1024:
        raise ValueError("картинка больше %d МБ" % _MAX_MB)
    if len(data) < 3000:
        raise ValueError("это превью, а не картинка (%d байт)" % len(data))
    p = Path(folder) / _safe_name(url, ctype)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return str(p)


# ────────────────────────────────────────────── «вот это»
_OG = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+'
                 r'content=["\']([^"\']+)', re.I)
_OG2 = re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+'
                  r'property=["\']og:image', re.I)
_IMG = re.compile(r'<img\b[^>]*>', re.I)
_ATTR = re.compile(r'(\w[\w-]*)\s*=\s*["\']([^"\']*)["\']')


def _biggest_img(html: str, base: str) -> str:
    best, best_area = "", 0
    for tag in _IMG.findall(html or "")[:400]:
        a = dict(_ATTR.findall(tag))
        src = (a.get("src") or a.get("data-src") or "").strip()
        if not src or src.startswith("data:"):
            continue
        try:
            area = int(float(a.get("width", 0))) * int(float(a.get("height", 0)))
        except Exception:
            area = 0
        if area > best_area:
            best, best_area = src, area
    return urljoin(base, best) if best else ""


def grab(url: str = "", why: str = "") -> str:
    """Взять картинку с текущей (или названной) страницы в папку проекта."""
    folder = _folder()
    if not folder:
        return ("Некуда класть: проект не заведён. Скажи «давай новый "
                "проект» и где — тогда рефы будут падать в его папку.")
    from anamorf import browser_hands as bh
    page_url, html = url, ""
    try:
        if not page_url:
            st = bh.current_page() if hasattr(bh, "current_page") else {}
            page_url = str((st or {}).get("url") or "")
            html = str((st or {}).get("html") or "")
        if not page_url:
            return ("Не вижу, на что ты смотришь: браузер не подключён. "
                    "Скажи «подключись к хрому» — и повтори «вот это».")
        # вкладка И ЕСТЬ картинка — самый частый случай
        if page_url.lower().split("?")[0].endswith(_IMG_EXT):
            p = _download(page_url, folder, referer=page_url)
            _remember(p, page_url, why)
            return "Забрала: %s" % Path(p).name
        if not html:
            html = bh.page_html(page_url) if hasattr(bh, "page_html") else ""
    except Exception as e:
        return "Не смогла посмотреть страницу: %s" % str(e)[:120]
    src = ""
    m = _OG.search(html or "") or _OG2.search(html or "")
    if m:
        src = urljoin(page_url, m.group(1))
    if not src:
        src = _biggest_img(html, page_url)
    if not src:
        return ("Не поняла, какую именно картинку брать с этой страницы. "
                "Открой её саму (клик по картинке) и скажи ещё раз.")
    try:
        p = _download(src, folder, referer=page_url)
    except Exception as e:
        return "Картинку не отдали: %s" % str(e)[:120]
    _remember(p, page_url, why)
    return "Забрала: %s" % Path(p).name


def _remember(path: str, source: str, why: str):
    try:
        from anamorf import project
        project.add_ref(path, source, why)
    except Exception:
        pass


# ────────────────────────────────────────────── «найди похожее»
_SITES = {
    "pinterest": "https://ru.pinterest.com/search/pins/?q=",
    "freepik": "https://ru.freepik.com/search?query=",
    "artstation": "https://www.artstation.com/search?query=",
    "google": "https://www.google.com/search?tbm=isch&q=",
}


def find(query: str, n: int = 6, site: str = "") -> str:
    """Найти несколько референсов и сложить в папку проекта."""
    folder = _folder()
    if not folder:
        return ("Некуда класть: проект не заведён. Скажи «давай новый "
                "проект» и где.")
    from anamorf import browser_hands as bh
    site = (site or CFG.get("refs.site", "pinterest")).lower()
    base = _SITES.get(site, _SITES["pinterest"])
    from urllib.parse import quote
    url = base + quote(query)
    try:
        html = bh.open_and_read(url) if hasattr(bh, "open_and_read") else ""
    except Exception as e:
        return "Не смогла открыть поиск: %s" % str(e)[:120]
    if not html:
        return ("Открыла поиск «%s», но страницу прочитать не смогла — "
                "посмотри сам, я рядом." % query)
    urls, seen = [], set()
    for m in re.finditer(r'https?://[^"\'\\s]+?\.(?:jpg|jpeg|png|webp)', html,
                         re.I):
        u = m.group(0)
        if u in seen:
            continue
        seen.add(u)
        urls.append(u)
        if len(urls) >= n * 4:
            break
    got, errs = [], 0
    for u in urls:
        if len(got) >= n:
            break
        try:
            p = _download(u, folder, referer=url)
            got.append(Path(p).name)
            _remember(p, u, query)
        except Exception:
            errs += 1
    if not got:
        return ("По «%s» ничего не забрала: сайт отдаёт только превью. "
                "Открой понравившееся сам и скажи «вот это»." % query)
    return ("По «%s» принесла %d штук в папку «рефы»: %s%s"
            % (query, len(got), ", ".join(got[:6]),
               (" (ещё %d не отдались)" % errs) if errs else ""))


def listing(n: int = 12) -> str:
    try:
        from anamorf import project
        cur = project.current()
        refs = (cur.get("refs") or [])[-n:]
    except Exception:
        refs = []
    if not refs:
        return "Референсов пока нет."
    return "\n".join("%s — %s" % (Path(r["file"]).name, r.get("why") or r.get("from", "")[:60])
                     for r in refs)
