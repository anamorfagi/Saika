# -*- coding: utf-8 -*-
"""ВТОРОЕ УХО — WHISPER ПОВЕРХ БЫСТРОГО ДВИЖКА (2026-09-06).

Замер на орущем начале ролика ДНК (0–22 с): GigaAM CTC находит 48% слов
ютуба, faster-whisper large-v3-turbo — 80% и слышит «Где много денег-то
было», как ютуб. Но whisper на коротких кусках выдумывает («Добро
пожаловать в Казахстан!», «Субтитры сделал DimaTorzok») и ставит
звёздочки в мате. Поэтому он НЕ первый: облачко рождает быстрый CTC,
а whisper переслушивает кусок следом и, если услышал заметно больше и
прошёл предохранители, правит облачко (событие stt_fix, как раньше).

Предохранители:
  • кусок короче stt.second.min_s — не трогаем (там whisper и врёт);
  • чёрный список фраз-«водяных знаков» whisper;
  • повторы (compression) и низкая уверенность декодера — отбой;
  • принимаем только если слов стало заметно больше или текст был пустой.
"""
import logging
import re
import threading
import time

import numpy as np

from anamorf.config import CFG

log = logging.getLogger("saika.second")

_BAD = ("субтитр", "dimatorzok", "добро пожаловать", "спасибо за просмотр",
        "продолжение следует", "редактор", "подписывайтесь", "аплодисменты",
        "музыка", "смех", "thank you", "you", "конец",
        # галлюцинации whisper на музыке/шуме (07.09): «For more information,
        # visit www.fema.gov», «We'll be right back», ссылки
        "www.", ".gov", ".com", "for more information", "we'll be right back",
        "посетите", "дополнительной информации")
_LOCK = threading.Lock()
STATE = {"n": 0, "ok": 0, "ms": 0, "engine": "", "err": ""}
_PK = {"m": None, "loading": False}


def _parakeet():
    """NVIDIA Parakeet-TDT 0.6B v3 через onnx-asr: 25 языков, без языковой
    модели — не выдумывает фразы. Замер 2026-09-06: крик 0–22 с — 84.8%
    (whisper 80%, GigaAM 48%); диалог 3 мин — 85.8% (GigaAM 92.8%).
    Поэтому он второе ухо, а не первое. Грузится ~70 с — в фоне."""
    if _PK["m"] is not None:
        return _PK["m"]
    if _PK["loading"]:
        return None
    _PK["loading"] = True
    try:
        import onnx_asr
        t0 = time.monotonic()
        _PK["m"] = onnx_asr.load_model(str(CFG.get("stt.second.model", "nemo-parakeet-tdt-0.6b-v3")))
        log.info("Второе ухо: parakeet поднят за %.0fс", time.monotonic() - t0)
    except Exception as e:
        STATE["err"] = str(e)[:160]
        log.warning("Второе ухо: parakeet не поднялся (%s) — беру whisper", e)
    finally:
        _PK["loading"] = False
    return _PK["m"]


def warm(stt=None):
    if CFG.get("stt.second.engine", "parakeet") == "parakeet":
        threading.Thread(target=_parakeet, daemon=True, name="second-warm").start()
    elif stt is not None:
        def _w():
            try:
                t0 = time.monotonic()
                stt._get("faster_whisper").load()
                log.info("Второе ухо: whisper поднят за %.1fс", time.monotonic() - t0)
            except Exception as e:
                log.warning("Второе ухо: whisper не поднялся (%s)", e)
        threading.Thread(target=_w, daemon=True, name="second-warm").start()


def _words(t):
    return [w for w in re.findall(r"[а-яёa-z]+", (t or "").lower()) if len(w) > 1]


def _bad(t: str) -> str:
    low = (t or "").lower()
    for b in _BAD:
        if b in low:
            return b
    ws = _words(t)
    # ПОВТОР В ЛЮБОЙ ПИСЬМЕННОСТИ (06.09.2026, «このように、» × 80): старый
    # счётчик слов знал только кириллицу/латиницу. Сжимаемость текста —
    # универсальна: у живой речи zlib даёт ≥0.45 от длины, у зацикленной
    # модели — меньше 0.25.
    try:
        import zlib
        _t2 = re.sub(r"\s", "", t or "")
        if len(_t2) >= 30:
            _b = _t2.encode("utf-8")
            if len(zlib.compress(_b)) / max(1, len(_b)) < 0.25:
                return "зацикленный повтор"
    except Exception:
        pass
    # «ВЫСТРЕЛЫ», «[МУЗЫКА]» — субтитровая ремарка целиком капсом
    _letters = re.sub(r"[^А-ЯЁа-яёA-Za-z]", "", t or "")
    if len(_letters) >= 3 and _letters.upper() == _letters:
        return "ремарка капсом"
    if len(ws) >= 4 and len(set(ws)) <= len(ws) // 3:
        return "повтор"
    # «ААААААААА…» на крике (живой случай 06.09) — не слово
    if any(len(w) > 20 or re.search(r"(.)\1{3,}", w) for w in ws):
        return "тянутая каша"
    # «ДРУК ДРУК ДРУК» (живой случай 06.09): одно слово трижды подряд — заикание модели
    for i in range(len(ws) - 2):
        if ws[i] == ws[i + 1] == ws[i + 2]:
            return "заикание"
    return ""


def enabled() -> bool:
    return bool(CFG.get("stt.second.enabled", True))


def _lang_ctx(eng, x, sr, txt):
    """Контекст языка канала: (текст, почему). Пусто — оставить как есть."""
    import collections
    now = time.time()
    STATE["forced"] = False
    lg0 = str(getattr(eng, "last_lang", None) or "")
    lp0 = float(getattr(eng, "last_lang_p", 0.0) or 0.0)
    fl = [z for z in (STATE.get("fl") or []) if now - z[0] < float(CFG.get("stt.second.lang_ctx_s", 45))]
    if lg0 and lg0 not in ("ru", "uk", "be") and lp0 >= 0.75:
        fl.append((now, lg0))
    STATE["fl"] = fl[-8:]
    if not fl or (lg0 not in ("", "ru", "uk", "be")) or lp0 >= float(CFG.get("stt.second.lang_ctx_p", 0.7)):
        return "", ""
    L, n = collections.Counter(l for _t, l in fl).most_common(1)[0]
    if n < 2:
        return "", "контекст слаб"
    pL = float((getattr(eng, "last_lang_probs", None) or {}).get(L, 0.0) or 0.0)
    if pL < 0.10 and lp0 >= 0.5:
        return "", "контекст %s не подтверждён (%.2f)" % (L, pL)
    t0 = time.monotonic()
    txt2 = eng.transcribe(x, sr, language=L) or ""
    wp2 = [(str(w.get("w", "")), float(w.get("p", 0.0))) for w in (getattr(eng, "last_words", None) or [])]
    avg2 = (sum(p for _w, p in wp2) / len(wp2)) if wp2 else 0.0
    ms = int((time.monotonic() - t0) * 1000)
    if len(wp2) >= 2 and avg2 >= float(CFG.get("stt.second.lang_ctx_word_p", 0.55)) and not _bad(txt2):
        log.info("Язык по контексту %s (ru %.2f, %s %.2f, слова %.2f, %d мс): %r -> %r", L, lp0, L, pL, avg2, ms, txt[:40], txt2[:60])
        STATE["lang"] = L; STATE["wprob"] = wp2; STATE["forced"] = True
        eng.last_lang = L
        return txt2, "контекст %s" % L
    log.info("Язык по контексту %s не подтвердился (слова %.2f, %d мс): %r", L, avg2, ms, txt2[:40])
    return "", ""


def listen(stt, pcm16: np.ndarray, sr: int, first_text: str, bconf=None, whole: bool = False):
    """-> (новый текст или "", причина). Зовётся из фонового потока."""
    if not enabled():
        return "", "выкл"
    sec = len(pcm16) / float(sr or 16000)
    if sec < float(CFG.get("stt.second.min_s", 1.5)):
        return "", "коротко"
    t0 = time.monotonic()
    txt = ""
    pk = _parakeet() if CFG.get("stt.second.engine", "parakeet") == "parakeet" else None
    if pk is not None:
        try:
            a = np.asarray(pcm16, np.int16).astype(np.float32) / 32768.0
            with _LOCK:
                txt = pk.recognize(a, language=str(CFG.get("stt.language", "ru") or "ru")) or ""
            STATE["engine"] = "parakeet"
        except Exception as e:
            return "", "parakeet: %s" % str(e)[:80]
    else:
        try:
            eng = stt._get("faster_whisper")
            eng.load()
            x = pcm16
            try:
                # ФРОНТЕНД ТОЛЬКО ДЛЯ WHISPER (замер 06.09.2026, tools/fe_bench.py):
                # компрессор+лимитер на крике 0-22 с: whisper 75.8 -> 84.8%,
                # GigaAM 66.7 -> 69.7 (шум измерения). Whisper любит ровный уровень.
                if CFG.get("stt.second.prepare", True):
                    from anamorf.stt import frontend as _fe
                    x = _fe.prepare(pcm16, sr, CFG.get("stt.frontend", {}) or {})
            except Exception:
                x = pcm16
            # ЧУЖОЙ ЯЗЫК ТОЖЕ ПИШЕМ (владелец: «в игре много женских
            # персонажей, английская озвучка — хули оно не пишет»). GigaAM
            # знает только русский; когда его чтение неуверенное или
            # пустое, whisper слушает с автоопределением языка.
            # АВТОЯЗЫК ВСЕГДА (06.09.2026, «китаец спизданул — ни разу не
            # прописалось»): первое ухо на чужом языке уверенно пишет русскую
            # кашу («Забу, бляь, иди спи») с CTC ≥0.5, и по старому правилу
            # автоопределение не включалось. Цена — ~30 мс на кусок.
            _auto = bool(CFG.get("stt.second.auto_lang", True))
            with _LOCK:
                STATE["_x"] = x
                txt = eng.transcribe(x, sr, language=("auto" if _auto else "cfg")) or ""
                STATE["lang"] = getattr(eng, "last_lang", None)
                # уверенность каждого слова (word_conf в настройках whisper):
                # только уверенные слова имеют право дописаться в облачко
                STATE["wprob"] = [(str(w.get("w", "")), float(w.get("p", 0.0)))
                                  for w in (getattr(eng, "last_words", None) or [])]
            STATE["engine"] = "faster_whisper"
            # ═══ ЯЗЫКОВОЙ КОНТЕКСТ (07.09.2026, владелец: «бля, он испанский
            # врубил» — «Сабэскіе ауре ёо», «Я не кастельяно, потому что я
            # говорю о кастельянной»). Whisper на коротком испанском куске
            # неуверенно выбирает русский и пишет транслит. Если последние
            # полминуты в канале уверенно звучал чужой язык, а сейчас
            # whisper выбрал русский без уверенности — переслушиваем кусок с
            # принудительным языком контекста и берём, если слова уверенные.
            try:
                _txt2, _why2 = _lang_ctx(eng, x, sr, txt)
                if _txt2:
                    txt = _txt2
            except Exception:
                pass
        except Exception as e:
            return "", "нет whisper: %s" % e
    # чужой алфавит — модель уехала в другой язык на крике, не берём
    lat = len(re.findall(r"[a-z]", txt.lower())); cyr = len(re.findall(r"[а-яё]", txt.lower()))
    # ═══ ДРУГИЕ ПИСЬМЕННОСТИ (06.09.2026, владелец: «чувак на китайском
    # пизданул — транскриб вообще не прошёл»). Иероглифы, кана, хангыль,
    # арабица: если whisper уверен в языке — берём как есть.
    oth = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\u0600-\u06ff\u0e00-\u0e7f\u0900-\u097f]", txt))
    if oth >= 2 and oth > cyr:
        _lp = 0.0
        try:
            _lp = float(getattr(stt._get("faster_whisper"), "last_lang_p", 0.0) or 0.0)
        except Exception:
            pass
        if _lp >= 0.6 and not _bad(txt):
            STATE["n"] += 1; STATE["ok"] += 1
            STATE["ms"] = int((time.monotonic() - t0) * 1000)
            return txt.strip(), "язык %s" % (STATE.get("lang") or "?")
        return "", "чужая письменность без уверенности"
    if lat > cyr:
        # английская (и любая латинская) речь — целиком вместо каши GigaAM,
        # если whisper уверен в языке и в словах
        _lp = 0.0
        try:
            _lp = float(getattr(stt._get("faster_whisper"), "last_lang_p", 0.0) or 0.0)
        except Exception:
            pass
        ws2 = re.findall(r"[a-z']+", txt.lower())
        wp = STATE.get("wprob") or []
        avg = (sum(p for _w, p in wp) / len(wp)) if wp else 0.0
        # редкий язык на шумном куске — почти всегда галлюцинация
        # («Tá? Dá pra ter uma mulher» на стриме, 00:05): для языков вне
        # en/uk/de/fr/es/it требуем уверенность ≥0.85
        _lg = str(STATE.get("lang") or "")
        _need = 0.6 if _lg in ("en", "uk", "de", "fr", "es", "it") else 0.85
        if STATE.get("forced"):
            _lp = max(_lp, 0.8)   # язык взят из контекста канала, переслушано принудительно
        if len(ws2) >= 2 and _lp >= _need and avg >= 0.6 and not _bad(txt):
            STATE["n"] += 1; STATE["ok"] += 1
            STATE["ms"] = int((time.monotonic() - t0) * 1000)
            return txt.strip(), "язык %s" % (STATE.get("lang") or "?")
        return "", "не русский"
    STATE["n"] += 1
    STATE["ms"] = int((time.monotonic() - t0) * 1000)
    txt = txt.strip()
    why = _bad(txt)
    if why:
        return "", "мусор: " + why
    w1, w2 = _words(first_text), _words(txt)
    if not w2:
        return "", "пусто"
    # ПОД МУЗЫКОЙ — ТОЛЬКО ВТОРОЕ УХО (06.09.2026, владелец: «видишь, как
    # криво пишет» — в овале смешались русская каша первого уха и
    # английские слова whisper). Песня целиком берётся у whisper, если он
    # уверен в словах; сведение с первым ухом не делаем.
    if whole:
        wp = STATE.get("wprob") or []
        avg = (sum(p for _w, p in wp) / len(wp)) if wp else 0.0
        # под музыкой планка ниже (0.35): слова идут в овал песни, не в ленту,
        # и лучше неточные слова песни, чем пустой овал (07.09, «где слова?»)
        if avg >= float(CFG.get("stt.second.song_p", 0.35)) and len(w2) >= 2:
            STATE["ok"] += 1
            return txt.strip(), "песня целиком p=%.2f" % avg
        return "", "песня: whisper не уверен"
    # ═══ СВЕДЕНИЕ ПО УВЕРЕННОСТИ КАЖДОГО СЛОВА (06.09.2026) ═══
    # Стенд фильма «11 друзей Оушена», судья — parakeet (независим от обоих):
    # GigaAM 0.651, whisper 0.727, «взять whisper целиком при p≥0.7» 0.725,
    # сведение по словам 0.728. Сведение и точнее, и бережнее: совпавшие
    # слова остаются в форме первого уха (с растяжкой «Тааак»), спорные
    # берутся у того, кто увереннее (CTC против p слова), цифры whisper
    # («20010-го») не вытесняют слова первого уха («двухтысячно десятого»).
    try:
        if CFG.get("stt.second.rover", True) and w1 and STATE.get("wprob"):
            merged, ch = _rover(first_text, txt, STATE.get("wprob") or [],
                                bconf if bconf is not None else (STATE.get("bconf") or {}),
                                float(CFG.get("stt.second.take_p", 0.70)))
            if ch and merged.strip() and merged.strip() != first_text.strip():
                STATE["ok"] += 1
                STATE["take"] = STATE.get("take", 0) + 1
                return merged.strip(), "сведение %d" % ch
            if not ch:
                return "", "второе ухо согласно"
    except Exception as _te:
        log.debug("сведение не вышло: %s", _te)
    if CFG.get("stt.second.union", True) and w1:
        # ═══ СОЮЗ ДВУХ УШЕЙ (06.09.2026) ═══
        # Замер (tools/fe_bench.py, куски 2.5 с): крик 0-22 с — GigaAM 66.7%,
        # whisper 84.8%, ОБЪЕДИНЕНИЕ слов 81.8%→ (с учётом выравнивания);
        # диалог 22:00 — GigaAM 90.2%, whisper 87.4%, объединение 93.4%.
        # Ни один не лучше везде, вместе — лучше обоих. Первое ухо остаётся
        # основой (оно точнее на чистой речи), второе ДОПИСЫВАЕТ слова в
        # свои пропуски по выравниванию, а не переписывает фразу целиком.
        # уверенность слов ПЕРВОГО уха — из CTC (engines.LAST_WORDS того же
        # потока: второе ухо зовут сразу после первого чтения, до фона)
        merged, added = _union(first_text, txt, STATE.get("wprob") or [],
                               float(CFG.get("stt.second.word_conf_min", 0.75)),
                               bconf if bconf is not None else (STATE.get("bconf") or {}))
        if added <= 0:
            # УШИ РАЗОШЛИСЬ (владелец, 06.09: «пишет лишние слова — там сказали
            # „что это за штуковины такие"», а движок написал «Минутаки есть»
            # с уверенностью 0.8). Когда whisper уверенно слышит ДРУГИЕ слова
            # и ни одно не совпадает с первым ухом — это не факт, а спор;
            # облачко получает пометку «сомнительно» с версией второго уха.
            w2s = [w for w in txt.split() if _sure_word(w, STATE.get("wprob") or [],
                                                        float(CFG.get("stt.second.word_conf_min", 0.75)))]
            if len(w2s) >= 2 and not (set(_words(" ".join(w2s))) & set(w1)):
                STATE["doubt"] = " ".join(w2s)
                return "", "разошлись"
            return "", "второе ухо ничего не добавило"
        STATE["ok"] += 1
        return merged, "союз +%d" % added
    if w1 and len(w2) < len(w1) * float(CFG.get("stt.second.gain", 1.3)):
        return "", "не больше слов (%d -> %d)" % (len(w1), len(w2))
    STATE["ok"] += 1
    return txt, "ok"


def _rover(base: str, other: str, wprob, bconf, take_p: float = 0.7):
    """Пословное сведение двух ушей по уверенности -> (текст, сколько правок)."""
    import difflib
    bt, ot = base.split(), other.split()
    if not ot:
        return base, 0
    probs = {}
    for w, pr in (wprob or []):
        k = re.sub(r"[^а-яёa-z]", "", w.lower())
        if k:
            probs[k] = max(pr, probs.get(k, 0.0))
    def wp(w):
        ps = [probs.get(x, 0.0) for x in re.findall(r"[а-яёa-z]+", w.lower())]
        return (sum(ps) / len(ps)) if ps else 0.0
    bconf = bconf or {}
    def bp(w):
        v = bconf.get(re.sub(r"[^а-яёa-z]", "", w.lower()))
        return 0.5 if v is None else float(v)
    def key(w):
        return re.sub(r"[^а-яёa-z0-9]", "", w.lower())
    def caps(w):
        # «ВЫСТРЕЛЫ», «МУЗЫКА» — субтитровые ремарки whisper, не речь
        return len(key(w)) >= 3 and w.upper() == w and bool(re.search(r"[А-ЯЁA-Z]", w))
    ot = [w for w in ot if not caps(w)]
    if not ot:
        return base, 0
    if not bt:
        return (other if sum(wp(w) for w in ot) / len(ot) >= take_p else base), (1 if ot else 0)
    sm = difflib.SequenceMatcher(a=[key(w) for w in bt], b=[key(w) for w in ot], autojunk=False)
    out, ch = [], 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out.extend(bt[i1:i2])
        elif tag == "insert":
            ins = [w for w in ot[j1:j2] if wp(w) >= take_p and not _bad(w)]
            # одно короткое слово («и», «ну») не вставляем — чаще шум стыка
            if len(ins) == 1 and len(key(ins[0])) < 3:
                ins = []
            # вставка, повторяющая слова первого уха («терпила. Он терпило») —
            # это второе чтение того же, а не новые слова
            bk = {key(w) for w in bt}
            if ins and sum(1 for w in ins if key(w) in bk or any(
                    difflib.SequenceMatcher(None, key(w), k).ratio() >= 0.8 for k in bk)) * 2 >= len(ins):
                ins = []
            out.extend(ins); ch += len(ins)
        elif tag == "delete":
            mine = [w for w in bt[i1:i2] if bp(w) >= 0.5]
            ch += (i2 - i1) - len(mine)
            out.extend(mine)
        else:
            mine, theirs = bt[i1:i2], ot[j1:j2]
            mp = sum(bp(w) for w in mine) / len(mine)
            tp = sum(wp(w) for w in theirs) / len(theirs)
            digits = any(re.search(r"\d", w) for w in theirs) and not any(re.search(r"\d", w) for w in mine)
            # стенд фильма (судья parakeet): порог спора +0.05 → 0.728,
            # 0 → 0.731, −0.10 → 0.737, −0.20 → 0.740: уверенность CTC первого
            # уха завышена относительно p слов whisper, спор отдаём whisper,
            # если он не заметно слабее (stt.second.dispute_margin)
            if tp > mp + float(CFG.get("stt.second.dispute_margin", -0.15)) and not digits and not any(_bad(w) for w in theirs):
                out.extend(theirs); ch += 1
            else:
                out.extend(mine)
    return " ".join(out), ch


def split_turns(pcm16, sr: int, words, thr: float = None, min_s: float = 0.45):
    """Разрез реплики по СМЕНЕ ГОЛОСА (06.09.2026, владелец: «два человека
    быстро друг за другом — транскриб пишет в одно облачко»).

    Не по высоте (под музыкой она врёт), а по отпечатку: слова whisper с
    таймингами режутся на куски по паузам (≥0.25 с) и концам предложений,
    каждый кусок ≥ min_s кодируется тем же ReDimNet, что и реестр; соседние
    куски с косинусом ≥ thr склеиваются обратно. -> [{text,t0,t1,v,sec}]
    (пусто или один кусок = делить нечего)."""
    try:
        ws = [w for w in (words or []) if w.get("w") and w.get("t1") is not None]
        if len(ws) < 3:
            return []
        thr = float(CFG.get("stt.turns.cos", 0.35)) if thr is None else thr
        a = np.asarray(pcm16, np.int16)
        # 1. куски по паузам и знакам конца
        segs, cur = [], [ws[0]]
        for prev, w in zip(ws, ws[1:]):
            gap = float(w["t0"]) - float(prev["t1"])
            end = bool(re.search(r"[.!?…]$", str(prev["w"])))
            nxt = bool(re.match(r"^—|^-$|^[А-ЯЁA-Z]", str(w["w"])))
            # тире диалога: «—» или одиночный «-»; дефис внутри слова
            # («Лас» + «-Вегас») — не смена реплики
            dashw = bool(re.match(r"^—|^-$", str(w["w"])))
            if gap >= 0.25 or (end and (nxt or gap >= 0.12)) or dashw:
                segs.append(cur); cur = [w]
            else:
                cur.append(w)
        segs.append(cur)
        if len(segs) < 2:
            return []
        # 2. слишком короткие куски — к соседу
        def dur(sg): return float(sg[-1]["t1"]) - float(sg[0]["t0"])
        merged = []
        for sg in segs:
            starts_dash = bool(re.match(r"^—|^-$", str(sg[0]["w"])))
            if merged and not starts_dash and (dur(sg) < min_s or dur(merged[-1]) < min_s):
                merged[-1] = merged[-1] + sg
            else:
                merged.append(sg)
        if len(merged) < 2:
            return []
        # 3. отпечаток каждого куска
        from anamorf import voiceprint as _vp
        enc = _vp.S.enc
        if getattr(enc, "_sb", None) is None:
            return []
        parts = []
        for sg in merged:
            t0, t1 = float(sg[0]["t0"]), float(sg[-1]["t1"])
            i0, i1 = max(0, int((t0 - 0.05) * sr)), min(len(a), int((t1 + 0.05) * sr))
            if i1 - i0 < int(0.3 * sr):
                i0 = max(0, i1 - int(0.3 * sr))
            v, hz = enc.encode(a[i0:i1])
            parts.append({"text": " ".join(str(w["w"]) for w in sg), "t0": round(t0, 2),
                          "t1": round(t1, 2), "v": v, "hz": int(hz or 0)})
        # 4. соседей с одним голосом — обратно вместе
        out = [parts[0]]
        try:
            log.info("Кандидаты разреза: %s", " | ".join("%.1fс %dГц %r" % (p["t1"] - p["t0"], p["hz"], p["text"][:24]) for p in parts)
                     + " cos=" + ",".join("%.2f" % float(np.dot(a_["v"], b_["v"])) for a_, b_ in zip(parts, parts[1:])))
        except Exception:
            pass
        # КАЛИБРОВКА ПО ЖУРНАЛУ (23:08–23:14): на кусках короче ~1.2 с
        # отпечаток врёт — один и тот же голос даёт cos 0.25–0.45
        # («Ничего, | хорошие друзья» 0.25). Поэтому косинус решает только
        # на длинных кусках (оба ≥ min_each), а на коротких — тире whisper:
        # он ставит «— » на смене реплики (учился на субтитрах), и
        # «— Ой! — Вон там за углом. — Слава Богу» режется по нему.
        min_each = float(CFG.get("stt.turns.min_each_s", 1.2))
        for pt in parts[1:]:
            c = float(np.dot(out[-1]["v"], pt["v"]))
            short = (pt["t1"] - pt["t0"]) < min_each or (out[-1]["t1"] - out[-1]["t0"]) < min_each
            dash = bool(re.match(r"^(—|-\s)\s*\S", pt["text"])) or bool(re.search(r"\s[—-]\s*$", out[-1]["text"]))
            if dash and c < float(CFG.get("stt.turns.dash_cos", 0.6)):
                pt["cos"] = c; pt["by"] = "тире"
                out.append(pt)
                continue
            # вопрос → ответ + чужой отпечаток («Как играет? | В плюсе.»
            # cos 0.24): две улики вместе — режем и на коротких кусках
            if out[-1]["text"].rstrip().endswith("?") and c < float(CFG.get("stt.turns.qa_cos", 0.35)) \
                    and (pt["t1"] - pt["t0"]) >= 0.5:
                pt["cos"] = c; pt["by"] = "вопрос-ответ"
                out.append(pt)
                continue
            if c >= thr or short:
                n1 = out[-1]["t1"] - out[-1]["t0"]; n2 = pt["t1"] - pt["t0"]
                vv = out[-1]["v"] * n1 + pt["v"] * n2
                out[-1] = {"text": out[-1]["text"] + " " + pt["text"], "t0": out[-1]["t0"], "t1": pt["t1"],
                           "v": vv / (np.linalg.norm(vv) + 1e-9), "hz": out[-1]["hz"] or pt["hz"], "cos": c}
            else:
                pt["cos"] = c
                out.append(pt)
        if len(out) < 2:
            return []
        for pt in out:
            pt["sec"] = round(pt["t1"] - pt["t0"], 1)
        return out
    except Exception as e:
        log.debug("разрез по голосам не вышел: %s", e)
        return []


def _sure_word(w, wprob, conf_min):
    probs = {}
    for ww, pr in (wprob or []):
        k = re.sub(r"[^а-яёa-z]", "", ww.lower())
        if k:
            probs[k] = max(pr, probs.get(k, 0.0))
    parts = [x for x in re.findall(r"[а-яёa-z]+", w.lower()) if x]
    if not parts or sum(len(x) for x in parts) < 3:
        return False
    ps = [probs.get(x, 0.0) for x in parts]
    return min(ps) >= conf_min * 0.7 and sum(ps) / len(ps) >= conf_min


def _union(base: str, other: str, wprob=None, conf_min: float = 0.75, bconf=None):
    """Слова второго уха, которых нет в первом, — на своё место по
    выравниванию (difflib по нормализованным словам). -> (текст, добавлено).

    ТОЛЬКО УВЕРЕННЫЕ СЛОВА (06.09.2026, владелец: «он должен получать
    правильные слова, а не выдумывать хуету» — «многофейд», «соню», «не
    зная» были словами whisper с вероятностью ниже 0.5). Слово без
    уверенности ≥ conf_min в облачко не попадает; нет данных об
    уверенности — не дописываем вовсе."""
    import difflib
    bt = base.split()
    ot = other.split()
    probs = {}
    for w, pr in (wprob or []):
        k = re.sub(r"[^а-яёa-z]", "", w.lower())
        if k:
            probs[k] = max(pr, probs.get(k, 0.0))
    def _sure(w):
        parts = [x for x in re.findall(r"[а-яёa-z]+", w.lower()) if x]
        if not parts or sum(len(x) for x in parts) < 2:
            return False
        # КАПС из whisper на крике («ДРУК», «ААААА») — артефакт, не слово
        if len(w) > 2 and w.upper() == w and re.search(r"[А-ЯЁ]", w):
            return False
        ps = [probs.get(x, 0.0) for x in parts]      # «денег-то» = денег + то
        return min(ps) >= conf_min * 0.7 and sum(ps) / len(ps) >= conf_min
    if not probs:
        return base, 0
    # первое ухо почти ничего не услышало (≤2 слова) — терять нечего,
    # планка уверенности для второго ниже (0.75 → ~0.4): «много» под
    # музыкой у whisper 0.41, и это правильное слово (замер 06.09)
    conf_hi = conf_min
    if len([w for w in bt if re.sub(r"[^а-яёa-z]", "", w.lower())]) <= 2:
        conf_min = conf_min * float(CFG.get("stt.second.weak_base_k", 0.5))
    # ХВОСТ whisper НА ОБРЕЗАННОМ КУСКЕ — самое ненадёжное («союз? Ну!»
    # 0.59/0.45): неуверенные слова с конца срезаем до первого уверенного
    def _pk(w):
        ps = [probs.get(x, 0.0) for x in re.findall(r"[а-яёa-z]+", w.lower())]
        return (sum(ps) / len(ps)) if ps else 0.0
    while ot and _pk(ot[-1]) < conf_hi:
        ot.pop()
    bconf = bconf or {}
    def _weak(ws):
        """слова первого уха неуверенны (CTC < 0.5 в среднем) или их нет"""
        vals = [bconf.get(re.sub(r"[^а-яёa-z]", "", w.lower()), None) for w in ws]
        vals = [v for v in vals if v is not None]
        return (not vals) or (sum(vals) / len(vals) < float(CFG.get("stt.second.base_weak", 0.5)))
    bn = [re.sub(r"[^а-яёa-z]", "", w.lower()) for w in bt]
    on = [re.sub(r"[^а-яёa-z]", "", w.lower()) for w in ot]
    sm = difflib.SequenceMatcher(a=bn, b=on, autojunk=False)
    out = []
    added = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out.extend(bt[i1:i2])
        elif tag == "insert":
            ins = [w for w in ot[j1:j2] if _sure(w)]
            # одинокое короткое «не»/«ну» между чужими словами — чаще
            # домысел языковой модели, чем услышанное; пропускаем
            if len(ins) == 1 and len(re.sub(r"[^а-яёa-z]", "", ins[0].lower())) < 3:
                ins = []
            out.extend(ins)
            added += len(ins)
        elif tag == "replace":
            # оба что-то слышали: своё оставляем, чужое добавляем, только
            # если у второго уха тут заметно больше слов (пропуск, не спор)
            mine = bt[i1:i2]
            theirs = [w for w in ot[j1:j2] if _sure(w)]
            if (len(theirs) >= len(mine) + 2 and len(theirs) * 2 >= (j2 - j1)) \
                    or (theirs and _weak(mine) and len(theirs) >= len(mine)):
                # у второго уха тут уверенные слова, у первого — обрывок
                # или неуверенное чтение («мо деньг» 0.3 против «денег-то
                # было» 0.9)
                out.extend(theirs)
                added += max(1, len(theirs) - len(mine))
            else:
                out.extend(mine)
        else:  # delete — слово есть только у первого уха, оставляем
            out.extend(bt[i1:i2])
    return " ".join(out), added


def listen_async(stt, pcm16, sr, r: dict, emit, force: bool = False):
    """Переслушать в фоне и, если есть что править, отдать stt_fix.
    force=True — первое ухо промолчало (песня): результат уходит новой
    репликой stt, а не правкой."""
    if not enabled():
        return
    pid = r.get("pid")
    first = r.get("text") or ""
    if force:
        def _bg_force():
            try:
                new, why = listen(stt, pcm16, sr, "", {})
                if new and not _bad(new):
                    e = dict(r); e["text"] = new; e["_flush"] = "песня"
                    e["engine"] = STATE.get("engine") or "second"
                    log.info("Песня вторым ухом (%d мс): %r", STATE["ms"], new[:60])
                    emit(e)
                else:
                    log.debug("песня: %s", why)
            except Exception as e:
                log.debug("песня упала: %s", e)
        threading.Thread(target=_bg_force, daemon=True, name="second-song").start()
        return
    try:
        from anamorf.stt import engines as _eg
        _bc = {}
        for _w in (getattr(_eg.LAST_WORDS, "words", None) or []):
            if len(_w) >= 4:
                _bc[re.sub(r"[^а-яёa-z]", "", str(_w[0]).lower())] = float(_w[3])
        STATE["bconf"] = _bc
    except Exception:
        _bc = {}
        STATE["bconf"] = {}

    def _release(new_text="", parts=None, drop=False, why=""):
        """облачко придержано в main до нашего ответа — выпустить его сразу"""
        try:
            from anamorf import main as _mn
            return bool(_mn.stt_release(pid, new_text, why or STATE.get("engine") or "второе ухо", parts, drop))
        except Exception:
            return False

    def _parts():
        """разрез по сменам голоса — по таймингам слов whisper и звуку, который он слушал"""
        try:
            if not CFG.get("stt.turns.split", True):
                return None
            eng = stt._get("faster_whisper")
            ww = getattr(eng, "last_words", None) or []
            xa = STATE.get("_x")
            if xa is None or len(ww) < 3:
                return None
            pts = split_turns(xa, sr, ww)
            if pts:
                log.info("Разрез по голосам: %s", " | ".join("%s (cos %.2f)" % (p["text"][:30], p.get("cos", 1.0)) for p in pts))
            return pts or None
        except Exception as _pe:
            log.debug("разрез не вышел: %s", _pe)
            return None

    # первое ухо уверено (CTC ≥ base_sure по всем словам) — карту не жжём
    try:
        if _bc and min(_bc.values()) >= float(CFG.get("stt.second.base_sure", 0.85)) \
                and len(_words(first)) >= 3:
            _release()
            return
    except Exception:
        pass

    def _bg():
        try:
            _mus = 0.0
            try:
                _mus = max([float(v) for k, v, *_ in (r.get("sounds") or []) if str(k) in ("музыка", "пение")] or [0.0])
            except Exception:
                _mus = 0.0
            new, why = listen(stt, pcm16, sr, first, _bc, whole=(_mus >= 0.6))
            # ═══ РУССКАЯ КАША НА ЧУЖОМ ЯЗЫКЕ (06.09.2026, владелец: «много
            # выдуманных русских слов, хотя русского не было»): whisper
            # уверенно слышит другой язык (≥0.75), но в словах не уверен —
            # значит первое ухо написало русские слова поверх чужой речи.
            # Такой реплики не было: гасим.
            try:
                if not new and CFG.get("stt.second.drop_foreign", True):
                    _lg = str(STATE.get("lang") or "")
                    _lp = float(getattr(stt._get("faster_whisper"), "last_lang_p", 0.0) or 0.0)
                    _cyr = len(re.findall(r"[а-яё]", first.lower()))
                    if _lg and _lg not in ("ru", "uk", "be") and _lp >= 0.75 and _cyr >= 3:
                        log.info("Каша на чужом языке (%s %.2f): %r — не показываю", _lg, _lp, first[:40])
                        _release(drop=True, why="чужой язык %s" % _lg)
                        return
            except Exception:
                pass
            # разрез стоит ~100 мс (отпечаток каждого куска) — если whisper
            # уже съел бюджет придержки, разрез пропускаем, чтобы облачко
            # вышло сведённым, а не «по сроку»
            _budget = float(CFG.get("stt.second.wait_ms", 600)) - 250
            pts = _parts() if STATE.get("ms", 0) < _budget else None
            if new and new != first:
                if _release(new, pts):
                    log.info("Второе ухо успело (%d мс): %r -> %r", STATE["ms"], first[:50], new[:60])
                    return
                log.info("Второе ухо (%d мс): %r -> %r", STATE["ms"], first[:50], new[:60])
                emit({"type": "stt_fix", "pid": pid, "was": first, "text": new,
                      "engine": STATE.get("engine") or "second", "src": r.get("src", "")})
                return
            _release("", pts)
            if why == "разошлись":
                log.info("Уши разошлись: %r против %r", first[:50], STATE.get("doubt", "")[:50])
                emit({"type": "stt_doubt", "pid": pid, "other": STATE.get("doubt", ""),
                      "src": r.get("src", "")})
            else:
                log.debug("Второе ухо: %s (%r)", why, first[:40])
        except Exception as e:
            _release()
            log.debug("второе ухо упало: %s", e)

    threading.Thread(target=_bg, daemon=True, name="second-ear").start()
