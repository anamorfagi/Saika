"""УХО: что именно звучит вокруг — метки звуков, а не слова.

2026-08-13, живой отказ владельца: «клацанье клавиатуры система всё так же
записывает в голос». И правда — в карте голосов завёлся «Голос 4»: 153
срабатывания, 103-400 Гц. Это не человек, это клавиатура получила профиль.

ДВЕ РАЗНЫЕ ЗАДАЧИ, которые до сих пор путались:
  1. ЧЕЙ голос — этим занят voiceprint (эмбеддинги ECAPA);
  2. ЗВУК ЛИ ЭТО ВООБЩЕ ГОЛОС — а этим не занимался никто. Отпечаток
     честно считался от чего угодно: щелчка, стука, музыки. Отсюда и
     фантомные «голоса» в карте.

Здесь второе. Классификатор AudioSet отвечает на вопрос «что звучит»
(527 классов: речь, клавиатура, музыка, лай, посуда). Из его ответа берём:
  - ПРЕДОХРАНИТЕЛЬ: нет речи в кадре — voiceprint не трогаем;
  - КОНТЕКСТ: метки того, что слышно, уходят в промпт как ФОН, который
    Сайка МОЖЕТ использовать в разговоре. Не как запрос и не как команда:
    «слышу клавиатуру» — это не «прокомментируй клавиатуру».

ПОЧЕМУ PANNs, А НЕ YAMNet (отступление от плана в HEARING.md). YAMNet тянет
TensorFlow — второй фреймворк глубокого обучения в венв, где уже стоит
torch. Этот венв и так хрупкий (см. FORBIDDEN_PKG в setup/ai_doctor.py:
одна переустановка torch чуть не снесла CUDA всему проекту). panns_inference
работает на уже установленном torch и добавляет только веса.

ПОЧЕМУ ПО УМОЛЧАНИЮ CPU. Видеопамять — самый дефицитный ресурс машины
(13 из 16 ГБ заняты, клон-голосу не хватает), а процессор простаивает на
20%. CNN14 на пару секунд звука — десятки миллисекунд на CPU, и раз в
секунду это незаметно. Ключ hearing.device, если захочется на видеокарту.

ЗВУК НЕ ХРАНИМ — как и в earlog. Только метки.
"""
import logging
import threading
import time

import numpy as np

from anamorf.config import CFG

log = logging.getLogger("saika.ears")

SR_IN = 16000          # микрофон
SR_MODEL = 32000       # PANNs обучены на 32 кГц
WINDOW_S = 2.0         # окно классификации
EVERY_S = 1.0          # как часто прогонять

STATE = {
    "ready": False,        # модель загружена
    "off": False,          # выключено или не установлено — работаем без ушей
    "tags": [],            # [(имя, вероятность)] последнего окна
    "speech": 0.0,         # уверенность, что в кадре РЕЧЬ
    "ts": 0.0,             # когда посчитано
    "dist": "",            # на слух: рядом / в комнате / приглушённо
    "event": None,         # разовое событие (чих, крик) для рефлекса
    "typing_cps": 0.0,     # темп печати по звуку, нажатий/сек
    "sounds": [],          # живая лента звуков для чата (см. pop_sounds)
}

# ═══ СОБЫТИЯ, НА КОТОРЫЕ ЖИВОЙ ЧЕЛОВЕК РЕАГИРУЕТ (2026-08-15) ═══
# Просьба владельца: «услышать, что кто-то чихнул, и сказать "будь
# здоров"; понять, что кто-то орёт и это не к ней относится». Чих — повод
# для короткой человеческой реакции; крик — наоборот, знак ФОНА: на
# повышенных тонах говорят не с ассистентом. Событие складывается сюда
# один раз, забирает его конвейер (pop_event) с собственным кулдауном.
_EVENTS = {
    "sneeze": ("чих", 0.30),
    "cough": ("кашель", 0.45),
    "shout": ("крик", 0.35),
    "yell": ("крик", 0.35),
    "screaming": ("крик", 0.35),
    "children shouting": ("крик", 0.35),
}


# ═══ ЖИВАЯ ЛЕНТА ЗВУКОВ (2026-08-15) ═══
# Владелец: «она должна определять звуки в реальном времени и ПИСАТЬ их,
# даже длинные — я специально сказал "Тссссс", и ничего не появилось».
# Он прав в главном: шипение — не речь, нейро-VAD честно его не режет, и
# движку писать нечего. Но УШИ его слышат — просто их метки уходили только
# в промпт, человеку их видно не было. Теперь заметный НЕ-речевой звук
# уезжает строкой в чат: «🔉 слышу: шипение». Один и тот же звук не
# повторяется чаще раза в 8 секунд — лента, а не пулемёт.
_FEED_SKIP = ("speech", "conversation", "narration", "male speech",
              "female speech", "silence", "inside", "music")  # музыку шлём
_FEED_SKIP = ("speech", "conversation", "narration", "male speech",
              "female speech", "silence", "inside, small room",
              "inside, large room or hall")
_feed_last = {}


# ЗВУК — БУКВАМИ, КАК ЕГО ПЕРЕДАЛ БЫ ЧЕЛОВЕК (2026-08-15, владелец:
# «звуки тс-тс-тс, тарелочки, хай-хэты, кх-кх он мог бы писать как
# похожий звук, просто как текст»). У ударных и шумов есть общепринятая
# «запись голосом» — ею и подписываем.
_ONOMA = {
    "hi-hat": "тс-тс", "cymbal": "тссь", "bass drum": "бум-бум",
    "snare drum": "тыщ", "drum": "тум", "beatboxing": "бц-тк",
    "hiss": "тсссс", "sizzle": "тсссс", "click": "щёлк",
    "mouse click": "щёлк", "computer keyboard": "тук-тук-тук",
    "typing": "тук-тук", "knock": "тук-тук", "cough": "кхе-кхе",
    "finger snapping": "щёлк", "clapping": "хлоп", "applause": "хлоп-хлоп",
    "whistling": "фьюить", "laughter": "ха-ха", "sneeze": "апчхи",
    "drum roll": "тррр", "telephone bell ringing": "дзынь",
    "alarm": "дзынь-дзынь", "water": "буль", "drip": "кап",
    "plop": "бульк", "chop": "чоп", "thud": "бух", "squish": "хлюп",
}


# ЗВУК ЖИВЁТ, ПОКА ЗВУЧИТ (2026-08-15, третья редакция за день — и
# владелец каждый раз прав). Дословно: «метки живые, не нужно их писать
# каждый тик. Я слышу, как шелестит дерево от ветра, — оно уходит в фон
# меткой в голове; звук исчез — метка исчезла». Ровно так и делаем:
# СОБЫТИЯ вместо потока. Метка рождается, когда звук ПОЯВИЛСЯ, молча
# висит, пока он длится, и снимается, когда он ушёл. Наружу уезжает
# только ИЗМЕНЕНИЕ картины; звук мигает на границе порога — держим его
# в картине ещё пару секунд (linger), чтобы метка не дрожала.
# ═══ ЗВУКИ ЧЕЛОВЕКА — КАК ИХ СЛЫШИТ ЧЕЛОВЕК (06.09.2026) ═══
# Владелец, о разметке ролика: «правильнее делает разметки смеха… крика…
# чтобы вы именно звуки прям как люди воспринимали не как текст а как
# звуки», «система должна определять от звуков природы до искусственных и
# отмечать в ролике это где что она услыхала».
#
# Живой замер (tools/sound_probe.py, первые 20 с ролика ДНК, окно 1 с):
#   крик Снейла на 6.5-7.5 с уши назвали «Animal 0.63 · Dog 0.29 ·
#   Wail, moan 0.14 · Groan 0.34 · Screaming 0.12»; смех на 9.5 —
#   «Laughter 0.17»; запиканное слово на 16.0 — «Beep, bleep 0.44».
# То есть слышат всё, но: (1) человеческий вопль спектрально похож на
# собачий вой, и родовой «зверь» берёт больше баллов; (2) смех и крик
# редко набирают общий порог 0.2-0.35 — у них свои, ниже. Поэтому:
#   - у каждого человеческого звука СВОЙ порог (таблица ниже);
#   - если в окне есть человеческий звук — «животные» в этом окне молчат:
#     в комнате с людьми вопль — это человек, а не собака;
#   - у каждой метки есть РОД (kind): «миг» — разовое (крик, смех, чих,
#     пик), уходит в ленту отметкой на месте; «фон» — длящееся (музыка,
#     дождь, клавиатура), живёт в чате как состояние, пока звучит.
_HUMAN_EV = {
    "screaming": ("крик", 0.10), "yell": ("крик", 0.10),
    "shout": ("крик", 0.12), "bellow": ("крик", 0.12),
    "wail, moan": ("крик", 0.12), "groan": ("крик", 0.20),
    "children shouting": ("крик", 0.15), "whoop": ("крик", 0.12),
    "laughter": ("смех", 0.12), "giggle": ("смех", 0.10),
    "chuckle, chortle": ("смех", 0.10), "belly laugh": ("смех", 0.10),
    "snicker": ("смех", 0.10), "baby laughter": ("смех", 0.10),
    "crying, sobbing": ("плач", 0.20), "baby cry, infant cry": ("плач", 0.20),
    "cough": ("кашель", 0.30), "sneeze": ("чих", 0.30),
    "whistling": ("свист", 0.30), "singing": ("пение", 0.35),
    "applause": ("аплодисменты", 0.25), "clapping": ("хлопки", 0.30),
    "cheering": ("ликование", 0.20), "gasp": ("вздох испуга", 0.25),
    "beep, bleep": ("пик", 0.20), "busy signal": ("пик", 0.25),
}
_NATURE = ("fire", "crackle", "rain", "wind", "water", "stream", "river",
           "waves", "ocean", "thunder", "bird", "chirp", "insect", "cricket",
           "frog", "owl", "rustling", "leaves", "waterfall", "drip", "snow")
_ANIMAL = ("animal", "dog", "domestic animals", "wild animals", "bark",
           "howl", "bow-wow", "yip", "whimper", "growling", "cat", "meow",
           "caterwaul", "roar", "livestock")
_MOMENT = ("крик", "смех", "плач", "кашель", "чих", "свист", "хлопки",
           "аплодисменты", "ликование", "вздох испуга", "пик", "щелчок",
           "стук", "хлопок двери", "звон стекла", "звон осколков", "бух",
           "шлеп", "чоп", "бульк")


# ЗВУК — БУКВАМИ (06.09.2026, владелец: «я хлопнул в ладоши или чихнул —
# это можно отобразить „хлоп-хлоп" или „апчхи"»). Для человеческих
# звуков — своя запись голосом, как её написал бы человек в чате.
_HUMAN_ONO = {"крик": "а-а-а!", "смех": "ха-ха", "плач": "у-у-у",
              "кашель": "кхе-кхе", "чих": "апчхи", "свист": "фьюить",
              "хлопки": "хлоп-хлоп", "аплодисменты": "хлоп-хлоп-хлоп",
              "пик": "пи-и-п", "вздох испуга": "ах"}


def _kind(ru: str) -> str:
    return "миг" if ru in _MOMENT else "фон"


def _human_events(tags):
    """-> [(ru, p)] человеческие звуки из окна по своим порогам."""
    out = {}
    for name, p in tags:
        low = str(name).lower()
        hit = _HUMAN_EV.get(low)
        if hit and float(p) >= hit[1]:
            ru = hit[0]
            if float(p) > out.get(ru, 0.0):
                out[ru] = float(p)
    return sorted(out.items(), key=lambda kv: -kv[1])


_active = {}          # low-имя -> {"ru","en","ono","p","last"}  (канал по умолчанию)
_last_sent = None     # какой набор ключей уже показан
# ПО КАНАЛАМ (06.09.2026): ролик из петли и голос из Discord — разные
# комнаты. Раньше их куски по 100 мс перемежались в одном буфере, и окно
# в секунду было винегретом из двух источников — уши слышали «скретч» и
# «гудок». Теперь у каждого канала свой буфер, своё окно, свои метки.
_active_by = {}       # src -> {low: ent}
_last_by = {}         # src -> keys

# РОДОВЫЕ МЕТКИ МОЛЧАТ, КОГДА ЕСТЬ ЧАСТНАЯ (2026-08-15, живой случай:
# губная трель дала «собака 44% · Animal 44% · Domestic animals 35%» —
# это ОДИН звук, показанный трижды, от частного к общему: AudioSet
# иерархичен, и родители класса срабатывают вместе с ним. Человек так не
# слышит: «собака» уже включает «животное». Родовую метку показываем,
# только если ничего конкретнее в кадре нет.
_GENERIC = ("animal", "domestic animals, pets", "wild animals",
            "human sounds", "sounds of things", "source-ambiguous sounds",
            "music", "musical instrument", "human voice", "human locomotion",
            "onomatopoeia", "noise", "background noise", "generic impact",
            "surface contact", "miscellaneous sources", "specific impact")


# ═══ ЗА ОКНОМ НЕ ЕЗДЯТ МАШИНЫ ПО КЛАВИАТУРЕ (2026-08-16) ═══
# Владелец, дословно: «клавиатура или шум в микро вряд ли похоже на
# машину или на мои звуки битбокса». Он прав дважды.
#
# Про машину. PANNs обучены на ютубе, где «vehicle» — это широкополосный
# гул с транзиентами. Серия щелчков клавиш даёт спектрально ровно это, и
# на одном окне класс честно берёт свои 41%. Но у настоящей машины есть
# то, чего у клавиатуры нет: ДЛИТЕЛЬНОСТЬ. Машина за окном гудит десять
# секунд подряд, щелчок живёт сотню миллисекунд. Поэтому:
#   - любая метка показывается только после ВТОРОГО подряд окна;
#   - «уличные» классы, которых у стола не бывает без открытого окна, —
#     после третьего и с порогом заметно выше.
# Это не запрет на класс (машина за окном действительно бывает, и она
# нужна) — это требование подтвердить себя временем.
_OUTDOOR = ("vehicle", "car", "truck", "motor", "engine", "aircraft",
            "helicopter", "train", "motorcycle", "thunder", "wind",
            "chainsaw", "siren")


# ═══ ФИЗИКА ПРОТИВ ОШИБКИ «КЛАВИАТУРА = МАШИНА» (27.08.2026) ═══
# Владелец, дословно: «я за всё время даже клавиатуру замечал, что он писал
# слышу машину — это хуета у нас сделана».
#
# PANNs обучены на ютубе: там «vehicle» — широкополосный гул с транзиентами,
# и серия щелчков клавиш спектрально попадает ровно в него. Подтверждение
# временем (три окна) помогает, но не спасает: печатают тоже долго.
#
# Разница у них ФИЗИЧЕСКАЯ, и её видно по спектру одного окна:
#   машина  — энергия внизу (до ~500 Гц), спектр СТОИТ на месте;
#   клавиши — энергия размазана вверх, спектр дёргается на каждом щелчке.
# Считаем два числа — долю низа и «дёрганость» (среднее изменение спектра
# между кадрами) — и не пускаем уличные метки, если картина не машинная.
# Это не запрет класса: настоящая машина обе проверки проходит легко.
def _spectral_veto(tags, chunk):
    try:
        if not tags:
            return tags
        if not any(any(k in str(n).lower() for k in _OUTDOOR) for n, _ in tags):
            return tags                      # уличных меток нет — не мешаем
        x = np.asarray(chunk, dtype=np.float32).ravel()
        if x.size < 2048:
            return tags
        if np.max(np.abs(x)) > 1.5:          # пришёл int16
            x = x / 32768.0
        n = 1024
        hop = 512
        win = np.hanning(n).astype(np.float32)
        fq = np.fft.rfftfreq(n, 1.0 / 16000)
        lo_m = fq <= 500.0
        sp_prev = None
        lo_r, flux = [], []
        for off in range(0, max(0, x.size - n), hop):
            sp = np.abs(np.fft.rfft(x[off:off + n] * win))
            tot = float(sp.sum()) + 1e-9
            lo_r.append(float(sp[lo_m].sum()) / tot)
            spn = sp / tot
            if sp_prev is not None:
                d = spn - sp_prev
                flux.append(float(np.sqrt((d[d > 0] ** 2).sum())))
            sp_prev = spn
        if not lo_r or not flux:
            return tags
        low_ratio = float(np.mean(lo_r))
        jitter = float(np.mean(flux))
        need_low = float(CFG.get("hearing.outdoor_low_ratio", 0.45))
        max_jit = float(CFG.get("hearing.outdoor_max_jitter", 0.10))
        if low_ratio >= need_low and jitter <= max_jit:
            return tags                      # похоже на настоящий гул
        out = [(n_, p) for n_, p in tags
               if not any(k in str(n_).lower() for k in _OUTDOOR)]
        if len(out) != len(tags):
            log.debug("уличная метка отклонена: низ %.2f (нужно %.2f), "
                      "дёрганость %.3f (предел %.3f)",
                      low_ratio, need_low, jitter, max_jit)
        return out or tags[:1]
    except Exception:
        return tags


def _feed_sounds(tags, rms=None, src=None):
    global _last_sent, _active
    now = time.time()
    if src is None:
        src = STATE.get("src", "")
    # музыка в канале → узнавание (Shazam) и караоке; см. music_id.maybe
    try:
        from anamorf import music_id as _mid
        _mp = max([float(p) for n, p in (tags or []) if str(n).lower() in ("music", "музыка")] or [0.0])
        _mid.maybe(src or "mic", _mp)
    except Exception:
        pass
    _active = _active_by.setdefault(src, {})
    _last_sent = _last_by.get(src)
    # ТИШИНА — ЭТО ТИШИНА (06.09.2026). Владелец: «я сижу в наушниках,
    # слышу тишину, а он у нас слышит огонь». Классификатор на шумовом
    # полу честно находит «огонь» (шипение) и «пулемёт» (щелчки шумодава
    # Discord) — человек ниже порога слышимости не слышит ничего. Ниже
    # уровня — новых меток не заводим, старые сами гаснут по linger.
    if rms is None:
        try:
            _b = _bufs.get(src, _buf)[-int(float(CFG.get("hearing.window_s", WINDOW_S)) * SR_IN):]
            rms = float(np.sqrt(np.mean(_b ** 2))) if _b.size else 0.0
        except Exception:
            rms = None
    STATE["rms"] = rms
    if rms is not None and rms < float(CFG.get("hearing.feed_min_rms", 0.006)):
        tags = []
    # ШУМ МИКРОФОНА — ПОСТОЯННАЯ МЕТКА (06.09.2026). Владелец: «если система
    # слышит шумы из микро, такое состояние с ней всегда — могла бы просто
    # постоянную метку иметь „шум", пока я шумодав не подрублю». Звук есть,
    # речи нет, ничего конкретного уши не назвали — это и есть шум.
    if (rms is not None and src == "mic"
            and rms >= float(CFG.get("hearing.noise_rms", 0.004))
            and float(STATE.get("speech", 0.0)) < 0.3
            and not any(float(p) >= 0.3 for _n, p in tags)):
        tags = list(tags) + [("Noise", 0.99)]
    linger = float(CFG.get("hearing.feed_linger_s", 2.5))
    conf_n = int(CFG.get("hearing.confirm_windows", 2))
    out_n = int(CFG.get("hearing.confirm_windows_outdoor", 3))
    out_min = float(CFG.get("hearing.feed_min_outdoor", 0.55))
    # есть ли в кадре конкретная (не родовая) метка выше порога
    _has_specific = any(
        float(p) >= float(CFG.get("hearing.feed_min", 0.35))
        and str(n).lower() not in _GENERIC
        and not any(k in str(n).lower() for k in _FEED_SKIP)
        for n, p in tags[:3])
    # человеческие звуки — по своим порогам, из ВСЕХ меток окна
    _hum = _human_events(tags)
    cand = [(ru, p, ru) for ru, p in _hum]
    for name, p in tags[:3]:
        low = str(name).lower()
        if low in _HUMAN_EV:
            continue                      # уже учтён выше по своему порогу
        if _hum and any(k in low for k in _ANIMAL):
            continue                      # в комнате с людьми вопль — человек
        if p < float(CFG.get("hearing.feed_min", 0.35)):
            continue
        # фоновые метки (музыка, дождь, клавиатура) — только уверенные:
        # человеческие звуки идут выше по своим порогам, а «фон» на 0.2
        # это чаще шумовой пол, чем звук. На тихом звуке (комнатный фон,
        # rms < 0.03) планка ещё выше: «артиллерия 0.45» из шороха — не звук.
        _bg_min = float(CFG.get("hearing.feed_min_bg", 0.35))
        if rms is not None and rms < float(CFG.get("hearing.quiet_rms", 0.03)):
            _bg_min = max(_bg_min, float(CFG.get("hearing.feed_min_bg_quiet", 0.55)))
        # ПРИРОДА ПОД РЕЧЬЮ (владелец, аниме 06.09: «звуки огня есть, а метки
        # не было»). Костёр, дождь, ветер, птицы, сверчки под диалогом дают
        # 0.2-0.3 — человек их слышит, планка для них ниже
        if any(k in low for k in _NATURE):
            _bg_min = min(_bg_min, float(CFG.get("hearing.feed_min_nature", 0.22)))
        if p < _bg_min:
            continue
        if any(k in low for k in _FEED_SKIP):
            continue
        if low in _GENERIC and _has_specific:
            continue
        _out = any(k in low for k in _OUTDOOR)
        if _out and p < out_min:
            continue
        cand.append((low, p, name))
    for low, p, name in cand:
        _out = any(k in low for k in _OUTDOOR)
        ent = _active.get(low)
        if ent is None:
            ono = _HUMAN_ONO.get(low, "")
            if not ono:
                for k, v in _ONOMA.items():
                    if k in low:
                        ono = v
                        break
            _ru_name = name if low in {v[0] for v in _HUMAN_EV.values()} else _ru(name)
            _active[low] = {"ru": _ru_name, "en": name, "ono": ono,
                            "p": round(float(p), 2), "last": now,
                            "kind": _kind(_ru_name), "born": now,
                            "seen": 1,
                            # миг (смех, крик, пик) живёт полсекунды — ждать
                            # второго окна значит его не услышать
                            "need": out_n if _out else (
                                1 if _kind(_ru_name) == "миг" else conf_n)}
        else:
            ent["p"] = round(float(p), 2)
            ent["last"] = now
            ent["seen"] = int(ent.get("seen", 1)) + 1
    for low in [k for k, v in _active.items()
                if now - v["last"] > linger]:
        _active.pop(low, None)
    # наружу — только подтверждённые временем; неподтверждённые живут в
    # _active молча и либо дозреют следующим окном, либо истекут по linger
    ready = {k: v for k, v in _active.items()
             if int(v.get("seen", 1)) >= int(v.get("need", 1))}
    keys = tuple(sorted(ready))
    if keys != _last_sent:
        _prev = set(_last_sent or ())
        _last_sent = keys
        _last_by[src] = keys
        cur = [{k: v.get(k) for k in ("ru", "en", "ono", "p", "kind")}
               for v in ready.values()]
        on = [{k: v.get(k) for k in ("ru", "en", "ono", "p", "kind")}
              for k_, v in ready.items() if k_ not in _prev]
        off = [k_ for k_ in _prev if k_ not in ready]
        if on or off:
            log.info("Уши (%s, %.4f): +%s -%s", src, rms or 0.0,
                     [(e["ru"], e["p"]) for e in on], off)
        STATE["sounds"] = (STATE.get("sounds") or []) + [
            {"now": cur, "on": on, "off": off,
             "dist": STATE.get("dist", ""), "src": src, "ts": now}]


def pop_sounds() -> list:
    out, STATE["sounds"] = STATE["sounds"], []
    return out


def pop_event():
    """-> (имя, вероятность) один раз, дальше None до нового события."""
    ev = STATE.get("event")
    STATE["event"] = None
    return ev

_buf = np.zeros(0, dtype=np.float32)
_bufs = {}            # src -> буфер в долях [-1, 1]
_fresh = {}           # src -> сколько новых отсчётов с прошлого окна
_lock = threading.Lock()
_worker = None
_model = None
_labels: list = []

# классы AudioSet, означающие «это голос человека». Пение сюда НЕ входит
# осознанно: подпевающий телевизор не должен заводить профиль в карте.
_SPEECH = ("speech", "conversation", "narration", "monologue",
           "male speech", "female speech", "child speech", "babbling",
           "speech synthesizer")

# по-русски — только то, что реально бывает у компьютера. Остальное
# отдаём английской меткой: честнее, чем выдумывать перевод.
_RU = {
    "computer keyboard": "клавиатура", "typing": "печатает",
    "keyboard (musical)": "синтезатор", "mouse": "мышь",
    "mouse click": "щелчок мыши", "click": "щелчок",
    "music": "музыка", "singing": "пение", "musical instrument": "инструмент",
    "speech": "речь", "conversation": "разговор", "laughter": "смех",
    "cough": "кашель", "sneeze": "чих", "breathing": "дыхание",
    "sigh": "вздох", "whistling": "свист", "humming": "мычит мотив",
    "dog": "собака", "bark": "лай", "cat": "кошка", "meow": "мяу",
    "bird": "птица", "vehicle": "машина", "car": "машина",
    "siren": "сирена", "door": "дверь", "knock": "стук",
    "telephone": "телефон", "telephone bell ringing": "звонок телефона",
    "alarm": "будильник", "water": "вода", "dishes, pots, and pans": "посуда",
    "cutlery, silverware": "посуда", "chewing, mastication": "жуёт",
    "drinking, sipping": "пьёт", "television": "телевизор",
    "radio": "радио", "fan": "вентилятор", "air conditioning": "кондиционер",
    "printer": "принтер", "silence": "тишина", "white noise": "шум",
    "static": "шум", "wind": "ветер", "rain": "дождь", "thunder": "гром",
    "applause": "аплодисменты", "footsteps": "шаги", "clapping": "хлопки",
    "writing": "пишет", "scissors": "ножницы", "tools": "инструмент",
    "drill": "дрель", "sawing": "пила", "hammer": "молоток",
    # БИТБОКС (2026-08-15, владелец: «увидеть, какие я звуки в битбоксе
    # использую»). AudioSet знает и сам битбокс, и его составные части —
    # им просто не хватало русских имён, чтобы попасть в панель и в промпт.
    "plop": "бульк", "chop": "чоп", "thud": "бух", "thump, thud": "бух",
    "squish": "хлюп", "slap, smack": "шлеп",
    "burping, eructation": "отрыжка", "gargling": "полоскание горла",
    "cacophony": "гвалт", "noise": "шум", "animal": "животное",
    "domestic animals, pets": "домашнее животное",
    "wild animals": "дикое животное", "growling": "рычание",
    "roar": "рёв", "purr": "мурчание", "trill": "трель",
    "hiss": "шипение", "sizzle": "шипение", "whoosh, swoosh": "шелест",
    "air": "воздух", "buzz": "жужжание", "hum": "гул", "snap": "щелчок",
    "finger snapping": "щелчок пальцами", "whistling": "свист",
    "beatboxing": "бит-бокс", "drum": "барабан", "drum kit": "ударные",
    "bass drum": "бочка", "snare drum": "малый барабан",
    "hi-hat": "хай-хэт", "cymbal": "тарелка", "percussion": "перкуссия",
    "drum roll": "дробь", "tabla": "табла", "rimshot": "римшот",
    "scratching (performance technique)": "скретч",
    # ═══ ЖИВОТНЫЕ И ОКРУЖЕНИЕ (27.08.2026, владелец: «добавь разметки
    # животных и окружения… больше получать разных меток, а не только
    # машина или музыка»). PANNs знает 527 классов AudioSet, и добрая
    # половина из них — звери, птицы, погода, дом. Им просто не хватало
    # русских имён: без перевода метка уезжала английской строкой либо
    # подбиралась подстрокой наугад. ═══
    # звери
    "cow": "корова", "moo": "мычание", "cattle, bovinae": "коровы",
    "horse": "лошадь", "neigh, whinny": "ржание", "clip-clop": "цокот копыт",
    "pig": "свинья", "oink": "хрюканье", "goat": "коза", "bleat": "блеяние",
    "sheep": "овца", "donkey, ass": "осёл", "rodents, rats, mice": "грызуны",
    "squeak": "писк", "mouse (animal)": "мышь", "hamster": "хомяк",
    "rabbit": "кролик", "bat": "летучая мышь", "whimper (dog)": "скулёж",
    "howl": "вой", "yip": "тявканье", "bow-wow": "гав-гав",
    "growling (dog)": "рычание", "caterwaul": "кошачий вопль",
    "hiss (cat)": "шипение кошки", "livestock, farm animals": "скот",
    # птицы
    "bird vocalization, bird call, bird song": "пение птицы",
    "chirp, tweet": "чирикание", "squawk": "клёкот", "pigeon, dove": "голубь",
    "coo": "воркование", "crow": "ворона", "caw": "карканье",
    "owl": "сова", "hoot": "уханье", "gull, seagull": "чайка",
    "chicken, rooster": "курица", "cluck": "кудахтанье",
    "crowing, cock-a-doodle-doo": "кукареканье", "turkey": "индюк",
    "gobble": "клокотание", "duck": "утка", "quack": "кряканье",
    "goose": "гусь", "honk": "гоготание", "bird flight, flapping wings": "хлопанье крыльев",
    # мелкая живность
    "insect": "насекомое", "cricket": "сверчок", "mosquito": "комар",
    "fly, housefly": "муха", "buzz (insect)": "жужжание насекомого",
    "bee, wasp, etc.": "пчела", "frog": "лягушка", "croak": "кваканье",
    "snake": "змея", "rattle": "трещотка", "whale vocalization": "кит",
    # погода и улица
    "rain on surface": "дождь по крыше", "raindrop": "капли дождя",
    "thunderstorm": "гроза", "wind noise (microphone)": "ветер в микрофон",
    "rustling leaves": "шелест листвы", "howl (wind)": "вой ветра",
    "gust of wind": "порыв ветра", "stream": "ручей", "waterfall": "водопад",
    "ocean": "океан", "waves, surf": "прибой", "splash, splatter": "плеск",
    "gurgling": "журчание", "fire": "огонь", "crackle": "потрескивание",
    "hail": "град", "sonar": "сонар",
    # «gunfire» содержит «fire» и переводилось «огнём» (06.09.2026, живой
    # случай: тишина в наушниках — «огонь»); теперь своё слово
    "gunshot, gunfire": "выстрел", "machine gun": "пулемёт",
    # инструменты и природа (журнал аниме 06.09: «Guitar» шёл по-английски)
    "guitar": "гитара", "acoustic guitar": "гитара", "electric guitar": "электрогитара",
    "bass guitar": "бас", "piano": "пианино", "electric piano": "пианино",
    "organ": "орган", "violin, fiddle": "скрипка", "cello": "виолончель",
    "orchestra": "оркестр", "choir": "хор", "synthesizer": "синтезатор",
    "harp": "арфа", "flute": "флейта", "trumpet": "труба", "saxophone": "саксофон",
    "bell": "колокол", "church bell": "колокол", "wind chime": "колокольчики",
    "fire": "огонь", "crackle": "потрескивание", "fire crackle": "костёр",
    "wood": "дерево", "chirp tone": "писк",
    "fusillade": "стрельба", "artillery fire": "артиллерия",
    "cap gun": "пугач", "fireworks": "фейерверк", "firecracker": "петарда",
    # дом и вещи
    "door": "дверь", "slam": "хлопок двери", "creak": "скрип",
    "squeal": "визг", "cupboard open or close": "шкаф",
    "drawer open or close": "ящик", "microwave oven": "микроволновка",
    "blender": "блендер", "vacuum cleaner": "пылесос",
    "washing machine": "стиральная машина", "toilet flush": "смыв",
    "sink (filling or washing)": "раковина", "bathtub (filling or washing)": "ванна",
    "electric shaver, electric razor": "бритва", "hair dryer": "фен",
    "zipper (clothing)": "молния", "velcro, hook and loop fastener": "липучка",
    "coin (dropping)": "монета", "packing tape, duct tape": "скотч",
    "keys jangling": "звон ключей", "scissors": "ножницы",
    "electric toothbrush": "зубная щётка", "frying (food)": "жарит",
    "boiling": "кипит", "chopping (food)": "режет",
    "glass": "стекло", "chink, clink": "звон стекла", "shatter": "звон осколков",
    "clock": "часы", "tick": "тиканье", "tick-tock": "тик-так",
    "doorbell": "дверной звонок", "ding-dong": "динь-дон",
    "buzzer": "зуммер", "smoke detector, smoke alarm": "датчик дыма",
    "fire alarm": "пожарная сигнализация",
    # техника и транспорт (частное — раньше всё сваливалось в «машину»)
    "car passing by": "машина проехала", "car alarm": "автосигнализация",
    "power windows, electric windows": "стеклоподъёмник",
    "skidding": "визг шин", "tire squeal": "визг шин",
    "engine starting": "завёлся двигатель", "idling": "работает на холостых",
    "accelerating, revving, vroom": "газует", "motorcycle": "мотоцикл",
    "bus": "автобус", "truck": "грузовик", "train": "поезд",
    "train horn": "гудок поезда", "railroad car, train wagon": "вагон",
    "subway, metro, underground": "метро", "aircraft": "самолёт",
    "helicopter": "вертолёт", "fixed-wing aircraft, airplane": "самолёт",
    "bicycle": "велосипед", "skateboard": "скейт", "boat, water vehicle": "лодка",
    "sailboat, sailing ship": "парусник", "chainsaw": "бензопила",
    "lawn mower": "газонокосилка", "jackhammer": "отбойный молоток",
    "power tool": "электроинструмент",
    # человек
    "crying, sobbing": "плач", "baby cry, infant cry": "плач ребёнка",
    "screaming": "крик", "yell": "вопль", "shout": "окрик",
    "children shouting": "детские крики", "whispering": "шёпот",
    "snoring": "храп", "hiccup": "икота", "burp": "отрыжка",
    "gasp": "вздох испуга", "groan": "стон", "grunt": "кряхтение",
    "chatter": "болтовня", "babbling": "лепет", "cheering": "ликование",
    "booing": "освистывание", "crowd": "толпа", "hubbub, speech noise": "гул голосов",
    "run": "бег", "walk, footsteps": "шаги", "shuffle": "шарканье",
}

# ПОРЯДОК ПОИСКА — ОТ ДЛИННОГО К КОРОТКОМУ. Подбор по подстроке шёл в
# порядке записи словаря, и короткий ключ побеждал длинный: «car» стоит
# выше, поэтому «car alarm» становилось просто «машиной», а «bird flight,
# flapping wings» — «птицей». Сортируем один раз при загрузке: сначала
# самые частные ключи, общие остаются на подхвате (27.08.2026).
_RU_ORDER = sorted(_RU.items(), key=lambda kv: -len(kv[0]))


def enabled() -> bool:
    return bool(CFG.get("hearing.enabled", True)) and not STATE["off"]


def _ru(label: str) -> str:
    low = label.lower()
    if low in _RU:
        return _RU[low]
    for k, v in _RU_ORDER:          # от частного к общему, см. _RU_ORDER
        if k in low:
            return v
    return label


def _load():
    """Ленивая загрузка: модель поднимается при первом звуке, а не на старте —
    старт и так длинный, а уши нужны только когда кто-то шумит."""
    global _model, _labels
    try:
        from panns_inference import AudioTagging, labels
        dev = str(CFG.get("hearing.device", "cpu"))
        # ПОД ОБЩИМ ЗАМКОМ ЗАГРУЗКИ (2026-08-14). Уши — тоже торч-модель, и
        # на старте они въезжают в память ровно тогда же, когда озвучка
        # компилируется, а слух поднимает GigaAM. Тройное совпадение и дало
        # три access violation подряд. Замок TORCH_GATE придуман для этого.
        from anamorf.torch_gate import TORCH_GATE
        with TORCH_GATE:
            _model = AudioTagging(checkpoint_path=None, device=dev)
        _labels = list(labels)
        STATE["ready"] = True
        log.info("Уши: PANNs загружены (%s, %d классов)", dev, len(_labels))
    except ImportError:
        STATE["off"] = True
        log.info("Уши: panns_inference не установлен — работаю без меток "
                 "звуков (ставится сам при следующем запуске)")
    except Exception as e:
        STATE["off"] = True
        log.warning("Уши: не поднялись (%s) — работаю без меток звуков", e)


def _resample(a: np.ndarray) -> np.ndarray:
    """16 -> 32 кГц линейной интерполяцией. Для классификатора событий
    этого достаточно: он смотрит на форму спектра, а не на тембр."""
    n = int(len(a) * SR_MODEL / SR_IN)
    if n < 2:
        return a
    return np.interp(np.linspace(0, len(a) - 1, n),
                     np.arange(len(a)), a).astype(np.float32)


def _classify(chunk: np.ndarray):
    x = _resample(chunk)[None, :]
    # ЭМБЕДДИНГ БОЛЬШЕ НЕ ВЫБРАСЫВАЕТСЯ (2026-08-15, цель владельца:
    # «кластеризация звуков»). Второй выход PANNs — отпечаток ЗВУКА,
    # 2048 чисел; он уезжает в карту звуков (anamorf/sound_map.py), где
    # повторяющиеся источники дома получают имена, как голоса в карте.
    clipwise, _emb = _model.inference(x)
    probs = np.asarray(clipwise[0])
    globals()["_last_emb"] = _emb
    idx = probs.argsort()[::-1][:6]
    tags = [(_labels[i], float(probs[i])) for i in idx
            if probs[i] >= float(CFG.get("hearing.min_conf", 0.12))]
    speech = 0.0
    for name, p in ((_labels[i].lower(), float(probs[i]))
                    for i in probs.argsort()[::-1][:25]):
        if any(k in name for k in _SPEECH):
            speech = max(speech, p)
    return tags, speech


def _loop():
    _load()
    if STATE["off"]:
        return
    while True:
        # окно/шаг — из пульта: для ролика 1.0/0.5 (события длиной в
        # полсекунды, крик и смех, не тонут в двухсекундном окне речи)
        need = int(float(CFG.get("hearing.window_s", WINDOW_S)) * SR_IN)
        time.sleep(float(CFG.get("hearing.every_s", EVERY_S)))
        if not enabled():
            continue
        hop = int(float(CFG.get("hearing.every_s", EVERY_S)) * SR_IN * 0.8)
        with _lock:
            todo = []
            for _s, _b in list(_bufs.items()):
                if len(_b) < need // 2 or _fresh.get(_s, 0) < hop:
                    continue
                _fresh[_s] = 0
                todo.append((_s, _b[-need:].copy()))
        if not todo:
            continue
        # «главный» канал для общего состояния (речь ли сейчас) — самый громкий
        todo.sort(key=lambda t: -float(np.sqrt(np.mean(t[1] ** 2))))
        for _src_i, chunk in todo[1:]:
            try:
                _tg, _sp = _classify(chunk)
                _feed_sounds(_spectral_veto(_tg, chunk),
                             float(np.sqrt(np.mean(chunk ** 2))), _src_i)
            except Exception as _e_i:
                log.debug("уши (%s) споткнулись: %s", _src_i, _e_i)
        src_main, chunk = todo[0]
        try:
            tags, speech = _classify(chunk)
            STATE.update(tags=tags, speech=speech, ts=time.time(), src=src_main)
            try:
                from anamorf import sound_map
                _top_ru = _ru(tags[0][0]) if tags else ""
                _src = sound_map.hear(
                    np.asarray(globals().get("_last_emb")).ravel(),
                    _top_ru, speech)
                if _src:
                    STATE["source"] = _src
            except Exception:
                pass
            # ═══ CLAP — ВТОРОЕ МНЕНИЕ СО СВОИМИ МЕТКАМИ (2026-08-15) ═══
            # Живой вечер битбокса: губная трель у AudioSet — «собака»,
            # трещётка — «машина», горловая бочка — «музыка». Словарь у
            # PANNs фиксированный, вокальной перкуссии в нём нет. CLAP
            # сравнивает звук с ЛЮБЫМ текстом — метки задаются словами в
            # config (hearing.clap.labels). Уверенный ответ CLAP встаёт
            # ПЕРВЫМ в картину звука; не уверен — всё как было. Дорогой
            # (сотни мс), поэтому не чаще clap_every_s и только на звуке.
            try:
                from anamorf import clap_ears
                _now = time.time()
                if (clap_ears.enabled()
                        and float(np.sqrt(np.mean(chunk ** 2))) > 0.01
                        and _now - STATE.get("clap_ts", 0)
                            >= float(CFG.get("hearing.clap.every_s", 2.0))):
                    STATE["clap_ts"] = _now
                    if not clap_ears.STATE["ready"]:
                        clap_ears.warm()
                    else:
                        best = clap_ears.classify(chunk)
                        picked = [(en, p) for ru, en, ono, p in best
                                  if p >= float(CFG.get(
                                      "hearing.clap.min", 0.45))
                                  and ru not in ("речь", "музыка")]
                        STATE["clap_tags"] = best
                        if picked:
                            # ru/ono кладём в словари налету, чтобы
                            # _feed_sounds показал их по-человечески
                            for ru, en, ono, p in best:
                                _RU.setdefault(en.lower(), ru)
                                if ono:
                                    _ONOMA.setdefault(en.lower(), ono)
                            tags = picked + [t for t in tags
                                             if t[0].lower() not in
                                             {e.lower() for e, _ in picked}]
            except Exception as _ce:
                log.debug("CLAP пропущен: %s", _ce)
            try:
                _feed_sounds(_spectral_veto(tags, chunk),
                             float(np.sqrt(np.mean(chunk ** 2))), src_main)
            except Exception:
                pass
            # разовые события: чих/кашель/крик — с порогом из таблицы
            try:
                for name, p in tags:
                    low = str(name).lower()
                    for key, (ru, thr) in _EVENTS.items():
                        if key in low and p >= thr:
                            STATE["event"] = (ru, float(p))
                            break
            except Exception:
                pass
            # ТЕМП ПЕЧАТИ ПО ЗВУКУ (2026-08-15, владелец: «когда я печатаю,
            # по звуку определить примерно скорость печати»). Нажатие — это
            # транзиент: резкий скачок огибающей. Когда уши слышат
            # клавиатуру, считаем скачки в окне и делим на секунды — вот и
            # нажатия/сек. Уходит фоном в промпт: «печатает, ~6 наж/с» —
            # и она может отреагировать («строчишь как из пулемёта»).
            try:
                kbd = any(any(k in str(t).lower() for k in
                              ("keyboard", "typing", "click"))
                          for t, _ in tags)
                if kbd:
                    env = np.abs(chunk)
                    # разрешение огибающей ~2.5мс: на 400 точках соседние
                    # щелчки при быстрой печати сливались, и темп занижался
                    # вдвое (поймано стендом: сцена 8 наж/с давала 3.8)
                    k = max(1, len(env) // 1600)
                    env = env[:len(env) - len(env) % k].reshape(-1, k).max(1)
                    d = np.diff(env)
                    thr_ = float(d.std()) * 2.5 + 1e-6
                    peaks = 0
                    armed = True
                    for v in d:
                        if armed and v > thr_:
                            peaks += 1
                            armed = False
                        elif v < 0:
                            armed = True
                    cps = peaks / WINDOW_S
                    STATE["typing_cps"] = round(
                        0.6 * STATE["typing_cps"] + 0.4 * cps, 1)
                else:
                    STATE["typing_cps"] = round(STATE["typing_cps"] * 0.6, 1)
            except Exception:
                pass
            # ДИСТАНЦИЯ НА СЛУХ (2026-08-15, владелец: «услышать звук от
            # телефона в другой комнате и примерное расстояние»). По одному
            # микрофону метры не меряются честно — но КЛАСС дистанции
            # слышен и человеку, и спектру: далёкий/застенный звук теряет
            # верхи (стены и воздух гасят их первыми) и тонет в
            # реверберации. Оцениваем долю энергии выше 2 кГц и общий
            # уровень: ярко и громко — рядом; глухо и тихо — «где-то
            # далеко, как из другой комнаты». Это описание, а не линейка.
            try:
                x = _resample(chunk)
                spec = np.abs(np.fft.rfft(x[-SR_MODEL:]))
                fr = np.fft.rfftfreq(min(len(x), SR_MODEL), 1.0 / SR_MODEL)
                hi = float(spec[fr > 2000].sum())
                tot = float(spec.sum()) + 1e-9
                bright = hi / tot
                loud = float(np.sqrt(np.mean(x ** 2)))
                if loud < 0.003:
                    STATE["dist"] = ""
                elif bright < 0.12 and loud < 0.03:
                    STATE["dist"] = "приглушённо, будто из другой комнаты"
                elif loud < 0.02:
                    STATE["dist"] = "негромко, в стороне"
                else:
                    STATE["dist"] = "рядом"
            except Exception:
                pass
        except Exception as e:
            log.debug("уши споткнулись: %s", e)


def feed(pcm, src=""):
    """Кормить из того же места, что и voiceprint — из аудиоцикла."""
    global _buf, _worker
    if not enabled():
        return
    if src:
        STATE["src"] = src
    STATE["scale"] = 1.0
    try:
        _raw = np.asarray(pcm)
        a = _raw.astype(np.float32).ravel()
        # ОДНА ШКАЛА ДЛЯ ВСЕХ (06.09.2026): int16 из микрофона/петли и
        # float из шумодава сходятся в один буфер — в долях [-1, 1], как
        # обучен классификатор. Иначе уровень тишины «прыгал» 0.00007 ↔ 1600.
        if _raw.dtype.kind in "iu":
            a = a / 32768.0
    except Exception:
        return
    if not a.size:
        return
    # копия в буфер узнавания музыки (anamorf/music_id.py, 12 с на канал)
    try:
        from anamorf import music_id as _mid
        _mid.feed(a, src or "mic")
    except Exception:
        pass
    with _lock:
        _k = src or "mic"
        _keep = int(max(WINDOW_S, float(CFG.get("hearing.window_s", WINDOW_S))) * SR_IN * 1.5)
        _prev = _bufs.get(_k)
        _bufs[_k] = (np.concatenate([_prev, a]) if _prev is not None and _prev.size else a)[-_keep:]
        _fresh[_k] = _fresh.get(_k, 0) + a.size
        _buf = _bufs[_k]
    # старт под замком: два канала (петля и Discord) звали feed разом, и
    # уши поднимались дважды — две модели на видеокарте (журнал 18:30/18:31)
    with _lock:
        if _worker is None:
            _worker = threading.Thread(target=_loop, daemon=True, name="ears")
            _worker.start()


# звуки, которые чаще всего заводят фантомные «голоса» в карте. Живой
# случай дважды: «Голос 4» из клавиатуры (153 срабатывания, 103-400 Гц)
# 13 августа и «Голос 2» из неё же (112 раз, 109-115 Гц) 15 августа.
_MECH = ("computer keyboard", "typing", "mouse", "click", "knock",
         "tap", "clicking",
         # БИТБОКС — НЕ НОВЫЙ ЧЕЛОВЕК (2026-08-15, живой вечер: вокальная
         # перкуссия владельца завела в карте голосов «Голос 4» на 75
         # точек). Это голос, но не РЕЧЬ: профиль из бочек и трещоток
         # только мусорит карту и ворует точки у настоящих людей.
         "beatboxing", "drum", "bass drum", "snare", "hi-hat", "cymbal",
         "percussion", "burping")


def speech_ok() -> bool:
    """ПРЕДОХРАНИТЕЛЬ ДЛЯ КАРТЫ ГОЛОСОВ: похоже ли, что сейчас говорит
    человек. Отвечаем ДА, когда ушей нет или они молчат дольше трёх секунд —
    правило «не уверен, значит не мешай»: лучше лишний отпечаток, чем
    молча потерять живую речь.

    ВЕТО МЕХАНИКИ (2026-08-15, владелец: «звук клавиатуры ОПЯТЬ почему-то
    записывается как голос»). Прошлый порог не спасал вот от чего: окно
    классификации — две секунды. Человек договорил фразу, потянулся к
    клавишам — в окне ЕЩЁ живёт хвост его речи (speech выше порога), а в
    микрофон УЖЕ идут щелчки, и они честно получают эмбеддинг. Так у
    клавиатуры второй раз завёлся профиль. Лечится не порогом, а ВЕТО:
    когда уши уверенно слышат механику (клавиатура, мышь, стук) ГРОМЧЕ,
    чем речь, — отпечаток не считаем, каким бы ни был хвост речи в окне.
    Живую речь это не режет: у говорящего человека speech стабильно выше
    меток механики."""
    if not enabled() or not STATE["ready"]:
        return True
    if time.time() - STATE["ts"] > 3.0:
        return True
    sp = float(STATE["speech"])
    mech = 0.0
    try:
        for name, p in STATE["tags"]:
            low = str(name).lower()
            if any(k in low for k in _MECH):
                mech = max(mech, float(p))
    except Exception:
        pass
    if mech >= float(CFG.get("hearing.mech_veto", 0.25)) and mech >= sp:
        return False
    return sp >= float(CFG.get("hearing.speech_min", 0.15))


def now() -> list:
    """Что слышно прямо сейчас: [(имя по-русски, вероятность)]."""
    if not STATE["ready"] or time.time() - STATE["ts"] > 8.0:
        return []
    out, seen = [], set()
    for name, p in STATE["tags"]:
        ru = _ru(name)
        if ru in seen:
            continue
        seen.add(ru)
        out.append((ru, p))
    return out[:3]


def context_line() -> str:
    """Строка для промпта. Формулировка важна: это ФОН, а не обращение.
    Раньше подобные вещи модель принимала за задание и начинала их
    комментировать — здесь прямо сказано, что реагировать не обязательно."""
    tags = now()
    if not tags:
        return ""
    body = ", ".join(t for t, _ in tags)
    if STATE.get("typing_cps", 0) >= 2 and any(
            k in str(t).lower() for t, _ in tags
            for k in ("keyboard", "typing")):
        body += f" (печатает, ~{STATE['typing_cps']:.0f} наж/с)"
    if STATE.get("dist"):
        body += f" ({STATE['dist']})"
    # крик — отдельная ремарка: на повышенных тонах говорят НЕ с ассистентом
    if any("крик" == _EVENTS.get(k, ("",))[0]
           for t, _ in tags for k in _EVENTS if k in str(t).lower()):
        body += ("; кто-то повышает голос — это почти наверняка не "
                 "обращение к тебе, не вмешивайся без причины")
    return ("Фоном сейчас слышно: " + body + ". Это просто обстановка "
            "вокруг, а не обращение к тебе и не задание. Можешь опереться "
            "на это, если к слову придётся, — а можешь не заметить, как "
            "человек не замечает гула холодильника.")
