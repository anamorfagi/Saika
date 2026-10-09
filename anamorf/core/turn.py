"""ОДИН ХОД РАЗГОВОРА ЯДРА v2 — вход из main.run_dialog.

Протокол очереди `out` тот же, что у старого run_dialog, поэтому чат,
REST /api/chat и голос работают без переделок:
    {"type":"token","text"} · {"type":"tool","name","args"} ·
    {"type":"audio_meta","sr"} + bytes · {"type":"final","text"} ·
    {"type":"stats",...} · {"type":"done"}
"""
import json
import logging
import queue
import re
import threading
import time

from anamorf.core import agent_loop, context, engine

log = logging.getLogger("saika.core.turn")
_GESTURE = re.compile(r"\[жест:[^\]]*\]")
_SENT_END = re.compile(r"([.!?…]+)(\s+|$)")


class _Speaker:
    """Голос в отдельном потоке: текст идёт в чат сразу, звук — по фразам."""

    def __init__(self, out, stop, tts, gesture_fn, enabled=True):
        self.out, self.stop, self.tts, self.g = out, stop, tts, gesture_fn
        self.q = queue.Queue()
        self.buf = ""
        self.first_sound = None
        self.enabled = enabled and tts is not None
        self.th = threading.Thread(target=self._run, daemon=True, name="core-voice")
        self.th.start()

    def feed(self, delta: str):
        self.buf += delta
        while True:
            m = _SENT_END.search(self.buf)
            if not m or len(self.buf[:m.end()].strip()) < 2:
                return
            self.q.put(self.buf[:m.end()].strip())
            self.buf = self.buf[m.end():]

    def flush(self):
        if self.buf.strip():
            self.q.put(self.buf.strip())
        self.buf = ""
        self.q.put(None)

    def _run(self):
        while True:
            s = self.q.get()
            if s is None:
                return
            try:
                if self.g:
                    s = self.g(s)            # [жест:joy] -> жест аватару, из текста убран
                s = _GESTURE.sub("", s).strip()
                if not self.enabled or self.stop.is_set() or \
                        not re.search(r"[0-9a-zа-яё]", s, re.I):
                    continue
                for pcm, sr in self.tts.speak(s):
                    if self.stop.is_set():
                        break
                    if self.first_sound is None:
                        self.first_sound = time.monotonic()
                    self.out.put({"type": "audio_meta", "sr": sr})
                    self.out.put(pcm)
            except Exception as e:
                log.warning("голос ядра v2: %s", e)

    def join(self, timeout=120):
        self.th.join(timeout)


def _display_filter():
    """Чат видит текст сразу, но без [жест:...] (держим от «[» до «]»)."""
    st = {"hold": ""}

    def f(delta: str) -> str:
        s = st["hold"] + delta
        st["hold"] = ""
        i = s.rfind("[")
        if i != -1 and "]" not in s[i:]:
            st["hold"] = s[i:]
            s = s[:i]
        return _GESTURE.sub("", s)
    return f


_FAIL = re.compile(r"^\s*(отказ|ошибка|не\s|нет\s|нужно подтверждение|кадр не)", re.I)


def run(user_text: str, out, stop, *, memory, tts, owner_id: str,
        owner_name: str, gesture_fn=None, speak: bool = True,
        heard_ts=None) -> str:
    """ХРОНОМЕТРАЖ ХОДА (каждый ход, в чат и в лог):
        слух    — от готового текста распознавания до входа в ядро
        решение — вход -> первое слово ИЛИ первый вызов модели
        рука    — сумма времени инструментов (по каждому отдельно в строках ✓/✗)
        голос   — первое слово -> первый звук
        всего   — вход -> первый звук (или первое слово, если голос выключен)"""
    t0 = time.monotonic()
    tl = {"first": None, "tools_ms": 0, "tools": []}
    if not engine.ensure():
        out.put({"type": "noreply", "text": "мозг ядра v2 не поднялся — смотри logs/core_engine.log"})
        out.put({"type": "done"})
        return ""
    msgs, user_msg = context.build(memory, owner_id, owner_name, user_text)
    t_ctx = time.monotonic()
    try:                                     # отпечаток префикса: ловим, что ломает кэш
        import hashlib
        log.info("ядро v2: префикс sys=%s hist=%d сообщ (%s)",
                 hashlib.md5(msgs[0]["content"].encode()).hexdigest()[:8], len(msgs) - 2,
                 hashlib.md5(json.dumps(msgs[1:-1], ensure_ascii=False).encode()).hexdigest()[:8])
    except Exception:
        pass
    memory.add_event(owner_id, "user", user_text)
    voice = _Speaker(out, stop, tts, gesture_fn, enabled=speak)
    show = _display_filter()
    said = []

    def on_text(d):
        if tl["first"] is None:
            tl["first"] = time.monotonic()
        if tl.get("first_text") is None:
            tl["first_text"] = time.monotonic()
        said.append(d)
        v = show(d)
        if v:
            out.put({"type": "token", "text": v})
        voice.feed(d)

    def on_tool(name, args, res, ms=0):
        if tl["first"] is None:
            tl["first"] = time.monotonic() - ms / 1000.0   # решение = до вызова
        tl["tools_ms"] += ms
        tl["tools"].append(f"{name} {ms}")
        out.put({"type": "tool", "name": name,
                 "args": json.dumps(args, ensure_ascii=False)})
        out.put({"type": "tool_result", "name": name, "text": str(res)[:400],
                 "ms": ms, "ok": not _FAIL.search(str(res))})
        voice.feed(" ")

    try:
        r = agent_loop.run(msgs, user_text, on_text, on_tool, stop)
    except Exception as e:
        log.exception("ядро v2: ход упал")
        voice.flush()
        out.put({"type": "noreply", "text": f"ядро v2 упало: {e}"})
        out.put({"type": "done"})
        return ""
    voice.flush()
    reply = _GESTURE.sub("", "".join(said)).strip()
    if reply:
        memory.add_event(owner_id, "assistant", reply)
    # в стенограмму — без повторов жестов: один [жест:..] на реплику, иначе
    # модель учится на собственном зацикливании
    _new = []
    for _m in (r.get("new") or []):
        if _m.get("role") == "assistant" and _m.get("content"):
            _m = dict(_m)
            _seen = {"g": False}

            def _one(mt, _s=_seen):
                if _s["g"]:
                    return ""
                _s["g"] = True
                return mt.group(0)
            _m["content"] = _GESTURE.sub(_one, _m["content"]).strip()
        _new.append(_m)
    context.commit(user_msg, _new)
    out.put({"type": "final", "text": reply})
    st = r["stats"][0] if r["stats"] else {}
    stats = {"model": "core-v2/Qwen3.6-35B-A3B", "tokens": len(reply.split()),
             "latency_ms": int((t_ctx - t0) * 1000) + int(st.get("ttft_ms") or 0),
             "steps": r["steps"], "tools": [t["name"] for t in r["tools"]],
             "cache_n": st.get("cache_n"), "prompt_n": st.get("prompt_n")}
    # ждём ПЕРВЫЙ звук (не весь голос): до 15 с или пока голос не кончился
    _w = time.monotonic()
    while voice.first_sound is None and voice.th.is_alive() and time.monotonic() - _w < 15:
        time.sleep(0.02)
    _snd = voice.first_sound
    _fst = tl["first"] or time.monotonic()
    _ftx = tl.get("first_text") or _fst
    timeline = {
        "hear_ms": int((t0 - heard_ts) * 1000) if heard_ts else None,
        "decide_ms": int((_fst - t0) * 1000),
        "hand_ms": tl["tools_ms"], "hand": tl["tools"],
        "voice_ms": int((_snd - _ftx) * 1000) if _snd else None,
        "total_ms": int(((_snd or _fst) - (heard_ts or t0)) * 1000)}
    stats["timeline"] = timeline
    out.put({"type": "stats", **stats})
    log.info("ядро v2: хронометраж %s", timeline)
    log.info("ядро v2: ход за %.1f с | сборка %d мс | до 1-го токена %s мс | "
             "шагов %d | инструменты %s", time.monotonic() - t0,
             (t_ctx - t0) * 1000, st.get("ttft_ms"), r["steps"], stats["tools"])
    engine.save_slot_async()
    voice.join()
    out.put({"type": "done"})
    return reply
