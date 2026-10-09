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

from anamorf.config import CFG, resolve
from anamorf.proc_utils import kill_by_port

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


def _running_alias() -> str:
    """Какую модель крутит сервер, который сейчас отвечает на нашем порту.

    Спрашиваем /v1/models: llama-server представляется тем самым --alias,
    который мы ему даём при запуске, а это имя файла модели. Нужен ответ
    на вопрос «сосед крутит то же, что нужно мне?» — чтобы взять чужой
    сервер вместо второй копии модели в видеопамяти."""
    import requests
    try:
        r = requests.get(base_url() + "/v1/models",
                         timeout=float(_cfg().get("health_timeout_s", 2)))
        if not r.ok:
            return ""
        d = (r.json() or {}).get("data") or []
        return str((d[0] or {}).get("id") or "") if d else ""
    except Exception:
        return ""


def note_alive():
    """Сервер только что ответил на настоящий запрос — значит он жив, и
    отдельная проверка ближайшее время не нужна."""
    _ALIVE["t"] = time.monotonic()


# Урезано ли окно ради голоса — чтобы совет при нехватке контекста называл
# НАСТОЯЩУЮ причину. Иначе человек идёт поднимать llamacpp.n_ctx, а потолок
# всё равно срезает — совет, который не работает, хуже молчания.
CTX_CAP = {"capped": False, "raw": 0, "cap": 0, "who": ""}

# РАСКРОЙ MoE (2026-09-05). Сколько слоёв экспертов уходит в системную
# память флагом --n-cpu-moe. Считает план (anamorf/vramplan.py), а кладут
# сюда — потому что число нужно и _args (собрать команду), и _sig
# (подписать процесс: сменился раскрой — сервер обязан перезапуститься,
# иначе правка не доедет никогда, ровно как было с окном до 27.07).
PLAN = {"n_cpu_moe": 0, "note": "", "fits": True}


def _eff_ctx() -> int:
    """ОКНО, С КОТОРЫМ СЕРВЕР РЕАЛЬНО СТАРТУЕТ.

    Считается в одном месте намеренно: этим же числом подписывается живой
    процесс (см. `_sig`). Пока расчёт жил внутри `_args`, подпись брала
    сырой ключ из конфига — и сервер, поднятый со старым окном, выглядел
    «тем самым» и не перезапускался. То есть правка окна не доезжала
    никогда, а по конфигу выглядела применённой.

    Два правила, и оба выстраданы:

    1. БОЛЬШЕЕ ИЗ ДВУХ КЛЮЧЕЙ (2026-07-28). В конфиге два места про окно:
       locallm_gguf.n_ctx (по нему main.py считает бюджет промпта) и
       llamacpp.n_ctx (с ним стартует движок). Разъехались — и получалась
       худшая комбинация: бюджет верит в большое окно, движок живёт в
       маленьком, история ужимается, Сайка «забывает нить».

    2. НО ОКНО НЕ СЪЕДАЕТ ГОЛОС (2026-08-22, живой замер: 12.7 ГБ из 16.4
       занято llama-server, клон-голосу нужно ~5, и он не поднялся весь
       вечер). Правило (1) тянуло 32768 из настроек СОВСЕМ ДРУГОГО движка
       (locallm_gguf — это T-lite), и за чужой ключ расплачивался голос.
       Видеокарта одна, и делить её надо явно, а не по тому, кто первым
       встал: выбран тяжёлый голос — оставляем ему место. Потеря меньше,
       чем кажется: 16k токенов — десятки страниц разговора, а молчащую
       Сайку слышно сразу.
    """
    g = _cfg()
    n_ctx = int(g.get("n_ctx", 16384))
    try:
        other = int((CFG.get("locallm_gguf") or {}).get("n_ctx") or 0)
        if other > n_ctx:
            n_ctx = other
    except Exception:
        pass
    heavy_voice = ("qwen3", "omni", "xtts", "f5")
    try:
        # берём и «погашенный» движок: разгрузка памяти могла оставить
        # tts.engine=off, а llama-server стартует раньше, чем автопуск
        # успеет вернуть голос. Занять всю карту в эту щель — значит не
        # дать голосу подняться вовсе.
        cur_tts = str(CFG.get("tts.engine", "") or "") or \
            str(CFG.get("tts.engine_was", "") or "")
        voice_on = bool(CFG.get("tts.enabled", True)) and \
            any(h in cur_tts.lower() for h in heavy_voice)
    except Exception:
        cur_tts, voice_on = "", False
    cap = int(g.get("n_ctx_voice_cap", 16384))
    # ГРУБЫЙ ПОТОЛОК УСТУПАЕТ ПЛАНУ (2026-09-05). Правило «выбран тяжёлый
    # голос — режем окно до 16384» появилось, когда делить карту было нечем:
    # оно вычитает место под голос вслепую, одним числом на все случаи.
    # Теперь место под голос считает план памяти — по настоящему устройству
    # модели и по настоящему замеру карты. Оставить оба значит вычесть голос
    # ДВАЖДЫ, и просьба «окно 120 тысяч» разбилась бы об эти 16384, даже
    # когда на карте есть место. Как только человек назвал желаемое окно
    # (llamacpp.n_ctx_want), решает план; без него всё как было.
    if int(g.get("n_ctx_want", 0) or 0):
        cap = 0
    CTX_CAP.update(capped=bool(voice_on and cap and n_ctx > cap),
                   raw=n_ctx, cap=cap, who=cur_tts)
    if voice_on and cap and n_ctx > cap:
        log.info("llamacpp: окно %d -> %d, чтобы на карте осталось место "
                 "клон-голосу «%s» (16 ГБ на двоих)", n_ctx, cap, cur_tts)
        n_ctx = cap
    # ПЛАН ПАМЯТИ ВМЕСТО ДРАКИ (2026-08-23, владелец: «оптимизируй
    # ресурсы так, чтобы выбранные компоненты запускались гарантированно»).
    # Стоимость заказа — мозг, голос, слух, запас — считается заранее
    # (anamorf/vramplan.py), и единственная гибкая величина, окно
    # контекста, подгоняется под остаток. Раньше карта делилась явочным
    # порядком, и сторож железа душил проигравшего каждые полминуты.
    try:
        mp = find_model()
        if mp:
            gb = Path(mp).stat().st_size / (1 << 30)
            from anamorf import vramplan
            # ОКНО, КОТОРОЕ ПРОСИЛИ, А НЕ ТОЛЬКО ТО, ЧТО В КОНФИГЕ
            # (2026-09-05). llamacpp.n_ctx_want — верхняя планка желания:
            # «хочу 120 тысяч». План возьмёт её как потолок и спустится
            # ниже ровно настолько, насколько заставит железо. Без этого
            # ключа большое окно нельзя было даже попросить: лестница в
            # плане начиналась с 16384.
            want = int(g.get("n_ctx_want", 0) or 0)
            pl = vramplan.plan(gb, model_path=mp, want_ctx=want)
            PLAN.update(n_cpu_moe=int(pl.get("n_cpu_moe", 0)),
                        note=pl.get("note", ""), fits=bool(pl.get("fits")))
            if want and pl["n_ctx"] > n_ctx:
                # заказ больше, чем стоит в конфиге, и он влезает —
                # значит окно поднимаем, а не оставляем прежним
                n_ctx = pl["n_ctx"]
            if pl["n_ctx"] < n_ctx:
                log.info("llamacpp: план памяти — %s; окно %d -> %d",
                         pl["note"], n_ctx, pl["n_ctx"])
                n_ctx = pl["n_ctx"]
            else:
                log.info("llamacpp: план памяти — %s", pl["note"])
            if not pl["fits"]:
                log.warning("llamacpp: заказ НЕ влезает в карту: %s",
                            pl["note"])
    except Exception as e:
        log.debug("план памяти не посчитался: %s", e)
    return n_ctx


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
        "model": find_model(), "n_ctx": _eff_ctx(),
        "cpu_moe": PLAN.get("n_cpu_moe", 0),
        "loadmode": g.get("load_mode_moe", "none"),
        "ngl": g.get("n_gpu_layers", 999), "fa": g.get("flash_attn", "on"),
        "reuse": g.get("cache_reuse", 256),
        "cshift": bool(g.get("context_shift", True)), "kv": g.get("kv_quant", "q8_0"),
        "kvv": g.get("kv_quant_v", ""),
        "kvvb": bool(g.get("kv_v_benchmarked", False)),
        "nommproj": bool(g.get("no_mmproj", False)),
        "swa": g.get("swa_full", True), "batch": g.get("batch_size", 2048),
        "ubatch": g.get("ubatch_size", 512),
        "draft": g.get("draft_model_path", ""),
        "extra": g.get("extra_args") or [],
    }, sort_keys=True)


def _sig_path():
    return resolve("logs/llamacpp_server.sig")


def stop(why: str = "выход") -> bool:
    """Погасить НАШ llama-server и убедиться, что он умер.

    Отличие от kill_stale — не «расчистить место перед стартом», а
    «освободить видеопамять при закрытии». Разница важная: 04.09.2026
    владелец закрыл Сайку, а карта осталась занята на 12,4 из 16 ГБ —
    llama-server пережил её и держал модель. Виноват не замысел (сервер
    и правда должен переживать ПЕРЕЗАПУСК), а то, что при выходе звался
    только kill_by_port. На Windows он молча промахивается: psutil не
    получает доступа к соединениям чужих процессов и просто пропускает
    их. Здесь тот же добивающий taskkill, что и в kill_stale, плюс
    честная проверка результата.
    """
    global _proc
    kill_by_port(port(), f"llama-server ({why})")
    try:
        if _proc and _proc.poll() is None:
            _proc.terminate()
    except Exception:
        pass
    _proc = None
    try:
        _sig_path().unlink(missing_ok=True)
    except Exception:
        pass
    if _health(timeout=0.7) is None:
        return True
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"],
                           capture_output=True, timeout=15)
        except Exception as e:
            log.warning("llamacpp: taskkill при выходе не сработал: %s", e)
    for _ in range(10):
        if _health(timeout=0.5) is None:
            log.info("llamacpp: сервер погашен (%s), видеопамять свободна", why)
            return True
        time.sleep(0.3)
    log.warning("llamacpp: сервер пережил выход — видеопамять останется "
                "занятой до следующего старта Сайки")
    return False


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
    # ТОЧНОЕ ИМЯ ФАЙЛА БЬЁТ ПОХОЖЕЕ (2026-08-23: человек выбрал
    # qwen3-14b-abliterated-q4_k_m, а по кусочкам одинаково набрал очки и
    # файл huihui-…-Q4_K_S — тот же мозг в другом кванте; загрузился не
    # тот файл, что он ткнул). Совпадение стема буква в букву — вне
    # конкуренции.
    if re.sub(r"[^a-z0-9]+", "", path.stem.lower()) == \
            re.sub(r"[^a-z0-9]+", "", want.lower()):
        score += 100
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
    # ВЫБОР ЧЕЛОВЕКА ГЛАВНЕЕ СЛУЖЕБНОГО КЛЮЧА (2026-08-23, живой обман:
    # клик в меню пишет llm.model, а поиск файла смотрел сперва в
    # llamacpp.model — там лежала старая gemma. Сервер крутил gemma,
    # подпись под ответами честно писала имя выбранной huihui, и человек
    # разговаривал не с тем, с кем думал. «Видишь, какая модель в памяти
    # и какая отвечает?»)
    want = CFG.get("llm.model", "") or _cfg().get("model") or ""
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
    n_ctx = _eff_ctx()

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
    # ГЛАЗА МОДЕЛИ СТОЯТ ДОРОЖЕ, ЧЕМ КАЖЕТСЯ (2026-09-05). Проектор — это
    # не только гигабайт видеопамяти. Сам llama-server пишет при загрузке:
    # «cache_reuse is not supported by multimodal, it will be disabled» и
    # «swa_full is not supported by this model, it will be disabled».
    #
    # То есть с проектором ОТКЛЮЧАЕТСЯ ПЕРЕИСПОЛЬЗОВАНИЕ ПРЕФИКСА. А весь
    # расчёт на быстрый первый токен держится именно на нём: её характер,
    # память и описания инструментов — это тысячи токенов, которые в начале
    # КАЖДОГО хода одни и те же. С кэшем они считаются один раз за сеанс,
    # без кэша — заново на каждую реплику. Владелец видит это как «шесть
    # секунд молчит, потом отвечает», и правы оба: и он, и движок.
    #
    # Зрение Сайки при этом никуда не девается: скриншоты и камера идут
    # своим трактом (anamorf/vision.py), а картинку в САМУ модель она
    # прикладывает редко. Ключ llamacpp.no_mmproj = true меняет эту редкую
    # возможность на быстрый ответ в каждом ходе.
    if g.get("no_mmproj", False):
        if mmproj:
            log.info("llamacpp: проектор картинок отключён ключом "
                     "no_mmproj — зато работает переиспользование префикса "
                     "(первый токен быстрее в разы)")
        mmproj = ""
    elif not mmproj:
        try:
            mdir = Path(model_path).parent
            cands = sorted(mdir.glob("mmproj*.gguf")) + \
                sorted(mdir.glob("*mmproj*.gguf")) + \
                sorted(mdir.glob("*vision*.gguf"))
            # ПРОЕКТОР — ТОЛЬКО РОДНОЙ (2026-08-23, живой лог: к
            # huihui-Qwen3 подключился mmproj-gemma-4 — проектор ЧУЖОЙ
            # модели. Со стороны это «модель с глазами», по факту — мусор
            # на входе и падения на каждой картинке. Проектор обучен под
            # конкретную модель; чужой хуже никакого). Родство меряем по
            # семье в имени: у модели «...Qwen3...» проектор обязан
            # содержать «qwen», у геммы — «gemma».
            import re as _re
            _fam = [w for w in _re.split(r"[^a-z]+",
                                         Path(model_path).stem.lower())
                    if len(w) > 2 and not w.isdigit()][:4]
            def _kin(c):
                h = c.name.lower()
                return any(w in h for w in _fam)
            kin = [c for c in cands if _kin(c)]
            if cands and not kin:
                log.info("llamacpp: проектор рядом есть (%s), но он от "
                         "другой модели — работаю без зрения",
                         cands[0].name)
            cands = kin
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
    # ПАСПОРТ ЗРЕНИЯ — СРАЗУ ПРИ ЗАПУСКЕ (2026-08-23, живой вечер: зрение
    # приложило кадр к huihui без проектора, сервер ответил 500, модель
    # улетела в карантин, а разговор — к гигачату). Без mmproj глаза не
    # подключены — записываем это в опыт, чтобы кадр слепому мозгу больше
    # никогда не прикладывали.
    try:
        from anamorf import capabilities as _caps
        _caps.note(Path(model_path).stem, "vision", bool(mmproj))
    except Exception:
        pass

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
            # алиас: имя в /v1/models. Берём ИСТИНУ — имя файла, который
            # реально запускаем. Раньше тут стоял g.get("model") — стылый
            # ключ llamacpp.model с прошлой моделью: сервер крутил huihui,
            # а представлялся gemma → интерфейс рисовал вечные песочные
            # часы, сверки считали «не та модель» и перезапускали сервер
            # по кругу. Имя файла не врёт никогда; сопоставление с выбором
            # человека делает _nrm в loaded_models и keeper.
            "--alias", Path(model_path).stem or "local",
            *(["--mmproj", mmproj] if mmproj else []),
            # шаблон из GGUF + поддержка tools/chat_template_kwargs —
            # без --jinja llama.cpp берёт свой упрощённый шаблон и теряет
            # и инструменты, и выключение размышлений
            # МЫСЛИ — В ОТДЕЛЬНОЕ ПОЛЕ, А НЕ В ОТВЕТ (2026-08-23: шаблон
            # Qwen3.5 сам открывает <think>, модель его закрывает — и
            # черновик уезжал в чат и в голос («</think> Хорошо, понятно»).
            # С этим флагом llama.cpp вынимает размышления в
            # reasoning_content, а в content остаётся чистая речь.
            "--reasoning-format", "deepseek",
            "--jinja"]
    # ЭКСПЕРТЫ — В СИСТЕМНУЮ ПАМЯТЬ (2026-09-05, владелец: «нужна модель
    # нормальная по качеству и окно 120 тысяч, и чтобы игру одновременно»).
    #
    # У модели вида 35B-A3B из двадцати одного гигабайта весов восемнадцать
    # — это эксперты, и на каждом токене работают три миллиарда параметров
    # из тридцати пяти. Держать всё это в видеопамяти незачем и негде:
    # --n-cpu-moe уводит эксперты первых N слоёв в ОЗУ, а на карте остаётся
    # внимание и KV-кэш — те самые два-три гигабайта, ради которых окно в
    # 120 тысяч наконец становится возможным на карте в 16 ГБ.
    #
    # Число берёт план памяти: он подбирает МИНИМАЛЬНОЕ N, при котором
    # заказ влезает, — каждый слой экспертов, оставшийся на карте, считается
    # на карте, а это в разы быстрее. Ноль означает «модель плотная или всё
    # и так помещается» — тогда флага нет вовсе и поведение прежнее.
    #
    # Флаг проверен по сборке: b10195 его знает (строка есть в
    # llama-common.dll). Если сборку сменят на старую — llama-server
    # откажется стартовать, и _spawn спустится на ярус ниже, где флага нет.
    n_moe = int(PLAN.get("n_cpu_moe", 0) or 0)
    if n_moe > 0 and tier <= 1:
        args += ["--n-cpu-moe", str(n_moe)]
        # САМ ДВИЖОК ПРОСИТ ОБ ЭТОМ (2026-09-05, первая же строка его лога
        # при подъёме 35B-A3B): «tensor overrides to CPU are used with mmap
        # enabled — consider using --no-mmap for better performance».
        #
        # Почему так. При mmap веса лежат отображённым файлом, и обращение
        # к эксперту — это обращение к странице файла, которую Windows
        # вправе в любой момент выбросить и дочитать с диска. Для весов,
        # живущих на карте, это безразлично: они там один раз и навсегда.
        # Для экспертов, которые считаются НА ПРОЦЕССОРЕ на каждом токене,
        # это лотерея: попал в память — быстро, не попал — ждём диск.
        # --no-mmap кладёт их в оперативку честно и один раз.
        #
        # Цена: память занимается по-настоящему, и её нельзя вытеснить.
        # Поэтому ключ отдельный: если оперативки в обрез, выключается без
        # смены всего остального.
        # ФЛАГ НАЗЫВАЕТСЯ ИНАЧЕ В ЭТОЙ СБОРКЕ. Первый заход поставил
        # --no-mmap, и движок ответил: «DEPRECATED: --mmap and --no-mmap
        # are deprecated, use --load-mode mmap instead». Режимы у него
        # такие: none | mmap | mlock | mmap+mlock | dio. Нам нужен «none»
        # — прочитать веса в обычную оперативку и там оставить; это и есть
        # смысл прежнего --no-mmap. «mlock» звучит надёжнее, но требует
        # права запрещать вытеснение и на семнадцати гигабайтах чаще
        # отваливается, чем помогает.
        _lm = str(g.get("load_mode_moe", "none") or "").strip()
        if _lm:
            args += ["--load-mode", _lm]
        log.info("llamacpp: эксперты %d слоёв уходят в системную память "
                 "(--n-cpu-moe %d). %s", n_moe, n_moe, PLAN.get("note", ""))
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
            # СДВИГ КОНТЕКСТА — УСЛОВИЕ РАБОТЫ КЭША, А НЕ ОТДЕЛЬНАЯ УДОБНАЯ
            # ШТУЧКА (2026-09-05). Живой лог после отключения проектора:
            # «cache_reuse is not supported by this context, it will be
            # disabled» — сообщение сменилось, но кэш префикса как не
            # работал, так и не работает.
            #
            # Причина в том, что переиспользование куска префикса физически
            # требует умения СДВИГАТЬ ячейки KV: llama.cpp выбрасывает
            # разошедшийся кусок и сдвигает позиции остальных. В свежих
            # сборках сдвиг по умолчанию ВЫКЛЮЧЕН и включается флагом —
            # а без него --cache-reuse тихо игнорируется. Тихо: сервер
            # пишет одну строку при загрузке и работает дальше, честно
            # пересчитывая весь промпт каждый ход. Снаружи это ровно то, на
            # что жалуется владелец: «шесть секунд молчит перед ответом».
            *(["--context-shift"] if g.get("context_shift", True) else []),
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
        # КЛЮЧИ И ЗНАЧЕНИЯ КВАНТУЮТСЯ ПОРОЗНЬ (2026-09-05). Раньше сюда
        # уходил один и тот же квант на оба флага. Но K и V ведут себя
        # по-разному: значения переносят грубое квантование заметно легче
        # ключей. K в q8_0 и V в q4_0 — это минус четверть памяти под кэш
        # почти без потери связности, и именно этой четверти не хватало,
        # чтобы окно на 120 тысяч ужилось на карте рядом с клон-голосом.
        # Ключа нет — оба как раньше, поведение прежнее.
        kvv = g.get("kv_quant_v", "") or kv
        # ЦЕНУ КВАНТА НАДО МЕРИТЬ, А НЕ ЗНАТЬ (2026-09-05, замер
        # llama-bench на Qwen3.5-9B Q4_K_M, prefill 2048 токенов):
        #     f16          — 4906 ток/с
        #     f16 + fa     — 5033
        #     q8_0 / q8_0  — 5006
        #     q8_0 / q4_0  —  327   ← в пятнадцать раз хуже
        # Экономия памяти от q4_0 на значениях была настоящей: минус
        # четверть кэша. Цена оказалась в пятнадцать раз дороже экономии.
        # Причина, судя по всему, в геометрии: у этой модели длина головы
        # 256, а быстрые ядра внимания написаны под 64/96/128 — на 256 с
        # четырёхбитными значениями движок сваливается в общий медленный
        # путь. Наружу это выглядело как «шесть секунд молчит перед
        # ответом», и искали причину где угодно, только не в кэше.
        #
        # Отсюда правило: РАЗНЫЙ квант для ключей и значений разрешён
        # только когда он замерен на ЭТОЙ модели и этой сборке. Флаг
        # llamacpp.kv_v_benchmarked ставится руками после прогона
        # tools/bench_llm.py — не «включи и посмотри», а «померь и решай».
        if kvv != kv and not g.get("kv_v_benchmarked", False):
            log.info("llamacpp: kv_quant_v=%s не замерен на этой модели — "
                     "беру как у ключей (%s). Прогони tools/bench_llm.py и "
                     "поставь llamacpp.kv_v_benchmarked, если он быстрее",
                     kvv, kv)
            kvv = kv
        if kv and kv != "f16":
            args += ["--cache-type-k", kv]
        if kvv and kvv != "f16":
            args += ["--cache-type-v", kvv]
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
            # ══ ЧУЖОЙ СЕРВЕР НА НАШЕМ ПОРТУ — НЕ ВОЙНА, А ПОПУТЧИК ══
            # (2026-08-25, живой разбор.) Владелец запустил собранное
            # приложение, не закрыв Сайку из исходника. Веб-серверы у них
            # разные (8765 и 8799) и мирно ужились, а порт llama-server в
            # обоих конфигах ОДИН — 8771. Дальше начиналась война: каждая
            # сторона видела живой /health с ЧУЖИМ отпечатком настроек,
            # решала «настройки изменились», убивала соседа и поднимала
            # свой сервер. В логе это видно как два запуска подряд с
            # разницей в 0.4 секунды, а в диспетчере — два llama-server.exe
            # по 5 ГБ видеопамяти каждый. Клон-голосу (ещё 5 ГБ) на карте
            # места уже не оставалось НИКОГДА — отсюда «в проге голос не
            # поднимается, хотя из исходника при той же нагрузке работал».
            #
            # Отпечаток настроек отвечает на вопрос «мои ли это флаги», а
            # нужен ответ на другой: «мой ли это процесс». Его мы знаем
            # точно — по _proc. Чужой сервер не трогаем: если он крутит ту
            # же модель, просто берём его (одна модель на карте вместо
            # двух); если другую — говорим об этом словами, а не убиваем
            # чужую работу молча.
            ours = _proc is not None and _proc.poll() is None
            if not ours:
                want = Path(find_model() or "").stem
                got = _running_alias()
                if want and got and want == got:
                    log.info("llamacpp: на порту %s уже работает сервер с той "
                             "же моделью «%s» — беру его, второй не поднимаю "
                             "(иначе две копии модели в видеопамяти)",
                             port(), got)
                    note_alive()
                    return {"ok": True, "port": port(), "shared": True}
                return {"error": "на порту %s уже работает чужой llama-server"
                                 " с моделью «%s», а мне нужна «%s». Скорее "
                                 "всего запущены две Сайки разом (исходник и "
                                 "собранное приложение) — закрой лишнюю, либо "
                                 "разведи их по портам: llamacpp.port."
                                 % (port(), got or "неизвестной", want or "?")}
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
        from anamorf.llm import one_local
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
    """Погасить сервер и освободить VRAM (аналог unload_model у Ollama).

    ОТВЕТ ЧЕСТНЫЙ (06.09.2026). Владелец: «я нажал раз четыреста, ничего
    не произошло за целую минуту». Так и было: модель выгрузилась с
    первого раза, а дальше выгружать было нечего — но ответ всё равно
    возвращался бодрый, и вкладка каждый раз писала «выгрузила». Человек
    жмёт и жмёт, потому что интерфейс обещает действие, которого нет.
    Если сервера уже нет — так и говорим."""
    global _proc
    if _proc is None or _proc.poll() is not None:
        kill_stale()
        _proc = None
        return "нечего выгружать: llama-server уже не запущен"
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
