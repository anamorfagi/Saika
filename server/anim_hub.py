"""Автопоиск и скачивание VRMA-анимаций для веб-аватара (2026-07-25).

Просьба владельца: «не ползать по прогам» за анимациями. Источник — GitHub:
публичные репозитории с файлами *.vrma (формат VRM Animation). Поиск без
токена (rate-limit 10 запросов/мин — для ручного использования хватает):
  1) search/repositories?q=vrma — кандидаты;
  2) git/trees?recursive=1 — ищем в дереве файлы .vrma;
  3) скачивание через raw.githubusercontent.com в models/avatar/anims/.

Скачанный файл автоматически становится жестом: имя файла = имя жеста
(ui/avatar.html перечитывает библиотеку при загрузке страницы).

Инструменты для модели: anim_search (читающий), anim_download (изменяющий —
пишет файл на диск, поэтому в _MUTATING_INTENT в tools.py).
"""
import logging
import re

import requests

from server.config import CFG, ROOT

log = logging.getLogger("saika.animhub")

_API = "https://api.github.com"
_HEADERS = {"Accept": "application/vnd.github+json",
            "User-Agent": "saika-anim-hub"}


def _gh_headers():
    """GitHub-поиск без токена часто отвечает 403 (2026-07-25 — «пусто» на
    любой запрос). Личный токен (без прав, только public) решает: положи
    его в secrets.json -> github.token, и поиск оживёт."""
    h = dict(_HEADERS)
    try:
        import json as _j
        tok = (_j.loads((ROOT / "secrets.json").read_text(encoding="utf-8"))
               .get("github", {}) or {}).get("token", "")
        if tok:
            h["Authorization"] = "Bearer " + tok
    except Exception:
        pass
    return h
# найденное в последнем поиске: индекс -> (repo, branch, path) — чтобы
# скачивать по короткому номеру, а не заставлять модель повторять пути
_LAST = {}


def _anims_dir():
    from pathlib import Path
    raw = CFG.get("avatar.web.anims_dir", "models/avatar/anims")
    p = Path(raw)
    p = p if p.is_absolute() else (ROOT / raw)
    p.mkdir(parents=True, exist_ok=True)
    return p


def search(query: str = "") -> str:
    """Найти .vrma-анимации на GitHub. Возвращает нумерованный список."""
    q = (query or "").strip()
    try:
        r = requests.get(_API + "/search/repositories",
                         params={"q": f"{q} vrma".strip(), "per_page": 6},
                         headers=_gh_headers(), timeout=15)
        r.raise_for_status()
        repos = r.json().get("items", [])
    except Exception as e:
        return (f"поиск по GitHub не удался: {e}. Вызови anim_hints — там "
                "прямые проверенные ссылки на источники VRMA (через "
                "anim_from_url), не зависящие от GitHub API")

    _LAST.clear()
    lines, idx = [], 1
    for repo in repos:
        full = repo["full_name"]
        branch = repo.get("default_branch", "main")
        try:
            t = requests.get(f"{_API}/repos/{full}/git/trees/{branch}",
                             params={"recursive": "1"},
                             headers=_gh_headers(), timeout=15)
            if not t.ok:
                continue
            paths = [n["path"] for n in t.json().get("tree", [])
                     if n.get("path", "").lower().endswith(".vrma")]
        except Exception:
            continue
        for p in paths[:8]:
            _LAST[idx] = (full, branch, p)
            lines.append(f"{idx}. {p.rsplit('/', 1)[-1]}  "
                         f"({full}, ⭐{repo.get('stargazers_count', 0)})")
            idx += 1
        if idx > 20:
            break
    if not lines:
        return ("ничего не нашла по «" + q + "» — поиск по GitHub ищет "
                "репозитории ПО ИМЕНИ, а .vrma обычно лежат в репо с обычным "
                "названием, так что это нормально, не поломка. Вызови "
                "anim_hints — там прямые проверенные ссылки на источники "
                "VRMA (можно сразу через anim_from_url)")
    return ("нашла анимации (скачать: anim_download с номером):\n"
            + "\n".join(lines))


def download(num, name: str = "") -> str:
    """Скачать анимацию №num из последнего поиска в библиотеку жестов."""
    try:
        num = int(num)
    except Exception:
        return "нужен номер из результата anim_search"
    if num not in _LAST:
        return "такого номера нет — сначала anim_search или anim_from_url"
    full, branch, path = _LAST[num]
    url = path if full == "__direct__" \
        else f"https://raw.githubusercontent.com/{full}/{branch}/{path}"
    fname = (name or path.rsplit("/", 1)[-1].rsplit(".", 1)[0]).lower()
    fname = re.sub(r"[^a-z0-9_\-]", "_", fname)[:32] or "anim"
    dest = _anims_dir() / f"{fname}.vrma"
    try:
        r = requests.get(url, timeout=60, headers=_HEADERS)
        r.raise_for_status()
        if len(r.content) < 200:
            return "файл подозрительно мал — похоже, не скачался"
        dest.write_bytes(r.content)
    except Exception as e:
        return f"не скачалось: {e}"
    return (f"скачала {path.rsplit('/', 1)[-1]} -> жест «{fname}» "
            f"({len(r.content)//1024} КБ). Обнови страницу аватара, и можно "
            f"звать: avatar_action или [жест:{fname}]")


def from_url(url: str, name: str = "") -> str:
    """Универсальный путь (2026-07-25, просьба владельца: «сама парсит
    сайты»): дать ЛЮБОЙ url. Если это сам .vrma — скачиваем. Если это
    страница — парсим HTML, собираем все ссылки на .vrma и показываем
    нумерованный список (скачивание — anim_download по номеру).
    Работает в связке с web_search/open_page: Сайка сама ищет страницу
    в интернете, потом сюда её адрес."""
    url = (url or "").strip()
    if not url.startswith("http"):
        return "нужен полный http(s)-адрес страницы или файла"
    # сам файл?
    if url.lower().split("?")[0].endswith(".vrma"):
        _LAST.clear()
        _LAST[1] = ("__direct__", "", url)
        return download(1, name)
    try:
        r = requests.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (saika-anim-hub)"})
        r.raise_for_status()
        html = r.text[:2_000_000]
    except Exception as e:
        return f"страница не открылась: {e}"
    from urllib.parse import urljoin
    links = re.findall(r'href=["\']([^"\']+?\.vrma(?:\?[^"\']*)?)["\']',
                       html, re.I)
    links += re.findall(r'["\'](https?://[^"\']+?\.vrma)["\']', html, re.I)
    seen, out = set(), []
    for l in links:
        full = urljoin(url, l)
        if full not in seen:
            seen.add(full)
            out.append(full)
    if not out:
        return ("на странице нет прямых ссылок на .vrma — попробуй другую "
                "страницу (или это сайт с кнопкой-скачиванием за логином, "
                "туда мне не пройти)")
    _LAST.clear()
    lines = []
    for i, full in enumerate(out[:20], 1):
        _LAST[i] = ("__direct__", "", full)
        lines.append(f"{i}. {full.rsplit('/', 1)[-1].split('?')[0]}")
    return ("нашла на странице (скачать: anim_download с номером):\n"
            + "\n".join(lines))


def list_local() -> str:
    files = sorted(f.stem for f in _anims_dir().glob("*.vrma"))
    return ("в библиотеке: " + ", ".join(files)) if files \
        else "библиотека пуста — anim_search найдёт новые"


# ---------------------------------------------------------------------------
# ПРЯМЫЕ ПОДСКАЗКИ (2026-07-25) — поиск по GitHub repo-search почти всегда
# пуст: .vrma-файлы обычно лежат ГЛУБОКО в репозиториях с обычными именами
# (не «dance», не «vrma»), поиск по названию репо их не находит. Вместо
# того чтобы полагаться только на угадывание запроса, держим проверенный
# список реальных источников — их можно сразу предложить владельцу или
# скормить в anim_from_url (для страниц) / скачать напрямую (для файла).
_HINTS = [
    ("VRoid Hub — Photo Booth", "https://hub.vroid.com/en",
     "готовые VRMA от сообщества, можно скачивать прямо со страницы модели/анимации"),
    ("BOOTH — бесплатный набор от VRoid (7 анимаций)",
     "https://vroid.booth.pm/items/5512385",
     "greeting, peace sign, shoot, spin, pose, squat и др. — сразу .vrma, без конвертации"),
    ("BOOTH — раздел «3D Motion/Animation»", "https://booth.pm/en/browse/3D%20Motion%2FAnimation",
     "авторские VRMA, часть бесплатно — там же ищи по тегу vrma"),
    ("Librn Editor", "https://editor.librn.com/",
     "браузерный редактор — можно и создать свою VRMA, и посмотреть примеры"),
    ("pixiv/three-vrm — тестовый файл (для проверки, что скачивание/плеер работает)",
     "https://raw.githubusercontent.com/pixiv/three-vrm/dev/packages/three-vrm-animation/examples/models/test.vrma",
     "один короткий жест, зато 100% рабочий — можно anim_from_url на этот url напрямую"),
    ("VRM showcase — список ещё платформ", "https://vrm.dev/en/showcase/?flags=98",
     "официальный список инструментов/сайтов вокруг VRM, включая источники анимаций"),
]


def hints() -> str:
    """Прямые проверенные ссылки на источники VRMA — когда anim_search
    не находит ничего (обычная история для repo-name поиска на GitHub)."""
    lines = [f"{i}. {title} — {url}\n   ({note})"
             for i, (title, url, note) in enumerate(_HINTS, 1)]
    return ("проверенные источники VRMA-анимаций (для страниц — anim_from_url, "
            "для прямого .vrma — тоже anim_from_url, он сам скачает):\n"
            + "\n".join(lines))
