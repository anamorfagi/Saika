"""ПЛАН ПАМЯТИ: делим железо ДО старта, а не дракой после.

Владелец: «сделай оптимизацию системы таким образом, чтобы она
оптимизировала ресурсы и гарантированно запускала выбранные компоненты»
(23.08.2026) и «нужна модель нормальная по качеству, окно 120 тысяч, всё
как часы, и игру одновременно» (05.09.2026).

Правило: выбранные человеком компоненты — это ЗАКАЗ. Считаем его
стоимость заранее и подгоняем гибкие величины. Не сходится — говорим
вслух, ЧЕМ пожертвовать, а не жертвуем молча.

ЧТО ПЕРЕПИСАНО 05.09.2026 И ПОЧЕМУ
1. ПОТОЛОК ОКНА БЫЛ 16384. В списке стояло (16384, 12288, 8192), и
   больше взяться было неоткуда. То есть просьба «окно под 120 тысяч»
   была невыполнима не из-за железа, а из-за трёх чисел в этом файле.
   Теперь лестница идёт от 131072 вниз, а верх ограничен родным окном
   самой модели.
2. KV СЧИТАЛСЯ ПРОПОРЦИЕЙ ОТ РАЗМЕРА ФАЙЛА. Для MoE это ошибка в разы:
   у 35B-A3B файл 21 ГБ, а KV живёт только во внимании. Теперь считается
   по устройству модели из её же заголовка (anamorf/gguf_meta.py).
3. НЕ БЫЛО ПОНЯТИЯ «ЧАСТЬ ВЕСОВ В СИСТЕМНОЙ ПАМЯТИ». Флаг --n-cpu-moe
   уводит экспертов в ОЗУ; на карте остаётся внимание. Без этого знания
   план считал 21 ГБ невлезающими и был прав — и потому предлагал только
   резать. Теперь он подбирает, сколько слоёв экспертов отдать в ОЗУ.
4. ГОЛОС СЧИТАЛСЯ ВЕЧНЫМ ЖИЛЬЦОМ. Клон-голос занимает пять гигабайт
   ради секунд речи в час. Если он поднимается по требованию
   (tts.ondemand), его место — не постоянный вычет, а пиковый запас,
   который делится со зрением: одновременно они не нужны.

Оценки по-прежнему грубые там, где нечего читать, и точные там, где есть
что прочитать. План нужен, чтобы не заказывать тринадцать литров в
десятилитровое ведро.
"""
import logging
from pathlib import Path

from anamorf.config import CFG

log = logging.getLogger("saika.vramplan")

# стоимость тяжёлых голосов в VRAM (замерено по живым логам проекта)
_VOICE_GB = {"qwen3": 5.0, "omni": 4.0, "xtts": 2.5, "f5": 2.5, "f5ru": 2.5}
# слух: gigaam ~1.2, whisper large ~3 — берём по имени
_STT_GB = {"gigaam": 1.2, "whisper": 3.0, "vosk": 0.3, "voxtral": 2.5}
# зрение: проектор картинок живёт рядом с моделью, пока смотрит
_VISION_GB = 1.2
# ЗАПАС НА СИСТЕМУ. Не «на всякий случай», а по замеру: рабочий стол
# Windows (dwm), браузер и Blender держат на карте полтора-два гигабайта,
# и их никто не спрашивает.
#
# ПОЧЕМУ ЭТО КРИТИЧНО, А НЕ АККУРАТНО (2026-09-05, живой замер в логе
# движка). Один и тот же промпт на 4543 токена:
#     утром, когда карта была свободна — 1004 мс (4523 ток/с)
#     ночью, когда план заполнил её под завязку — 28740 мс (158 ток/с)
# Двадцать восемь раз. Не «чуть медленнее» — качественно другая машина.
# Причина в том, как Windows ведёт себя при переполнении видеопамяти: он
# НЕ отказывает в выделении, он молча начинает подкачивать через шину.
# Всё продолжает работать и выглядеть исправным, просто в тридцать раз
# медленнее. Это ровно то, на что жалуется владелец: «память загружена, а
# оно не работает».
#
# Поэтому план обязан оставлять карте воздух. План, который сходится в
# «16.0 из 16.0», — это не идеально упакованный план, это план, который
# сам себе выстрелил в ногу.
_RESERVE_GB = 1.6
# И сверх запаса — жёсткий потолок доли карты. Даже если замер уверяет,
# что свободно всё, занимать всё нельзя.
_MAX_FILL = 0.92
# ОКНА, ИЗ КОТОРЫХ ВЫБИРАЕМ. Сверху вниз: берём первое, что влезает.
# НИЖЕ 8192 ОКНА НЕ БЫВАЕТ (27.08.2026). Её собственный промпт — характер,
# память, инструменты — стабильно 7.5–8 тысяч токенов. Окно 4096 не «хуже»,
# оно нерабочее по построению: движок отвечает 400 на КАЖДЫЙ ход.
_CTX_STEPS = (131072, 98304, 65536, 49152, 32768, 24576, 16384, 12288, 8192)

# ПОЛ ОКНА — ЭТО РАЗМЕР ЕЁ СОБСТВЕННОГО ПРОМПТА, А НЕ КРАСИВОЕ ЧИСЛО
# (2026-09-05, живой лог во время прогона стенда: план ужал окно до 8192,
# а следом в том же логе — «под систему нужно ~14390 симв + инструменты
# 2307, а всего бюджета 16182». То есть в окно не влезал даже её характер
# с описаниями инструментов, до истории разговора дело не доходило вовсе.
# Формально план сработал: он честно уложился в свободную видеопамять.
# Фактически он поднял мозг, который не может думать.)
#
# Ниже этого окна поднимать сервер бессмысленно: лучше честно сказать,
# что заказ не влезает, и назвать, чем жертвовать, — чем молча получить
# «Окно контекста мало» на каждом ходу.
def _ctx_floor() -> int:
    try:
        return int(CFG.get("llamacpp.n_ctx_floor", 16384))
    except Exception:
        return 16384

# наши же процессы на карте: их память при перезапуске освободится и
# снова достанется заказу. Чужое (игра, браузер) НЕ трогаем.
_OUR_GPU = ("python", "llama-server", "llama", "ollama", "lm studio",
            "lmstudio", "koboldcpp", "anamorf")

_META_CACHE = {}


def meta(model_path: str) -> dict:
    """Паспорт модели из её же файла. Кэш по пути и времени правки:
    заголовок читать дёшево, но незачем делать это на каждый ход."""
    if not model_path:
        return {}
    try:
        p = Path(model_path)
        key = (str(p), p.stat().st_mtime_ns)
        if key in _META_CACHE:
            return _META_CACHE[key]
        from anamorf import gguf_meta
        m = gguf_meta.read(str(p))
        _META_CACHE.clear()
        _META_CACHE[key] = m
        log.info("план памяти: %s", gguf_meta.describe(m))
        return m
    except Exception as e:
        log.debug("паспорт модели не прочитался (%s) — считаю по-старому: %s",
                  model_path, e)
        return {}


def own_est_gb(weights_gb: float) -> float:
    """Сколько видеопамяти держат НАШИ уже поднятые движки.

    ЗАЧЕМ (27.08.2026). Раньше своё считалось по колонке used_memory из
    nvidia-smi. На Windows её нет: карта отвечает «[N/A]» без прав
    администратора. Своё выходило нулём, свободного — два гигабайта из
    шестнадцати (всё остальное держим мы сами!), и план каждый раз решал
    «не влезает даже с окном 4096». Дальше сервер поднимался с окном, куда
    её собственный промпт не влезает НИКОГДА, и каждый ход отвечал 400.
    Связка ломалась не от нехватки памяти, а от слепоты замера."""
    names = []
    try:
        from anamorf import system_control as sc
        names = [(n or "").lower() for n, _pid, _mb in sc.gpu_top_processes(64)]
    except Exception:
        pass
    own = 0.0
    if any("llama" in n for n in names):
        try:
            cur = int(CFG.get("llamacpp.n_ctx_live", 0) or 0)
        except Exception:
            cur = 0
        own += weights_gb + kv_gb(weights_gb, cur or _CTX_STEPS[-1])
    if any("python" in n or "anamorf" in n for n in names):
        own += voice_gb() + stt_gb()
    return own


def total_gb(weights_gb: float = 0.0) -> float:
    """Сколько видеопамяти реально доступно ЗАКАЗУ.

    Доступно нам = свободно СЕЙЧАС + то, что держат НАШИ же движки (их
    перезапуск освободит и вернёт в общий котёл). Чужие процессы — игра,
    браузер — вычтены естественно: их память не входит ни в free, ни в наш
    own. Верхняя граница — общая ёмкость карты."""
    try:
        from anamorf import system_control as sc
        free, total = sc.gpu_mem()
        if free is not None and total:
            try:
                own = sum(m for n, _pid, m in sc.gpu_top_processes(64)
                          if any(o in (n or "").lower() for o in _OUR_GPU))
            except Exception:
                own = 0
            own_gb = max(own / 1024.0, own_est_gb(weights_gb))
            avail = min(total / 1024.0, free / 1024.0 + own_gb) * 1024.0
            return max(1.0, avail) / 1024.0
    except Exception:
        pass
    try:
        import torch
        return torch.cuda.get_device_properties(0).total_memory / (1 << 30)
    except Exception:
        return float(CFG.get("guard.vram_total_gb", 16.0))


def total_cap_gb() -> float:
    """Полная ёмкость карты — верхняя граница для потолка заполнения."""
    try:
        from anamorf import system_control as sc
        _free, total = sc.gpu_mem()
        if total:
            return total / 1024.0
    except Exception:
        pass
    try:
        import torch
        return torch.cuda.get_device_properties(0).total_memory / (1 << 30)
    except Exception:
        return float(CFG.get("guard.vram_total_gb", 16.0))


def ram_free_gb() -> float:
    """Свободная СИСТЕМНАЯ память — в неё уезжают эксперты MoE. Считаем
    доступное, а не «всего»: заказать 26 ГБ под экспертов при живой игре
    на 12 — это своп и смерть по скорости, а не работа."""
    try:
        import psutil
        return psutil.virtual_memory().available / (1 << 30)
    except Exception:
        return float(CFG.get("guard.ram_free_gb", 16.0))


def voice_gb() -> float:
    if not CFG.get("tts.enabled", True):
        return 0.0
    eng = (str(CFG.get("tts.engine", "") or "")
           or str(CFG.get("tts.engine_was", "") or "")).lower()
    for k, v in _VOICE_GB.items():
        if k in eng:
            return v
    return 0.3                                     # лёгкий голос — копейки


def stt_gb() -> float:
    eng = str(CFG.get("stt.engine", "") or "").lower()
    for k, v in _STT_GB.items():
        if k in eng:
            return v
    return 0.5


def vision_gb() -> float:
    return _VISION_GB if CFG.get("vision.enabled", False) else 0.0


def _companions() -> tuple:
    """Что ещё живёт на карте рядом с мозгом, и сколько это стоит.

    ДВА РЕЖИМА, И РАЗНИЦА ПРИНЦИПИАЛЬНАЯ.
    Резидентный (как было всегда): голос, слух и зрение стоят каждый своё
    и стоят это круглосуточно. Пять гигабайт под клон-голос держатся и
    тогда, когда он молчит час подряд.
    По требованию (tts.ondemand): они поднимаются на фразу и отпускают
    карту. Тогда с мозга берётся не сумма, а ПИК — самый дорогой из тех,
    кто может проснуться, потому что одновременно они не нужны. Слух —
    исключение: он слушает всегда, его место резидентно в любом режиме.

    Возвращает (постоянно, пик_под_требование, расшифровка)."""
    v, s, e = voice_gb(), stt_gb(), vision_gb()
    if CFG.get("tts.ondemand", False):
        peak = max(v, e)
        return s, peak, (f"слух {s:.1f} постоянно + пик под голос/зрение "
                         f"{peak:.1f}")
    return v + s + e, 0.0, (f"голос {v:.1f} + слух {s:.1f} + зрение {e:.1f} "
                            f"(все резидентно)")


def kv_gb(weights_gb: float, n_ctx: int, m: dict = None,
          quant: str = "") -> float:
    """Сколько видеопамяти займёт KV-кэш.

    Если паспорт модели прочитан — считаем честно, по числу слоёв и
    KV-голов. Если нет — старая грубая пропорция от веса: она врёт на MoE,
    но лучше, чем ничего, и работает как раньше на плотных моделях."""
    if m and m.get("n_head_kv"):
        try:
            from anamorf import gguf_meta
            q = quant or str(CFG.get("llamacpp.kv_quant", "q8_0") or "q8_0")
            qv = str(CFG.get("llamacpp.kv_quant_v", "") or "") or q
            return gguf_meta.kv_gb(m, n_ctx, q, qv)
        except Exception:
            pass
    return weights_gb * 0.011 * (n_ctx / 1024.0)


def _fit_moe(m, gpu_budget, ram_free, ctx, quant):
    """Сколько слоёв экспертов увести в ОЗУ, чтобы окно `ctx` влезло.

    Меньше — лучше: каждый слой экспертов, оставшийся на карте, считается
    на карте, а это в разы быстрее. Поэтому идём снизу вверх и берём
    первое подходящее число, а не сразу «все в ОЗУ».

    Возвращает (n_cpu_moe, gpu_gb, ram_gb) или None, если не влезает даже
    когда все эксперты в системной памяти."""
    lay = int(m.get("n_layer") or 0)
    exps = float(m.get("gb_experts") or 0.0)
    rest = float(m.get("gb_rest") or 0.0)
    if not (lay and exps):
        return None
    kv = kv_gb(0, ctx, m, quant)
    for n in range(0, lay + 1):
        on_cpu = exps * (n / lay)
        on_gpu = rest + (exps - on_cpu) + kv
        if on_gpu <= gpu_budget and on_cpu <= ram_free:
            return n, on_gpu, on_cpu
    return None


def plan(weights_gb: float = 0.0, model_path: str = "",
         want_ctx: int = 0) -> dict:
    """Уложить заказ в железо.

    Возвращает {fits, n_ctx, n_cpu_moe, note, parts}. n_cpu_moe = 0
    означает «MoE тут не при чём, всё на карте, как раньше»."""
    m = meta(model_path)
    quant = str(CFG.get("llamacpp.kv_quant", "q8_0") or "q8_0")
    if m.get("gb_total"):
        weights_gb = m["gb_total"]
    total = total_gb(weights_gb)
    ram = ram_free_gb()
    fixed_res, peak, who = _companions()

    # потолок окна: чего просит человек и что умеет сама модель
    top = int(want_ctx or CFG.get("llamacpp.n_ctx_want", 0) or 0)
    native = int(m.get("ctx_train") or 0)
    floor = _ctx_floor()
    steps = [c for c in _CTX_STEPS
             if (not top or c <= top) and (not native or c <= native)
             and c >= floor]
    if not steps:
        steps = [min(floor, native or floor)]

    # видеопамять, которая остаётся мозгу после соседей
    cap = total_cap_gb() * _MAX_FILL
    if total > cap:
        total = cap
    budget = total - fixed_res - peak - _RESERVE_GB

    is_moe = bool(m.get("n_expert"))
    for ctx in steps:
        if is_moe:
            got = _fit_moe(m, budget, ram - 2.0, ctx, quant)
            if got:
                n, on_gpu, on_cpu = got
                note = (f"{m.get('name', 'модель')}: окно {ctx}, экспертов "
                        f"в ОЗУ {n} из {m['n_layer']} слоёв ({on_cpu:.1f} ГБ "
                        f"из {ram:.1f} свободных); на карте {on_gpu:.1f} + "
                        f"{who} + запас {_RESERVE_GB:.1f} = "
                        f"{on_gpu + fixed_res + peak + _RESERVE_GB:.1f} из "
                        f"{total:.1f} ГБ — влезает")
                return {"fits": True, "n_ctx": ctx, "n_cpu_moe": n,
                        "note": note, "meta": m,
                        "parts": {"gpu": on_gpu, "ram": on_cpu,
                                  "resident": fixed_res, "peak": peak,
                                  "reserve": _RESERVE_GB, "total": total,
                                  "ram_free": ram}}
            continue
        need = weights_gb + kv_gb(weights_gb, ctx, m, quant)
        if need <= budget:
            note = (f"мозг {weights_gb:.1f} + окно {ctx} "
                    f"({kv_gb(weights_gb, ctx, m, quant):.1f}) + {who} + "
                    f"запас {_RESERVE_GB:.1f} = "
                    f"{need + fixed_res + peak + _RESERVE_GB:.1f} из "
                    f"{total:.1f} ГБ — влезает")
            return {"fits": True, "n_ctx": ctx, "n_cpu_moe": 0, "note": note,
                    "meta": m,
                    "parts": {"gpu": need, "ram": 0.0, "resident": fixed_res,
                              "peak": peak, "reserve": _RESERVE_GB,
                              "total": total, "ram_free": ram}}

    # не влезло даже с минимальным окном — называем жертву вслух
    low = steps[-1]
    if is_moe:
        lack = (float(m.get("gb_rest") or 0) + kv_gb(0, low, m, quant)
                - budget)
        why = (f"даже со всеми экспертами в ОЗУ на карте остаётся "
               f"{float(m.get('gb_rest') or 0):.1f} весов + "
               f"{kv_gb(0, low, m, quant):.1f} кэша")
    else:
        lack = weights_gb + kv_gb(weights_gb, low, m, quant) - budget
        why = f"мозг целиком на карте — {weights_gb:.1f} ГБ"
    v = voice_gb()
    note = (f"не сходится даже с окном {low}: не хватает {max(0, lack):.1f} ГБ "
            f"({why}; соседи: {who}). Освободит место: лёгкий голос вместо "
            f"клона ({v:.1f} ГБ) либо подъём голоса по требованию "
            f"(tts.ondemand)")
    return {"fits": False, "n_ctx": low,
            "n_cpu_moe": int(m.get("n_layer") or 0) if is_moe else 0,
            "note": note, "meta": m,
            "parts": {"gpu": 0.0, "ram": 0.0, "resident": fixed_res,
                      "peak": peak, "reserve": _RESERVE_GB, "total": total,
                      "ram_free": ram}}
