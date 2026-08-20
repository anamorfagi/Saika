"""Лорбук: факты о мире, которые всплывают по упоминанию (2026-07-26).

ЗАЧЕМ. Всё, что Сайка должна знать «вообще» — имена зрителей, история
канала, постоянные шутки, названия наших модулей, кто такой Беймакс — можно
было бы вписать в персону. Но персона едет в КАЖДЫЙ запрос: сто фактов там
это сто фактов контекста на каждую фразу, и они вытесняют то, что реально
нужно сейчас. Лорбук решает это иначе: запись лежит тихо и подмешивается в
промпт только тогда, когда в разговоре прозвучал её ключ.

Идея (записи с ключами, глубиной сканирования, кулдауном) взята из разбора
Soul of Waifu; реализация своя — его код под GPL-3.0.

Данные: data/lorebook.json (в .gitignore, как и вся папка data) — это личное
знание конкретной машины, в публичный репозиторий ему не надо.

Формат записи:
    {
      "id": "beymax",
      "keys": ["беймакс", "baymax", "доктор"],   # ключи, регистр не важен
      "content": "Беймакс — её собственная система самодиагностики…",
      "enabled": true,
      "always": false,       # true = всегда в промпте, без ключей
      "depth": 4,            # в скольких последних сообщениях искать ключи
      "cooldown_s": 0,       # не повторять чаще, чем раз в N секунд
      "priority": 0          # больше = выше в списке при переполнении
    }
"""
import json
import logging
import re
import threading
import time

from anamorf.config import CFG, resolve

log = logging.getLogger("saika.lore")

_lock = threading.Lock()
_fired: dict = {}          # id -> когда запись последний раз срабатывала


def path():
    return resolve(CFG.get("lore.path", "data/lorebook.json"))


def load() -> list:
    p = path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("entries", []) if isinstance(data, dict) else data
    except Exception as e:
        log.warning("лорбук не читается (%s) — работаю без него", e)
        return []


def save(entries: list):
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        p.write_text(json.dumps({"entries": entries}, ensure_ascii=False,
                                indent=2), encoding="utf-8")
    log.info("Лорбук сохранён: %d записей", len(entries))


def upsert(entry: dict) -> list:
    """Добавить или обновить запись. Без id — заводим по первому ключу."""
    entries = load()
    eid = str(entry.get("id") or "").strip()
    if not eid:
        keys = entry.get("keys") or []
        # без ключей (запись с always) имя берём из первых слов содержимого —
        # «запись», «запись_2», «запись_3» в списке ни о чём не говорят
        seed = keys[0] if keys else " ".join(
            str(entry.get("content", "")).split()[:3]) or "запись"
        base = re.sub(r"[^\w]+", "_", seed).strip("_")[:32]
        eid = base.lower() or f"e{int(time.time())}"
        taken = {e.get("id") for e in entries}
        n, cand = 2, eid
        while cand in taken:
            cand, n = f"{eid}_{n}", n + 1
        eid = cand
    entry["id"] = eid
    entry.setdefault("enabled", True)
    entry.setdefault("always", False)
    entry.setdefault("depth", int(CFG.get("lore.depth", 4)))
    entry.setdefault("cooldown_s", 0)
    entry.setdefault("priority", 0)
    entry["keys"] = [str(k).strip() for k in (entry.get("keys") or [])
                     if str(k).strip()]
    for i, e in enumerate(entries):
        if e.get("id") == eid:
            entries[i] = entry
            break
    else:
        entries.append(entry)
    save(entries)
    return entries


def delete(eid: str) -> list:
    entries = [e for e in load() if e.get("id") != eid]
    save(entries)
    _fired.pop(eid, None)
    return entries


# Русский склоняет, а владелец пишет ключ словарной формой. Поэтому перед
# поиском отрезаем окончание: «озвучка» -> «озвучк» ловит и «озвучку», и
# «озвучки», и «озвучкой». Без этого запись с ключом «озвучка» молча не
# срабатывала на фразу «почини озвучку» — поймано на тесте 2026-07-26.
_TAIL_LETTERS = "аяоеёыиуюьйАЯОЕЁЫИУЮЬЙ"


def _stem(k: str) -> str:
    """Основа ключа: снимаем до двух конечных гласных/мягких знаков, но не
    короче трёх букв — иначе «яма» превратилась бы в «я» и ловила всё."""
    s = k
    for _ in range(2):
        if len(s) > 3 and s[-1] in _TAIL_LETTERS:
            s = s[:-1]
        else:
            break
    return s


def _key_hit(key: str, text: str) -> bool:
    """Ключ найден в тексте. Начало слова обязательно (чтобы «рт» не ловилось
    внутри «спорт»), конец — свободен, там живёт окончание."""
    k = key.strip().lower()
    if not k:
        return False
    if len(k) < 3:                      # короткие ключи — только целым словом
        return re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", text) is not None
    return re.search(r"(?<!\w)" + re.escape(_stem(k)), text) is not None


def relevant(user_text: str, history=None) -> list:
    """Какие записи всплыли на этот ход. history — список последних текстов
    (свежие в конце), чтобы ключ, названный пару реплик назад, ещё работал."""
    entries = [e for e in load() if e.get("enabled", True)]
    if not entries:
        return []
    hist = [str(h or "") for h in (history or [])]
    now = time.time()
    hits = []
    for e in entries:
        eid = e.get("id") or ""
        cd = float(e.get("cooldown_s") or 0)
        if cd and now - _fired.get(eid, 0) < cd:
            continue
        if e.get("always"):
            hits.append(e)
            continue
        depth = max(1, int(e.get("depth") or 4))
        # окно сканирования: текущая фраза плюс последние depth-1 сообщений
        window = " \n ".join(hist[-(depth - 1):] + [str(user_text or "")]).lower()
        if any(_key_hit(k, window) for k in e.get("keys", [])):
            hits.append(e)
    if not hits:
        return []
    hits.sort(key=lambda e: (-int(e.get("priority") or 0),
                             str(e.get("id") or "")))
    cap = int(CFG.get("lore.max_entries", 6))
    hits = hits[:cap]
    for e in hits:
        _fired[e.get("id") or ""] = now
    return hits


def block(user_text: str, history=None) -> str:
    """Готовый кусок для промпта или пустая строка."""
    hits = relevant(user_text, history)
    if not hits:
        return ""
    log.info("Лорбук: всплыло %d (%s)", len(hits),
             ", ".join(e.get("id", "?") for e in hits))
    body = "\n".join("- " + str(e.get("content", "")).strip()
                     for e in hits if str(e.get("content", "")).strip())
    if not body:
        return ""
    # Формулировка важна: это ЕЁ знание, а не справка от системы. Иначе
    # модель начинает пересказывать блок вслух («в моём лорбуке написано…»),
    # вместо того чтобы просто знать.
    return ("### Что ты знаешь об этом мире (это твоя собственная память, "
            "не цитируй и не упоминай, что тебе это подсказали):\n" + body)


def stats() -> dict:
    entries = load()
    return {"count": len(entries),
            "enabled": sum(1 for e in entries if e.get("enabled", True)),
            "always": sum(1 for e in entries if e.get("always"))}
