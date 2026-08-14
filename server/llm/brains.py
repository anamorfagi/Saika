"""ЛЕСТНИЦА МОЗГОВ (2026-08-13).

ЗАЧЕМ. Владелец: «она должна уметь достигать результата; если не получилось —
просто использует мозг с более высоким рейтингом». До сегодня эскалация была
одноступенчатой: мелкая локальная модель -> ЕДИНСТВЕННЫЙ облачный слот
llm.cloud. Если этот слот пуст, отвалился по лимиту или сам не справился —
дальше идти было некуда, и Сайка оставалась барахтаться там же, где упала.
А ключи в secrets.json лежат СРАЗУ от нескольких бесплатных провайдеров
(gigachat, mistral, github, kimi…) — они просто не участвовали в подъёме.

ЧТО ЗДЕСЬ. Упорядоченный список «мозгов» от сильного к слабому:

    ladder()      -> [{"backend","model","rank","why","free"}...]
    higher_than() -> кто сильнее текущей модели (для эскалации)
    next_brain()  -> следующий по силе, ещё не пробованный и живой
    note_fail()   -> «этот мозг сейчас не отвечает» (остывает 10 минут)

ЧЕМ МЕРЯЕМ СИЛУ. ratings.llm_scores() меряет СКОРОСТЬ (tps) — для эскалации
это вредный ориентир: самая быстрая модель обычно самая тупая. Поэтому:
  1) ручная оценка владельца (manual:<имя>) — его слово выше всех;
  2) таблица RANK по имени модели — грубая, но честная оценка «мозгов»;
  3) облако по умолчанию выше локального парка.
Скорость участвует только как разделитель равных.

ЖИВОСТЬ. Облачный мозг попадает в лестницу, только если под его провайдера
реально есть ключ, — иначе эскалация упиралась бы в 401 и человек видел бы
«не смогла» вместо результата.
"""
import json
import logging
import time

from server.config import CFG, ROOT

log = logging.getLogger("saika.brains")

# ГРУБАЯ ОЦЕНКА МОЗГОВ ПО ИМЕНИ (1..10). Не бенчмарк — порядок подъёма.
# Совпадение по подстроке, сверху вниз, первое найденное выигрывает.
RANK = [
    # ВАЖЕН ПОРЯДОК: совпадение по подстроке, первое найденное выигрывает,
    # поэтому частное имя стоит ВЫШЕ общего («gpt-4.1-mini» перед «gpt-4.1»,
    # иначе мелкая модель получала бы оценку старшей).
    ("claude", 10), ("gpt-5", 10), ("o3-", 10),
    ("gpt-4.1-mini", 7), ("gpt-4.1", 9), ("gpt-oss-120b", 8),
    ("kimi-k3", 9), ("kimi", 9),
    ("deepseek-v4-flash", 7), ("deepseek-v4", 9), ("deepseek", 8),
    ("gigachat-2-max", 9), ("gigachat-2-ultra", 9), ("gigachat-2-pro", 9),
    ("gigachat-2", 8), ("gigachat", 7),
    ("mistral-large", 9), ("mistral-medium", 8), ("mistral-small", 6),
    ("nemotron", 8), ("glm-4.7-flash", 7), ("glm-4.7", 8), ("glm", 7),
    ("gemini-3.6-flash", 8), ("gemini-3", 9), ("gemini", 8),
    ("llama-3.3-70b", 8), ("llama-3.1-8b", 4),
    ("qwen3.6-27b", 8), ("qwen3.6", 8),
    # Alibaba Model Studio (2026-08-13)
    ("qwen3-max", 9), ("qwen3.5-397b", 9), ("qwen3.5-plus", 8),
    ("qwen3-plus", 8), ("qwq-plus", 8), ("qwen3-vl-plus", 8),
    ("qwen3-coder-plus", 8), ("qwen3.5-flash", 7), ("qwen3.7-flash", 7),
    ("minimax-m2.7", 8), ("minimax", 7),
    ("gpt-oss-20b", 6), ("gpt-oss", 8),
    # локальный парк — по размеру, это единственное, что видно из имени
    ("120b", 9), ("72b", 8), ("70b", 8), ("32b", 7), ("31b", 7),
    ("30b", 7), ("27b", 7), ("26b", 7), ("24b", 7), ("14b", 6),
    ("12b", 6), ("9b", 5), ("8b", 5), ("7b", 5), ("e4b", 3),
    ("4b", 3), ("3b", 3), ("e2b", 2), ("2b", 2), ("1b", 1),
    ("flash", 7), ("mini", 6), ("lite", 6),
]

DEFAULT_RANK = 5
_CLOUD_BONUS = 1        # облако обычно умнее домашнего парка при равном имени

# ПЛАТНЫЕ ПРОВАЙДЕРЫ (2026-08-13, поправка владельца: «кими платный API-ключ
# если что»). Лестница поднимается САМА, без спроса — значит она не имеет
# права тратить деньги владельца по своей инициативе. Платные мозги в
# автоподъём не попадают вообще; выбрать такую модель руками по-прежнему
# можно, запрет только на самодеятельность. Разрешить: llm.paid_ok = true.
PAID_PROVIDERS = {"kimi", "moonshot", "openai", "anthropic", "openrouter",
                  "deepseek", "together", "fireworks"}

# ЗАДЕРЖКА ТОЖЕ ЕСТЬ КАЧЕСТВО (2026-08-13, владелец: «3-ка бывает на 30
# секунд отвечает»). Мозг, который думает полминуты, для голосового режима
# бесполезен, каким бы умным он ни был: человек за это время встанет с
# дивана. Держим скользящее среднее времени ответа и понижаем медленных на
# ступень — не выкидываем, но пропускаем вперёд тех, кто отвечает.
_LAT: dict = {}
_LAT_ALPHA = 0.4
_LAT_LOADED = {"done": False}


# ОКНО ОБЛАЧНЫХ МОДЕЛЕЙ (2026-08-15). Знать его надо не ради красоты:
# бюджет истории считался единым потолком 9000 символов на все облака —
# он выбирался под kimi, который дорого жевал длинные промпты. У
# GigaChat-2-Pro окно 128k и свой префикс-кэш, и этот потолок отнимал у
# Сайки память там, где платить за неё почти не нужно. Цифры — паспортные
# окна моделей в ТОКЕНАХ; неизвестная модель даёт 0 = «не знаю, оставь
# как было». Порядок тот же, что в RANK: частное имя выше общего.
WINDOW = [
    ("gpt-4.1", 1_000_000), ("gpt-5", 400_000), ("claude", 200_000),
    ("gigachat-2", 128_000), ("gigachat", 32_000),
    ("kimi", 256_000), ("deepseek", 128_000),
    ("mistral-medium", 128_000), ("mistral-small", 128_000),
    ("mistral", 128_000),
    ("gemini", 1_000_000), ("glm", 128_000),
    ("llama-3.3-70b", 24_000), ("llama-3.1", 16_000),
    ("qwen3-30b", 32_000), ("qwen3", 128_000), ("qwen", 32_000),
    ("minimax", 200_000), ("gpt-oss", 128_000), ("nemotron", 128_000),
]

# символов на токен — тот же осторожный ориентир, что в main.py: кириллица
# у большинства токенизаторов идёт вдвое плотнее английского
_CH_PER_TOK = 1.5


def window_tokens_of(model: str) -> int:
    m = (model or "").lower()
    for key, win in WINDOW:
        if key in m:
            return win
    return 0


def window_chars_of(model: str) -> int:
    """Паспортное окно в символах. 0 — модель незнакомая."""
    return int(window_tokens_of(model) * _CH_PER_TOK)


def _lat_file():
    from server.config import resolve
    d = resolve("data")
    d.mkdir(parents=True, exist_ok=True)
    return d / "brain_latency.json"


def _lat_load():
    """ЗАМЕРЫ ПЕРЕЖИВАЮТ ПЕРЕЗАПУСК (2026-08-14). Держали в памяти — и
    каждый старт начинался с чистого листа: GigaChat, накануне отвечавший
    по 46 секунд, снова оказывался первым в очереди на руки и снова
    тормозил весь разговор. Опыт, который стирается, опытом не является."""
    if _LAT_LOADED["done"]:
        return
    _LAT_LOADED["done"] = True
    try:
        import json
        f = _lat_file()
        if f.exists():
            for k, v in (json.loads(f.read_text(encoding="utf-8")) or {}).items():
                b, _, m = k.partition("|")
                if m:
                    _LAT[(b, m)] = float(v)
            log.info("Задержки мозгов подняты с диска: %d", len(_LAT))
    except Exception as e:
        log.debug("замеры задержек не прочитались: %s", e)


def _lat_save():
    try:
        import json
        data = {f"{b}|{m}": round(v, 2) for (b, m), v in _LAT.items()}
        _lat_file().write_text(json.dumps(data, ensure_ascii=False, indent=1),
                               encoding="utf-8")
    except Exception as e:
        log.debug("замеры задержек не сохранились: %s", e)


def note_latency(backend: str, model: str, seconds: float):
    """Сколько этот мозг думал в этот раз (скользящее среднее)."""
    if seconds <= 0:
        return
    _lat_load()
    k = (backend, model)
    was = _LAT.get(k)
    _LAT[k] = seconds if was is None else was * (1 - _LAT_ALPHA) + seconds * _LAT_ALPHA
    _lat_save()


def latency_of(backend: str, model: str) -> float:
    _lat_load()
    return _LAT.get((backend, model), 0.0)


# «этот мозг сейчас не отвечает»: (backend, model) -> время, до которого
# его не предлагаем. Лимиты бесплатных тиров, отвалившийся VPN, 401 —
# всё это временно, поэтому не выкидываем навсегда, а даём остыть.
_SICK: dict = {}
_SICK_S = 600


def rank_of(model: str, backend: str = "") -> int:
    """Оценка МОЗГОВ 1..10 по имени модели.

    Ручная оценка владельца НЕ подменяет таблицу, а только сдвигает её.
    Живой случай, на котором это выяснилось: у gemma-4-e4b (4 миллиарда
    параметров) стояла ручная десятка — это оценка «моя рабочая лошадка,
    быстрая», а не «умнее GPT». Взяв её за ум, лестница решила, что выше
    подниматься некуда, и эскалация умирала на месте. Поэтому усредняем:
    слово владельца слышно, но 4b не становится умнее облака."""
    name = (model or "").lower()
    base = None
    for pat, sc in RANK:
        if pat in name:
            base = sc
            break
    if base is None:
        base = DEFAULT_RANK
    if backend == "cloud":
        base = min(10, base + _CLOUD_BONUS)
    try:
        from server import ratings
        man = (ratings.manual_scores() or {}).get(model)
        if man:
            base = int(round((base * 2 + int(man)) / 3))
    except Exception:
        pass
    return max(1, min(10, base))


# ═══ ПАМЯТЬ НА ПОСЛЕДНИЕ МОЗГИ (2026-08-14) ═══
# Владелец: «я вот нах просил сделать запоминание всех моделей, которые
# были последние?». Просил. Помнился ровно ОДИН — тот, что в llm.model, —
# а список из десятка, между которыми он ходит весь день, каждый раз
# начинался с чистого листа: перезапуск, и порядок опять «как посчиталось».
#
# Теперь на диске лежит очередь последних: кем реально отвечали, когда и
# сколько раз. Это НЕ рейтинг — рейтинг про ум. Это привычка: при равном
# уме первым берётся тот, с кем работали, а не случайный сосед по таблице.
RECENT_PATH = ROOT / "data" / "brain_recent.json"
_RECENT: list | None = None
RECENT_MAX = 24


def recent() -> list:
    """[{backend, model, ts, hits}] — свежие первыми."""
    global _RECENT
    if _RECENT is None:
        try:
            _RECENT = json.loads(RECENT_PATH.read_text("utf-8"))
            if not isinstance(_RECENT, list):
                _RECENT = []
        except Exception:
            _RECENT = []
    return _RECENT


def note_used(backend: str, model: str):
    """Этой моделью только что отвечали. Зовётся отовсюду, идемпотентно."""
    if not model:
        return
    r = recent()
    key = (backend or "", model)
    for e in r:
        if (e.get("backend", ""), e.get("model", "")) == key:
            e["ts"] = time.time()
            e["hits"] = int(e.get("hits", 0)) + 1
            r.remove(e)
            r.insert(0, e)
            break
    else:
        r.insert(0, {"backend": backend or "", "model": model,
                     "ts": time.time(), "hits": 1})
    del r[RECENT_MAX:]
    try:
        RECENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RECENT_PATH.write_text(json.dumps(r, ensure_ascii=False, indent=1),
                               encoding="utf-8")
    except Exception as e:
        log.debug("память последних мозгов не записалась: %s", e)


def recent_pos(backend: str, model: str) -> int:
    """Насколько давно им отвечали: 0 — последний, 99 — не помним вовсе."""
    for i, e in enumerate(recent()):
        if (e.get("backend", ""), e.get("model", "")) == (backend or "", model):
            return i
    return 99


def note_fail(backend: str, model: str, why: str = ""):
    """Мозг не ответил — уводим его из лестницы на 10 минут."""
    _SICK[(backend, model)] = time.time() + _SICK_S
    log.info("Мозг %s/%s отложен на %dс: %s", backend, model, _SICK_S, why)


def is_sick(backend: str, model: str) -> bool:
    return time.time() < _SICK.get((backend, model), 0.0)


def revive(backend: str, model: str):
    _SICK.pop((backend, model), None)


def _cloud_candidates() -> list[dict]:
    """Настроенные облачные модели, У КОТОРЫХ ЕСТЬ КЛЮЧ."""
    from server.llm import manager
    out = []
    for e in manager.cloud_saved():
        prov, model = e.get("provider", ""), e.get("model", "")
        if not model:
            continue
        try:
            if not manager.cloud_key_for(prov):
                continue                      # ключа нет — не мозг, а 401
        except Exception:
            continue
        if prov in PAID_PROVIDERS and not CFG.get("llm.paid_ok", False):
            continue                          # чужие деньги без спроса — нет
        free = ""
        try:
            from server.llm import free_tiers
            c = free_tiers.get(prov) or {}
            free = c.get("free", "")
        except Exception:
            pass
        out.append({"backend": "cloud", "model": model,
                    "base_url": e.get("base_url", ""),
                    "provider": prov, "free": free,
                    "rank": rank_of(model, "cloud")})
    return out


def _local_candidates() -> list[dict]:
    from server.llm import manager
    out = []
    try:
        for m in manager.list_models():
            if m.get("backend") == "cloud":
                continue
            if "embed" in (m.get("name") or "").lower():
                continue
            out.append({"backend": m["backend"], "model": m["name"],
                        "base_url": "", "provider": "", "free": "",
                        "rank": rank_of(m["name"], m["backend"])})
    except Exception as e:
        log.debug("парк локальных моделей недоступен: %s", e)
    return out


def ladder(include_sick: bool = False) -> list[dict]:
    """Все доступные мозги от сильного к слабому."""
    try:
        from server import ratings
        tps = ratings.llm_scores() or {}
    except Exception:
        tps = {}
    cands = _cloud_candidates() + _local_candidates()
    seen, out = set(), []
    for c in cands:
        key = (c["backend"], c["model"])
        if key in seen:
            continue
        seen.add(key)
        if not include_sick and is_sick(*key):
            continue
        c["speed"] = tps.get(c["model"], 0)
        c["lat"] = round(latency_of(*key), 1)
        # медленный мозг спускается на ступень: полминуты молчания в
        # голосовом режиме дороже пары баллов ума
        slow = float(CFG.get("llm.slow_s", 15))
        c["rank_eff"] = c["rank"] - (1 if c["lat"] > slow else 0)
        out.append(c)
    out.sort(key=lambda c: (-c["rank_eff"], c["lat"] or 99, -c["speed"],
                            c["model"]))
    return out


def current() -> tuple[str, str]:
    b = CFG.get("llm.backend", "ollama")
    if b == "cloud":
        return "cloud", (CFG.get("llm.cloud", {}) or {}).get("model", "")
    return b, CFG.get("llm.model", "")


def higher_than(backend: str = "", model: str = "") -> list[dict]:
    """Мозги строго сильнее указанного (по умолчанию — текущего)."""
    if not model:
        backend, model = current()
    mine = rank_of(model, backend)
    return [c for c in ladder()
            if c["rank"] > mine and (c["backend"], c["model"]) != (backend, model)]


def next_brain(tried=()) -> dict | None:
    """Следующая ступень вверх: сильнее текущей, ещё не пробованная, живая.

    tried — набор кортежей (backend, model), уже опробованных В ЭТОМ ходе.
    Если выше ничего нет, отдаём просто самого сильного из непробованных:
    лучше повторить попытку другим мозгом того же уровня, чем сдаться."""
    tried = {tuple(t) for t in (tried or ())}
    b, m = current()
    tried.add((b, m))
    up = [c for c in higher_than(b, m) if (c["backend"], c["model"]) not in tried]
    if up:
        return up[0]
    rest = [c for c in ladder() if (c["backend"], c["model"]) not in tried]
    return rest[0] if rest else None


def for_hands(min_rank: int = 7) -> dict | None:
    """Мозг, которому можно доверить РУКИ.

    2026-08-13, живой лог: «открой Геншин» — ярлык в каталоге есть, нечёткий
    поиск даёт 70 баллов, а инструмент не вызван НИ РАЗУ. Пять реплик подряд
    уточняющих вопросов вместо одного app_launch. За рулём сидела
    gemma-4-e4b: она прекрасный собеседник на «привет», но команду в вызов
    не превращает — не потому что сломана, а потому что четыре миллиарда
    параметров.

    Правило простое и дешёвое: болтать может кто угодно, РАБОТАТЬ РУКАМИ —
    только тот, кто дотягивает до планки. Возвращаем самого быстрого из
    достаточно умных: для команды «сверни окно» ум сверх порога уже не
    улучшает результат, а секунды ожидания портят всё."""
    good = [c for c in ladder() if c["rank"] >= min_rank]
    if not good:
        return None
    # среди годных — по задержке (0 = ещё не мерили, такие вперёд не лезут)
    good.sort(key=lambda c: (c["lat"] or 5.0, -c["rank"]))
    return good[0]


def describe() -> dict:
    """Для интерфейса и для неё самой: какая сейчас лестница."""
    b, m = current()
    return {"current": {"backend": b, "model": m, "rank": rank_of(m, b)},
            "ladder": ladder(),
            "sick": [{"backend": k[0], "model": k[1],
                      "until": int(v - time.time())}
                     for k, v in _SICK.items() if time.time() < v]}
