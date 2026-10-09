# -*- coding: utf-8 -*-
"""
[ШАГ 4] Оформление карточки: геном + корпус → char.json (alias, desc, identity, samples, never, masks, tensions, voice)

  python profile.py <id> --provider gigachat            # сам зовёт модель
  python profile.py <id> --emit                          # промпт в chars/<id>/prompts/profile.md
  python profile.py <id> --ingest ответ.json             # принять ответ внешней модели
Правило: поля, которые уже заполнены руками в char.json (name, ageStated, фото…), не затираются.
"""
import json, pathlib, argparse, re, sys

HERE = pathlib.Path(__file__).parent
TEMPLATE = (HERE / "profiler.md").read_text(encoding="utf-8")
NAMES = {g["id"]: g["name"] for b in json.loads((HERE / "genes.json").read_text(encoding="utf-8")) for g in b["genes"]}

def build(cdir, meta):
    G = json.loads((cdir / "genome.json").read_text(encoding="utf-8"))
    top = sorted(((k, v) for k, v in G.items() if v[1] > 0), key=lambda kv: -abs(kv[1][0]) * kv[1][1])[:40]
    genes = "\n".join(f"{k} · {NAMES.get(k,k)} · {v[0]:+.2f} · c={v[1]:.2f} · {v[2][0][1][:120] if v[2] else ''}" for k, v in top)
    text = ""
    for f in sorted((cdir / "corpus").glob("*.txt")):
        text += f.read_text(encoding="utf-8", errors="replace")[:9000] + "\n\n"
    return TEMPLATE.replace("{NAME}", meta["name"]).replace("{GENES}", genes).replace("{TEXT}", text[:40000])

def accept(cdir, meta, ans):
    m = re.search(r"\{.*\}", ans, flags=re.S)
    d = json.loads(m.group(0)) if m else {}
    for k, v in d.items():
        if k in ("name",): continue
        if k == "voice" and isinstance(meta.get("voice"), dict) and meta["voice"]:
            for kk, vv in v.items():
                if not meta["voice"].get(kk): meta["voice"][kk] = vv
        elif not meta.get(k): meta[k] = v
    (cdir / "char.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("карточка:", ", ".join(k for k in d))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("id"); ap.add_argument("--provider", default="gigachat"); ap.add_argument("--model"); ap.add_argument("--base"); ap.add_argument("--key"); ap.add_argument("--secrets")
    ap.add_argument("--emit", action="store_true"); ap.add_argument("--ingest"); a = ap.parse_args()
    cdir = pathlib.Path("chars") / a.id; meta = json.loads((cdir / "char.json").read_text(encoding="utf-8"))
    if a.ingest: accept(cdir, meta, pathlib.Path(a.ingest).read_text(encoding="utf-8")); return
    prompt = build(cdir, meta)
    if a.emit:
        (cdir / "prompts").mkdir(exist_ok=True); (cdir / "prompts" / "profile.md").write_text(prompt, encoding="utf-8"); print("промпт →", cdir / "prompts" / "profile.md"); return
    from llm import Client
    c = Client(a.provider, a.model, a.base, a.key, a.secrets)
    accept(cdir, meta, c.chat("Ты оформитель карточек персонажей. Отвечай только JSON-объектом.", prompt, temperature=0.3, max_tokens=3000))

if __name__ == "__main__":
    main()
