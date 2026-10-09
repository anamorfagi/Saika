# -*- coding: utf-8 -*-
"""КТО ГОВОРИТ — ПО СМЫСЛУ (06.09.2026).

Владелец, аниме в Discord: «одна актриса озвучивает двух персонажей —
по тексту ты явно можешь это определить». Спектр и отпечаток тут
бессильны по определению: тембр один. А текст читается: обращения по
имени («Слушай, Хлоя» → отвечает Хлоя), вопрос → короткий ответ, смена
«я/ты», эхо-переспрос.

Это УТОЧНЕНИЕ ЗАДНИМ ЧИСЛОМ, не замена быстрого пути: облачко встаёт по
спектру за полсекунды, а через секунду-две сюда приходит окно последних
реплик, языковая модель размечает, чья каждая фраза (A/B/C…) и где
внутри фразы сменился говорящий, и вкладка перекрашивает слова с
подписью «по смыслу». Модель — служебный мозг (chat_once), не тот, что
ведёт разговор. Ошибки модели видны как её решение, а не как факт.

Алгоритм (без модели — правила, с моделью — она поверх правил):
  1. окно: последние N реплик одного канала, с pid;
  2. правила дают черновую разметку (обращение, вопрос→ответ, эхо);
  3. модели отдаётся окно + черновик, она возвращает JSON
     [{"pid":…, "who":"A", "split": [["текст части","A"],["…","B"]]}];
  4. наружу уходит stt_who на каждую реплику, где решение отличается
     от текущего.
"""
import json
import logging
import re
import threading
import time

from anamorf.config import CFG

log = logging.getLogger("saika.dialog_llm")

STATE = {"on": False, "runs": 0, "ok": 0, "ms": 0, "err": "", "last": 0.0,
         "who": {}}          # pid -> метка
_WIN = []                    # [(pid, text, app, ts)]
_LOCK = threading.Lock()
_emit = None

_SYS = ("Ты размечаешь стенограмму: кто из собеседников произнёс каждую "
        "реплику. Реплики уже распознаны со слуха и могут содержать ошибки. "
        "Собеседников обозначай буквами A, B, C… по порядку появления. "
        "Улики: обращение по имени (после «Слушай, Хлоя» отвечает Хлоя), "
        "вопрос и короткий ответ на него, смена «я/ты», переспрос-эхо, "
        "продолжение оборванной фразы — тот же человек. Если внутри одной "
        "реплики говорящий сменился — разбей её на части. "
        "В поле name — имя ТОГО, КТО ГОВОРИТ эту реплику, если оно известно из "
        "контекста: к нему обратились по имени, и он отвечает; он представился; "
        "его назвали в третьем лице и он откликнулся. Имя того, к КОМУ обращаются, "
        "в name не ставь: в «Хочу поговорить с господином Цинем» говорит НЕ Цин. "
        "Нет уверенности — name не заполняй. "
        "Отвечай ТОЛЬКО JSON-массивом без пояснений: "
        "[{\"pid\": 12, \"who\": \"A\", \"name\": \"Хлоя\", "
        "\"split\": [[\"текст части\", \"A\"], [\"текст части\", \"B\"]]}]. "
        "Поле split только если говорящий сменился внутри реплики.")


def enabled() -> bool:
    return bool(CFG.get("stt.dialog_llm.enabled", True))


def start(emit):
    """emit — broadcast_event. Поток просыпается, когда накопились реплики."""
    global _emit
    _emit = emit
    if STATE["on"]:
        return
    STATE["on"] = True
    threading.Thread(target=_loop, daemon=True, name="dialog-llm").start()


def push(r: dict):
    """Зовётся на каждую готовую реплику (из журнала событий или прямо)."""
    if not r.get("pid") or not (r.get("text") or "").strip():
        return
    with _LOCK:
        _WIN.append((r["pid"], r["text"], r.get("app") or r.get("src") or "",
                     float(r.get("_ts") or time.time())))
        del _WIN[:-int(CFG.get("stt.dialog_llm.window", 14))]


def _rules(win):
    """Черновик по правилам — то же, что во вкладке, но по окну целиком."""
    who, cur = {}, "A"
    prev = ""
    for pid, text, _app, _ts in win:
        t = text.strip()
        pw = re.sub(r"[^а-яёa-z ]", "", prev.lower()).split()
        nw = re.sub(r"[^а-яёa-z ]", "", t.lower()).split()
        answer = prev.endswith("?") and len(nw) <= 3
        echo = nw and len(nw) <= 3 and len(pw) > len(nw) and pw[-len(nw):] == nw
        cont = prev and not re.search(r"[.!?…]$", prev) and re.match(r"^(\.\.\.|…|[а-яёa-z])", t)
        if (answer or echo) and not cont:
            cur = "B" if cur == "A" else "A"
        who[pid] = cur
        prev = t
    return who


def _ask(win, draft):
    from anamorf.llm import manager as llm
    lines = []
    for pid, text, _app, _ts in win:
        # черновик модели НЕ показываем: облачный мозг его просто копировал
        # (журнал 23:46 — вход A/A/A/B, выход тот же один в один)
        lines.append("%d: %s" % (pid, text.strip()))
    user = ("Это стенограмма разговора двух-четырёх людей, реплики подряд по "
            "времени, распознаны со слуха (есть ошибки, мат — часть речи, не "
            "фильтруй). Определи по смыслу, кто говорит каждую реплику: буквы A, "
            "B, C по порядку появления. Признаки смены говорящего: вопрос → ответ; "
            "реакция («Ага», «Что?», «Да, точно», «Блядь» в ответ); ответ на "
            "обращение по имени — говорит НЕ названный; спор («Ты еблан» — другой "
            "человек). Признаки того же говорящего: продолжение оборванной фразы, "
            "тот же рассказ от первого лица. Пометь, где сменился говорящий, даже "
            "если не уверен в буквах.\n"
            + "\n".join(lines))
    t0 = time.monotonic()
    out = llm.chat_once([{"role": "system", "content": _SYS},
                         {"role": "user", "content": user}], max_len=3000) or ""
    STATE["ms"] = int((time.monotonic() - t0) * 1000)
    STATE["raw"] = out[:1500]
    STATE["raw_in"] = user[-1500:]
    m = re.search(r"\[.*\]", out, re.S)
    if not m:
        raise ValueError("нет JSON в ответе: %r" % out[:80])
    return json.loads(m.group(0))


def _loop():
    seen = 0
    while True:
        time.sleep(float(CFG.get("stt.dialog_llm.every_s", 2.5)))
        try:
            if not enabled():
                continue
            with _LOCK:
                win = list(_WIN)
            if len(win) < 3 or len(win) == seen and win[-1][0] == STATE.get("last_pid"):
                continue
            seen = len(win)
            STATE["last_pid"] = win[-1][0]
            draft = _rules(win)
            STATE["runs"] += 1
            res = _ask(win, draft)
            changed = 0
            for e in res:
                try:
                    pid = int(e.get("pid"))
                except Exception:
                    continue
                who = str(e.get("who") or "").strip()[:2]
                name = str(e.get("name") or "").strip()[:24]
                split = e.get("split") if isinstance(e.get("split"), list) else None
                # РАЗРЕЗ ТОЛЬКО СВОИМИ СЛОВАМИ (06.09.2026): модель отдавала
                # в split тексты СОСЕДНИХ реплик окна, и вкладка вклеивала
                # их в чужое облачко — текст фильма повторялся дважды.
                if split:
                    try:
                        own = next((t for p_, t, *_ in win if int(p_) == pid), "")
                        ow = set(re.findall(r"[а-яёa-z0-9]+", own.lower()))
                        sw = re.findall(r"[а-яёa-z0-9]+", " ".join(str(x[0]) for x in split if x).lower())
                        if not ow or not sw or len(sw) > len(ow) * 1.3 \
                                or sum(1 for w in sw if w in ow) < len(sw) * 0.8:
                            split = None
                    except Exception:
                        split = None
                key = (who, name, json.dumps(split, ensure_ascii=False) if split else "")
                if STATE["who"].get(pid) == key:
                    continue
                STATE["who"][pid] = key
                changed += 1
                _em = _emit
                if _em is None:          # модуль перечитан — ссылка потерялась
                    try:
                        from anamorf import main as _mn
                        _em = _mn.broadcast_event
                    except Exception:
                        _em = None
                if _em:
                    _em({"type": "stt_who", "pid": pid, "who": who, "name": name,
                         "split": split, "by": "смысл"})
            STATE["ok"] += 1
            STATE["last"] = time.time()
            if changed:
                log.info("Диалог по смыслу (%d мс): окно %d реплик, изменено %d",
                         STATE["ms"], len(win), changed)
        except Exception as e:
            STATE["err"] = str(e)[:160]
            log.debug("диалог по смыслу: %s", e)
