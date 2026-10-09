# -*- coding: utf-8 -*-
"""
[ШАГ 2] Следователь: корпус → улики на гены (chars/<id>/evidence.jsonl)

Как работает:
  1. корпус режется на фрагменты ~CHUNK символов по абзацам (эпизод/глава не рвётся посередине, если влезает);
  2. 345 генов делятся на ГРУППЫ блоков (--groups), чтобы промпт влезал в контекст любой модели;
  3. на каждую пару (фрагмент × группа) — один запрос к модели по investigator.md; ответ — JSON-массив улик;
  4. улики пишутся построчно в evidence.jsonl: {"g","v","c","q","src","kind","chunk"}.
     kind — код канала улики (w вики · k краткое содержание · n ранобэ/текст · t транскрипт · a просодия · f фото),
     потолок уверенности по kind: w/k 0.7, n 0.8, t 0.8, a 0.7, f 0.3.

Режимы:
  python investigate.py <id> --provider gigachat --model GigaChat-2-Pro          # сам зовёт модель
  python investigate.py <id> --emit                                             # только пишет промпты в chars/<id>/prompts/*.md
  python investigate.py <id> --ingest папка_с_ответами                          # читает ответы внешней модели (*.json) → evidence.jsonl
  --only dyn        — только гены динамики каналов (досъёмка);  --groups 4 — на сколько частей делить гены
Каждый прогон пишет chars/<id>/run.json: сколько запросов, токенов, секунд, сколько улик на группу — это данные для улучшения промпта.
"""
import re, sys, json, time, pathlib, argparse

HERE = pathlib.Path(__file__).parent
GENES = json.loads((HERE / "genes.json").read_text(encoding="utf-8"))
TEMPLATE = (HERE / "investigator.md").read_text(encoding="utf-8")
CAP = {"w": .7, "k": .7, "n": .8, "t": .8, "a": .7, "f": .3}
CHUNK = 7000

def kind_of(header):
    h = header.lower()
    if "википедия" in h or "wiki" in h: return "k" if ("season" in h or "сезон" in h or "film" in h or "фильм" in h or "list" in h) else "w"
    if "транскр" in h or "монолог" in h or ".txt" in h and "ролик" in h: return "t"
    if "глава" in h or "ранобэ" in h or "novel" in h: return "n"
    return "w"

def chunks(corpus_dir):
    """Каждый файл → список (src, kind, text) кусками ~CHUNK, режем по пустым строкам/абзацам."""
    out = []
    for f in sorted(pathlib.Path(corpus_dir).glob("*.txt")):
        t = f.read_text(encoding="utf-8", errors="replace")
        head = t.split("\n", 1)[0]; src = head.replace("# источник:", "").strip() or f.name
        kind = kind_of(head + " " + f.name)
        paras = re.split(r"\n\s*\n", t); buf = ""
        for p in paras:
            if len(buf) + len(p) > CHUNK and buf:
                out.append((src, kind, buf.strip())); buf = ""
            buf += p + "\n\n"
        if buf.strip(): out.append((src, kind, buf.strip()))
    return out

def gene_groups(n_groups, only=None):
    blocks = GENES
    if only: blocks = [b for b in GENES if b["block"] in only]
    n_groups = max(1, min(n_groups, len(blocks)))
    per = -(-len(blocks) // n_groups)          # ровно n_groups частей (последняя короче)
    return [blocks[i:i + per] for i in range(0, len(blocks), per)]

def gene_list(blocks):
    L = []
    for b in blocks:
        L.append(f"### {b['name']} ({b['block']})")
        for g in b["genes"]:
            L.append(f"{g['id']} · {g['name']} · −1 = {g.get('neg','')} · +1 = {g.get('pos','')}")
    return "\n".join(L)

def build_prompt(name, src, kind, text, blocks):
    return TEMPLATE.replace("{NAME}", name).replace("{CAP}", str(CAP[kind])).replace("{GENES}", gene_list(blocks)).replace("{SRC}", src).replace("{TEXT}", text)

def parse_json_array(s):
    """Модели любят оборачивать JSON в ```; вытаскиваем первый массив."""
    s = s.strip()
    m = re.search(r"\[.*\]", s, flags=re.S)
    if not m: return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        try: arr = json.loads(re.sub(r",\s*([\]}])", r"\1", m.group(0)))
        except Exception: return []
    return [x for x in arr if isinstance(x, dict) and "g" in x]

VALID = {g["id"] for b in GENES for g in b["genes"]}
def normalize(ev, kind, src, chunk_i):
    out = []
    for e in ev:
        g = str(e.get("g", "")).strip()
        if g not in VALID: continue
        try: v = max(-1.0, min(1.0, float(e.get("v", 0)))); c = max(.1, min(CAP[kind], float(e.get("c", .3))))
        except (TypeError, ValueError): continue
        out.append({"g": g, "v": round(v, 2), "c": round(c, 2), "q": str(e.get("q", ""))[:220], "src": src, "kind": kind, "chunk": chunk_i})
    return out

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("id")
    ap.add_argument("--provider", default="gigachat"); ap.add_argument("--model"); ap.add_argument("--base"); ap.add_argument("--key"); ap.add_argument("--secrets")
    ap.add_argument("--groups", type=int, default=4); ap.add_argument("--only", help="блоки через запятую, напр. dyn или dyn,emo")
    ap.add_argument("--emit", action="store_true"); ap.add_argument("--ingest"); ap.add_argument("--append", action="store_true", help="дописывать в evidence.jsonl, не затирать")
    a = ap.parse_args()
    cdir = pathlib.Path("chars") / a.id; meta = json.loads((cdir / "char.json").read_text(encoding="utf-8"))
    only = a.only.split(",") if a.only else None
    ch = chunks(cdir / "corpus"); groups = gene_groups(a.groups, only)
    evfile = cdir / "evidence.jsonl"; mode = "a" if a.append else "w"
    run = {"id": a.id, "chunks": len(ch), "groups": len(groups), "calls": 0, "evidence": 0, "per_group": [0] * len(groups), "started": time.strftime("%Y-%m-%d %H:%M")}
    if a.ingest:      # ответы внешней модели: файлы <chunk>_<group>.json
        n = 0
        with open(evfile, mode, encoding="utf-8") as out:
            for f in sorted(pathlib.Path(a.ingest).glob("*.json")):
                m = re.match(r"(\d+)_(\d+)", f.stem)
                if not m: continue
                ci, gi = int(m.group(1)), int(m.group(2)); src, kind, _ = ch[ci]
                for e in normalize(parse_json_array(f.read_text(encoding="utf-8")), kind, src, ci):
                    out.write(json.dumps(e, ensure_ascii=False) + "\n"); n += 1; run["per_group"][gi] += 1
        run["evidence"] = n; (cdir / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
        print("улик принято:", n); return
    if a.emit:        # промпты в файлы — для внешней модели
        pdir = cdir / "prompts"; pdir.mkdir(exist_ok=True)
        for ci, (src, kind, text) in enumerate(ch):
            for gi, blocks in enumerate(groups):
                (pdir / f"{ci:02d}_{gi}.md").write_text(build_prompt(meta["name"], src, kind, text, blocks), encoding="utf-8")
        print(f"промптов: {len(ch)}×{len(groups)} = {len(ch)*len(groups)} → {pdir}"); return
    from llm import Client
    c = Client(a.provider, a.model, a.base, a.key, a.secrets)
    ok, msg = c.ping(); print(msg)
    if not ok: sys.exit(1)
    with open(evfile, mode, encoding="utf-8") as out:
        for ci, (src, kind, text) in enumerate(ch):
            for gi, blocks in enumerate(groups):
                prompt = build_prompt(meta["name"], src, kind, text, blocks)
                try: ans = c.chat("Ты следователь генома. Отвечай только JSON-массивом.", prompt, temperature=0.1, max_tokens=3000)
                except Exception as e: print("сбой", ci, gi, e); continue
                ev = normalize(parse_json_array(ans), kind, src, ci)
                for e in ev: out.write(json.dumps(e, ensure_ascii=False) + "\n")
                run["calls"] += 1; run["evidence"] += len(ev); run["per_group"][gi] += len(ev)
                print(f"фрагмент {ci+1}/{len(ch)} группа {gi+1}/{len(groups)}: улик {len(ev)}")
    run["usage"] = c.usage; (cdir / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
    print("итого улик:", run["evidence"], "· запросов:", run["calls"], "· токенов:", c.usage["prompt"] + c.usage["completion"])

if __name__ == "__main__":
    main()
