# -*- coding: utf-8 -*-
"""behavior_fill.py — вкладка «Поведение»: реплики персонажа на 15 сценариев по мотивам его РЕАЛЬНЫХ эпизодов.

---- учебный блок ----
Для каждого сценария из scen.json берём 8 настоящих эпизодов из chars/<id>/episodes.jsonl (поиск по
ключевым словам, без модели и бесплатно), отдаём их ВЫБРАННОЙ модели одним вызовом и просим реплику
на каждое действие сценария его голосом. Результат пишется в meta.trace_by, расход идёт в кошелёк.
Запуск: py -3 behavior_fill.py <id> <провайдер> <модель> [лимит_руб]
"""
import sys, json, pathlib, random, re, time, io
import concurrent.futures as cf
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from llm import Client
from research import object_response
from research_into import рублей, прайс
import spend

ROOT = pathlib.Path(__file__).resolve().parent.parent
КЛЮЧИ = {
    "refuse": ["refuse", "no way", "won't", "reject", "decline"],
    "lie": ["lie", "lying", "liar", "where were you", "deceiv"],
    "humil": ["laugh at", "mock", "humiliat", "ridicul", "sneer", "insult"],
    "count": ["calculat", "count", "formula", "pill", "concoct", "medicin"],
    "day": ["today", "sect", "eat", "sleep", "turtle"],
    "sad": ["sad", "cry", "tears", "sigh", "grief", "silent"],
    "bored": ["bored", "fun", "play", "prank", "chicken"],
    "wrong": ["wrong", "mistake", "you're right", "admit", "fool"],
    "omen": ["fate", "heaven", "omen", "fortune", "karma", "destiny"],
    "lie4me": ["cover for", "pretend", "don't tell", "secret", "deceive"],
    "pry": ["past", "secret", "why do you", "ask", "village"],
    "risk": ["danger", "risk", "die", "death", "afraid", "scared"],
    "compliment": ["handsome", "beautiful", "praise", "admire"],
    "flirt": ["blush", "beautiful", "smile", "Du Lingfei", "Hou Xiaomei"],
    "sex": ["blush", "embarrass", "cough", "Du Lingfei", "shameless"],
}


def эпизоды(ид):
    return [json.loads(x) for x in (ROOT / "chars" / ид / "episodes.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


def подобрать(все, ключи, n=8):
    rx = re.compile("|".join(re.escape(k) for k in ключи), re.I)
    хит = [e for e in все if rx.search(e.get("абзац", "") + " " + e.get("до", ""))]
    random.shuffle(хит)
    out = хит[:n]
    if len(out) < n:
        out += random.sample(все, n - len(out))
    return out


def все_объекты(text):
    """Слабые/бесплатные модели (GigaChat, малые локальные) часто отдают не один JSON, а по объекту на действие.
    Собираем ВСЕ объекты из ответа в один словарь, а не только первый."""
    dec, out, i, t = json.JSONDecoder(), {}, 0, str(text)
    while True:
        j = t.find("{", i)
        if j < 0:
            return out
        try:
            v, k = dec.raw_decode(t[j:]); i = j + k
            if isinstance(v, dict):
                out.update(v)
        except ValueError:
            i = j + 1


def кратко(e):
    return f"[гл.{e.get('гл')}] {e.get('до','')[:220]} || ОН: «{e.get('реплика','')[:200]}» || {e.get('после','')[:180]}"


def main():
    ид, пров, модель = sys.argv[1], sys.argv[2], sys.argv[3]
    лимит = float(sys.argv[4]) if len(sys.argv) > 4 else 4.0
    файл = ROOT / "share" / f"{ид}.genome.json"
    карта = json.loads(файл.read_text(encoding="utf-8"))
    м = карта.setdefault("meta", {})
    сцены = json.loads((pathlib.Path(__file__).parent / "scen.json").read_text(encoding="utf-8"))
    все = эпизоды(ид)
    клиент = Client(provider=пров, model=модель, timeout=180)
    пр = прайс()
    кто = f"{м.get('name', ид)} — {str(м.get('desc',''))[:700]}"
    голос = str((м.get("voice") or {}).get("timbre", ""))
    образцы = [s if isinstance(s, str) else (s.get("text") or s.get("say") or "") for s in (м.get("samples") or [])][:6]
    итог, главы = dict(м.get("trace_by") or {}), set()

    # ---- видимость: указатель logs/behavior_<id>.json + живой журнал chars/<job>/events.jsonl → полоска работ в студии
    job = f"behavior_{ид}_{time.strftime('%Y%m%d_%H%M%S')}"
    папка = ROOT / "chars" / job; папка.mkdir(parents=True, exist_ok=True)
    указатель = ROOT / "logs" / f"behavior_{ид}.json"
    д = {"job": job, "pid": __import__("os").getpid(), "query": "поведение: 15 сценариев", "provider": пров, "model": модель,
         "started": time.strftime("%Y-%m-%d %H:%M:%S"), "всего": len(сцены), "готово": 0, "реплик": 0, "rub": 0}

    def отметить(stage, message, **data):
        e = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "stage": stage, "message": message, **data}
        with (папка / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        д["usage"] = dict(клиент.usage); д["rub"] = round(рублей(клиент.usage, клиент.model, пр), 2)
        указатель.write_text(json.dumps(д, ensure_ascii=False), encoding="utf-8")
        print(f"[{stage}] {message}", flush=True)

    отметить("start", f"{len(сцены)} сценариев · {len(все)} его эпизодов · {пров} {модель}")

    def одна(s):
        if рублей(клиент.usage, клиент.model, пр) >= лимит:
            return s["id"], None, []
        эп = подобрать(все, КЛЮЧИ.get(s["id"], [s["id"]]))
        sysm = ("Ты пишешь реплики персонажа строго по его реальному поведению в первоисточнике. "
                "Не персонаж читает анкету — живой человек реагирует на ситуацию. Ответ — только JSON.")
        user = (f"Персонаж: {кто}\nГолос: {голос}\nЕго реальные фразы (переведены): " + " / ".join(образцы) +
                "\n\nРеальные эпизоды из книги (как он реально ведёт себя):\n" + "\n".join(кратко(e) for e in эп) +
                f"\n\nСитуация: {s['t']}. {s['in']}\nДля КАЖДОГО действия ниже напиши, что он скажет/сделает, "
                "если выберет именно его: 1–2 фразы по-русски, его манерой (характерные словечки, реакции, бравада/трусость "
                "— как в эпизодах), без ремарок в звёздочках. Если действие ему чуждо — покажи, как он его исказит по-своему. "
                "Также поле \"_выбор\": какое действие он выберет на самом деле.\n"
                "Действия: " + json.dumps(s["acts"], ensure_ascii=False) +
                '\nФормат: {"<действие>": "<реплика>", ..., "_выбор": "<действие>"}')
        try:
            r = все_объекты(клиент.chat(sysm, user, temperature=0.7, max_tokens=900, json_mode=(пров != "gigachat")))
            if not r:
                raise ValueError("модель не вернула JSON")
        except Exception as ex:
            print(f"[{s['id']}] ошибка: {ex}", flush=True)
            return s["id"], None, []
        return s["id"], r, [e.get("гл") for e in эп]

    # бесплатный GigaChat пускает только 1 запрос одновременно — иначе 429
    with cf.ThreadPoolExecutor(1 if пров == "gigachat" else 5) as пул:
        for sid, r, гл in пул.map(одна, сцены):
            сц = next(x for x in сцены if x["id"] == sid)
            д["готово"] += 1
            if not r:
                отметить("error", f"«{сц['t']}» — модель не ответила")
                continue
            итог[sid] = {a: str(r[a]).strip() for a in сц["acts"] if r.get(a)}
            if r.get("_выбор") in сц["acts"]:
                м.setdefault("trace_pick", {})[sid] = r["_выбор"]
            главы.update(g for g in гл if g)
            д["реплик"] += len(итог[sid])
            пример = итог[sid].get(r.get("_выбор")) or next(iter(итог[sid].values()), "")
            отметить("scene", f"«{сц['t']}» {len(итог[sid])}/{len(сц['acts'])} · выбор: {r.get('_выбор')} — «{пример[:160]}» (главы {', '.join(map(str, гл[:5]))})")

    руб = round(рублей(клиент.usage, клиент.model, пр), 2)
    if not итог:
        sys.exit("ни одного сценария не снято — карточку не трогаю")
    м["trace_by"] = итог
    гл = sorted(главы)
    м["trace_provenance"] = (f"по мотивам реальных эпизодов (главы {', '.join(map(str, гл[:12]))}{'…' if len(гл) > 12 else ''}) · "
                             f"{пров} {модель} · {time.strftime('%Y-%m-%d %H:%M')}")
    (ROOT / "logs" / f"{ид}.before-behavior.json").write_text(файл.read_text(encoding="utf-8"), encoding="utf-8")
    файл.write_text(json.dumps(карта, ensure_ascii=False, indent=1), encoding="utf-8")
    spend.записать(ид, "поведение: 15 сценариев (доп. к кошельку по «доделай»)", 0, руб, модель)
    д["finished"] = time.strftime("%Y-%m-%d %H:%M:%S"); д["state"] = "done"
    отметить("done", f"записано в карточку: {sum(len(v) for v in итог.values())} реплик в {len(итог)} сценариях · {руб} ₽ · {round(клиент.usage['sec'])} с")


if __name__ == "__main__":
    main()
