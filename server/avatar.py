"""Управление VRM-аватаром (VMagicMirror и совместимые) из Сайки.

Два независимых канала, оба выключены по умолчанию (avatar.enabled=false),
включаются правкой config.json:

1. Жесты/эмоции — «Слово в движение» аватара через ГЛОБАЛЬНЫЕ горячие
   клавиши (как их видит сама VMagicMirror-программа: Ctrl+Alt+1..0). Шлём
   их тем же способом, что и server/hotkeys.py — сырой ctypes keybd_event,
   без внешних пакетов. Работает независимо от hotkeys.enabled (тот флаг
   про ДРУГУЮ систему — пользовательские голосовые/клавиатурные бинды,
   которые может заводить сама модель; здесь никакой LLM ничего не биндит,
   решение полностью в коде — детерминированно и безопасно).

2. VMCP (VMC Protocol) — сырой OSC по UDP, БЕЗ пакета python-osc (его
   нельзя доустановить в живой .venv удалённо, поэтому пишем сами: формат
   OSC-сообщения простой и целиком укладывается в struct+socket). Шлём
   /VMC/Ext/Blend/Val + /VMC/Ext/Blend/Apply для мгновенной, более быстрой
   и надёжной реакции лица, чем хоткей (не зависит от фокуса окна/раскладки
   клавиатуры), с авто-затуханием обратно в нейтраль через decay_s секунд.

Обе метки — эмоция пользователя (tone.py, УЖЕ детектится в run_dialog) и
простые приветствие/прощание — решаются кодом, без обращения к LLM: та же
философия, что и в tone.py («оболочка даёт ярлык, а не текст»).

Слоты «Слово в движение» — порядок, который пользователь сам заводит в
самой программе (вкладка «Слово в движение»); по умолчанию совпадает с
дефолтной раскладкой программы: 1=reset 2=joy 3=angry 4=sorrow 5=fun
6=wave 7=good 8=nodding 9=shaking 10=clap. Если пользователь у себя в
программе переставил порядок — поправить avatar.gestures.slot_names
в config.json под свой реальный порядок, коду это без разницы.

3. Голова в такт речи (VMC Bone/Pos «Head») — пока Sайка реально говорит
   (реальный уровень TTS-звука, тот же AUDIO_LEVEL, что main.py уже считает
   для /api/audio_level), голова аватара мягко покачивается синхронно с
   громкостью — вместо статичной «говорящей головы». Кости рук/тела НАРОЧНО
   не трогаем сырым VMC: в программе уже есть профессионально анимированные
   жесты (Слово в движение — wave/clap/nodding/shaking), а руками через
   Bone/Pos без полноценной IK/интерполяции получилось бы хуже, чем есть.
   Приём VMCP «Рука»/«Голова» в самой программе можно оставить включённым —
   мы просто не используем «Руку», это не мешает.
"""
import logging
import math
import re
import socket
import struct
import threading
import time

from server.config import CFG

log = logging.getLogger("saika.avatar")

_LAST_FIRE = {"ts": 0.0}
_VMC_LAST = {"ts": 0.0}
_LAST_TOOL_FIRE = {"ts": 0.0}

DEFAULT_SLOT_NAMES = ["reset", "joy", "angry", "sorrow", "fun",
                      "wave", "good", "nodding", "shaking", "clap"]
DEFAULT_WORD_HOTKEYS = ["ctrl+alt+1", "ctrl+alt+2", "ctrl+alt+3",
                        "ctrl+alt+4", "ctrl+alt+5", "ctrl+alt+6",
                        "ctrl+alt+7", "ctrl+alt+8", "ctrl+alt+9",
                        "ctrl+alt+0"]
DEFAULT_CAM_HOTKEYS = ["ctrl+shift+1", "ctrl+shift+2", "ctrl+shift+3"]
# тон собеседника (tone.py) -> какой слот отыграть; хамство/пошлость получают
# видимую, но не истеричную реакцию — Сайка не обижается, а слегка реагирует.
# «provoke» (проверка на прочность) -> «good»: спокойная уверенная реакция,
# ей не задели, а не разозлили — по характеру (persona.py: «спокойствие —
# базовый режим»).
DEFAULT_TONE_MAP = {"hostile": "angry", "vulgar": "shaking",
                    "flirt": "fun", "praise": "joy", "provoke": "good"}
DEFAULT_BLEND_MAP = {"joy": "Joy", "angry": "Angry", "sorrow": "Sorrow",
                     "fun": "Fun"}
# короткие описания слотов — для тела инструмента avatar_action (см.
# server/llm/tools.py), чтобы ЛЮБАЯ модель (даже без доступа к этому файлу)
# видела человеческим языком, что означает каждый жест
ACTION_DESC = {
    "joy": "радостная улыбка",
    "angry": "недовольство, лёгкая злость",
    "sorrow": "грусть, сочувствие",
    "fun": "игривость, озорной вид",
    "wave": "приветственный или прощальный взмах рукой",
    "good": "спокойное уверенное одобрение (кивок/жест «всё хорошо»)",
    "nodding": "кивок согласия",
    "shaking": "покачивание головой (несогласие, неодобрение)",
    "clap": "аплодисменты, восторг",
    "reset": "нейтральная поза",
}

# Простые текстовые сигналы (не через tone.py — тот про допустимое ПОВЕДЕНИЕ
# модели, а это чисто про то, что показать на лице/жестом) -> оставшиеся
# слоты «Слово в движение», чтобы весь набор реально использовался, а не
# простаивал: sorrow/nodding/clap. «reset» — не по тексту, см. on_startup().
_GREETING_RE = re.compile(
    r"\b(привет|здравств|добр(?:ый|ое)\s+(?:день|утро|вечер)|хай|hi|hello)\b",
    re.I)
_FAREWELL_RE = re.compile(
    r"\b(пока|до встречи|до завтра|прощай|спокойной ночи|bye|увидимся)\b",
    re.I)
_CLAP_RE = re.compile(
    r"\b(ура+|получилось|наконец.то|сдал(?:а)?(?:\s+экзамен)?|"
    r"выиграл(?:а)?|поздравь|устроилась?\s+на\s+работу|приняли\s+на\s+работу|"
    r"защитил(?:а)?(?:\s+диплом)?)\b", re.I)
_SORROW_RE = re.compile(
    r"\b(жаль|груст(?:ь|но|ит)|печал\w*|тяжело на душе|расстро\w*|умер(?:ла|ло)?|"
    r"заболел(?:а)?|не получилось|провалил(?:а)?|уволили|плохо себя чувствую)\b",
    re.I)
_AGREE_RE = re.compile(
    r"\b(соглас(?:на|ен|ны)|точно подмечено|ты\s+прав(?:а)?\b|"
    r"верно подмечено|именно так|в точку)\b", re.I)


# ---------------- горячие клавиши (сырой ctypes, без внешних пакетов) ------
# ВАЖНО (2026-07-23): изначально слали keybd_event (VK-код без scan-кода).
# Диагностика показала: код у Сайки отрабатывал БЕЗ единой ошибки (лог
# «жест «fun» -> ctrl+alt+5»), а физическое нажатие той же комбинации
# пользователем аватар отыгрывал нормально — значит хоткей в самой проге
# заведён и слушается, но именно синтетический keybd_event ею игнорировался.
# Классическая причина: движки на Unity (VMagicMirror — как раз Unity) часто
# читают клавиатуру через низкоуровневый Raw Input / опрос состояния по
# сканкоду, а не по голому VK — keybd_event(..., 0, ...) шлёт scan-код 0,
# такое событие многие такие обработчики просто не видят как «настоящее».
# Фикс — SendInput с ПРАВИЛЬНЫМ аппаратным scan-кодом (MapVirtualKeyW) и
# флагом KEYEVENTF_SCANCODE: эмулирует реальное железное нажатие гораздо
# точнее, чем keybd_event, и его подхватывают в том числе Raw Input/хуки,
# которые голый VK-инжект пропускали.
_VK = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10}

_INPUT_KEYBOARD = 1
_KEYEVENTF_SCANCODE = 0x0008
_KEYEVENTF_KEYUP = 0x0002
_MAPVK_VK_TO_VSC = 0


def _combo_to_vks(combo: str):
    vks = []
    for part in combo.lower().replace(" ", "").split("+"):
        if part in _VK:
            vks.append(_VK[part])
        elif len(part) == 1 and (part.isdigit() or part.isalpha()):
            vks.append(ord(part.upper()))
        else:
            raise ValueError(f"неизвестная клавиша в комбинации: {part!r}")
    return vks


def _build_send_input_types():
    """ctypes-структуры для SendInput — строятся лениво (нужны только на
    Windows; на прочих ОС эта ветка не вызывается вообще)."""
    import ctypes
    PUL = ctypes.POINTER(ctypes.c_ulong)

    class KeyBdInput(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort),
                   ("wScan", ctypes.c_ushort),
                   ("dwFlags", ctypes.c_ulong),
                   ("time", ctypes.c_ulong),
                   ("dwExtraInfo", PUL)]

    class Input_I(ctypes.Union):
        _fields_ = [("ki", KeyBdInput)]

    class Input(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("ii", Input_I)]

    return KeyBdInput, Input_I, Input


_SEND_INPUT_TYPES = {}


def _send_key_event(vk: int, key_up: bool):
    import ctypes
    if not _SEND_INPUT_TYPES:
        kb, ii, inp = _build_send_input_types()
        _SEND_INPUT_TYPES["KeyBdInput"] = kb
        _SEND_INPUT_TYPES["Input_I"] = ii
        _SEND_INPUT_TYPES["Input"] = inp
    KeyBdInput = _SEND_INPUT_TYPES["KeyBdInput"]
    Input_I = _SEND_INPUT_TYPES["Input_I"]
    Input = _SEND_INPUT_TYPES["Input"]

    user32 = ctypes.windll.user32
    scan = user32.MapVirtualKeyW(vk, _MAPVK_VK_TO_VSC)
    flags = _KEYEVENTF_SCANCODE | (_KEYEVENTF_KEYUP if key_up else 0)
    extra = ctypes.c_ulong(0)
    ii_ = Input_I()
    ii_.ki = KeyBdInput(vk, scan, flags, 0, ctypes.pointer(extra))
    x = Input(ctypes.c_ulong(_INPUT_KEYBOARD), ii_)
    user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))


def _press_combo(combo: str):
    vks = _combo_to_vks(combo)
    for vk in vks:
        _send_key_event(vk, key_up=False)
    time.sleep(0.06)   # держим чуть дольше физического нажатия — надёжнее
                       # ловится глобальными хоткеями сторонних программ
    for vk in reversed(vks):
        _send_key_event(vk, key_up=True)


def _fire_slot(slot: str):
    names = CFG.get("avatar.gestures.slot_names", DEFAULT_SLOT_NAMES)
    combos = CFG.get("avatar.gestures.word_to_motion_hotkeys",
                     DEFAULT_WORD_HOTKEYS)
    if slot not in names:
        return
    idx = names.index(slot)
    if idx >= len(combos):
        return
    try:
        _press_combo(combos[idx])
        log.info("жест «%s» -> %s", slot, combos[idx])
    except Exception as e:
        log.warning("не отправился жест «%s»: %s", slot, e)


def fire_camera_pose(n: int):
    """Поза камеры 1..3 (Ctrl+Shift+1..3) — переключение по контексту."""
    combos = CFG.get("avatar.gestures.camera_pose_hotkeys",
                     DEFAULT_CAM_HOTKEYS)
    if not (1 <= n <= len(combos)):
        return
    try:
        _press_combo(combos[n - 1])
        log.info("поза камеры -> %d", n)
    except Exception as e:
        log.warning("не переключилась поза камеры %d: %s", n, e)


# ---------------- VMCP: сырой OSC по UDP, без python-osc -------------------
_sock = None


def _osc_pad(b: bytes) -> bytes:
    return b + b"\x00" * ((4 - len(b) % 4) % 4)


def _osc_string(s: str) -> bytes:
    return _osc_pad(s.encode("utf-8") + b"\x00")


def _osc_message(address: str, *args) -> bytes:
    tags = ","
    body = b""
    for a in args:
        if isinstance(a, bool):
            tags += "i"; body += struct.pack(">i", int(a))
        elif isinstance(a, int):
            tags += "i"; body += struct.pack(">i", a)
        elif isinstance(a, float):
            tags += "f"; body += struct.pack(">f", a)
        elif isinstance(a, str):
            tags += "s"; body += _osc_string(a)
        else:
            raise TypeError(f"неподдержанный тип OSC-аргумента: {type(a)}")
    return _osc_string(address) + _osc_string(tags) + body


def _vmc_send(address: str, *args):
    global _sock
    host = CFG.get("avatar.vmcp.host", "127.0.0.1")
    port = int(CFG.get("avatar.vmcp.port", 39539))
    if _sock is None:
        _sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        _sock.sendto(_osc_message(address, *args), (host, port))
    except Exception as e:
        log.warning("VMCP: не отправилось %s%s -> %s:%d (%s)",
                   address, args, host, port, e)


def _vmc_blend(name: str, value: float):
    _vmc_send("/VMC/Ext/Blend/Val", name, float(value))


def _vmc_apply():
    _vmc_send("/VMC/Ext/Blend/Apply")


def vmc_expression(blend_name: str, value: float = 1.0, decay_s: float = 4.0):
    """Выставить блендшейп напрямую по VMC-протоколу и мягко вернуть в 0."""
    if not CFG.get("avatar.vmcp.enabled", False):
        return
    _vmc_blend(blend_name, value)
    _vmc_apply()
    if decay_s > 0:
        def _decay():
            time.sleep(decay_s)
            _vmc_blend(blend_name, 0.0)
            _vmc_apply()
        threading.Thread(target=_decay, daemon=True).start()


def _vmc_slot(slot: str):
    bmap = CFG.get("avatar.vmcp.blend_map", DEFAULT_BLEND_MAP) or {}
    name = bmap.get(slot)
    if not name:
        return
    vmc_expression(name, 1.0, float(CFG.get("avatar.vmcp.decay_s", 4.0)))


# ---------------- голова в такт речи (VMC Bone/Pos «Head») ------------------
# HumanBodyBones-имя "Head" — стандартное для VRM/VMC, одна кость, без рук/тела.
_TALK = {"level": 0.0, "ts": 0.0}
_TALK_THREAD = {"started": False}


def _euler_small_quat(pitch_deg: float, yaw_deg: float, roll_deg: float = 0.0):
    """Кватернион маленького поворота головы (град.) — porядок yaw*pitch*roll,
    для небольших углов порядок почти не заметен визуально."""
    def axis(ax, ay, az, deg):
        h = math.radians(deg) / 2.0
        s = math.sin(h)
        return (ax * s, ay * s, az * s, math.cos(h))

    def qmul(a, b):
        ax, ay, az, aw = a
        bx, by, bz, bw = b
        return (aw * bx + ax * bw + ay * bz - az * by,
               aw * by - ax * bz + ay * bw + az * bx,
               aw * bz + ax * by - ay * bx + az * bw,
               aw * bw - ax * bx - ay * by - az * bz)

    qy = axis(0, 1, 0, yaw_deg)
    qx = axis(1, 0, 0, pitch_deg)
    qz = axis(0, 0, 1, roll_deg)
    return qmul(qmul(qy, qx), qz)


def _vmc_bone(name: str, quat, pos=(0.0, 0.0, 0.0)):
    x, y, z, w = quat
    px, py, pz = pos
    _vmc_send("/VMC/Ext/Bone/Pos", name, px, py, pz, x, y, z, w)


def on_audio_chunk(level: float):
    """Дёргается из main.py:tts_worker на каждый чанк озвучки (тот же RMS,
    что уже идёт в AUDIO_LEVEL). Никогда не бросает исключений наружу."""
    try:
        if not CFG.get("avatar.enabled", False) \
                or not CFG.get("avatar.vmcp.enabled", False) \
                or not CFG.get("avatar.vmcp.head_bob", True):
            return
        _TALK["level"] = float(level)
        _TALK["ts"] = time.time()
        if not _TALK_THREAD["started"]:
            _TALK_THREAD["started"] = True
            threading.Thread(target=_talk_loop, daemon=True).start()
    except Exception as e:
        log.debug("on_audio_chunk: %s", e)


def _talk_loop():
    phase = 0.0
    was_talking = False
    while True:
        time.sleep(1.0 / 15.0)   # ~15 Гц — плавно, не спамит VMCP
        try:
            if not CFG.get("avatar.vmcp.enabled", False):
                continue
            talking = (time.time() - _TALK["ts"]) < 0.35
            if talking:
                max_deg = float(CFG.get("avatar.vmcp.head_bob_max_deg", 6.0))
                phase += 0.9
                amp = min(max_deg, 2.0 + _TALK["level"] * 10.0)
                pitch = amp * math.sin(phase)
                yaw = amp * 0.4 * math.sin(phase * 0.6 + 1.0)
                _vmc_bone("Head", _euler_small_quat(pitch, yaw))
                was_talking = True
            elif was_talking:
                _vmc_bone("Head", (0.0, 0.0, 0.0, 1.0))   # назад в нейтраль
                was_talking = False
        except Exception as e:
            log.debug("head-bob: %s", e)


# ---------------- точка входа из run_dialog ---------------------------------
def react(user_text: str, tone_cls: str | None = None):
    """Вызывается один раз на реплику пользователя (main.py:run_dialog),
    сразу после детекта тона — реагирует ДО того, как модель начала думать,
    поэтому жест/эмоция синхронны с началом ответа, а не запаздывают."""
    if not CFG.get("avatar.enabled", False):
        return
    if not CFG.get("avatar.gestures.enabled", True) \
            and not CFG.get("avatar.vmcp.enabled", False):
        return
    cooldown = float(CFG.get("avatar.gestures.cooldown_s", 8))
    now = time.time()
    if now - _LAST_FIRE["ts"] < cooldown:
        return

    text = user_text or ""
    # порядок важен: явные текстовые сигналы (приветствие/радость/грусть/
    # согласие) идут раньше общего тона — тон может быть neutral, а повод
    # для жеста уже есть
    if _GREETING_RE.search(text) or _FAREWELL_RE.search(text):
        slot = "wave"
    elif _SORROW_RE.search(text):
        # ПЕРЕД clap: у clap есть «получилось», а у sorrow — «не получилось»/
        # «не удалось» — при обратном порядке отрицание давало ложный clap
        slot = "sorrow"
    elif _CLAP_RE.search(text):
        slot = "clap"
    elif _AGREE_RE.search(text):
        slot = "nodding"
    else:
        tone_map = CFG.get("avatar.gestures.tone_map", DEFAULT_TONE_MAP) or {}
        slot = tone_map.get(tone_cls or "")

    if not slot:
        return
    _LAST_FIRE["ts"] = now
    if CFG.get("avatar.gestures.enabled", True):
        _fire_slot(slot)
    if CFG.get("avatar.vmcp.enabled", False):
        _vmc_slot(slot)


def fire_named(name: str) -> str:
    """Явный, ОСОЗНАННЫЙ вызов жеста/эмоции самой моделью через tool-call
    avatar_action (server/llm/tools.py) — в отличие от react() выше, тут не
    смотрим на тон/regex/общий кулдаун диалога: модель сама решила показать
    что-то по контексту разговора, и её решение не должно тонуть в пассивной
    логике. У инструмента свой отдельный короткий кулдаун — просто чтобы
    модель не задребезжала одним и тем же жестом дважды подряд в одном ответе."""
    if not CFG.get("avatar.enabled", False):
        return "аватар выключен в настройках — жест не отправлен"
    names = CFG.get("avatar.gestures.slot_names", DEFAULT_SLOT_NAMES)
    name = (name or "").strip().lower()
    if name not in names:
        return f"неизвестный жест «{name}», доступны: {', '.join(names)}"
    now = time.time()
    if now - _LAST_TOOL_FIRE["ts"] < 1.5:
        return "слишком часто — предыдущий жест ещё не отыгран, пропущено"
    _LAST_TOOL_FIRE["ts"] = now
    _LAST_FIRE["ts"] = now   # чтобы пассивная react() не задублировала следом
    fired = False
    if CFG.get("avatar.gestures.enabled", True):
        _fire_slot(name)
        fired = True
    if CFG.get("avatar.vmcp.enabled", False):
        _vmc_slot(name)
        fired = True
    if not fired:
        return "жест не отправлен — все каналы аватара выключены в настройках"
    return f"жест «{name}» отправлен аватару"


def on_startup():
    """Один раз при старте сервера Sайки — «привет» жестом (wave) и сброс
    позы (reset), чтобы аватар не заставал следующую сессию в случайном
    состоянии от предыдущей. Вызывается из main.py при запуске, без связи
    с диалогом — сюда user_text/tone_cls не нужны."""
    if not CFG.get("avatar.enabled", False) \
            or not CFG.get("avatar.gestures.enabled", True):
        return
    try:
        _fire_slot("reset")
        time.sleep(0.5)
        _fire_slot("wave")
        log.info("avatar: стартовое приветствие отправлено")
    except Exception as e:
        log.debug("avatar.on_startup: %s", e)
