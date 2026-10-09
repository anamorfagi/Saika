# -*- coding: utf-8 -*-
"""autopilot.py — довести персонажа до конца САМОМУ, этап за этапом, на выбранной модели.

---- учебный блок: как автопилот решает, что делать ----
Каждый круг он заново меряет готовность (те же 7 этапов, что видны в полосе работ) и делает первое
недоделанное:
  источники / разбор → новый прогон анализа (до 2 прогонов; поиск в каждом ≤ 50 ₽, разбор — работа)
  проверка           → review_genome, если после последнего разбора проверки не было
  реплики            → из прочитанных текстов берутся его настоящие фразы, модель выбирает 8 из разных ситуаций
  голос              → описание голоса и манеры по тем же фразам
  промпт             → promptsmith на той же модели
  решения            → это делает ВЛАДЕЛЕЦ: автопилот не трогает, а в конце пишет, сколько ждут
Всё видно в полосе работ: logs/auto_<id>.json + chars/auto_<id>_<время>/events.jsonl.

Запуск: py -3 autopilot.py <id> <провайдер> <модель>
"""
import sys, json, time, os, re, pathlib, subprocess, random
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parent
SHARE, LOGS, CHARS = ROOT / "share", ROOT / "logs", ROOT / "chars"
ПРОГОНОВ_АНАЛИЗА = 2


def готовность(ид):
    к = json.loads((SHARE / f"{ид}.genome.json").read_text(encoding="utf-8"))
    m, г, вид = к.get("meta") or {}, к.get("genome") or {}, (к.get("meta") or {}).get("kind", "персонаж")
    всего = снято = пустых = улик = 0
    for b in json.loads((HERE / "genes.json").read_text(encoding="utf-8")):
        ids = [g["id"] for g in b["genes"]]
        if not ids: continue
        p = ids[0].split(".")[0]
        if (p == "beast" and вид != "существо") or (p == "nat" and вид != "ии"): continue
        есть = [i for i in ids if i in г]; всего += len(ids); снято += len(есть)
        улик += sum(len(г[i][2]) for i in есть if isinstance(г[i], list) and len(г[i]) > 2 and isinstance(г[i][2], list))
        if len(есть) / len(ids) < .3: пустых += 1
    рев = (m.get("review") or [None])[-1]
    голос = m.get("voice"); голос = голос.get("timbre") if isinstance(голос, dict) else голос
    return {"источники": bool((m.get("research") or {}).get("job")) or улик > 0, "разбор": снято >= всего * .5 or пустых == 0,
            "проверка": bool(рев) and рев.get("at", "") >= m.get("analyzed_at", ""), "реплики": len(m.get("samples") or []) >= 5,
            "голос": bool(голос), "промпт": bool(m.get("prompt")),
            "ждут": len([x for x in (рев or {}).get("предложения", []) if not x.get("решено")]),
            "цифры": f"генов {снято}/{всего}, пустых блоков {пустых}, улик {улик}"}, к


def тексты(к):
    """Все прочитанные тексты по всем прогонам анализа этой карточки."""
    jobs = list(dict.fromkeys([j for j in ((к.get("meta") or {}).get("research_jobs") or []) + [((к.get("meta") or {}).get("research") or {}).get("job")] if j]))
    out = []
    for j in jobs:
        for f in sorted((CHARS / j).glob("source_*.txt")):
            out.append(f.read_text(encoding="utf-8", errors="replace"))
    return out


def его_реплики(тексты_, имена, n=80):
    """Его настоящие фразы из прочитанного: кавычки, рядом с которыми стоит его имя (как в research.реплик_в_прозе)."""
    ключи = [re.sub(r"[^0-9a-zа-яё]+", "", x.lower()) for x in имена if x]
    out = []
    for т in тексты_:
        for m in re.finditer(r'[“"«]([^”"»\n]{12,300})[”"»]', т):
            рядом = re.sub(r"[^0-9a-zа-яё]+", "", (т[max(0, m.start() - 140):m.start()] + т[m.end():m.end() + 140]).lower())
            if any(k and k in рядом for k in ключи):
                out.append({"t": m.group(1).strip(), "вокруг": т[max(0, m.start() - 220):m.end() + 120].replace("\n", " ")})
    random.shuffle(out)
    return out[:n]


def main():
    from llm import Client
    from research import object_response
    from research_into import рублей, прайс, пересобрать_список
    ид, пров, модель = sys.argv[1], sys.argv[2], sys.argv[3]
    if not (пров and модель):
        sys.exit("нужны провайдер и модель")
    папка = CHARS / f"auto_{ид}_{time.strftime('%Y%m%d_%H%M%S')}"; папка.mkdir(parents=True, exist_ok=True)
    указатель = LOGS / f"auto_{ид}.json"
    клиент = Client(provider=пров, model=модель, timeout=240); пр = прайс()
    д = {"job": папка.name, "pid": os.getpid(), "query": "довести персонажа", "provider": пров, "model": модель,
         "started": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": "автопилот"}
    def записать(**доп):
        д.update(доп); д["usage"] = dict(клиент.usage); д["rub"] = round(рублей(клиент.usage, модель, пр), 2)
        указатель.write_text(json.dumps(д, ensure_ascii=False), encoding="utf-8")
    def событие(stage, message):
        with (папка / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "stage": stage, "message": message}, ensure_ascii=False) + "\n")
        print(f"[{stage}] {message}", flush=True); записать()
    def шаг(скрипт, *арг, ждать=3600):
        r = subprocess.run([sys.executable, str(HERE / скрипт), *арг], cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=ждать, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        if r.returncode != 0:
            событие("error", f"{скрипт}: {(r.stderr or r.stdout).strip()[-300:]}")
        return r.returncode == 0
    записать()
    прогонов = 0
    import spend
    for круг in range(10):
        г, к = готовность(ид); m = к.get("meta") or {}
        ост_п, ост_р = spend.остаток(ид)
        событие("plan", f"Кошелёк персонажа: поиск осталось {ост_п:.1f} ₽, работа {ост_р:.1f} ₽")
        if ост_р < 0.5:
            событие("stop", "Кошелёк работы персонажа исчерпан — останавливаюсь, остальное решаешь ты"); break
        событие("plan", f"Круг {круг + 1}: {г['цифры']}")
        if not (г["источники"] and г["разбор"]) and прогонов < ПРОГОНОВ_АНАЛИЗА and (ост_п >= 1 or прогонов >= 1):
            прогонов += 1
            событие("step", f"Разбор неполный → прогон анализа {прогонов}/{ПРОГОНОВ_АНАЛИЗА} (поиск ≤ 50 ₽, ход — строкой «анализ» в полосе)")
            запрос = (m.get("research") or {}).get("query") or f"{m.get('name', ид)} {m.get('src', '')}"
            if прогонов > 1:   # второй прогон — добор: без повторной охоты, только новые главы и их разбор
                os.environ["RESEARCH_ONLY_AUTO"] = "1"
            шаг("research_into.py", ид, запрос, пров, модель)
            os.environ.pop("RESEARCH_ONLY_AUTO", None)
            continue
        if not г["проверка"]:
            событие("step", "После разбора не было проверки → сверяю улики (строка «проверка» в полосе)")
            шаг("review_genome.py", ид, пров, модель); continue
        if not г["реплики"]:
            имена = [m.get("name", "")] + [x.strip() for x in re.split(r"[,«»]", str(m.get("alias", ""))) if x.strip()]
            имена += [x for x in (((m.get("research") or {}).get("subject") or {}).get("aliases") or [])]
            кандидаты = его_реплики(тексты(к), имена + [ид.replace("_", " ")])
            событие("step", f"Реплик-образцов {len(m.get('samples') or [])} → нашёл в текстах его фраз: {len(кандидаты)}, выбираю 8 из разных ситуаций")
            if len(кандидаты) < 5:
                событие("stop", "Его фраз в прочитанных текстах меньше 5 — нужен ещё прогон анализа с главами, где он говорит"); break
            ответ = object_response(клиент.chat(
                "Выбери 8 реплик, которые лучше всего показывают характер персонажа в РАЗНЫХ ситуациях (страх, хвастовство, забота, спор, шутка, опасность, победа). "
                "Бери только фразы, которые произносит ОН (по контексту «вокруг»), дословно. JSON: {\"samples\":[{\"t\":дословно,\"ctx\":\"ситуация в 3–6 словах\"}]}",
                json.dumps({"персонаж": m.get("name"), "кандидаты": кандидаты}, ensure_ascii=False), json_mode=True, max_tokens=1800))
            тексты_кандидатов = {c["t"] for c in кандидаты}
            выбор = [{"t": s["t"], "ctx": s.get("ctx", ""), "src": "текст источника"} for s in (ответ.get("samples") or []) if s.get("t") in тексты_кандидатов]
            было = [s if isinstance(s, dict) else {"t": str(s), "ctx": "", "src": "вписано"} for s in (m.get("samples") or [])]
            к["meta"]["samples"] = было + выбор
            (SHARE / f"{ид}.genome.json").write_text(json.dumps(к, ensure_ascii=False, indent=2), encoding="utf-8")
            событие("step", f"Добавлено реплик: {len(выбор)} (только дословные из текстов; выдуманные отброшены)")
            if not выбор: break
            continue
        if not г["голос"]:
            ответ = object_response(клиент.chat(
                "По репликам и описанию опиши голос персонажа для озвучки: пол, примерный возраст голоса, тембр, темп, манера. Без выдумок сверх текста. "
                "JSON: {\"gender\":..,\"age\":..,\"timbre\":\"1–2 предложения\",\"lang\":\"ru\"}",
                json.dumps({"персонаж": m.get("name"), "описание": m.get("desc", ""), "реплики": m.get("samples")}, ensure_ascii=False), json_mode=True, max_tokens=600))
            голос = m.get("voice") if isinstance(m.get("voice"), dict) else {"mode": "design"}
            голос.update({k: ответ.get(k) for k in ("gender", "age", "timbre", "lang") if ответ.get(k)})
            к["meta"]["voice"] = голос
            (SHARE / f"{ид}.genome.json").write_text(json.dumps(к, ensure_ascii=False, indent=2), encoding="utf-8")
            событие("step", "Голос описан: " + str(голос.get("timbre", ""))[:160]); continue
        if not г["промпт"]:
            событие("step", "Собираю промпт для общения (promptsmith)")
            if not шаг("promptsmith.py", str(SHARE / f"{ид}.genome.json"), пров, модель, ждать=900): break
            continue
        break
    г, к = готовность(ид)
    spend.записать(ид, "автопилот: реплики и голос", 0, рублей(клиент.usage, модель, пр), модель)
    недоделано = [э for э in ("источники", "разбор", "проверка", "реплики", "голос", "промпт") if not г[э]]
    итог = ("всё сделано" if not недоделано else "не сделано: " + ", ".join(недоделано)) + (f" · ждут твоего решения: {г['ждут']} предложений проверки" if г["ждут"] else "")
    пересобрать_список()
    событие("done", f"Автопилот закончил: {итог} · {г['цифры']}")
    записать(finished=time.strftime("%Y-%m-%d %H:%M:%S"), state="done" if not недоделано else "insufficient")


if __name__ == "__main__":
    main()
