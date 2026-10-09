#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
persona.py — персона без нейронки: внешность (теги) + описание + главные ползунки + архетипы → геном → файл персонажа.

Четыре ступени, всё кодом:
  1. теги внешности (tagger.py или список)   → гены канала f, потолок c 0.3   (tags2genes.json)
  2. описание по-русски                       → гены канала k, c 0.4          (desc_lex.json, отрицание меняет знак)
  3. главные характеристики (7 ползунков) и архетипы (1–3) → гены c 0.6–0.7  (sigs.json)
  4. дорисовка по корреляциям                 → неснятые гены, c 0.25         (correlations.json)
Слияние улик на одном гене — формулой генома (§9): v' = (v·c + v₂·c₂)/(c+c₂), c' = min(1, c + c₂(1−c)).

Пример:
  python persona.py --name "Лаборантка" --sex женский --tags tags.json \
    --desc "юная изобретательница: игривая, любопытная, дерзкая, немного рассеянная, язвительная по-доброму, не любит правил, верна своим" \
    --main soc.playful=0.6 ag.curiosity=0.7 soc.sociable=0.4 will.discipline=-0.3 \
    --arch "Трикстер" "Новатор" --avatar face.jpg --out ../share
"""
import json, re, sys, argparse, base64, datetime, pathlib
HERE = pathlib.Path(__file__).parent
def load(n): return json.load(open(HERE / n, encoding="utf-8"))
GENES = load("genes.json"); TAGS = load("tags2genes.json"); LEX = load("desc_lex.json"); CORR = load("correlations.json"); SIGS = load("sigs.json")
IDS = {x["id"]: x for b in GENES for x in b["genes"]}; N = len(IDS)

# --- главные характеристики: подпись → ген (то же, что ползунки в панели студии) ---
MAIN = {"тепло": "soc.caring", "напор": "soc.dominance", "общительность": "soc.sociable", "игривость": "soc.playful",
        "дисциплина": "will.discipline", "тревожность": "dyn.fear.threshold", "любопытство": "ag.curiosity"}

def merge(G, gid, v, c, ev, same_source=False):
    """Слияние улики в ген по формуле генома. same_source=True — улики из одного источника (одно фото, одно описание):
    значение усредняется по весу, а уверенность берётся как max, не растёт от повторов (пять аксессуаров ≠ пять доказательств)."""
    if gid not in IDS: return
    v = max(-1.0, min(1.0, float(v)))
    if gid not in G: G[gid] = [v, c, [ev], 0]; return
    v0, c0, evs, sp = G[gid]
    if c0 > 0.5 and abs(v - v0) > 0.6: sp = 1
    v1 = (v0 * c0 + v * c) / (c0 + c); c1 = max(c0, c) if same_source else min(1.0, c0 + c * (1 - c0))
    G[gid] = [round(v1, 3), round(c1, 3), evs + [ev], sp]

def stage_tags(G, tags):
    """tags: {тег: вероятность} или список тегов. Уверенность = c_правила × p (потолок 0.3)."""
    if isinstance(tags, list): tags = {t: 1.0 for t in tags}
    hit = 0
    for tag, p in tags.items():
        rule = TAGS.get(tag.lower().replace("_", " "))
        if not rule: continue
        hit += 1
        for gid, v, c in rule: merge(G, gid, v, min(0.3, c * float(p)), ["f", f"внешность: {tag} ({float(p):.2f})"], same_source=True)
    return hit

INTENS = {"очень": 1.3, "крайне": 1.4, "жутко": 1.3, "слишком": 1.3, "довольно": 1.0, "немного": 0.5, "слегка": 0.5, "чуть": 0.5, "чуточку": 0.4, "иногда": 0.5, "порой": 0.5}
def stage_desc(G, text):
    """Сначала многословные основы (вырезаются из текста), потом слова.
    Инверсия относится только к соседнему слову (или к «не очень X»), иначе
    фраза «без приторности, спокойная» ошибочно делает спокойствие отрицательным.
    «очень/немного/слегка…» перед словом — множитель силы. Уверенность 0.4,
    повторы одного описания её не наращивают."""
    low = text.lower(); hit = []
    for phrase, rule in LEX.items():
        if " " in phrase and phrase in low:
            for gid, v in rule: merge(G, gid, v, 0.4, ["k", f"описание: «{phrase}»"], same_source=True)
            hit.append(phrase); low = low.replace(phrase, " ")
    words = re.findall(r"[а-яё]+", low)
    for i, w in enumerate(words):
        for stem, rule in LEX.items():
            if stem == "_" or " " in stem or not w.startswith(stem): continue
            p1 = words[i - 1] if i >= 1 else ""
            p2 = words[i - 2] if i >= 2 else ""
            # «не спокойная», «без грубости», «не очень шумная»;
            # не ищем отрицание в произвольных двух предыдущих словах.
            neg = p1 in ("не", "без", "ни") or (p2 == "не" and p1 in INTENS)
            k = INTENS.get(p1, 1.0)
            qualifier = " ".join(x for x in (p2 if p2 == "не" and p1 in INTENS else "", p1 if (neg or p1 in INTENS) else "", w) if x)
            for gid, v in rule: merge(G, gid, (-v if neg else v) * k, 0.4, ["k", f"описание: «{qualifier if (neg or k != 1) else w}»"], same_source=True)
            hit.append(("не " if neg else "") + w); break
    return hit

def stage_main(G, pairs):
    for k, v in pairs.items():
        gid = MAIN.get(k, k); vv = -float(v) if k == "тревожность" else float(v)   # порог страха: + = спокойная
        merge(G, gid, vv, 0.7, ["k", f"главная характеристика: {k} {float(v):+.1f}"])

def stage_arch(G, names, sex):
    picked = []
    for n in names:
        s = next((s for s in SIGS if s["n"] == n or s.get("nm") == n), None)
        if not s: print("архетип не найден:", n, file=sys.stderr); continue
        picked.append(s); nm = s["nm"] if sex == "мужской" and s.get("nm") else s["n"]
        for gid, lo, hi in s["c"]:
            if gid in G and G[gid][1] >= 0.4: continue   # явное (описание, ползунок) сильнее шаблона типа
            merge(G, gid, (lo + hi) / 2, 0.5, ["k", f"архетип «{nm}»: диапазон {lo}…{hi}"])
    return picked

def stage_fill(G):
    """Один проход от снятых к неснятым: v = clamp(Σ w·v_src·c_src / max(1, Σ|w|·c_src)·√n_src-ослабление), c = 0.25·(средняя c источников/0.6), вид улики d."""
    acc = {}
    for src, edges in CORR.items():
        if src == "_" or src not in G: continue
        v_src, c_src = G[src][0], G[src][1]
        if abs(v_src) < 0.15: continue
        for dst, w in edges:
            if dst in G: continue
            acc.setdefault(dst, []).append((w * v_src * c_src, abs(w) * c_src, IDS[src]["name"], v_src, w, c_src))
    for dst, L in acc.items():
        num = sum(x[0] for x in L); den = max(0.5, sum(x[1] for x in L))
        v = max(-1.0, min(1.0, num / den * min(1.0, den / 0.3)))   # один слабый источник (c 0.4, w 0.6 → den 0.24) даёт 80 % своего вклада
        if abs(v) < 0.1: continue
        cm = sum(x[5] for x in L) / len(L)
        G[dst] = [round(v, 3), round(min(0.3, 0.25 * cm / 0.6), 3), [["d", "дорисовка: " + "; ".join(f"{n} {vs:+.1f} × {w:+.1f}" for _, _, n, vs, w, _ in sorted(L, key=lambda x: -abs(x[0]))[:4])]], 0]
    return len(acc)

def build(name, sex, kind, tags=None, desc="", main=None, arch=(), avatar=None):
    G = {}; log = {}
    if main: stage_main(G, main); log["генов после главных"] = len(G)
    if desc: log["слова описания"] = stage_desc(G, desc); log["генов после описания"] = len(G)
    if tags: log["теги"] = stage_tags(G, tags); log["генов после внешности"] = len(G)
    picked = stage_arch(G, arch, sex) if arch else []; log["генов после архетипов"] = len(G)
    log["спорных"] = sum(1 for x in G.values() if x[3])
    before = len(G); stage_fill(G); log["дорисовано"] = len(G) - before; log["итого генов"] = len(G)
    tid = re.sub(r"[^a-z0-9_]+", "_", translit(name)).strip("_")[:28] or "persona"
    genome = {g: [v, c, ev] for g, (v, c, ev, sp) in G.items()}
    src_parts = [] + ([f"внешность: {log.get('теги',0)} тегов"] if tags else []) + (["описание"] if desc else []) + ([f"главные: {len(main)}"] if main else []) + ([f"архетипы: {', '.join(s['n'] for s in picked)}"] if picked else [])
    meta = {"kind": kind, "name": name, "alias": " · ".join(s["n"] for s in picked) or "персона без модели",
            "src": " · ".join(src_parts), "method": f"персона без модели: {before} генов задано, {log['дорисовано']} дорисовано по корреляциям (c 0.25)",
            "desc": desc, "identity": [], "samples": [], "never": [], "masks": [], "tensions": [],
            "voice": {"mode": "design", "gender": sex, "age": "", "lang": "русский", "timbre": ""}}
    obj = {"format": "saika-genome/1", "id": tid, "exported": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M"), "studio": "Anamorf Genom",
           "genes_total": N, "genes_captured": len(G), "meta": meta, "genome": genome}
    if avatar:
        p = pathlib.Path(avatar); ext = p.suffix.lower().lstrip(".").replace("jpg", "jpeg")
        obj["avatar"] = f"data:image/{ext};base64," + base64.b64encode(p.read_bytes()).decode()
    return obj, log

def translit(s):
    m = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", ["a","b","v","g","d","e","e","zh","z","i","y","k","l","m","n","o","p","r","s","t","u","f","h","c","ch","sh","sch","","y","","e","yu","ya"]))
    return "".join(m.get(ch, ch) for ch in s.lower())

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True); ap.add_argument("--sex", default="женский"); ap.add_argument("--kind", default="персонаж")
    ap.add_argument("--tags", help="json от tagger.py ({тег: p}) или список через запятую"); ap.add_argument("--desc", default="")
    ap.add_argument("--main", nargs="*", default=[], help="ген=значение или подпись=значение (тепло, напор, общительность, игривость, дисциплина, тревожность, любопытство)")
    ap.add_argument("--arch", nargs="*", default=[]); ap.add_argument("--avatar"); ap.add_argument("--out", default="../share")
    a = ap.parse_args()
    tags = None
    if a.tags:
        tags = json.load(open(a.tags, encoding="utf-8")) if a.tags.endswith(".json") else [t.strip() for t in a.tags.split(",")]
        if isinstance(tags, dict) and "tags" in tags: tags = tags["tags"]
    main = {k: float(v) for k, v in (x.split("=") for x in a.main)}
    obj, log = build(a.name, a.sex, a.kind, tags, a.desc, main, a.arch, a.avatar)
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True); f = out / f"{obj['id']}.genome.json"
    f.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(log, ensure_ascii=False, indent=1)); print("→", f)
