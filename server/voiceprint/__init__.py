"""ОТПЕЧАТОК ГОЛОСА — модуль распознавания говорящего + живая визуализация.

2026-07-28. Расширение блока слуха: раньше Сайка знала ЧТО сказано, теперь
знает и КТО сказал. Плюс показывает это человеку — точкой в пространстве
голосов, которая едет за тем, как ты говоришь.

ПОЧЕМУ ОТДЕЛЬНЫЙ ПОТОК, А НЕ В КОНВЕЙЕР СЛУХА. Задержка ответа выстрадана
(LATENCY.md: 6.9с -> 0.6с), и вешать на путь STT ещё одну модель — прямой
способ всё вернуть. Поэтому feed() из вебсокета только КЛАДЁТ чанк в
очередь и мгновенно возвращается; считает отдельный рабочий поток, а если
он не успевает — очередь переполняется и чанки ТЕРЯЮТСЯ. Так и задумано:
пропущенный кадр картинки не стоит ни одной миллисекунды слуха.

ОКНО, А НЕ ФРАЗА. Эмбеддинг считается по скользящему окну ~1.2с и обновляется
раз в ~320мс — точка едет ПОКА ты говоришь, а не появляется через секунду
после того, как замолчал. Ждать конца фразы было бы дешевле, но мертво.

ФИЛОСОФИЯ (PHILOSOPHY.md). Модуль не сочиняет за Сайку реплик. Он отдаёт
ФАКТ «сейчас говорит владелец / незнакомый голос» — что с этим делать,
решает она сама.
"""
import logging
import queue
import threading
import time

import numpy as np

from server.config import CFG
from server.voiceprint.encoder import Encoder, speechiness, mel_profile
from server.voiceprint.projector import Projector
from server.voiceprint.registry import Registry
from server.voiceprint import naming

log = logging.getLogger("saika.voiceprint")

SR = 16000
QUEUE_MAX = 40             # ~4с звука; переполнилась — роняем старое молча
REFIT_EVERY = 120          # новых точек между переобучениями проекции
SAVE_EVERY = 30.0          # сек между записями состояния на диск
SELF_COLOR = "#9184d9"     # её собственный голос — цветом интерфейса Сайки


class _State:
    def __init__(self):
        self.q: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
        self.thread: threading.Thread | None = None
        self.stop = threading.Event()
        self.sink = None                 # callable(dict) -> разослать в UI
        self.echo_guard = None           # callable() -> True, если это её эхо
        self.enc = Encoder()
        self.proj = Projector()
        self.reg = Registry()
        self.enroll_name = ""
        self.enroll_buf: list = []
        self.enroll_need = 24
        self.last_event: dict = {}
        self.new_points = 0
        self.refitting = False
        self.last_save = 0.0
        self.heard_s = 0.0               # сколько речи прошло через модуль
        # ЕЁ СОБСТВЕННЫЙ ГОЛОС (2026-07-28). Второй, независимый вход: сюда
        # льётся то, что синтезирует TTS, ещё ДО колонок. Свой поток и своя
        # очередь, потому что тут не нужен ни VAD (это заведомо речь), ни
        # защита от эха (это и есть источник эха).
        self.selfq: queue.Queue = queue.Queue(maxsize=60)
        self.self_thread: threading.Thread | None = None
        self.self_buf: list = []         # копится на автоматический эталон
        self.self_on = False             # звучит ли прямо сейчас
        self.self_pts = 0                # счётчик для прореживания облака
        self.noise_seen = 0              # сколько кусков отсеяно как «не голос»
        self.last_noise: dict = {}
        # АВТОЗНАКОМСТВО: незнакомый, но устойчивый голос сам становится
        # «Голос N». Без этого имя не к чему привязывать — догадка «его зовут
        # Аня» должна лечь на конкретную сигнатуру, а не в воздух.
        self.unk: list = []
        self.unk_n = 0
        self.who_ts = 0.0                # когда последний раз кого-то узнала
        self.who_last = ""
        self.addr: list = []             # имена, сказанные В АДРЕС собеседника


S = _State()


# --------------------------------------------------------------- публичное
def start(sink=None, echo_guard=None):
    """Поднять рабочий поток. sink — как разослать событие во все вкладки."""
    S.sink = sink
    S.echo_guard = echo_guard
    if S.thread and S.thread.is_alive():
        return
    S.stop.clear()
    S.thread = threading.Thread(target=_worker, name="voiceprint", daemon=True)
    S.thread.start()
    S.self_thread = threading.Thread(target=_self_worker, name="voiceprint-self",
                                     daemon=True)
    S.self_thread.start()


def stop():
    S.stop.set()
    S.reg.save()


def enabled():
    return bool(CFG.get("voiceprint.enabled", True))


def set_enabled(on: bool):
    CFG.set("voiceprint.enabled", bool(on))
    if not on:
        _emit({"type": "voiceprint", "state": "off"})
    return enabled()


def feed(pcm16: np.ndarray):
    """Зовётся из вебсокета на каждый чанк. ОБЯЗАН быть мгновенным."""
    if not enabled() or S.thread is None:
        return
    try:
        S.q.put_nowait(pcm16)
    except queue.Full:
        try:                     # роняем самый старый — свежесть важнее полноты
            S.q.get_nowait()
            S.q.put_nowait(pcm16)
        except Exception:
            pass


def self_name():
    """Как зовут её саму. Берём из общей настройки — переименовали Сайку,
    и её метка в пространстве голосов переименовалась вместе с ней."""
    return str(CFG.get("assistant_name", "Сайка")).strip() or "Сайка"


def listen_self():
    return bool(CFG.get("voiceprint.listen_self", True))


def set_listen_self(on: bool):
    CFG.set("voiceprint.listen_self", bool(on))
    return listen_self()


def feed_self(pcm_f32, sr: int):
    """Кусок СИНТЕЗИРОВАННОЙ речи (float32, частота движка TTS).

    Зовётся из конвейера озвучки. Как и feed(), обязан быть мгновенным:
    озвучка — самая заметная часть задержки, и модуль-зеркало не имеет права
    её задерживать даже на миллисекунду."""
    if not enabled() or not listen_self() or S.self_thread is None:
        return
    try:
        S.selfq.put_nowait((np.asarray(pcm_f32, dtype=np.float32), int(sr)))
    except queue.Full:
        try:
            S.selfq.get_nowait()
            S.selfq.put_nowait((np.asarray(pcm_f32, dtype=np.float32), int(sr)))
        except Exception:
            pass


def who_now(max_age=2.5):
    """Кто говорит прямо сейчас -> (имя, уверенность). Нужен конвейеру речи:
    распознанную фразу помечаем говорящим, как только тембр узнаётся
    устойчиво. До этого метки нет — врать про автора реплики нельзя."""
    if not S.who_last or time.monotonic() - S.who_ts > max_age:
        return "", 0.0
    ev = S.last_event or {}
    return S.who_last, float(ev.get("conf", 0.0))


def room(window_s: float = 180.0):
    """КТО СЕЙЧАС В КОМНАТЕ (2026-07-29, замысел владельца).

    Отвечает на вопрос «я тут один или нас несколько» — тот самый, от
    которого зависит, как раскладывать чат: разговор с ней в одну колонку
    или беседа нескольких людей облачками. Считаем по факту: какие голоса
    подавали признаки жизни за последние N минут, с их цветами.

    Она сама в счёт НЕ идёт: её собственный голос звучит из колонок и в
    «сколько людей рядом» ему делать нечего."""
    now = time.time()
    me = self_name()
    who = []
    for name, st in S.reg.stat.items():
        if name == me or name not in S.reg.speakers:
            continue
        last = float(st.get("last", 0) or 0)
        if now - last > window_s:
            continue
        v = S.reg.speakers[name]
        who.append({"name": name, "color": v.get("color", ""),
                    "owner": bool(v.get("owner")),
                    "ago": round(now - last, 1),
                    "heard": int(st.get("n", 0))})
    who.sort(key=lambda x: x["ago"])
    return {"people": who, "n": len(who), "crowd": len(who) >= 2}


def prosody():
    """Как звучал последний узнанный кусок: тон, энергия и рабочий диапазон
    говорящего. Нужен стенограмме для пометок настроения («тихо», «на
    подъёме») — считается из уже готового события, ничего не стоит."""
    ev = S.last_event or {}
    st = S.reg.stat.get(S.who_last or "", {})
    return {"pitch": float(ev.get("pitch", 0) or 0),
            "energy": float(ev.get("energy", 0) or 0),
            "plo": float(st.get("plo", 0) or 0),
            "phi": float(st.get("phi", 0) or 0)}


def note_text(text: str, who: str = ""):
    """Скормить распознанную фразу: вдруг в ней прозвучало имя.

    Кто сказал — берём из свежего узнавания, если не передали явно. Имя,
    сказанное В АДРЕС собеседника, кладём в ожидание: его получит следующий
    ДРУГОЙ голос, который заговорит в ближайшие секунды."""
    if not CFG.get("voiceprint.learn_names", True):
        return []
    said = who or who_now()[0]
    out = []
    for name, kind, w in naming.guess(text):
        if kind == "self" and said:
            out.append(_apply_name(said, name, w))
        elif kind == "address":
            S.addr.append((name, time.monotonic(), said, w))
            del S.addr[:-8]
    return [x for x in out if x]


def _apply_name(speaker: str, guessed: str, w: float):
    """Записать догадку и, если она вызрела, переименовать голос."""
    if speaker not in S.reg.speakers or guessed == speaker:
        return ""
    new = S.reg.note_hyp(speaker, guessed, w)
    cand, conf = S.reg.name_guess(speaker)
    _emit({"type": "voiceprint_name", "who": speaker, "guess": cand,
           "conf": conf})
    if new:
        r = S.reg.rename(speaker, new, pin=False)
        if r.get("ok"):
            S.reg.save()
            log.info("Отпечаток голоса: «%s» теперь зовут «%s» (набрала вес)",
                     speaker, new)
            _emit({"type": "voiceprint_renamed", "old": speaker, "new": new})
            return new
    return ""


def rename(old: str, new: str, pin: bool = True):
    r = S.reg.rename(old, new, pin=pin)
    if r.get("ok"):
        S.reg.save()
        _emit({"type": "voiceprint_renamed", "old": old, "new": r["name"]})
    return {**r, **status()}


def set_color(name: str, color: str):
    r = S.reg.set_color(name, color)
    if r.get("ok"):
        S.reg.save()
        _emit({"type": "voiceprint_renamed", "old": name, "new": name})
    return {**r, **status()}


def owner_name() -> str:
    return S.reg.owner_name()


def seal_owner(name: str):
    """Пометить голос создателем (золото, закреплён) и запечатать его в
    проект: зашифрованный файл едет с репозиторием, ключ — в secrets.json.
    Перенёс secrets.json на другую машину — она узнала создателя там."""
    r = S.reg.set_owner(name)
    if not r.get("ok"):
        return {**r, **status()}
    v = S.reg.speakers[name]
    from server.voiceprint import owner_seal
    sr = owner_seal.seal(name, v["embs"], S.reg.stat.get(name))
    S.reg.save()
    _emit({"type": "voiceprint_renamed", "old": name, "new": name})
    log.info("Голос создателя: «%s» помечен золотом%s", name,
             "" if not sr.get("ok") else " и запечатан в проект")
    return {**sr, "owner": name, **status()}


def load_owner_seal():
    """При старте: печать есть, ключ есть, а создателя в памяти нет —
    распечатать и познакомить. Ровно сценарий «поставил на другой ПК»."""
    try:
        if S.reg.owner_name():
            return
        from server.voiceprint import owner_seal
        got = owner_seal.unseal()
        if not got:
            return
        name, embs, stat = got
        if S.reg.speakers and next(iter(
                S.reg.speakers.values()))["embs"].shape[1] != embs.shape[1]:
            log.info("Печать голоса: размерность %d не совпала с текущим "
                     "энкодером — распечатаю после смены", embs.shape[1])
            return
        S.reg.enroll(name, embs)
        S.reg.set_owner(name)
        if stat:
            st = S.reg.stat.setdefault(name, {"last": 0.0, "n": 0,
                                              "plo": 0.0, "phi": 0.0})
            st["plo"] = float(stat.get("plo") or 0)
            st["phi"] = float(stat.get("phi") or 0)
        S.reg.save()
        refit()
        log.info("Печать голоса: создатель «%s» распечатан — узнаю его на "
                 "этой машине", name)
    except Exception as e:
        log.warning("Печать голоса: не распечаталась (%s)", e)


def enroll_file(name: str, path, owner: bool = False):
    """Эталон из АУДИОФАЙЛА (2026-07-28): владелец наговорил текст на
    диктофон телефона — этого достаточно, микрофон ПК не нужен. Файл режем
    скользящими окнами ~1.2с, каждое окно проверяем на речь и кодируем тем
    же энкодером, что слышит микрофон."""
    import soundfile as sf
    from server.voiceprint.encoder import speechiness
    try:
        x, sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception as e:
        return {"ok": False, "error": f"файл не читается: {e}"}
    x = x.mean(axis=1)
    if sr != SR:
        # линейный ресемпл: для эмбеддинга тембра этого достаточно
        n = int(len(x) * SR / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n),
                      np.arange(len(x)), x).astype(np.float32)
    pcm = np.clip(x * 32767, -32768, 32767).astype(np.int16)
    win, hop = int(SR * 1.2), int(SR * 0.6)
    embs, skipped = [], 0
    for i in range(0, max(1, len(pcm) - win), hop):
        w = pcm[i:i + win]
        if len(w) < win:
            break
        sc, _ = speechiness(w, SR)
        if sc < 0.35:
            skipped += 1
            continue
        vec, _pitch = S.enc.encode(w)
        if vec is not None:
            embs.append(vec)
    if len(embs) < 6:
        return {"ok": False, "error": "в записи меньше четырёх секунд "
                                      "внятной речи — наговори подольше"}
    n = S.reg.enroll(name, np.vstack(embs))
    S.reg.save()
    refit()
    log.info("Эталон из файла: «%s», окон %d (пропущено не-речи %d)",
             name, n, skipped)
    out = {"ok": True, "name": name, "vectors": int(n), "skipped": skipped}
    if owner:
        out = {**out, **seal_owner(name)}
    return out


def merge(src: str, dst: str):
    """Слить голос src в dst и сразу переобучить проекцию: облако должно
    перекраситься на глазах, а не после перезапуска."""
    r = S.reg.merge(src, dst)
    if r.get("ok"):
        S.reg.save()
        refit()
        log.info("Отпечаток голоса: «%s» слит с «%s» — теперь эталон из %d "
                 "векторов", src, dst, r.get("vectors", 0))
        _emit({"type": "voiceprint_renamed", "old": src, "new": dst})
    return {**r, **status()}


def enroll_start(name: str, need: int = 24):
    name = (name or "").strip()[:32]
    if not name:
        return {"ok": False, "error": "нужно имя"}
    S.enroll_name, S.enroll_buf, S.enroll_need = name, [], max(6, int(need))
    log.info("Отпечаток голоса: записываю эталон «%s»", name)
    _emit(_enroll_event())
    return {"ok": True, **status()}


def enroll_cancel():
    S.enroll_name, S.enroll_buf = "", []
    _emit(_enroll_event())
    return {"ok": True, **status()}


def enroll_finish():
    name, buf = S.enroll_name, S.enroll_buf
    S.enroll_name, S.enroll_buf = "", []
    if not name or len(buf) < 4:
        _emit(_enroll_event())
        return {"ok": False, "error": "слишком мало речи — скажи ещё пару фраз"}
    n = S.reg.enroll(name, np.vstack(buf))
    S.reg.dirty = True
    S.reg.save()
    refit()
    log.info("Отпечаток голоса: «%s» запомнен, эталонных векторов %d", name, n)
    _emit(_enroll_event())
    return {"ok": True, "name": name, "vectors": n, **status()}


def clear_map():
    """Полная чистка карты голосов: облака начинают расти заново, эталоны
    целы — узнавание не страдает. Ответ на «остаточные облачка»: серые
    точки без имени не принадлежали никому и при удалении голосов
    оставались висеть."""
    n = S.reg.clear_points()
    S.reg.save()
    refit()
    log.info("Карта голосов очищена: убрано точек %d", n)
    return {"ok": True, "removed": n, **status()}


def forget(name: str):
    ok = S.reg.forget(name)
    S.reg.save()
    return {"ok": ok, **status()}


def refit():
    """Переобучить проекцию в отдельном потоке — рабочий поток не ждёт."""
    if S.refitting:
        return
    X = S.reg.training_set()
    if X is None or len(X) < 4:
        return
    S.refitting = True

    def _job():
        try:
            t0 = time.monotonic()
            kind = S.proj.fit(X)
            ms = round((time.monotonic() - t0) * 1000)
            S.new_points = 0
            _emit({"type": "voiceprint_refit", "kind": kind,
                   "points": int(len(X)), "ms": ms})
        except Exception as e:
            log.warning("Переобучение проекции упало: %s", e)
        finally:
            S.refitting = False

    threading.Thread(target=_job, name="voiceprint-fit", daemon=True).start()


def points():
    """Всё облако для интерфейса: пересчитывается текущей проекцией."""
    if S.reg.pts is None or not len(S.reg.pts):
        return {"pts": [], "colors": S.reg.colors(), **S.proj.state()}
    P = S.proj.transform(S.reg.pts)
    out = [{"x": round(float(p[0]), 4), "y": round(float(p[1]), 4),
            "who": w} for p, w in zip(P, S.reg.pts_who)]
    return {"pts": out, "colors": S.reg.colors(), **S.proj.state()}


def status():
    sp = {}
    for name, v in S.reg.speakers.items():
        st = S.reg.stat.get(name, {})
        cand, conf = S.reg.name_guess(name)
        sp[name] = {"vectors": int(len(v["embs"])), "color": v["color"],
                    "pinned": bool(v.get("pinned")),
                    "auto": bool(v.get("auto")),
                    "owner": bool(v.get("owner")),
                    "guess": cand, "guess_conf": conf,
                    "last": round(float(st.get("last", 0.0)), 1),
                    "heard": int(st.get("n", 0)),
                    "pitch_lo": int(st.get("plo", 0) or 0),
                    "pitch_hi": int(st.get("phi", 0) or 0)}
    return {
        "enabled": enabled(),
        "backend": S.enc.backend,
        "backend_error": S.enc.last_error,
        "dim": int(S.enc.dim),
        "speakers": sp,
        "cloud": 0 if S.reg.pts is None else int(len(S.reg.pts)),
        "enroll": {"name": S.enroll_name, "got": len(S.enroll_buf),
                   "need": S.enroll_need},
        "heard_s": round(S.heard_s, 1),
        "noise_seen": S.noise_seen,
        "speech_min": float(CFG.get("voiceprint.speech_min", 0.5)),
        "self_name": self_name(),
        "listen_self": listen_self(),
        "self_known": self_name() in S.reg.speakers,
        "owner": S.reg.owner_name(),
        "room": room(),
        "last": S.last_event,
        **S.proj.state(),
    }


# ---------------------------------------------------------------- механика
def _emit(evt: dict):
    if S.sink:
        try:
            S.sink(evt)
        except Exception as e:
            log.debug("не смогла разослать событие отпечатка: %s", e)


def _enroll_event():
    return {"type": "voiceprint_enroll", "name": S.enroll_name,
            "got": len(S.enroll_buf), "need": S.enroll_need}


class _Vad:
    """Тот же приём, что в слухе (stt/manager.py): адаптивный порог по
    шумовому полу + гистерезис. Свой экземпляр, чтобы не лезть в состояние
    рабочего VAD — там от него зависит нарезка фраз для распознавания."""

    def __init__(self):
        self.thr = CFG.get("stt.vad.rms_threshold", 0.012)
        self.floor = 0.0
        self.in_speech = False

    def push(self, x: np.ndarray):
        rms = float(np.sqrt(np.mean(x * x))) if len(x) else 0.0
        eff = max(self.thr, self.floor * 2.5 + 0.004)
        voice = rms > (eff * 0.6 if self.in_speech else eff)
        if not voice and not self.in_speech:
            self.floor = (0.95 * self.floor + 0.05 * rms) if self.floor else rms
        self.in_speech = voice
        return voice, rms


def _worker():
    S.enc.warmup()
    # проекция на старте: восстановить ту же картинку, что была вчера
    if S.reg.training_set() is not None:
        refit()

    vad = _Vad()
    win_s = float(CFG.get("voiceprint.window_s", 1.2))
    emit_ms = int(CFG.get("voiceprint.emit_ms", 320))
    min_s = 0.55
    buf: list = []
    buf_n = 0
    since_emit = 0
    silence = 0
    speaking = False

    while not S.stop.is_set():
        try:
            chunk = S.q.get(timeout=0.4)
        except queue.Empty:
            chunk = None

        if chunk is None:
            # тишина в очереди: если только что говорили — гасим точку
            if speaking and time.monotonic() - silence > 0.6:
                speaking = False
                buf, buf_n, since_emit = [], 0, 0
                _emit({"type": "voiceprint", "state": "idle"})
            continue

        if not enabled():
            buf, buf_n = [], 0
            continue

        x = np.asarray(chunk, dtype=np.float32) / 32768.0
        voice, rms = vad.push(x)
        # ЖУРНАЛ СЛУХА СЛУШАЕТ ШИРЕ. Обычно окно набирается только на речи —
        # так дешевле и так надо для отпечатка. Но щелчок мышкой короче любого
        # порога длительности: пока журнал пишет, берём ВСЁ, что заметно
        # громче шумового пола, иначе в отчёте про звуки не будет звуков.
        wide = False
        try:
            from server.earlog import EARLOG
            # Пока журнал пишет, набираем окно НЕПРЕРЫВНО, включая паузы:
            # иначе короткие события недосчитываются. Щелчок это 90 отсчётов
            # в чанке из 1600; между щелчками тишина, буфер перестаёт
            # набираться, и на шесть серий кликов приходится два окна, а на
            # ровный гул — двадцать. Отчёт получался «в комнате был гул».
            wide = EARLOG.on
        except Exception:
            pass
        if not voice and not wide:
            if speaking and time.monotonic() - silence > 0.6:
                speaking = False
                buf, buf_n, since_emit = [], 0, 0
                _emit({"type": "voiceprint", "state": "idle"})
            continue

        silence = time.monotonic()
        speaking = True
        S.heard_s += len(x) / SR
        buf.append(x)
        buf_n += len(x)
        since_emit += len(x)
        cap = int(SR * win_s)
        while buf_n > cap and len(buf) > 1:
            buf_n -= len(buf.pop(0))

        if buf_n < SR * min_s or since_emit < SR * emit_ms / 1000:
            continue
        since_emit = 0

        # её собственный голос из колонок не должен становиться «человеком»
        if S.echo_guard is not None:
            try:
                if S.echo_guard():
                    _emit({"type": "voiceprint", "state": "echo"})
                    continue
            except Exception:
                pass

        try:
            _process(np.concatenate(buf), rms)
        except Exception as e:
            log.warning("Отпечаток голоса споткнулся: %s", e)


def _to16k(x: np.ndarray, sr: int) -> np.ndarray:
    """Линейная передискретизация в 16кГц. Для отпечатка этого достаточно:
    важна не идеальная форма волны, а чтобы ВСЕ её куски приводились к одной
    и той же шкале — иначе её собственный голос расползётся на два кластера
    только оттого, что движки TTS работают на разной частоте."""
    if sr == SR or sr <= 0:
        return x
    n = int(round(len(x) * SR / float(sr)))
    if n < 2:
        return x
    return np.interp(np.linspace(0, len(x) - 1, n),
                     np.arange(len(x)), x).astype(np.float32)


def _self_worker():
    """Её собственный голос: окно 1.2с, точка раз в ~320мс — как у людей.

    ЗАЧЕМ ЭТО ВООБЩЕ. Во-первых, человеку интересно видеть её голос рядом
    со своим — это и есть «режим её спектра». Во-вторых, у неё появляется
    СВОЯ метка в пространстве голосов, и тогда эхо из колонок перестаёт быть
    загадкой: микрофон слышит её же голос, точка падает в её территорию, и
    видно, что это она, а не «незнакомый человек»."""
    win_s = float(CFG.get("voiceprint.window_s", 1.2))
    emit_ms = int(CFG.get("voiceprint.emit_ms", 320))
    buf: list = []
    buf_n = since = 0
    while not S.stop.is_set():
        try:
            chunk, sr = S.selfq.get(timeout=0.5)
        except queue.Empty:
            if S.self_on:
                S.self_on = False
                buf, buf_n, since = [], 0, 0
                _emit({"type": "voiceprint", "state": "self_idle"})
            continue
        if not enabled() or not listen_self():
            buf, buf_n = [], 0
            continue
        x = _to16k(np.asarray(chunk, dtype=np.float32), sr)
        if not len(x):
            continue
        S.self_on = True
        buf.append(x)
        buf_n += len(x)
        since += len(x)
        cap = int(SR * win_s)
        while buf_n > cap and len(buf) > 1:
            buf_n -= len(buf.pop(0))
        if buf_n < SR * 0.55 or since < SR * emit_ms / 1000:
            continue
        since = 0
        try:
            _process_self(np.concatenate(buf))
        except Exception as e:
            log.warning("Свой голос не разобрался: %s", e)


def _process_self(win: np.ndarray):
    name = self_name()
    rms = float(np.sqrt(np.mean(win * win))) if len(win) else 0.0
    pcm = np.clip(win * 32768.0, -32768, 32767).astype(np.int16)
    emb, f0 = S.enc.encode(pcm)
    xy = S.proj.transform(emb)[0]

    # ЗНАКОМСТВО С СОБОЙ: первые два десятка кусков собственной речи
    # становятся эталоном автоматически. Просить владельца «записать голос
    # Сайки» было бы странно — она и так знает, когда говорит сама.
    if name not in S.reg.speakers:
        S.self_buf.append(emb)
        if len(S.self_buf) >= 24:
            S.reg.enroll(name, np.vstack(S.self_buf), color=SELF_COLOR)
            S.self_buf = []
            S.reg.save()
            refit()
            log.info("Отпечаток голоса: запомнила СВОЙ голос как «%s»", name)
    else:
        S.reg.note(name, f0)
        S.reg.adapt(name, emb, 1.0)

    # в облако кладём каждую вторую: говорит она много, и без прореживания
    # её кластер за вечер вытеснит из истории все людские точки
    S.self_pts += 1
    if S.self_pts % 2 == 0:
        S.reg.add_point(emb, name)
        S.new_points += 1

    _emit({"type": "voiceprint", "state": "self",
           "x": round(float(xy[0]), 4), "y": round(float(xy[1]), 4),
           "who": name, "sim": 1.0, "conf": 1.0,
           "energy": round(min(1.0, rms * 8.0), 3), "pitch": int(f0),
           "color": S.reg.speakers.get(name, {}).get("color", SELF_COLOR)})


def _process(win: np.ndarray, rms: float):
    # ЭТО ВООБЩЕ ГОЛОС? Проверяем ДО кодирования — и ради честности, и ради
    # экономии: щелчок мышкой не должен ни стоить нам эмбеддинга, ни получать
    # метку «незнакомый голос».
    #
    # ЗАЧЕМ (2026-07-28, жалоба владельца): порог громкости не отличает речь
    # от клацанья мышкой, стука по столу и скрипа стула. Всё это громче
    # тишины, значит «речь», значит точка на карте и подпись «незнакомый
    # голос». Пространство голосов засорялось стуком, статистика врала.
    # Теперь смотрим строение звука: тон, форма спектра, доля низа,
    # длительность (см. encoder.speechiness).
    # тишину не разбираем вообще: в режиме журнала окно набирается всегда,
    # и без этой отсечки в отчёт попали бы сотни «звуков тишины»
    wrms = float(np.sqrt(np.mean(win * win))) if len(win) else 0.0
    if wrms < float(CFG.get("voiceprint.silence_rms", 0.0022)):
        return
    score, parts = speechiness(win)
    if score < float(CFG.get("voiceprint.speech_min", 0.5)):
        S.noise_seen += 1
        try:                       # журнал слуха: копим, если он пишет
            from server.earlog import EARLOG
            if EARLOG.on:
                EARLOG.note_sound(mel_profile(win), rms * 8.0, parts)
        except Exception:
            pass
        evt = {"type": "voiceprint", "state": "noise",
               "score": round(score, 2), "parts": parts,
               "energy": round(min(1.0, rms * 8.0), 3)}
        S.last_noise = evt
        _emit(evt)
        return
    pcm = np.clip(win * 32768.0, -32768, 32767).astype(np.int16)
    emb, f0 = S.enc.encode(pcm)
    who, sim, conf, near = S.reg.match(emb)
    xy = S.proj.transform(emb)[0]

    if S.enroll_name:
        S.enroll_buf.append(emb)
        who = S.enroll_name                # свои же точки красим сразу
        _emit(_enroll_event())
        if len(S.enroll_buf) >= S.enroll_need:
            enroll_finish()

    if who:
        S.who_last, S.who_ts = who, time.monotonic()
        S.unk = []
        # имя, сказанное в адрес собеседника, достаётся тому, кто ответил
        now = time.monotonic()
        S.addr = [a for a in S.addr if now - a[1] < 20.0]
        for nm, ts, frm, w in list(S.addr):
            if frm != who:
                _apply_name(who, nm, w)
                S.addr.remove((nm, ts, frm, w))
    elif not S.enroll_name and CFG.get("voiceprint.auto_meet", True):
        # незнакомый голос: копим, и если он устойчив — знакомимся сами
        S.unk.append(emb)
        del S.unk[:-40]
        need = int(CFG.get("voiceprint.auto_meet_n", 22))
        if len(S.unk) >= need:
            X = np.vstack(S.unk)
            c = X.mean(axis=0)
            c = c / max(1e-9, float(np.linalg.norm(c)))
            # порог «это один и тот же незнакомец» чуть мягче порога
            # узнавания: тут мы не решаем «свой/чужой», а лишь проверяем,
            # что накопленное не каша из двух разных людей
            keep = X[(X @ c) > (0.75 if len(c) < 128 else 0.45)]
            if len(keep) >= need * 0.7:
                S.unk_n += 1
                nm = f"Голос {S.unk_n + 1}"
                while nm in S.reg.speakers:
                    S.unk_n += 1
                    nm = f"Голос {S.unk_n + 1}"
                S.reg.enroll(nm, keep)
                S.reg.speakers[nm]["auto"] = True
                S.reg.save()
                S.unk = []
                log.info("Отпечаток голоса: познакомилась сама — «%s» "
                         "(%d векторов)", nm, len(keep))
                _emit({"type": "voiceprint_met", "who": nm})
                refit()
            else:
                S.unk = S.unk[-10:]
    # ЕЁ СОБСТВЕННЫЙ ЭТАЛОН ЖИВЁТ ТОЛЬКО ОТ TTS. Раньше сюда попадало всё,
    # что микрофон принял за неё, — и получалась положительная обратная
    # связь: рыхлый эталон -> низкий порог -> «своим» становится чужой голос
    # -> он же дописывается в эталон -> порог ещё ниже. За вечер её профиль
    # вбирал в себя ползала. Живой звук её эталон больше не трогает.
    if who and not S.enroll_name and who != self_name():
        S.reg.note(who, f0)
        S.reg.adapt(who, emb, conf)   # эталон взрослеет вместе с человеком
    try:
        from server.earlog import EARLOG
        if EARLOG.on:
            EARLOG.note_voice(emb, mel_profile(win), f0, rms * 8.0, who)
    except Exception:
        pass
    S.reg.add_point(emb, who)
    S.new_points += 1

    evt = {
        "type": "voiceprint", "state": "voice",
        "x": round(float(xy[0]), 4), "y": round(float(xy[1]), 4),
        "who": who, "near": near, "sim": round(sim, 3),
        "conf": round(conf, 3),
        "energy": round(min(1.0, rms * 8.0), 3), "pitch": int(f0),
        "speech": round(score, 2),
        "color": S.reg.speakers.get(who, {}).get("color", "#8892a6"),
    }
    S.last_event = evt
    _emit(evt)

    if S.new_points >= REFIT_EVERY:
        refit()
    now = time.time()
    if now - S.last_save > SAVE_EVERY:
        S.last_save = now
        S.reg.save()
