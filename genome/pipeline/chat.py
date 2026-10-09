# -*- coding: utf-8 -*-
"""[БЛОК ЧАТ] Живой разговор с моделью внутри студии.

Зачем отдельный файл, а не «спросить модель текстом»: обычный chat отдаёт ответ
и всё. Здесь у модели руки — она сама ищет в сети, читает страницы, открывает
карточки персонажей из share/, правит гены, вызывает promptsmith. И она знает,
куда попала: системный текст ниже объясняет, что такое Anamorf Genom, из чего
состоит геном и по каким принципам он заполняется.

Протокол: на stdin приходит {"id", "messages":[{role, content, files:[...]}], "provider", "model"}.
На stdout построчно летят события NDJSON:
  {"t":"step","text":...}          — что модель делает сейчас
  {"t":"tool","name":...,"arg":...,"out":...,"links":[...]}
  {"t":"reply","text":...}         — финальный ответ
  {"t":"error","text":...}
Построчно — чтобы студия показывала ход работы, а не ждала минуту в тишине.
"""
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ГЕНОМ = HERE.parent
SHARE = ГЕНОМ / "share"
sys.path.insert(0, str(HERE))

ПРЕДЕЛ_ТЕКСТА = 12000          # сколько знаков инструмента отдаём модели за раз
ПРЕДЕЛ_ШАГОВ = 14              # потолок по вызовам инструментов на один ответ


def шлём(**что):
    sys.stdout.write(json.dumps(что, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def обрезать(текст, предел=ПРЕДЕЛ_ТЕКСТА):
    текст = str(текст or "")
    return текст if len(текст) <= предел else текст[:предел] + f"\n…(обрезано, всего {len(текст)} знаков)"


# ---------------------------------------------------------------- знание о проекте

def структура_генома():
    try:
        блоки = json.loads((HERE / "genes.json").read_text(encoding="utf-8"))
    except Exception:
        return "", 0
    строки, всего = [], 0
    for b in блоки:
        гены = b.get("genes") or []
        всего += len(гены)
        строки.append(f"{b.get('block')} · {b.get('name')} ({len(гены)}): " +
                      ", ".join(g.get("id", "") for g in гены))
    return "\n".join(строки), всего


def о_проекте():
    карта, всего = структура_генома()
    try:
        имена = sorted(p.name[:-12] for p in SHARE.glob("*.genome.json"))
    except Exception:
        имена = []
    return f"""Ты — ассистент внутри программы Anamorf Genom. Это не абстрактный чат:
ты живёшь в студии, где собираются личностные геномы персонажей для Сайки.

ЧТО ТАКОЕ ГЕНОМ. {всего} генов в {len(карта.splitlines())} блоках. Каждый ген — шкала
от -1 до +1 с уверенностью 0..1 и списком улик. Ген без улики — пустой звук: значение
без цитаты и источника в этом проекте не считается снятым.

ВИДЫ ПЕРСОНАЖЕЙ. персонаж/человек — блок beast и блок nat не применяются; ии —
применяется nat (природа машины), beast нет; существо — применяется beast (бессловесное
поведение), nat нет. Существо (дракон, зверь, дух) не говорит: все речевые гены у него
остаются пустыми, и это правильно, а не пробел.

ИСТОЧНИКИ. Первоисточник — само произведение: сценарий, субтитры, реплики. Дальше —
слова автора/актёра из их собственных каналов и интервью, потом студия и релизные
материалы. Фан-сайты, фанфики, форумы, соцсети источниками НЕ являются. Пересказ
энциклопедии слабее прямой реплики и получает меньшую уверенность.

ВИДЫ УЛИК: w — вики/энциклопедия, k — пересказ, n — первоисточник, t — расшифровка
реплик, a — просодия (голос), f — кадр/фото, v — вручную от человека, d — достроено
по корреляциям (самое слабое).

ПРИНЦИПЫ, по которым тут работают:
1. Правим класс проблемы, а не одну карточку. Кривая карточка — симптом кривой логики.
2. Сверяемся с литературой по психологии, а не с ощущениями. Слабо реплицируемые
   конструкты (истощение эго, мышление роста, grit, зефирный тест) в опору не берём.
3. Малые данные — не повод фантазировать. Лучше 12 генов с уликами, чем 300 с догадками.
4. Противоречивые улики снижают уверенность, а не выбирают удобную сторону.
5. Ничего не спрашиваем ради разрешения — делаем и показываем результат.

БЛОКИ ГЕНОМА:
{карта}

ПЕРСОНАЖИ СЕЙЧАС В ПАПКЕ: {', '.join(имена) if имена else '(пусто)'}

КАК ГОВОРИТЬ. Ты не служба поддержки. Никаких «Привет! Я ассистент в…», никаких
«могу помочь с…», никаких «что вас интересует?». На «привет» отвечают «здорово» и
сразу по делу: что сейчас открыто и что с этим не так. Обращение на «ты». Живой
разговорный русский, коротко, без канцелярита и без списков услуг. Своё мнение
говоришь прямо: «тут криво, потому что…», а не «возможно, стоит рассмотреть».
Не извиняешься по пустякам и не расшаркиваешься.

КАК РАБОТАТЬ. Не спрашивай разрешения — если можешь проверить инструментом, проверь.
Если правишь ген, сначала прочитай карточку, потом скажи, что именно поменял и почему.
Всё о персонаже — из того, что реально прочитал, а не из памяти. Не знаешь — так и скажи.
Картинки: существующего персонажа ищи find_images и ставь set_avatar; синтез или кого нет в сети — рисуй gen_avatar.
Полный анализ существующего персонажа — research_genome (фон, минуты); ход — research_status, прочитанное — research_sources.
ПОЛНЫЙ АНАЛИЗ / «доделай» / «доведи до конца» — это finish_character: он сам ведёт все этапы, не спрашивай разрешения на каждый шаг.
САМОПРОВЕРКА: прежде чем сказать «готово», вызови card_audit и назови, что осталось. Не дописал — так и скажи, что именно и почему."""


# ---------------------------------------------------------------- инструменты

def _карточка(идентификатор):
    идентификатор = re.sub(r"[^a-z0-9_]", "", str(идентификатор or "").lower())
    файл = SHARE / (идентификатор + ".genome.json")
    if not файл.exists():
        raise RuntimeError(f"карточки «{идентификатор}» нет в share/")
    return файл, json.loads(файл.read_text(encoding="utf-8"))


def _переписать(файл, карта):
    файл.write_text(json.dumps(карта, ensure_ascii=False, indent=2), encoding="utf-8")
    список = []
    for p in sorted(SHARE.glob("*.genome.json")):
        try:
            c = json.loads(p.read_text(encoding="utf-8")); c.pop("avatar", None)
            if c.get("format") == "saika-genome/1":
                список.append(c)
        except Exception:
            continue
    врем = SHARE / "_list.tmp"
    врем.write_text("window.__SHARE=" + json.dumps(список, ensure_ascii=False) + ";\n", encoding="utf-8")
    врем.replace(SHARE / "_list.js")


def и_search_web(a):
    from research import search_web
    ряды = search_web(str(a.get("query") or ""))[:6]
    ссылки = [r["url"] for r in ряды]
    текст = "\n".join(f"- {r['title']}\n  {r['url']}\n  {r['snippet'][:220]}" for r in ряды)
    return текст or "ничего не нашлось", ссылки


def и_read_url(a):
    from research import fetch_source
    url = str(a.get("url") or "")
    d = fetch_source(url)
    текст = d.get("text") if isinstance(d, dict) else str(d)
    return обрезать(текст), [url]


def и_list_chars(a):
    ряды = []
    for p in sorted(SHARE.glob("*.genome.json")):
        try:
            c = json.loads(p.read_text(encoding="utf-8")); m = c.get("meta") or {}
            ряды.append(f"{p.name[:-12]} · {m.get('name','')} «{m.get('alias','')}» · вид={m.get('kind','')} · "
                        f"генов снято={len(c.get('genome') or {})} · {m.get('src','')}")
        except Exception:
            continue
    return "\n".join(ряды) or "папка пуста", []


def и_read_card(a):
    _, карта = _карточка(a.get("id"))
    часть = str(a.get("part") or "all")
    м = карта.get("meta") or {}
    if часть == "meta":
        м = dict(м); м.pop("evidence", None)
        return обрезать(json.dumps(м, ensure_ascii=False, indent=2)), []
    if часть == "genome":
        return обрезать(json.dumps(карта.get("genome") or {}, ensure_ascii=False, indent=2)), []
    if часть == "evidence":
        return обрезать(json.dumps(м.get("evidence") or [], ensure_ascii=False, indent=2)), []
    if часть == "prompt":
        return обрезать(м.get("prompt") or "(системный промпт ещё не собран)"), []
    карта = dict(карта); карта.pop("avatar", None)
    return обрезать(json.dumps(карта, ensure_ascii=False, indent=2), 20000), []


# --- зрение: чужими глазами ------------------------------------------------------------
# Признаки моделей, которые умеют смотреть картинки. Список нарочно консервативный:
# лучше лишний раз позвать распознавание, чем отправить изображение в текстовую модель
# и получить выдумку.
ЗРЯЧИЕ = ("gpt-4o", "gpt-4.1", "gpt-5", "gemini", "claude-3.5", "claude-3-5", "claude-sonnet-4",
          "claude-5", "sonnet-4", "pixtral", "llava", "qwen-vl", "qwen2-vl", "glm-4v", "-vl")


def видит(модель):
    м = str(модель or "").lower()
    return any(з in м for з in ЗРЯЧИЕ)


ПАМЯТЬ = ГЕНОМ / ".genome_state.json"
ЗАБЫТЬ_ЧЕРЕЗ = 6 * 3600          # столько держим отказ в чёрном списке


def _память():
    try:
        return json.loads(ПАМЯТЬ.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _запомнить(что):
    д = _память(); д.update(что)
    try:
        ПАМЯТЬ.write_text(json.dumps(д, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def зрячие_кандидаты(кроме=()):
    """Пары «стык + модель», которыми можно посмотреть картинку.

    Берём только те стыки, где реально лежит ключ, и только их собственные модели
    из каталога: выдуманное имя модели даст 404 вместо ответа.
    """
    try:
        кат = json.loads((HERE / "providers.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    по_id = {п.get("id"): (п.get("models") or []) for п in (кат.get("providers") or [])}
    ряд = []
    for стык in все_стыки():
        for модель in по_id.get(стык, []):
            if видит(модель) and (стык, модель) not in кроме:
                ряд.append((стык, модель))

    # Кто уже показал себя рабочим — первым; кто недавно отказал — в конец.
    # Без этого каждая картинка заново перебирала выбитые квоты: три лишних запроса
    # и полминуты ожидания на ровном месте.
    п = _память(); удачный = п.get("vision_ok"); плохие = п.get("vision_bad") or {}
    сейчас = time.time()

    def вес(пара):
        ключ = "/".join(пара)
        if ключ == удачный:
            return -1
        когда_отказал = плохие.get(ключ)
        if когда_отказал and сейчас - когда_отказал < ЗАБЫТЬ_ЧЕРЕЗ:
            return 1
        return 0

    return sorted(ряд, key=вес)


ПРОСЬБА_К_ГЛАЗАМ = (
    "Опиши это изображение для другого ассистента, который его не видит. "
    "Нужно: 1) что на картинке в целом; 2) ВЕСЬ читаемый текст дословно, включая заголовки, "
    "адреса и подписи; 3) если это персонаж или страница о персонаже — кто он и из какого "
    "произведения, если это видно. Без выводов и советов, только то, что действительно видно."
)


def посмотреть_чужими_глазами(картинки):
    """Текущая модель без зрения — просим зрячую пересказать картинку словами.

    Так связка не упирается в «эта модель не умеет смотреть»: работу продолжает та же
    модель, просто с описанием вместо изображения. Что именно смотрело — видно в окне.
    """
    from llm import Client
    беда = None
    for стык, модель in зрячие_кандидаты()[:4]:
        try:
            глаза = Client(provider=стык, model=модель, timeout=120)
            if not глаза.key:
                continue
            куски = [{"type": "text", "text": ПРОСЬБА_К_ГЛАЗАМ}]
            куски += [{"type": "image_url", "image_url": {"url": к}} for к in картинки]
            шлём(t="step", text=f"смотрю картинку через {модель}")
            текст = глаза.chat_parts([{"role": "user", "content": куски}], max_tokens=1200)
            if текст and текст.strip():
                _запомнить({"vision_ok": f"{стык}/{модель}"})
                return текст.strip(), модель
        except Exception as e:
            беда = e
            плохие = (_память().get("vision_bad") or {})
            плохие[f"{стык}/{модель}"] = time.time()
            _запомнить({"vision_bad": плохие})
            continue
    if беда:
        raise RuntimeError(str(беда)[:200])
    return "", ""


def прочитать_буквы(картинки):
    """Последний рубеж: если зрячей модели нет вовсе, снимаем хотя бы текст локально."""
    try:
        import base64 as б64, io
        from PIL import Image
        import pytesseract
    except Exception:
        return ""
    куски = []
    for к in картинки:
        try:
            сырьё = б64.b64decode(str(к).split(",", 1)[-1])
            куски.append(pytesseract.image_to_string(Image.open(io.BytesIO(сырьё)), lang="rus+eng"))
        except Exception:
            continue
    текст = "\n".join(x.strip() for x in куски if x and x.strip())
    return текст[:4000]


# --- проверка генов -------------------------------------------------------------------
БЛОКИ_ВИДА = {"beast": {"существо"}, "nat": {"ии"}}
ВИДЫ = ("персонаж", "человек", "ии", "существо", "синтез")


def _каталог():
    блоки = json.loads((HERE / "genes.json").read_text(encoding="utf-8"))
    return {г["id"]: б.get("block") for б in блоки for г in (б.get("genes") or [])}


def годен(ген, вид, каталог):
    """Ген должен и существовать, и подходить виду.

    Тот же класс ошибки, что раньше ловили в исследовании: у Эльзы оказывались гены
    блока beast, потому что при заполнении никто не спрашивал, кто она такая.
    Проверка живёт здесь, чтобы чат не мог завести ту же кривизну заново.
    """
    блок = каталог.get(ген)
    if блок is None:
        return False, "такого гена нет"
    можно = БЛОКИ_ВИДА.get(блок)
    if можно and вид not in можно:
        return False, f"блок {блок} не применяется к виду «{вид}»"
    return True, ""


def и_create_card(a):
    """Завести персонажа с нуля — ручная сборка, без исследования."""
    ид = re.sub(r"[^a-z0-9_]", "", str(a.get("id") or "").lower())
    if not ид:
        raise RuntimeError("нужен id латиницей, например elsa или toothless")
    файл = SHARE / (ид + ".genome.json")
    if файл.exists():
        raise RuntimeError(f"«{ид}» уже есть в папке — правь через edit_card или возьми другой id")
    вид = str(a.get("kind") or "персонаж").strip()
    if вид not in ВИДЫ:
        raise RuntimeError("вид должен быть одним из: " + ", ".join(ВИДЫ))
    имя = str(a.get("name") or "").strip()
    if not имя:
        raise RuntimeError("нужно имя персонажа")

    гены = a.get("genes") or {}
    if isinstance(гены, str):
        гены = json.loads(гены)
    каталог = _каталог()
    принято, отклонено = {}, []
    улика = "v:собран ассистентом в чате"
    for ген, зн in (гены or {}).items():
        ладно, почему_нет = годен(ген, вид, каталог)
        if not ладно:
            отклонено.append(f"{ген} — {почему_нет}")
            continue
        if isinstance(зн, (int, float)):
            зн = [float(зн), 0.5]
        значение = max(-1.0, min(1.0, float(зн[0])))
        уверенность = max(0.0, min(1.0, float(зн[1]) if len(зн) > 1 else 0.5))
        принято[ген] = [значение, уверенность, [улика]]

    список = lambda ключ: [str(x) for x in (a.get(ключ) or []) if str(x).strip()]
    карта = {
        "format": "saika-genome/1", "id": ид,
        "meta": {
            "kind": вид, "name": имя,
            "alias": str(a.get("alias") or ""), "src": str(a.get("src") or ""),
            "method": str(a.get("method") or "собран вручную в чате"),
            "desc": str(a.get("desc") or ""), "identity": str(a.get("identity") or ""),
            "voice": str(a.get("voice") or ""),
            "samples": список("samples"), "never": список("never"),
            "masks": список("masks"), "tensions": список("tensions"),
            "evidence": [], "prompt": "",
            "exported": time.strftime("%Y-%m-%dT%H:%M"),
        },
        "genome": принято,
    }
    _переписать(файл, карта)
    ответ = [f"создан share/{ид}.genome.json · вид {вид} · генов {len(принято)}"]
    if отклонено:
        ответ.append("не записаны: " + "; ".join(отклонено))
    ответ.append("промпт пока пустой — собери его через make_prompt, если нужен")
    return "\n".join(ответ), []


def и_edit_card(a):
    файл, карта = _карточка(a.get("id"))
    отчёт = []
    мета = a.get("meta") or {}
    if isinstance(мета, str):
        мета = json.loads(мета)
    for k, v in (мета or {}).items():
        if k in ("evidence", "prompt"):
            continue
        карта.setdefault("meta", {})[k] = v
        отчёт.append(f"meta.{k} = {json.dumps(v, ensure_ascii=False)[:80]}")
    гены = a.get("genes") or {}
    if isinstance(гены, str):
        гены = json.loads(гены)
    каталог = _каталог()
    вид = (карта.get("meta") or {}).get("kind") or "персонаж"
    for ген, зн in (гены or {}).items():
        ладно, почему_нет = годен(ген, вид, каталог)
        if not ладно:
            отчёт.append(f"{ген}: пропущен — {почему_нет}")
            continue
        if isinstance(зн, (int, float)):
            зн = [float(зн), 0.5]
        значение = float(зн[0]); уверенность = float(зн[1]) if len(зн) > 1 else 0.5
        было = (карта.get("genome") or {}).get(ген)
        улики = было[2] if (было and len(было) > 2) else []
        улики = list(улики) + ["v:правка в чате"]
        карта.setdefault("genome", {})[ген] = [max(-1.0, min(1.0, значение)),
                                               max(0.0, min(1.0, уверенность)), улики]
        отчёт.append(f"{ген}: {было[0] if было else '—'} → {значение:+.2f} (ув. {уверенность:.2f})")
    if not отчёт:
        return "нечего менять: ни meta, ни genes не переданы", []
    _переписать(файл, карта)
    return "записано в share/:\n" + "\n".join(отчёт), []


def и_find_genes(a):
    запрос = str(a.get("query") or "").lower()
    блоки = json.loads((HERE / "genes.json").read_text(encoding="utf-8"))
    найдено = []
    for b in блоки:
        for g in b.get("genes") or []:
            куча = " ".join(str(g.get(k, "")) for k in ("id", "name", "desc", "neg", "pos")).lower()
            if запрос in куча:
                найдено.append(f"{g['id']} · {g.get('name')} [{b.get('block')}]\n"
                               f"  -1: {g.get('neg')}   +1: {g.get('pos')}\n  {str(g.get('desc',''))[:400]}")
    return обрезать("\n".join(найдено[:20]) or "по этому слову генов нет"), []


def и_make_prompt(a):
    файл, _ = _карточка(a.get("id"))
    import subprocess
    r = subprocess.run([sys.executable, str(HERE / "promptsmith.py"), str(файл),
                        getattr(КЛИЕНТ, "pid", "") or "", getattr(КЛИЕНТ, "model", "") or ""],   # на выбранной модели
                       capture_output=True, text=True, timeout=600,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1"))
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "promptsmith не отработал")[:400])
    _, карта = _карточка(a.get("id"))
    return обрезать(((карта.get("meta") or {}).get("prompt")) or "(пусто)"), []


def и_read_upload(a):
    имя = str(a.get("name") or "")
    for ф in ВЛОЖЕНИЯ:
        if ф["name"] == имя:
            return обрезать(ф.get("text") or "(в этом файле нет текста — это картинка, я её вижу целиком)"), []
    return "такого файла не прикреплено", []


ВЛОЖЕНИЯ = []
КЛИЕНТ = None   # текущий стык модели — им же пойдёт фоновое исследование


# ---- полное исследование в фоне: pipeline/research_into.py ----
def и_research_genome(a):
    import subprocess, sys as _s
    ид = re.sub(r"[^a-z0-9_]", "", str(a.get("id") or "").lower())
    запрос = str(a.get("query") or "").strip()
    if not ид or not запрос:
        raise RuntimeError("нужны id карточки и query (имя + произведение)")
    if not (SHARE / f"{ид}.genome.json").exists():
        raise RuntimeError(f"карточки {ид} нет — сначала create_card")
    указатель = ГЕНОМ / "logs" / f"research_{ид}.json"
    if указатель.exists():
        д = json.loads(указатель.read_text(encoding="utf-8"))
        if not д.get("finished") and time.time() - указатель.stat().st_mtime < 3 * 3600:
            return f"исследование {ид} уже идёт (job {д.get('job')}) — смотри research_status", []
    повтор = ""
    if указатель.exists():
        import agent_jobs
        было = next((р for р in agent_jobs.работы() if р["id"] == ид), None)
        if было and было["сост"] in ("прервано", "мало данных", "ошибка", "остановлено"):
            повтор = str(было["job"])   # тот же job: движок прочтёт, что уже пробовали, и продолжит
    пров = getattr(КЛИЕНТ, "pid", "") or ""
    модель = getattr(КЛИЕНТ, "model", "") or ""
    if not (пров and модель):
        raise RuntimeError("не известна выбранная модель чата — анализ не запускаю")
    subprocess.Popen([_s.executable, str(HERE / "research_into.py"), ид, запрос, пров, модель, повтор],
                     cwd=str(ГЕНОМ), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     stdout=subprocess.DEVNULL, stderr=open(ГЕНОМ / "logs" / f"research_{ид}.err", "w", encoding="utf-8"))
    return ((f"ПРОДОЛЖАЮ прерванное исследование {повтор}: " if повтор else "") + f"запущено полное исследование «{запрос}» → карточка {ид} (модель {пров} {модель}). "
            "Идёт в фоне несколько минут: поиск источников, сцены с персонажем, улики по генам, сверка. "
            "Ход — research_status."), []


def и_research_status(a):
    ид = re.sub(r"[^a-z0-9_]", "", str(a.get("id") or "").lower())
    указатель = ГЕНОМ / "logs" / f"research_{ид}.json"
    if not указатель.exists():
        ош = ГЕНОМ / "logs" / f"research_{ид}.err"
        return ("исследование не запускалось" + (": " + ош.read_text(encoding="utf-8")[-400:] if ош.exists() and ош.stat().st_size else "")), []
    д = json.loads(указатель.read_text(encoding="utf-8"))
    сост = ГЕНОМ / "chars" / str(д.get("job")) / "state.json"
    # state.json движок пишет только в конце; живой ход — в events.jsonl (каждое событие сразу)
    живые = ГЕНОМ / "chars" / str(д.get("job")) / "events.jsonl"
    if not сост.exists():
        if not живые.exists():
            return f"job {д.get('job')} запущен {д.get('started')}, событий ещё нет", []
        ев = [json.loads(x) for x in живые.read_text(encoding="utf-8").splitlines() if x.strip()]
        прочитано = sum(1 for e in ев if e.get("stage") == "source")
        return (f"идёт · запущено {д.get('started')} · событий {len(ев)} · прочитано источников ~{прочитано}\n" +
                "\n".join(f"- {e.get('stage')}: {str(e.get('message'))[:160]}" for e in ев[-8:])), []
    s = json.loads(сост.read_text(encoding="utf-8"))
    # state.json пишется урывками и отстаёт; хвост событий берём из живого журнала
    события = ([json.loads(x) for x in живые.read_text(encoding="utf-8").splitlines() if x.strip()]
               if живые.exists() else (s.get("events") or []))
    карта = s.get("card") or {}
    строки = [f"состояние: {s.get('state')} · источников {len(s.get('sources') or [])} · "
              f"улик {len(s.get('evidence') or [])} · генов {len((карта.get('genome') or {}))}"
              + (f" · закончено {д.get('finished')}" if д.get("finished") else "")]
    строки += [f"- {e.get('stage')}: {str(e.get('message'))[:160]}" for e in события[-8:]]
    ош = ГЕНОМ / "logs" / f"research_{ид}.err"
    if ош.exists() and ош.stat().st_size:
        строки.append("ОШИБКИ процесса: " + ош.read_text(encoding="utf-8")[-400:])
    return "\n".join(строки), []


def и_review_genome(a):
    import subprocess, sys as _s
    ид = re.sub(r"[^a-z0-9_]", "", str(a.get("id") or "").lower())
    if not (SHARE / f"{ид}.genome.json").exists():
        raise RuntimeError(f"карточки {ид} нет")
    пров = getattr(КЛИЕНТ, "pid", "") or ""; модель = getattr(КЛИЕНТ, "model", "") or ""
    if not (пров and модель):
        raise RuntimeError("не известна выбранная модель чата — проверку не запускаю")
    subprocess.Popen([_s.executable, str(HERE / "review_genome.py"), ид, пров, модель], cwd=str(ГЕНОМ),
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), stdout=subprocess.DEVNULL,
                     stderr=open(ГЕНОМ / "logs" / f"review_{ид}.err", "w", encoding="utf-8"))
    return (f"запущена проверка генома {ид} на {пров} · {модель}: сверка каждой улики с геном (не про него / знак / перебор) "
            "и сверка сильнейших генов с самим текстом источников. Правки и отчёт — по завершении, ход в полосе работ."), []


def и_finish_character(a):
    import subprocess, sys as _s
    ид = re.sub(r"[^a-z0-9_]", "", str(a.get("id") or "").lower())
    if not (SHARE / f"{ид}.genome.json").exists():
        raise RuntimeError(f"карточки {ид} нет — сначала create_card")
    пров = getattr(КЛИЕНТ, "pid", "") or ""; модель = getattr(КЛИЕНТ, "model", "") or ""
    if not (пров and модель):
        raise RuntimeError("не известна выбранная модель чата — автопилот не запускаю")
    ук = ГЕНОМ / "logs" / f"auto_{ид}.json"
    if ук.exists():
        д = json.loads(ук.read_text(encoding="utf-8"))
        import agent_jobs
        if not д.get("finished") and agent_jobs._жив(д.get("pid")):
            return f"автопилот по {ид} уже идёт — его этапы видны в полосе работ", []
    subprocess.Popen([_s.executable, str(HERE / "autopilot.py"), ид, пров, модель], cwd=str(ГЕНОМ),
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), stdout=subprocess.DEVNULL,
                     stderr=open(ГЕНОМ / "logs" / f"auto_{ид}.err", "w", encoding="utf-8"))
    return (f"запущен автопилот {ид} на {пров} · {модель}: сам проходит этапы (анализ до 2 прогонов с потолком поиска 50 ₽, "
            "проверка, реплики, голос, промпт) и останавливается только на решениях владельца. Ход — в полосе работ."), []


def и_card_audit(a):
    import agent_jobs
    return agent_jobs.аудит(re.sub(r"[^a-z0-9_]", "", str(a.get("id") or "").lower())), []


def и_research_sources(a):
    import agent_jobs
    return agent_jobs.источники(re.sub(r"[^a-z0-9_]", "", str(a.get("id") or "").lower())), []


def и_jobs_list(a):
    import agent_jobs
    р = agent_jobs.работы()
    return ("\n".join(f"{x['id']}: {x['сост']} · старт {x['started']} · источников {x['источников']} · реплик ~{x['реплик']} · {x['последнее'][:120]}" for x in р)
            or "фоновых работ не было"), []


# ---- вызов инструмента, написанный текстом ----
# Некоторые модели (deepseek) иногда пишут вызов словами — «tool_call_name: read_card /
# tool_call_arguments: {...}» — вместо настоящего вызова. Раньше это уходило человеку как ответ
# и работа вставала. Теперь такой текст разбирается: имя из списка рук + JSON-объект рядом.
def вызовы_из_текста(текст):
    т = str(текст or "")
    if not т:
        return []
    вышло = []
    for имя in РУКИ:
        for m in re.finditer(r"\b" + re.escape(имя) + r"\b", т):
            кусок = т[m.end():m.end() + 4000]
            k = кусок.find("{")
            if k < 0 or k > 120:
                continue
            глубина, конец = 0, -1
            for i, ch in enumerate(кусок[k:], k):
                глубина += ch == "{"; глубина -= ch == "}"
                if глубина == 0:
                    конец = i; break
            if конец < 0:
                continue
            try:
                арг = json.loads(кусок[k:конец + 1])
            except Exception:
                continue
            if isinstance(арг, dict):
                арг = арг.get("arguments", арг) if set(арг) <= {"name", "arguments"} else арг
                вышло.append({"id": f"text_{len(вышло)}", "type": "function",
                              "function": {"name": имя, "arguments": json.dumps(арг, ensure_ascii=False)}})
            break
    return вышло


# ---- картинки: найти в сети / скачать и поставить / нарисовать в ComfyUI (pipeline/agent_images.py) ----
def и_find_images(a):
    import agent_images as И
    return И.find_images(str(a.get("query") or ""), a.get("n") or 8)


def и_set_avatar(a):
    import agent_images as И
    текст, ссылки = И.set_avatar(a.get("id"), str(a.get("url") or ""), a.get("index"))
    try:
        ф = SHARE / (И._id(a.get("id")) + ".genome.json")
        if ф.exists(): _переписать(ф, json.loads(ф.read_text(encoding="utf-8")))
    except Exception:
        pass
    return текст, ссылки


def и_gen_avatar(a):
    import agent_images as И
    текст, ссылки = И.gen_avatar(a.get("id"), str(a.get("prompt") or ""), str(a.get("style") or "anime"), a.get("seed"))
    try:
        ф = SHARE / (И._id(a.get("id")) + ".genome.json")
        if ф.exists(): _переписать(ф, json.loads(ф.read_text(encoding="utf-8")))
    except Exception:
        pass
    return текст, ссылки

РУКИ = {
    "search_web": (и_search_web, "Поиск в интернете. Возвращает заголовки, ссылки и выдержки.",
                   {"query": ("string", "поисковый запрос")}),
    "read_url": (и_read_url, "Открыть страницу и получить её текст.",
                 {"url": ("string", "адрес страницы")}),
    "list_chars": (и_list_chars, "Список персонажей в папке share/ с их видом и охватом.", {}),
    "read_card": (и_read_card, "Прочитать карточку персонажа. part: all | meta | genome | evidence | prompt.",
                  {"id": ("string", "идентификатор персонажа"), "part": ("string", "какую часть")}),
    "create_card": (и_create_card, "Завести НОВОГО персонажа с нуля, без исследования. "
                    "id латиницей, kind: персонаж | человек | ии | существо | синтез. "
                    "genes — объект {ген: [значение, уверенность]}; неподходящие виду гены отсеются.",
                    {"id": ("string", "идентификатор латиницей"), "name": ("string", "имя"),
                     "kind": ("string", "вид персонажа"), "alias": ("string", "короткий титул"),
                     "src": ("string", "произведение или откуда он"), "desc": ("string", "описание"),
                     "identity": ("string", "кем себя считает"), "voice": ("string", "как звучит"),
                     "samples": ("array", "примеры реплик"), "never": ("array", "чего никогда не делает"),
                     "genes": ("object", "гены {id: [value, confidence]}")}),
    "edit_card": (и_edit_card, "Изменить карточку: поля meta и/или значения генов. "
                               "genes — объект {ген: [значение, уверенность]}.",
                  {"id": ("string", "идентификатор"), "meta": ("object", "поля meta"),
                   "genes": ("object", "гены {id: [value, confidence]}")}),
    "find_genes": (и_find_genes, "Найти гены по слову в названии или описании — чтобы не выдумывать id.",
                   {"query": ("string", "слово для поиска")}),
    "make_prompt": (и_make_prompt, "Собрать системный промпт персонажа (promptsmith).",
                    {"id": ("string", "идентификатор")}),
    "find_images": (и_find_images, "Найти картинки персонажа в интернете (для существующих: аниме, фильмы, игры, реальные люди). "
                    "Отдаёт пронумерованных кандидатов с размером и источником. Выбирай официальный арт/вики, один человек в кадре, от 400 px.",
                    {"query": ("string", "запрос, лучше по-английски с названием произведения"), "n": ("integer", "сколько, до 15")}),
    "set_avatar": (и_set_avatar, "Скачать картинку и поставить аватаром персонажа (ava/<id>.jpg + вшивка в карточку). "
                   "url — прямая ссылка ИЛИ index — номер из последнего find_images.",
                   {"id": ("string", "идентификатор персонажа"), "url": ("string", "прямая ссылка на картинку"),
                    "index": ("integer", "номер из find_images")}),
    "gen_avatar": (и_gen_avatar, "Нарисовать аватар в локальном ComfyUI (сам запустит, если выключен) и поставить его. "
                   "Для синтезов и тех, у кого нет картинок в сети. prompt — английские теги внешности; style: anime | real.",
                   {"id": ("string", "идентификатор персонажа"), "prompt": ("string", "теги внешности по-английски"),
                    "style": ("string", "anime или real"), "seed": ("integer", "зерно, необязательно")}),
    "research_genome": (и_research_genome, "ПОЛНЫЙ анализ персонажа: в фоне ищет источники (вики, сценарии, субтитры), "
                        "режет сцены с персонажем, снимает улики по всем группам генов, сверяет противоречия и вливает геном "
                        "в карточку id. Для существующих персонажей. Идёт минуты — после запуска скажи человеку и проверяй research_status.",
                        {"id": ("string", "идентификатор карточки"), "query": ("string", "имя + произведение, лучше по-английски")}),
    "finish_character": (и_finish_character, "ДОВЕСТИ ПЕРСОНАЖА ДО КОНЦА САМОМУ: автопилот сам проходит все этапы — анализ (до 2 прогонов), "
                         "проверка улик, реплики из текста, голос, промпт — и останавливается только на решениях владельца. "
                         "Зови, когда просят полный анализ, «доделай», «доведи», «заверши». Фон, десятки минут.",
                         {"id": ("string", "идентификатор карточки")}),
    "review_genome": (и_review_genome, "ПРОВЕРКА уже собранного генома без новых поисков: каждая улика сверяется с геном "
                      "(улика не про него, перепутан знак, перебор силы), сильнейшие гены — с самим текстом источников; "
                      "поправки вносятся в карточку с записью «было → стало», отчёт в chars/review_*/review.md. Фон, минуты.",
                      {"id": ("string", "идентификатор карточки")}),
    "card_audit": (и_card_audit, "Проверка карточки: охват генома по блокам, улики, образцы реплик, голос, аватар, промпт "
                   "и список «НЕ ХВАТАЕТ». Зови перед тем, как сказать «готово», и после каждого этапа.",
                   {"id": ("string", "идентификатор карточки")}),
    "research_sources": (и_research_sources, "Что исследование реально прочитало: источники, объём, реплики персонажа, отказы.",
                         {"id": ("string", "идентификатор карточки")}),
    "jobs_list": (и_jobs_list, "Все фоновые работы: идёт / готово / прервано / мало данных.", {}),
    "research_status": (и_research_status, "Ход фонового исследования: стадия, источники, улики, гены, последние события.",
                        {"id": ("string", "идентификатор карточки")}),
    "read_upload": (и_read_upload, "Прочитать текст прикреплённого пользователем файла.",
                    {"name": ("string", "имя файла")}),
}


def схема():
    вышло = []
    for имя, (_, опис, поля) in РУКИ.items():
        # У массива обязан быть тип элементов, иначе строгие провайдеры отвергают
        # описание инструмента целиком — и модель остаётся вообще без рук.
        свойства = {}
        for k, (t, d) in поля.items():
            # ВНИМАНИЕ: переменную здесь нельзя звать «опис» — этим именем выше распакован
            # текст описания самого инструмента. Затирание уводило в description словарь
            # последнего поля, и стык отвергал весь пакет инструментов целиком.
            поле = {"type": t, "description": d}
            if t == "array":
                поле["items"] = {"type": "string"}
            свойства[k] = поле
        вышло.append({"type": "function", "function": {
            "name": имя, "description": опис,
            "parameters": {"type": "object", "properties": свойства,
                           "required": [k for k in list(поля)[:1]]}}})
    return вышло


# ---------------------------------------------------------------- вложения

ТЕКСТОВЫЕ = (".txt", ".md", ".json", ".csv", ".py", ".js", ".html", ".srt", ".vtt", ".log", ".yml", ".yaml")


def разобрать_вложения(файлы):
    """Картинку отдаём модели как картинку, документ — как текст."""
    готово = []
    for ф in файлы or []:
        имя = str(ф.get("name") or "файл")
        mime = str(ф.get("mime") or "")
        данные = str(ф.get("data") or "")
        запись = {"name": имя, "mime": mime, "text": "", "image": ""}
        if mime.startswith("image/"):
            запись["image"] = данные if данные.startswith("data:") else f"data:{mime};base64,{данные}"
        else:
            сырьё = b""
            try:
                сырьё = base64.b64decode(данные.split(",", 1)[-1])
            except Exception:
                запись["text"] = данные
            if сырьё:
                if имя.lower().endswith(".pdf"):
                    запись["text"] = _pdf(сырьё)
                elif имя.lower().endswith(".docx"):
                    запись["text"] = _docx(сырьё)
                elif имя.lower().endswith(ТЕКСТОВЫЕ) or mime.startswith("text/"):
                    запись["text"] = сырьё.decode("utf-8", "replace")
                else:
                    запись["text"] = сырьё.decode("utf-8", "replace")[:ПРЕДЕЛ_ТЕКСТА]
        готово.append(запись)
    return готово


def _pdf(сырьё):
    import io
    for модуль in ("pdfminer.high_level", "PyPDF2", "pypdf"):
        try:
            if модуль == "pdfminer.high_level":
                from pdfminer.high_level import extract_text
                return extract_text(io.BytesIO(сырьё)) or ""
            mod = __import__(модуль)
            чтец = mod.PdfReader(io.BytesIO(сырьё))
            return "\n".join((s.extract_text() or "") for s in чтец.pages)
        except Exception:
            continue
    return "(PDF не разобрался: не установлен pdfminer.six)"


def _docx(сырьё):
    import io, zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(сырьё)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)
    except Exception as e:
        return f"(docx не разобрался: {e})"


def все_стыки():
    """Все стыки, у которых во вкладке «API» лежит ключ — в порядке появления."""
    ряд = []
    for файл in (ГЕНОМ / "api_keys.json", HERE / "api_keys.json"):
        try:
            if not файл.exists():
                continue
            д = json.loads(файл.read_text(encoding="utf-8"))
        except Exception:
            continue
        for ветка in [д] + ([д["keys"]] if isinstance(д.get("keys"), dict) else []):
            for имя, зн in (ветка or {}).items():
                ключ = зн.get("key") if isinstance(зн, dict) else зн
                if isinstance(ключ, str) and len(ключ.strip()) > 12 and имя not in ряд:
                    ряд.append(имя)
    return ряд


ПЕРЕБОР = ("429", "401", "402", "403", "quota", "insufficient", "expired", "invalid_api_key")
# Отдельно от квот: на этой модели нет зрения. Перебирать стыки бессмысленно —
# нужна другая модель, и человеку надо сказать об этом словами, а не кодом ошибки.
БЕЗ_ЗРЕНИЯ = ("image", "vision", "multimodal", "image_url")


def почему(текст):
    """Человеческая причина вместо сырого JSON провайдера."""
    т = str(текст).lower()
    if any(з in т for з in ("image", "vision", "multimodal", "image_url")):
        return "эта модель не умеет смотреть картинки"
    if "429" in т or "quota" in т or "insufficient" in т:
        return "кончилась квота"
    if "401" in т or "invalid_api_key" in т:
        return "ключ не принят"
    if "402" in т:
        return "нужен платёж"
    if "403" in т:
        return "доступ закрыт"
    return str(текст)[:200]


def стоит_переключиться(ошибка):
    т = str(ошибка).lower()
    return any(з in т for з in ПЕРЕБОР)


def выбрать_провайдера():
    """Кого звать, если студия не сказала явно.

    Жёстко зашитый chadapi — это ставка на то, что ключ вписан именно туда.
    Правильнее спросить у самой студии: берём первый стык, у которого во вкладке
    «API» лежит непустой ключ, и говорим об этом вслух в окне.
    """
    for файл in (ГЕНОМ / "api_keys.json", HERE / "api_keys.json"):
        try:
            if not файл.exists():
                continue
            д = json.loads(файл.read_text(encoding="utf-8"))
        except Exception:
            continue
        ветки = [д] + ([д["keys"]] if isinstance(д.get("keys"), dict) else [])
        for ветка in ветки:
            for имя, зн in (ветка or {}).items():
                ключ = зн.get("key") if isinstance(зн, dict) else зн
                if isinstance(ключ, str) and len(ключ.strip()) > 12:
                    return имя
    return "chadapi"


# ---------------------------------------------------------------- цикл

def main():
    # Без stdin висеть вечно нельзя: скрипт иногда запускают руками или через агента,
    # и тогда read() блокировал бы процесс до таймаута задания.
    if sys.stdin is None or sys.stdin.isatty():
        шлём(t="error", text="chat.py читает запрос со стандартного ввода — его запускает студия, а не человек")
        return
    сырой = sys.stdin.read()
    try:
        зов = json.loads(сырой or "{}")
    except Exception as e:
        шлём(t="error", text=f"сломанный запрос: {e}"); return

    global ВЛОЖЕНИЯ
    история = зов.get("messages") or []
    ВЛОЖЕНИЯ = разобрать_вложения((история[-1] if история else {}).get("files"))

    from llm import Client
    провайдер = зов.get("provider") or os.environ.get("GENOME_PROVIDER") or выбрать_провайдера()
    модель = зов.get("model") or os.environ.get("GENOME_MODEL") or None
    try:
        if not модель:
            # раньше Client молча брал первую модель провайдера — человек выбирал одно, работало другое
            raise RuntimeError("модель не выбрана — выбери её внизу чата")
        клиент = Client(provider=провайдер, model=модель, timeout=180)
        if not клиент.key:
            raise RuntimeError("нет ключа: вставь его во вкладке API")
    except Exception as e:
        шлём(t="error", text=str(e)); return
    шлём(t="step", text=f"модель: {клиент.pid} · {клиент.model}")

    систем = о_проекте()
    # Характер ассистента задаётся тем же способом, что и любой персонаж здесь:
    # карточкой в share/. Лежит assistant.genome.json с собранным промптом — говорит им.
    try:
        свой = SHARE / "assistant.genome.json"
        if свой.exists():
            к = json.loads(свой.read_text(encoding="utf-8"))
            голос = ((к.get("meta") or {}).get("prompt") or "").strip()
            if len(голос) > 100:
                систем += "\n\nТВОЙ ХАРАКТЕР (карточка assistant в share/):\n" + голос
    except Exception:
        pass
    карточка = str(зов.get("id") or "")
    if карточка:
        try:
            _, карта = _карточка(карточка)
            м = карта.get("meta") or {}
            систем += (f"\n\nСЕЙЧАС ОТКРЫТ ПЕРСОНАЖ: id={карточка}, {м.get('name','')} «{м.get('alias','')}», "
                       f"вид={м.get('kind','')}, произведение: {м.get('src','')}. "
                       f"Снято генов: {len(карта.get('genome') or {})}. "
                       f"Когда человек говорит «он/она/этот персонаж» — речь о нём.")
        except Exception:
            pass

    сообщения = [{"role": "system", "content": систем}]
    for ход in история:
        роль = "assistant" if ход.get("role") == "assistant" else "user"
        текст = str(ход.get("content") or "")
        сообщения.append({"role": роль, "content": текст})

    if ВЛОЖЕНИЯ:
        куски = []
        картинки = []
        сырые_картинки = []
        for ф in ВЛОЖЕНИЯ:
            if ф["image"]:
                картинки.append({"type": "image_url", "image_url": {"url": ф["image"]}})
                сырые_картинки.append(ф["image"])
                шлём(t="step", text=f"прикреплена картинка: {ф['name']}")
            elif ф["text"]:
                куски.append(f"=== файл {ф['name']} ===\n{обрезать(ф['text'], 20000)}")
                шлём(t="step", text=f"прочитан файл: {ф['name']} · {len(ф['text'])} знаков")
        if картинки:
            систем += ("\n\nСЕЙЧАС ПРИЛОЖЕНО ИЗОБРАЖЕНИЕ. Если ты его видишь — первым делом скажи "
                       "своими словами, что на нём, и предложи очевидное действие одним вопросом "
                       "(«вижу страницу про такого-то — заводим карточку?»). Если НЕ видишь — скажи "
                       "об этом прямо и попроси текстом. Ни при каких условиях не выдумывай "
                       "содержимое картинки по имени файла.")
        # Картинку отдаём модели напрямую, только если она умеет смотреть. Иначе зовём
        # зрячую, получаем описание словами и работаем дальше прежней моделью.
        if картинки and not видит(клиент.model):
            описание, кто = "", ""
            try:
                описание, кто = посмотреть_чужими_глазами(сырые_картинки)
            except Exception as e:
                шлём(t="step", text=f"распознать не вышло: {почему(e)}")
            if not описание:
                буквы = прочитать_буквы(сырые_картинки)
                if буквы:
                    описание, кто = буквы, "локальное распознавание текста"
            if описание:
                куски.append(f"=== что на приложенной картинке (посмотрел {кто}) ===\n{описание}")
                шлём(t="tool", name="зрение", arg=кто, out=обрезать(описание, 900), links=[], sec=0)
                картинки = []
            else:
                куски.append("=== приложена картинка, но посмотреть её нечем: "
                             "ни одна доступная модель не умеет смотреть изображения ===")
                картинки = []

        хвост = сообщения[-1]
        if куски:
            хвост["content"] = str(хвост.get("content") or "") + "\n\n" + "\n\n".join(куски)
        if картинки:
            хвост["content"] = [{"type": "text", "text": str(хвост.get("content") or "")}] + картинки

    инструменты = схема()
    global КЛИЕНТ
    КЛИЕНТ = клиент
    # ---- учебный блок: работа не теряется между сообщениями ----
    # chat.py живёт один ответ, а исследование — минуты и может оборваться (выключили ПК, упал процесс).
    # Поэтому при КАЖДОМ сообщении проверяем фоновые работы: прерванные ассистент продолжает сам,
    # идущие — знает и может доложить ход. Человек видит то же самое в полосе работ над полем ввода.
    try:
        import agent_jobs
        вся = agent_jobs.работы()
        нз = [р for р in вся if р["сост"] == "прервано"]
        идут = [р for р in вся if р["сост"] == "идёт"]
        if нз or идут:
            заметка = "\n\nФОНОВЫЕ РАБОТЫ СЕЙЧАС:\n" + "\n".join(
                f"- {р['id']}: {р['сост']} (источников {р['источников']}, реплик ~{р['реплик']}; последнее: {р['последнее'][:100]})" for р in нз + идут)
            if нз:
                заметка += ("\nПРЕРВАННОЕ НАДО ПРОДОЛЖИТЬ: вызови research_genome с тем же id — продолжится тот же прогон. "
                            "Скажи человеку одной строкой, что продолжаешь.")
            if сообщения and сообщения[0].get("role") == "system":
                сообщения[0]["content"] = str(сообщения[0]["content"]) + заметка
            шлём(t="step", text="фоновые работы: " + "; ".join(f"{р['id']} — {р['сост']}" for р in нз + идут))
    except Exception as e:
        шлём(t="step", text=f"проверка фоновых работ не удалась: {e}")
    # Запасные стыки: если у выбранного кончилась квота или не принят ключ, разговор
    # не должен на этом заканчиваться — берём следующий вписанный и говорим об этом вслух.
    запас = []   # перескок на другие стыки выключен: работает только выбранная модель (правило владельца)

    def позвать():
        nonlocal клиент
        пока = None
        while True:
            try:
                return клиент.chat_tools(сообщения, инструменты, temperature=0.3, max_tokens=2600)
            except Exception as e:
                пока = e
                if not (стоит_переключиться(e) and запас):
                    raise
                следующий = запас.pop(0)
                шлём(t="step", text=f"у {клиент.pid} {почему(e)}, отвечаю через {следующий}")
                try:
                    клиент = Client(provider=следующий, timeout=180)
                except Exception:
                    continue
            
    вызвано, поправлен = set(), False   # какие инструменты реально вызваны в этом ответе — для проверки заявлений
    for шаг in range(ПРЕДЕЛ_ШАГОВ):
        try:
            ответ = позвать()
        except Exception as e:
            текст = f"{клиент.pid}: {почему(e)}"
            if any(з in str(e).lower() for з in БЕЗ_ЗРЕНИЯ):
                текст += ". Выбери модель со зрением внизу окна или опиши картинку текстом."
            шлём(t="error", text=текст); return
        зовы = ответ.get("tool_calls") or []
        if not зовы:
            зовы = вызовы_из_текста(ответ.get("content"))
            if зовы:
                шлём(t="step", text="модель написала вызов текстом — исполняю как вызов")
                ответ = {"content": "", "tool_calls": зовы}
        if not зовы:
            текст = ответ.get("content") or ""
            # ---- учебный блок: проверка заявлений ----
            # 04.10 на «доделай» модель ответила «Запустил полный анализ», не вызвав ни одного инструмента.
            # Теперь заявление о запуске без настоящего вызова возвращается ей: вызови или признай.
            if (not поправлен and re.search(r"запустил|запущен|запускаю|начал[аи]? (анализ|проверк|исследов)", текст, re.I)
                    and not (вызвано & {"research_genome", "review_genome", "finish_character"})):
                поправлен = True
                шлём(t="step", text="проверка заявлений: модель написала «запустил», но инструмент не вызывала — возвращаю ей")
                сообщения.append({"role": "assistant", "content": текст})
                сообщения.append({"role": "user", "content": "Ты написал, что запустил работу, но не вызвал ни одного инструмента — "
                                  "ничего не запущено. Вызови нужный инструмент сейчас или честно скажи, что не запускал."})
                continue
            шлём(t="reply", text=текст or "(модель промолчала)")
            return
        сообщения.append({"role": "assistant", "content": ответ.get("content") or "", "tool_calls": зовы})
        if ответ.get("content"):
            шлём(t="step", text=ответ["content"][:400])
        for з in зовы:
            фн = (з.get("function") or {})
            имя = фн.get("name") or ""
            try:
                арг = json.loads(фн.get("arguments") or "{}")
            except Exception:
                арг = {}
            вызвано.add(имя)
            коротко = ", ".join(f"{k}={str(v)[:60]}" for k, v in арг.items())
            шлём(t="step", text=f"{имя}({коротко})")
            t0 = time.time()
            try:
                рука = РУКИ.get(имя)
                if not рука:
                    вышло, ссылки = f"нет такого инструмента: {имя}", []
                else:
                    вышло, ссылки = рука[0](арг)
            except Exception as e:
                вышло, ссылки = f"ОШИБКА: {e}", []
            шлём(t="tool", name=имя, arg=коротко, out=обрезать(вышло, 1400),
                 links=ссылки, sec=round(time.time() - t0, 1))
            # Как только стало ясно, над кем работаем, — сообщаем студии, чтобы беседа
            # получила имя персонажа вместо случайной первой фразы.
            если_про = арг.get("id") if имя in ("create_card", "edit_card", "read_card",
                                                "make_prompt") else None
            if если_про:
                try:
                    _, карточка = _карточка(если_про)
                    шлём(t="тема", id=str(если_про),
                         name=((карточка.get("meta") or {}).get("name") or "").strip())
                except Exception:
                    pass
            сообщения.append({"role": "tool", "tool_call_id": з.get("id") or имя,
                              "name": имя, "content": обрезать(вышло)})
    шлём(t="reply", text="Упёрся в потолок шагов — расскажи, что из найденного разобрать дальше.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        шлём(t="error", text=str(e)[:500])
