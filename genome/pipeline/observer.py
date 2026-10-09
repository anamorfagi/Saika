# -*- coding: utf-8 -*-
"""
[ФУНКЦИЯ 3] Наблюдение — следователь на живом потоке (спека §9).

Поток = транскрипт с метками времени: строки «[m:ss] текст» (так пишет слух Сайки и так лежат «Мюсли» Макса).
Каждые STEP секунд берётся окно последних WINDOW секунд речи → один запрос следователю (kind t, потолок 0.8) →
улики сливаются в текущий геном формулой
    v' = (v·c + v_new·c_new)/(c + c_new),  c' = min(1, c + c_new·(1−c));  |v_new − v| > 0.6 при c > 0.5 → «спорный».
Каждое событие пишется с временем — из этого строится лента «геном меняется на глазах».

Режимы:
  python observer.py <id> --transcript a.txt [b.txt …] --emit                 # промпты по окнам → chars/<id>/obs_prompts/NN.md
  python observer.py <id> --transcript … --ingest chars/<id>/obs_answers      # ответы внешней модели → timeline.json
  python observer.py <id> --transcript … --provider gigachat                  # сам зовёт модель
  python observer.py <id> --follow live.txt --provider …                      # живой режим: файл дописывается, окна считаются по мере роста
Выход: chars/<id>/timeline.json = {"windows":[{t0,t1,n_ev,captured,conf,top}], "events":[{t,g,v0,v1,c0,c1,q,spor}], "final":{gene:[v,c,[evidence]]}}
"""
import re, sys, json, time, pathlib, argparse
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from investigate import GENES, TEMPLATE, VALID, parse_json_array, gene_list

WINDOW, STEP = 180, 180     # секунд: окно и шаг; для живого режима можно 90/45

def parse_transcript(paths):
    """→ [(t_sec, text)], файлы идут один за другим, время сквозное."""
    out, base = [], 0
    for p in paths:
        last = 0
        for line in pathlib.Path(p).read_text(encoding="utf-8", errors="replace").splitlines():
            # два формата: «[m:ss] текст» (слух Сайки) и «m:ssM минут(ы) S секунд(ы)текст» (копия с YouTube)
            m = re.match(r"\s*\[(\d+):(\d{2})\]\s*(.*)", line) or re.match(r"\s*(\d+):(\d{2})\d+ минут[аы]? \d+ секунд[аы]?\s*(.*)", line)
            if not m: continue
            t = int(m.group(1)) * 60 + int(m.group(2)); last = max(last, t)
            out.append((base + t, m.group(3).strip(), pathlib.Path(p).stem))
        base += last + 10
    return out

def windows(utts, window=WINDOW, step=STEP):
    if not utts: return []
    T = utts[-1][0]; out = []; t1 = step
    while t1 <= T + step:
        t0 = max(0, t1 - window); seg = [u for u in utts if t0 <= u[0] < t1]
        if seg: out.append((t0, min(t1, T + 1), seg))
        t1 += step
    return out

def mmss(t): return f"{int(t)//60}:{int(t)%60:02d}"

def build_prompt(name, w):
    t0, t1, seg = w
    text = "\n".join(f"[{mmss(u[0])}] {u[1]}" for u in seg)
    src = f"{seg[0][2]} · окно {mmss(t0)}–{mmss(t1)}"
    return TEMPLATE.replace("{NAME}", name).replace("{CAP}", "0.8").replace("{GENES}", gene_list(GENES)).replace("{SRC}", src).replace("{TEXT}", text)

class State:
    def __init__(self): self.G = {}; self.events = []
    def merge(self, t, e):
        g = e["g"]; v0, c0, ev, spor = self.G.get(g, [0.0, 0.0, [], False])
        vn = max(-1, min(1, float(e["v"]))); cn = max(.1, min(.8, float(e.get("c", .3))))
        q = str(e.get("q", ""))[:200]
        if any(x[1].startswith(q[:60]) for x in ev): return None        # та же улика дважды — не двигает
        m = re.search(r"\[(\d+):(\d{2})\]", q)                        # время события — метка из цитаты, иначе конец окна
        if m: t = min(t, int(m.group(1)) * 60 + int(m.group(2)))
        if c0 == 0: v1, c1, s = vn, cn, False
        else: v1, c1, s = (v0 * c0 + vn * cn) / (c0 + cn), min(1, c0 + cn * (1 - c0)), abs(vn - v0) > .6 and c0 > .5
        self.G[g] = [round(v1, 3), round(c1, 3), ev + [["t", f"{q} — {mmss(t)}"]], spor or s]
        evn = {"t": t, "g": g, "v0": round(v0, 2), "v1": round(v1, 2), "c0": round(c0, 2), "c1": round(c1, 2), "q": q, "spor": bool(s)}
        self.events.append(evn); return evn
    def stats(self):
        cap = [x for x in self.G.values() if x[1] > 0]
        return len(cap), round(sum(x[1] for x in cap) / len(cap), 2) if cap else 0

def run(name, wins, answer_for, out_path):
    st = State(); W = []
    for i, w in enumerate(wins):
        ans = answer_for(i, w)
        ev = [e for e in parse_json_array(ans or "[]") if e.get("g") in VALID]
        def tq(e):                                                     # улики внутри окна — в порядке времени их цитат
            m = re.search(r"\[(\d+):(\d{2})\]", str(e.get("q", ""))); return int(m.group(1)) * 60 + int(m.group(2)) if m else w[1]
        ev.sort(key=tq)
        moved = [x for x in (st.merge(w[1], e) for e in ev) if x]
        cap, conf = st.stats()
        top = sorted(moved, key=lambda x: -abs(x["v1"] - x["v0"]) * x["c1"])[:5]
        W.append({"t0": w[0], "t1": w[1], "n_ev": len(moved), "captured": cap, "conf": conf, "top": [[x["g"], x["v0"], x["v1"]] for x in top]})
        print(f"окно {mmss(w[0])}–{mmss(w[1])}: улик {len(moved)} · снято {cap} · уверенность {conf}")
    res = {"window": WINDOW, "step": STEP, "windows": W, "events": st.events, "final": st.G}
    pathlib.Path(out_path).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print("событий:", len(st.events), "→", out_path)

def main():
    global WINDOW, STEP
    ap = argparse.ArgumentParser(); ap.add_argument("id")
    ap.add_argument("--transcript", nargs="+"); ap.add_argument("--follow")
    ap.add_argument("--provider"); ap.add_argument("--model"); ap.add_argument("--base"); ap.add_argument("--key"); ap.add_argument("--secrets")
    ap.add_argument("--emit", action="store_true"); ap.add_argument("--ingest")
    ap.add_argument("--window", type=int, default=WINDOW); ap.add_argument("--step", type=int, default=STEP)
    a = ap.parse_args(); WINDOW, STEP = a.window, a.step
    cdir = pathlib.Path("chars") / a.id; meta = json.loads((cdir / "char.json").read_text(encoding="utf-8")); name = meta["name"]
    if a.follow:   # живой режим: файл растёт, каждое новое окно — запрос
        from llm import Client
        c = Client(a.provider or "gigachat", a.model, a.base, a.key, a.secrets); st = State(); done = 0; out = cdir / "timeline_live.json"
        while True:
            utts = parse_transcript([a.follow]); wins = windows(utts, WINDOW, STEP)
            for w in wins[done:]:
                ans = c.chat("Ты следователь генома. Отвечай только JSON-массивом.", build_prompt(name, w), temperature=.1, max_tokens=3000)
                for e in parse_json_array(ans):
                    if e.get("g") in VALID: st.merge(w[1], e)
                cap, conf = st.stats(); done += 1; print(f"[{mmss(w[1])}] снято {cap} · уверенность {conf} · событий {len(st.events)}")
                out.write_text(json.dumps({"events": st.events, "final": st.G}, ensure_ascii=False), encoding="utf-8")
            time.sleep(5)
    utts = parse_transcript(a.transcript); wins = windows(utts, WINDOW, STEP)
    print(f"реплик {len(utts)} · длительность {mmss(utts[-1][0])} · окон {len(wins)}")
    if a.emit:
        pd = cdir / "obs_prompts"; pd.mkdir(exist_ok=True)
        for i, w in enumerate(wins): (pd / f"{i:02d}.md").write_text(build_prompt(name, w), encoding="utf-8")
        print("промптов →", pd); return
    if a.ingest:
        ad = pathlib.Path(a.ingest)
        run(name, wins, lambda i, w: (ad / f"{i:02d}.json").read_text(encoding="utf-8") if (ad / f"{i:02d}.json").exists() else "[]", cdir / "timeline.json"); return
    from llm import Client
    c = Client(a.provider or "gigachat", a.model, a.base, a.key, a.secrets)
    run(name, wins, lambda i, w: c.chat("Ты следователь генома. Отвечай только JSON-массивом.", build_prompt(name, w), temperature=.1, max_tokens=3000), cdir / "timeline.json")
    print("токены/время:", c.usage)

if __name__ == "__main__":
    main()
