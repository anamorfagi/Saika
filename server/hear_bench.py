"""СТЕНД СЛУХА — «волна и то, что по ней написано» (2026-08-15).

ПОВОД, дословно от владельца: «скорость отклика транскриба и его качество
написания относительно звуковых волн», «он в половину слов что-то своё
вообще написал». Спорить об этом на слух невозможно: пока нет пары «вот
кусок звука — вот что по нему написано», любая правка порога, шумодава или
движка остаётся угадайкой. Сначала линейка, потом правка — иначе получается
ровно то, за что в CLAUDE.md записан отдельный раздел про сломанное ради
починки.

ЧТО КОПИТ. На каждый распознанный сегмент — ДВЕ вещи:
  1. сам звук, ровно тот массив, который ушёл в движок (WAV, 16 кГц);
  2. строку в index.jsonl: что написано, каким движком, за сколько
     миллисекунд, какой был шумодав, длительность куска, RMS и пик.
Ничего лишнего не считается: все эти числа уже есть в конвейере, стенд их
только записывает рядом со звуком.

ЧТО ОТДАЁТ. report() собирает ОДНУ html-страницу: волна сегмента, под ней
написанный текст, рядом кнопка «послушать». На такой странице сразу видно,
что именно произошло — голос был тише порога и начало съедено, звук обрезан
на первом слоге, или движок выдумал шесть слов на полсекунды шороха. Это и
есть ответ на «относительно звуковых волн».

ЗВУК ЗДЕСЬ ХРАНИТСЯ — И ЭТО ОСОЗНАННОЕ ИСКЛЮЧЕНИЕ. В earlog и hearing звук
принципиально не сохраняется: час микрофона в квартире — это чужие
разговоры и телевизор, и складывать их ради отчёта про щелчки было бы не тем
разменом. Стенд — другое дело: он ВЫКЛЮЧЕН по умолчанию, включается руками
на время отладки, держит только последние N сегментов и сам сносит старые.
Пока он выключен, ни одного байта звука на диск не попадает.
"""
import json
import logging
import threading
import time
import wave
from pathlib import Path

import numpy as np

from server.config import CFG, ROOT

log = logging.getLogger("saika.bench")

DIR = ROOT / "data" / "hear_bench"
INDEX = DIR / "index.jsonl"

_lock = threading.Lock()
_n = {"saved": 0}


def on() -> bool:
    return bool(CFG.get("stt.bench", False))


def set_on(value: bool) -> dict:
    CFG.set("stt.bench", bool(value))
    log.info("Стенд слуха: %s", "пишу звук и текст" if value else "выключен")
    return status()


def keep() -> int:
    """Сколько последних сегментов держим на диске. 300 сегментов средней
    фразы — это порядка 100 МБ; больше для отладки не нужно, а меньше не
    даёт увидеть закономерность."""
    return int(CFG.get("stt.bench_keep", 300))


# ------------------------------------------------------------------ запись
def record(pcm16, sr: int, text: str, engine: str, ms: int, extra=None):
    """Сегмент + то, что по нему написано. Зовётся из потока распознавания
    ПОСЛЕ движка, поэтому цена (запись WAV на диск, единицы миллисекунд)
    никому не мешает: горячий цикл слуха давно в другом потоке.

    Ошибки глотаем молча только здесь и только в лог: стенд — вещь для
    отладки, он не имеет права уронить слух, ради которого включён."""
    if not on():
        return None
    try:
        a = np.asarray(pcm16, dtype=np.int16).ravel()
        if not a.size:
            return None
        with _lock:
            DIR.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            name = f"{stamp}_{_n['saved'] % 100000:05d}.wav"
            _n["saved"] += 1
            with wave.open(str(DIR / name), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(int(sr))
                w.writeframes(a.tobytes())
            f = a.astype(np.float32) / 32768.0
            row = {
                "ts": time.time(),
                "at": time.strftime("%H:%M:%S"),
                "wav": name,
                "text": text or "",
                "engine": engine or "",
                "ms": int(ms or 0),
                "sec": round(len(a) / float(sr or 16000), 2),
                "rms": round(float(np.sqrt(np.mean(f ** 2))), 5),
                "peak": round(float(np.max(np.abs(f))), 4),
                "denoise": str(CFG.get("denoise.engine", "off")),
                "seg_denoise": str(CFG.get("denoise.segment_engine", "off")),
            }
            if extra:
                row.update(extra)
            with INDEX.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            _rotate()
        return row
    except Exception as e:
        log.warning("Стенд слуха: не записал сегмент (%s)", e)
        return None


def _rotate():
    """Кольцо: старше keep() — на удаление. Чистим и файлы, и строки, иначе
    отчёт начинает ссылаться на несуществующий звук."""
    try:
        rows = _rows()
        if len(rows) <= keep():
            return
        drop, rows = rows[:-keep()], rows[-keep():]
        for r in drop:
            try:
                (DIR / str(r.get("wav", ""))).unlink(missing_ok=True)
            except Exception:
                pass
        INDEX.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8")
    except Exception as e:
        log.debug("Стенд слуха: кольцо не провернулось (%s)", e)


def _rows() -> list:
    if not INDEX.exists():
        return []
    out = []
    for line in INDEX.read_text("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def clear() -> dict:
    with _lock:
        try:
            for p in DIR.glob("*.wav"):
                p.unlink(missing_ok=True)
            INDEX.unlink(missing_ok=True)
        except Exception as e:
            log.warning("Стенд слуха: не почистился (%s)", e)
    return status()


# ------------------------------------------------------------------ отчёт
def _peaks(path: Path, n: int = 900):
    """Огибающая волны: n пар (мин, макс). Считается по файлу, а не по
    памяти, — отчёт можно собрать и через час после разговора."""
    try:
        with wave.open(str(path), "rb") as w:
            raw = w.readframes(w.getnframes())
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if not a.size:
            return []
        step = max(1, len(a) // n)
        cut = a[:len(a) - len(a) % step].reshape(-1, step)
        return [[round(float(x), 3), round(float(y), 3)]
                for x, y in zip(cut.min(1), cut.max(1))]
    except Exception:
        return []


def report(limit: int = 40) -> dict:
    """Одна самодостаточная html-страница: волна, текст, «послушать».

    Звук вшивается в страницу как data-URL — файл можно унести куда угодно
    и открыть без сервера. Поэтому limit небольшой: сорок сегментов это
    порядка десяти мегабайт, а закономерность видна уже на десятке."""
    import base64

    rows = _rows()[-int(limit):]
    if not rows:
        return {"ok": False, "error": "стенд пуст — включи его и поговори"}
    cards = []
    for r in rows:
        p = DIR / str(r.get("wav", ""))
        pk = _peaks(p)
        try:
            b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        except Exception:
            b64 = ""
        raw = r.get("heard_raw", "")
        fixed = (f'<div class="raw">было услышано: {_esc(raw)}</div>'
                 if raw and raw != r.get("text") else "")
        cards.append(
            '<div class="c">'
            f'<div class="h"><b>{_esc(r.get("at", ""))}</b>'
            f' · {_esc(r.get("engine", ""))} · {r.get("ms", 0)}мс'
            f' · звук {r.get("sec", 0)}с · rms {r.get("rms", 0)}'
            f' · пик {r.get("peak", 0)}'
            f' · шумодав {_esc(r.get("denoise", ""))}'
            f'/{_esc(r.get("seg_denoise", "off"))}</div>'
            f'<canvas class="w" data-p=\'{json.dumps(pk)}\'></canvas>'
            f'<div class="t">{_esc(r.get("text", "")) or "<i>— пусто —</i>"}</div>'
            f'{fixed}'
            + (f'<audio controls src="data:audio/wav;base64,{b64}"></audio>'
               if b64 else "")
            + '</div>')

    html = _PAGE.replace("__CARDS__", "\n".join(cards)).replace(
        "__N__", str(len(rows)))
    DIR.mkdir(parents=True, exist_ok=True)
    out = DIR / f"report_{time.strftime('%Y%m%d_%H%M')}.html"
    out.write_text(html, encoding="utf-8")
    log.info("Стенд слуха: отчёт %s (%d сегментов)", out.name, len(rows))
    return {"ok": True, "file": str(out), "n": len(rows)}


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def status() -> dict:
    rows = _rows()
    return {"on": on(), "n": len(rows), "keep": keep(),
            "dir": str(DIR), "last": rows[-1] if rows else None}


_PAGE = """<!doctype html><meta charset="utf-8">
<title>Стенд слуха — волна и текст</title>
<style>
 body{background:#12141c;color:#dfe3ee;font:14px/1.5 system-ui,sans-serif;
      margin:0;padding:18px}
 h1{font-size:17px;font-weight:600;margin:0 0 14px}
 .c{background:#1a1d28;border:1px solid #262b3a;border-radius:10px;
    padding:10px 12px;margin:0 0 12px}
 .h{color:#8b93ab;font-size:12px;margin-bottom:6px}
 .w{width:100%;height:64px;display:block}
 .t{margin:8px 0 6px;font-size:15px}
 .raw{color:#c9a227;font-size:12px;margin-bottom:6px}
 audio{width:100%;height:30px}
</style>
<h1>Стенд слуха — __N__ сегментов: волна и то, что по ней написано</h1>
__CARDS__
<script>
for(const cv of document.querySelectorAll('canvas.w')){
  const p=JSON.parse(cv.dataset.p||'[]');
  const w=cv.clientWidth||900, h=64;
  cv.width=w*2; cv.height=h*2;
  const g=cv.getContext('2d'); g.scale(2,2);
  g.fillStyle='#12141c'; g.fillRect(0,0,w,h);
  g.strokeStyle='#2f3549'; g.beginPath();
  g.moveTo(0,h/2); g.lineTo(w,h/2); g.stroke();
  if(!p.length) continue;
  g.strokeStyle='#7aa2f7';
  for(let i=0;i<p.length;i++){
    const x=i/p.length*w;
    g.beginPath();
    g.moveTo(x,h/2-p[i][1]*h/2);
    g.lineTo(x,h/2-p[i][0]*h/2);
    g.stroke();
  }
}
</script>
"""
