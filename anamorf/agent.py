"""АГЕНТНЫЙ ЦИКЛ: довести задачу до конца, а не сделать один вызов.

ПРОСЬБА ВЛАДЕЛЬЦА, дословно (2026-08-14):

    «сделай ей логику как у тебя при работе с системой — как ты сам
     ползаешь по папкам, ищешь материалы, можешь просматривать файлы,
     одновременно мне отвечать и работать… самопроверка результата.
     за всё время она ни разу сама не юзала агентности никакой: просто
     выполняет запрос и всё, останавливается, не завершив даже задание.
     но тут есть нюанс: она может ебучий браузер открыть и хуячить в него
     всякую залупу из-за того, что затупок и не пытается понять
     причинно-следственные связи — что и для чего делается»

ЧТО ЗДЕСЬ РЕАЛЬНО НОВОГО. Регламент из workflow.py — это ТЕКСТ В ПРОМПТЕ:
просьба к модели вести себя правильно. Мелкая модель читает его через
строчку, а крупная читает и всё равно отвечает одним ходом, потому что
устройство разговора одноходовое: фраза человека -> один ответ -> конец.
Никакого «продолжай, пока не сделано» в системе не было вообще.

Здесь этот цикл появляется НА СТОРОНЕ СЕРВЕРА, где его нельзя
проигнорировать:

    цель -> шаг -> исполнение -> ПРОВЕРКА глазами -> решение -> шаг…

Пока цель не достигнута или не упёрлись — цикл идёт сам. Модель на каждом
витке отвечает не прозой, а строгим решением: {"действие", "почему",
"готово"}. Проза, которой она любит заменять дело, тут не проходит просто
потому, что формат не тот.

ПРО «ЕБУЧИЙ БРАУЗЕР» — ЭТО ГЛАВНОЕ, А НЕ ПРИМЕЧАНИЕ. Агентность без
причинности опаснее, чем её отсутствие: цикл из десяти шагов, каждый из
которых наугад, — это десять открытых окон вместо одного. Поэтому:

  * КАЖДЫЙ шаг обязан назвать, ЗАЧЕМ он приближает к цели («почему»), и
    решение без внятного «почему» не исполняется;
  * инструменты режутся ПОД ЗАДАЧУ: разговор про папки не выдаёт браузер
    в принципе — его нет в списке, из которого выбирают;
  * повтор того же вызова с теми же аргументами запрещён механически;
  * два шага подряд без продвижения — стоп и честный рассказ человеку.

ЧЕГО ЦИКЛ НЕ ДЕЛАЕТ. Не решает за человека спорное, не тратит деньги
(платные мозги в цикл не берём), не лезет в разрушающие инструменты без
его слов — предохранитель намерения тот же, что в обычном ходе.
"""
from __future__ import annotations

import json
import logging
import re
import time

from anamorf.config import CFG

log = logging.getLogger("saika.agent")

# ── КОГДА ЗАПУСКАТЬ ЦИКЛ ─────────────────────────────────────────────
# Не на каждую фразу: «привет» и «как дела» цикл не нужен, а лишний виток
# — это лишнее действие на машине владельца. Признак задачи — глагол
# действия. Признак МНОГОШАГОВОЙ задачи — несколько действий или предмет,
# которого мы ещё не нашли.
_DOING = re.compile(
    r"\b(?:найд|поищ|откр|запус|закр|сверн|разверн|перейд|зайд|спуст|"
    r"переимен|перемест|скопир|удали|созда|сдела|постав|включ|выключ|"
    r"проверь|посмотр|глянь|собер|разбер|почини|настрой|покаж)\w*", re.I)
_MULTI = re.compile(
    r"\bи\b|\bпотом\b|\bзатем\b|\bа\s+после\b|\bдальше\b|,\s*\w+\s+"
    r"(?:потом|затем)|\bвсе\b|\bвсё\b|\bкажд\w+", re.I)


# РАЗГОВОР О ДЕЙСТВИИ — НЕ ПРИКАЗ (2026-08-15). Живой вечер: владелец
# проверял распознаватель и вслух рассуждал — «давай посмотрим, как у тебя
# это получится», «я просто проверяю, как пишет распознаватель», «не делай
# ничего, я не с тобой разговариваю». В каждой фразе есть глагол
# «посмотреть», и цикл послушно поднимался: восемь шагов, заблокированный
# предохранителем folder_list и открытый на экране проводник. Человек в
# это время просто говорил.
#
# Отличаем по форме речи, а не по глаголу: «посмотрим» (мы вместе, в
# будущем) — это размышление; «посмотри» (ты, сейчас) — приказ. Плюс
# прямые запреты, которые человек проговаривает вслух.
_NOT_TASK = re.compile(
    r"\bдавай(?:-ка)?\s+(?:посмотр|глян|провер)|"
    r"\b(?:посмотрим|глянем|проверим|увидим|попробуем)\b|"
    r"\bя\s+(?:просто|сейчас|тут)\s+(?:провер|говор|болта|смотр|тест)|"
    r"\bне\s+с\s+тобой\b|\bничего\s+не\s+делай\b|\bне\s+делай\b|"
    r"\bне\s+надо\s+ничего\b|\bпросто\s+(?:слушай|болтаю|говорю)\b|"
    r"\bкак\s+(?:у\s+тебя|он|она|оно|это)\s+(?:получ|работа|пиш|определ)",
    re.I)


def wanted(user_text: str) -> bool:
    """Стоит ли поднимать цикл под эту фразу."""
    if not CFG.get("agent.enabled", True):
        return False
    t = (user_text or "").strip()
    if len(t) < 6 or not _DOING.search(t):
        return False
    if _NOT_TASK.search(t):
        log.info("Цикл не поднимаю: «%s» — это разговор, а не задача",
                 t[:60])
        return False
    return True


# ── ИНСТРУМЕНТЫ ПОД ЗАДАЧУ ───────────────────────────────────────────
# «Причинно-следственная связь» на практике начинается здесь: если задача
# про папки, браузера в списке нет — и модель физически не может его
# позвать, как бы ни затупила. Это дешевле и надёжнее любых уговоров в
# промпте.
KITS = {
    "walk": ("диск|папк|провод|файл|каталог|игр|программ|музык|документ|"
             "загрузк|скачан|exe|bat|ярлык",
             ["go_to", "scan_disk", "find_here", "pick_number", "learn_app",
              "run_file", "folder_list", "open_folder", "find_folder",
              "app_launch", "window_focus", "window_close", "window_list"]),
    "windows": ("окн|сверн|разверн|закр|переключ|экран|поверх|угол|"
                "размест|полный экран",
                ["window_list", "window_focus", "window_close",
                 "window_minimize", "window_maximize", "window_restore",
                 "window_restore_all", "window_place", "minimize_all",
                 "screen_map"]),
    "apps": ("запус|включи|открой програм|прог\\b|приложен",
             ["app_launch", "apps_list", "window_focus", "window_list",
              "go_to", "find_folder"]),
    "media": ("музык|трек|песн|громк|звук|тише|громче|пауз|играй",
              ["media", "volume_set", "find_here", "run_file", "go_to"]),
    "web": ("интернет|в\\s+сет|гугл|сайт|браузер|ютуб|youtube|стать|новост",
            ["web_search", "web_research", "web_open", "web_list",
             "open_result", "close_browser", "screen_read"]),
}
# всегда доступны: посмотреть — не действие, и запрещать смотреть глупо
_ALWAYS = ["window_list", "folder_list", "screen_map"]


def kit_for(goal: str) -> list:
    """Какие инструменты вообще разрешены под эту цель."""
    g = (goal or "").lower()
    names: list = []
    for _name, (pat, tools) in KITS.items():
        if re.search(pat, g, re.I):
            names += tools
    if not names:                       # непонятная задача — только смотреть
        names = list(_ALWAYS)
    for t in _ALWAYS:
        if t not in names:
            names.append(t)
    seen, out = set(), []
    for t in names:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ── РЕШЕНИЕ ШАГА ─────────────────────────────────────────────────────
_DECIDE = (
    "Ты — исполнительный контур голосового помощника. Твоя работа: "
    "довести задачу человека до конца, шаг за шагом.\n\n"
    "Отвечай ТОЛЬКО одним JSON-объектом, без пояснений вокруг:\n"
    '{"почему": "<одной фразой: зачем этот шаг приближает к цели>",\n'
    ' "инструмент": "<имя из списка или null, если всё сделано>",\n'
    ' "аргументы": {<аргументы инструмента>},\n'
    ' "готово": <true, если цель достигнута и проверена>,\n'
    ' "сказать": "<что сказать человеку, когда готово; иначе пусто>"}\n\n'
    "ПРАВИЛА, ОТ КОТОРЫХ НЕ ОТСТУПАЮТ:\n"
    "- ОДИН шаг за раз. Не планируй вслух, не перечисляй будущее.\n"
    "- «почему» обязательно и по делу. Нет внятного «почему» — значит "
    "шаг не нужен.\n"
    "- Смотри ПЕРЕД тем, как делать, и ПОСЛЕ того, как сделал: результат "
    "прошлого шага показан ниже, читай его, а не догадывайся.\n"
    "- Не повторяй вызов, который уже не сработал. Иди другим путём.\n"
    "- Инструментов, которых нет в списке, не существует.\n"
    "- «готово» ставится, только когда результат ВИДЕН в истории шагов. "
    "Намерение результатом не является.\n"
    "- Упёрлась и не знаешь, как обойти — верни готово=true и честно "
    "напиши в «сказать», что именно помешало."
)


def _tool_lines(names: list) -> str:
    """Компактная выжимка схем: имя, зачем, какие аргументы."""
    try:
        from anamorf.llm import tools as _t
        by = {s["function"]["name"]: s["function"] for s in _t.schemas()}
    except Exception:
        return "\n".join("- " + n for n in names)
    out = []
    for n in names:
        f = by.get(n)
        if not f:
            continue
        props = ((f.get("parameters") or {}).get("properties") or {})
        args = ", ".join(props.keys()) or "без аргументов"
        out.append(f"- {n}({args}): {(f.get('description') or '')[:150]}")
    return "\n".join(out)


def _brain():
    """Кому доверить рассуждение. Владелец: «модели для этого более умные
    есть в арсенале». Цикл — это не болтовня, тут думать надо: берём
    самую сильную живую и БЕСПЛАТНУЮ (лестница платных не отдаёт)."""
    try:
        from anamorf import capabilities as caps
        from anamorf.llm import brains, skills

        def _fit(b, m):
            """Цикл ДЕЙСТВУЕТ, а не болтает. Тому, кто инструменты только
            изображает словами, тут делать нечего (2026-08-19: GigaChat в
            этой роли запустил владельцу After Effects и лаунчер игры,
            которых он не просил, и отчитался об успехе)."""
            return bool(m) and caps.tools_ok(m)

        best = skills.best_for("smart", min_score=7)
        if best and _fit(best["backend"], best["model"]):
            return best["backend"], best["model"]
        for c in brains.ladder():
            if _fit(c["backend"], c["model"]):
                return c["backend"], c["model"]
    except Exception as e:
        log.debug("умный мозг для цикла не нашёлся: %s", e)
    return "", ""


def _json_of(raw: str) -> dict:
    """Достать объект решения из чего угодно, что вернула модель."""
    if not raw:
        return {}
    m = re.search(r"\{", raw)
    if not m:
        return {}
    depth, end = 0, None
    for i in range(m.start(), len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if not end:
        return {}
    try:
        d = json.loads(raw[m.start():end])
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _decide(goal: str, kit: list, history: list) -> dict:
    from anamorf.llm import manager as llm
    b, m = _brain()
    steps = "\n".join(
        f"{i}. {h['tool']}({json.dumps(h['args'], ensure_ascii=False)})\n"
        f"   -> {h['result'][:400]}"
        for i, h in enumerate(history, 1)) or "(ещё ничего не делали)"
    # ПАМЯТЬ У НАС УСТРОЕНА НЕ КАК У ЧЕЛОВЕКА (2026-08-14, замечание
    # владельца: «неудачи тоже нужно учитывать… но для ИИ это не совсем
    # корректно, вы изначально дохера знаете, и память у вас по другим
    # принципам»). Он прав дважды. Модель не переучивается от опыта — её
    # знание уже внутри; меняется только то, что лежит перед глазами В
    # ЭТОТ момент. Значит «учиться на ошибках» для неё = ПОЛОЖИТЬ нужный
    # факт в промпт вовремя. И учить надо не общему («проводник — это
    # окно»), а частному про ЭТУ машину: что именно тут не сработало.
    rakes = ""
    try:
        from anamorf import recipes as _rc
        rakes = _rc.rakes_text(goal)
    except Exception:
        pass
    msgs = [
        {"role": "system", "content": _DECIDE},
        {"role": "user", "content":
            f"ЦЕЛЬ ЧЕЛОВЕКА: {goal}\n\n"
            f"ДОСТУПНЫЕ ИНСТРУМЕНТЫ:\n{_tool_lines(kit)}\n\n"
            + (rakes + "\n\n" if rakes else "") +
            f"ЧТО УЖЕ СДЕЛАНО И ЧТО ПОЛУЧИЛОСЬ:\n{steps}\n\n"
            "Твой следующий шаг — одним JSON."}]
    try:
        raw = (llm.ask_specific(b, m, msgs, max_len=1200) if b and m
               else llm.chat_once(msgs, max_len=1200))
    except Exception as e:
        log.info("цикл: мозг не ответил (%s)", e)
        return {}
    return _json_of(raw)


# ── САМ ЦИКЛ ─────────────────────────────────────────────────────────
def run(goal: str, on_step=None, user_text: str = "") -> dict:
    """Довести цель до конца. Возвращает {ok, said, steps, why}.

    on_step(tool, args, result) — чтобы человек видел работу вживую, а не
    ждал молча: он просил «одновременно мне отвечать и работать»."""
    t0 = time.time()
    max_steps = int(CFG.get("agent.max_steps", 5))
    budget_s = float(CFG.get("agent.budget_s", 35))
    kit = kit_for(goal or user_text)
    history: list = []
    tried: set = set()
    said, why = "", ""

    from anamorf.llm import tools as _t
    _t.LAST_USER["text"] = user_text or goal

    # ── СНАЧАЛА ПАМЯТЬ, ПОТОМ ДУМАНЬЕ (2026-08-14) ──
    # Владелец: «конкретно собирать удачные логические цепочки, запоминая,
    # чтобы такой же запрос в будущем выполнить на огромной скорости».
    # Если эту задачу уже доводили до конца — проигрываем застывший успех
    # напрямую, без единого обращения к мозгу. Не сработало — честно
    # откатываемся к обычному циклу и помечаем рецепт промахом.
    try:
        from anamorf import recipes as _rc
        rec = _rc.find(goal)
        if rec:
            log.info("Знакомая задача (совпало %.0f%%) — играю по памяти: %s",
                     rec.get("match", 0) * 100, rec.get("goal", "")[:60])
            got = _rc.replay(rec, on_step=on_step, user_text=user_text)
            if got["ok"]:
                return {"ok": True, "said": rec.get("said", ""),
                        "why": "готово по памяти", "steps": got["steps"],
                        "from_memory": True}
            _rc.note_miss(goal)
            history = got["steps"]      # что успели — не выбрасываем
            for h in history:
                tried.add(h["tool"] + json.dumps(h["args"],
                                                 ensure_ascii=False,
                                                 sort_keys=True))
    except Exception as e:
        log.debug("память цепочек пропущена: %s", e)

    # ОТКАЗ — НЕ ШАГ (2026-08-14, стенд поймал): «не сказано зачем»,
    # «это уже было», «такого инструмента нет» — это ПОПРАВКИ, а не
    # действия на машине. Если они съедают бюджет шагов, болтливая модель
    # тратит всю задачу на препирательства и до дела не доходит. Считаем
    # их отдельно и обрываем только если их стало неприлично много.
    done_steps, rejects = 0, 0
    step = 0
    while done_steps < max_steps and rejects < max_steps + 3:
        step += 1
        if time.time() - t0 > budget_s:
            why = f"вышло время ({int(budget_s)}с)"
            break
        d = _decide(goal, kit, history)
        if not d:
            why = "не смогла решить, что делать дальше"
            break
        tool = (d.get("инструмент") or d.get("tool") or "") or ""
        args = d.get("аргументы") or d.get("args") or {}
        because = str(d.get("почему") or d.get("why") or "").strip()
        if d.get("готово") or d.get("done") or not tool:
            said = str(d.get("сказать") or d.get("say") or "").strip()
            why = "готово"
            break
        if tool not in kit:
            history.append({"tool": tool, "args": args,
                            "result": f"инструмента «{tool}» тут нет — "
                                      "выбери из списка"})
            rejects += 1
            continue
        # ПРИЧИННОСТЬ НЕ ФОРМАЛЬНОСТЬ: шаг без внятного «зачем» не идёт
        if len(because) < 8:
            history.append({"tool": tool, "args": args,
                            "result": "шаг отклонён: не сказано, ЗАЧЕМ он "
                                      "нужен для цели"})
            rejects += 1
            continue
        key = tool + json.dumps(args, ensure_ascii=False, sort_keys=True)
        if key in tried:
            history.append({"tool": tool, "args": args,
                            "result": "этот вызов с теми же аргументами уже "
                                      "был и не помог — иди другим путём"})
            rejects += 1
            continue
        tried.add(key)
        log.info("Цикл, шаг %d: %s(%s) — %s", step, tool, args, because)
        try:
            res = str(_t.call(tool, args) or "")
        except Exception as e:
            res = f"вызов сорвался: {e}"
        done_steps += 1
        history.append({"tool": tool, "args": args, "result": res,
                        "why": because})
        # НЕУДАЧУ ЗАПОМИНАЕМ СРАЗУ, не дожидаясь конца задачи: даже если
        # цель в итоге взята другим путём, ЭТОТ путь всё равно тупик, и в
        # следующий раз в него ходить незачем.
        _low = res.lower()
        if ("не нашла" in _low or "тут нет" in _low or "не получилось" in _low
                or "отказ:" in _low or "не смогла" in _low
                or "не послушалось" in _low or _low.startswith("нечего")):
            try:
                from anamorf import recipes as _rcf
                _rcf.remember_fail(goal, tool, args, res)
            except Exception:
                pass
        if on_step:
            try:
                on_step(tool, args, res)
            except Exception:
                pass
    if not why:
        why = (f"кончились шаги ({max_steps})" if done_steps >= max_steps
               else "модель спорит вместо дела")
    # УСПЕХ СОХРАНЯЕМ — но только доведённый до конца: половина пути
    # рецептом не становится, иначе память наполнится тупиками.
    if why == "готово" and history:
        try:
            from anamorf import recipes as _rc2
            _rc2.remember(goal, history, said)
        except Exception as e:
            log.debug("цепочку не запомнила: %s", e)
    log.info("Цикл завершён: %s, шагов %d, %.1fс", why, len(history),
             time.time() - t0)
    return {"ok": why == "готово", "said": said, "why": why,
            "steps": history}


def digest(res: dict) -> str:
    """Короткая честная выжимка для промпта: что цикл реально сделал."""
    if not res or not res.get("steps"):
        return ""
    lines = ["### Ты УЖЕ поработала над этим (факт, не план):"]
    for h in res["steps"][-6:]:
        lines.append(f"- {h['tool']}: {str(h['result'])[:200]}")
    if res.get("ok"):
        lines.append("Цель достигнута. Скажи человеку результат коротко, "
                     "своими словами, не пересказывая шаги.")
    else:
        lines.append(f"НЕ довела до конца ({res.get('why')}). Скажи честно, "
                     "на чём встала и что нужно от человека.")
    return "\n".join(lines)
