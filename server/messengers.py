"""Коннекторы мессенджеров: Telegram + VK. Позволяют управлять ПК с телефона
(«закрой VPN на домашнем ПК») — что особенно выручает, когда VPN/сеть рубят
удалёнку, а мессенджер всё равно достучится.

Модель: КАЖДЫЙ ПК = свой бот (свой токен в его config.json). Пишешь тому боту,
которым владеешь этот ПК; конфликтов опроса одного токена нет. Отвечает бот с
префиксом имени ПК (messengers.pc_name).

Безопасность (важно, это управление ПК из интернета):
- отвечаем ТОЛЬКО владельцу (messengers.owner_ids.<platform>);
- опасное (завершить/запустить) — только после подтверждения «да»;
- запуск — лишь из белого списка путей (messengers.launch_allowlist);
- критические системные процессы не убиваются (см. system_control).
- ТОКЕН БОТА — это ключ от ПК, держи в секрете (он в config.json, не пушь его).

Всё по умолчанию ВЫКЛЮЧЕНО (enabled:false). Включается заполнением токена.
Работает поверх requests (long-polling), публичный IP не нужен.
"""
import json
import logging
import threading
import time

import requests

from server.config import CFG, ROOT

log = logging.getLogger("saika.msg")


def _effective_cfg():
    """Настройки мессенджеров = config.json, поверх — secrets.json (если есть).
    Токены держим в secrets.json, чтобы git-пуш не утащил их на GitHub."""
    m = dict(CFG.get("messengers", {}) or {})
    sp = ROOT / "secrets.json"
    if sp.exists():
        try:
            s = json.loads(sp.read_text(encoding="utf-8")).get("messengers", {})
            for k, v in (s or {}).items():
                if isinstance(v, dict) and isinstance(m.get(k), dict):
                    m[k] = {**m[k], **v}
                else:
                    m[k] = v
        except Exception as e:
            log.warning("secrets.json не прочитан: %s", e)
    return m

# незавершённые подтверждения опасных команд: (platform, user_id) -> dict
_pending = {}
CONFIRM_TTL = 90  # сек на «да»

_CONFIRM = {"да", "ага", "yes", "y", "давай", "подтверждаю", "жми", "го"}
_CANCEL = {"нет", "no", "отмена", "стоп", "не надо"}

HELP = ("Я Сайка на «{pc}». Команды:\n"
        "• статус — нагрузка ЦП/ОЗУ/GPU\n"
        "• процессы — что запущено (топ по памяти)\n"
        "• найди <имя> — найти процесс\n"
        "• закрой <имя> — завершить процесс (спрошу подтверждение)\n"
        "• запусти <имя> — запустить из белого списка\n"
        "Опасные действия подтверждаю по «да».")


def _expand(cfg, word):
    """Разворачиваем разговорное слово в список имён процессов через
    config.aliases. Значение алиаса — строка ИЛИ список (напр. «впн» ->
    ['amnezia','hupp','bluc'], чтобы одной командой закрыть все VPN)."""
    aliases = cfg.get("aliases", {}) or {}
    v = aliases.get(word.lower().strip(), word)
    return v if isinstance(v, list) else [v]


def _control_on():
    """Мастер-рубильник управления ПК. Читаем ЖИВО из CFG (не из кэша), чтобы
    переключатель в интерфейсе действовал сразу. Выключен -> ни закрыть, ни
    запустить нельзя, даже с подтверждением (защита: друг ничего не сломает,
    пока владелец сам не включит функцию)."""
    return bool(CFG.get("messengers.control_enabled", False))


# РЕЖИМ ЗНАКОМСТВА (2026-08-17). Курица и яйцо: чтобы бот слушался только
# владельца, нужен его числовой id, а узнать этот id владельцу негде — в
# Телеграме он нигде не показан. Раньше бот в такой ситуации просто НЕ
# ЗАПУСКАЛСЯ, и человек упирался в тупик: токен вписан, бот молчит, а
# почему — видно только в логе сервера.
# Теперь без списка владельцев бот поднимается, но не делает НИЧЕГО: любому
# написавшему отвечает его же id и инструкцией. Это безопасно (команды в
# этом режиме не исполняются ни для кого) и ровно этого хватает, чтобы
# владелец узнал свой id и вписал его.
_GREET = (
    "\U0001f44b Это Сайка, но я пока никого не знаю в лицо.\n\n"
    "Твой числовой id в Телеграме: {uid}\n\n"
    "Впиши его в secrets.json, в messengers.owner_ids.telegram, и\n"
    "перезапусти меня. До тех пор я никаких команд не выполняю — ни от\n"
    "тебя, ни от кого-либо ещё.")

_LOCKED = ("🔒 Управление ПК сейчас ВЫКЛЮЧЕНО владельцем. Включи рубильник в "
           "интерфейсе Сайки (правый верхний угол), тогда смогу закрывать/"
           "запускать. Статус и список процессов доступны всегда.")


def _reply_for(platform, user_id, text, cfg):
    from server import system_control as sc
    pc = cfg.get("pc_name", "этот ПК")
    t = (text or "").strip()
    low = t.lower()
    key = (platform, user_id)

    # 1) ждём подтверждение опасного действия?
    pend = _pending.get(key)
    if pend and time.time() - pend["ts"] < CONFIRM_TTL:
        if low in _CONFIRM:
            _pending.pop(key, None)
            if not _control_on():
                return f"🖥 {pc}: " + _LOCKED
            if pend["action"] == "kill":
                return f"🖥 {pc}: " + sc.kill(
                    pend["arg"], allow=cfg.get("kill_allowlist", []),
                    deny=cfg.get("kill_denylist", []))
            if pend["action"] == "launch":
                return f"🖥 {pc}: " + sc.launch(
                    pend["arg"], cfg.get("launch_allowlist", {}))
        if low in _CANCEL:
            _pending.pop(key, None)
            return f"🖥 {pc}: отменила."
        # иначе — новая команда, старое подтверждение сбрасываем
        _pending.pop(key, None)

    # 2) обычные команды
    if low in ("/start", "help", "команды", "помощь", "что умеешь"):
        return HELP.format(pc=pc)

    if low in ("статус", "status", "как дела", "нагрузка", "здоровье"):
        return f"🖥 {pc}:\n" + sc.status_text()

    if low in ("процессы", "что запущено", "список процессов", "список"):
        return f"🖥 {pc}:\n" + sc.list_top()

    for kw in ("найди ", "поиск ", "find "):
        if low.startswith(kw):
            subs = _expand(cfg, t[len(kw):])
            hits = []
            for s in subs:
                hits += sc.find(s)
            if not hits:
                return f"🖥 {pc}: по «{t[len(kw):]}» ничего не запущено."
            lines = [f"  {nm} (pid {pid})" for pid, nm in hits[:15]]
            return f"🖥 {pc}: нашла:\n" + "\n".join(lines)

    for kw in ("закрой ", "заверши ", "убей ", "выключи ", "kill ", "закрыть "):
        if low.startswith(kw):
            if not _control_on():
                return f"🖥 {pc}: " + _LOCKED
            raw = t[len(kw):]
            subs = _expand(cfg, raw)
            hits = []
            for s in subs:
                hits += (sc.find(s) if not str(s).isdigit()
                         else [(int(s), s)])
            if not hits:
                return f"🖥 {pc}: не нашла «{raw}», нечего закрывать."
            _pending[key] = {"action": "kill", "arg": subs, "ts": time.time()}
            names = ", ".join(nm for _, nm in hits[:8])
            return (f"🖥 {pc}: закрыть {len(hits)} процесс(ов) — {names}? "
                    "Ответь «да».")

    for kw in ("запусти ", "открой ", "старт ", "launch "):
        if low.startswith(kw):
            if not _control_on():
                return f"🖥 {pc}: " + _LOCKED
            arg = t[len(kw):].strip()
            _pending[key] = {"action": "launch", "arg": arg, "ts": time.time()}
            return f"🖥 {pc}: запустить «{arg}»? Ответь «да»."

    return (f"🖥 {pc}: не поняла команду. Напиши «команды», покажу что умею.")


# ---------------------- Telegram ----------------------
def _tg_loop(token, owner_ids, cfg):
    base = f"https://api.telegram.org/bot{token}"
    offset = 0
    while True:
        try:
            r = requests.get(base + "/getUpdates",
                             params={"offset": offset, "timeout": 25}, timeout=35)
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or u.get("edited_message")
                if not msg:
                    continue
                uid = (msg.get("from") or {}).get("id")
                chat = (msg.get("chat") or {}).get("id")
                text = msg.get("text", "")
                if not owner_ids:
                    # режим знакомства: называем id и ничего не выполняем
                    _tg_send(base, chat, _GREET.format(uid=uid))
                    continue
                if uid not in owner_ids:
                    _tg_send(base, chat, "Извини, слушаюсь только владельца.")
                    continue
                _tg_send(base, chat, _reply_for("telegram", uid, text, cfg))
        except Exception as e:
            log.debug("telegram loop: %s", e)
            time.sleep(3)


def _tg_send(base, chat_id, text):
    try:
        requests.get(base + "/sendMessage",
                     params={"chat_id": chat_id, "text": text}, timeout=15)
    except Exception:
        pass


# ---------------------- VK ----------------------
def _vk_call(token, method, **params):
    params.update(access_token=token, v="5.199")
    return requests.get("https://api.vk.com/method/" + method,
                        params=params, timeout=30).json()


def _vk_send(token, peer_id, text):
    try:
        _vk_call(token, "messages.send", peer_id=peer_id, message=text,
                 random_id=int(time.time() * 1000) % 2**31)
    except Exception:
        pass


def _vk_loop(token, group_id, owner_ids, cfg):
    while True:
        try:
            lp = _vk_call(token, "groups.getLongPollServer",
                          group_id=group_id)["response"]
            server, key, ts = lp["server"], lp["key"], lp["ts"]
        except Exception as e:
            log.debug("vk getLongPollServer: %s", e)
            time.sleep(5)
            continue
        while True:
            try:
                r = requests.get(server, params={
                    "act": "a_check", "key": key, "ts": ts, "wait": 25},
                    timeout=35).json()
                if r.get("failed"):
                    break  # ключ/ts протух — пересоздаём сервер
                ts = r.get("ts", ts)
                for ev in r.get("updates", []):
                    if ev.get("type") != "message_new":
                        continue
                    m = ev["object"]["message"]
                    uid, peer = m.get("from_id"), m.get("peer_id")
                    if uid not in owner_ids:
                        _vk_send(token, peer, "Слушаюсь только владельца.")
                        continue
                    _vk_send(token, peer,
                             _reply_for("vk", uid, m.get("text", ""), cfg))
            except Exception as e:
                log.debug("vk poll: %s", e)
                time.sleep(3)
                break


# ---------------------- запуск ----------------------
def start_all():
    """Поднимает включённые боты в фоновых потоках. Токенов нет — тихо выходит."""
    m = _effective_cfg()
    pc = m.get("pc_name", "этот ПК")
    owners = m.get("owner_ids", {}) or {}

    tg = m.get("telegram", {}) or {}
    if tg.get("enabled") and tg.get("token"):
        ids = set(owners.get("telegram", []))
        threading.Thread(target=_tg_loop, args=(tg["token"], ids, m),
                         daemon=True).start()
        if ids:
            log.info("Telegram-бот Сайки запущен для «%s»", pc)
        else:
            # это не отказ, а знакомство: команды не исполняются, бот
            # только называет собеседнику его id (см. _GREET)
            log.warning("Telegram: owner_ids.telegram пуст — поднимаю в "
                        "режиме знакомства. Напиши боту, он пришлёт твой "
                        "id; впиши его в secrets.json и перезапусти. "
                        "Команды до этого не выполняются ни для кого.")

    vk = m.get("vk", {}) or {}
    if vk.get("enabled") and vk.get("token") and vk.get("group_id"):
        ids = set(owners.get("vk", []))
        if not ids:
            log.warning("VK включён, но owner_ids.vk пуст — не запускаю")
        else:
            threading.Thread(target=_vk_loop,
                             args=(vk["token"], vk["group_id"], ids, m),
                             daemon=True).start()
            log.info("VK-бот Сайки запущен для «%s»", pc)
