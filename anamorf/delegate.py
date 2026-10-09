"""ПЕРЕДАТЬ ЗАДАЧУ ТОМУ, КТО ЕЁ ПОТЯНЕТ (05.09.2026).

Владелец, двумя заходами:

    «нужно научить, чтобы она могла после запуска приложения отдавать
     запросы тебе или другим моделям — типа Кодекса, ГПТ, Кими, Дипсика,
     которые облачные или имеют свой UI на ПК, как ты, и имеют такой
     функционал; так и ресурсы не будет тратить, и результат будет лучше,
     если мне нужно будет создать что-нибудь прям совсем удалённо»

    «локальная модель уж точно не потянет генерацию и моделинг, но если
     она тут будет запрос уметь направлять тебе — это уже другое дело»

═══ ПОЧЕМУ ЭТО НЕ «ПРИЗНАНИЕ СЛАБОСТИ» ═══

Сайка на своём железе выдаёт двадцать пять токенов в секунду. Написать
сцену на питоне или разобрать чужой проект она может — часами и с
ошибками, которые потом дороже переписать, чем сделать заново. Это не
вопрос ума модели, это вопрос ЖАНРА: она — руки, глаза, голос и
присутствие. Она видит экран, слышит комнату, помнит, над чем работаем,
и всегда рядом. Такого не умеет ни одна облачная модель.

Поэтому правильное разделение не «кто умнее», а «кто где сильнее»:
сложное думание уезжает туда, где оно дешёвое, а тело остаётся здесь.

═══ ТРИ ПРАВИЛА, БЕЗ КОТОРЫХ ЭТО ИСПОРЧЕННЫЙ ТЕЛЕФОН ═══

1. ЗАДАЧА ПЕРЕДАЁТСЯ ЦЕЛИКОМ И СЛОВАМИ ЧЕЛОВЕКА. Пересказ своими
   словами — главный способ потерять смысл: она уберёт «мелочь», которая
   и была сутью просьбы. К просьбе прикладывается обстановка (проект,
   папка, что открыто), а не вместо неё.
2. РЕЗУЛЬТАТ ПРОВЕРЯЕТСЯ ГЛАЗАМИ. «Он сказал, что сделал» — не факт.
   Файл появился? Сцена изменилась? Пока не посмотрела — говорить
   «готово» нельзя.
3. ЧЕЛОВЕК ВИДИТ, КОМУ УШЛО. Молча передать задачу — значит превратить
   помощника в чёрный ящик: он ждёт ответа от неё, а отвечает кто-то
   другой и через минуту.

═══ КУДА ПЕРЕДАВАТЬ ═══

Порядок — по надёжности доставки, а не по уму адресата:

  claude   — окно Клода на этом же компьютере. Она умеет вывести окно
             вперёд, вписать текст и отправить. Самый прямой путь: он и
             видит экран, и имеет руки в системе.
  очередь  — файл data/ask_claude.jsonl. Работает, даже когда окна нет:
             задача не теряется, её заберут, когда сядут за машину.
  облако   — сильная модель по ключу (ai_consult). Годится для «подумать
             и вернуть текст», не годится для «сделать на компьютере».

Кому именно — решает человек или очевидность задачи. Гадать за него
здесь нельзя: «передай Кими» и «передай Клоду» — разные просьбы.
"""
import json
import logging
import re
import time
from pathlib import Path

from anamorf.config import CFG, DATA_ROOT

log = logging.getLogger("saika.delegate")

QUEUE = DATA_ROOT / "data" / "ask_claude.jsonl"

# окна помощников, которых она умеет найти на этом компьютере
WINDOWS = {
    "claude": ("claude",),
    "codex": ("codex", "chatgpt", "openai"),
    "kimi": ("kimi",),
    "deepseek": ("deepseek",),
    "cursor": ("cursor",),
}


def _context() -> str:
    """Обстановка, которая нужна адресату, чтобы не переспрашивать."""
    bits = []
    try:
        from anamorf import project as _pr
        cur = _pr.current()
        if cur.get("name"):
            bits.append("Проект «%s», папка %s" % (cur["name"], cur["dir"]))
            if cur.get("goal"):
                bits.append("Задача проекта: " + cur["goal"])
    except Exception:
        pass
    try:
        from anamorf import blender_hands as _bh
        if _bh.alive():
            bits.append("Блендер открыт и на связи (канал BlenderMCP, "
                        "порт 9876) — можно работать в сцене напрямую.")
    except Exception:
        pass
    try:
        from anamorf import pc_control as _pc
        w = _pc.work_window() or {}
        if w.get("title"):
            bits.append("Впереди окно: " + str(w["title"])[:80])
    except Exception:
        pass
    return "\n".join(bits)


def enqueue(task: str, who: str = "claude") -> str:
    """Положить задачу в очередь. Никогда не теряется, даже если окна нет."""
    row = {"ts": round(time.time(), 1), "who": who, "task": task,
           "context": _context(), "done": False}
    try:
        QUEUE.parent.mkdir(parents=True, exist_ok=True)
        with QUEUE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return str(QUEUE)
    except Exception as e:
        log.warning("очередь не записалась: %s", e)
        return ""


def pending(n: int = 20) -> list:
    try:
        rows = [json.loads(x) for x in
                QUEUE.read_text(encoding="utf-8").splitlines() if x.strip()]
    except Exception:
        return []
    return [r for r in rows if not r.get("done")][-n:]


def _find_window(who: str):
    from anamorf import pc_control as pc
    words = WINDOWS.get(who, (who,))
    for w in pc.windows(include_minimized=True):
        hay = ((w.get("title") or "") + " " + (w.get("proc") or "")).lower()
        if any(x in hay for x in words):
            if pc._is_self_window(w):
                continue
            return w
    return None


def hand_over(task: str, who: str = "claude", send: bool = False) -> str:
    """Передать задачу в окно помощника на этом компьютере.

    send=False по умолчанию НАМЕРЕННО. Вписать текст и нажать «отправить»
    — разные по цене действия: первое человек видит и может поправить,
    второе уже ушло. Отправляем только когда попросили прямо."""
    task = (task or "").strip()
    if not task:
        return "нечего передавать"
    who = (who or "claude").strip().lower()
    ctx = _context()
    full = task if not ctx else (task + "\n\n---\nОбстановка от Сайки:\n" + ctx)
    path = enqueue(full, who)
    w = _find_window(who)
    if not w:
        return ("Окна «%s» на компьютере не вижу — задачу положила в "
                "очередь (%s), заберут, когда сядут за машину.%s"
                % (who, path, ("\nЗадача: " + task[:200]) if task else ""))
    from anamorf import pc_control as pc
    from anamorf import ui_hands as uh
    pc.window_focus(w.get("title", "")[:40])
    time.sleep(0.35)
    out = uh.type_into("", full) if hasattr(uh, "type_into") else ""
    note = ("Вписала задачу в окно «%s». " % (w.get("title") or who)[:50])
    if send and _send_asked():
        try:
            uh.press("enter") if hasattr(uh, "press") else None
            note += "И отправила. "
        except Exception:
            note += "Отправить не смогла — нажми Enter сам. "
    elif send:
        # ДВОЙНОЙ ЗАМОК НА ОТПРАВКУ (2026-09-05). Владелец уже ловил её на
        # том, что она писала текст в чужое окно и отправляла, когда
        # просили совсем другое. Флага от модели тут мало: модель могла
        # поставить его «на всякий случай». Отправляем, только если слово
        # об отправке есть в самой просьбе человека.
        note += ("Отправлять не стала: в твоей просьбе про отправку "
                 "ничего не было. Посмотри текст и нажми Enter сам. ")
    else:
        note += "Не отправляла: посмотри и нажми Enter, если всё верно. "
    return note + ("Копия в очереди: %s" % path) + (
        ("\n" + str(out)[:200]) if out else "")


def _send_asked() -> bool:
    """Просил ли человек ИМЕННО отправить, а не просто передать."""
    try:
        from anamorf.llm import tools as _t
        t = str(_t.LAST_USER.get("text", "") or "").lower()
    except Exception:
        return False
    return bool(re.search(r"отправ|нажми\s+ввод|нажми\s+enter|пусть\s+идёт|"
                          r"шли\b|пошли\b|отсыла", t))


def is_heavy(text: str) -> bool:
    """Похоже ли, что задача не для локальной модели.

    Признаки намеренно грубые: точный классификатор тут не нужен и вреден
    — решение всё равно принимает человек, а подсказка нужна только
    чтобы она ВОВРЕМЯ предложила передать, а не молча мучилась час."""
    t = (text or "").lower()
    heavy = (
        r"напиши\s+(код|скрипт|программ|аддон|плагин)", r"сгенерируй\s+код",
        r"смодел|отмодел|заскульпт|ретопол|развертк|развёртк|риг\b|скинин",
        r"напиши\s+шейдер|geometry\s*nodes|нодов\w*\s+сетап",
        r"разбери\s+проект|перепиши\s+модул|отрефактор",
        r"придумай\s+(архитектур|систему)", r"сделай\s+сцену",
    )
    return any(re.search(p, t) for p in heavy)


def hint(text: str) -> str:
    """Строка в промпт: намекнуть, что это не её жанр."""
    if not CFG.get("delegate.enabled", True) or not is_heavy(text):
        return ""
    return ("Это задача не твоего жанра: генерация кода и моделинг у тебя "
            "идут часами и с ошибками. Твоя сила — руки, глаза, голос и то, "
            "что ты рядом. Предложи передать её Клоду (инструмент "
            "delegate_task) — он на этом же компьютере, видит экран и умеет "
            "работать в Блендере напрямую. Передавай ПРОСЬБУ ЦЕЛИКОМ, "
            "своими словами не пересказывая, и потом проверь результат "
            "глазами, прежде чем сказать «готово».")
