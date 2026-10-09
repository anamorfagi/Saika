# -*- coding: utf-8 -*-
"""
[БЛОК АВАТАРЫ] Найти лицо персонажа в сети, скачать и вшить в карточку намертво.

Зачем так. Картинка, лежащая только на диске, теряется при первой же чистке —
владелец на этом уже обжёгся. Поэтому изображение кладётся двумя способами
сразу: файлом в ava/<id>.jpg (быстро показать) и строкой base64 внутри
share/<id>.genome.json (карточка переносима и переживает удаление картинок).

Имя файлу даётся по персонажу, а не по идентификатору: ava/Карен.jpg найдётся
глазами, ava/research_28056043bd70.jpg — нет.
"""
import base64
import io as _io
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ЗДЕСЬ = pathlib.Path(__file__).resolve().parent
ГЕНОМ = ЗДЕСЬ.parent
ДОЛЯ = ГЕНОМ / "share"
ЛИЦА = ГЕНОМ / "ava"

ШАПКА = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
         "Accept": "image/avif,image/webp,image/jpeg,image/png,*/*"}
# Откуда берём кадры: вики персонажей и подобные каталоги. Маркетплейсы и
# генераторы «фото в костюме» сюда не попадают — там не персонаж, а товар.
ХОРОШИЕ = ('fandom.com', 'wikia.', 'static.wikia', 'wikimedia.org', 'wikipedia.org',
           'themoviedb.org', 'imdb.com', 'myanimelist', 'anilist', 'kinopoisk')


def искать_картинки(запрос, сколько=12):
    """Поиск картинок с запасными движками и повтором.

    Один движок время от времени не отвечает, и весь поиск падал по таймауту.
    Пробуем по очереди несколько и не сдаёмся с первого раза.
    """
    from ddgs import DDGS
    строки = []
    последняя = None
    for движки in ('duckduckgo, yandex, google', 'yandex', 'google', 'duckduckgo'):
        for попытка in range(2):
            try:
                with DDGS(timeout=25) as d:
                    строки = list(d.images(запрос, max_results=сколько, backend=движки))
                if строки:
                    print("движок:", движки)
                    break
            except Exception as e:
                последняя = e
                continue
        if строки:
            break
    if not строки:
        print("поиск картинок не ответил:", str(последняя)[:140])
    ответ = []
    for r in строки:
        url = r.get("image") or r.get("thumbnail")
        if not url:
            continue
        ответ.append({"url": url, "source": r.get("url", ""), "title": r.get("title", ""),
                      "w": int(r.get("width") or 0), "h": int(r.get("height") or 0)})
    return ответ


# Пользовательские доски и ленты: там что угодно подписано чем угодно.
# По запросу «Karen Spider-Man» оттуда приехал Питер в костюме, а не Карен.
СОМНИТЕЛЬНЫЕ = ('pinterest.', 'tiktok.', 'vk.com', 'ok.ru', 'twitter.', 'x.com',
                'instagram.', 'reddit.', 'facebook.', 'aliexpress', 'ebay.',
                # Обои: широкий кадр, где герой сбоку и в четверть роста.
                # Квадрат из такого — кусок костюма без лица.
                'wallpaper', 'alphacoders', 'wallhaven', '4kwallpapers', 'hdqwalls')


def оценка(кадр, имя=''):
    """Чем выше, тем лучше: вики-каталоги, имя в подписи, портретная форма."""
    очки = 0
    адрес = (кадр["url"] + " " + кадр["source"]).lower()
    if any(h in адрес for h in ХОРОШИЕ):
        очки += 40
    if any(h in адрес for h in СОМНИТЕЛЬНЫЕ):
        очки -= 35
    # Имя персонажа в подписи — единственная проверка, что это вообще он.
    подпись = (кадр.get("title", "") + " " + кадр["source"]).lower()
    куски = [ч for ч in re.split(r'[\s:,\-]+', (имя or '').lower()) if len(ч) > 2]
    if куски and all(ч in подпись for ч in куски):
        очки += 30
    elif куски and any(ч in подпись for ч in куски):
        очки += 10
    w, h = кадр["w"], кадр["h"]
    if w and h:
        отношение = w / h
        if 0.65 <= отношение <= 1.45:     # близко к квадрату — годится под аватар
            очки += 25
        elif отношение > 1.9 or отношение < 0.45:
            # Панорама или узкая полоса: квадрат из неё — обрезок без лица.
            очки -= 45
        if min(w, h) >= 400:
            очки += 15
        if min(w, h) < 180:
            очки -= 40
    return очки


def со_страницы_персонажа(имя, работа):
    """Запасной путь: взять главное изображение со страницы персонажа в вики.

    Когда поиск картинок не отвечает, нужное изображение всё равно лежит в
    карточке персонажа на фэндом-вики — в теге og:image.
    """
    try:
        from ddgs import DDGS
        with DDGS(timeout=25) as d:
            ссылки = list(d.text(f'{имя} {работа} wiki', max_results=6,
                                 backend='duckduckgo, yandex, google'))
    except Exception as e:
        print("и страницу персонажа не нашли:", str(e)[:120])
        return []
    найдено = []
    for r in ссылки:
        url = r.get("href") or ""
        if not any(h in url for h in ('fandom.com', 'wikipedia.org', 'wikia')):
            continue
        try:
            req = urllib.request.Request(url, headers=ШАПКА)
            with urllib.request.urlopen(req, timeout=40) as f:
                html = f.read(600_000).decode("utf-8", "replace")
        except Exception:
            continue
        for шаблон in (r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
                       r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image'):
            m = re.search(шаблон, html, re.I)
            if m:
                print("картинка со страницы:", url[:70])
                найдено.append({"url": m.group(1), "source": url, "title": имя, "w": 0, "h": 0})
                break
        if найдено:
            break
    return найдено


def скачать(url, предел=8_000_000):
    req = urllib.request.Request(url, headers=ШАПКА)
    with urllib.request.urlopen(req, timeout=40) as r:
        тип = r.headers.get_content_type()
        if not тип.startswith("image/"):
            raise ValueError("не изображение: " + тип)
        сырое = r.read(предел + 1)
    if len(сырое) > предел:
        raise ValueError("картинка больше лимита")
    return сырое


def в_квадрат(сырое, сторона=512):
    """Обрезать в квадрат с упором в верх кадра и пережать в jpeg.

    Обрезка строго по центру срезала Питеру голову: на широком кадре герой
    стоит в полный рост, и середина приходится на пояс. Лицо почти всегда
    выше середины, поэтому квадрат берётся ближе к верху.

    Без этого в карточку уезжает мегабайтный кадр: студия держит список
    персонажей в памяти браузера, и на таких картинках он уже однажды лопнул.
    """
    try:
        from PIL import Image
    except Exception:
        return сырое, "как есть (нет Pillow)"
    им = Image.open(_io.BytesIO(сырое))
    им = им.convert("RGB")
    w, h = им.size
    б = min(w, h)
    лево = (w - б) // 2
    # По вертикали отступ сверху — четверть свободного места, а не половина.
    верх = int((h - б) * 0.25)
    им = им.crop((лево, верх, лево + б, верх + б))
    им = им.resize((сторона, сторона), Image.LANCZOS)
    буфер = _io.BytesIO()
    им.save(буфер, "JPEG", quality=88, optimize=True)
    return буфер.getvalue(), f"{w}×{h} → {сторона}×{сторона}"


def безопасное_имя(имя):
    чистое = re.sub(r'[^\w\- .]', '', (имя or '').strip(), flags=re.UNICODE)
    return (чистое or 'персонаж')[:60]


def вшить(ид, запрос=None, имя_файла=None):
    """Найти, скачать, обрезать и вшить картинку в карточку персонажа."""
    файл = ДОЛЯ / (ид + ".genome.json")
    if not файл.exists():
        raise SystemExit("нет карточки " + str(файл))
    карта = json.loads(файл.read_text(encoding="utf-8"))
    мета = карта.get("meta") or {}
    имя = мета.get("name") or ид
    работа = (мета.get("src") or "").split("·")[0].strip()
    запрос = запрос or f"{имя} {работа} character".strip()
    print("ищу картинку:", запрос)

    кадры = sorted(искать_картинки(запрос), key=lambda к: оценка(к, имя), reverse=True)
    if not кадры:
        кадры = со_страницы_персонажа(имя, работа)
    if not кадры:
        raise SystemExit("картинку найти не удалось ни поиском, ни со страницы персонажа")
    for кадр in кадры[:6]:
        try:
            сырое = скачать(кадр["url"])
        except Exception as e:
            print("  мимо:", кадр["url"][:70], "·", str(e)[:60]); continue
        try:
            готово, как = в_квадрат(сырое)
        except Exception as e:
            print("  не обрезалась:", str(e)[:60]); continue
        ЛИЦА.mkdir(parents=True, exist_ok=True)
        имя_файла = имя_файла or безопасное_имя(имя)
        путь = ЛИЦА / (имя_файла + ".jpg")
        путь.write_bytes(готово)
        # Тот же файл ложится под идентификатором: студия ищет лицо по нему.
        (ЛИЦА / (ид + ".jpg")).write_bytes(готово)
        карта["avatar"] = "data:image/jpeg;base64," + base64.b64encode(готово).decode()
        карта.setdefault("meta", {})["avatar_name"] = путь.name
        файл.write_text(json.dumps(карта, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"взято: {кадр['source'][:70] or кадр['url'][:70]}")
        print(f"  {как} · {len(готово)} байт · файл {путь.name} · вшито в карточку")
        return True
    raise SystemExit("ни одна картинка не скачалась")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("как звать: ava_fetch.py <id персонажа> [поисковый запрос] [имя файла]")
        raise SystemExit(2)
    вшить(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None,
          sys.argv[3] if len(sys.argv) > 3 else None)
