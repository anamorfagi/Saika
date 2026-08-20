"""ПАМЯТЬ НА ПРОГРАММЫ — она учит ТВОЙ словарь (2026-07-29).

ПРОСЬБА ВЛАДЕЛЬЦА, дословно: «она должна запустить любую прогу просто по
запросу; не знает — ищет в системе, в диспетчере, на рабочем столе,
сравнивает похожие, спрашивает ОДИН РАЗ „это оно?“ и запоминает, если
человек подтвердил».

ПОЧЕМУ ЭТО ВАЖНЕЕ, ЧЕМ КАЖЕТСЯ. Человек называет программы своими словами:
«корел», «фотка», «звук», «та штука для чертежей». Никакой список синонимов,
написанный заранее, этого не покроет — потому что словарь у каждого свой и
меняется. Единственный способ не проиграть эту гонку — не угадывать, а
СПРОСИТЬ ОДИН РАЗ и запомнить навсегда. Ровно так устроены зрелые голосовые
оболочки (Talon: сначала список, потом выбор, дальше — свой алиас).

ТРИ УРОВНЯ ПОИСКА, по возрастанию цены:
  1. ВЫУЧЕННОЕ — что владелец уже подтверждал. Мгновенно и без вопросов.
  2. ЯРЛЫКИ — «Пуск» и рабочий стол (это умел и старый код).
  3. ШИРОКИЙ ЗАХОД — реестр App Paths (то самое место, откуда Windows
     запускает программы по имени в «Выполнить»), запущенные процессы
     (программа без ярлыка, но открытая прямо сейчас) и PATH.
Уровень 3 включается, только когда первые два промолчали: он дороже.

ЧТО НЕ ЗАПОМИНАЕМ БЕЗ СПРОСА. Догадка становится памятью ТОЛЬКО после
подтверждения человеком. Молча выученная ошибка хуже честного «не нашла»:
её потом не найти и не переучить.

Выученное лежит в data/app_aliases.json — это личные привычки владельца,
в публичный репозиторий им нельзя (data/ в гитигноре).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from anamorf.config import CFG, ROOT

log = logging.getLogger("saika.pc")

STORE = ROOT / "data" / "app_aliases.json"
_IS_WIN = os.name == "nt"

# что предложили человеку и ждём ответа «да». Живёт минуту: дольше — это уже
# другой разговор, и «да» из него относится не к нам
_pending: dict = {"query": "", "cands": [], "ts": 0.0}
_last: dict = {"query": ""}          # о чём был последний отвеченный вопрос

_learned: dict | None = None


# ─────────────────────────────────────────────────────── выученное
def learned() -> dict:
    global _learned
    if _learned is None:
        try:
            _learned = json.loads(STORE.read_text("utf-8"))
        except Exception:
            _learned = {}
    return _learned


def _save():
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        STORE.write_text(json.dumps(learned(), ensure_ascii=False, indent=1),
                         "utf-8")
    except Exception as e:
        log.warning("Не смогла сохранить выученные названия программ: %s", e)


def remember(query: str, name: str, path: str):
    """Запомнить: этой фразой владелец называет вот эту программу."""
    q = (query or "").strip().lower()
    if not q or not path:
        return
    learned()[q] = {"name": name, "path": path, "ts": time.time(),
                    "hits": int((learned().get(q) or {}).get("hits", 0)) + 1}
    _save()
    log.info("Запомнила: «%s» — это %s", q, name)


def forget(query: str) -> bool:
    q = (query or "").strip().lower()
    if q in learned():
        learned().pop(q)
        _save()
        return True
    return False


def recall(query: str):
    """Выученное совпадение: точное или очень близкое. Возвращает запись
    или None. Близкое — потому что голос не повторяет фразу дословно:
    «открой корел» и «корел» это одна и та же просьба."""
    q = (query or "").strip().lower()
    if not q:
        return None
    L = learned()
    if q in L:
        return L[q]
    # выученная фраза ЦЕЛИКОМ внутри просьбы: «а открой-ка корел драфт» —
    # это та же самая просьба, что и «корел драфт». Берём самую длинную,
    # чтобы «корел драфт» победил «корел»
    inside = [k for k in L if len(k) >= 3 and k in q]
    if inside:
        return L[max(inside, key=len)]
    import difflib
    best, br = None, 0.0
    for k, v in L.items():
        r = difflib.SequenceMatcher(None, k, q).ratio()
        if r > br:
            best, br = v, r
    return best if br >= 0.82 else None


# ─────────────────────────────────────────────── широкий поиск по системе
def _from_registry() -> list:
    """App Paths — реестр, откуда сама Windows запускает программы по имени
    в окне «Выполнить». Тут лежит то, у чего нет ярлыка в «Пуске»."""
    if not _IS_WIN:
        return []
    out = []
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                key = winreg.OpenKey(
                    root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths")
            except OSError:
                continue
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(key, sub) as k2:
                        path = winreg.QueryValueEx(k2, "")[0]
                    if path and Path(path).exists():
                        out.append({"name": Path(sub).stem, "path": path,
                                    "kind": "reg"})
                except Exception:
                    pass
    except Exception as e:
        log.debug("реестр App Paths не прочитался: %s", e)
    return out


def _from_processes() -> list:
    """Запущенные программы. Ловит то, у чего нет ни ярлыка, ни записи в
    реестре, но что открыто прямо сейчас — «закрой ту штуку» про неё."""
    out, seen = [], set()
    try:
        import psutil
        for p in psutil.process_iter(["name", "exe"]):
            try:
                nm = (p.info.get("name") or "").strip()
                ex = p.info.get("exe") or ""
                if not nm or not ex or nm.lower() in seen:
                    continue
                seen.add(nm.lower())
                out.append({"name": Path(nm).stem, "path": ex,
                            "kind": "running"})
            except Exception:
                continue
    except Exception as e:
        log.debug("процессы не перечислились: %s", e)
    return out


def wide_catalog() -> list:
    """Всё, что вообще можно запустить, кроме ярлыков (их знает pc_control).
    Кэш на десять минут: реестр и процессы меняются редко, а обходить их
    на каждую фразу дорого."""
    now = time.time()
    if wide_catalog._cache and now - wide_catalog._ts < 600:
        return wide_catalog._cache
    items, seen = [], set()
    for it in _from_registry() + _from_processes():
        low = it["name"].lower()
        if low in seen or len(low) < 2:
            continue
        seen.add(low)
        items.append(it)
    wide_catalog._cache, wide_catalog._ts = items, now
    log.info("Широкий каталог программ: %d записей (реестр + запущенные)",
             len(items))
    return items


wide_catalog._cache = []
wide_catalog._ts = 0.0


# ──────────────────────────────── подсматривание ────────────────────────────
# (2026-07-29, просьба владельца дословно: «если она не понимает — предлагает
# посмотреть мои действия, получает лог, какая это прога и какой у неё путь,
# и записывает себе: пользователь хотел запустить аркнайтс эндфилд, запустил
# GRYPHLINK, которое открыло Arknights Endfield — сама обучается, какое
# приложение где находится».)
#
# Как работает: поиск провалился -> она честно говорит «не нашла — запусти
# сам, я подсмотрю» и две минуты следит за НОВЫМИ процессами. Первый
# содержательный новый exe — это то, что человек кликнул (лаунчер!); его и
# запоминаем как путь запуска. Что лаунчер открыл следом — упоминаем в
# отчёте, но путём не делаем: игра без лаунчера часто не стартует.

_SYS_NOISE = {
    "svchost.exe", "dllhost.exe", "conhost.exe", "runtimebroker.exe",
    "backgroundtaskhost.exe", "searchhost.exe", "searchapp.exe",
    "explorer.exe", "cmd.exe", "powershell.exe", "python.exe", "pythonw.exe",
    "werfault.exe", "ctfmon.exe", "sihost.exe", "taskhostw.exe",
    "applicationframehost.exe", "smartscreen.exe", "audiodg.exe",
    "wmiprvse.exe", "openconsole.exe", "crashpad_handler.exe",
    "msedgewebview2.exe", "textinputhost.exe", "shellexperiencehost.exe",
}

_watch: dict = {"on": False, "query": "", "until": 0.0}


def _notify(text: str):
    """Сообщение в чат — человек должен УВИДЕТЬ, что она научилась."""
    try:
        from anamorf import main as _m
        _m.broadcast_event({"type": "baymax", "mood": "ok", "text": text})
    except Exception as e:
        log.debug("не смогла сообщить в чат: %s", e)


def watching():
    return _watch["on"] and time.time() < _watch["until"]


def watch(query: str, seconds: int = 120):
    """Начать подсматривать: что человек запустит руками в ближайшие
    seconds — то и есть «query». Работает в своём потоке, диалог не держит."""
    q = (query or "").strip().lower()
    if not q:
        return
    if watching():                      # уже смотрим — просто меняем вопрос
        _watch.update(query=q, until=time.time() + seconds)
        return
    _watch.update(on=True, query=q, until=time.time() + seconds)

    def _job():
        import threading  # noqa: F401  (импорт тут — поток уже наш)
        try:
            import psutil
            base = {p.pid for p in psutil.process_iter()}
            first, chain = None, []

            def _scan():
                out = []
                for p in psutil.process_iter(["name", "exe", "pid"]):
                    try:
                        if p.info["pid"] in base:
                            continue
                        base.add(p.info["pid"])
                        nm = (p.info["name"] or "").lower()
                        ex = p.info["exe"] or ""
                        if ex and nm not in _SYS_NOISE:
                            out.append({"name": Path(ex).stem, "path": ex})
                    except Exception:
                        continue
                return out

            while time.time() < _watch["until"] and first is None:
                time.sleep(1.5)
                for item in _scan():
                    if first is None:
                        first = item
                    elif item["name"].lower() != first["name"].lower():
                        chain.append(item["name"])
            if first is not None:
                # лаунчер часто открывает игру следом — добираем цепочку,
                # чтобы честно сказать «GRYPHLINK, следом Arknights Endfield»
                time.sleep(6)
                for item in _scan():
                    if item["name"].lower() != first["name"].lower():
                        chain.append(item["name"])
            if first is None:
                log.info("Подсматривание за «%s»: никто ничего не запустил",
                         _watch["query"])
                return
            q2 = _watch["query"]
            remember(q2, first["name"], first["path"])
            tail = (" (следом открылось: " + ", ".join(chain[:3]) + ")"
                    if chain else "")
            _notify(f"🎓 Подсмотрела и запомнила: «{q2}» — это "
                    f"{first['name']}{tail}. В следующий раз запущу сама.")
        except Exception as e:
            log.warning("подсматривание сломалось: %s", e)
        finally:
            _watch["on"] = False

    import threading
    threading.Thread(target=_job, daemon=True, name="app-watch").start()


# ─────────────────────────────────────────────────── вопрос и подтверждение
def offer(query: str, cands: list) -> str:
    """Запомнить, что мы спросили, и составить человеческий вопрос."""
    _pending.update(query=(query or "").strip().lower(),
                    cands=cands[:4], ts=time.time())
    # хвост адресован МОДЕЛИ: без него она озвучивает вопрос и на «да»
    # начинает новый поиск с нуля — а весь смысл был спросить один раз
    tail = ("Спроси это вслух и, когда человек ответит, вызови запуск ещё "
            "раз, передав его ответ дословно («да», «второе», «нет») — "
            "я пойму и запомню на будущее.")
    if len(cands) == 1:
        return (f"Не уверена: «{query}» — это {cands[0]['name']}? " + tail)
    lst = "; ".join(f"{i + 1}. {c['name']}" for i, c in enumerate(cands[:4]))
    return (f"Похоже на несколько: {lst}. Какое из них «{query}»? " + tail)


def pending():
    """Есть ли неотвеченный вопрос (и не протух ли он)."""
    if _pending["cands"] and time.time() - _pending["ts"] < 90:
        return _pending
    return None


def last_query() -> str:
    """Фраза, про которую спрашивали. Нужна после confirm — чтобы вслух
    сказать человеку не «запомнила», а «запомнила: „корел“ — это CorelDRAW»."""
    return _last["query"]


def drop():
    """Человек ответил «нет». Забываем вопрос, ничего не выучив: неверная
    догадка, записанная в память, потом ищется часами."""
    _pending.update(query="", cands=[], ts=0.0)


def confirm(pick: int = 1):
    """Ответ человека на «это оно?». pick — номер из списка, с единицы.
    Возвращает выбранную запись или None, если спрашивать было нечего."""
    p = pending()
    if not p:
        return None
    i = max(1, int(pick or 1)) - 1
    if i >= len(p["cands"]):
        return None
    chosen = p["cands"][i]
    remember(p["query"], chosen["name"], chosen["path"])
    _last["query"] = p["query"]
    _pending.update(query="", cands=[], ts=0.0)
    return chosen
