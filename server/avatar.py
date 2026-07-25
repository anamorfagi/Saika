"""Жесты и эмоции VRM-аватара Сайки.

Единственный канал — СВОЙ рендер (ui/avatar.html): событие по websocket,
браузер отыгрывает жест сам. Прямо, без задержек и без посредников.

История (2026-07-25): раньше тут жили три канала в ЧУЖИЕ программы-аватары
(VMagicMirror/ВВА/Warudo) — глобальные хоткеи через SendInput, MIDI через
loopMIDI и мимика по VMC-протоколу (сырой OSC/UDP). Всё удалено вместе с
самими программами: у Сайки собственный рендер, а переезд в UE5 будет
цепляться совсем иначе. Понадобится — код есть в истории git.

Решение «какой жест показать» принимает КОД, а не LLM: метка тона (tone.py,
уже посчитана в run_dialog) плюс простые текстовые сигналы (приветствие,
радость, грусть, согласие). Та же философия, что в tone.py — оболочка даёт
ярлык, а не текст. Модель может позвать жест и сама: инструмент
avatar_action или маркер [жест:имя] в ответе (см. fire_named).
"""
import logging
import re
import threading
import time

from server.config import CFG

log = logging.getLogger("saika.avatar")

_re_anim = re.compile(r"^[a-z0-9_\-]{2,32}$")   # имена анимаций из библиотеки
_LAST_FIRE = {"ts": 0.0}
_LAST_TOOL_FIRE = {"ts": 0.0}

DEFAULT_SLOT_NAMES = ["reset", "joy", "angry", "sorrow", "fun",
                      "wave", "good", "nodding", "shaking", "clap"]
DEFAULT_TONE_MAP = {"hostile": "angry", "vulgar": "shaking",
                    "flirt": "fun", "praise": "joy", "provoke": "good"}
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
    "idle1": "лёгкая живая анимация ожидания (переминание)",
    "idle2": "другая анимация ожидания (потянуться/оглядеться)",
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


def _emit_web(slot: str):
    """Событие в веб-аватар (ui/avatar.html, 2026-07-25): собственный
    three-vrm рендер Сайки слушает /ws и отыгрывает жест сам — прямой канал
    без MIDI и эмуляции ввода. Шлём ВСЕГДА (дёшево), даже если открытых
    вкладок аватара нет."""
    try:
        from server.main import broadcast_event
        broadcast_event({"type": "avatar_gesture", "gesture": slot})
    except Exception:
        pass


def _fire_slot(slot: str):
    """Жест в свой рендер. Отдельная функция (а не прямой вызов _emit_web) —
    точка, где раньше ветвились каналы, и куда удобно добавить новый."""
    _emit_web(slot)


# ---------------- точка входа из run_dialog ---------------------------------
def react(user_text: str, tone_cls: str | None = None):
    """Вызывается один раз на реплику пользователя (main.py:run_dialog),
    сразу после детекта тона — реагирует ДО того, как модель начала думать,
    поэтому жест/эмоция синхронны с началом ответа, а не запаздывают."""
    if not CFG.get("avatar.enabled", False):
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
    if not CFG.get("avatar.gestures.enabled", True):
        return
    _LAST_FIRE["ts"] = now
    _fire_slot(slot)


# русские/вольные имена жестов -> слоты: маленькие модели пишут маркеры
# как умеют ([жест:радость], [жест:похлопай]) — принимаем и это
_NAME_ALIAS = {
    "радость": "joy", "улыбка": "joy", "улыбнись": "joy", "счастье": "joy",
    "злость": "angry", "злюсь": "angry", "гнев": "angry",
    "грусть": "sorrow", "печаль": "sorrow", "сочувствие": "sorrow",
    "весело": "fun", "игриво": "fun", "озорство": "fun",
    "привет": "wave", "пока": "wave", "махать": "wave", "помаши": "wave",
    "одобрение": "good", "хорошо": "good", "класс": "good",
    "кивок": "nodding", "согласие": "nodding", "да": "nodding",
    "несогласие": "shaking", "нет": "shaking",
    "аплодисменты": "clap", "похлопай": "clap", "браво": "clap",
    "нейтрально": "reset", "сброс": "reset",
    "ожидание": "idle1", "потянуться": "idle2",
    # стрим-набор (веб-аватар; во внешней программе сработают, только если
    # заведёшь одноимённые слоты) — 2026-07-25
    "вопрос": "ask", "указать": "point", "укажи": "point", "вот": "point",
    "танец": "dance", "танцуй": "dance", "станцуй": "dance",
    "смущение": "shy", "смущаюсь": "shy", "стесняюсь": "shy",
    "кринж": "cringe", "ярость": "rage", "бешенство": "rage",
    "милота": "cute", "мило": "cute",
    "усталость": "tired", "устала": "tired",
    # официальный VRMA-пак VRoid (models/avatar/anims, 2026-07-25):
    # showcase/greet/peace/shoot/spin/pose/squat — файлы .vrma
    "покажись": "showcase", "покрутись": "spin", "кружись": "spin",
    "приветствие": "greet", "поздоровайся": "greet",
    "пис": "peace", "виктори": "peace", "мир": "peace",
    "выстрел": "shoot", "пиф-паф": "shoot",
    "поза": "pose", "позируй": "pose",
    "присед": "squat", "приседание": "squat", "присядь": "squat",
}


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
    name = _NAME_ALIAS.get(name, name)
    if name not in names:
        # не слот, но может быть анимацией из библиотеки веб-аватара
        # (models/avatar/anims/<name>.vrma) — шлём событие, веб сам решит
        if _re_anim.match(name):
            _emit_web(name)
            return (f"жест «{name}» отправлен веб-аватару (сработает, если "
                    f"в библиотеке анимаций есть {name}.vrma)")
        return f"неизвестный жест «{name}», доступны: {', '.join(names)}"
    now = time.time()
    if now - _LAST_TOOL_FIRE["ts"] < 1.5:
        return "слишком часто — предыдущий жест ещё не отыгран, пропущено"
    _LAST_TOOL_FIRE["ts"] = now
    _LAST_FIRE["ts"] = now   # чтобы пассивная react() не задублировала следом
    if not CFG.get("avatar.gestures.enabled", True):
        return "жесты аватара выключены в настройках"
    _fire_slot(name)
    return f"жест «{name}» отправлен аватару"


# ---------------- фиджеты: живость в простое (2026-07-25) -------------------
# Слоты 11-12 («idle2», «idle1» в программе) — анимации ожидания. Чтобы
# аватар не стоял столбом между репликами, фоновый цикл изредка (случайный
# интервал idle.min_s..max_s) отыгрывает одну из них — но только если
# недавно не было «настоящего» жеста (не перебиваем реакцию на диалог).
_IDLE_THREAD = {"started": False}


def _idle_loop():
    import random
    while True:
        lo = float(CFG.get("avatar.gestures.idle.min_s", 120))
        hi = float(CFG.get("avatar.gestures.idle.max_s", 300))
        time.sleep(random.uniform(lo, max(lo, hi)))
        try:
            if not CFG.get("avatar.enabled", False) \
                    or not CFG.get("avatar.gestures.enabled", True) \
                    or not CFG.get("avatar.gestures.idle.enabled", True):
                continue
            # свежий «настоящий» жест — пропускаем такт, живость не нужна
            if time.time() - _LAST_FIRE["ts"] < 30:
                continue
            slots = CFG.get("avatar.gestures.idle.slots", ["idle1", "idle2"])
            names = CFG.get("avatar.gestures.slot_names", DEFAULT_SLOT_NAMES)
            slots = [s for s in slots if s in names]
            if slots:
                _fire_slot(random.choice(slots))
        except Exception as e:
            log.debug("idle-fidget: %s", e)


_ASK_CUE = {"ts": 0.0}


def question_cue():
    """Реплика Сайки заканчивается «?» — наклон головы (жест ask) в
    веб-аватаре (2026-07-25, co-speech: вопрос = наклон, как в ВВА).
    Свой кулдаун, чтобы серия вопросов не превращалась в тик."""
    now = time.time()
    if now - _ASK_CUE["ts"] < 8:
        return
    _ASK_CUE["ts"] = now
    _emit_web("ask")


def list_outfits() -> list:
    """Доступные наряды: «default» (базовая модель avatar.web.model) плюс
    все *.vrm из models/avatar/outfits (см. main.py:_outfits_dir)."""
    try:
        from server.main import _outfits_dir
        d = _outfits_dir()
        names = sorted(p.stem for p in d.glob("*.vrm")) if d.exists() else []
    except Exception:
        names = []
    return ["default"] + names


def change_outfit(name: str) -> str:
    """Сменить наряд аватара (2026-07-25): полная подмена VRM-модели в
    браузере (не toggle одежды внутри одного файла — обычный экспорт из
    VRoid Studio так не умеет). Каждый наряд — отдельный .vrm-файл в
    models/avatar/outfits/<name>.vrm, «default» — исходная модель."""
    name = (name or "").strip().lower()
    avail = list_outfits()
    if name not in avail:
        return (f"такого наряда нет ({name}) — доступны: {', '.join(avail)}. "
                "Новый наряд — экспортируй из VRoid Studio отдельным .vrm "
                "и положи в models/avatar/outfits/")
    try:
        from server.main import broadcast_event
        broadcast_event({"type": "avatar_outfit", "outfit": name})
    except Exception as e:
        return f"не получилось переключить: {e}"
    return f"переоделась: {name}"


def start_idle_fidgets():
    if not _IDLE_THREAD["started"]:
        _IDLE_THREAD["started"] = True
        threading.Thread(target=_idle_loop, daemon=True).start()
        log.info("avatar: фиджеты в простое запущены")


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
    start_idle_fidgets()
