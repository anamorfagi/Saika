"""Ставит НАТИВНЫЙ llama-server (llama.cpp, CUDA) в third_party/llamacpp.

ЗАЧЕМ ЭТО ВООБЩЕ (2026-07-27). До сих пор Сайка думала через чужие
программы: Ollama и LM Studio. Замер (tools/latency_bench.py) показал, чем
это кончается — LM Studio была поднята с окном 4096, молча резала промпт
вдвое, KV-кэш не работал ни разу, prefill шёл 640 ток/с на 4070 Ti SUPER.
Ни одну из этих ручек снаружи не покрутить: окно, flash-attention, offload,
переиспользование кэша — всё живёт в чужом GUI.

llama-server — тот же C++ движок, что и внутри LM Studio (llama.cpp), но
запускается нами, с нашими флагами, и говорит по OpenAI-совместимому API —
то есть код Сайки к нему подключается БЕЗ единой правки в стриме.

ПОЧЕМУ ГОТОВЫЙ БИНАРЬ, А НЕ llama-cpp-python. Биндинг отстаёт от upstream
на версию-две, требует CUDA-колеса под конкретный питон (в проекте уже есть
целая ветка фолбэка на случай, когда колеса нет) и добавляет питон в горячий
путь. Готовый .exe — это zip с GitHub: качается за минуту, обновляется
перезапуском этого же скрипта.

Запуск:
    .venv\\Scripts\\python setup\\install_llamacpp.py
    .venv\\Scripts\\python setup\\install_llamacpp.py --cuda 13.3
    .venv\\Scripts\\python setup\\install_llamacpp.py --force
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "third_party" / "llamacpp"
API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=12"

# Сборок под Windows две: под CUDA 12.4 и под 13.3. 12.4 берём по умолчанию —
# она работает на драйверах и постарше, а прироста от 13.3 на потребительской
# карте нет. Если драйвер свежий и хочется — --cuda 13.3.
DEFAULT_CUDA = "12.4"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _get(url: str, binary=False):
    # GitHub отдаёт 403 без User-Agent — это не блокировка, а требование API
    req = urllib.request.Request(url, headers={
        "User-Agent": "Saika-installer",
        "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    return data if binary else json.loads(data.decode("utf-8"))


def _total_size(url: str) -> int:
    """Сколько байт ДОЛЖНО приехать. Без этого числа обрыв связи неотличим
    от конца файла: read() возвращает b"" в обоих случаях — ровно так первая
    версия скачала 114 МБ из 235 и радостно пошла их распаковывать."""
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "Saika-installer"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return int(r.headers.get("Content-Length") or 0)
    except Exception:
        return 0


def _download(url: str, note: str, dest: Path) -> Path:
    """Качает с ДОКАЧКОЙ. Архив на 235 МБ по обычному домашнему каналу рвётся
    регулярно, и начинать каждый раз с нуля — издевательство. Недокачанное
    лежит рядом файлом .part: повторный запуск скрипта продолжает с того же
    места (HTTP Range), а не сначала. Имя .part содержит номер сборки, так
    что хвост от прошлого релиза не подмешается к новому."""
    tmp = dest.with_name(dest.name + ".part")
    total = _total_size(url)
    print(f"качаю {note} ({total >> 20 if total else '?'} МБ)…", flush=True)
    last_err = None
    for attempt in range(1, 7):
        have = tmp.stat().st_size if tmp.exists() else 0
        if total and have >= total:
            break
        headers = {"User-Agent": "Saika-installer"}
        if have:
            headers["Range"] = f"bytes={have}-"
            print(f"  докачиваю с {have >> 20} МБ (попытка {attempt})",
                  flush=True)
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as r:
                # 206 — сервер согласился отдать хвост; 200 на запрос с Range
                # означает «докачку не умею, держи всё сначала»
                resume = (getattr(r, "status", 200) == 206)
                if have and not resume:
                    have = 0
                with open(tmp, "ab" if have else "wb") as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        have += len(chunk)
                        if total:
                            print(f"\r  {have * 100 // total}% "
                                  f"({have >> 20}/{total >> 20} МБ)",
                                  end="", flush=True)
            print()
        except Exception as e:
            last_err = e
            print(f"\n  обрыв ({e}) — пробую дальше", flush=True)
            time.sleep(2)
            continue
        if not total or tmp.stat().st_size >= total:
            break
        print(f"  приехало {tmp.stat().st_size >> 20} из {total >> 20} МБ — "
              f"продолжаю", flush=True)

    got = tmp.stat().st_size if tmp.exists() else 0
    if total and got < total:
        raise RuntimeError(f"скачалось {got} из {total} байт "
                           f"({last_err or 'связь рвётся'}). Запусти скрипт "
                           f"ещё раз — докачает с этого места.")
    # ЧЕСТНАЯ ПРОВЕРКА перед распаковкой: битый или обрезанный архив должен
    # говорить «архив битый», а не «File is not a zip file» из недр zipfile
    if not zipfile.is_zipfile(tmp):
        tmp.unlink(missing_ok=True)
        raise RuntimeError("скачанный архив битый (удалила) — запусти "
                           "скрипт ещё раз")
    tmp.replace(dest)
    return dest


def _unzip_flat(path: Path, dest: Path):
    """Раскладываем ПЛОСКО: в архивах llama.cpp файлы лежат то в корне, то в
    build/bin/ — а нам нужен предсказуемый путь third_party/llamacpp/
    llama-server.exe, иначе спавнер будет его искать по всему дереву."""
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if not name:
                continue
            with z.open(info) as src, open(dest / name, "wb") as dst:
                shutil.copyfileobj(src, dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cuda", default=DEFAULT_CUDA,
                    help="версия CUDA-сборки (12.4 или 13.3)")
    ap.add_argument("--force", action="store_true",
                    help="переустановить, даже если уже стоит")
    a = ap.parse_args()

    exe = DEST / "llama-server.exe"
    if exe.exists() and not a.force:
        print(f"llama-server уже стоит: {exe}")
        print("переустановить: --force")
        return 0

    if os.name != "nt":
        print("этот установщик — под Windows (у проекта Windows-ветка). "
              "На другой ОС поставь llama.cpp пакетным менеджером и пропиши "
              "путь в config: llamacpp.binary")
        return 1

    try:
        rels = _get(API)
    except Exception as e:
        print(f"не достучалась до GitHub API: {e}")
        return 1

    # llama-b10144-bin-win-cuda-12.4-x64.zip + cudart-llama-bin-win-cuda-12.4-x64.zip
    pat_bin = re.compile(rf"^llama-.*-bin-win-cuda-{re.escape(a.cuda)}-x64\.zip$")
    pat_rt = re.compile(rf"^cudart-llama-bin-win-cuda-{re.escape(a.cuda)}-x64\.zip$")

    # БЕРЁМ НЕ «САМЫЙ СВЕЖИЙ», А СВЕЖАЙШИЙ ГОДНЫЙ (2026-07-27). llama.cpp
    # публикует релиз раньше, чем догружаются его файлы: у только что вышедшей
    # сборки в списке лежат cpu-архивы и cudart, а CUDA-сборки ещё нет —
    # /releases/latest честно её показывает, а качать нечего. Поэтому идём по
    # последним релизам вниз и берём первый, где нужный архив УЖЕ выложен.
    tag, assets, bin_name, rt_name = "", {}, None, None
    skipped = []
    for rel in (rels if isinstance(rels, list) else [rels]):
        if rel.get("draft"):
            continue
        cand = {x["name"]: x["browser_download_url"]
                for x in rel.get("assets", [])}
        nb = next((n for n in cand if pat_bin.match(n)), None)
        if not nb:
            skipped.append(rel.get("tag_name", "?"))
            continue
        tag, assets, bin_name = rel.get("tag_name", "?"), cand, nb
        rt_name = next((n for n in cand if pat_rt.match(n)), None)
        break
    if not bin_name:
        print(f"ни в одном из последних релизов нет сборки под CUDA {a.cuda}.")
        print("попробуй --cuda 13.3")
        return 1
    if skipped:
        print(f"пропустила (сборка под CUDA {a.cuda} ещё не выложена): "
              f"{', '.join(skipped)}")
    print(f"беру релиз llama.cpp: {tag}")

    if DEST.exists() and a.force:
        shutil.rmtree(DEST, ignore_errors=True)
    # архивы качаем в кэш рядом: недокачанное переживает перезапуск скрипта
    cache = DEST.parent / "_dl"
    cache.mkdir(parents=True, exist_ok=True)
    _unzip_flat(_download(assets[bin_name], bin_name, cache / bin_name), DEST)
    if rt_name:
        # без cudart-DLL рядом .exe стартует только если CUDA Toolkit
        # установлен в системе — а он у обычного пользователя не установлен
        _unzip_flat(_download(assets[rt_name], rt_name, cache / rt_name),
                    DEST)
    else:
        print("ВНИМАНИЕ: cudart-архива в релизе нет — если llama-server не "
              "стартует с ошибкой про cudart64_*.dll, поставь CUDA Toolkit")

    if not exe.exists():
        print(f"llama-server.exe не появился в {DEST} — архив с другой "
              f"раскладкой, посмотри что распаковалось")
        return 1

    (DEST / "VERSION.txt").write_text(f"{tag}\n{bin_name}\n",
                                      encoding="utf-8")
    # распакованное больше не зависит от архивов, а это 300+ МБ на диске
    shutil.rmtree(DEST.parent / "_dl", ignore_errors=True)
    print(f"\nготово: {exe}")
    print("проверить:  third_party\\llamacpp\\llama-server.exe --version")
    print("включить в Сайке:  config.json -> llm.backend = \"llamacpp\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
