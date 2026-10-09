#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scout.py — разведчик: имя + «откуда» → папка персоны с материалами для детального анализа.

Ступени (каждая пишет строку JSON в stdout: {"stage","msg","progress"} — панель студии показывает их живьём):
  1 identify   Википедия ru/en (+ фэндом-вики, если указано произведение): кто это, чем известен, дата рождения / канон-возраст, фото.
               ГЕЙТ: нет статьи ни в Википедии, ни в фэндом-вики → стоп, «дай корпус руками». По соцсетям частных людей разведчик не ходит.
               Возраст: живой человек младше 18 или персонаж-ребёнок → пометка kind/child, блок влечения не снимается.
  2 sources    тексты статей → corpus/; для живого человека — поиск интервью/подкастов на YouTube (yt-dlp ytsearch), отбор по длине и имени в названии;
               для персонажа — страницы вики по сериям/аркам.
  3 download   yt-dlp: аудио (m4a) + субтитры (ru/en, авто) → audio/, corpus/; фото из Википедии → photos/.
  4 transcribe субтитров нет → faster-whisper (если установлен) → corpus/*.txt с метками [m:ss].
  5 analyze    prosody.py по аудио → prosody.json; age_lex.py по транскриптам → age.json; tagger.py по фото → tags.json.
  6 handoff    corpus.py собирает фрагменты; sources.json — что откуда взято. Дальше: investigate.py → aggregate.py → profile.py (или «снять» в панели).

  python scout.py --name "Максим Киселёв" --origin "SNAILKICK youtube" --kind человек --out ../chars/snailkick --max-videos 3
  python scout.py --name "Кагуя Синомия" --origin "Kaguya-sama: Love is War" --kind персонаж --out ../chars/kaguya
Зависимости по желанию: pip install yt-dlp faster-whisper   (без них — только тексты и фото)
"""
import sys, os, re, json, argparse, pathlib, subprocess, shutil, datetime, urllib.request, urllib.parse
HERE = pathlib.Path(__file__).parent
UA = {"User-Agent": "AnamorfGenom-scout/1.0 (personal research tool)"}
def say(stage, msg, progress=None, **kw):
    d = {"stage": stage, "msg": msg}; d.update(kw)
    if progress is not None: d["progress"] = round(progress, 3)
    print(json.dumps(d, ensure_ascii=False), flush=True)

def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r: return r.read()
def getj(url): return json.loads(get(url).decode("utf-8"))

# ---------- 1. опознание ----------
def wiki_search(lang, q):
    u = f"https://{lang}.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(q)}&srlimit=5&format=json"
    return [(h["title"], h.get("snippet", "")) for h in getj(u).get("query", {}).get("search", [])]
def wiki_page(lang, title):
    u = f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=extracts|pageimages|pageprops&explaintext=1&piprop=original&titles={urllib.parse.quote(title)}&format=json"
    pages = getj(u).get("query", {}).get("pages", {})
    for p in pages.values():
        return {"title": p.get("title"), "text": p.get("extract", ""), "image": (p.get("original") or {}).get("source"), "wikibase": (p.get("pageprops") or {}).get("wikibase_item")}
    return None
def wikidata_facts(qid):
    """P569 дата рождения, P106 род занятий, P31 (человек/персонаж), P27 гражданство — по-русски через labels."""
    try:
        d = getj(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")["entities"][qid]
    except Exception: return {}
    cl = d.get("claims", {}); out = {}
    def first(p):
        try: return cl[p][0]["mainsnak"]["datavalue"]["value"]
        except Exception: return None
    b = first("P569")
    if b and isinstance(b, dict): out["birth"] = b.get("time", "").lstrip("+")[:10]
    inst = first("P31")
    if inst: out["instance"] = inst.get("id")
    occ = [c["mainsnak"]["datavalue"]["value"]["id"] for c in cl.get("P106", []) if "datavalue" in c["mainsnak"]]
    if occ: out["occupations_q"] = occ[:6]
    out["labels"] = {k: v["value"] for k, v in d.get("labels", {}).items() if k in ("ru", "en")}
    out["desc"] = {k: v["value"] for k, v in d.get("descriptions", {}).items() if k in ("ru", "en")}
    return out
def fandom_search(origin, q):
    """Фэндом-вики произведения: поддомен угадывается из названия (kaguya-sama, date-a-live…)."""
    slug = re.sub(r"[^a-z0-9]+", "-", origin.lower()).strip("-")
    cands = [slug, slug.split("-")[0]]
    for s in cands:
        try:
            u = f"https://{s}.fandom.com/api.php?action=query&list=search&srsearch={urllib.parse.quote(q)}&srlimit=3&format=json"
            hits = getj(u).get("query", {}).get("search", [])
            if hits:
                t = hits[0]["title"]
                pg = getj(f"https://{s}.fandom.com/api.php?action=query&prop=extracts&explaintext=1&titles={urllib.parse.quote(t)}&format=json")
                for p in pg["query"]["pages"].values(): return {"site": s, "title": t, "text": p.get("extract", "")}
        except Exception: continue
    return None

def identify(name, origin, kind):
    q = f"{name} {origin}".strip(); found = {"wiki": {}, "fandom": None, "facts": {}}
    for lang in ("ru", "en"):
        try:
            hits = wiki_search(lang, q) or wiki_search(lang, name)
            if not hits: continue
            title = hits[0][0]; pg = wiki_page(lang, title)
            if pg and len(pg["text"]) > 400:
                found["wiki"][lang] = pg; say("identify", f"Википедия {lang}: «{title}», {len(pg['text'])//1000}k символов")
                if pg.get("wikibase") and not found["facts"]: found["facts"] = wikidata_facts(pg["wikibase"])
        except Exception as e: say("identify", f"Википедия {lang}: {e}")
    if origin and kind == "персонаж":
        fd = fandom_search(origin, name)
        if fd: found["fandom"] = fd; say("identify", f"фэндом-вики {fd['site']}: «{fd['title']}», {len(fd['text'])//1000}k")
    return found

def age_gate(found, kind):
    """Возраст: для человека — по дате рождения; для персонажа — по тексту статьи (лет / years old / школьница)."""
    f = found.get("facts", {}); today = datetime.date.today()
    if kind == "человек" and f.get("birth"):
        try:
            y, m, d = [int(x) for x in f["birth"].split("-")[:3]]; age = today.year - y - ((today.month, today.day) < (m, d))
            return {"age": age, "child": age < 18, "how": "дата рождения " + f["birth"]}
        except Exception: pass
    text = " ".join(p["text"][:4000] for p in found["wiki"].values()) + " " + ((found.get("fandom") or {}).get("text", "")[:4000])
    m = re.search(r"(\d{1,2})\s*(?:лет|года|год)\b|(\d{1,2})[- ]year[- ]old", text)
    if m:
        age = int(m.group(1) or m.group(2)); return {"age": age, "child": age < 18, "how": "возраст в статье"}
    if re.search(r"школьни|старшеклассни|ученица|ученик|high school student|middle school", text, re.I):
        return {"age": None, "child": True, "how": "в статье — школьник"}
    return {"age": None, "child": False, "how": "не определён"}

# ---------- 2–3. источники и скачивание ----------
def ytdlp_ok(): return shutil.which("yt-dlp") is not None or subprocess.run([sys.executable, "-m", "yt_dlp", "--version"], capture_output=True).returncode == 0
def ytdlp(*args):
    cmd = (["yt-dlp"] if shutil.which("yt-dlp") else [sys.executable, "-m", "yt_dlp"]) + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
def yt_search(name, extra, n=15):
    r = ytdlp(f"ytsearch{n}:{name} {extra}", "--dump-json", "--flat-playlist", "--no-warnings", "--skip-download")
    out = []
    for line in r.stdout.splitlines():
        try:
            j = json.loads(line); out.append({"id": j.get("id"), "title": j.get("title", ""), "duration": j.get("duration") or 0, "channel": j.get("channel") or j.get("uploader", ""), "url": j.get("url") or f"https://www.youtube.com/watch?v={j.get('id')}"})
        except Exception: pass
    return out
def pick_videos(vids, name, k=3):
    """Интервью/подкасты: 10–150 минут, имя в названии — предпочтительно; сцены/нарезки — нет."""
    key = name.split()[0].lower()
    good = [v for v in vids if 600 <= v["duration"] <= 9000 and not re.search(r"нарезк|shorts|клип|тизер|trailer|compilation|best of", v["title"], re.I)]
    good.sort(key=lambda v: (key not in v["title"].lower(), -v["duration"]))
    return good[:k]
def download(vid, outdir: pathlib.Path):
    aud = outdir / "audio"; aud.mkdir(exist_ok=True)
    r = ytdlp(vid["url"], "-x", "--audio-format", "m4a", "--audio-quality", "5", "-o", str(aud / f"{vid['id']}.%(ext)s"),
              "--write-auto-subs", "--write-subs", "--sub-langs", "ru,en", "--sub-format", "vtt", "--no-warnings", "--no-playlist")
    subs = list(aud.glob(f"{vid['id']}*.vtt")); return r.returncode == 0, subs
def vtt_to_txt(vtt: pathlib.Path, txt: pathlib.Path):
    """VTT → строки [m:ss] текст, без дублей авто-субтитров."""
    lines = []; last = ""
    for block in vtt.read_text(encoding="utf-8", errors="ignore").split("\n\n"):
        m = re.search(r"(\d+):(\d+):(\d+)\.\d+ -->", block)
        if not m: continue
        t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        text = " ".join(re.sub(r"<[^>]+>", "", l).strip() for l in block.splitlines()[1:] if "-->" not in l).strip()
        if text and text != last: lines.append(f"[{t//60}:{t%60:02d}] {text}"); last = text
    txt.write_text("\n".join(lines), encoding="utf-8"); return len(lines)

# ---------- 4. транскрипция ----------
def transcribe(audio: pathlib.Path, txt: pathlib.Path, lang="ru"):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _ = model.transcribe(str(audio), language=lang, vad_filter=True)
    lines = [f"[{int(s.start)//60}:{int(s.start)%60:02d}] {s.text.strip()}" for s in segs]
    txt.write_text("\n".join(lines), encoding="utf-8"); return len(lines)

# ---------- 5. анализ ----------
def run_tool(script, *args):
    r = subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=900)
    return r.stdout.strip(), r.stderr.strip()[-300:]

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True); ap.add_argument("--origin", default=""); ap.add_argument("--kind", default="человек", choices=["человек", "персонаж", "ии"])
    ap.add_argument("--out", required=True); ap.add_argument("--max-videos", type=int, default=3); ap.add_argument("--lang", default="ru")
    ap.add_argument("--mock", help="папка с заглушками вместо сети (для теста конвейера)")
    a = ap.parse_args()
    if not a.mock and os.environ.get("SCOUT_MOCK"): a.mock = os.environ["SCOUT_MOCK"]   # для тестов конвейера без сети
    out = pathlib.Path(a.out); (out / "corpus").mkdir(parents=True, exist_ok=True); (out / "photos").mkdir(exist_ok=True)
    src = {"name": a.name, "origin": a.origin, "kind": a.kind, "started": datetime.datetime.now().isoformat(timespec="minutes"), "texts": [], "audio": [], "photos": [], "notes": []}

    # 1
    say("identify", f"ищу «{a.name}» ({a.origin or 'без уточнения'})…", 0.02)
    if a.mock:
        found = json.load(open(pathlib.Path(a.mock) / "found.json", encoding="utf-8"))
    else:
        found = identify(a.name, a.origin, a.kind)
    if not found["wiki"] and not found.get("fandom"):
        say("stop", "публичных источников не нашлось (нет статьи в Википедии и фэндом-вики). Разведчик по частным людям не ходит — положи корпус в папку руками.", 1.0, ok=False)
        json.dump(src, open(out / "sources.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1); return 2
    gate = age_gate(found, a.kind); src["age"] = gate
    say("identify", f"возраст: {gate['age'] if gate['age'] is not None else '—'} ({gate['how']})" + (" · ребёнок: блок влечения не снимается" if gate["child"] else ""), 0.1)
    facts = found.get("facts", {})
    if facts: src["facts"] = facts; say("identify", "wikidata: " + "; ".join(f"{k}={v}" for k, v in facts.items() if k in ("birth", "desc")), 0.12)

    # 2 тексты
    for lang, pg in found["wiki"].items():
        f = out / "corpus" / f"wiki_{lang}.txt"; f.write_text(pg["text"], encoding="utf-8"); src["texts"].append({"file": f.name, "kind": "w", "title": pg["title"], "chars": len(pg["text"])})
        if pg.get("image") and not src["photos"]:
            try:
                img = get(pg["image"]); ext = ".jpg" if b"JFIF" in img[:20] or pg["image"].lower().endswith(("jpg", "jpeg")) else ".png"
                (out / "photos" / ("main" + ext)).write_bytes(img); src["photos"].append("main" + ext); say("sources", "фото из Википедии", 0.18)
            except Exception as e: src["notes"].append("фото: " + str(e))
    if found.get("fandom"):
        fd = found["fandom"]; f = out / "corpus" / "fandom.txt"; f.write_text(fd["text"], encoding="utf-8"); src["texts"].append({"file": f.name, "kind": "w", "title": fd["title"], "chars": len(fd["text"])})
    say("sources", f"текстов: {len(src['texts'])}", 0.22)

    # 2–3 видео (только живые люди: интервью/подкасты)
    if a.kind == "человек" and a.max_videos > 0:
        if a.mock:
            vids = json.load(open(pathlib.Path(a.mock) / "videos.json", encoding="utf-8"))
        elif ytdlp_ok():
            vids = yt_search(a.name, "интервью OR подкаст OR interview"); say("sources", f"YouTube: найдено {len(vids)} видео", 0.28)
        else:
            vids = []; src["notes"].append("yt-dlp не установлен: pip install yt-dlp — без него нет аудио и транскриптов"); say("sources", "yt-dlp не установлен — аудио пропускаю", 0.28)
        picked = pick_videos(vids, a.name, a.max_videos)
        for i, v in enumerate(picked):
            say("download", f"{v['title'][:70]} · {v['duration']//60} мин · {v['channel']}", 0.3 + 0.3 * i / max(1, len(picked)))
            if a.mock:
                ok, subs = True, []
                (out / "audio").mkdir(exist_ok=True); shutil.copy(pathlib.Path(a.mock) / "sample.txt", out / "corpus" / f"yt_{v['id']}.txt")
            else:
                ok, subs = download(v, out)
            if not ok and not a.mock: src["notes"].append(f"не скачалось: {v['url']}"); continue
            entry = {"id": v["id"], "url": v["url"], "title": v["title"], "duration": v["duration"], "channel": v["channel"], "audio": f"audio/{v['id']}.m4a", "transcript": None}
            txt = out / "corpus" / f"yt_{v['id']}.txt"
            if subs:
                ru = [s for s in subs if ".ru." in s.name] or subs; n = vtt_to_txt(ru[0], txt); entry["transcript"] = txt.name; entry["transcript_from"] = "субтитры"; say("transcribe", f"субтитры → {n} строк", None)
            elif (out / entry["audio"]).exists():
                n = transcribe(out / entry["audio"], txt, a.lang)
                if n: entry["transcript"] = txt.name; entry["transcript_from"] = "faster-whisper"; say("transcribe", f"whisper → {n} строк", None)
                else: src["notes"].append("faster-whisper не установлен: pip install faster-whisper — транскрипта нет, только просодия")
            elif a.mock: entry["transcript"] = txt.name; entry["transcript_from"] = "заглушка"
            src["audio"].append(entry)
            if entry["transcript"]: src["texts"].append({"file": txt.name, "kind": "t", "title": v["title"], "chars": txt.stat().st_size})

    # 5 анализ
    say("analyze", "просодия / возраст по речи / теги внешности…", 0.65)
    for e in src["audio"]:
        au = out / e["audio"]
        if au.exists() and (HERE / "prosody.py").exists():
            o, err = run_tool("prosody.py", str(au)); e["prosody"] = o[:2000] or err
    tr = [out / "corpus" / e["transcript"] for e in src["audio"] if e.get("transcript")]
    if tr and (HERE / "age_lex.py").exists():
        o, err = run_tool("age_lex.py", *[str(t) for t in tr]); (out / "age.json").write_text(o or err, encoding="utf-8"); brief = o
        try: j = json.loads(o); brief = ", ".join(f"{k}: {v}" for k, v in j.items() if not isinstance(v, (dict, list)))[:160]
        except Exception: brief = (o.replace("\n", " ")[:160] if o else err[:120])
        say("analyze", "возраст по речи: " + brief, 0.8)
    for ph in src["photos"]:
        if (HERE / "tagger.py").exists():
            o, err = run_tool("tagger.py", str(out / "photos" / ph)); (out / "tags.json").write_text(o or json.dumps({"error": err}), encoding="utf-8"); say("analyze", "теги внешности: " + (o[:100].replace("\n", " ") if o else err[:100]), 0.88)

    # 6 корпус
    corpus = out / "corpus.txt"
    with open(corpus, "w", encoding="utf-8") as f:
        for t in src["texts"]:
            f.write(f"\n\n## {t['title']} [{t['kind']}]\n\n" + (out / "corpus" / t["file"]).read_text(encoding="utf-8", errors="ignore"))
    src["corpus_chars"] = corpus.stat().st_size; src["finished"] = datetime.datetime.now().isoformat(timespec="minutes")
    json.dump(src, open(out / "sources.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    say("done", f"собрано: текстов {len(src['texts'])}, аудио {len(src['audio'])}, фото {len(src['photos'])}; корпус {src['corpus_chars']//1000}k символов → {out}", 1.0, ok=True,
        corpus=str(corpus), child=gate["child"], notes=src["notes"])
    return 0

if __name__ == "__main__":
    try: sys.exit(main())
    except KeyboardInterrupt: sys.exit(130)
    except Exception as e: say("error", str(e), 1.0, ok=False); sys.exit(1)
