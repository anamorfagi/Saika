# -*- coding: utf-8 -*-
"""research_into.py — полное исследование персонажа в фоне, с записью в ЕГО карточку.

Запускает ассистент студии (инструмент research_genome). Движок — research.ResearchJob:
карта источников → чтение → сцены с персонажем → улики по группам генов → сверка → добор пробелов.
Сам движок заводит карточку research_…; здесь результат вливается в существующую карточку
(аватар и то, что вписал человек, остаются), а файл research_… уходит в папку прогона chars/<job>/.

---- учебный блок: почему отдельный процесс ----
Исследование идёт минуты, а chat.py живёт один ответ. Поэтому chat.py только запускает
этот скрипт; ход виден в logs/research_<id>.json (там же расход: вызовы, токены, секунды)
и chars/<job>/events.jsonl.

Запуск:        py -3 research_into.py <id> "<запрос>" [провайдер] [модель] [job-для-продолжения]
Спасти итог:   py -3 research_into.py --recover <id> <job>   (влить готовый результат прогона в карточку)
"""
import sys, json, time, pathlib, os, threading
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHARE, LOGS, CHARS = ROOT / "share", ROOT / "logs", ROOT / "chars"


def списком(x):
    """create_card пишет identity строкой, движок — списком; 04.10 их сложение уронило вливание."""
    if isinstance(x, list):
        return x
    return [x] if x else []


def пересобрать_список():
    cards = []
    for p in sorted(SHARE.glob("*.genome.json")):
        try:
            c = json.loads(p.read_text(encoding="utf-8")); c.pop("avatar", None)
            if c.get("format") == "saika-genome/1": cards.append(c)
        except (ValueError, OSError):
            continue
    tmp = SHARE / "_list.tmp"
    tmp.write_text("window.__SHARE=" + json.dumps(cards, ensure_ascii=False) + ";\n", encoding="utf-8")
    tmp.replace(SHARE / "_list.js")


# ---- учебный блок: как считается цена ----
# Провайдер берёт деньги за токены: входные (что мы отправили) и выходные (что модель написала).
# Цена = вход/1e6 × цена_входа + выход/1e6 × цена_выхода. Цены лежат в prices.json; для gemini-2.5-flash
# они вычислены по реальным строкам лога ProxyAPI, для остальных — оценка, её надо сверить с логом.
def прайс():
    try:
        return json.loads((pathlib.Path(__file__).parent / "prices.json").read_text(encoding="utf-8"))
    except Exception:
        return {"budget_rub": 50, "models": {}, "_если_модели_нет": {"in": 300, "out": 1500}}


def рублей(usage, модель, пр=None):
    пр = пр or прайс()
    ц = (пр.get("models") or {}).get(модель) or пр.get("_если_модели_нет") or {"in": 300, "out": 1500}
    return (usage.get("prompt", 0) * ц["in"] + usage.get("completion", 0) * ц["out"]) / 1e6


def влить_в(цель, карта, job_id=""):
    """Слить результат исследования в карточку цели. Возвращает число генов."""
    файл = SHARE / f"{цель}.genome.json"
    старая = json.loads(файл.read_text(encoding="utf-8")) if файл.exists() else {}
    новая = json.loads(json.dumps(карта, ensure_ascii=False))
    новая["id"] = цель
    # ---- учебный блок: накопление генома ----
    # Ген есть в старой и новой карточке → улики объединяются, значение — среднее с весом уверенности,
    # уверенность растёт как у независимых свидетелей: 1−(1−c1)(1−c2), не выше 0.85. Ген только в старой — остаётся.
    стар_г, нов_г = старая.get("genome") or {}, новая.setdefault("genome", {})
    for gid, s in стар_г.items():
        if not (isinstance(s, list) and len(s) > 1):
            continue
        n = нов_г.get(gid)
        if not (isinstance(n, list) and len(n) > 1):
            нов_г[gid] = s; continue
        c1, c2 = float(s[1] or 0), float(n[1] or 0)
        v = (float(s[0]) * c1 + float(n[0]) * c2) / ((c1 + c2) or 1)
        ул = list(s[2] if len(s) > 2 and isinstance(s[2], list) else [])
        for u in (n[2] if len(n) > 2 and isinstance(n[2], list) else []):
            if u not in ул: ул.append(u)
        нов_г[gid] = [round(v, 3), round(min(0.85, 1 - (1 - c1) * (1 - c2)), 3), ул]
    новая["genes_captured"] = len(нов_г)
    if старая.get("avatar"):
        новая["avatar"] = старая["avatar"]
    m_old, m_new = старая.get("meta") or {}, новая.setdefault("meta", {})
    for k in ("name", "alias", "avatar_src", "img_prompt"):
        if m_old.get(k):
            m_new[k] = m_old[k]
    for k in ("samples", "never", "identity"):   # вписанное руками не теряем, найденное добавляем
        было, стало = списком(m_old.get(k)), списком(m_new.get(k))
        m_new[k] = было + [x for x in стало if x not in было]
    m_new.setdefault("research", {})["into"] = цель
    for k in ("review", "prompt", "prompt_by", "voice"):          # проверки, промпт и голос не теряем
        if m_old.get(k) and not m_new.get(k):
            m_new[k] = m_old[k]
    if isinstance(m_old.get("voice"), dict) and m_old["voice"].get("timbre"):
        m_new["voice"] = m_old["voice"]
    m_new["research_jobs"] = list(dict.fromkeys((m_old.get("research_jobs") or []) + [x for x in [(m_old.get("research") or {}).get("job"), job_id] if x]))
    m_new["analyzed_at"] = time.strftime("%Y-%m-%d %H:%M")
    SHARE.mkdir(exist_ok=True)
    файл.write_text(json.dumps(новая, ensure_ascii=False, indent=2), encoding="utf-8")
    # файл research_<job> движок кладёт в share/ — убираем его в папку прогона, чтобы в списке не было двойника
    if job_id:
        лишний = SHARE / f"{job_id}.genome.json"
        if лишний.exists():
            (CHARS / job_id).mkdir(parents=True, exist_ok=True)
            лишний.replace(CHARS / job_id / "card.genome.json")
    пересобрать_список()
    return len(новая.get("genome") or {})


def main():
    from research import ResearchJob
    цель, запрос = sys.argv[1], sys.argv[2]
    if not (len(sys.argv) > 4 and sys.argv[3] and sys.argv[4]):
        sys.exit("нужны провайдер и модель: анализ идёт только на выбранной модели")
    if цель.startswith("-"):
        sys.exit("неизвестный ключ: " + цель)   # 04.10 «--recover» старой версией ушёл в запуск исследования
    cfg = {"provider": sys.argv[3] if len(sys.argv) > 3 else "", "model": sys.argv[4] if len(sys.argv) > 4 else ""}
    повтор = sys.argv[5] if len(sys.argv) > 5 else ""   # job прерванного прогона: продолжаем его
    указатель = LOGS / f"research_{цель}.json"
    job = ResearchJob(запрос, "", {k: v for k, v in cfg.items() if v}, повтор=повтор)
    LOGS.mkdir(exist_ok=True)
    д = {"job": job.id, "pid": os.getpid(), "query": запрос, "cfg": cfg, "model": job.client.model,
         "provider": job.client.pid, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    lock = threading.Lock()
    пр = прайс()
    import spend
    from research import Cancelled
    потолок, потолок_работы = spend.остаток(цель)   # остаток кошелька персонажа, а не отдельный лимит на прогон
    д["budget"] = round(потолок, 2); д["budget_work"] = round(потолок_работы, 2)
    if потолок_работы < 0.5:
        sys.exit(f"кошелёк персонажа {цель} на работу исчерпан — анализ не запускаю")
    # ---- учебный блок: поиск отдельно от работы ----
    # Поиск = распознавание, охота модели за источниками, проверка страниц. Работа = разбор сцен в улики,
    # сверка противоречий, описание. Пока идёт работа, счётчик job._работа > 0 — вызовы в это время
    # идут в «работу» и потолком не режутся. Всё остальное — «поиск», ему потолок budget_rub (50 ₽).
    траты = {"поиск": 0.0, "работа": 0.0}
    дороже = [0.0]              # самый дорогой вызов поиска — запас, чтобы следующий не пробил потолок
    job._работа = 0
    вход = [0.0]
    вызовов_работы = [0]
    job._поиск_закрыт = False
    for метод in ("разобрать_пачкой", "сверить_противоречия", "describe"):
        if hasattr(job, метод):
            исх = getattr(job, метод)
            def обёртка(*a, _исх=исх, **k):
                if job._работа == 0:
                    вход[0] = рублей(job.client.usage, job.client.model, пр)
                job._работа += 1
                try:
                    return _исх(*a, **k)
                finally:
                    job._работа -= 1
                    if job._работа == 0:   # вышли из работы: весь прирост за это время — работа
                        траты["работа"] += рублей(job.client.usage, job.client.model, пр) - вход[0]
            setattr(job, метод, обёртка)

    исходный_поиск = job.search_for
    def поиск_с_потолком(*a, **k):
        if job._поиск_закрыт and not job._работа:
            return []          # бюджет поиска исчерпан — новых кандидатов нет
        return исходный_поиск(*a, **k)
    job.search_for = поиск_с_потолком

    def закрыть_поиск(потрачено):
        if not job._поиск_закрыт:
            job._поиск_закрыт = True
            job.emit("budget", f"Поиск: потрачено ≈{потрачено:.1f} ₽ из {потолок:.0f} ₽ — поиск закрыт. "
                               "Разбираю то, что уже найдено (у разбора свой кошелёк).")

    def с_потолком(имя):
        исходный = getattr(job.client, имя)
        def вызов(*a, **k):
            работа = job._работа > 0
            траты["поиск"] = max(0.0, рублей(job.client.usage, job.client.model, пр) - траты["работа"])
            if работа:
                в_работе = траты["работа"] + (рублей(job.client.usage, job.client.model, пр) - вход[0])
                вызовов_работы[0] += 1
                средний = в_работе / max(1, вызовов_работы[0] - 1) if вызовов_работы[0] > 1 else 0
                if в_работе + средний > потолок_работы:   # запас на ещё один средний вызов
                    if not job.cancelled.is_set():
                        job.emit("budget", f"Кошелёк работы персонажа исчерпан ({потолок_работы:.1f} ₽): останавливаю разбор, собранное вливаю")
                        job.cancelled.set()
                    raise Cancelled()
            if not работа and (job._поиск_закрыт or траты["поиск"] + дороже[0] > потолок):
                закрыть_поиск(траты["поиск"])
                if имя == "chat_tools":   # охота: мягко останавливаем, чтобы она вернула уже взятое
                    return {"content": "", "tool_calls": [{"id": "budget", "type": "function", "function": {
                        "name": "stop", "arguments": json.dumps({"summary": "потолок трат на поиск"}, ensure_ascii=False)}}]}
                raise RuntimeError("потолок трат на поиск исчерпан")
            до = рублей(job.client.usage, job.client.model, пр)
            r = исходный(*a, **k)
            if not работа:   # поиск идёт по одному вызову — прирост честный; берём самый дорогой как запас
                дороже[0] = max(дороже[0], рублей(job.client.usage, job.client.model, пр) - до)
            return r
        setattr(job.client, имя, вызов)
    for имя in ("chat", "chat_tools", "chat_parts"):
        if hasattr(job.client, имя):
            с_потолком(имя)

    def записать():
        with lock:
            д["usage"] = dict(job.client.usage)
            д["rub"] = round(рублей(job.client.usage, job.client.model, пр), 2)
            всего = рублей(job.client.usage, job.client.model, пр)
            работа = траты["работа"] + ((всего - вход[0]) if job._работа else 0)
            д["rub_search"] = round(max(0.0, всего - работа), 2); д["rub_work"] = round(работа, 2)
            указатель.write_text(json.dumps(д, ensure_ascii=False), encoding="utf-8")
    записать()

    def расход():   # каждые 5 с — расход в указатель: полоса работ показывает вызовы/токены/время по правде
        while not job.done:
            time.sleep(5)
            try: записать()
            except Exception: pass
    threading.Thread(target=расход, daemon=True).start()

    def влить():
        n = влить_в(цель, job.card, job.id)
        job.emit("done", f"Влито в карточку {цель}: {n} генов")
    job.publish = влить
    job.run()
    if job.state in ("insufficient", "error", "cancelled") and job.evidence:
        # улики собраны, но финал не прошёл — всё равно вливаем: частичный геном с уликами лучше пустого
        try:
            влить()
        except Exception as e:
            job.emit("error", "вливание не удалось: " + str(e)[:200])
    д.update(finished=time.strftime("%Y-%m-%d %H:%M:%S"), state=job.state)
    записать()
    spend.записать(цель, "анализ", д.get("rub_search", 0), д.get("rub_work", 0), job.client.model)


def recover(цель, job_id):
    карта_ф = SHARE / f"{job_id}.genome.json"
    if not карта_ф.exists():
        карта_ф = CHARS / job_id / "card.genome.json"
    if карта_ф.exists():
        карта = json.loads(карта_ф.read_text(encoding="utf-8"))
    else:
        карта = json.loads((CHARS / job_id / "state.json").read_text(encoding="utf-8"))["card"]
    n = влить_в(цель, карта, job_id)
    print(f"влито в {цель}: {n} генов из {job_id}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--recover"]:
        recover(sys.argv[2], sys.argv[3])
    else:
        main()
