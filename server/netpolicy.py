"""Политика сети: часть интернета на этом ПК ходит через обходчик DPI.

ЗАЧЕМ ЭТО ВООБЩЕ ЕСТЬ. Владелец: «я не понимаю почему сеть типа не
показывается, я на хаггинг захожу спокойно, впн у меня отключен».
Индикатор при этом честно писал «нет сети» — он звонил ровно на один
адрес (1.1.1.1), который у российских провайдеров режется постоянно.
Половина здешней сети такая: до одних хостов достучаться нельзя, до
других можно, и это НОРМАЛЬНОЕ состояние, а не авария.

Поверх этого у него стоит zapret (C:\\AI\\Cnox\\zapret-discord-youtube):
служба `zapret`, процесс `winws.exe`, драйвер WinDivert. Пока Сайка про
неё не знала, любой отвал YouTube/Discord она объясняла «нет интернета»
и предлагала чинить не то. Здесь — знание, из которого получается
осмысленный ответ: кто именно не отвечает, работает ли обходчик, и что
человеку предложить (перезапустить службу — одна команда, он это и так
делает руками через zapret-restart.bat).

Модуль НИЧЕГО не обходит сам и ничего не устанавливает: он смотрит
состояние того, что владелец поставил себе сам, и умеет попросить
Windows перезапустить уже установленную службу.
"""
import logging
import os
import subprocess

from server.config import CFG

log = logging.getLogger("saika.netpolicy")

# хосты, ради которых обходчик обычно и ставят — если не отвечают ОНИ, а
# остальное живо, диагноз почти наверняка «обходчик не работает»
_BEHIND = ("youtube.com", "discord.com", "huggingface.co", "github.com")

_NOWIN = os.name != "nt"


# УМОЛЧАНИЕ ПРЯМО В КОДЕ (2026-08-15). Папку владелец показал сам:
# C:\\AI\\Cnox\\zapret-discord-youtube. Класть такое ТОЛЬКО в config.json
# нельзя — конфиг это его хозяйство, а знание о том, как устроена сеть на
# этой машине, должно работать и на чистой установке. Config, если он
# есть, всё равно главнее: там можно указать другую папку или выключить.
_DEFAULT = {
    "enabled": True,
    "name": "zapret",
    "service": "zapret",
    "proc": "winws.exe",
    "restart": "zapret-restart.bat",
    "dirs": [r"C:\AI\Cnox\zapret-discord-youtube",
             r"C:\zapret-discord-youtube",
             r"C:\Program Files\zapret"],
}


def cfg() -> dict:
    d = dict(_DEFAULT)
    live = CFG.get("net.bypass", {}) or {}
    if isinstance(live, dict):
        d.update(live)
    if not d.get("dir"):
        for cand in d.get("dirs") or []:
            try:
                if os.path.isdir(cand):
                    d["dir"] = cand
                    break
            except Exception:
                pass
    return d


def _run(args, timeout=6) -> str:
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout,
                           text=True, errors="replace",
                           creationflags=getattr(subprocess,
                                                 "CREATE_NO_WINDOW", 0))
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        log.debug("%s: %s", args, e)
        return ""


def state() -> dict:
    """Что сейчас с обходчиком. Ничего не запускает и не чинит."""
    c = cfg()
    out = {"known": bool(c.get("enabled", True) and c.get("dir")),
           "name": c.get("name", "zapret"),
           "dir": c.get("dir", ""),
           "service": "unknown", "proc": False}
    if not out["known"] or _NOWIN:
        return out
    svc = c.get("service", "zapret")
    txt = _run(["sc", "query", svc]).upper()
    if "RUNNING" in txt:
        out["service"] = "running"
    elif "STOPPED" in txt or "PAUSED" in txt:
        out["service"] = "stopped"
    elif "1060" in txt or "NOT EXIST" in txt or "НЕ СУЩЕСТВ" in txt.upper():
        out["service"] = "absent"
    proc = c.get("proc", "winws.exe")
    tl = _run(["tasklist", "/FI", f"IMAGENAME eq {proc}"])
    out["proc"] = proc.lower() in tl.lower()
    return out


def explain(probes: dict) -> dict:
    """Человеческий диагноз по результатам пробников.

    probes: {хост: пинг_мс или None}. Возвращает {"human", "action"} либо
    пустой словарь, если объяснять нечего (всё живо).
    """
    if not isinstance(probes, dict) or not probes:
        return {}
    dead = [h for h, v in probes.items() if v is None]
    alive = [h for h, v in probes.items() if v is not None]
    if not dead:
        return {}
    if not alive:
        return {"human": "Не отвечает никто: " + ", ".join(dead)
                         + " — похоже, интернета нет совсем.",
                "action": "проверь кабель/Wi-Fi и роутер"}
    st = state()
    behind = [h for h in dead if any(b in h for b in _BEHIND)]
    base = ("Интернет есть (отвечают: " + ", ".join(alive)
            + "), не отвечают: " + ", ".join(dead) + ".")
    if behind and st.get("known"):
        if st.get("service") == "running" or st.get("proc"):
            return {"human": base + " Обходчик «%s» работает, но эти хосты "
                             "всё равно молчат — возможно, провайдер сменил "
                             "фильтр." % st.get("name"),
                    "action": "перезапусти обходчик (я умею: «перезапусти "
                              "запрет») или попробуй другую его стратегию"}
        return {"human": base + " Обходчик «%s» не запущен — как раз эти "
                         "адреса без него обычно и не открываются."
                         % st.get("name"),
                "action": "запустить обходчик — скажи «включи запрет»"}
    return {"human": base + " Это обычное дело: часть адресов у российских "
                     "провайдеров закрыта, и на диагноз «нет сети» это не "
                     "тянет.", "action": ""}


def _bat(key: str):
    from server.config import resolve
    c = cfg()
    d = c.get("dir") or ""
    name = c.get(key) or ""
    if not d or not name:
        return None
    try:
        from pathlib import Path
        p = Path(d) / name
        return p if p.exists() else None
    except Exception:
        return None


def restart() -> str:
    """Перезапустить службу обходчика. Он сам просит права администратора
    (в zapret-restart.bat это уже вшито) — Windows покажет своё окно."""
    if _NOWIN:
        return "Это только для Windows."
    c = cfg()
    if not c.get("enabled", True):
        return "Обходчик выключен в настройках (net.bypass.enabled)."
    bat = _bat("restart")
    if bat is None:
        # своими руками, без .bat: тот же net stop/start
        svc = c.get("service", "zapret")
        _run(["net", "stop", svc], timeout=20)
        out = _run(["net", "start", svc], timeout=30)
        ok = "успешно" in out.lower() or "started" in out.lower()
        return ("Служба «%s» перезапущена." % svc if ok else
                "Не смогла перезапустить службу «%s» — нужны права "
                "администратора. %s" % (svc, out.strip()[:200]))
    try:
        subprocess.Popen(["cmd", "/c", "start", "", str(bat)],
                         cwd=str(bat.parent), shell=False)
        return ("Запустила перезапуск обходчика (%s). Windows спросит права "
                "администратора — подтверди." % bat.name)
    except Exception as e:
        return "Не смогла запустить %s: %s" % (bat.name, e)


def start() -> str:
    """Поднять службу, если она стоит."""
    if _NOWIN:
        return "Это только для Windows."
    st = state()
    if st.get("service") == "running":
        return "Обходчик «%s» уже работает." % st.get("name")
    if st.get("service") == "absent":
        return ("Служба «%s» не установлена. Ставится она из своей папки "
                "(service.bat), и делать это надо руками — я не буду "
                "устанавливать системные службы без тебя." % st.get("name"))
    return restart()


def status_text() -> str:
    """Строка для ответа голосом."""
    st = state()
    if not st.get("known"):
        return "Обходчик сети у меня не настроен."
    m = {"running": "работает", "stopped": "остановлен",
         "absent": "не установлен", "unknown": "непонятно в каком состоянии"}
    return "Обходчик «%s» %s%s." % (
        st.get("name"), m.get(st.get("service"), "?"),
        ", процесс на месте" if st.get("proc") else "")
