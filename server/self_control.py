"""СВОИ НАСТРОЙКИ — то, что раньше жило только кнопками в интерфейсе.

2026-08-13, при сверке с VOICE_TESTS.md: цель — управлять компом с дивана,
а половина её собственных настроек оставалась доступна только мышкой.
«Выгрузи всё из памяти», «сколько ты токенов сожгла», «что сейчас слышно»,
«выключи микрофон», «переключись на другой голос» — под каждым пунктом
протокола стояла кнопка и НИ ОДНОГО инструмента.

Правило простое: если в интерфейсе есть кнопка, у Сайки должен быть
инструмент. Иначе «не вставая с дивана» разбивается о первую же настройку.
"""
import logging

from server.config import CFG

log = logging.getLogger("saika.selfctl")

SCHEMAS = [
    {"type": "function", "function": {
        "name": "unload_memory",
        "description": ("Выгрузить ВСЁ тяжёлое из памяти: слух, голос, "
                        "локальные модели, кэш видеокарты. Сама останешься "
                        "работать, нужное подгрузится заново. Зови на "
                        "«выгрузи всё из памяти», «освободи память», "
                        "«память забита»."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "usage_report",
        "description": ("Сколько токенов потрачено на облачные модели за "
                        "период и во что это обошлось. Зови на «сколько ты "
                        "сожгла», «сколько потратила», «расход»."),
        "parameters": {"type": "object", "properties": {
            "days": {"type": "integer", "description": "за сколько дней"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "hearing_now",
        "description": ("Что звучит вокруг прямо сейчас — метки твоего "
                        "слуха. Зови на «что слышишь», «что там шумит», "
                        "«слышишь музыку?»."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "where_am_i",
        "description": ("Что сейчас открыто и какое окно впереди. Зови на "
                        "«где ты», «что у меня открыто», «что сейчас "
                        "впереди»."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "set_engine",
        "description": ("Переключить свой движок: слух (stt), голос (tts) "
                        "или шумодав. Зови на «переключись на другой "
                        "голос», «включи вosk», «выключи микрофон» "
                        "(kind=stt, name=none)."),
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string", "description": "stt | tts | denoise"},
            "name": {"type": "string", "description":
                     "имя движка; none/off — выключить"}},
            "required": ["kind", "name"]}}},
    {"type": "function", "function": {
        "name": "engines_list",
        "description": ("Какие движки слуха и голоса есть и какой сейчас "
                        "включён. Зови, когда просят переключить, но не "
                        "назвали конкретный."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]
SCHEMAS += [
    {"type": "function", "function": {
        "name": "guests_may_talk",
        "description": ("Разрешить или запретить отвечать ЧУЖИМ голосам. "
                        "По умолчанию отвечаешь только владельцу, остальных "
                        "слышишь и записываешь молча. Зови на «можешь "
                        "отвечать всем», «поговори с ним», «отвечай только "
                        "мне», «не отвечай другим»."),
        "parameters": {"type": "object", "properties": {
            "allow": {"type": "boolean",
                      "description": "true — отвечать всем"}},
            "required": ["allow"]}}},
    {"type": "function", "function": {
        "name": "remember_my_voice",
        "description": ("Запомнить голос говорящего как ГОЛОС ВЛАДЕЛЬЦА — "
                        "после этого ты узнаёшь его и отвечаешь только ему. "
                        "Зови на «запомни мой голос», «это я», «отмечай "
                        "меня по голосу». Нужно имя."),
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "как его зовут"}},
            "required": ["name"]}}},
]

# КОСТЮМЫ (2026-08-13, идея владельца про карточки персонажей из игр,
# аниме и фильмов). Инструменты намеренно простые: список, надеть, снять,
# сочинить новую. Сочиняет карточку сильнейший мозг с лестницы — список
# персонажей бесконечен, зашивать его в код смысла нет.
SCHEMAS += [
    {"type": "function", "function": {
        "name": "card_list",
        "description": ("Показать, какие карточки персонажей (костюмы) "
                        "есть и какой надет сейчас. Зови на «какие есть "
                        "костюмы/персонажи», «кем ты можешь быть»."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "card_wear",
        "description": ("Надеть костюм персонажа: манера речи и голос "
                        "меняются, ты сама остаёшься собой. Зови на "
                        "«побудь <имя>», «надень костюм <имя>», «отыграй "
                        "<имя>»."),
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string", "description": "имя карточки из card_list"}},
            "required": ["id"]}}},
    {"type": "function", "function": {
        "name": "card_off",
        "description": ("Снять костюм и вернуться к себе. Зови на «сними "
                        "костюм», «хватит отыгрывать», «будь собой»."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "card_make",
        "description": ("Сочинить НОВУЮ карточку персонажа и сохранить её. "
                        "Зови, когда просят персонажа, которого в списке "
                        "нет. Сочиняет сильнейший доступный мозг."),
        "parameters": {"type": "object", "properties": {
            "who": {"type": "string",
                    "description": "кто именно, напр. «2B из NieR: Automata»"}},
            "required": ["who"]}}},
]


def card_list(args) -> str:
    from server import cards
    have = cards.list_cards()
    now = cards.active()
    if not have:
        return ("карточек пока нет — сочини первую через card_make, "
                "например «Гарри Поттер»")
    lines = [f"{c['id']} — {c.get('name', c['id'])}"
             + (f" ({c['source']})" if c.get("source") else "")
             for c in have]
    tail = (f"\nСейчас надет: {now.get('name', now['id'])}" if now
            else "\nСейчас костюма нет — ты это ты.")
    return "Костюмы:\n" + "\n".join(lines) + tail


def card_wear(args) -> str:
    from server import cards
    return cards.wear(str((args or {}).get("id", "")))


def card_off(args) -> str:
    from server import cards
    return cards.off()


def card_make(args) -> str:
    from server import cards
    return cards.make(str((args or {}).get("who", "")))


NAMES = {s["function"]["name"] for s in SCHEMAS}


def guests_may_talk(args) -> str:
    allow = bool((args or {}).get("allow"))
    CFG.set("owner.only_owner", not allow)
    log.info("Чужим голосам отвечать: %s", "да" if allow else "нет")
    return ("теперь отвечаю всем, кто заговорит" if allow else
            "теперь отвечаю только владельцу — остальных слышу и записываю, "
            "но молчу")


def remember_my_voice(args) -> str:
    name = str((args or {}).get("name") or "").strip()
    if not name:
        return "нужно имя: как тебя записать?"
    try:
        from server import voiceprint as vp
        cur, conf = vp.who_now()
        if not cur:
            return ("голос сейчас не узнаётся устойчиво — скажи ещё пару "
                    "фраз подряд, и я запомню. Так честнее, чем записать "
                    "наугад чужой тембр.")
        if cur != name:
            try:
                vp.rename(cur, name)
            except Exception as e:
                log.debug("переименование голоса: %s", e)
        r = vp.seal_owner(name)
        CFG.set("owner.name", name)
        if not r.get("ok", True):
            return f"не вышло пометить голос: {r}"
        return (f"запомнила: этот голос — {name}, владелец. Теперь узнаю "
                "тебя и отвечаю тебе; чужих слышу, но молчу, пока не "
                "разрешишь.")
    except Exception as e:
        log.exception("владелец по голосу")
        return f"не получилось: {e}"


def unload_memory(args=None) -> str:
    try:
        from server.main import do_panic_unload
        r = do_panic_unload()
        return r or "выгрузила всё тяжёлое из памяти"
    except Exception as e:
        log.exception("выгрузка")
        return f"выгрузить не вышло: {e}"


def usage_report(args=None) -> str:
    days = 7
    try:
        days = int((args or {}).get("days") or 7)
    except Exception:
        pass
    try:
        from server import usage
        r = usage.report(days)
    except Exception as e:
        return f"счётчик не ответил: {e}"
    rows = [x for x in r.get("rows", []) if x.get("cloud")]
    if not rows:
        return (f"за {days} дн. облачные модели не звались — всё считала "
                "локально, то есть бесплатно")
    parts = []
    for x in rows:
        c = ("" if x.get("cost") is None
             else f", ~{x['cost']:.2f}")
        parts.append(f"{x['model'].split('/')[-1]}: {x['in']}→{x['out']} "
                     f"токенов за {x['calls']} обращений{c}")
    t = r.get("today_cloud") or {}
    tail = f". Сегодня: {t.get('in', 0) + t.get('out', 0)} токенов"
    if r.get("cost_unknown"):
        tail += " (цену не считаю — ставки не заданы в llm.pricing)"
    elif r.get("cloud_cost") is not None:
        tail += f", всего за период ~{r['cloud_cost']:.2f}"
    return f"За {days} дн. — " + "; ".join(parts) + tail


def hearing_now(args=None) -> str:
    try:
        from server import hearing
        tags = hearing.now()
    except Exception as e:
        return f"уши не ответили: {e}"
    if not tags:
        return ("сейчас ничего заметного не слышно — либо тихо, либо уши "
                "ещё не установлены. Скажи это честно.")
    return "Слышу: " + ", ".join(f"{t} ({int(p * 100)}%)" for t, p in tags)


def where_am_i(args=None) -> str:
    try:
        from server import situation
        b = situation.block()
    except Exception as e:
        return f"обстановку не собрала: {e}"
    return b or "не смогла понять, что сейчас открыто"


def engines_list(args=None) -> str:
    out = []
    try:
        from server import stt
        cur = CFG.get("stt.engine", "")
        names = sorted(getattr(stt, "ALL_ENGINES", {}) or {})
        out.append(f"Слух: сейчас «{cur}», есть — {', '.join(names) or '?'}")
    except Exception as e:
        out.append(f"слух не опросился: {e}")
    try:
        from server import tts
        cur = CFG.get("tts.engine", "")
        names = sorted(getattr(tts, "engines", {}) or {})
        out.append(f"Голос: сейчас «{cur}», есть — {', '.join(names) or '?'}")
    except Exception as e:
        out.append(f"голос не опросился: {e}")
    return "\n".join(out)


def set_engine(args) -> str:
    a = args or {}
    kind = str(a.get("kind") or "").strip().lower()
    name = str(a.get("name") or "").strip().lower()
    if kind in ("слух", "микрофон", "stt"):
        kind = "stt"
    elif kind in ("голос", "озвучка", "tts"):
        kind = "tts"
    elif kind in ("шумодав", "denoise"):
        kind = "denoise"
    if kind not in ("stt", "tts", "denoise"):
        return "не поняла, что переключать: слух, голос или шумодав?"
    if name in ("выключи", "выключить", "off", "нет"):
        name = "none" if kind == "stt" else "off"
    try:
        if kind == "stt":
            from server import stt as _s
            _s.set_engine(name)
            return (f"слух выключен" if name in ("none", "off")
                    else f"слушаю движком «{name}»")
        if kind == "tts":
            from server import tts as _t
            _t.set_engine(name)
            return ("озвучка выключена" if name in ("none", "off")
                    else f"говорю движком «{name}»")
        from server import denoise as _d
        _d.set_engine(name)
        return f"шумодав: «{name}»"
    except Exception as e:
        return (f"движок «{name}» не встал: {e}. Позови engines_list и "
                "назови человеку тот, что есть.")


CALLS = {"unload_memory": unload_memory, "usage_report": usage_report,
         "hearing_now": hearing_now, "where_am_i": where_am_i,
         "set_engine": set_engine, "engines_list": engines_list,
         "guests_may_talk": guests_may_talk,
         "remember_my_voice": remember_my_voice,
         "card_list": card_list, "card_wear": card_wear,
         "card_off": card_off, "card_make": card_make}
