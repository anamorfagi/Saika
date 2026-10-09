# -*- coding: utf-8 -*-
"""Узнавание музыки и караоке (06.09.2026).

Владелец: «может, какую-то систему распознавания музыки и её названия
найти, а не писать транскриб слов от персонажей в это окно; если это
песня — писать название и её слова как караоке, бегущая строка, которая
показывает текущее слово песни».

Как устроено:
  1. feed(a, src) — те же 16 кГц доли [-1, 1], что идут в уши; храним
     последние 12 с на каждый канал (микрофон, система, Discord).
  2. maybe(src, music_p) — зовётся из ушей на каждом окне; музыка ≥ 0.6
     держится ≥ 4 с и с прошлой попытки прошло ≥ 25 с → в фоне Shazam
     (shazamio, ~0.4 с) по последним 10 с.
  3. Узнали → синхронный текст с LRCLIB (бесплатно, [mm:ss.xx] строки),
     наружу song_id: название, исполнитель, смещение в треке на момент
     конца буфера и строки текста. Вкладка сама бежит по времени и
     подсвечивает текущее слово.
Замер: 31 с из hear_bench → «Hit the Floor — LINKIN PARK» за 0.4 с,
смещение 30.97 с (tools/shazam_probe.py).
"""
import io
import json
import logging
import threading
import time
import wave

import numpy as np

from anamorf.config import CFG

log = logging.getLogger("saika.music")

SR = 16000
KEEP_S = 12.0
_lock = threading.Lock()
BUF = {}            # src -> float32 буфер
STATE = {"on_since": {}, "last_try": {}, "song": {}, "busy": False, "n": 0, "ok": 0, "err": ""}
_emit = None
_LYR = {}           # (artist, title) -> lyrics list или None


def start(emit):
    global _emit
    _emit = emit


def feed(a, src: str = ""):
    """Кормить долями [-1, 1] 16 кГц (из hearing.feed)."""
    if not CFG.get("music.id", True):
        return
    try:
        a = np.asarray(a, np.float32).ravel()
        if not a.size:
            return
        k = src or "mic"
        keep = int(KEEP_S * SR)
        with _lock:
            prev = BUF.get(k)
            BUF[k] = (np.concatenate([prev, a]) if prev is not None and prev.size else a)[-keep:]
    except Exception:
        pass


def maybe(src: str, music_p: float):
    """Уши сообщают: в канале музыка с вероятностью music_p."""
    global _emit
    if not CFG.get("music.id", True):
        return
    if _emit is None:
        try:
            from anamorf import main as _mn
            _emit = _mn.broadcast_event
        except Exception:
            return
    now = time.time()
    k = src or "mic"
    thr = float(CFG.get("music.id_p", 0.6))
    if music_p < thr:
        STATE["on_since"].pop(k, None)
        # музыка стихла: если трек вели — через 3 с без музыки снимаем его
        # (владелец: «музыку вырубили — он до сих пор мигает, текст идёт»)
        off = STATE.setdefault("off_since", {})
        off.setdefault(k, now)
        if STATE["song"].get(k) and now - off[k] >= float(CFG.get("music.id_off_s", 3.0)):
            STATE["song"].pop(k, None)
            if _emit:
                _emit({"type": "song_id", "src": k, "lost": True, "why": "музыка стихла"})
        return
    STATE.setdefault("off_since", {}).pop(k, None)
    since = STATE["on_since"].setdefault(k, now)
    if now - since < float(CFG.get("music.id_hold_s", 4.0)):
        return
    # пока трек ведём — проверяем чаще (смена песни должна ловиться быстро)
    _every = float(CFG.get("music.id_every_s", 12.0))
    if now - STATE["last_try"].get(k, 0) < _every:
        return
    with _lock:
        buf = BUF.get(k)
        if buf is None or buf.size < int(8 * SR) or STATE["busy"]:
            return
        a = buf[-int(10 * SR):].copy()
        STATE["busy"] = True
    STATE["last_try"][k] = now
    threading.Thread(target=_recognize, args=(k, a, now), daemon=True, name="music-id").start()


def _wav_bytes(a: np.ndarray) -> bytes:
    pcm = np.clip(a * 32768.0, -32768, 32767).astype(np.int16)
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
    return b.getvalue()


def _lyrics(artist: str, title: str):
    """Синхронный текст с LRCLIB -> [[секунда, строка], ...] или None."""
    key = (artist.lower(), title.lower())
    if key in _LYR:
        return _LYR[key]
    out = None
    try:
        import urllib.parse, urllib.request
        q = urllib.parse.urlencode({"artist_name": artist, "track_name": title})
        req = urllib.request.Request("https://lrclib.net/api/get?" + q,
                                     headers={"User-Agent": "Saika/1.0 (hearing karaoke)"})
        with urllib.request.urlopen(req, timeout=6) as r:
            d = json.loads(r.read().decode("utf-8"))
        synced = d.get("syncedLyrics") or ""
        lines = []
        import re
        for ln in synced.splitlines():
            m = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)", ln)
            if m:
                t = int(m.group(1)) * 60 + float(m.group(2))
                lines.append([round(t, 2), m.group(3).strip()])
        if lines:
            out = {"synced": True, "lines": lines}
        elif d.get("plainLyrics"):
            out = {"synced": False, "lines": [[None, x] for x in d["plainLyrics"].splitlines() if x.strip()]}
    except Exception as e:
        log.info("LRCLIB: нет текста для %s — %s: %s", artist, title, str(e)[:80])
    _LYR[key] = out
    return out


def _recognize(src: str, a: np.ndarray, t_end: float):
    try:
        STATE["n"] += 1
        import asyncio
        from shazamio import Shazam
        wav = _wav_bytes(a)
        t0 = time.time()
        res = asyncio.run(Shazam().recognize(wav))
        ms = int((time.time() - t0) * 1000)
        tr = (res or {}).get("track") or {}
        title, artist = tr.get("title"), tr.get("subtitle")
        if not title:
            log.info("Музыка (%s): Shazam не узнал (%d мс)", src, ms)
            # трек вели, а теперь дважды подряд не узнали — песня сменилась
            # или кончилась: вкладке сказать «потеряли», чтобы не тянула старую
            STATE.setdefault("miss", {})[src] = STATE.get("miss", {}).get(src, 0) + 1
            if STATE["song"].get(src) and STATE["miss"][src] >= 2 and _emit:
                STATE["song"].pop(src, None)
                _emit({"type": "song_id", "src": src, "lost": True})
            return
        STATE.setdefault("miss", {})[src] = 0
        m = ((res or {}).get("matches") or [{}])[0]
        # offset у Shazam — секунда трека, где НАЧАЛСЯ наш кусок; конец
        # буфера = offset + длина куска (владелец: «жёстко отстаёт»)
        offset = float(m.get("offset") or 0.0) + len(a) / float(SR)
        STATE["ok"] += 1
        lyr = _lyrics(artist or "", title or "")
        # перевод строк песни — одним запросом к служебному мозгу (владелец:
        # «ниже пиши переводы»); только если текст не русский
        tr_lines = []
        try:
            lines = (lyr or {}).get("lines") or []
            txt = "\n".join(x[1] for x in lines if x[1])
            import re as _re
            if lines and _re.search(r"[a-zA-Z\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", txt) \
                    and len(_re.findall(r"[а-яё]", txt.lower())) < len(txt) * 0.3:
                from anamorf.llm import manager as _lm
                src_lines = [x[1] for x in lines][:80]
                out = _lm.chat_once([{"role": "system", "content":
                                      "Переведи строки песни на русский, построчно, ровно столько же строк, "
                                      "в том же порядке, без нумерации и пояснений."},
                                     {"role": "user", "content": "\n".join(src_lines)}], max_len=3000) or ""
                got = [x.strip() for x in out.splitlines() if x.strip()]
                if abs(len(got) - len(src_lines)) <= max(2, len(src_lines) // 10):
                    tr_lines = got
                else:
                    # строк не сошлось — переводим по одной короткими пачками
                    log.info("перевод песни: строк %d, получено %d — пачками", len(src_lines), len(got))
                    tr_lines = []
                    for i in range(0, len(src_lines), 8):
                        chunk = src_lines[i:i + 8]
                        o2 = _lm.chat_once([{"role": "system", "content":
                                             "Переведи строки на русский построчно: столько же строк, тот же порядок, без нумерации."},
                                            {"role": "user", "content": "\n".join(chunk)}], max_len=800) or ""
                        g2 = [x.strip() for x in o2.splitlines() if x.strip()]
                        if len(g2) != len(chunk):
                            g2 = (g2 + [""] * len(chunk))[:len(chunk)]
                        tr_lines += g2
                    if not any(tr_lines):
                        tr_lines = []
        except Exception as e:
            log.info("перевод песни не вышел: %s", str(e)[:80])
        song = {"type": "song_id", "src": src, "title": title, "artist": artist, "lyrics_tr": tr_lines,
                "lead": float(CFG.get("music.lead_s", 1.5)),
                "offset": round(offset, 2), "t_end": round(t_end, 3), "ms": ms, "buf_s": round(len(a) / float(SR), 1),
                "cover": ((tr.get("images") or {}).get("coverart") or ""),
                "lyrics": (lyr or {}).get("lines") or [], "synced": bool((lyr or {}).get("synced"))}
        STATE["song"][src] = song
        # задним числом: реплики, оказавшиеся строками этой песни, — с ленты
        try:
            if song["lyrics"]:
                from anamorf import main as _mn
                _mn.song_cleanup(src, song["lyrics"])
        except Exception:
            pass
        log.info("Музыка (%s): %s — %s, смещение %.1f с, текст %s (%d мс)", src, artist, title, offset,
                 "синхронный" if song["synced"] else ("простой" if song["lyrics"] else "нет"), ms)
        if _emit:
            _emit(dict(song, lyrics=song["lyrics"][:400], lyrics_tr=song.get("lyrics_tr", [])[:400]))
    except Exception as e:
        STATE["err"] = str(e)[:160]
        log.info("Музыка: узнавание упало: %s", str(e)[:120])
    finally:
        STATE["busy"] = False
