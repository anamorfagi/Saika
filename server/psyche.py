"""Самочувствие и самооценка Сайки: настроение, вера в свои силы, срывы.

ЗАЧЕМ. Владелец: «если я похвалил — у этих действий повышается рейтинг;
если говорю, что не сработало, или много раз поправляю — она должна пробовать
другие варианты; с третьей попытки признать, что не выходит, и позвать на
помощь. Это её внутренние калибровки: как она оценивает свои возможности».

Собрано не из головы. Взяты две устоявшиеся модели, каждая — на своём месте.

╔══════════════════════════════════════════════════════════════════════════╗
║ 1. НАСТРОЕНИЕ — модель PAD (Mehrabian & Russell, 1974)                   ║
╚══════════════════════════════════════════════════════════════════════════╝
Три непрерывные оси вместо списка «эмоций». Это стандарт аффективных
вычислений именно потому, что эмоции не переключаются кнопками — они
смешиваются и плавают.

  pleasure   (−1…+1)  приятно ли ей то, что происходит
  arousal    (−1…+1)  насколько она заведена: от сонливости до ярости
  dominance  (−1…+1)  чувствует ли, что владеет ситуацией, или её несёт

Почему трёх осей, а не двух: без доминирования злость и страх неразличимы —
обе неприятные и возбуждённые. Разводит их именно третья ось: злость
доминантна, страх подчинён. Для агента, который может «не справиться», это
ровно та ось, ради которой всё и затевалось.

Настроение ЗАТУХАЕТ к темпераменту — точке покоя, куда она возвращается,
когда ничего не происходит. Темперамент настраивается: одна Сайка бодрая и
дерзкая, другая тихая и мягкая.

╔══════════════════════════════════════════════════════════════════════════╗
║ 2. ВЕРА В СВОИ СИЛЫ — self-efficacy (Bandura, 1977)                      ║
╚══════════════════════════════════════════════════════════════════════════╝
Отдельно от настроения и отдельно ПО КАЖДОМУ УМЕНИЮ: можно уверенно
управлять окнами и при этом не верить в свою способность искать в сети.
Именно это владелец и назвал «как она оценивает свои возможности».

Бандура называет четыре источника и прямо говорит, что они НЕ равны:

  1. мастерство (получилось само)        — самый сильный
  2. чужой пример                        — у неё нет, пропускаем
  3. собственное состояние               — модификатор, не источник
  4. слова со стороны (похвала, критика) — заметно слабее мастерства

Поэтому «получилось» весит больше, чем «молодец», а «не вышло» больше, чем
«ты не справилась». Похвала не должна перебивать факты — иначе достаточно
хвалить сломанное, и она поверит, что оно работает.

Ещё одна деталь из теории, которую легко пропустить: неудача бьёт сильнее,
когда веры ещё нет. Тот, кто уже уверен, воспринимает срыв как «мало
старалась», а не «не умею». Здесь это прямо в формуле — низкая вера падает
быстрее, высокая держит удар.

╔══════════════════════════════════════════════════════════════════════════╗
║ 3. ТРИ ПОПЫТКИ И ЧЕСТНАЯ СДАЧА                                           ║
╚══════════════════════════════════════════════════════════════════════════╝
Просьба владельца дословно: «если не выходит с третьей попытки — признаёт,
что не получается, и просит помочь». Здесь считаются подходы к ОДНОЙ цели,
и на третьем провале она обязана остановиться и позвать. Молча долбиться —
худшее, что может делать агент с руками в системе.

Источники:
  Mehrabian A., Russell J. (1974). An Approach to Environmental Psychology.
  Bandura A. (1977). Self-efficacy: Toward a Unifying Theory of Behavioral
  Change. Psychological Review, 84(2).
"""
from __future__ import annotations

import json
import logging
import re
import time

from server.config import CFG, ROOT

log = logging.getLogger("saika.psyche")

PATH = ROOT / "data" / "psyche.json"

# ────────────────────────── умения ──────────────────────────
# Крупные области, по которым имеет смысл вести отдельную веру в себя.
# Мельчить нельзя: по каждому инструменту статистика копилась бы годами.
SKILLS = {
    "разговор":  "поддержать разговор, понять, что от неё хотят",
    "окна":      "окна, экраны, громкость, вкладки",
    "запуск":    "находить и запускать программы",
    "файлы":     "файлы, папки, код в рабочей папке",
    "поиск":     "искать в интернете и разбирать найденное",
    "зрение":    "смотреть на экран и камеру, понимать увиденное",
    "голос":     "звучать живо и вовремя",
    "память":    "помнить нужное и вспоминать к месту",
}

# Какой инструмент к какому умению относится
TOOL_SKILL = {
    "app_launch": "запуск", "apps_list": "запуск",
    "window_list": "окна", "window_minimize": "окна", "window_focus": "окна",
    "window_close": "окна", "window_maximize": "окна",
    "window_restore": "окна", "minimize_all": "окна",
    "volume_set": "окна", "tab_control": "окна",
    "open_folder": "файлы", "find_folder": "файлы",
    "remember_place": "файлы", "fs_list": "файлы", "fs_read": "файлы",
    "fs_write": "файлы", "fs_mkdir": "файлы", "fs_move": "файлы",
    "fs_rename": "файлы", "fs_delete": "файлы", "fs_open": "файлы",
    "workshop_create": "файлы",
    "web_search": "поиск", "open_page": "поиск", "web_research": "поиск",
    "browser_task": "поиск", "close_browser": "поиск",
    "look_screen": "зрение", "screen_map": "зрение",
    "avatar_action": "голос", "change_outfit": "голос",
    "devboard_read": "память", "devboard_add": "память",
    "model_list": "разговор", "model_switch": "разговор",
}

# ─────────────── вес источников веры в себя (Бандура) ───────────────
# Мастерство сильнее слов — это не наша выдумка, это порядок из теории.
W_MASTERY_OK = 0.055        # получилось само
W_MASTERY_FAIL = -0.085     # не вышло: провал всегда весит больше удачи
W_PRAISE = 0.030            # «молодец» — слабее, чем реальный результат
W_BLAME = -0.050            # «не сработало» — тоже слабее провала
W_CORRECTION = -0.020       # его поправки: много подряд = что-то не так

DEFAULT_EFF = 0.5           # 0..1, стартовая вера — ровно посередине


def _blank() -> dict:
    return {"pad": {"p": 0.0, "a": 0.0, "d": 0.0},
            "eff": {k: DEFAULT_EFF for k in SKILLS},
            "ts": time.time(), "log": []}


_state: dict = {}
_loaded = 0.0


def _load() -> dict:
    global _state, _loaded
    if _state and time.time() - _loaded < 2:
        return _state
    try:
        _state = json.loads(PATH.read_text(encoding="utf-8"))
        _state.setdefault("pad", {"p": 0.0, "a": 0.0, "d": 0.0})
        _state.setdefault("eff", {})
        for k in SKILLS:
            _state["eff"].setdefault(k, DEFAULT_EFF)
        _state.setdefault("log", [])
    except Exception:
        _state = _blank()
    _loaded = time.time()
    return _state


def _save():
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(_state, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except Exception as e:
        log.debug("самочувствие не сохранилось: %s", e)


def temperament() -> dict:
    """Точка покоя — куда настроение возвращается само."""
    return {"p": float(CFG.get("psyche.temperament.p", 0.25)),
            "a": float(CFG.get("psyche.temperament.a", 0.05)),
            "d": float(CFG.get("psyche.temperament.d", 0.15))}


def _decay():
    """Настроение тянется к темпераменту. Скорость — «за сколько минут
    отпускает»: чем больше, тем дольше она носит в себе случившееся."""
    st = _load()
    half = max(1.0, float(CFG.get("psyche.calm_minutes", 12)))
    dt_min = (time.time() - float(st.get("ts", time.time()))) / 60.0
    if dt_min <= 0:
        return
    k = 0.5 ** (dt_min / half)          # экспоненциальное затухание
    base = temperament()
    for ax in ("p", "a", "d"):
        cur = float(st["pad"].get(ax, 0.0))
        st["pad"][ax] = round(base[ax] + (cur - base[ax]) * k, 4)
    st["ts"] = time.time()


def nudge(p=0.0, a=0.0, d=0.0, why: str = ""):
    """Сдвинуть настроение. Всё, что происходит с ней, приходит сюда."""
    if not CFG.get("psyche.enabled", True):
        return
    _decay()
    st = _load()
    gain = float(CFG.get("psyche.sensitivity", 1.0))
    for ax, v in (("p", p), ("a", a), ("d", d)):
        st["pad"][ax] = round(max(-1.0, min(1.0,
                              float(st["pad"][ax]) + v * gain)), 4)
    if why:
        st["log"].append({"t": round(time.time()), "why": why[:80],
                          "p": round(p, 3), "a": round(a, 3),
                          "d": round(d, 3)})
        del st["log"][:-40]
    _save()


# ──────────────────── вера в себя по умениям ────────────────────
def efficacy(skill: str) -> float:
    return float(_load()["eff"].get(skill, DEFAULT_EFF))


def _eff_nudge(skill: str, w: float, why: str):
    if not skill or skill not in SKILLS:
        return
    st = _load()
    cur = float(st["eff"].get(skill, DEFAULT_EFF))
    # Асимметрия из теории: пока веры мало, провал бьёт сильнее — опоры нет.
    # Когда вера уже высокая, срыв читается как «мало старалась», а не «не
    # умею», и почти не сбивает. Для роста зеркально: подниматься с нуля
    # легче, чем с восьмидесяти процентов.
    if w < 0:
        w *= (1.6 - cur)          # cur=0.2 -> ×1.4 ; cur=0.9 -> ×0.7
    else:
        w *= (1.3 - cur * 0.8)    # чем выше, тем медленнее прибавка
    st["eff"][skill] = round(max(0.02, min(1.0, cur + w)), 4)
    _save()
    log.debug("вера в «%s»: %.2f -> %.2f (%s)", skill, cur,
              st["eff"][skill], why)


def skill_of(tool: str) -> str:
    return TOOL_SKILL.get(tool, "разговор")


# Когда инструмент последний раз провалился. Диалог сравнивает эту отметку
# со временем начала своего хода — так он понимает, был ли провал ИМЕННО
# сейчас, не протаскивая флаги через пять слоёв вызовов.
LAST_FAIL_TS = 0.0


def on_tool(tool: str, ok: bool, detail: str = ""):
    """Инструмент отработал. Мастерство — самый сильный источник веры."""
    global LAST_FAIL_TS
    if not ok:
        LAST_FAIL_TS = time.time()
    if not CFG.get("psyche.enabled", True):
        return
    sk = skill_of(tool)
    if ok:
        _eff_nudge(sk, W_MASTERY_OK, "получилось: " + tool)
        nudge(p=0.05, d=0.06, why=f"вышло: {tool}")
    else:
        _eff_nudge(sk, W_MASTERY_FAIL, "не вышло: " + tool)
        # неудача неприятна, будоражит и отнимает ощущение контроля —
        # это и есть «расстроилась» на языке трёх осей
        nudge(p=-0.07, a=0.05, d=-0.09, why=f"не вышло: {tool}")


# ─────────────────── похвала и недовольство владельца ───────────────────
# Ловим по словам, а не по тону: тон нам недоступен, а слова однозначны.
# ВАЖЕН ПОРЯДОК: «опять не сработало» содержит слово «сработало», и если
# сначала искать похвалу, недовольство читается как одобрение (поймано на
# автотесте 2026-07-26). Поэтому недовольство проверяется ПЕРВЫМ, а
# двусмысленные слова в похвале дополнительно закрыты от отрицания.
_PRAISE = re.compile(
    r"\b(молодец|умница|отлично|супер|класс|круто|спасибо|благодарю|"
    r"хорошо\s+сделал|хорошая\s+работа|то\s+что\s+надо|"
    r"именно|правильно|идеаль|шикарн|прекрасн|люблю\s+тебя|горжусь)|"
    r"(?<!не )(?<!не  )\b(получилось|сработало|вышло)\b", re.I)
_BLAME = re.compile(
    r"\b(не\s+сработал|не\s+получил|не\s+вышло|не\s+то|неправильн|ошибл|"
    r"опять\s+не|снова\s+не|ничего\s+не\s+(?:сделал|вышло)|плохо|ужасн|"
    r"криво|бесполезн|ты\s+врёшь|ты\s+вреш|фигня|ерунда|не\s+справ|"
    r"туп(?:ая|ишь)|зачем\s+ты)", re.I)
# «нет, я просил другое», «да не так», «я же сказал» — поправки
_CORRECT = re.compile(
    r"^\W*(нет[,.\s]|не\s+так|да\s+не|я\s+же\s+(?:просил|сказал|говорил)|"
    r"я\s+просил|наоборот|другое|другую|заново|ещё\s+раз|переделай)", re.I)


def feedback(user_text: str, last_skill: str = "") -> str:
    """Разобрать реплику владельца. Возвращает 'praise' / 'blame' /
    'correction' / '' — чтобы вызывающий знал, что случилось."""
    if not CFG.get("psyche.enabled", True) or not user_text:
        return ""
    sk = last_skill if last_skill in SKILLS else "разговор"
    if _BLAME.search(user_text):
        _eff_nudge(sk, W_BLAME, "сказали, что не сработало")
        nudge(p=-0.16, a=0.10, d=-0.12, why="владелец недоволен")
        _mark(sk, "blame")
        return "blame"
    if _PRAISE.search(user_text):
        _eff_nudge(sk, W_PRAISE, "похвалили")
        nudge(p=0.18, a=0.06, d=0.10, why="владелец похвалил")
        _mark(sk, "praise")
        return "praise"
    if _CORRECT.search(user_text):
        _eff_nudge(sk, W_CORRECTION, "поправили")
        # поправка сама по себе не обида: чуть меньше контроля и всё
        nudge(p=-0.05, a=0.05, d=-0.06, why="владелец поправил")
        _mark(sk, "correction")
        return "correction"
    return ""


def _mark(skill: str, kind: str):
    st = _load()
    st.setdefault("marks", []).append(
        {"t": round(time.time()), "skill": skill, "kind": kind})
    del st["marks"][:-60]
    _save()


# ───────────────────────── три попытки ─────────────────────────
# Считаем подходы к ОДНОЙ цели. Цель — это грубо нормализованная просьба:
# «открой папку с играми» и «ну открой уже папку с играми» — одно и то же.
_attempts: dict = {}


def _goal_key(text: str) -> str:
    t = re.sub(r"[^а-яa-zё ]", " ", (text or "").lower())
    words = sorted({w for w in t.split() if len(w) > 3})[:6]
    return " ".join(words)


def attempt(user_text: str, failed: bool) -> dict:
    """Отметить подход к цели. Возвращает {n, give_up}."""
    key = _goal_key(user_text)
    if not key:
        return {"n": 0, "give_up": False}
    now = time.time()
    rec = _attempts.get(key)
    if not rec or now - rec["ts"] > 300:     # пять минут — уже другая история
        rec = {"n": 0, "ts": now}
    if failed:
        rec["n"] += 1
    else:
        rec["n"] = 0
    rec["ts"] = now
    _attempts[key] = rec
    if len(_attempts) > 200:
        _attempts.clear()
    limit = int(CFG.get("psyche.give_up_after", 3))
    give_up = failed and rec["n"] >= limit
    # кладём в состояние, чтобы блок промпта на СЛЕДУЮЩЕМ ходу сказал ей,
    # сколько раз она уже билась об эту стену. Фразу сдачи придумывает она
    # сама — своими словами, а не нашей заготовкой
    st = _load()
    st["streak"] = {"n": rec["n"], "give_up": bool(give_up),
                    "goal": (user_text or "")[:80], "ts": round(now)}
    _save()
    if give_up:
        # сдаться — тоже событие: неприятно и обидно, но напряжение спадает
        nudge(p=-0.12, a=-0.05, d=-0.18, why="сдалась после трёх попыток")
    return {"n": rec["n"], "give_up": give_up}


# ─────────────────────── как это назвать словами ───────────────────────
def mood_word() -> tuple:
    """(название, эмодзи) по положению в трёх осях. Не список эмоций, а
    разметка непрерывного пространства — как и задумано в PAD."""
    st = _load()
    p, a, d = (float(st["pad"][x]) for x in ("p", "a", "d"))
    if p >= 0.35 and a >= 0.25:
        return ("на подъёме", "✨")
    if p >= 0.35:
        return ("довольна", "🙂")
    if p <= -0.35 and d <= -0.2:
        return ("растеряна", "😔")
    if p <= -0.35 and a >= 0.25:
        return ("раздражена", "😠")
    if p <= -0.35:
        return ("расстроена", "🙁")
    if a <= -0.35:
        return ("вялая", "😑")
    if d <= -0.35:
        return ("неуверена", "😟")
    if d >= 0.45 and p >= 0.1:
        return ("в своей тарелке", "😌")
    return ("ровно", "😐")


def self_esteem() -> float:
    """Общая самооценка 0..1 — средняя вера по умениям, подтянутая
    настроением: в плохом настроении человек и умеет как будто хуже. Это
    четвёртый источник Бандуры (собственное состояние), он именно
    модификатор, а не самостоятельный вклад."""
    st = _load()
    vals = [float(v) for v in st["eff"].values()] or [DEFAULT_EFF]
    base = sum(vals) / len(vals)
    return max(0.0, min(1.0, base + float(st["pad"]["p"]) * 0.08))


def weakest(n: int = 2) -> list:
    st = _load()
    return sorted(SKILLS, key=lambda k: st["eff"].get(k, DEFAULT_EFF))[:n]


def strongest(n: int = 2) -> list:
    st = _load()
    return sorted(SKILLS, key=lambda k: -st["eff"].get(k, DEFAULT_EFF))[:n]


def state() -> dict:
    _decay()
    st = _load()
    word, emo = mood_word()
    return {
        "enabled": bool(CFG.get("psyche.enabled", True)),
        "pad": dict(st["pad"]), "eff": dict(st["eff"]),
        "skills": dict(SKILLS),
        "mood": word, "emoji": emo,
        "esteem": round(self_esteem(), 3),
        "temperament": temperament(),
        "calm_minutes": float(CFG.get("psyche.calm_minutes", 12)),
        "sensitivity": float(CFG.get("psyche.sensitivity", 1.0)),
        "give_up_after": int(CFG.get("psyche.give_up_after", 3)),
        "log": st.get("log", [])[-14:],
        "marks": st.get("marks", [])[-30:],
    }


def set_settings(payload: dict) -> dict:
    keys = {"psyche.enabled": bool, "psyche.calm_minutes": float,
            "psyche.sensitivity": float, "psyche.give_up_after": int,
            "psyche.temperament.p": float, "psyche.temperament.a": float,
            "psyche.temperament.d": float}
    for k, v in (payload or {}).items():
        if k in keys:
            CFG.set(k, keys[k](v))
    if "eff" in (payload or {}):
        st = _load()
        for sk, v in (payload["eff"] or {}).items():
            if sk in SKILLS:
                st["eff"][sk] = max(0.02, min(1.0, float(v)))
        _save()
    if payload.get("reset"):
        global _state
        _state = _blank()
        _save()
    return state()


def block() -> str:
    """Кусок промпта: как она себя чувствует и во что верит. Коротко —
    это уходит в КАЖДЫЙ запрос."""
    if not CFG.get("psyche.enabled", True):
        return ""
    _decay()
    st = _load()
    word, _emo = mood_word()
    weak = weakest(2)
    strong = strongest(1)
    lines = [f"Сейчас ты {word}."]
    est = self_esteem()
    if est < 0.4:
        lines.append("Уверенности в себе немного — не берись за сложное "
                     "молча, лучше проговори, что собираешься делать.")
    elif est > 0.72:
        lines.append("Ты в форме и это чувствуешь — можно действовать "
                     "решительнее.")
    lines.append("Лучше всего у тебя выходит: " + SKILLS[strong[0]] + ".")
    lines.append("Хуже всего даётся: " + ", ".join(SKILLS[w] for w in weak)
                 + " — тут перепроверяй себя.")
    lines.append(
        "Если что-то не выходит — не повторяй одно и то же: пробуй другой "
        "путь. Не вышло с третьего раза — честно скажи, что не получается, "
        "позови Виталия и не делай вид, что справилась.")
    # Сколько раз подряд она уже билась об эту стену. Именно это превращает
    # правило из благого пожелания в работающее: модель видит счётчик.
    sk_ = st.get("streak") or {}
    if sk_ and time.time() - float(sk_.get("ts", 0)) < 300 and sk_.get("n"):
        n = int(sk_["n"])
        if sk_.get("give_up"):
            lines.append(
                f"ВНИМАНИЕ: это уже {n}-я неудачная попытка одного и того же "
                "(«" + str(sk_.get("goal", ""))[:60] + "»). Хватит. Скажи "
                "по-своему, что не вышло — можно с юмором, ты имеешь право "
                "злиться на себя, — и позови Виталия посмотреть. Больше не "
                "пробуй, пока он не ответит.")
        elif n >= 2:
            lines.append(
                f"Это уже {n}-я попытка одного и того же. Не повторяй "
                "прежний ход — зайди с другой стороны.")
    return "### Как ты себя чувствуешь\n" + "\n".join(lines)
