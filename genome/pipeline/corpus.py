# -*- coding: utf-8 -*-
"""
[ШАГ 1] Сбор корпуса персонажа — сам ходит по вики и складывает тексты в chars/<id>/corpus/*.txt

Источники:
  - Википедия (любой язык) через MediaWiki API: страница персонажа, страницы сезонов/фильма с сюжетом
  - Fandom-вики через тот же API (?action=raw), разделы Personality / History / Relationships
  - локальные файлы: транскрипты, главы ранобэ, переписка — просто кладутся в corpus/

Запуск:
  python corpus.py <id> "<Имя>" --wiki en:Kaguya_Shinomiya --wiki "en:Kaguya-sama:_Love_Is_War_season_1" \
                   --fandom kaguyasama-wa-kokurasetai:Kaguya_Shinomiya --local файл.txt
Ничего не анализирует — только собирает. Каждый файл начинается со строки «# источник: …»,
её потом видит следователь и пишет в улику.
"""
import re, sys, json, argparse, pathlib, urllib.request, urllib.parse

UA = {"User-Agent": "GenomeStudio/1.0 (personality capture; contact: owner)"}

def http(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")

def wiki_extract(lang, title):
    """Чистый текст статьи Википедии (без разметки), через API extracts."""
    q = urllib.parse.urlencode({"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
                                "format": "json", "titles": title})
    d = json.loads(http(f"https://{lang}.wikipedia.org/w/api.php?{q}"))
    pages = d["query"]["pages"]
    return next(iter(pages.values())).get("extract", "")

def fandom_raw(wiki, title):
    """Исходник статьи Fandom (вики-разметка) → грубая очистка до текста."""
    url = f"https://{wiki}.fandom.com/wiki/{urllib.parse.quote(title)}?action=raw"
    t = http(url)
    t = re.sub(r"\{\{[^{}]*\}\}", "", t)            # шаблоны
    t = re.sub(r"\{\{[^{}]*\}\}", "", t)            # вложенные — второй проход
    t = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", t)  # [[ссылка|текст]] → текст
    t = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"'{2,}", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("id"); ap.add_argument("name")
    ap.add_argument("--wiki", action="append", default=[], help="lang:Title")
    ap.add_argument("--fandom", action="append", default=[], help="wikiname:Title")
    ap.add_argument("--local", action="append", default=[], help="путь к txt")
    a = ap.parse_args()
    out = pathlib.Path("chars") / a.id / "corpus"; out.mkdir(parents=True, exist_ok=True)
    n = 0
    for w in a.wiki:
        lang, title = w.split(":", 1)
        try:
            t = wiki_extract(lang, title)
        except Exception as e:
            print("wiki fail", w, e); continue
        if len(t) < 200: print("wiki empty", w); continue
        p = out / ("wiki_" + re.sub(r"[^\w]+", "_", title)[:60] + ".txt")
        p.write_text(f"# источник: Википедия ({lang}) · {title}\n\n{t}", encoding="utf-8"); n += 1
        print("ok", p, len(t))
    for f in a.fandom:
        wiki, title = f.split(":", 1)
        try:
            t = fandom_raw(wiki, title)
        except Exception as e:
            print("fandom fail", f, e); continue
        p = out / ("fandom_" + re.sub(r"[^\w]+", "_", title)[:60] + ".txt")
        p.write_text(f"# источник: {wiki}.fandom · {title}\n\n{t}", encoding="utf-8"); n += 1
        print("ok", p, len(t))
    for l in a.local:
        src = pathlib.Path(l); t = src.read_text(encoding="utf-8", errors="replace")
        p = out / ("local_" + src.stem + ".txt")
        p.write_text(f"# источник: файл · {src.name}\n\n{t}", encoding="utf-8"); n += 1
        print("ok", p, len(t))
    meta = pathlib.Path("chars") / a.id / "char.json"
    if not meta.exists():
        meta.write_text(json.dumps({"id": a.id, "name": a.name, "gender": "женский", "alias": "", "src": "", "voice": {}}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("файлов в корпусе:", n)

if __name__ == "__main__":
    main()
