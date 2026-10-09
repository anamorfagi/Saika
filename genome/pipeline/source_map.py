# -*- coding: utf-8 -*-
"""source_map.py — карта источников: ГДЕ искать характер, в зависимости от того, из чего сделан персонаж.

---- учебный блок: почему поиск искал «хуйню» ----
Охота была написана под кино: «найди транскрипт фильма и интервью актёра». Для героя
китайской новеллы это значит искать то, чего нет (интервью актёра озвучки дунхуа), и не
искать то, что есть (1300 глав книги с его речью и мыслями). Характер живёт в разных местах:

  книга          — речь + ВНУТРЕННИЕ МЫСЛИ (лучший источник логики мышления)
  манга/манхуа   — речь в пузырях + МИМИКА и эмоции на картинке
  аниме/дунхуа   — живая речь серий (субтитры), тон, реакции
  кино/сериал    — транскрипт/сценарий, трактовка актёра
  игра           — сценарий катсцен и диалогов, выборы
  реальный человек — его собственные интервью, подкасты, выступления, книги, посты
  существо       — описание поведения, ремарки, разборы аниматоров; для реальных животных — этология
  разборы фанатов (TV Tropes и т.п.) — НЕ речь, а как его видят: тропы, развитие по арке

Поэтому сначала определяем формы произведения (identify → media), строим маршрут из шагов,
часть шагов выполняет код сам (главы книги, страницы манги, серии), а охоте модели отдаём
правила ИМЕННО для этих форм. Каждый прочитанный адрес пишется в logs/source_yield.jsonl:
сколько реплик дала площадка → в следующий раз лучшие площадки идут первыми (опыт копится).
"""
import json, re, time, pathlib, urllib.request, urllib.parse
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
ВЫХОД = ROOT / "logs" / "source_yield.jsonl"
# честный User-Agent: MangaDex отдаёт 404 на поддельный «браузерный» и пускает честного клиента
UA = {"User-Agent": "AnamorfGenom/1.0 (personal character research)"}

# формы произведения → ключевые слова, по которым их узнаём в строке work, если модель не сказала
ФОРМЫ = {
    "novel":   r"novel|ранобэ|новелл|роман|книг|light novel|web ?novel|xianxia|wuxia|xuanhuan",
    "manga":   r"manga|manhua|manhwa|webtoon|манга|манхуа|манхва|комикс|comic",
    "anime":   r"anime|donghua|animated|аниме|дунхуа|мультсериал|cartoon|мультфильм",
    "film":    r"film|movie|фильм|кино",
    "series":  r"series|сериал|tv show|sitcom",
    "game":    r"game|игра|игры|visual novel",
}

# маршрут по формам: канал, что ищем, как (авто — делает код; поиск — шаблоны для охоты), цель
МАРШРУТЫ = {
    "novel": [
        {"канал": "речь+мысли", "что": "главы самой книги: его реплики и внутренний голос", "авто": "главы", "цель": 60},
        {"канал": "речь", "что": "цитатники по книге", "поиск": ['"{name}" quotes {work}', 'site:wikiquote.org {work}']},
    ],
    "manga": [
        {"канал": "речь+мимика", "что": "страницы глав: реплики в пузырях и эмоции на лице", "авто": "манга", "цель": 40},
    ],
    "anime": [
        {"канал": "речь", "что": "серии с субтитрами (официальные каналы)", "авто": "серии", "цель": 40},
        {"канал": "речь", "что": "транскрипты серий", "поиск": ['"{name}" {work} episode transcript', '{work} episode 1 subtitles']},
    ],
    "film": [
        {"канал": "речь", "что": "полный транскрипт или сценарий", "поиск": ['"{name}" {work} transcript', '{work} screenplay', 'site:scrapsfromtheloft.com {work}']},
        {"канал": "трактовка", "что": "интервью исполнителя об этой роли", "поиск": ['{work} {name} actor interview role']},
    ],
    "series": [
        {"канал": "речь", "что": "транскрипты серий", "поиск": ['site:transcripts.foreverdreaming.org {work}', '"{name}" {work} episode transcript']},
    ],
    "game": [
        {"канал": "речь", "что": "сценарий игры: катсцены и диалоги", "поиск": ['{work} game script "{name}"', '{work} all cutscenes dialogue', 'site:gamefaqs.gamespot.com {work} script']},
    ],
    "real_person": [
        {"канал": "речь", "что": "его собственные интервью и выступления (транскрипты, субтитры)", "поиск": ['"{name}" interview transcript', '"{name}" podcast', '"{name}" speech full text']},
        {"канал": "речь", "что": "его цитаты с источником", "поиск": ['site:wikiquote.org "{name}"']},
    ],
    "creature": [
        {"канал": "поведение", "что": "описания поведения, ремарки, разборы аниматоров / этология вида", "поиск": ['{work} "{name}" behavior animation breakdown', '"{name}" {work} scene description']},
    ],
}
# общее для всех вымышленных: как его ВИДЯТ (не речь) — тропы и развитие
ОБЩЕЕ = [{"канал": "разбор", "что": "TV Tropes / разборы: тропы, развитие по арке, как его видят", "поиск": ['site:tvtropes.org {work} characters', '"{name}" character analysis {work}']}]

ПРАВИЛА_ФОРМ = {
    "novel": "КНИГА: речь и внутренние мысли героя — в главах. Читай главы с читалок (novelfull, lightnovelworld и т.п.), а не пересказы. Интервью актёров экранизации для книжного героя не нужны.",
    "manga": "МАНГА/МАНХУА: реплики в пузырях и мимика — на страницах глав. Текстовые пересказы глав беднее самой страницы.",
    "anime": "АНИМЕ/ДУНХУА: живая речь — субтитры серий. Ищи официальные каналы с сериями (YouTube), вызывай subs на ОДНОЙ серии, не на плейлисте.",
    "film": "КИНО: полный транскрипт/сценарий одной страницей; затем интервью исполнителя о роли (канал трактовка).",
    "series": "СЕРИАЛ: транскрипты по сериям; бери серии из разных сезонов.",
    "game": "ИГРА: сценарий катсцен и диалогов (script, transcript, all cutscenes). Видео катсцен — subs.",
    "real_person": "РЕАЛЬНЫЙ ЧЕЛОВЕК: только его собственные слова — интервью, подкасты, выступления, посты. Статьи о нём — пересказ, не речь. Жёлтую прессу не брать.",
    "creature": "СУЩЕСТВО: речи нет или мало; характер — в описанных действиях, реакциях, разборах аниматоров. Ноль реплик — норма.",
}


def формы(subject):
    """Из чего сделан персонаж: сначала то, что сказала модель (media), потом ключевые слова в work."""
    out = []
    for m in subject.get("media") or []:
        m = str(m).lower()
        for ф, рег in ФОРМЫ.items():
            if re.search(рег, m) and ф not in out:
                out.append(ф)
        if m in ("real_person", "человек") and "real_person" not in out:
            out.append("real_person")
    work = str(subject.get("work", "")).lower()
    for ф, рег in ФОРМЫ.items():
        if re.search(рег, work) and ф not in out:
            out.append(ф)
    вид = subject.get("kind", "")
    if вид == "человек" and "real_person" not in out:
        out.insert(0, "real_person")
    if (вид == "существо" or subject.get("speaks") is False) and "creature" not in out:
        out.append("creature")
    перв = str(subject.get("primary") or "").lower()
    for ф, рег in ФОРМЫ.items():   # первоисточник — вперёд: книга раньше её экранизации
        if перв and re.search(рег, перв) and ф in out:
            out.remove(ф); out.insert(0, ф)
    return out or ["film"]


def маршрут(subject):
    шаги = []
    for ф in формы(subject):
        for ш in МАРШРУТЫ.get(ф, []):
            шаги.append(dict(ш, форма=ф))
    if subject.get("kind") != "человек":
        шаги += [dict(ш, форма="разбор") for ш in ОБЩЕЕ]
    return шаги


def описание(шаги):
    return " → ".join(f"[{ш['форма']}] {ш['что']}" + (" (сам)" if ш.get("авто") else "") for ш in шаги)


def запросы(шаги, name, work):
    q = []
    for ш in шаги:
        for t in ш.get("поиск", []):
            q.append(t.format(name=name, work=work).strip())
    return q


# ---------------------------------------------------------------- опыт площадок
def домен(url):
    return re.sub(r"^www\.", "", urllib.parse.urlsplit(str(url)).netloc.lower())


def учесть(url, реплик, знаков, формы_, принят=None):
    """Каждый прочитанный адрес — строка опыта: площадка, форма, сколько реплик дала."""
    if not url or not str(url).startswith("http"):
        return
    try:
        ВЫХОД.parent.mkdir(exist_ok=True)
        with ВЫХОД.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M"), "domain": домен(url), "forms": list(формы_),
                                "replicas": int(реплик or 0), "chars": int(знаков or 0), "taken": принят}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def лучшие_площадки(формы_, n=8):
    """Площадки, которые реально давали реплики для таких же форм — по среднему улову."""
    if not ВЫХОД.exists():
        return []
    сумма, раз = defaultdict(int), defaultdict(int)
    for x in ВЫХОД.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(x)
        except Exception:
            continue
        if set(r.get("forms") or []) & set(формы_):
            сумма[r["domain"]] += r.get("replicas", 0); раз[r["domain"]] += 1
    ряд = sorted(((сумма[d] / раз[d], раз[d], d) for d in раз), reverse=True)
    return [(d, round(ср, 1), к) for ср, к, d in ряд if ср >= 3][:n]


def пустые_площадки(формы_, n=10):
    """Площадки, которые трижды и больше дали ноль — охоте говорим их не трогать."""
    if not ВЫХОД.exists():
        return []
    сумма, раз = defaultdict(int), defaultdict(int)
    for x in ВЫХОД.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(x)
        except Exception:
            continue
        if set(r.get("forms") or []) & set(формы_):
            сумма[r["domain"]] += r.get("replicas", 0); раз[r["domain"]] += 1
    return [d for d in раз if раз[d] >= 3 and сумма[d] == 0][:n]


def правила_охоты(шаги, формы_, собрано):
    """Свод для охоты модели: ЧТО и ГДЕ искать для этих форм, что уже собрано кодом, что опыт говорит о площадках."""
    строки = ["Ты ищешь материал о характере персонажа. Порядок и площадки зависят от того, из чего он сделан.",
              "Формы произведения: " + ", ".join(формы_) + "."]
    строки += [ПРАВИЛА_ФОРМ[ф] for ф in формы_ if ф in ПРАВИЛА_ФОРМ]
    строки.append("МАРШРУТ (по порядку): " + описание(шаги))
    if собрано:
        строки.append("УЖЕ СОБРАНО КОДОМ (не ищи это заново): " + "; ".join(собрано))
    лучшие = лучшие_площадки(формы_)
    if лучшие:
        строки.append("ОПЫТ: эти площадки реально давали реплики для таких форм — начинай с них: " +
                      ", ".join(f"{d} (~{ср} реплик за чтение, читали {к} раз)" for d, ср, к in лучшие))
    пустые = пустые_площадки(формы_)
    if пустые:
        строки.append("ОПЫТ: эти площадки много раз давали НОЛЬ — не читай их: " + ", ".join(пустые))
    строки.append("""ОБЩИЕ ПРАВИЛА:
- Нужна прямая речь персонажа в РАЗНЫХ ситуациях: опасность, спор, шутка, страх, близкий человек, победа, неудача. Один жанр сцен — однобокий геном.
- Пересказы, вики-биографии, обзоры, «10 фактов», магазины — не речь. Брать как источник речи нельзя.
- Имя в кавычках + название произведения в каждом запросе, иначе притащит однофамильца.
- Ищи на языке оригинала или английском: там текста больше.
- Ссылка на видео — subs на ОДНОМ видео, не на плейлисте.
- Read показал 0 реплик — не бери, ищи дальше. 403 — browser или другая площадка.
- Перед каждым вызовом одной строкой: что делаешь и почему.
- Хватит, когда речи 60+ реплик из 3+ источников в разных ситуациях, или когда честно больше негде — тогда stop.""")
    return "\n\n".join(строки)


# ---------------------------------------------------------------- серии: субтитры официальных серий
def серии(job, name, work, серий=3):
    """Аниме/дунхуа: находим отдельные серии (не плейлисты) и снимаем субтитры с нескольких из разных мест сериала."""
    from ddgs import DDGS
    import tools_web
    job.emit("sources", f"Ищу серии «{work}» с субтитрами")
    ролики = []
    try:
        with DDGS(timeout=25) as d:
            for q in (f"{work} episode 1 english sub", f"{work} episode 10 eng sub", f"{work} episode 30 english subtitles"):
                ролики += [r for r in d.videos(q, max_results=6) if "list=" not in str(r.get("content", ""))]
    except Exception as e:
        job.emit("source_error", "поиск серий: " + str(e)[:160]); return 0
    взято, всего = 0, 0
    for r in ролики:
        if взято >= серий:
            break
        url = r.get("content") or r.get("url") or ""
        if not url or url in job.attempted or "youtube.com/watch" not in url and "youtu.be" not in url:
            continue
        job.attempted.add(url)
        job.emit("fetch", "Субтитры серии: " + str(r.get("title", ""))[:120], url=url)
        try:
            готовое = tools_web.субтитры_видео(url, "en")
        except Exception as e:
            job.emit("source_error", "субтитры: " + str(e)[:140], url=url); continue
        текст = готовое.get("текст") or ""
        if len(текст) < 2000:
            continue
        источник = {"url": url, "title": "Серия: " + str(r.get("title", ""))[:140], "snippet": "", "identity_quote": "",
                    "chars": len(текст), "status": "read", "_text": текст, "реплик": 0, "канал": "речь"}
        job.sources.append(источник); взято += 1; всего += len(текст)
        (job.directory / ("source_%02d.txt" % len(job.sources))).write_text(текст, encoding="utf-8")
        job.emit("source", f"Серия: субтитры {готовое.get('вид')} · {len(текст)} знаков (говорящий не подписан — речь сплошная)",
                 url=url, chars=len(текст), replicas=0)
    return взято


# ---------------------------------------------------------------- манга: страницы глав → зрение модели
def _json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
        return json.loads(r.read())


def манга(job, name, work, глав=3, страниц=8):
    """Манга/манхуа: MangaDex (открытое API) → главы из начала/середины/конца → страницы → модель-зрение
    переписывает пузыри в виде «Говорящий: реплика [эмоция на лице]». Так в разбор идут и слова, и мимика.
    ---- учебный блок: почему base64 ----
    Картинку модели отдаём самим содержимым (data:image/...;base64), а не ссылкой: прокси модели
    не обязан уметь скачивать с mangadex, а так он видит ровно то, что скачали мы."""
    import base64
    названия = [str(work).split("·")[0].split("(")[0].strip()]
    try:
        from chat import видит
        if not видит(job.client.model):
            job.emit("sources", f"Манга пропущена: выбранная модель {job.client.model} не смотрит картинки")
            return 0
    except ImportError:
        pass
    job.emit("sources", f"Ищу мангу/манхуа «{названия[0]}» на MangaDex")
    try:
        найдено = _json("https://api.mangadex.org/manga?limit=5&title=" + urllib.parse.quote(названия[0]))["data"]
    except Exception as e:
        job.emit("source_error", "MangaDex: " + str(e)[:160]); return 0
    if not найдено:
        job.emit("sources", "На MangaDex этой манги/манхуа нет"); return 0
    mid = найдено[0]["id"]
    try:
        главы_ = _json(f"https://api.mangadex.org/manga/{mid}/feed?limit=500&translatedLanguage[]=en&order[chapter]=asc")["data"]
    except Exception as e:
        job.emit("source_error", "MangaDex главы: " + str(e)[:160]); return 0
    главы_ = [g for g in главы_ if not g["attributes"].get("externalUrl") and g["attributes"].get("pages", 0) > 0]
    if not главы_:
        job.emit("sources", "Английских глав с картинками на MangaDex нет (лицензия или только внешние ссылки)"); return 0
    выбор = [главы_[0]] + ([главы_[len(главы_) // 2]] if len(главы_) > 2 else []) + ([главы_[-1]] if len(главы_) > 1 else [])
    выбор = выбор[:глав]
    job.emit("sources", f"MangaDex: {len(главы_)} глав на английском · читаю главы " + ", ".join(str(g["attributes"].get("chapter")) for g in выбор))
    куски, реплик_всего = [], 0
    for г in выбор:
        job.check()
        try:
            at = _json("https://api.mangadex.org/at-home/server/" + г["id"])
            файлы = at["chapter"]["dataSaver"]
            шаг = max(1, len(файлы) // страниц)
            адреса = [f"{at['baseUrl']}/data-saver/{at['chapter']['hash']}/{f}" for f in файлы[::шаг][:страниц]]
        except Exception as e:
            job.emit("source_error", f"глава {г['attributes'].get('chapter')}: {str(e)[:120]}"); continue
        for i in range(0, len(адреса), 4):
            части = [{"type": "text", "text":
                      f"Это страницы манги/манхуа «{названия[0]}». Перепиши ВСЕ реплики из пузырей по порядку чтения, "
                      f"каждую строкой «Говорящий: реплика [эмоция и мимика говорящего]». Персонажа {name} узнавай по внешности и обращениям. "
                      "Мысли (пузыри-облака) помечай «(мысль)». Не выдумывай: нечитаемое пропускай. Без вступлений."}]
            for u in адреса[i:i + 4]:
                try:
                    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25) as r:
                        части.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(r.read()).decode()}})
                except Exception:
                    continue
            if len(части) < 2:
                continue
            try:
                текст = job.client.chat_parts([{"role": "user", "content": части}], max_tokens=1800)
            except Exception as e:
                job.emit("source_error", "зрение модели: " + str(e)[:160]); return 0
            куски.append(f"=== глава {г['attributes'].get('chapter')} ===\n{текст}")
        реплик = sum(1 for x in "\n".join(куски).splitlines() if re.match(r"\s*[^:\n]{1,40}:", x))
        job.emit("source", f"Манга, глава {г['attributes'].get('chapter')}: переписано зрением, строк речи ~{реплик}",
                 url=f"https://mangadex.org/chapter/{г['id']}", replicas=реплик)
    if not куски:
        return 0
    текст = "\n\n".join(куски)
    from research import реплик_в_тексте
    реплик_всего = реплик_в_тексте(текст, job.имена())
    job.sources.append({"url": f"https://mangadex.org/title/{mid}", "title": f"Манга «{названия[0]}»: пузыри и мимика (зрение)",
                        "snippet": "", "identity_quote": "", "chars": len(текст), "status": "read", "_text": текст, "реплик": реплик_всего})
    (job.directory / ("source_%02d.txt" % len(job.sources))).write_text(текст, encoding="utf-8")
    job.emit("source", f"Манга: {len(выбор)} глав, реплик персонажа ~{реплик_всего}, с эмоциями на лицах", chars=len(текст), replicas=реплик_всего)
    job.persist()
    return реплик_всего


def выполнить_авто(job, шаги, name, aliases, work):
    """Шаги, которые код делает сам, ДО охоты модели. Возвращает список «что собрано» для правил охоты."""
    собрано = []
    for ш in шаги:
        a = ш.get("авто")
        if not a:
            continue
        try:
            if a == "главы":
                n = job.главы_новеллы(name, aliases, work)
                if n: собрано.append(f"главы книги: реплик ~{n}")
            elif a == "манга":
                n = манга(job, name, work)
                if n: собрано.append(f"страницы манги зрением: реплик ~{n}")
            elif a == "серии":
                n = серии(job, name, work)
                if n: собрано.append(f"субтитры {n} серий")
        except Exception as e:
            if type(e).__name__ == "Cancelled":
                raise
            job.emit("source_error", f"авто-шаг «{a}» сорвался: {str(e)[:160]}")
    return собрано
