"""Руки Сайки в самой Windows: программы, окна, звук, вкладки браузера.

ЗАЧЕМ. Владелец хочет разговаривать с ней с дивана: «запусти Blender»,
«сверни всё лишнее», «сделай потише», «закрой эту вкладку». До сих пор из
системного у неё были только просмотр процессов и запуск строго из белого
списка путей, который надо было заполнять руками — на практике он так и
остался пустым.

ЧТО ЗДЕСЬ ЕСТЬ
  каталог программ  — сам собирается из меню «Пуск» и рабочего стола
  окна              — список, свернуть, закрыть, показать поверх
  звук              — громче/тише/выключить
  вкладки           — открыть, закрыть, перейти к N-й (клавишами в активное окно)
  папки             — открыть в проводнике

ЧЕГО ЗДЕСЬ НЕТ И ПОЧЕМУ. Ничего, что стирает данные. Файлы, папки и код —
отдельный модуль file_hands, и он заперт в рабочей директории (files.roots).
Здесь только запуск и окна. «Закрыть» — это WM_CLOSE, вежливая просьба:
программа успеет спросить про несохранённое. Принудительное снятие процесса
живёт в system_control.kill и требует подтверждения — тут его нет намеренно.

КАК СОБИРАЕТСЯ КАТАЛОГ. Ярлыки .lnk из меню «Пуск» (общесистемного и
пользовательского) и с рабочего стола. Запускаем САМ ЯРЛЫК через
os.startfile — так не нужно разбирать бинарный формат .lnk ради пути к exe,
и заодно сохраняются рабочая папка и аргументы, прописанные в ярлыке.
Игры Steam и Epic попадают сюда же: их установщики кладут ярлыки в «Пуск».
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

from server.config import CFG, ROOT

log = logging.getLogger("saika.pc")

_IS_WIN = os.name == "nt"
INDEX_PATH = ROOT / "data" / "app_index.json"
_index: dict = {"apps": [], "built": 0.0}

# Что в каталог не берём никогда: деинсталляторы, «прочитай меня», ссылки на
# сайты производителя. Владелец с дивана просит «запусти игру», а не
# «удали игру» — и промахнуться голосом тут очень легко.
_SKIP_RE = re.compile(
    r"uninstall|удал|деинстал|remove|repair|readme|help|справк|"
    r"документац|manual|license|лиценз|website|веб-?сайт|support|"
    r"поддержк|report a (bug|problem)|crash",
    re.I)


# ─────────────────────────── каталог программ ───────────────────────────
def _scan_dirs() -> list[Path]:
    out = []
    for env, sub in (("ProgramData", "Microsoft/Windows/Start Menu/Programs"),
                     ("APPDATA", "Microsoft/Windows/Start Menu/Programs"),
                     ("USERPROFILE", "Desktop"),
                     ("PUBLIC", "Desktop")):
        base = os.environ.get(env)
        if base:
            p = Path(base) / sub
            if p.exists():
                out.append(p)
    for extra in (CFG.get("pc.extra_scan_dirs", []) or []):
        p = Path(str(extra))
        if p.exists():
            out.append(p)
    return out


def build_index(force=False) -> dict:
    """Собрать каталог программ. Кэшируем на диск: обход «Пуска» это
    несколько тысяч файлов, дёргать его на каждую фразу незачем."""
    ttl = float(CFG.get("pc.index_ttl_h", 24)) * 3600
    if not force and _index["apps"] and time.time() - _index["built"] < ttl:
        return _index
    if not force and not _index["apps"] and INDEX_PATH.exists():
        try:
            data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            if time.time() - float(data.get("built", 0)) < ttl:
                _index.update(apps=data.get("apps", []),
                              built=float(data.get("built", 0)))
                return _index
        except Exception as e:
            log.debug("каталог программ не прочитался: %s", e)

    apps, seen = [], set()
    for d in _scan_dirs():
        try:
            for f in d.rglob("*"):
                if f.suffix.lower() not in (".lnk", ".url"):
                    continue
                name = f.stem.strip()
                if not name or _SKIP_RE.search(name) or _SKIP_RE.search(str(f)):
                    continue
                low = name.lower()
                if low in seen:
                    continue
                seen.add(low)
                apps.append({"name": name, "path": str(f),
                             "kind": f.suffix.lower().lstrip(".")})
        except Exception as e:
            log.debug("не смогла обойти %s: %s", d, e)
    apps.sort(key=lambda a: a["name"].lower())
    _index.update(apps=apps, built=time.time())
    try:
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(json.dumps(_index, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    except Exception as e:
        log.debug("каталог программ не сохранился: %s", e)
    log.info("Каталог программ собран: %d ярлыков", len(apps))
    return _index


def blocked() -> set:
    return {str(x).lower() for x in (CFG.get("pc.blocked_apps", []) or [])}


def set_blocked(name: str, on: bool) -> str:
    """Вычеркнуть программу из каталога (или вернуть). Список правится в
    интерфейсе: каталог собирается сам, но последнее слово за владельцем."""
    cur = [str(x) for x in (CFG.get("pc.blocked_apps", []) or [])]
    low = [x.lower() for x in cur]
    if on and name.lower() not in low:
        cur.append(name)
    if not on:
        cur = [x for x in cur if x.lower() != name.lower()]
    CFG.set("pc.blocked_apps", cur)
    return f"«{name}» " + ("скрыта от Сайки" if on else "снова доступна")


def apps(query: str = "", limit: int = 40) -> list:
    """Программы каталога, при желании отфильтрованные."""
    idx = build_index()
    bad = blocked()
    q = (query or "").strip().lower()
    out = []
    for a in idx["apps"]:
        if a["name"].lower() in bad:
            continue
        if q and q not in a["name"].lower():
            continue
        out.append(a)
    return out[:limit] if limit else out


# РУССКАЯ РАСКЛАДКА ГОЛОСОМ (2026-07-29). Названия программ латинские, а
# произносят их по-русски: «корел дро», «фотошоп», «блендер». Распознавание
# честно пишет кириллицей — и точное сравнение проваливается на ровном месте.
# Таблица грубая нарочно: нам не нужна правильная транслитерация, нужно
# лишь сблизить строки настолько, чтобы их поймало нечёткое сравнение.
_RU2LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _norm(s: str) -> str:
    """Строка без пробелов, знаков и регистра, кириллица — латиницей.
    «Coral Draft», «CorelDRAW 2021», «корел дро» сходятся в одно поле."""
    s = (s or "").lower()
    # диграфы до побуквенной замены: «эксель» должен стать exel, а не eksel,
    # иначе от excel его отделяет лишняя буква и совпадение не дотягивает
    for a, b in (("кс", "x"), ("ья", "ya"), ("ье", "ye")):
        s = s.replace(a, b)
    out = []
    for ch in s:
        if ch in _RU2LAT:
            out.append(_RU2LAT[ch])
        elif ch.isalnum():
            out.append(ch)
    return "".join(out)


# ТРАНСЛИТ (2026-08-13, живой провал: «Запусти блендер» -> она нашла
# «Blender», «Blend for Visual Studio» и «Mount & Blade II», и вместо
# запуска СПРОСИЛА, какой именно. Причина не в логике выбора: сравнивалось
# «блендер» с «blender» — кириллица с латиницей, похожесть нулевая, ни одно
# правило не сработало. То же с «хром», «стим», «фотошоп», «дискорд» — то
# есть с половиной названий, которые человек произносит по-русски.)
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
# как русское ухо слышит латиницу: «си» это c, «кей» это k. Второй проход
# нужен, потому что один звук пишут по-разному: хром/chrome, кром/chrome.
_SOUND_FIX = (("ks", "x"), ("kh", "h"), ("ck", "k"), ("ph", "f"),
              ("ee", "i"), ("oo", "u"), ("yu", "u"), ("ya", "ia"))


def translit(t: str) -> str:
    out = "".join(_TRANSLIT.get(ch, ch) for ch in (t or "").lower())
    for a, b in _SOUND_FIX:
        out = out.replace(a, b)
    return out


# СОГЛАСНЫЙ СКЕЛЕТ. Одного транслита мало: «стим» -> stim, а программа
# Steam; «дискорд» -> diskord против Discord; «хром» -> hrom против Chrome.
# Всё это ОДИН звук, записанный по-разному. Гласные в названиях почти не
# несут различия, а согласные несут — поэтому сравниваем скелет из
# согласных, предварительно сведя разнописания к одному виду.
_SKEL_FIX = (("ch", "h"), ("sh", "s"), ("zh", "z"), ("ph", "f"),
             ("ck", "k"), ("c", "k"), ("q", "k"), ("x", "ks"),
             ("y", "i"), ("w", "v"), ("j", "i"))


# ═══ СЛЫШУ КРИВО — УЗНАЮ ВСЁ РАВНО (2026-08-14) ═══
# Владелец: «что нужно сделать, чтобы она могла анализировать косяки микро и
# логично исправлять неточности, даже если криво всё сказали».
#
# Живой замер, с которого всё началось:
#     _score("Genshin Impact", "гентион импакт") = 31
#     _score("Genshin Impact", "генжон факт")    = 26   при пороге 45
# То есть распознавание речи услышало «гентион», транслит дал «gention», а
# скелет согласных gntn против gnshn — уже другое слово. Формально верно,
# по делу — провал: человек сказал понятно, ошиблась цепочка.
#
# Лечим фонетикой, а не порогами. Шипящие и свистящие в русской речи через
# микрофон путаются постоянно (ш/с/ж/з/щ/ч), звонкие глохнут (д/т, г/к,
# б/п, в/ф), гласные съедаются. Приводим оба имени к «звуковому скелету»,
# где эти различия стёрты, и сравниваем уже его.
#
# ВАЖНО: эта оценка только ПОДНИМАЕТ результат, никогда не опускает. Старый
# счёт остаётся как есть — он рабочий, и ломать его ради нового нельзя.
_PHON_MAP = str.maketrans({
    # шипящие и свистящие — в один звук
    "ш": "s", "щ": "s", "ж": "s", "з": "s", "с": "s", "ц": "s", "ч": "s",
    "j": "s", "z": "s", "c": "s",
    # звонкие/глухие пары
    "д": "t", "т": "t", "d": "t",
    "г": "k", "к": "k", "х": "k", "g": "k", "q": "k",
    "б": "p", "п": "p", "b": "p",
    "в": "f", "ф": "f", "v": "f", "w": "f",
    # прочее
    "л": "l", "р": "r", "м": "m", "н": "n", "й": "i", "y": "i",
})
_VOWELS = "аеёиоуыэюяaeiou"


def _phon(t: str) -> str:
    """Звуковой скелет: то, что реально слышно, без различимых мелочей."""
    t = translit(str(t or "").lower())
    t = "".join(ch for ch in t if ch.isalnum())
    t = t.translate(_PHON_MAP)
    out = []
    for ch in t:
        if ch in _VOWELS:
            continue                      # гласные съедаются первыми
        if out and out[-1] == ch:
            continue                      # сдвоенные согласные — один звук
        out.append(ch)
    return "".join(out)


def _ratio(a: str, b: str) -> float:
    """Похожесть 0..1 без внешних библиотек (расстояние Левенштейна)."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return 1.0 - prev[-1] / max(len(a), len(b))


def phon_score(name: str, query: str) -> int:
    """Насколько похоже НА СЛУХ, 0..100. Только как добавка к _score."""
    pn, pq = _phon(name), _phon(query)
    if not pn or not pq:
        return 0
    r = _ratio(pn, pq)
    # длинное имя, короткий запрос: «геншин» против «genshin impact» —
    # человек назвал часть, и это нормально
    if len(pq) >= 3 and pq in pn:
        r = max(r, 0.86)
    return int(r * 100)


def _skeleton(t: str) -> str:
    v = translit(t)
    for a, b in _SKEL_FIX:
        v = v.replace(a, b)
    v = re.sub(r"[^a-z]", "", v)
    v = re.sub(r"[aeiou]", "", v)
    return re.sub(r"(.)\1+", r"\1", v)      # «ss» и «s» — одно и то же


def _score(name: str, q: str) -> int:
    """Похожесть с учётом того, что человек говорит по-русски, а ярлык
    подписан по-английски. Три уровня: как есть -> транслит -> скелет."""
    best = _score_raw(name, q)
    tn, tq = translit(name), translit(q)
    if tn != name.lower() or tq != q.lower():
        # транслит — догадка, поэтому чуть дешевле точного совпадения
        best = max(best, _score_raw(tn, tq) - 3)
    if best >= 45:
        return best
    sn, sq = _skeleton(name), _skeleton(q)
    if len(sq) >= 3 and sn and sq:
        # скелет всей строки или ПЕРВОГО СЛОВА: «Adobe Photoshop 2024» —
        # человек говорит «фотошоп», а не полное имя ярлыка
        parts = [sn] + [_skeleton(w) for w in re.findall(r"\w+", name)]
        if sq in parts:
            best = max(best, 62)
        elif any(p.startswith(sq) and len(p) - len(sq) <= 3 for p in parts):
            best = max(best, 52)
    return best


def _score_raw(name: str, q: str) -> int:
    """Насколько ярлык похож на то, что попросили. Голосом просят коротко
    («блендер», «стим»), а в «Пуске» лежат «Blender 4.2» и «Steam Client».

    НЕЧЁТКОЕ СРАВНЕНИЕ ДОБАВЛЕНО 2026-07-29 по живому промаху: владелец
    сказал «открой Корел Драфт», распознавание написало «CoralDraft», а
    программа зовётся «CorelDRAW». Ни одно точное правило не срабатывает:
    подстроки нет, общих слов нет — и Сайка отвечала «не нашла», хотя
    ярлык лежал прямо перед ней. Человек услышал название один раз и
    повторяет как запомнил; попадать в написание побуквенно — не его
    работа. Поэтому последним рубежом идёт похожесть строк, и она же
    вытягивает опечатки распознавания."""
    n = name.lower()
    if n == q:
        return 100
    if n.startswith(q):
        return 80 - min(20, len(n) - len(q))
    if q in n:
        return 55 - min(20, len(n) - len(q))
    words = set(re.findall(r"\w+", n))
    qw = set(re.findall(r"\w+", q))
    if qw and qw <= words:
        return 45
    if qw & words:
        return 25
    # ПОСЛЕДНИЙ РУБЕЖ: ПОХОЖЕСТЬ ПО БУКВАМ.
    # Стенд показал, что сравнивать строку целиком мало: «Adobe Photoshop
    # 2024» против «фотошоп» — это 18 букв против 8, и любая честная мера
    # похожести тонет в марке производителя и номере версии. Поэтому имя
    # разбирается на кусочки, и запрос меряется с КАЖДЫМ: целиком, по
    # отдельным словам, по первым двум словам. Совпало с «photoshop» —
    # достаточно, остальное в названии человека не интересует.
    nq = _norm(q)
    if len(nq) < 3:
        return 0
    parts = [_norm(name)]
    ws = [w for w in re.findall(r"[A-Za-zА-Яа-яЁё]+", name) if len(w) > 2]
    parts += [_norm(w) for w in ws]
    if len(ws) >= 2:
        parts.append(_norm(ws[0] + ws[1]))
    # Сначала СОБИРАЕМ все признаки, потом решаем — ранний return 40 на
    # префиксе перехватывал даже точное «телеграм» = telegram и не пускал
    # его к уверенному баллу (стенд 2026-07-29 поймал на первом же прогоне)
    best, near = 0.0, False
    import difflib
    for cand in parts:
        if len(cand) < 3:
            continue
        if cand == nq:
            # слово имени целиком совпало: «телеграм» = telegram из
            # «Telegram Desktop» — это ОНО, спрашивать нечего
            return 46
        if nq in cand or cand.startswith(nq[:5]):
            near = True
        # и с НАЧАЛОМ кандидата той же длины: короткое «корел» против
        # длинного «coreldraw» иначе тонет — половина букв кандидата не
        # имеет пары, и честная мера похожести падает ниже порога, хотя
        # человек назвал программу совершенно узнаваемо
        r = max(difflib.SequenceMatcher(None, cand, nq).ratio(),
                difflib.SequenceMatcher(None, cand[:len(nq) + 2], nq).ratio())
        if r > best:
            best = r
    # КУСОЧКИ ЗАПРОСА (2026-07-29, живой пример владельца: «клауд код» не
    # находило Claude — целиком «klaudkod» слишком далёк от «claude», а вот
    # слово «клауд» уже узнаваемо). Слова запроса мерим с именем по одному.
    # Потолок кусочку — НИЖЕ любой оценки целой фразы (стенд поймал
    # инверсию: «корел драфт» ставил PHOTO-PAINT (кусок «корел» = слово
    # имени) выше CorelDRAW (целая фраза похожа на 0.84) — и «да» человека
    # запоминало НЕ ТУ программу навсегда). Целая фраза — свидетельство
    # сильнее фрагмента, всегда.
    frag = False
    for sw in (_norm(w) for w in re.findall(r"[A-Za-zА-Яа-яЁё\d'-]+", q)):
        if frag:
            break
        if len(sw) < 3 or sw == nq:
            continue
        for cand in parts:
            if len(cand) < 3:
                continue
            if cand == sw or sw in cand or cand.startswith(sw[:5]):
                frag = True
                break
            rr = max(difflib.SequenceMatcher(None, cand, sw).ratio(),
                     difflib.SequenceMatcher(None, cand[:len(sw) + 2],
                                             sw).ratio())
            if rr >= 0.7:
                frag = True
                break
    # ПОЧТИ ТОЧНО = ТОЧНО (2026-07-29, просьба владельца: «геншин импакт мы
    # же можем понять»). genshinimpakt против genshinimpact — одна буква из
    # тринадцати, это не «похоже», это ОНО с акцентом распознавалки. Такому
    # совпадению даём уверенный балл — запуск без лишнего вопроса. Порог 0.9
    # строгий нарочно: «похожая» программа сюда не пролезет, а что пролезло
    # ниже — уйдёт в «это оно?» и запомнится с первого ответа.
    if best >= 0.9:
        return 46
    if near:
        return 40
    if best >= 0.62:
        return int(10 + 28 * best)
    if frag:
        return 26            # кусочек: хватает попасть в вопрос, не в запуск
    return 0


def find_app(query: str) -> list:
    q = (query or "").strip().lower()
    if not q:
        return []
    scored = [(a, _score(a["name"], q)) for a in apps(limit=0)]
    scored = [(a, s) for a, s in scored if s > 0]
    scored.sort(key=lambda p: -p[1])
    return [a for a, _s in scored[:8]]


def _memory():
    """Память на программы. Отдельным модулем и лениво: если файла нет
    (старая копия проекта), запуск по ярлыкам обязан работать как раньше."""
    try:
        from server import app_memory
        return app_memory
    except Exception as e:      # pragma: no cover
        log.debug("память на программы недоступна: %s", e)
        return None


def _start(item: dict) -> str:
    """Собственно запуск + честная проверка, что окно появилось."""
    try:
        if _IS_WIN:
            os.startfile(item["path"])          # noqa: S606 — ярлык из «Пуска»
        else:
            subprocess.Popen(["xdg-open", item["path"]])
    except Exception as e:
        return f"Не смогла запустить «{item['name']}»: {e}"
    # проверка результата: ждём до 3с, появилось ли ОКНО этой программы —
    # «запустила» без окна на экране человек читает как «ничего не произошло»
    seen = ""
    try:
        want = (item["name"] or "").lower().split()[0]
        for _ in range(6):
            time.sleep(0.5)
            for w in windows(include_minimized=False):
                hay = (w["title"] + " " + (w["proc"] or "")).lower()
                if want and want in hay:
                    seen = w["title"][:50]
                    break
            if seen:
                break
    except Exception:
        pass
    return (f"Запустила {item['name']} — окно «{seen}» уже на экране." if seen
            else f"Запустила {item['name']}, но окна пока не вижу — она может "
                 "грузиться или живёт в трее. Скажи человеку как есть.")


# ОТВЕТ НА «ЭТО ОНО?» (2026-07-29). Отдельного инструмента у модели нет и не
# надо: человек отвечает голосом в тот же запуск — «да», «второе», «нет».
# Ловим это здесь, на входе launch, пока вопрос не протух.
_YES = re.compile(r"^\s*(да|ага|угу|верно|точно|оно|это оно|именно|"
                  r"подтверждаю|конечно|ну да)\b", re.I)
_NO = re.compile(r"^\s*(нет|не|неа|не то|не оно|мимо)\b", re.I)
_ORD = (("перв", 1), ("втор", 2), ("трет", 3), ("четв", 4),
        ("1", 1), ("2", 2), ("3", 3), ("4", 4))


def _as_answer(q: str):
    """Номер выбора из фразы человека, 0 — «нет», None — это не ответ."""
    s = (q or "").strip().lower()
    if not s:
        return None
    if _NO.match(s):
        return 0
    for word, n in _ORD:
        if word in s:
            return n
    if _YES.match(s):
        return 1
    return None


def _wide_hits(q: str) -> list:
    """Широкий заход: реестр App Paths и запущенные процессы. Дороже ярлыков,
    поэтому только когда «Пуск» промолчал."""
    mem = _memory()
    if not mem:
        return []
    scored = []
    for it in mem.wide_catalog():
        s = _score(it["name"], q.lower())
        if s > 0:
            scored.append((it, s))
    scored.sort(key=lambda p: -p[1])
    return scored[:6]


def launch(query: str) -> str:
    # запоминаем, ЧЕМ занимались: следом человек скажет «подними ЕГО»
    remember_app(query)
    """Запустить программу по человеческому названию.

    ПОРЯДОК (2026-07-29, дословная просьба владельца: «она должна запустить
    любую прогу по запросу; не знает — ищет в системе, в диспетчере, на
    рабочем столе, сравнивает похожее и спрашивает ОДИН РАЗ „это оно?“,
    и запоминает»):
      0. это ответ на наш же вопрос — исполняем и запоминаем;
      1. выученное — мгновенно, без вопросов;
      2. ярлыки «Пуска» с уверенным совпадением — как раньше;
      3. широкий заход + вопрос «это оно?» вместо тихой догадки.
    Догадка запускается молча только когда совпадение уверенное. Тихая
    ошибка дороже вопроса: её не видно и она повторяется каждый раз.
    """
    mem = _memory()
    # хвостовая пунктуация распознавания («Telegram.») ломала точное
    # совпадение и уводила уверенный запуск в лишний вопрос (2026-07-29)
    q = (query or "").strip().strip(" .,!?…»«\"'")
    # МУСОР ВОКРУГ НАЗВАНИЯ (2026-07-29, владелец: «распознаватель чуток
    # лишнего захватил»). Голосом просят «ну открой мне геншин импакт
    # пожалуйста» — командные и вежливые слова к имени программы не
    # относятся и топят совпадение. Вычищаем их; если после чистки ничего
    # не осталось (фраза целиком командная) — работаем с исходной.
    _junk = {"открой", "открыть", "запусти", "запустить", "включи",
             "включить", "вруби", "стартуй", "поставь", "запуск",
             "пожалуйста", "плиз", "просто", "ну", "давай", "быстро",
             "мне", "мой", "моя", "его", "её", "же", "ка", "а", "и",
             "приложение", "программу", "программа", "прогу", "прога",
             "игру", "игра", "на", "в", "компе", "пк", "снова", "опять",
             "заново", "ещё", "еще", "раз"}
    _kept = [w for w in re.findall(r"[\w'-]+", q) if w.lower() not in _junk]
    if _kept and len(_kept) < len(re.findall(r"[\w'-]+", q)):
        q = " ".join(_kept)

    # 0. ОТВЕТ НА ВОПРОС
    if mem and mem.pending():
        pick = _as_answer(q)
        if pick == 0:
            mem.drop()
            return ("Поняла, не то. Назови иначе — или скажи точное название, "
                    "как оно подписано в «Пуске».")
        if pick:
            chosen = mem.confirm(pick)
            if chosen:
                return (f"Запомнила: «{mem.last_query()}» — это "
                        f"{chosen['name']}. ") + _start(chosen)
            return "Такого номера в списке не было — назови ещё раз."

    if not q:
        return "Не расслышала, что запускать."

    # 1. ВЫУЧЕННОЕ
    if mem:
        rec = mem.recall(q)
        if rec and Path(rec["path"]).exists():
            mem.remember(q, rec["name"], rec["path"])   # счётчик обращений
            return _start(rec)

    # 1а. СИСТЕМНЫЕ ПРОГРАММЫ WINDOWS (2026-07-29, живой провал: «открой
    # диспетчер задач» -> «не могу найти» — у системных программ нет ярлыка
    # в «Пуске», их запускают по имени, как из окна «Выполнить»)
    _builtin = {
        "диспетчер задач": "taskmgr", "диспетчер": "taskmgr",
        "блокнот": "notepad", "калькулятор": "calc",
        "проводник": "explorer", "паинт": "mspaint", "пейнт": "mspaint",
        "командная строка": "cmd", "консоль": "cmd", "терминал": "wt",
        "панель управления": "control", "ножницы": "snippingtool",
        "параметры": "ms-settings:", "настройки windows": "ms-settings:",
        "регедит": "regedit", "реестр": "regedit",
        "звук": "mmsys.cpl", "устройства": "devmgmt.msc",
    }
    _bk = q.lower()
    _hit = _builtin.get(_bk) or next(
        (v for k, v in _builtin.items() if k in _bk or _bk in k), "")
    if _hit and _IS_WIN:
        try:
            os.startfile(_hit)              # noqa: S606 — системное имя
            return f"Запустила ({_hit})."
        except Exception as e:
            log.debug("системный запуск %s: %s", _hit, e)

    # 2. ЯРЛЫКИ
    hits = find_app(q)
    if not hits:
        # каталог мог собраться до установки — пересобираем и пробуем ещё раз
        build_index(force=True)
        hits = find_app(q)
    # _score сравнивает с нижним регистром — «Telegram» с большой буквы
    # иначе тихо проигрывает собственному ярлыку (стенд 2026-07-29)
    # берём лучшее из двух: буквенного счёта и фонетического. Второй
    # вытягивает случаи, где микрофон услышал «гентион» вместо «genshin»
    scored = [(a, max(_score(a["name"], q.lower()),
                      phon_score(a["name"], q))) for a in hits]
    if scored:
        best, bs = scored[0]
        second = scored[1][1] if len(scored) > 1 else 0
        # уверенно = попали по названию (не по буквенной похожести) и рядом
        # нет второго такого же кандидата
        # ОДНО И ТО ЖЕ РАЗНЫМИ ПОДПИСЯМИ (2026-08-13): «Steam» и «Steam
        # Client», «Blender» и «Blender 4.2» — это не выбор, а один ярлык в
        # двух видах. Правило «второй должен отстать на 20» тут работало
        # против человека: кандидаты набирали поровну, и она переспрашивала
        # там, где спрашивать нечего. Если у лидеров ОДИН скелет — берём
        # самое короткое имя: оно почти всегда и есть основная программа.
        same = [a for a, sc in scored
                if sc >= 45 and _skeleton(a["name"]) == _skeleton(best["name"])]
        if len(same) > 1:
            best = min(same, key=lambda a: len(a["name"]))
            msg = _start(best)
            return (msg + " (нашла несколько подписей одной программы — "
                    "взяла основную)")
        if bs >= 45 and bs - second >= 20:
            msg = _start(best)
            others = [h["name"] for h, _s in scored[1:4]]
            if others:
                msg += " Похожие, если промахнулась: " + ", ".join(others) + "."
            return msg

    # 3. ШИРОКИЙ ЗАХОД И ВОПРОС
    cands, seen = [], set()
    for a, s in scored[:4]:
        cands.append({"name": a["name"], "path": a["path"], "score": s})
        seen.add(_norm(a["name"]))
    for it, s in _wide_hits(q):
        if _norm(it["name"]) in seen:
            continue
        seen.add(_norm(it["name"]))
        cands.append({"name": it["name"], "path": it["path"], "score": s})
    # 3б. ПОИСК ПО ДИСКАМ (2026-08-14). Если ни «Пуск», ни реестр, ни
    # запущенные процессы ничего не дали — идём смотреть туда, где программы
    # и игры лежат физически: Program Files, библиотеки Steam/Epic/HoYoPlay
    # на всех дисках, папки «games»/«игры». Медленно ровно один раз: найденное
    # тут же уходит в память, и следующий запрос уже мгновенный.
    if not cands:
        try:
            from server import app_finder
            deep = app_finder.search(q)
            if deep:
                log.info("Поиск по дискам нашёл для «%s»: %s", q,
                         ", ".join(d["name"] for d in deep))
                cands = deep
        except Exception as e:
            log.debug("поиск по дискам не вышел: %s", e)
    cands.sort(key=lambda c: -c["score"])
    if not cands:
        # ПОДСМАТРИВАНИЕ (2026-07-29): не знаю — так покажи. Две минуты
        # следим, что человек запустит руками, и запоминаем навсегда.
        if mem:
            try:
                mem.watch(q)
            except Exception as e:
                log.debug("вотчер не встал: %s", e)
        return (f"Не нашла «{q}»: смотрела в «Пуске», в реестре, среди "
                f"запущенных программ и по дискам (Program Files, "
                f"библиотеки Steam/Epic/HoYoPlay, папки с играми). "
                f"Запусти её сам ПРЯМО СЕЙЧАС — я две "
                "минуты смотрю за системой, увижу, что это за программа, и "
                "запомню навсегда. Или скажи мне путь к ней — тоже запомню.")
    if not mem:
        return _start(cands[0])
    return mem.offer(q, cands[:4])


# ──────────────────────────────── окна ────────────────────────────────
def _win32():
    import ctypes
    from ctypes import wintypes
    return ctypes, wintypes, ctypes.windll.user32


def _mon_info() -> list:
    """Мониторы С НОМЕРАМИ САМОЙ WINDOWS (2026-07-29, вопрос владельца в
    живом тесте: «они не понимают, какой первый экран, какой второй?»).

    Раньше нумеровали по положению: левый верхний = первый. Но человек
    называет экраны так, как их подписывает Windows в настройках дисплея
    (кнопка «Определить» рисует цифру на весь экран) — и если главный
    монитор стоит справа, наши номера расходились с его. Теперь номер
    берём из имени устройства (\\.\\DISPLAY2 -> 2): это ровно те цифры,
    которые Windows показывает человеку. Возвращает по одному словарю на
    монитор: num, rect (весь экран), work (без панели задач), primary."""
    if not _IS_WIN:
        return []
    ctypes, wintypes, user32 = _win32()
    out = []

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                    ("szDevice", ctypes.c_wchar * 32)]

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.POINTER(wintypes.RECT), ctypes.c_double)

    def cb(hmon, hdc, lprc, data):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            return 1
        m = re.search(r"(\d+)$", mi.szDevice or "")
        r, wk = mi.rcMonitor, mi.rcWork
        out.append({"num": int(m.group(1)) if m else len(out) + 1,
                    "rect": (r.left, r.top, r.right, r.bottom),
                    "work": (wk.left, wk.top, wk.right, wk.bottom),
                    "primary": bool(mi.dwFlags & 1)})
        return 1

    try:
        user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(cb), 0)
    except Exception as e:
        log.debug("мониторы не перечислились: %s", e)
    out.sort(key=lambda d: d["num"])
    return out


def _monitors() -> list:
    """Прямоугольники мониторов в порядке номеров Windows — чтобы сказать,
    на каком экране висит окно. Владелец просил именно это: «понимала, что
    на первом экране, что на втором»."""
    return [d["rect"] for d in _mon_info()]


def _monitor_of(rect, mons) -> int:
    """Номер экрана, на котором центр окна. mons — список прямоугольников
    в порядке _mon_info(); возвращается НОМЕР WINDOWS, не позиция в списке
    (они совпадают почти всегда, но DISPLAY1+DISPLAY3 тоже бывает)."""
    cx = (rect[0] + rect[2]) // 2
    cy = (rect[1] + rect[3]) // 2
    info = _mon_info()
    for d in info:
        m = d["rect"]
        if m[0] <= cx < m[2] and m[1] <= cy < m[3]:
            return d["num"]
    # окно целиком за краями (бывает у свёрнутых) — считаем по ближайшему
    for i, m in enumerate(mons):
        if m[0] <= cx < m[2] and m[1] <= cy < m[3]:
            return i + 1
    return 0


def windows(include_minimized=True) -> list:
    """Видимые окна с заголовком: чей процесс, на каком мониторе, свёрнуто ли."""
    if not _IS_WIN:
        return []
    ctypes, wintypes, user32 = _win32()
    mons = _monitors()
    out = []

    ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p,
                                  ctypes.c_void_p)

    def cb(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value.strip()
            if not title:
                return True
            # служебные окна оболочки — не то, что человек называет «окном»
            if title in ("Program Manager", "Windows Input Experience",
                         "Настройки", "搜索"):
                return True
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            rect = (r.left, r.top, r.right, r.bottom)
            mini = bool(user32.IsIconic(hwnd))
            if mini and not include_minimized:
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc = ""
            try:
                import psutil
                proc = psutil.Process(pid.value).name()
            except Exception:
                pass
            out.append({"hwnd": int(hwnd), "title": title, "proc": proc,
                        "pid": int(pid.value), "minimized": mini,
                        # окна от администратора нам не подчиняются — знать
                        # об этом надо ЗАРАНЕЕ, иначе модель будет долбиться
                        # в них раз за разом (живой случай с диспетчером
                        # задач: три захода подряд и три «готово»)
                        "admin": _elevated(int(pid.value)),
                        "monitor": 0 if mini else _monitor_of(rect, mons),
                        "w": rect[2] - rect[0], "h": rect[3] - rect[1]})
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(ENUMPROC(cb), 0)
    except Exception as e:
        log.warning("не смогла перечислить окна: %s", e)
    # крупные и не свёрнутые — выше: обычно про них и спрашивают
    out.sort(key=lambda w: (w["minimized"], -(w["w"] * w["h"])))
    return out


def screen_map() -> str:
    """Текстовая карта рабочего стола для промпта. Дешевле картинки на
    порядок и не жрёт зрение: модель понимает расклад по словам, а кадр
    берёт только если действительно надо посмотреть глазами."""
    ws = windows()
    if not ws:
        return "Окон не видно."
    mons = _monitors()
    lines = [f"Мониторов: {len(mons) or 1}."]
    by = {}
    for w in ws:
        by.setdefault(w["monitor"], []).append(w)
    for m in sorted(k for k in by if k):
        items = by[m][:8]
        lines.append(f"Экран {m}: " + "; ".join(
            f"{w['title'][:60]}" + (f" ({w['proc']})" if w["proc"] else "")
            + (" [от администратора — сворачивать и закрывать НЕЛЬЗЯ]"
               if w.get("admin") else "")
            for w in items))
    mini = by.get(0, [])
    if mini:
        lines.append("Свёрнуто: " + "; ".join(w["title"][:40]
                                              for w in mini[:8]))
    if any(w.get("admin") for w in ws):
        lines.append("Окна с пометкой «от администратора» я тронуть не могу: "
                     "Windows не даёт обычной программе командовать ими. "
                     "Не пытайся — скажи об этом человеку сразу.")
    return "\n".join(lines)


# ИНСТИНКТ САМОСОХРАНЕНИЯ (2026-07-28, реальный инцидент). Гость попросил
# «закрой всё» — Сайка честно закрыла и СВОЁ окно: консоль сервера и вкладку
# собственного интерфейса. WM_CLOSE консоли = смерть процесса, она
# «минуснула сама себя» посреди разговора. Живое существо не отрезает себе
# голову, выполняя просьбу прибраться: свои жизненно важные окна — не цель
# для window_close/kill. Явное «выключись» при этом работает как и раньше —
# для этого есть shutdown_self с собственным предохранителем и прощанием.
import os as _os


def _is_self_window(w: dict) -> bool:
    """Окно, без которого Сайка умрёт или ослепнет: её собственная консоль
    (тот же PID, что у сервера, или родительский cmd из start.bat) и
    вкладка/окно её интерфейса (порт 8765 в заголовке)."""
    try:
        if int(w.get("pid", 0)) == _os.getpid():
            return True
    except Exception:
        pass
    title = (w.get("title") or "").lower()
    proc = (w.get("proc") or "").lower()
    # окно её веб-интерфейса: заголовок вкладки содержит адрес или имя
    if "127.0.0.1:8765" in title or "сайка —" in title \
            or title.startswith("сайка"):
        return True
    # КОНСОЛЬ — ТОЛЬКО НАСТОЯЩАЯ (2026-07-29). Было «saika в заголовке» —
    # и под это правило попадало любое окно проводника, открытое на папке
    # C:\Saika, и любой файл с «saika» в имени. Свои окна из-за этого
    # переставали слушаться команд без всякой причины. Консоль опознаём по
    # процессу, а не по слову в заголовке.
    if proc in ("cmd.exe", "conhost.exe", "windowsterminal.exe",
                "powershell.exe") and ("saika" in title or "start.bat" in title):
        return True
    return False


# РУССКИЕ ИМЕНА ПРОГРАММ (2026-07-28, реальный случай). «Разверни
# проводник» не находило окно: заголовок окна проводника — имя ПАПКИ
# («Saika», «Загрузки»), а процесс — explorer.exe; слова «проводник» нет
# нигде. Голосом говорят по-русски — переводим на имена процессов.
_APP_ALIASES = {
    "проводник": "explorer", "папка": "explorer",
    "хром": "chrome", "гугл хром": "chrome", "браузер": "chrome",
    "блокнот": "notepad", "калькулятор": "calc",
    "телеграм": "telegram", "телега": "telegram",
    "диспетчер": "taskmgr", "диспетчер задач": "taskmgr",
    "корзина": "explorer",
}


def _aliases() -> dict:
    """Встроенные алиасы + пользовательские из config (pc.window_aliases).
    Практика Talon: имена приложений переопределяются человеком под себя
    («running list» + CSV-оверрайды). У нас — словарь в конфиге:
        "pc": {"window_aliases": {"корел": "coreldraw", "тг": "telegram"}}
    """
    out = dict(_APP_ALIASES)
    try:
        from server.config import CFG as _c
        for k, v in (_c.get("pc.window_aliases", {}) or {}).items():
            out[str(k).lower().strip()] = str(v).lower().strip()
    except Exception:
        pass
    return out


# ПАМЯТЬ НА ПОСЛЕДНЕЕ ОКНО (2026-07-29, живой диалог: «сверни код
# приложения» -> свернула -> «открой это же окно» -> «какое окно ты имеешь
# в виду?». Она сама только что его трогала — и не помнила. Человек в
# разговоре ссылается местоимением, это нормальная речь, а не загадка).
_last_target: dict = {"title": "", "ts": 0.0}


def _touch(w: dict):
    try:
        _last_target.update(title=w.get("title", ""), ts=time.time())
    except Exception:
        pass


_ANAPHORA = re.compile(
    r"^(это|то|его|её|ее|же|обратно|сам\w*|котор\w*|окно|окна|приложени\w*|"
    r"программ\w*|верни|снова|опять|\s)+$", re.I)


# командные обёртки, которые модель иногда приносит вместе с именем окна
_CMD_HEAD = re.compile(
    r"\b(?:сайка|открой|открыть|запусти|покажи|переключись|переключи|"
    r"поставь|перенеси|сделай|разверни|сверни|закрой|найди|поищи|"
    r"пожалуйста|мне|на|в|во|к|с|со|для|из|автора|канал|сайт|окно|"
    r"программу|приложение)\b", re.I)


def _match(query: str):
    """Найти окно по куску заголовка или имени процесса (+русские алиасы).
    «Это же окно», «его», «обратно» — окно, с которым работали последней."""
    q = (query or "").strip().lower()
    # ЦЕЛАЯ ФРАЗА ВМЕСТО ИМЕНИ (2026-08-13, живой промах: модель прислала
    # match="Открой на YouTube автора Snail Kick." и получила «не нашла
    # окно "Открой на YouTube…"» — ответ, который человеку ничего не
    # объясняет). Срезаем командные глаголы и предлоги: если после этого
    # остаётся вменяемое имя — ищем по нему, если нет — честно говорим,
    # что имени в просьбе не было.
    # служебные слова («окно», «программу», «на», «в») в имени не нужны
    # НИКОГДА (2026-08-14: match='окно Discorder' -> «окно Discorder найти
    # не удалось»). Раньше срез включался только с трёх слов и такие пары
    # проходили мимо.
    if len(q.split()) > 1:
        cut = _CMD_HEAD.sub("", q).strip(" ,.!?-")
        if cut and len(cut.split()) <= 4:
            q = " ".join(cut.split())
    if not q:
        return None
    ws = windows()

    # местоимение вместо названия -> последнее окно, которое трогали
    if _last_target["title"] and time.time() - _last_target["ts"] < 600 \
            and _ANAPHORA.fullmatch(q):
        lt = _last_target["title"].lower()
        for w in ws:
            if w["title"].lower() == lt:
                return w
        # окно могло сменить заголовок (браузер) — берём по началу
        for w in ws:
            if w["title"].lower()[:20] == lt[:20]:
                return w

    # ЧУЖИЕ ОКНА ВПЕРЁД (2026-07-29, живой промах: «перенеси хром» двигало
    # «Сайка — Google Chrome», её собственную вкладку — она крупнее всех и
    # стояла первой в списке). Когда человек называет браузер, он имеет в
    # виду СВОЁ окно, не окно Сайки; её вкладка — только если больше некому.
    def pick(cands):
        if not cands:
            return None
        other = [c for c in cands if not _is_self_window(c)]
        return (other or cands)[0]

    w = pick([w for w in ws if q in w["title"].lower()])
    if w:                              # точное вхождение в заголовок
        return w
    w = pick([w for w in ws if q in (w["proc"] or "").lower()])
    if w:                              # иначе по имени процесса
        return w
    # СПЕЦ-ВЕТКИ ДО АЛИАСОВ: у алиасов «папка -> explorer» жадный захват,
    # и «рабочая папка» уезжала в ПЕРВОЕ окно проводника (стенд поймал)

    # «ОКНО, ГДЕ ДИСК Ц» (2026-07-29, живой промах: «закрой окно, где диск
    # Ц» закрыло ДИСПЕТЧЕР ЗАДАЧ — нечёткое сравнение наскребло 28 баллов
    # на «дispetcher», а настоящее окно зовётся «System (C:)» и по-русски
    # не матчится вообще). Буквы дисков говорят по-русски — переводим и
    # ищем «(C:)» в заголовке проводника.
    _dm = re.search(r"диск\w*\s+([а-яa-z])", q)
    if _dm:
        _lat = {"ц": "c", "с": "c", "д": "d", "е": "e", "ф": "f", "ж": "g",
                "г": "g", "х": "h", "и": "i", "й": "j", "к": "k", "л": "l"}
        letter = _lat.get(_dm.group(1), _dm.group(1))
        w = pick([w for w in ws
                  if f"({letter.upper()}:)" in w["title"]
                  or w["title"].lower().startswith(letter + ":")])
        if w:
            return w

    # «РАБОЧАЯ ПАПКА» — окно проводника с рабочей директорией (files.roots)
    if "рабоч" in q and ("папк" in q or "директор" in q):
        try:
            from server import file_hands
            for r in file_hands.roots():
                nm = Path(r).name.lower()
                w = pick([w for w in ws if nm in w["title"].lower()])
                if w:
                    return w
        except Exception:
            pass

    _al = _aliases()
    alias = _al.get(q) or next((v for k, v in _al.items() if k in q), "")
    if alias:
        w = pick([w for w in ws
                  if alias in (w["proc"] or "").lower()
                  or alias in w["title"].lower()])
        if w:
            return w
    # НЕЧЁТКО — как и с программами: «Coral Draft» должно находить окно
    # CorelDRAW. Берём лучшее совпадение по заголовку или процессу и только
    # если оно уверенное: ошибиться окном хуже, чем не найти.
    best, bs = None, 0
    for w in ws:
        sc = max(_score(w["title"], q), _score(w["proc"] or "", q))
        if sc > bs:
            best, bs = w, sc
    # порог поднят 25 -> 34 (2026-07-29): на 28 баллах «диск ц» дотянулось
    # до «Диспетчер задач», и ЗАКРЫЛОСЬ чужое окно. Слабая догадка не
    # оправдывает действие над чужим окном — лучше честное «не нашла».
    if best is not None and bs >= 34:
        return best
    return None


_elev_cache: dict = {}


def _elevated(pid: int) -> bool:
    """Запущен ли процесс с правами администратора.

    Windows защищает такие окна от чужих команд (UIPI): обычная программа
    физически не может свернуть или закрыть окно процесса, поднятого выше
    себя по правам. ShowWindow при этом НЕ ругается — просто молча ничего
    не делает. Проверяем косвенно: у поднятого процесса нам не дадут даже
    прочитать путь к исполняемому файлу.
    """
    # список окон перечитывается часто, а права процесса не меняются —
    # держим ответ до его завершения
    if pid in _elev_cache:
        return _elev_cache[pid]
    try:
        import psutil
        psutil.Process(pid).exe()
        out = False
    except Exception as e:
        out = type(e).__name__ == "AccessDenied"
    if len(_elev_cache) > 400:
        _elev_cache.clear()
    _elev_cache[pid] = out
    return out


def _verify(hwnd, want: str) -> bool:
    """Действительно ли окно оказалось в нужном состоянии."""
    if not _IS_WIN:
        return True
    ctypes, _wt, user32 = _win32()
    time.sleep(0.12)                # окну нужен кадр, чтобы перерисоваться
    try:
        if want == "min":
            return bool(user32.IsIconic(hwnd))
        if want == "max":
            return bool(user32.IsZoomed(hwnd))
        if want == "gone":
            return not bool(user32.IsWindow(hwnd))
        if want == "front":
            return int(user32.GetForegroundWindow()) == int(hwnd)
        if want == "normal":
            return not (user32.IsIconic(hwnd) or user32.IsZoomed(hwnd))
    except Exception:
        pass
    return True


def _blocked_note(w: dict, verb: str) -> str:
    """Честное объяснение, почему не вышло. Раньше здесь врали «готово» —
    и владелец справедливо ловил на этом (живой случай с диспетчером
    задач 2026-07-26)."""
    if _elevated(w.get("pid", 0)):
        return (f"Не смогла {verb} «{w['title'][:50]}»: это окно запущено от "
                "администратора, а я — нет. Windows не даёт обычной "
                "программе командовать поднятыми окнами. Сделай это сам или "
                "запусти меня от администратора.")
    return (f"Не смогла {verb} «{w['title'][:50]}» — окно не послушалось. "
            "Бывает у полноэкранных игр и окон, которые держат себя "
            "поверх остальных.")


def window_minimize(query: str) -> str:
    w = _match(query)
    if not w:
        return f"Не нашла окно «{query}»."
    _touch(w)   # помним: «это же окно» — про него
    _, _, user32 = _win32()
    user32.ShowWindow(w["hwnd"], 6)                # SW_MINIMIZE
    if not _verify(w["hwnd"], "min"):
        return _blocked_note(w, "свернуть")
    return f"Свернула «{w['title'][:60]}»."


# С ЧЕМ РАБОТАЛИ ПОСЛЕДНИМ (2026-08-13, живой мат владельца: «подними его
# повыше, я из-за браузера его не вижу» — и в ответ «я не могу поднять
# что-то, о чём ничего не знаю, уточни, что ты имеешь в виду под "его"».
# Проводник она открыла СЕКУНДОЙ РАНЬШЕ. Человек говорит местоимениями,
# как со всеми — предмет живёт в разговоре, а не в каждой фразе.)
LAST_APP = {"name": "", "ts": 0.0}

_PRONOUN = re.compile(
    r"^\W*(?:его|её|ее|их|это|этого|эту|этот|ту|тот|там|окно|окошко|"
    r"программу|прогу|приложение)"
    # хвост вроде «повыше», «вперёд», «наверх» — это КУДА, а не ЧТО:
    # предмет всё равно остаётся местоимением («подними его повыше»)
    r"(?:\s+(?:повыше|выше|вперёд|вперед|наверх|сюда|обратно|назад|"
    r"поближе|нормально|полностью))*\W*$", re.I)


def remember_app(name: str):
    if name and len(name) > 1:
        LAST_APP.update(name=str(name), ts=time.time())


def _resolve_pronoun(query: str) -> str:
    q = (query or "").strip()
    if not q or not _PRONOUN.match(q):
        return q
    if LAST_APP["name"] and time.time() - LAST_APP["ts"] < 900:
        log.info("«%s» -> последнее, с чем работали: %s", q, LAST_APP["name"])
        return LAST_APP["name"]
    return q


_PRON_ONLY = re.compile(r"(его|её|ее|их|это|этот|эту|тот|та|то|он|она|"
                        r"окно|программу|приложение)\s*")


def _force_front(hwnd) -> bool:
    """ВЫВЕСТИ ОКНО ВПЕРЁД ПО-НАСТОЯЩЕМУ (2026-08-14).

    Голого SetForegroundWindow мало: Windows разрешает менять активное окно
    только процессу, который САМ сейчас на переднем плане, — защита от
    выпрыгивающих поверх всего окон. Сайка при этом фоновая служба, и
    честный ответ «Windows не даёт, кликни на панели задач» человеку не
    годится: он лежит на диване, кликать некому. Без фокуса же не работает
    вообще ничего дальше — ни ввод текста, ни клики, ни клавиши.

    Обходим тем же способом, которым это делают оконные менеджеры, по
    возрастанию грубости — как только окно оказалось впереди, выходим:
      1) просто попросить (вдруг мы и так активны);
      2) ALT-заглушка: системный «щелчок» снимает блокировку смены фокуса;
      3) AttachThreadInput — на секунду становимся одной очередью ввода с
         текущим передним окном, и запрет перестаёт нас касаться;
      4) SwitchToThisWindow — то же, что Alt+Tab делает руками человека.
    Ничего экзотического и никаких прав администратора."""
    if not _IS_WIN:
        return True
    ctypes, wt, user32 = _win32()
    kernel32 = ctypes.windll.kernel32

    def _front() -> bool:
        time.sleep(0.08)
        return int(user32.GetForegroundWindow()) == int(hwnd)

    user32.ShowWindow(hwnd, 9)                     # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    if _front():
        return True

    # 2) ALT вверх-вниз: система считает это вводом пользователя и снимает
    #    блокировку смены переднего окна на ближайший вызов
    try:
        user32.keybd_event(0x12, 0, 0, 0)          # VK_MENU down
        user32.keybd_event(0x12, 0, 2, 0)          # up
        user32.SetForegroundWindow(hwnd)
        if _front():
            return True
    except Exception as e:
        log.debug("alt-трюк не сработал: %s", e)

    # 3) прицепиться к очереди ввода текущего переднего окна
    try:
        cur = user32.GetForegroundWindow()
        tid_cur = user32.GetWindowThreadProcessId(cur, None)
        tid_me = kernel32.GetCurrentThreadId()
        tid_target = user32.GetWindowThreadProcessId(hwnd, None)
        for tid in {tid_cur, tid_target}:
            if tid and tid != tid_me:
                user32.AttachThreadInput(tid_me, tid, True)
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
        finally:
            for tid in {tid_cur, tid_target}:
                if tid and tid != tid_me:
                    user32.AttachThreadInput(tid_me, tid, False)
        if _front():
            return True
    except Exception as e:
        log.debug("AttachThreadInput не сработал: %s", e)

    # 4) то же, что Alt+Tab руками
    try:
        user32.SwitchToThisWindow(hwnd, True)
        if _front():
            return True
    except Exception as e:
        log.debug("SwitchToThisWindow не сработал: %s", e)
    return False


def window_focus(query: str) -> str:
    query = _resolve_pronoun(query)
    # «покажи его» — предмет берём со стола разговора, если своей памяти
    # о последнем окне не хватило (2026-08-14)
    if query and _PRON_ONLY.fullmatch(query.strip().lower()):
        try:
            from server import focus as _focus
            _subj = _focus.subject()
            if _subj:
                query = _subj
        except Exception:
            pass
    w = _match(query)
    if not w:
        return f"Не нашла окно «{query}»."
    _touch(w)   # помним: «это же окно» — про него
    if _force_front(w["hwnd"]):
        return f"Показала «{w['title'][:60]}» — оно теперь впереди."
    if _elevated(w.get("pid", 0)):
        return (f"«{w['title'][:50]}» запущено от администратора, а я нет — "
                "Windows не даёт мне командовать такими окнами. Запусти "
                "меня от администратора, и смогу.")
    return (f"«{w['title'][:50]}» не вышло вывести вперёд даже в обход — "
            "так себя ведут полноэкранные игры и окна поверх всех. "
            "Скажи это человеку честно, не делай вид, что получилось.")


def window_maximize(query: str = "", full: bool = False) -> str:
    """Развернуть окно. Просьба владельца: «развернуть на полный экран не
    могла». Без query берём то окно, что сейчас впереди — «разверни это»
    произносится куда чаще, чем «разверни блокнот»."""
    w = _match(query) if query else _foreground()
    if not w:
        return f"Не нашла окно «{query}»." if query else "Не вижу активного окна."
    _touch(w)   # помним: «это же окно» — про него
    _, _, user32 = _win32()
    user32.ShowWindow(w["hwnd"], 3)                # SW_MAXIMIZE
    _force_front(w["hwnd"])   # F11 ниже уйдёт в АКТИВНОЕ окно — оно нужно
    if not _verify(w["hwnd"], "max"):
        return _blocked_note(w, "развернуть")
    if full:
        # Настоящий полноэкранный режим — это внутреннее дело программы
        # (у браузеров и плееров это F11), снаружи его не включить.
        # Разворачиваем и жмём F11 в активное окно.
        try:
            import keyboard
            keyboard.send("f11")
        except Exception:
            return (f"Развернула «{w['title'][:60]}». Полный экран без "
                    "модуля keyboard не переключу — нажми F11 сам.")
    return ("Развернула «" + w["title"][:60] + "»"
            + (" на полный экран." if full else "."))


def window_restore(query: str = "") -> str:
    """Вернуть окно из развёрнутого в обычный размер."""
    w = _match(query) if query else _foreground()
    if not w:
        return "Не нашла такое окно."
    _touch(w)   # помним: «это же окно» — про него
    _, _, user32 = _win32()
    user32.ShowWindow(w["hwnd"], 9)                # SW_RESTORE
    if not _verify(w["hwnd"], "normal"):
        return _blocked_note(w, "вернуть в обычный размер")
    return f"Вернула «{w['title'][:60]}» в обычный размер."


def _foreground():
    """Окно, которое сейчас впереди."""
    if not _IS_WIN:
        return None
    _, _, user32 = _win32()
    try:
        h = int(user32.GetForegroundWindow())
    except Exception:
        return None
    for w in windows(include_minimized=False):
        if w["hwnd"] == h:
            return w
    return None


def window_close(query: str) -> str:
    """WM_CLOSE — вежливая просьба закрыться. Программа успеет спросить про
    несохранённое; принудительно ничего не снимаем (это system_control.kill,
    и он требует подтверждения)."""
    w = _match(query)
    if not w:
        return f"Не нашла окно «{query}»."
    _touch(w)   # помним: «это же окно» — про него
    if _is_self_window(w):
        return ("отказ: это моё собственное окно — закрыв его, я умру "
                "посреди разговора. Если нужно меня выключить, попроси "
                "прямо: «выключись» — я попрощаюсь и выйду сама.")
    _, _, user32 = _win32()
    user32.PostMessageW(w["hwnd"], 0x0010, 0, 0)   # WM_CLOSE
    if _elevated(w.get("pid", 0)) and not _verify(w["hwnd"], "gone"):
        return _blocked_note(w, "закрыть")
    # САМА ПРОВЕРЯЕТ РЕЗУЛЬТАТ (2026-07-28, просьба владельца). Раньше ответ
    # был «попросила закрыться» — и она искренне считала дело сделанным,
    # пока человек видел живое окно (реальный случай: VPN ушёл в трей и
    # проигнорировал просьбу). Секунду ждём и смотрим правде в глаза.
    time.sleep(1.2)
    try:
        gone = (not user32.IsWindow(w["hwnd"])
                or not user32.IsWindowVisible(w["hwnd"]))
    except Exception:
        gone = True
    if gone:
        return (f"Закрыла «{w['title'][:60]}» — проверила, окна на экране "
                "больше нет.")
    return (f"Попросила «{w['title'][:60]}» закрыться, но окно ВСЁ ЕЩЁ на "
            "экране — проверила сама. Либо оно спрашивает про несохранённое, "
            "либо игнорирует просьбы (VPN и трей-программы так любят). "
            "Скажи это человеку честно; жёстко снять можно только по его "
            "прямой просьбе — «убей процесс такой-то».")


def minimize_all(keep: str = "") -> str:
    """Свернуть всё, кроме названного. Просьба владельца: «что можно
    свернуть, пока работаем»."""
    _, _, user32 = _win32()
    k = (keep or "").strip().lower()
    done, stuck = [], []
    # СВОИ ОКНА ТОЖЕ СВОРАЧИВАЕМ (2026-07-29, владелец: «когда говорю
    # свернуть окна, она не сворачивает себя, браузер остаётся»). Раньше
    # они исключались «чтобы Сайка не ослепла» — но свернуть не значит
    # закрыть: сервер живёт, вебсокет держится, окно поднимается одним
    # кликом. Просьба «сверни всё» означает ровно всё, иначе стол не
    # чистый и человек доделывает руками. Правило теперь такое: СВОРАЧИВАТЬ
    # можно всё, ЗАКРЫВАТЬ себя нельзя (см. window_close).
    # …НО ТОЛЬКО ТЕ, КОТОРЫЕ ЧЕЛОВЕК СМОЖЕТ ВЕРНУТЬ (2026-08-14, владелец:
    # «после сворачивания её окно не смогло нормально развернуться»). Окно
    # модели на столе сделано без строки в панели задач (Qt.Tool) — это
    # правильно, она не программа, с которой переключаются. Но у свёрнутого
    # окна без строки в панели задач НЕТ НИ ОДНОГО способа вернуться:
    # ни кликом, ни Alt+Tab, ни «развернуть всё». Оно просто исчезает.
    # Правило общее, а не про аватар: чего человек не может достать
    # обратно — того мы и не прячем.
    WS_EX_TOOLWINDOW = 0x00000080
    GWL_EXSTYLE = -20

    def _has_taskbar_button(hwnd) -> bool:
        try:
            gwl = getattr(user32, "GetWindowLongPtrW", None) or \
                user32.GetWindowLongW
            return not (int(gwl(hwnd, GWL_EXSTYLE)) & WS_EX_TOOLWINDOW)
        except Exception:
            return True            # не смогли узнать — считаем обычным

    todo = [w for w in windows(include_minimized=False)
            if not (k and (k in w["title"].lower()
                           or k in (w["proc"] or "").lower()))
            and _has_taskbar_button(w["hwnd"])]
    for w in todo:
        try:
            user32.ShowWindow(w["hwnd"], 6)
        except Exception:
            pass
    time.sleep(0.15)                      # один общий кадр на все окна
    elevated_stuck = 0
    for w in todo:
        try:
            if user32.IsIconic(w["hwnd"]):
                done.append(w["title"][:40])
            else:
                # Диспетчер задач и прочие окна «от администратора» Windows
                # защищает от команд обычного процесса (UIPI): ShowWindow
                # молча не срабатывает. Это не наша поломка — говорим прямо.
                if _elevated(w.get("pid", 0)):
                    elevated_stuck += 1
                    stuck.append(w["title"][:40] + " (админ)")
                else:
                    stuck.append(w["title"][:40])
        except Exception:
            stuck.append(w["title"][:40])
    if not done and not stuck:
        return "Сворачивать было нечего."
    msg = (f"Свернула {len(done)}: " + ", ".join(done[:6])
           + ("…" if len(done) > 6 else "")) if done else "Ничего не свернулось."
    if stuck:
        msg += ". Не поддались: " + ", ".join(stuck[:4])
        if elevated_stuck:
            msg += (" — окна с пометкой (админ) Windows защищает от обычных "
                    "программ. start.bat при запуске просит права "
                    "администратора — согласись в окне UAC, и я смогу "
                    "командовать и ими.")
        else:
            msg += " — обычно это полноэкранные игры."
    return msg


def restore_all() -> str:
    """РАЗВЕРНУТЬ ВСЁ СВЁРНУТОЕ (2026-07-29, живой тупик: «открой все окна»
    -> у неё был только window_restore ПО ОДНОМУ, она честно вызывала его с
    «для всех активных окон» и получала «не нашла такое окно». Обратная
    операция к minimize_all обязана существовать: свернула всё — верни всё."""
    if not _IS_WIN:
        return "Окна есть только в Windows."
    _, _, user32 = _win32()
    done = []
    for w in windows(include_minimized=True):
        if not w.get("minimized"):
            continue
        try:
            user32.ShowWindow(w["hwnd"], 9)        # SW_RESTORE
            done.append(w["title"][:40])
        except Exception:
            pass
    if not done:
        return "Свёрнутых окон нет — разворачивать нечего."
    return (f"Развернула {len(done)}: " + ", ".join(done[:6])
            + ("…" if len(done) > 6 else "") + ".")


def window_place(query: str, position: str = "center",
                 width: int = 0, height: int = 0, monitor: int = 0) -> str:
    """РАССТАВИТЬ ОКНО (2026-07-28, просьба владельца): «по центру», «слева»,
    «в правый нижний угол», опционально с размером в процентах экрана.
    monitor (2026-07-29): «на втором экране» = monitor=2 — позиции тогда
    считаются от рабочей области ВТОРОГО монитора. -1 = «на другой экран»
    (противоположный тому, где окно сейчас). 0 = где окно сейчас.
    Рабочая область берётся без панели задач — окно не залезает под панель.
    Своё окно двигать можно — это не закрытие."""
    # без имени — двигаем АКТИВНОЕ окно: «перенеси на второй экран» сразу
    # после разговора про хром означает «его же», а не «ничего» (живой
    # промах 2026-07-29: пустой match -> «Не нашла окно „"»)
    w = _match(query) if (query or "").strip() else _foreground()
    if not w:
        return (f"Не нашла окно «{query}»." if (query or "").strip()
                else "Не вижу активного окна — назови кусок заголовка.")
    _touch(w)   # помним: «это же окно» — про него
    import ctypes
    _, _, user32 = _win32()
    if _elevated(w.get("pid", 0)):
        return _blocked_note(w, "двигать")

    class RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                    ("r", ctypes.c_long), ("b", ctypes.c_long)]
    # ЭКРАНЫ (2026-07-29, живой провал: «открой проводник на втором экране»
    # — а позиции считались только от главного). Номера — те же, что Windows
    # показывает кнопкой «Определить» в настройках дисплея: человек называет
    # экраны именно этими цифрами.
    info = _mon_info()
    mon = int(monitor or 0)
    by_num = {d["num"]: d for d in info}
    if mon == -1:
        # «на другой экран»: противоположный тому, где окно сейчас
        if len(info) < 2:
            return "Вижу только один экран — переносить некуда."
        cur0 = RECT()
        user32.GetWindowRect(w["hwnd"], ctypes.byref(cur0))
        here = _monitor_of((cur0.l, cur0.t, cur0.r, cur0.b),
                           [d["rect"] for d in info])
        mon = next((d["num"] for d in info if d["num"] != here),
                   info[0]["num"])
    if mon and mon not in by_num:
        have = ", ".join(str(d["num"]) for d in info) or "ни одного"
        return (f"Такого экрана нет. Windows знает экраны: {have} "
                "(это те же цифры, что в настройках дисплея по кнопке "
                "«Определить»). Проверь, подключён ли монитор.")
    if mon:
        al, at, ar, ab = by_num[mon]["work"]
    elif info:
        # экран не назван — остаёмся на том, где окно живёт сейчас,
        # а не тащим его молча на главный
        cur0 = RECT()
        user32.GetWindowRect(w["hwnd"], ctypes.byref(cur0))
        ci = _monitor_of((cur0.l, cur0.t, cur0.r, cur0.b),
                         [d["rect"] for d in info])
        al, at, ar, ab = (by_num.get(ci) or info[0])["work"]
    else:
        ra0 = RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0,
                                                   ctypes.byref(ra0), 0)
        al, at, ar, ab = ra0.l, ra0.t, ra0.r, ra0.b

    class _Area:                            # прежние имена, чтобы ниже не менять
        l, t, r, b = al, at, ar, ab
    ra = _Area()
    sw, sh = ra.r - ra.l, ra.b - ra.t

    # СНАП ПО-ВИНДОВОМУ (2026-08-13, живой промах: «Google Chrome слева,
    # как бы в половину экрана» -> модель прислала только width=50, и высота
    # осталась прежней — окно легло слева огрызком). Когда человек говорит
    # «слева», он имеет в виду Win+← : половина по ширине и ВСЯ высота.
    # Достраиваем недостающее измерение сами, а не ждём от модели полноты.
    _pos0 = (position or "center").strip().lower()
    if width and not height and _pos0 in (
            "left", "right", "лево", "слева", "право", "справа"):
        height = 100
    if height and not width and _pos0 in (
            "top", "bottom", "верх", "сверху", "низ", "снизу"):
        width = 100

    # размер: проценты экрана; 0 = не менять текущий
    cur = RECT()
    user32.GetWindowRect(w["hwnd"], ctypes.byref(cur))
    ww = int(sw * max(10, min(100, width)) / 100) if width else cur.r - cur.l
    wh = int(sh * max(10, min(100, height)) / 100) if height else cur.b - cur.t
    ww, wh = min(ww, sw), min(wh, sh)

    pos = (position or "center").strip().lower()
    # русские и английские имена позиций — голосом говорят по-русски
    aliases = {
        "центр": "center", "по центру": "center", "середина": "center",
        "лево": "left", "слева": "left", "право": "right", "справа": "right",
        "верх": "top", "сверху": "top", "низ": "bottom", "снизу": "bottom",
        "левый верхний": "topleft", "правый верхний": "topright",
        "левый нижний": "bottomleft", "правый нижний": "bottomright",
    }
    pos = aliases.get(pos, pos)
    cx, cy = ra.l + (sw - ww) // 2, ra.t + (sh - wh) // 2
    coords = {
        "center":      (cx, cy),
        "left":        (ra.l, cy),
        "right":       (ra.r - ww, cy),
        "top":         (cx, ra.t),
        "bottom":      (cx, ra.b - wh),
        "topleft":     (ra.l, ra.t),
        "topright":    (ra.r - ww, ra.t),
        "bottomleft":  (ra.l, ra.b - wh),
        "bottomright": (ra.r - ww, ra.b - wh),
    }
    if pos not in coords:
        return (f"не знаю позицию «{position}» — умею: центр, слева, справа, "
                "сверху, снизу и четыре угла")
    x, y = coords[pos]
    user32.ShowWindow(w["hwnd"], 9)            # SW_RESTORE: из свёрнутого
    if not user32.SetWindowPos(w["hwnd"], 0, x, y, ww, wh, 0x0004 | 0x0010):
        return _blocked_note(w, "двигать")
    # проверяем, куда окно встало НА САМОМ ДЕЛЕ — «поставила на второй
    # экран», когда окно на первом, ровно то враньё, с которого начался
    # этот фикс
    where = ""
    try:
        fin = RECT()
        user32.GetWindowRect(w["hwnd"], ctypes.byref(fin))
        got = _monitor_of((fin.l, fin.t, fin.r, fin.b),
                          [d["rect"] for d in info])
        if mon and got and got != mon:
            return (f"Двигала «{w['title'][:50]}» на экран {mon}, но окно "
                    f"оказалось на экране {got} — оно сопротивляется "
                    "(бывает у программ, которые сами помнят своё место). "
                    "Скажи человеку как есть.")
        if got:
            where = f" на экране {got}"
    except Exception:
        pass
    # ЧЕСТНЫЙ ОТЧЁТ (2026-08-13): здесь стояло max(10, …) и для height=0
    # рапортовалось «10%», хотя высоту никто не трогал. Ровно тот случай,
    # за который её справедливо ловят: сказала о том, чего не делала.
    _wd = (f"{max(10, min(100, width))}% по ширине" if width
           else "ширина как была")
    _ht = (f"{max(10, min(100, height))}% по высоте" if height
           else "высота как была")
    return (f"Поставила «{w['title'][:50]}» {position}{where}"
            + (f", {_wd}, {_ht}" if (width or height) else "")
            + ".")


# ──────────────────────────────── звук ────────────────────────────────
def _pycaw_volume():
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    dev = AudioUtilities.GetSpeakers()
    iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    import comtypes
    return comtypes.cast(iface, comtypes.POINTER(IAudioEndpointVolume))


def _tap_key(vk: int, times: int = 1):
    import ctypes
    for _ in range(max(1, times)):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


def volume(percent=None, mute=None, delta=None) -> str:
    """Громкость системы. Точное значение — через pycaw; если его нет,
    работаем клавишами громкости (шаг ~2%) и говорим об этом честно."""
    if not _IS_WIN:
        return "Управление звуком есть только в Windows."
    try:
        vol = _pycaw_volume()
        if mute is not None:
            vol.SetMute(bool(mute), None)
            return "Звук выключен." if mute else "Звук включён."
        cur = round(vol.GetMasterVolumeLevelScalar() * 100)
        if delta is not None:
            percent = cur + int(delta)
        if percent is None:
            return f"Громкость {cur}%."
        percent = max(0, min(100, int(percent)))
        vol.SetMasterVolumeLevelScalar(percent / 100.0, None)
        return f"Громкость {percent}%."
    except Exception as e:
        log.debug("pycaw недоступен (%s) — работаю клавишами", e)
    VK_MUTE, VK_DOWN, VK_UP = 0xAD, 0xAE, 0xAF
    if mute is not None:
        _tap_key(VK_MUTE)
        return "Переключила звук (точное состояние без pycaw не знаю)."
    step = int(delta if delta is not None else (10 if percent is None else 0))
    if percent is not None:
        # без pycaw абсолютное значение не выставить — честно говорим
        return ("Без библиотеки pycaw умею только «громче/тише». "
                "Поставь её — тогда смогу выставлять точный процент "
                "(setup/install_pc_control.bat).")
    _tap_key(VK_UP if step > 0 else VK_DOWN, abs(step) // 2 or 1)
    return "Сделала " + ("громче." if step > 0 else "тише.")


# ───────────────────────── вкладки активного окна ─────────────────────────
# Через клавиатуру, а не через API конкретного браузера: работает в Chrome,
# Edge, Firefox и вообще везде, где есть вкладки, и не требует расширения.
# ЧЬИ ВКЛАДКИ (2026-08-13, живой инцидент: «она мне чат в Клоде
# переключила»). tab() шлёт ГЛОБАЛЬНЫЕ горячие клавиши — они летят в то
# окно, что сейчас впереди, каким бы оно ни было. Человек работал в
# десктопном Клоде, Сайка отправила Ctrl+Tab «в браузер» — и переключила
# ему чат. Ctrl+W в том же положении закрыл бы разговор.
#
# Правило теперь простое: клавиши уходят ТОЛЬКО в браузер. Есть своё окно
# Playwright — работаем в нём, там ничего чужого нет и промахнуться некуда.
# Нет своего — проверяем, что впереди действительно браузер, и только тогда
# жмём. Впереди что-то другое — честный отказ, а не слепой удар по чужому
# приложению.
_BROWSER_HINT = ("chrome", "chromium", "firefox", "edge", "opera", "yandex",
                 "brave", "vivaldi", "браузер", "— google chrome",
                 "mozilla firefox", "safari", "tor browser")


def _front_is_browser():
    """(бразуер ли впереди, заголовок). None — определить не вышло."""
    w = _foreground()
    if not w:
        return None, ""
    title = str(w.get("title") or "")
    proc = str(w.get("proc") or w.get("exe") or "")
    hay = (title + " " + proc).lower()
    return any(k in hay for k in _BROWSER_HINT), title


def _own_tab(a: str, index: int):
    """Вкладки в СВО�ём окне браузера. None — своего окна нет."""
    try:
        from server import browser_hands as bh
        if not bh.is_open():
            return None
        return bh.tabs(a, index)
    except Exception as e:
        log.debug("свои вкладки недоступны: %s", e)
        return None


def tab(action: str, index: int = 0) -> str:
    if not _IS_WIN:
        return "Управление вкладками есть только в Windows."
    a = (action or "").lower()
    own = _own_tab(a, index)
    if own is not None:
        return own
    is_br, title = _front_is_browser()
    if is_br is False:
        return (f"Впереди сейчас не браузер, а «{title}» — вкладки трогать "
                "НЕ БУДУ, иначе нажатие уйдёт в чужое приложение (уже так "
                "переключала человеку чат в другой программе). Скажи "
                "человеку, чтобы он вывел браузер вперёд, или сперва зови "
                "window_focus с именем браузера.")
    try:
        import keyboard
    except Exception:
        return ("Нет модуля keyboard — не могу нажимать клавиши. "
                "Поставь его: setup/install_pc_control.bat")
    if a in ("open", "new", "открыть"):
        keyboard.send("ctrl+t")
        return "Открыла новую вкладку."
    if a in ("close", "закрыть"):
        keyboard.send("ctrl+w")
        return "Закрыла вкладку."
    if a in ("next", "следующая"):
        keyboard.send("ctrl+tab")
        return "Перешла на следующую."
    if a in ("prev", "previous", "предыдущая"):
        keyboard.send("ctrl+shift+tab")
        return "Перешла на предыдущую."
    if a in ("go", "перейти", "switch"):
        n = int(index or 1)
        if n < 1:
            return "Номер вкладки считается с единицы."
        # Ctrl+9 в браузерах это ВСЕГДА последняя вкладка, а не девятая
        keyboard.send("ctrl+9" if n >= 9 else f"ctrl+{n}")
        return f"Перешла на вкладку {n}." if n < 9 else "Перешла на последнюю."
    if a in ("pin", "закрепить", "открепить"):
        # У закрепления нет своего сочетания ни в одном браузере — только
        # правая кнопка по вкладке. Честно говорим, а не делаем вид.
        return ("Закрепление вкладки браузеры не отдают горячей клавишей — "
                "это только правой кнопкой по вкладке. Могу открыть, "
                "закрыть, перелистнуть или перейти к нужной по номеру.")
    if a in ("move", "перенести", "переместить"):
        # Ctrl+Shift+PgUp/PgDn двигает ТЕКУЩУЮ вкладку по ленте
        n = int(index or 1)
        key = "ctrl+shift+page down" if n >= 0 else "ctrl+shift+page up"
        for _ in range(min(abs(n) or 1, 20)):
            keyboard.send(key)
        return f"Подвинула вкладку на {abs(n) or 1} позиций."
    if a in ("restore", "вернуть", "reopen"):
        keyboard.send("ctrl+shift+t")
        return "Вернула закрытую вкладку."
    return f"Не знаю действия «{action}» для вкладок."


# ──────────────────── ПОИСК ПАПОК ПО ДИСКАМ ────────────────────
# Владелец: «я ей говорю найти папку с играми на диске C, она ищет, видит
# варианты и спрашивает, какая из них — я называю, она запоминает».
# Ровно это здесь и сделано. Запомненное живёт в file_hands.places, там уже
# есть механика закладок; сюда она приходит готовой.
#
# ПОЧЕМУ ГЛУБИНА ОГРАНИЧЕНА. Полный обход диска — это минуты и сотни тысяч
# папок. Всё, что человек называет словами («игры», «проекты», «музыка»),
# лежит близко к корню: C:\Games, D:\Steam\steamapps, Документы\Проекты.
# Три уровня закрывают это, а поиск занимает секунды.
_SKIP_DIRS = {"windows", "$recycle.bin", "system volume information",
              "programdata", "appdata", "node_modules", ".git", "__pycache__",
              "temp", "tmp", "cache", "recovery", "boot"}


def drives() -> list:
    """Буквы дисков, доступных для поиска."""
    if not _IS_WIN:
        return ["/"]
    out = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        p = Path(f"{letter}:/")
        try:
            if p.exists():
                out.append(f"{letter}:")
        except OSError:
            pass
    return out


# Человек говорит по-русски, а папки на диске почти всегда по-английски.
# Живой случай: «найди папку с играми» не нашло НИЧЕГО, а «Games» нашло
# одиннадцать штук. Поэтому запрос сам разворачивается в оба языка.
_SYNONYMS = {
    "игр": ("games", "game"),
    "музык": ("music", "музыка"),
    "видео": ("video", "videos", "movies"),
    "фильм": ("movies", "films", "video"),
    "картинк": ("pictures", "images", "img"),
    "фото": ("photos", "pictures", "camera"),
    "документ": ("documents", "docs"),
    "загруз": ("downloads", "download"),
    "проект": ("projects", "project", "work"),
    "работ": ("work", "projects"),
    "рабочий стол": ("desktop",),
    "модел": ("models", "assets"),
    "текстур": ("textures", "materials"),
    "рендер": ("render", "renders", "output"),
    "скрин": ("screenshots", "screenshot"),
    "сохранен": ("saves", "saved", "savegames"),
    "музыка": ("music",),
    "книг": ("books", "library"),
    "сцен": ("scenes", "levels"),
}
# Мусорные слова, которые человек говорит, а в имени папки их нет:
# «найди папку С ИГРАМИ» — «папка» и «с» только сбивают поиск.
_STOP_WORDS = {"папка", "папку", "папке", "папки", "директория", "каталог",
               "найди", "найти", "поищи", "ищи", "где", "мою", "мои", "моя",
               "с", "со", "на", "в", "для", "по", "folder", "directory",
               "find", "the", "my"}


def _expand(query: str) -> list:
    """Слова, по которым реально стоит искать: очищенный запрос + переводы."""
    q = (query or "").strip().lower()
    words = [w for w in re.findall(r"[\w-]+", q) if w not in _STOP_WORDS]
    out = [" ".join(words)] if words else []
    for w in words:
        out.append(w)
        for stem, alts in _SYNONYMS.items():
            if w.startswith(stem) or stem.startswith(w[:5] or "\0"):
                out.extend(alts)
    # длинные варианты вперёд: точное совпадение ценнее одиночного слова
    seen, res = set(), []
    for x in out:
        x = x.strip()
        if x and len(x) > 1 and x not in seen:
            seen.add(x)
            res.append(x)
    return res[:8]


def find_folder(query: str, drive: str = "", depth: int = 3) -> list:
    """Папки, похожие на запрос. Возвращает список путей, самые «главные»
    (ближе к корню, точнее совпадение) — первыми.

    Ограничена по времени намеренно (2026-07-26: в живом диалоге обход всех
    дисков занимал 30 секунд, и человек успевал переспросить трижды). Лучше
    отдать хорошие варианты за пару секунд, чем идеальные за полминуты.
    """
    terms = _expand(query)
    if not terms:
        return []
    q = terms[0]
    deadline = time.time() + float(CFG.get("pc.find_timeout_s", 4.0))
    roots = []
    if drive:
        d = drive.strip().rstrip(":\\/") + ":/"
        roots = [Path(d)] if Path(d).exists() else []
    else:
        roots = [Path(x + "/") for x in drives()]
        home = os.environ.get("USERPROFILE")
        if home:
            roots.append(Path(home))
    hits = []
    for root in roots:
        stack = [(root, 0)]
        while stack:
            if time.time() > deadline:
                log.info("Поиск папок «%s» остановлен по времени", query)
                break
            cur, lvl = stack.pop()
            if lvl > depth:
                continue
            try:
                entries = list(os.scandir(cur))
            except (PermissionError, OSError):
                continue
            for e in entries:
                try:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                name = e.name
                low = name.lower()
                if low in _SKIP_DIRS or low.startswith("."):
                    continue
                # берём лучшее совпадение по всем вариантам запроса —
                # русскому и английскому
                score = max(_score(name, t) for t in terms)
                if score > 0:
                    # ближе к корню — важнее: C:\Games главнее, чем
                    # C:\Users\...\AppData\...\games_cache
                    hits.append((score - lvl * 6, str(Path(e.path))))
                if lvl < depth:
                    stack.append((Path(e.path), lvl + 1))
    hits.sort(key=lambda h: -h[0])
    seen, out = set(), []
    for _s, path in hits:
        if path.lower() in seen:
            continue
        seen.add(path.lower())
        out.append(path)
        if len(out) >= 12:
            break
    return out


def folder_list(path: str = "") -> str:
    """Что внутри текущей папки (или указанной). Глаза прогулки: человек
    ведёт голосом и должен слышать, куда можно шагнуть (2026-07-29)."""
    p = (path or "").strip()
    base = Path(p) if p and Path(p).is_absolute() else None
    if base is None:
        cur = here()
        if not cur:
            return "Рабочая папка не задана."
        base = Path(cur) / p if p else Path(cur)
    if not base.is_dir():
        return f"«{base}» — не папка или её нет."
    try:
        subs = [d.name for d in _subdirs(base)]
        files = sorted(f.name for f in base.iterdir() if f.is_file())
    except OSError as e:
        return f"Не смогла заглянуть в {base}: {e}"
    out = [f"Сейчас в {base}."]
    if subs:
        out.append("Папки (%d): %s" % (len(subs), ", ".join(subs[:20])
                                       + ("…" if len(subs) > 20 else "")))
    if files:
        out.append("Файлы (%d): %s" % (len(files), ", ".join(files[:15])
                                       + ("…" if len(files) > 15 else "")))
    if not subs and not files:
        out.append("Пусто.")
    return " ".join(out)


def remember_place(name: str, path: str) -> str:
    """Запомнить папку под человеческим именем — «игровая», «проекты».
    Дальше её не надо искать заново."""
    from server import file_hands
    return file_hands.place_save(name, path)


# ──────────────────────────────── папки ────────────────────────────────
# ГДЕ ОНА СЕЙЧАС СТОИТ (2026-07-29, просьба владельца: «чтобы она могла
# условно гулять от текущей папки туда, куда я её направляю»). Разговор про
# файлы — это ходьба: «зайди в Ламоду» -> «а тут открой архив» -> «назад» ->
# «наверх». Без памяти о текущем месте каждая фраза начиналась бы от корня,
# и человек был бы обязан каждый раз диктовать полный путь.
_cwd: dict = {"path": "", "ts": 0.0, "back": []}


def here() -> str:
    """Текущая папка прогулки (или рабочая, если ещё никуда не заходили)."""
    p = _cwd["path"]
    if p and Path(p).is_dir():
        return p
    try:
        from server import file_hands
        rs = file_hands.roots()
        return str(rs[0]) if rs else ""
    except Exception:
        return ""


def _go(path: Path):
    """Запомнить, куда пришли (и откуда), чтобы работало «назад»."""
    cur = _cwd["path"]
    if cur and cur != str(path):
        _cwd["back"].append(cur)
        del _cwd["back"][:-20]
    _cwd.update(path=str(path), ts=time.time())


_NAV_UP = re.compile(r"^\s*(наверх|вверх|выше|родительск\w*|назад в верх|"
                     r"на уровень выше|\.\.)\s*$", re.I)
_NAV_BACK = re.compile(r"^\s*(назад|обратно|вернись|предыдущ\w*)\s*$", re.I)
_NAV_HOME = re.compile(r"^\s*(домой|в рабочую|рабоч\w+ папк\w+|в начало|"
                       r"корень)\s*$", re.I)
# «спустись ниже» / «зайди глубже» — шаг ВНУТРЬ без названия (2026-07-29):
# если подпапка одна, она и имелась в виду; если их несколько — не гадаем,
# а перечисляем и спрашиваем
_NAV_DOWN = re.compile(r"^\s*(спустись|спустимся|зайди|заходи|иди|перейди)?"
                       r"\s*(ниже|вниз|глубже|внутрь|дальше|в неё|в нее)"
                       r"\s*$", re.I)

# служебные имена, которых человек в отчёте видеть не должен: корзина —
# наша внутренняя кухня, а не содержимое его папки
_HIDE_DIRS = {"_trash", "$recycle.bin", "system volume information"}


def _subdirs(base: Path) -> list:
    """Подпапки без служебных."""
    try:
        return sorted((d for d in base.iterdir()
                       if d.is_dir() and d.name.lower() not in _HIDE_DIRS),
                      key=lambda d: d.name.lower())
    except OSError:
        return []
def open_folder(path: str = "") -> str:
    """Открыть папку в проводнике. Рабочую директорию (files.roots) —
    свободно; всё остальное только если владелец разрешил гулять по диску."""
    from server import file_hands
    p = (path or "").strip()
    # «ОТКРОЙ РАБОЧУЮ ПАПКУ» — ЭТО КОРЕНЬ, А НЕ ПОИСК ПО ИМЕНИ (2026-08-13,
    # живой отказ: она приняла «рабочую папку» за НАЗВАНИЕ и пошла искать
    # подпапку с таким именем, потом «Рабочий стол» — обе не нашлись, и
    # человек четыре раза повторил просьбу впустую. Эти слова значат
    # «вернись в начало», для чего уже есть ветка _NAV_HOME ниже.)
    if re.match(r"^(?:рабоч\w*\s+папк\w*|рабоч\w*\s+стол|"
                r"рабоч\w*\s+област\w*|мою?\s+папк\w*|"
                r"главн\w*\s+папк\w*|корень|начало)\s*$", p, re.I):
        p = ""
    if not p:
        # «ОТКРОЙ ПРОВОДНИК» БЕЗ ПАПКИ = ОТКРОЙ ХОТЬ ЧТО-НИБУДЬ (2026-08-13,
        # живой отказ: человек четыре раза сказал «просто открой проводник»,
        # а получал «папки F:\AI_load_work тут нет» и встречный вопрос.
        # Причина не в команде: в files.roots записан путь на переносимом
        # диске, буква которого сменилась — корень мёртв. Мёртвый корень не
        # повод отказывать: берём ПЕРВЫЙ ЖИВОЙ, а если живых нет — папку
        # самой Сайки. Открыть окно ничего не стоит, отказать — стоит.)
        rs = [Path(r) for r in file_hands.roots()]
        alive = [r for r in rs if r.exists()]
        if alive:
            p = str(alive[0])
        else:
            here_now = Path(here()) if here() else None
            if here_now is not None and here_now.exists():
                p = str(here_now)
            else:
                p = str(Path(__file__).resolve().parent.parent)
            if rs:
                log.warning("Рабочий корень %s не существует (диск "
                            "переехал?) — открываю %s", rs[0], p)
    # ПРОГУЛКА ПО ПАПКАМ: команды направления считаются от ТЕКУЩЕГО места
    cur = Path(here()) if here() else None
    if _NAV_UP.match(p) and cur is not None:
        target = cur.parent
        _go(target)
        p = str(target)
    elif _NAV_BACK.match(p):
        if _cwd["back"]:
            target = Path(_cwd["back"].pop())
            _cwd.update(path=str(target), ts=time.time())
            p = str(target)
        else:
            return "Назад некуда — мы там, откуда начали."
    elif _NAV_HOME.match(p):
        rs = file_hands.roots()
        if not rs:
            return "Рабочая папка не задана — укажи её в настройках."
        target = Path(rs[0])
        _go(target)
        p = str(target)
    elif _NAV_DOWN.match(p) and cur is not None:
        subs = _subdirs(cur)
        if not subs:
            return (f"Ниже некуда: в «{cur.name}» нет подпапок. "
                    "Скажи «наверх» или назови другую папку.")
        if len(subs) > 1:
            return ("Внутри несколько папок: " +
                    ", ".join(d.name for d in subs[:8]) +
                    ". В какую зайти? Спроси человека и назови её.")
        target = subs[0]                    # ровно одна — она и имелась в виду
        p = str(target)
    else:
        target = Path(p)

    # ОТНОСИТЕЛЬНЫЙ ПУТЬ = ОТ ТЕКУЩЕЙ ПАПКИ (2026-07-29, живой провал:
    # создала F:\AI_load_work\Lamoda и тут же «Папки нет на диске: Lamoda» —
    # открытие мерило путь от корня диска. Куда пришли — оттуда и шагаем).
    # Не нашлось по пути — ищем по ИМЕНИ рядом и в рабочих корнях, терпя
    # русское произношение («Ламода» = Lamoda через транслит).
    if not target.is_absolute():
        bases = []
        if cur is not None:
            bases.append(cur)
        bases += [Path(r) for r in file_hands.roots()]
        resolved = None
        for b in bases:
            cand = b / p
            if cand.exists():
                resolved = cand
                break
        if resolved is None:
            # НЕЧЁТКО (2026-07-29, стенд на живом случае: человек говорит
            # «Ламода», а папка называется Lomoda — её же создала модель со
            # слуха. Точное сравнение промахивалось на одной букве).
            want = Path(p).name.lower()
            best, bs = None, 0
            for b in bases:
                for d in _subdirs(b):
                    s = _score(d.name, want)
                    if s > bs:
                        best, bs = d, s
            # порог мягче, чем у окон (34): «Lomoda» против «ламода» — это
            # 33 балла, одна буква из шести. Цена ошибки тут мала (открылась
            # не та папка — просто скажи «наверх»), а цена промаха велика:
            # человек не может попасть в им же созданную папку
            if best is not None and bs >= 30:
                resolved = best
        if resolved is not None:
            target = resolved
    inside = any(target == r or r in target.parents
                 for r in file_hands.roots())
    # 2026-07-26. По умолчанию было запрещено — и получалась дичь: Сайка
    # САМА нашла человеку одиннадцать папок с играми, он выбрал первую, а
    # она отказалась её открыть. Открытие проводника ничего не меняет на
    # диске, это просто окно; запрет здесь охранял пустоту. Настоящая
    # защита — в file_hands: создавать, править и удалять она по-прежнему
    # может только внутри рабочей папки. Тумблер оставлен для тех, кому
    # нужно строже.
    if not inside and not CFG.get("pc.open_any_folder", True):
        return (f"«{p}» вне рабочей папки, а открывать посторонние тебе "
                "запрещено настройкой «Открывать любые папки».")
    if not target.exists():
        # НЕ ПРОСТО «НЕТ» — ПОКАЖИ, ЧТО ЕСТЬ РЯДОМ (2026-07-29): человек
        # ведёт её вслепую, и «папки нет» без списка соседей — тупик
        near = ""
        try:
            # смотрим ТЕКУЩЕЕ место (here() уже учитывает прогулку), а не
            # cur из начала вызова — он мог быть None на первом шаге
            base = Path(here() or file_hands.roots()[0])
            subs = [d.name for d in _subdirs(base)][:8]
            up = base.parent
            near = " Здесь (" + base.name + ") есть: " + \
                   (", ".join(subs) if subs else "только файлы") + "."
            if up != base:
                near += f" Наверху — {up.name}."
        except Exception:
            pass
        # мёртвый корень отличаем от опечатки: это разные разговоры
        try:
            dead = [str(r) for r in file_hands.roots() if not Path(r).exists()]
        except Exception:
            dead = []
        if dead:
            return (f"Папки «{p}» тут нет.{near} И отдельно: рабочая папка "
                    f"в настройках указывает на {dead[0]}, а такого пути "
                    "на диске НЕТ — похоже, сменилась буква диска. Скажи "
                    "человеку про это прямо, тут нужна его правка настроек.")
        return f"Папки «{p}» тут нет.{near}"
    if target.is_file():                    # «зайди в файл» = открыть его
        target_dir = target.parent
    else:
        target_dir = target
    # В ТО ЖЕ ОКНО, А НЕ В НОВОЕ (2026-07-29, владелец: «зашла в Ламоду, но
    # нафиг в новой папке?»). os.startfile каждый раз открывает ЕЩЁ ОДНО
    # окно проводника — за прогулку из пяти шагов их набирается пять.
    # Человек ходит по одной папке, значит и окно должно быть одно: если
    # окно проводника уже есть, переводим ЕГО через COM-интерфейс Shell
    # (тот же, которым пользуется сам проводник), и только если не вышло —
    # открываем новое.
    moved = False
    if _IS_WIN:
        try:
            import win32com.client            # ставится с pywinauto (pywin32)
            shell = win32com.client.Dispatch("Shell.Application")
            for w in shell.Windows():
                try:
                    if "explorer" not in str(w.FullName).lower():
                        continue              # это вкладка IE, не проводник
                    w.Navigate(str(target))
                    try:
                        _, _, user32 = _win32()
                        user32.SetForegroundWindow(int(w.HWND))
                    except Exception:
                        pass
                    moved = True
                    break
                except Exception:
                    continue
        except Exception as e:
            log.debug("Shell.Application недоступен (%s) — открою новое окно", e)
    if not moved:
        try:
            if _IS_WIN:
                os.startfile(str(target))       # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as e:
            return f"Не смогла открыть: {e}"
    # ПОКАЗАТЬ, А НЕ ПРОСТО ОТКРЫТЬ (2026-08-13, живой отказ: «не вижу его,
    # выведи на экран, чтоб я увидел»). Окно открывалось ЗА другими и
    # человек его не видел, а Сайка считала дело сделанным и принималась
    # объяснять, что не может заставить его увидеть. Windows не отдаёт
    # передний план фоновому процессу по первому требованию — поэтому не
    # SetForegroundWindow наугад, а тот же window_focus, что работает по
    # прямой просьбе.
    remember_app("проводник")
    try:
        window_focus(target_dir.name or "проводник")
    except Exception as e:
        log.debug("окно проводника не вышло вперёд: %s", e)
    _go(target_dir)                         # запомнили, где стоим
    # что внутри — сразу, чтобы человек мог вести дальше не глядя на экран
    inner = ""
    try:
        subs = [d.name for d in _subdirs(target_dir)][:8]
        files = [f.name for f in target_dir.iterdir() if f.is_file()][:5]
        if subs:
            inner += " Внутри папки: " + ", ".join(subs) + "."
        if files:
            inner += " Файлы: " + ", ".join(files) + "."
        if not subs and not files:
            inner = " Она пустая."
    except Exception:
        pass
    return f"Открыла {target}.{inner}"
