"""Свой движок Сайки: нативный llama-server (llama.cpp, CUDA).

ЗАЧЕМ (2026-07-27). Мозги жили в чужих программах — Ollama и LM Studio.
Замер вскрыл, чем это кончилось: LM Studio была поднята с окном 4096, молча
резала промпт вдвое (Сайка теряла системный промпт и половину истории, не
подавая виду), KV-кэш не срабатывал ни разу — повтор того же запроса стоил
столько же, сколько первый, — а prefill шёл 640 ток/с на 4070 Ti SUPER.
Ни одну из этих ручек снаружи не покрутить: они живут в чужом GUI.

llama-server — тот же C++ движок (llama.cpp), что внутри LM Studio, но
поднимаем его мы, своими флагами, и он говорит по OpenAI-совместимому API:
в manager.py для него не нужен новый стрим, годится общий _stream_openai.

Контракт как у остальных спавнеров проекта (dreampc.py, locallm.py):
    ensure_running() -> {"ok":True,"port":N} | {"error":…} | {"installing":True}

ГРАБЛИ, УЧТЁННЫЕ ЗДЕСЬ

- Флаги llama.cpp меняются между сборками (у -fa то булев вид, то on|off|auto;
  --reasoning-budget появился не сразу). Поэтому аргументы разложены на ЯРУСЫ:
  если сервер умер на старте, снимаем необязательный ярус и пробуем снова, а
  снятое пишем в лог. Гадать про версию сборки не надо — она сама скажет.
- Порт свой (8771), не 1234 и не 11434: LM Studio и Ollama могут остаться
  запущенными, и пересечься с ними нельзя.
- Модель ищем в том числе в каталоге LM Studio — GGUF там уже скачан, второй
  раз тянуть 3-8 ГБ незачем.
"""
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from server.config import CFG, resolve
from server.proc_utils import kill_by_port

log = logging.getLogger("saika.llamacpp")

_proc = None
_install_proc = None
_lock = threading.Lock()
_dropped_args: list = []          # что сборка не приняла — для лога и UI
# КОГДА В ПОСЛЕДНИЙ РАЗ УБЕДИЛИСЬ, ЧТО СЕРВЕР ЖИВ (2026-07-27).
# ensure_running() зовётся ПЕРЕД КАЖДОЙ репликой, а внутри неё — HTTP-проверка
# /health с таймаутом 2с. Пока всё хорошо, это миллисекунды; но замер показал
# в логе ровно «сборка запроса 2047мс» на каждый ответ — то есть проверка
# упиралась в свой таймаут целиком, и две секунды из трёх человек ждал
# ПРОВЕРКУ, а не модель. Живость меняется раз в час, а не раз в реплику:
# помним ответ и не переспрашиваем, пока он свежий. Настоящая поломка всё
# равно вылезет — на самом запросе, там она и обработается.
_ALIVE = {"t": 0.0}

DEFAULT_PORT = 8771
DEST = "third_party/llamacpp"


def _cfg() -> dict:
    return CFG.get("llamacpp", {}) or {}


def port() -> int:
    return int(_cfg().get("port", DEFAULT_PORT))


def base_url() -> str:
    return f"http://127.0.0.1:{port()}"


def binary() -> Path:
    p = _cfg().get("binary")
    if p:
        return Path(p)
    name = "llama-server.exe" if os.name == "nt" else "llama-server"
    return resolve(f"{DEST}/{name}")


def installed() -> bool:
    return binary().exists()


def version() -> str:
    v = resolve(f"{DEST}/VERSION.txt")
    try:
        return v.read_text(encoding="utf-8").splitlines()[0].strip()
    except Exception:
        return ""


def _health(timeout=None):
    import requests
    try:
        r = requests.get(base_url() + "/health",
                         timeout=timeout if timeout is not None
                         else float(_cfg().get("health_timeout_s", 2)))
        return r.json() if r.ok else None
    except Exception:
        return None


def note_alive():
    """Сервер только что ответил на настоящий запрос — значит он жив, и
    отдельная проверка ближайшее время не нужна."""
    _ALIVE["t"] = time.monotonic()


def _sig() -> str:
    """Отпечаток настроек, с которыми ДОЛЖЕН быть запущен сервер. Хранится
    рядом с логом; расхождение с живым процессом = его надо перезапустить.

    ЗАЧЕМ (2026-07-27, реальный случай). llama-server живёт отдельным
    процессом и переживает перезапуск Сайки. Мы поменяли флаги (--swa-full,
    от которого зависит вся работа KV-кэша на gemma), дважды перезапустили
    Сайку — а в логе движка так и осталось «cache_reuse is not supported» и
    prefill по 4200 токенов на реплику: ensure_running видел живой /health
    и радовался СТАРОМУ процессу со старыми флагами. Никакая ручная
    дисциплина тут не работает — сервер обязан сам замечать, что его
    настройки устарели."""
    import json as _json
    g = _cfg()
    return _json.dumps({
        "model": find_model(), "n_ctx": g.get("n_ctx", 16384),
        "ngl": g.get("n_gpu_layers", 999), "fa": g.get("flash_attn", "on"),
        "reuse": g.get("cache_reuse", 256), "kv": g.get("kv_quant", "q8_0"),
        "swa": g.get("swa_full", True), "batch": g.get("batch_size", 2048),
        "ubatch": g.get("ubatch_size", 512),
        "draft": g.get("draft_model_path", ""),
        "extra": g.get("extra_args") or [],
    }, sort_keys=True)


def _sig_path():
    return resolve("logs/llamacpp_server.sig")


def kill_stale():
    """Убить сервер, оставшийся от прошлого запуска Сайки (зовётся из main.py
    рядом с dreampc.kill_stale()).

    kill_by_port на Windows может МОЛЧА не найти процесс (psutil получает
    отказ в доступе к чужим соединениям и пропускает их) — поэтому после
    него проверяем порт по-настоящему и добиваем taskkill'ом по имени.
    Файл отпечатка тоже убираем: следующий ensure_running обязан спавнить."""
    kill_by_port(port(), "зависший llama-server")
    try:
        _sig_path().unlink(missing_ok=True)
    except Exception:
        pass
    if _health(timeout=0.7) is None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"],
                           capture_output=True, timeout=15)
            log.info("llamacpp: старый llama-server добит через taskkill")
        except Exception as e:
            log.warning("llamacpp: taskkill не сработал: %s", e)
    for _ in range(10):
        if _health(timeout=0.5) is None:
            return
        time.sleep(0.3)
    log.warning("llamacpp: старый сервер так и не умер — новые флаги "
                "не применятся, пока он жив")


# ─────────────────────── поиск GGUF-файла ───────────────────────

def _lmstudio_roots() -> list:
    """Каталоги, где LM Studio держит скачанные GGUF. Каталог часто ПЕРЕНЕСЁН
    на другой диск — настоящий путь тогда лежит первой строкой в файле-
    указателе ~/.lmstudio-home-pointer (та же логика, что в manager.py)."""
    home = Path.home()
    roots = [home / ".lmstudio" / "models",
             home / ".cache" / "lm-studio" / "models"]
    try:
        ptr = home / ".lmstudio-home-pointer"
        if ptr.exists():
            target = Path(ptr.read_text(encoding="utf-8", errors="ignore")
                          .strip().splitlines()[0].strip())
            if target.exists():
                roots.insert(0, target / "models")
    except Exception as e:
        log.debug("lmstudio home-pointer: %s", e)
    return [r for r in roots if r.exists()]


def _score_gguf(path: Path, want: str) -> int:
    """Насколько файл похож на искомую модель. Больше — лучше, 0 — мимо."""
    hay = str(path).lower().replace("\\", "/")
    parts = [p for p in re.split(r"[^a-z0-9.]+", want.lower()) if len(p) > 1]
    if not parts:
        return 0
    hit = sum(1 for p in parts if p in hay)
    if hit < max(1, len(parts) - 1):
        return 0                                   # совпало слишком мало
    score = hit * 10
    # мультичастевые GGUF (…-00001-of-00003.gguf) — брать надо ПЕРВЫЙ кусок,
    # llama.cpp сама подтянет остальные; прочие куски не предлагать вовсе
    m = re.search(r"-(\d{5})-of-\d{5}\.gguf$", hay)
    if m:
        if m.group(1) != "00001":
            return 0
        score += 1
    return score


def find_model() -> str:
    """Путь к .gguf. Явно заданный в конфиге -> проект -> каталог LM Studio."""
    p = _cfg().get("model_path")
    if p and Path(p).exists():
        return str(Path(p))
    want = _cfg().get("model") or CFG.get("llm.model", "")
    roots = [resolve("models/gguf"), resolve("models/llm")] + _lmstudio_roots()
    best, best_score = "", 0
    for root in roots:
        try:
            if not Path(root).exists():
                continue
            for f in Path(root).rglob("*.gguf"):
                s = _score_gguf(f, want)
                if s > best_score:
                    best, best_score = str(f), s
        except Exception as e:
            log.debug("обход %s: %s", root, e)
    return best


# ─────────────────────── аргументы запуска ───────────────────────

def _args(model_path: str, tier: int) -> list:
    """Командная строка. tier=0 — всё, дальше — по убыванию рискованности
    флагов (см. «грабли» в шапке модуля)."""
    g = _cfg()
    # ОКНО КОНТЕКСТА — БОЛЬШЕЕ ИЗ ДВУХ КЛЮЧЕЙ (2026-07-28). В конфиге два
    # места про окно: locallm_gguf.n_ctx (по нему main.py считает бюджет
    # промпта) и llamacpp.n_ctx (с ним реально стартует движок). Они
    # разъехались — 32768 против 24576 — и получилась худшая комбинация:
    # бюджет верит в большое окно, движок живёт в маленьком, история
    # ужимается до полутора тысяч символов, Сайка «забывает нить и странно
    # отвечает», а в логе на каждый ход сыплется «окно контекста мало».
    # Чинить просили руками в config.json — но правило проекта другое:
    # всё чинится само. Берём больший из двух ключей: явно попросили
    # больше окна хоть где-то — значит, столько и даём. VRAM это
    # переживает: KV-кэш квантован в q8_0.
    n_ctx = int(g.get("n_ctx", 16384))
    try:
        other = int((CFG.get("locallm_gguf") or {}).get("n_ctx") or 0)
        if other > n_ctx:
            log.info("llamacpp: окно %d < locallm_gguf.n_ctx=%d — беру большее",
                     n_ctx, other)
            n_ctx = other
    except Exception:
        pass
    # ГЛАЗА МОДЕЛИ (2026-07-29). gemma-4 мультимодальная, но llama-server
    # видит картинки ТОЛЬКО с файлом-проектором (mmproj-*.gguf). Без него
    # любой запрос с изображением падает 500 «image input is not supported»
    # — а зрение у Сайки включается тумблером, и тогда картинка уезжает в
    # КАЖДЫЙ запрос. В логе владельца это выглядело как «ни одна LLM не
    # ответила» на безобидное «открой проводник».
    # Проектор обычно лежит рядом с весами: ищем сами, руками указывать
    # ничего не надо. Не нашли — работаем текстом (менеджер отбросит
    # картинку и ответит, а не умрёт).
    mmproj = g.get("mmproj") or ""
    if not mmproj:
        try:
            mdir = Path(model_path).parent
            cands = sorted(mdir.glob("mmproj*.gguf")) + \
                sorted(mdir.glob("*mmproj*.gguf")) + \
                sorted(mdir.glob("*vision*.gguf"))
            if cands:
                mmproj = str(cands[0])
                log.info("llamacpp: нашла проектор картинок %s — подключаю "
                         "зрение модели", cands[0].name)
        except Exception:
            mmproj = ""
    if mmproj and not Path(mmproj).exists():
        log.warning("llamacpp: проектор %s не найден на диске — без зрения",
                    mmproj)
        mmproj = ""

    args = [str(binary()),
            "-m", model_path,
            "--host", g.get("host", "127.0.0.1"),
            "--port", str(port()),
            "--ctx-size", str(n_ctx),
            # ВСЕ слои на видеокарту. Ровно то, чего не было в LM Studio:
            # частичный offload и был причиной 640 ток/с на prefill.
            "-ngl", str(g.get("n_gpu_layers", 999)),
            # один слот = весь KV-кэш принадлежит одному диалогу, префикс
            # переиспользуется целиком (с несколькими слотами кэш делится)
            "--parallel", "1",
            # алиас: в /v1/models модель назовётся привычным именем, и
            # выбор модели в интерфейсе Сайки не поедет
            "--alias", g.get("model") or CFG.get("llm.model", "local"),
            *(["--mmproj", mmproj] if mmproj else []),
            # шаблон из GGUF + поддержка tools/chat_template_kwargs —
            # без --jinja llama.cpp берёт свой упрощённый шаблон и теряет
            # и инструменты, и выключение размышлений
            "--jinja"]
    if tier <= 1:
        args += [
            # flash-attention: главный множитель скорости prefill на Ada
            "-fa", str(g.get("flash_attn", "on")),
            # ПЕРЕИСПОЛЬЗОВАНИЕ КУСКА ПРЕФИКСА. Обычный кэш умирает на первом
            # же расхождении. У нас каждый ход в середину промпта вставляется
            # блок динамики (память/лорбук) — с --cache-reuse llama.cpp
            # переиспользует и то, что идёт ПОСЛЕ расхождения, сдвигая
            # позиции. Ровно наш случай.
            "--cache-reuse", str(g.get("cache_reuse", 256)),
            # prefill крупными пачками — упирается в вычисления, а не в
            # накладные на запуск ядер
            "--batch-size", str(g.get("batch_size", 2048)),
            "--ubatch-size", str(g.get("ubatch_size", 512))]
        # ПОЛНЫЙ KV ДЛЯ SWA-МОДЕЛЕЙ. gemma считает вниманием по скользящему
        # окну, и ради экономии памяти llama.cpp хранит для таких слоёв
        # только само окно — а тогда переиспользовать длинный префикс между
        # ходами нечем, его физически нет в кэше. --swa-full велит держать
        # KV целиком: памяти уходит больше, зато префикс живёт. У нас карта
        # свободна (6 из 16 ГБ), так что размен выгодный.
        if g.get("swa_full", True):
            args += ["--swa-full"]
        # СПЕКУЛЯТИВНОЕ ДЕКОДИРОВАНИЕ (опционально, llamacpp.draft_model_path).
        # Мелкая модель-черновик (например gemma-4-e2b рядом с e4b) угадывает
        # несколько токенов вперёд, большая только проверяет — генерация
        # ускоряется в 1.5-2 раза БЕЗ потери качества (проверка точная).
        # На первый токен не влияет, поэтому по умолчанию выключено: сначала
        # добиваем TTFT, потом включаем это ради длинных ответов.
        draft = g.get("draft_model_path", "")
        if draft and Path(draft).exists():
            args += ["-md", str(draft),
                     "--draft-max", str(g.get("draft_max", 12)),
                     "--draft-min", str(g.get("draft_min", 2))]
    if tier <= 0:
        kv = g.get("kv_quant", "q8_0")
        if kv and kv != "f16":
            # квантованный KV — вдвое меньше VRAM под контекст. Важно тут:
            # карта делится с Qwen3-TTS и GigaAM, все 16 ГБ не наши.
            args += ["--cache-type-k", kv, "--cache-type-v", kv]
        if g.get("no_reasoning", True):
            # у gemma-4 размышления включены по умолчанию; на уровне запроса
            # их гасит chat_template_kwargs (llama.cpp его понимает, в
            # отличие от LM Studio), но пусть и сервер знает
            args += ["--reasoning-budget", "0"]
        args += ["--metrics"]        # /metrics — для замеров скорости
    extra = g.get("extra_args") or []
    return args + [str(x) for x in extra]


MAX_TIER = 2


def _spawn(model_path: str) -> dict:
    """Поднять сервер, снижая ярус аргументов, если сборка их не приняла."""
    global _proc, _dropped_args
    log_path = resolve("logs/llamacpp_server.log")
    log_path.parent.mkdir(exist_ok=True)
    for tier in range(MAX_TIER + 1):
        cmd = _args(model_path, tier)
        logf = open(log_path, "w", encoding="utf-8")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log.info("llamacpp: запускаю (ярус %s): %s", tier, " ".join(cmd))
        _proc = subprocess.Popen(cmd, cwd=str(resolve(".")), stdout=logf,
                                 stderr=subprocess.STDOUT, creationflags=flags)
        # ждём /health; загрузка модели в VRAM — это секунды, не мгновение
        deadline = time.time() + int(_cfg().get("start_timeout_s", 120))
        while time.time() < deadline:
            h = _health()
            if h is not None and h.get("status") in (None, "ok"):
                note_alive()
                if tier:
                    _dropped_args = ["ярус " + str(tier)]
                    log.warning("llamacpp: сборка не приняла часть флагов — "
                                "поднялась на ярусе %s. Что именно не зашло "
                                "— в logs/llamacpp_server.log", tier)
                log.info("llamacpp: сервер готов на %s (%s)", base_url(),
                         version() or "версия неизвестна")
                try:
                    _sig_path().write_text(_sig(), encoding="utf-8")
                except Exception:
                    pass
                return {"ok": True, "port": port()}
            if _proc.poll() is not None:
                break
            time.sleep(0.5)
        if _proc.poll() is None:
            # жив, но /health молчит дольше таймаута — это не про флаги
            return {"ok": True, "port": port(),
                    "note": "сервер стартует, первая загрузка модели в VRAM "
                            "может занять время"}
        tail = ""
        try:
            tail = "\n".join(log_path.read_text(
                encoding="utf-8", errors="ignore").splitlines()[-6:])
        except Exception:
            pass
        log.warning("llamacpp: сервер упал на ярусе %s (код %s): %s",
                    tier, _proc.returncode, tail[-400:])
    return {"error": "llama-server не поднялся ни на одном наборе флагов — "
                     "смотри logs/llamacpp_server.log"}


def _start_install():
    global _install_proc
    py = resolve(".venv/Scripts/python.exe" if os.name == "nt"
                 else ".venv/bin/python")
    script = resolve("setup/install_llamacpp.py")
    logp = resolve("logs/llamacpp_install.log")
    logp.parent.mkdir(exist_ok=True)
    logf = open(logp, "w", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log.info("llamacpp: качаю llama-server в фоне")
    _install_proc = subprocess.Popen([str(py), str(script)],
                                     cwd=str(resolve(".")), stdout=logf,
                                     stderr=subprocess.STDOUT,
                                     creationflags=flags)


def ensure_running() -> dict:
    global _install_proc
    # свежая память о живом сервере — выходим, не трогая сеть
    ttl = float(_cfg().get("health_ttl_s", 30))
    if ttl and (time.monotonic() - _ALIVE["t"]) < ttl:
        return {"ok": True, "port": port()}
    with _lock:
        if _install_proc is not None:
            code = _install_proc.poll()
            if code is None:
                return {"ok": True, "installing": True,
                        "note": "качаю llama-server (~200 МБ), это разово"}
            _install_proc = None
            if code != 0:
                return {"error": "не смогла поставить llama-server — смотри "
                                 "logs/llamacpp_install.log"}

        h = _health()
        if h is not None:
            try:
                stale = _sig_path().read_text(encoding="utf-8") != _sig()
            except Exception:
                stale = True          # отпечатка нет = запускали не мы
            if not stale:
                note_alive()
                return {"ok": True, "port": port()}
            log.info("llamacpp: настройки движка изменились — перезапускаю "
                     "сервер с новыми флагами")
            unload()

        if not installed():
            _start_install()
            return {"ok": True, "installing": True,
                    "note": "llama-server ещё не установлен — ставлю сама"}

        # ОДИН ЛОКАЛЬНЫЙ ДВИЖОК НА ВИДЕОКАРТУ — разбор в one_local.py
        from server.llm import one_local
        _no = one_local.refuse("llamacpp")
        if _no:
            return _no

        model_path = find_model()
        if not model_path:
            return {"error": "не нашла .gguf для модели «%s». Положи файл в "
                             "models/gguf или пропиши путь в config: "
                             "llamacpp.model_path"
                             % (_cfg().get("model")
                                or CFG.get("llm.model", ""))}
        return _spawn(model_path)


def unload() -> str:
    """Погасить сервер и освободить VRAM (аналог unload_model у Ollama)."""
    global _proc
    if _proc is not None and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=10)
        except Exception:
            _proc.kill()
    kill_stale()
    _proc = None
    return "llama-server остановлен, VRAM свободна"


def status() -> dict:
    """Что сейчас с движком — для UI и диагностики."""
    h = _health()
    tail = ""
    p = resolve("logs/llamacpp_server.log")
    if p.exists():
        try:
            tail = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                             .splitlines()[-8:])
        except Exception:
            pass
    return {"installed": installed(), "version": version(),
            "alive": h is not None, "port": port(),
            "model_path": find_model(), "dropped_args": list(_dropped_args),
            "log_tail": tail}
