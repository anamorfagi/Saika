# -*- coding: utf-8 -*-
"""agent_jobs.py — самопроверка ассистента: что сделано, что идёт, чего не хватает.

  работы()       — все фоновые исследования: идёт / готово / прервано (процесс умер без финиша) / ошибка
  незаконченные() — прерванные работы: chat.py видит их при каждом сообщении и продолжает сам
  аудит(id)      — по карточке: охват генома по блокам, улики, реплики, описание, голос, аватар, промпт → список «не хватает»
  источники(id)  — что исследование реально прочитало: адреса, объём, реплики персонажа

---- учебный блок: почему «прервано» определяется по процессу ----
Указатель logs/research_<id>.json пишется при старте, а поле finished — только в самом конце.
Если finished нет, а процесса с таким pid уже нет (выключили компьютер, упал python),
работа прервана, и её надо продолжать, а не считать идущей вечно.
"""
import json, os, pathlib, ctypes

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHARE, LOGS, CHARS = ROOT / "share", ROOT / "logs", ROOT / "chars"


def _жив(pid):
    try:
        pid = int(pid)
    except Exception:
        return False
    if os.name == "nt":
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        код = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(код)); ctypes.windll.kernel32.CloseHandle(h)
        return код.value == 259   # STILL_ACTIVE
    try:
        os.kill(pid, 0); return True
    except Exception:
        return False


def _события(job):
    f = CHARS / str(job) / "events.jsonl"
    if not f.exists():
        return []
    out = []
    for x in f.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(x))
        except Exception:
            pass
    return out


def работы():
    out = []
    for f in sorted(list(LOGS.glob("research_*.json")) + list(LOGS.glob("review_*.json")) + list(LOGS.glob("auto_*.json")) + list(LOGS.glob("corpus_*.json"))):
        try:
            д = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        ид = f.stem.split("_", 1)[1]
        ев = _события(д.get("job"))
        if д.get("finished"):
            сост = {"done": "готово", "insufficient": "мало данных", "error": "ошибка"}.get(д.get("state"), "завершено")
            if str(д.get("finished")).startswith("останов"):
                сост = "остановлено"
        else:
            сост = "идёт" if _жив(д.get("pid")) else "прервано"
        ист = [e for e in ев if e.get("stage") == "source"]
        out.append({"id": ид, "job": д.get("job"), "сост": сост, "query": д.get("query"), "started": д.get("started"),
                    "finished": д.get("finished", ""), "событий": len(ев), "источников": len(ист),
                    "реплик": sum(int(e.get("replicas") or 0) for e in ист),
                    "последнее": (ев[-1].get("stage", "") + ": " + str(ев[-1].get("message", ""))[:200]) if ев else ""})
    return out


def незаконченные():
    return [р for р in работы() if р["сост"] == "прервано"]


def аудит(ид):
    файл = SHARE / f"{ид}.genome.json"
    if not файл.exists():
        return f"карточки {ид} нет"
    к = json.loads(файл.read_text(encoding="utf-8")); m = к.get("meta") or {}; г = к.get("genome") or {}
    вид = m.get("kind", "персонаж")
    блоки = json.loads((pathlib.Path(__file__).parent / "genes.json").read_text(encoding="utf-8"))
    строки, мало = [], []
    всего = снято = улик = 0
    for b in блоки:
        ids = [g["id"] for g in b.get("genes", [])]
        if not ids:
            continue
        pref = ids[0].split(".")[0]
        if (pref == "beast" and вид != "существо") or (pref == "nat" and вид != "ии"):
            continue
        есть = [i for i in ids if i in г]
        у = sum(len(г[i][2]) if isinstance(г[i], list) and len(г[i]) > 2 and isinstance(г[i][2], list) else 0 for i in есть)
        всего += len(ids); снято += len(есть); улик += у
        доля = len(есть) / len(ids)
        строки.append(f"{b.get('name', pref)[:28]:28} {len(есть):3}/{len(ids):<3} улик {у}")
        if доля < .3:
            мало.append(b.get("name", pref))
    уверенность = [v[1] for v in г.values() if isinstance(v, list) and len(v) > 1]
    сред = sum(уверенность) / len(уверенность) if уверенность else 0
    нехватка = []
    if снято < всего * .5: нехватка.append(f"геном снят на {снято}/{всего} — нужен разбор источников (research_genome)")
    if мало: нехватка.append("почти пустые блоки: " + ", ".join(мало[:8]))
    if len(m.get("samples") or []) < 5: нехватка.append(f"реплик-образцов {len(m.get('samples') or [])} — нужно 5+ настоящих из канона")
    if not m.get("never"): нехватка.append("нет списка «никогда не делает»")
    голос = m.get("voice")   # create_card кладёт голос строкой, студия — объектом {timbre,…}
    if not (голос.get("timbre") if isinstance(голос, dict) else голос): нехватка.append("не описан голос (тембр)")
    if not к.get("avatar"): нехватка.append("нет аватара")
    if not m.get("prompt"): нехватка.append("не собран промпт (make_prompt)")
    if not m.get("desc"): нехватка.append("нет описания")
    иссл = m.get("research") or {}
    return (f"{m.get('name', ид)} · вид {вид} · генов {снято}/{всего} · улик {улик} · средняя уверенность {сред:.2f}"
            + (f" · исследование: {иссл.get('job')} ({'опубликовано' if иссл.get('published') else 'не опубликовано'})" if иссл else " · исследования не было")
            + "\n" + "\n".join(строки)
            + "\n\nНЕ ХВАТАЕТ:\n" + ("\n".join("- " + x for x in нехватка) if нехватка else "- всё основное на месте"))


def источники(ид):
    ук = LOGS / f"research_{ид}.json"
    if not ук.exists():
        return "по этой карточке исследования не было"
    д = json.loads(ук.read_text(encoding="utf-8"))
    ев = _события(д.get("job"))
    прочитано = [e for e in ев if e.get("stage") == "source"]
    отказ = [e for e in ев if e.get("stage") in ("rejected", "source_error")]
    файлы = sorted((CHARS / str(д.get("job"))).glob("source_*.txt"))
    out = [f"job {д.get('job')} · прочитано {len(прочитано)} · отброшено/ошибок {len(отказ)} · текстов сохранено {len(файлы)}"]
    out += [f"✓ реплик {e.get('replicas', 0):>3} · {e.get('chars', 0):>6} зн · {str(e.get('message'))[:110]} · {e.get('url', '')[:90]}" for e in прочитано[-15:]]
    out += [f"✗ {str(e.get('message'))[:120]} · {e.get('url', '')[:80]}" for e in отказ[-6:]]
    return "\n".join(out)
