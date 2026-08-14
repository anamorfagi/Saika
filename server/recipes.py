"""ПАМЯТЬ НА УДАЧНЫЕ ЦЕПОЧКИ: второй раз — мгновенно (2026-08-14).

ПРОСЬБА ВЛАДЕЛЬЦА, дословно:

    «чтобы она думала, что делает, и понимала, зачем нужно сделать для
     выполнения запроса, по какой причине… смогла суммаризировать
     результаты и конкретно собирать удачные логические цепочки,
     запоминая, чтобы такой же запрос в будущем выполнить на огромной
     скорости»

ЗАЧЕМ ЭТО, ЕСЛИ ЕСТЬ ЦИКЛ. Цикл (server/agent.py) доводит задачу до конца,
но платит за это думаньем на каждом шаге: пять витков — пять обращений к
модели, секунды и токены. А задачи у человека повторяются: «открой диск C
и найди игры», «включи трек из железного человека», «зайди в комфи юай и
запусти бат». Второй раз думать над тем же — расточительство.

Рецепт — это ЗАСТЫВШИЙ УСПЕХ: последовательность вызовов, которая уже
привела к цели, вместе с «зачем» каждого шага. В следующий раз она
проигрывается напрямую, без единого обращения к мозгу. Это тот же приём,
что рефлексы (server/reflex.py), только правило пишется не программистом,
а самой работой.

ЧТО ЗАПОМИНАЕТСЯ, А ЧТО НЕТ:
  * запоминается ТОЛЬКО доведённое до конца — половина пути не рецепт;
  * запоминаются шаги вместе с причиной («почему»): без причины это
    заклинание, а не логика, и починить его потом нельзя;
  * НЕ запоминаются шаги с изменяющими инструментами, требующими слова
    человека, — их предохранитель всё равно спросит заново, и правильно.

КОГДА РЕЦЕПТ ЗАБЫВАЕТСЯ. Проигрался и не сработал — счётчик промахов
растёт; два промаха подряд, и рецепт снимается. Мир меняется: программу
переставили, диск переименовали. Рецепт, который врёт, хуже отсутствия
рецепта — он уводит уверенно.
"""
from __future__ import annotations

import json
import logging
import re
import time

from server.config import CFG, ROOT

log = logging.getLogger("saika.recipes")

PATH = ROOT / "data" / "recipes.json"
_CACHE: list | None = None
MAX = 200

# слова, которые ничего не говорят о СУТИ задачи
_NOISE = {"сайка", "пожалуйста", "давай", "просто", "ну", "вот", "там",
          "тут", "мне", "мой", "моя", "это", "то", "же", "бы", "а", "и",
          "в", "на", "с", "со", "по", "за", "к", "у", "о", "не", "ещё",
          "еще", "раз", "теперь", "потом", "окей", "ок", "так", "блин"}


# ГЛАГОЛЫ РАЗНЫЕ — ДЕЙСТВИЕ ОДНО (2026-08-14, стенд поймал: «открой диск C
# и найди там игры» и «зайди на диск C, поищи там игры» — одна задача, а
# совпало всего 50%, и рецепт не подхватился). Человек не повторяет свои
# формулировки дословно; узнавать задачу надо по ДЕЙСТВИЮ, а не по слову.
_VERB = [
    (r"^(?:откро|зайд|перейд|спуст|шагай|иди|вернис|подним|вывед)", "@идти"),
    (r"^(?:найд|поищ|ищи|искат|глянь|покаж|где|отыщ)", "@искать"),
    (r"^(?:запус|включ|стартуй|играй|поставь)", "@пустить"),
    (r"^(?:закр|выключ|убер|прекрат)", "@закрыть"),
    (r"^(?:сверн|спрячь)", "@свернуть"),
    (r"^(?:разверн|восстанов|верни)", "@развернуть"),
    (r"^(?:запомн|добавь|отметь|сохран)", "@запомнить"),
    (r"^(?:провер|убедис|глянь как|посмотр)", "@проверить"),
]


def _stem(w: str) -> str:
    for pat, tag in _VERB:
        if re.match(pat, w):
            return tag
    return w[:5]


def _norm(goal: str) -> list:
    """Смысловой костяк просьбы: значимые слова, укороченные до основы.

    Человек каждый раз говорит по-разному — «открой диск C и найди игры»,
    «зайди на C, поищи там игры». Для рецепта это одна и та же задача, и
    узнавать её надо по составу слов, а не по буквальному совпадению."""
    words = re.findall(r"[\wа-яё]+", (goal or "").lower())
    out = []
    for w in words:
        if w in _NOISE or len(w) < 3:
            continue
        out.append(_stem(w))
    return sorted(set(out))


def _load() -> list:
    global _CACHE
    if _CACHE is None:
        try:
            d = json.loads(PATH.read_text("utf-8"))
            _CACHE = d if isinstance(d, list) else []
        except Exception:
            _CACHE = []
    return _CACHE


def _save():
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.write_text(json.dumps(_load()[:MAX], ensure_ascii=False,
                                   indent=1), encoding="utf-8")
    except Exception as e:
        log.debug("рецепты не записались: %s", e)


def _score(a: list, b: list) -> float:
    """Насколько две просьбы про одно и то же: доля общих слов."""
    if not a or not b:
        return 0.0
    common = len(set(a) & set(b))
    return common / max(len(a), len(b))


def find(goal: str) -> dict | None:
    """Готовый рецепт под эту просьбу. None — такого ещё не делали."""
    if not CFG.get("recipes.enabled", True):
        return None
    key = _norm(goal)
    best, bs = None, 0.0
    for r in _load():
        if r.get("misses", 0) >= 2:
            continue
        s = _score(key, r.get("key") or [])
        if s > bs:
            best, bs = r, s
    thr = float(CFG.get("recipes.match", 0.72))
    if best is not None and bs >= thr:
        out = dict(best)
        out["match"] = round(bs, 2)
        return out
    return None


def remember(goal: str, steps: list, said: str = "") -> bool:
    """Запомнить доведённую до конца цепочку."""
    if not CFG.get("recipes.enabled", True):
        return False
    chain = [{"tool": s["tool"], "args": s.get("args") or {},
              "why": (s.get("why") or "")[:120]}
             for s in (steps or [])
             if s.get("tool") and "отклонён" not in str(s.get("result", ""))
             and "уже был" not in str(s.get("result", ""))
             and "тут нет" not in str(s.get("result", ""))]
    if not chain:
        return False
    key = _norm(goal)
    if not key:
        return False
    data = _load()
    for r in data:
        if _score(key, r.get("key") or []) >= 0.9:
            r.update(chain=chain, said=said or r.get("said", ""),
                     hits=int(r.get("hits", 0)) + 1, misses=0,
                     last=time.time(), goal=goal[:120])
            _save()
            return True
    data.insert(0, {"key": key, "goal": goal[:120], "chain": chain,
                    "said": said, "hits": 1, "misses": 0, "last": time.time()})
    del data[MAX:]
    _save()
    log.info("Запомнила цепочку (%d шагов) для «%s»", len(chain), goal[:60])
    return True


def note_miss(goal: str):
    """Рецепт проигрался и не помог — на второй раз снимаем."""
    key = _norm(goal)
    for r in _load():
        if _score(key, r.get("key") or []) >= 0.9:
            r["misses"] = int(r.get("misses", 0)) + 1
            if r["misses"] >= 2:
                log.info("Рецепт «%s» больше не работает — забываю",
                         r.get("goal", "")[:50])
            _save()
            return


def replay(rec: dict, on_step=None, user_text: str = "") -> dict:
    """Проиграть цепочку напрямую, без единого обращения к мозгу.

    Возвращает {ok, steps}. ok=False — что-то пошло не так; вызывающий
    обязан откатиться к обычному циклу, а не выдавать провал за успех."""
    from server.llm import tools as _t
    _t.LAST_USER["text"] = user_text or rec.get("goal", "")
    steps, bad = [], 0
    t0 = time.time()
    for s in rec.get("chain") or []:
        try:
            res = str(_t.call(s["tool"], s.get("args") or {}) or "")
        except Exception as e:
            res = f"вызов сорвался: {e}"
        steps.append({"tool": s["tool"], "args": s.get("args") or {},
                      "result": res, "why": s.get("why", "")})
        if on_step:
            try:
                on_step(s["tool"], s.get("args") or {}, res)
            except Exception:
                pass
        # ПРИЗНАКИ, ЧТО РЕЦЕПТ ПРОТУХ. Не пытаемся понимать текст ответа
        # умом — берём прямые признаки отказа, которые пишут сами
        # инструменты. Всё остальное считаем успехом: перестраховка тут
        # дороже, чем один лишний виток обычного цикла.
        low = res.lower()
        if ("не нашла" in low or "тут нет" in low or "не получилось" in low
                or "отказ:" in low or "не смогла" in low
                or low.startswith("нечего")):
            bad += 1
    ok = bad == 0 and bool(steps)
    log.info("Рецепт проигран за %.1fс: %s (%d шагов, осечек %d)",
             time.time() - t0, "успех" if ok else "мимо", len(steps), bad)
    return {"ok": ok, "steps": steps}


# ═══ ГРАБЛИ: ЧТО НА ЭТОЙ МАШИНЕ НЕ РАБОТАЕТ ═══
# Владелец: «неудачи тоже нужно учитывать. мы учимся на ошибках, но для ИИ
# это не совсем корректно — вы изначально дохера знаете».
#
# Замечание точное, и оно меняет ЧТО именно запоминать. Учить модель тому,
# что она и так знает, бессмысленно: она знает, как устроен проводник и
# что такое ярлык. Чего она знать НЕ МОЖЕТ — это particulars ЭТОЙ машины:
# что окно «Контакты» не ловится по слову «проводник», что диск E у него
# зовётся HDD_Work, что вот этот .bat лежит не там, где логично.
#
# Поэтому память ошибок здесь — не «учись на неудачах вообще», а список
# конкретных тупиков: такая-то попытка при такой-то цели не сработала.
# Он идёт В ПРОМПТ решения, чтобы второй раз в ту же дверь не ломиться.
FAILS = ROOT / "data" / "recipe_fails.json"
_FCACHE: list | None = None


def _fload() -> list:
    global _FCACHE
    if _FCACHE is None:
        try:
            d = json.loads(FAILS.read_text("utf-8"))
            _FCACHE = d if isinstance(d, list) else []
        except Exception:
            _FCACHE = []
    return _FCACHE


def remember_fail(goal: str, tool: str, args: dict, result: str):
    """Этот шаг при этой цели не сработал. Запоминаем ровно факт."""
    if not tool or not CFG.get("recipes.enabled", True):
        return
    key = _norm(goal)
    sig = tool + "|" + json.dumps(args or {}, ensure_ascii=False,
                                  sort_keys=True)[:120]
    d = _fload()
    for f in d:
        if f.get("sig") == sig and _score(key, f.get("key") or []) >= 0.8:
            f["n"] = int(f.get("n", 1)) + 1
            f["last"] = time.time()
            break
    else:
        d.insert(0, {"key": key, "sig": sig, "tool": tool,
                     "args": args or {}, "why": (result or "")[:160],
                     "n": 1, "last": time.time()})
        del d[300:]
    try:
        FAILS.parent.mkdir(parents=True, exist_ok=True)
        FAILS.write_text(json.dumps(d[:300], ensure_ascii=False, indent=1),
                         encoding="utf-8")
    except Exception as e:
        log.debug("грабли не записались: %s", e)


def _covers(a: list, b: list) -> float:
    """Насколько ОДНА задача входит в другую (а не совпадает с ней).

    Для рецепта нужно точное совпадение — иначе проиграем чужую цепочку.
    Для грабель наоборот: «закрой проводник» и «закрой проводник на первом
    экране» — про одно и то же, и известный тупик стоит вспомнить даже
    когда просьба стала подробнее. Считаем по МЕНЬШЕЙ из двух."""
    if not a or not b:
        return 0.0
    return len(set(a) & set(b)) / min(len(a), len(b))


def rakes(goal: str, limit: int = 6) -> list:
    """Известные тупики под эту задачу — чтобы не ломиться туда снова."""
    if not CFG.get("recipes.enabled", True):
        return []
    key = _norm(goal)
    out = []
    for f in _fload():
        if _covers(key, f.get("key") or []) >= 0.7:
            out.append(f)
    out.sort(key=lambda f: -int(f.get("n", 1)))
    return out[:limit]


def rakes_text(goal: str) -> str:
    """То же словами, для промпта решения."""
    rs = rakes(goal)
    if not rs:
        return ""
    lines = ["УЖЕ ПРОБОВАЛИ И НЕ ВЫШЛО (на этой машине, не в теории):"]
    for f in rs:
        a = json.dumps(f.get("args") or {}, ensure_ascii=False)
        lines.append(f"- {f['tool']}({a}) -> {f.get('why', '')[:90]}"
                     + (f" [раз: {f['n']}]" if f.get("n", 1) > 1 else ""))
    lines.append("Этими путями не ходи — ищи другой.")
    return "\n".join(lines)


def stats() -> dict:
    d = _load()
    return {"count": len(d),
            "top": [{"goal": r.get("goal", ""), "hits": r.get("hits", 0),
                     "steps": len(r.get("chain") or [])}
                    for r in sorted(d, key=lambda x: -x.get("hits", 0))[:8]]}
