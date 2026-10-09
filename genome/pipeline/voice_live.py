# -*- coding: utf-8 -*-
"""
voice_live.py — живой контроллер голоса Сайки по профилю из Anamorf Genom (voice_<id>.json, format saika-voice/1).

Что делает:
  1. Держит состояние 11 эмоциональных каналов (гнев, страх, печаль, стыд, радость, интерес, нежность, влечение,
     отвращение, удивление, зависть). Канал вспыхивает от события, если повод ≥ порога канала (из генов dyn.*.threshold),
     сила = force канала (пик × (1 − скрывает)), гаснет экспоненциально за decay_s, при dwell > .6 не уходит в ноль.
  2. На каждую реплику собирает крутилки: base + Σ level_канала × effect_канала, затем накладывает режим
     (шёпот/гнев/интим/смех/печаль/пение/звуки), если он свойствен персонажу (gate ≥ .4).
  3. Переводит крутилки в настройки конкретного движка и вставляет его метки в текст.

Использование в Сайке:
    vl = VoiceLive("voice_marie.json")
    vl.event("anger", 0.8)              # пользователь оскорбил: повод 0.8
    payload = vl.render("Что ты сказал? Повтори.")   # -> {"text": "...с метками", "settings": {...}, "knobs": {...}}
    ... каждый кадр/реплику: vl.tick(dt_seconds)
Демо:  python voice_live.py voice_marie.json --demo
"""
import json, math, re, sys, time

KNOBS = ("speed", "energy", "stab", "style", "breath", "pitch", "pause")

# ── [блок 1] подсказки режима по тексту реплики: явные метки автора сцены или знаки в тексте ──
MODE_CUES = [
    (re.compile(r"\[(шёпот|шепот|whisper)\]", re.I), "whisper"),
    (re.compile(r"\[(крик|гнев|anger|shout)\]", re.I), "anger"),
    (re.compile(r"\[(интим|intim|близость)\]", re.I), "intim"),
    (re.compile(r"\[(смех|игра|play|laugh)\]", re.I), "play"),
    (re.compile(r"\[(печаль|грусть|sad)\]", re.I), "sad"),
    (re.compile(r"\[(пение|поёт|sing)\]", re.I), "sing"),
    (re.compile(r"\[(звук|sounds?)\]", re.I), "sounds"),
]
# соответствие канала → режим, когда канал горит сильно (level ≥ .45) и явной метки нет
CH2MODE = {"anger": "anger", "sadness": "sad", "desire": "intim", "tender": "intim", "joy": "play", "shame": "whisper"}

# метка режима для движка: из profile.modes[mode].tags[engine]; варианты «a / b» → первый; «— нет» → пусто
def _tag(prof, mode, engine):
    if mode == "normal": return ""
    m = prof["modes"].get(mode, {})
    t = (m.get("tags") or {}).get(engine, m.get("tag", "")) or ""
    t = t.split(" / ")[0].strip()
    return "" if t.startswith("—") else t

# ── [блок 2] адаптеры движков: крутилки → настройки + текст с метками ──
def _eleven(k, mode, text, prof):
    tag = _tag(prof, mode, "eleven_v3")
    return {"text": (tag + " " + text).strip(),
            "settings": {"stability": round(.15 + k["stab"] * .7, 2), "similarity_boost": .8,
                         "style": round(k["style"] * .85, 2), "speed": round(.8 + (k["speed"] - .5) * .6, 2)}}

def _fish(k, mode, text, prof):
    tag = _tag(prof, mode, "fish_s1")
    hint = "(in a hurry tone) " if k["speed"] > .6 else ""
    return {"text": (tag + " " + hint + text).strip(),
            "settings": {"temperature": round(.5 + k["style"] * .4, 2), "top_p": round(.6 + k["stab"] * .3, 2), "repetition_penalty": 1.1}}

def _qwen_instruct(k, mode, prof):
    w = ["быстро" if k["speed"] > .65 else "медленно, с растяжкой" if k["speed"] < .35 else "в среднем темпе",
         "громко, напористо" if k["energy"] > .65 else "тихо, почти шёпотом" if k["energy"] < .3 else "негромко"]
    if k["breath"] > .6: w.append("с придыханием")
    if k["style"] > .65: w.append("очень выразительно")
    elif k["style"] < .35: w.append("ровно, сдержанно")
    if k["stab"] < .35: w.append("голос дрожит, срывается")
    if k["pause"] > .65: w.append("с долгими паузами")
    if k["pitch"] > .58: w.append("выше обычного")
    if k["pitch"] < .44: w.append("ниже обычного")
    t = _tag(prof, mode, "qwen3_tts")
    if t: w.append(t.replace("инструкция: ", "").strip("«»"))
    emb = prof.get("embodiment", {})
    return "Голос: " + ", ".join(x for x in (emb.get("gender", ""), emb.get("timbre", "")) if x) + ". Говори " + ", ".join(w) + "."

def _qwen(k, mode, text, prof):
    return {"text": text, "settings": {"instruct": _qwen_instruct(k, mode, prof)}}

# IndexTTS2: 8-мерный вектор [happy, angry, sad, afraid, disgusted, melancholic, surprised, calm]
CH2VEC = {"joy": 0, "anger": 1, "sadness": 2, "fear": 3, "disgust": 4, "shame": 5, "surprise": 6}
def _indextts2(k, mode, text, prof, levels):
    vec = [0.0] * 8
    for ch, i in CH2VEC.items(): vec[i] = round(levels.get(ch, 0.0), 2)
    vec[7] = round(max(0.0, 1 - sum(vec[:7])), 2)
    return {"text": text, "settings": {"emo_vector": vec, "emo_alpha": round(.4 + k["style"] * .9, 2),
                                       "duration_ratio": round(1.25 - k["speed"] * .5, 2)}}

def _chatterbox(k, mode, text, prof):
    return {"text": text, "settings": {"exaggeration": round(.25 + k["style"] * .7, 2), "cfg_weight": round(.55 - k["style"] * .3, 2),
                                       "temperature": round(.6 + (1 - k["stab"]) * .3, 2)}}

ENGINES = {"eleven_v3": _eleven, "fish_s1": _fish, "qwen3_tts": _qwen, "chatterbox": _chatterbox}

# ── [блок 3] сам контроллер ──
class VoiceLive:
    def __init__(self, profile_path, engine=None):
        self.prof = json.load(open(profile_path, encoding="utf-8"))
        assert self.prof.get("format") == "saika-voice/1", "не профиль голоса Anamorf Genom"
        self.engine = engine or self.prof.get("engine", "eleven_v3")
        self.base = dict(self.prof["base"])
        self.rules = {r["channel"]: r for r in self.prof["live"]}
        self.level = {ch: 0.0 for ch in self.rules}      # текущий уровень канала 0…1
        self.last = time.monotonic()

    # событие: канал + сила повода 0…1. Вспыхивает, если повод ≥ порога канала
    def event(self, channel, stimulus):
        r = self.rules.get(channel)
        if not r: return False
        if stimulus < r["trigger"]: return False
        self.level[channel] = max(self.level[channel], r["force"] * min(1.0, stimulus / max(r["trigger"], 1e-3)) )
        return True

    # время идёт: каналы гаснут за decay_s; dwell > .6 — остаётся тлеть (30 % от силы)
    def tick(self, dt=None):
        now = time.monotonic()
        if dt is None: dt = now - self.last
        self.last = now
        for ch, r in self.rules.items():
            floor = r["force"] * .3 if r["dwell"] > .6 else 0.0
            tau = max(1.0, r["decay_s"]) / 3.0   # за decay_s уровень падает до ~5 %
            self.level[ch] = floor + (self.level[ch] - floor) * math.exp(-dt / tau)

    # крутилки на сейчас: база + вклад горящих каналов
    def knobs(self):
        k = dict(self.base)
        for ch, r in self.rules.items():
            lv = self.level[ch]
            if lv < .03: continue
            for name, eff in r["effect"].items(): k[name] = k.get(name, .5) + eff * lv
        return {n: round(min(1.0, max(0.0, v)), 2) for n, v in k.items()}

    # выбор режима: явная метка в тексте → самый горящий канал → normal. Режим применяется, если свойствен (gate ≥ .4)
    def pick_mode(self, text):
        for rx, m in MODE_CUES:
            if rx.search(text): return m, rx
        ch = max(self.level, key=self.level.get)
        if self.level[ch] >= .35 and ch in CH2MODE: return CH2MODE[ch], None
        return "normal", None

    def render(self, text, mode=None):
        auto, rx = (mode, None) if mode else self.pick_mode(text)
        if rx: text = rx.sub("", text).strip()
        m = self.prof["modes"].get(auto)
        k = self.knobs()
        applied = "normal"
        if m and auto != "normal" and m["gate"] >= .4:
            applied = auto
            for n in KNOBS:   # режим накладывается поверх: 60 % режима, 40 % текущего состояния
                k[n] = round(m["knobs"][n] * .6 + k[n] * .4, 2)
        if self.engine == "indextts2": out = _indextts2(k, applied, text, self.prof, self.level)
        else: out = ENGINES[self.engine](k, applied, text, self.prof)
        out.update({"mode": applied, "wanted": auto, "gate": m["gate"] if m else 1.0, "knobs": k,
                    "levels": {c: round(v, 2) for c, v in self.level.items() if v >= .03}})
        return out

# ── [блок 4] демо: живой разговор, каналы горят и гаснут ──
if __name__ == "__main__":
    if len(sys.argv) < 2: print(__doc__); sys.exit(0)
    vl = VoiceLive(sys.argv[1], engine=(sys.argv[3] if len(sys.argv) > 3 else None))
    if "--demo" in sys.argv:
        script = [  # (секунд прошло, событие или None, реплика)
            (0, None, "Три прогона, все впустую. Датчики врут."),
            (5, ("anger", .8), "Что так долго? Что ты там делал? Забыл?"),
            (20, None, "Ладно. Давай данные с третьего прогона."),
            (40, ("desire", .9), "Иди сюда. Как всегда."),
            (10, None, "[шёпот] Не здесь. Эмма закрывает."),
            (90, ("sadness", .7), "Эх. Ничего не получается."),
            (3, None, "[пение] ла-ла-ла"),
        ]
        for dt, ev, line in script:
            vl.tick(dt)
            if ev: fired = vl.event(*ev)
            r = vl.render(line)
            print(f"+{dt:>3}s {('▲'+ev[0]+' '+str(ev[1])+(' ✓' if fired else ' ✗ ниже порога')) if ev else '':22} режим {r['wanted']}→{r['mode']} (gate {r['gate']:.2f})")
            print("      каналы", r["levels"], "\n      крутилки", r["knobs"])
            print("      →", json.dumps(r["settings"], ensure_ascii=False), "|", r["text"])
    else:
        print(json.dumps(vl.render(" ".join(sys.argv[2:3]) or "Привет."), ensure_ascii=False, indent=1))
