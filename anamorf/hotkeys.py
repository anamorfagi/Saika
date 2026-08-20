"""Голосовые и клавиатурные хоткеи — мгновенные действия Сайки.

Модель через инструменты (bind_create/list/delete) сама заводит бинды по
просьбе в диалоге: «забинди на слово капуста открытие ютуба», «повесь на
F8 закрытие окна». Дальше:
- голосовой триггер (type=voice): слово/фраза перехватывается ДО LLM в
  main.py -> действие выполняется мгновенно, без думанья и токенов;
- клавиатурный (type=key): глобальный хоткей (нужен пакет `keyboard`;
  если не стоит — бинд сохранится, но сработает только когда поставишь).

Действия — простые системные операции (Windows), без внешних либ для звука
и окон (чистый ctypes). Бинды хранятся в data/hotkeys.json.
"""
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

from anamorf.config import CFG, ROOT, DATA_ROOT, resolve
from anamorf import runtime_env

log = logging.getLogger("saika.hotkeys")
PATH = DATA_ROOT / "data" / "hotkeys.json"
_lock = threading.Lock()
_kb_registered = {}   # trigger -> hook (для клавиатурных)


# ---------------- действия ----------------
def _key(vk):
    """Нажать виртуальную клавишу Windows (медиа/громкость)."""
    import ctypes
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


def _hotkey(*vks):
    """Комбинация (напр. Alt+F4)."""
    import ctypes
    for vk in vks:
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


def _open(target):
    """URL, путь или приложение."""
    t = str(target).strip()
    if t.startswith("http") or "." in t.split("/")[0] and " " not in t[:40]:
        if not t.startswith("http"):
            t = "https://" + t
        os.startfile(t)  # noqa: S606
    else:
        try:
            os.startfile(t)  # noqa: S606
        except Exception:
            subprocess.Popen(t, shell=True)


# vk-коды
VK = {"vol_up": 0xAF, "vol_down": 0xAE, "vol_mute": 0xAD,
      "media_play": 0xB3, "media_next": 0xB0, "media_prev": 0xB1,
      "alt": 0x12, "f4": 0x73, "lwin": 0x5B, "d": 0x44, "m": 0x4D,
      "tab": 0x09, "ctrl": 0x11, "w": 0x57, "t": 0x54}

ACTIONS = {
    "volume_up":   lambda p=None: [_key(VK["vol_up"]) for _ in range(3)],
    "volume_down": lambda p=None: [_key(VK["vol_down"]) for _ in range(3)],
    "mute":        lambda p=None: _key(VK["vol_mute"]),
    "media_play_pause": lambda p=None: _key(VK["media_play"]),
    "media_next":  lambda p=None: _key(VK["media_next"]),
    "media_prev":  lambda p=None: _key(VK["media_prev"]),
    "close_window": lambda p=None: _hotkey(VK["alt"], VK["f4"]),
    "minimize_all": lambda p=None: _hotkey(VK["lwin"], VK["d"]),
    "new_tab":     lambda p=None: _hotkey(VK["ctrl"], VK["t"]),
    "close_tab":   lambda p=None: _hotkey(VK["ctrl"], VK["w"]),
    "open":        lambda p: _open(p),          # open + params=url/app
    "open_browser": lambda p=None: _open("https://www.google.com"),
}

# человекочитаемые описания для модели
ACTION_DESC = {
    "volume_up": "прибавить громкость", "volume_down": "убавить громкость",
    "mute": "выкл/вкл звук", "media_play_pause": "плей/пауза",
    "media_next": "след. трек", "media_prev": "пред. трек",
    "close_window": "закрыть активное окно", "minimize_all": "свернуть всё",
    "new_tab": "новая вкладка", "close_tab": "закрыть вкладку",
    "open": "открыть URL/приложение (нужен params)",
    "open_browser": "открыть браузер",
}


# ---------------- хранилище ----------------
def _load() -> list:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(binds: list):
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(binds, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def list_binds() -> list:
    return _load()


def add_bind(trigger: str, action: str, params: str = "",
             kind: str = "voice") -> str:
    trigger = (trigger or "").strip().lower()
    if not trigger:
        return "нужно слово-триггер или клавиша"
    if action not in ACTIONS:
        return (f"нет такого действия «{action}». Доступные: "
                + ", ".join(ACTIONS))
    with _lock:
        binds = [b for b in _load()
                 if not (b["trigger"] == trigger and b["kind"] == kind)]
        binds.append({"trigger": trigger, "action": action,
                      "params": params, "kind": kind})
        _save(binds)
    if kind == "key":
        _register_key(trigger, action, params)
    what = ACTION_DESC.get(action, action)
    how = f"по слову «{trigger}»" if kind == "voice" else f"на клавишу {trigger}"
    return f"готово: {how} -> {what}"


def del_bind(trigger: str) -> str:
    trigger = (trigger or "").strip().lower()
    with _lock:
        binds = _load()
        new = [b for b in binds if b["trigger"] != trigger]
        _save(new)
    _unregister_key(trigger)
    return (f"убрала бинд «{trigger}»" if len(new) < len(binds)
            else f"бинда «{trigger}» не было")


def fire(action: str, params: str = "") -> bool:
    fn = ACTIONS.get(action)
    if not fn:
        return False
    try:
        fn(params) if action == "open" else fn()
        return True
    except Exception as e:
        log.warning("хоткей %s не сработал: %s", action, e)
        return False


# ---------------- голосовой матчинг (до LLM) ----------------
def match_voice(text: str):
    """Фраза содержит слово-триггер голосового бинда? -> (bind) или None."""
    low = " " + (text or "").lower().strip(" .,!?…") + " "
    for b in _load():
        if b.get("kind") != "voice":
            continue
        if (" " + b["trigger"] + " ") in low or low.strip() == b["trigger"]:
            return b
    return None


# ---------------- клавиатурные (опционально) ----------------
_kb_install_tried = {"done": False}


def _ensure_keyboard():
    """Пакет keyboard нужен для клавиатурных хоткеев. Нет — ставим сами
    в фоне (один раз), чтобы на новых машинах не вводить руками."""
    try:
        import keyboard  # noqa: F401
        return True
    except ImportError:
        pass
    if _kb_install_tried["done"]:
        return False
    _kb_install_tried["done"] = True
    try:
        log.info("Ставлю пакет keyboard для клавиатурных хоткеев…")
        ok, why = runtime_env.ensure("hotkeys", ["keyboard"])
        if not ok:
            raise RuntimeError(why)
        import importlib
        importlib.invalidate_caches()
        import keyboard  # noqa: F401
        return True
    except Exception as e:
        log.info("keyboard не установился (%s) — клавиатурные хоткеи "
                 "недоступны, голосовые работают", e)
        return False


def _register_key(trigger, action, params):
    if not _ensure_keyboard():
        log.info("клавиатурный бинд %s сохранён, заработает после "
                 "установки keyboard", trigger)
        return
    try:
        import keyboard
        if trigger in _kb_registered:
            keyboard.remove_hotkey(_kb_registered[trigger])
        _kb_registered[trigger] = keyboard.add_hotkey(
            trigger, lambda a=action, p=params: fire(a, p))
        log.info("клавиатурный хоткей %s -> %s зарегистрирован", trigger, action)
    except Exception as e:
        log.warning("не зарегистрировать хоткей %s: %s", trigger, e)


def _unregister_key(trigger):
    try:
        import keyboard
        if trigger in _kb_registered:
            keyboard.remove_hotkey(_kb_registered.pop(trigger))
    except Exception:
        pass


def register_all_keys():
    """При старте — поднять сохранённые клавиатурные бинды."""
    for b in _load():
        if b.get("kind") == "key":
            _register_key(b["trigger"], b["action"], b.get("params", ""))
