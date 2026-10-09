# -*- coding: utf-8 -*-
"""corpus_mass.py — ступень 1 скоростного анализа: ВЕСЬ текст произведения на диск и все его эпизоды. Без модели, 0 ₽.

---- учебный блок: почему так ----
Модель дорогая и медленная (DeepSeek ~70 с на запрос), а скачать и порезать текст — бесплатно и параллельно.
Поэтому всё, что можно сделать кодом, делает код:
  1) скачать ВСЕ главы книги (по 8 одновременно), сохранить chars/<id>/corpus/0001.txt …
  2) в каждой главе найти его реплики (кавычки + имя рядом) и вырезать ЭПИЗОД: абзац до, реплика, абзац после;
  3) записать эпизоды в chars/<id>/episodes.jsonl с номером главы — номер главы = время в истории героя
     (по нему потом видно, как он менялся: трус в начале и Небесный Император в конце — разные люди).
Модель потом увидит не 1300 глав, а отобранную выжимку эпизодов (ступень 2).
Ход и цифры — в полосе работ (logs/corpus_<id>.json).

Запуск: py -3 corpus_mass.py <id> <адрес_книги_novelfull> <имя> [ещё имена через |]
"""
import sys, re, json, os, time, pathlib, threading, urllib.request
import concurrent.futures as cf
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36"}


def html(url, timeout=25, попыток=3):
    for п in range(попыток):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if п == попыток - 1: raise
            time.sleep(2 + 3 * п)


def текст_главы(код):
    """Текст главы со страницы novelfull: блок chapter-content, абзацы <p>."""
    m = re.search(r'id="chapter-content"[^>]*>(.*?)</div>\s*<div[^>]*(?:class="(?:text-center|chapter-nav)|id="chapter-nav)', код, re.S) \
        or re.search(r'id="chapter-content"[^>]*>(.*)', код, re.S)
    кусок = m.group(1) if m else код
    абзацы = [re.sub(r"<[^>]+>", "", p) for p in re.findall(r"<p[^>]*>(.*?)</p>", кусок, re.S)]
    import html as H
    return "\n".join(H.unescape(a).strip() for a in абзацы if a.strip())


def эпизоды(текст, ключи, глава):
    """Его реплики с контекстом: абзац до + абзац с репликой + абзац после."""
    абз = текст.split("\n"); out = []
    for i, a in enumerate(абз):
        for m in re.finditer(r'[“"]([^”"]{6,400})[”"]', a):
            рядом = re.sub(r"[^a-z]", "", (a[max(0, m.start() - 160):m.start()] + a[m.end():m.end() + 160]).lower())
            if any(k in рядом for k in ключи):
                out.append({"гл": глава, "реплика": m.group(1).strip(), "до": абз[i - 1][-400:] if i else "",
                            "абзац": a[:700], "после": абз[i + 1][:400] if i + 1 < len(абз) else ""})
                break
    return out


def main():
    ид, книга_url, имена = sys.argv[1], sys.argv[2], sys.argv[3].split("|")
    ключи = [re.sub(r"[^a-z]", "", n.lower()) for n in имена if re.sub(r"[^a-z]", "", n.lower())]
    книга = re.search(r"novelfull\.com/([a-z0-9\-]+)", книга_url).group(1).replace(".html", "")
    папка = ROOT / "chars" / ид / "corpus"; папка.mkdir(parents=True, exist_ok=True)
    журнал = ROOT / "chars" / ид / f"corpus_{time.strftime('%Y%m%d_%H%M%S')}"; журнал.mkdir(parents=True, exist_ok=True)
    указатель = ROOT / "logs" / f"corpus_{ид}.json"
    д = {"job": журнал.name, "pid": os.getpid(), "query": "весь текст произведения", "model": "без модели · 0 ₽",
         "started": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": "корпус"}
    lock = threading.Lock()
    def событие(stage, message, **доп):
        with lock:
            with (журнал / "events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "stage": stage, "message": message, **доп}, ensure_ascii=False) + "\n")
            указатель.write_text(json.dumps(д, ensure_ascii=False), encoding="utf-8")
    событие("plan", f"Скачиваю оглавление «{книга}»")
    первая = html(f"https://novelfull.com/{книга}.html")
    страниц = max([int(x) for x in re.findall(r"[?&]page=(\d+)", первая)] or [1])
    def оглавление(стр):
        код = первая if стр == 1 else html(f"https://novelfull.com/{книга}.html?page={стр}")
        return стр, list(dict.fromkeys(re.findall(r'href="(/' + re.escape(книга) + r'/chapter-[^"]+\.html)"', код)))
    ссылки = []
    with cf.ThreadPoolExecutor(8) as пул:
        for стр, s in sorted(пул.map(оглавление, range(1, страниц + 1))):
            ссылки += [x for x in s if x not in ссылки]
    д["всего_глав"] = len(ссылки)
    событие("plan", f"Глав в книге: {len(ссылки)} · качаю по 8 одновременно, уже скачанные пропускаю")
    готово = [0]; эп_всего = [0]; файл_эп = ROOT / "chars" / ид / "episodes.jsonl"
    def одна(пара):
        номер, путь = пара
        ф = папка / f"{номер:04d}.txt"
        if not ф.exists():
            try:
                ф.write_text(текст_главы(html("https://novelfull.com" + путь)), encoding="utf-8")
            except Exception as e:
                return номер, None, str(e)[:120]
        return номер, ф.read_text(encoding="utf-8"), None
    with файл_эп.open("w", encoding="utf-8") as вых, cf.ThreadPoolExecutor(8) as пул:
        for номер, текст, ош in пул.map(одна, enumerate(ссылки, 1)):
            готово[0] += 1
            if ош:
                событие("source_error", f"глава {номер}: {ош}"); continue
            э = эпизоды(текст, ключи, номер)
            for x in э:
                вых.write(json.dumps(x, ensure_ascii=False) + "\n")
            эп_всего[0] += len(э)
            д.update(глав_готово=готово[0], эпизодов=эп_всего[0])
            if готово[0] % 10 == 0 or готово[0] == len(ссылки):
                событие("source", f"Глав {готово[0]} из {len(ссылки)} · его эпизодов {эп_всего[0]}", replicas=len(э))
    д.update(finished=time.strftime("%Y-%m-%d %H:%M:%S"), state="done")
    событие("done", f"Корпус готов: {готово[0]} глав, его эпизодов {эп_всего[0]} · chars/{ид}/episodes.jsonl")


if __name__ == "__main__":
    main()
