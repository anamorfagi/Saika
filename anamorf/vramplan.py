"""ПЛАН ПАМЯТИ: делим видеокарту ДО старта, а не дракой после (2026-08-23).

Владелец: «сделай оптимизацию системы таким образом, чтобы она
оптимизировала ресурсы и гарантированно запускала выбранные компоненты».

До этого карта делилась явочным порядком: кто первым встал — того и
память, а сторож железа потом душил лишнего. Живой пример сегодняшнего
дня: 14B-модель (8 ГБ весов) + клон-голос (~5.5 ГБ) + окно 16384 на карте
в 16 ГБ — сторож глушил llama-server каждые полминуты, и «выбранная
модель не переключается».

Правило переворачивается: выбранные человеком компоненты — это ЗАКАЗ.
Считаем его стоимость заранее и подгоняем единственную гибкую величину —
окно контекста мозга. Не сходится даже с минимальным окном — честно
говорим, ЧЕМ пожертвовать, а не жертвуем молча.

Все оценки — в гигабайтах и нарочно грубые (плюс-минус полгига): план
нужен, чтобы не заказывать тринадцать литров в десятилитровое ведро, а
не чтобы попасть в миллилитр.
"""
import logging
from pathlib import Path

from anamorf.config import CFG

log = logging.getLogger("saika.vramplan")

# стоимость тяжёлых голосов в VRAM (замерено по живым логам проекта)
# qwen3 — 5.0, не 5.5: живой замер 23.08 — 14B Q4_K_S (8 ГБ) + клон + окно
# 8192 реально работают на 16 ГБ; план обязан сходиться с реальностью,
# иначе он режет окно там, где всё влезает
_VOICE_GB = {"qwen3": 5.0, "omni": 4.0, "xtts": 2.5, "f5": 2.5, "f5ru": 2.5}
# слух: gigaam ~1.2, whisper large ~3 — берём по имени
_STT_GB = {"gigaam": 1.2, "whisper": 3.0, "vosk": 0.3}
# запас на систему, композитор и мелочь, которую не считаем
_RESERVE_GB = 1.0
# окна, из которых выбираем (больше — лучше, если влезает)
# НИЖЕ 8192 ОКНА НЕ БЫВАЕТ (27.08.2026). Её собственный промпт — характер,
# память, инструменты — стабильно 7.5–8 тысяч токенов. Окно 4096 не «хуже»,
# оно нерабочее по построению: движок отвечает 400 на КАЖДЫЙ ход. Предлагать
# его как компромисс — значит поднять заведомо мёртвый мозг и молчать об этом.
_CTX_STEPS = (16384, 12288, 8192)


# наши же процессы на карте: их память при перезапуске освободится и
# снова достанется заказу. Чужое (игра, браузер) НЕ трогаем.
_OUR_GPU = ("python", "llama-server", "llama", "ollama", "lm studio",
            "lmstudio", "koboldcpp", "anamorf")


def own_est_gb(weights_gb: float) -> float:
    """Сколько видеопамяти держат НАШИ уже поднятые движки.

    ЗАЧЕМ (27.08.2026, живой случай владельца: «эта ллм, мой голос и слух
    должны работать одновременно — и работали»). Раньше своё считалось по
    колонке used_memory из nvidia-smi. На Windows её нет: карта отвечает
    «[N/A]» без прав администратора. Своё выходило нулём, свободного на
    карте — два гигабайта из шестнадцати (всё остальное держим мы сами!),
    и план каждый раз приходил к выводу «не влезает даже с окном 4096».
    Дальше сервер поднимался с окном 4096, куда её собственный промпт на
    восемь тысяч токенов не влезает НИКОГДА, — и каждый ход отвечал 400.
    Рабочая связка ломалась не от нехватки памяти, а от слепоты замера.

    Считаем по тому, что мы сами и загрузили: живой llama-server — это вес
    модели плюс KV текущего окна; живой процесс Сайки — голос и слух."""
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

    БЫЛО (до 2026-08-25): бралась ОБЩАЯ ёмкость карты. Планировщик не видел,
    что часть уже занята чужим — игрой, браузером, второй копией Сайки, — и
    считал модель «влезающей», хотя свободного места меньше. Отсюда живой
    случай владельца: при запущенном Genshin клон-голос не поднимался
    («не осталось видеопамяти»), хотя из исходника при той же нагрузке
    работал. Это ровно та ошибка, о которой он и просил: «гарантированно
    запускала выбранные компоненты».

    СТАЛО: доступно нам = свободно СЕЙЧАС + то, что держат НАШИ же движки
    (мозг/голос/слух — их перезапуск освободит и вернёт в общий котёл).
    Чужие процессы вычтены естественно: их память просто не входит ни в
    free, ни в наш own. Верхняя граница — общая ёмкость карты."""
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


def kv_gb(weights_gb: float, n_ctx: int) -> float:
    """KV-кэш растёт с окном и с размером модели. Грубая пропорция,
    снятая с живых замеров (q8_0-кэш): 8 ГБ весов ≈ 1.4 ГБ на 16k."""
    return weights_gb * 0.011 * (n_ctx / 1024.0)


def plan(weights_gb: float) -> dict:
    """Уложить заказ в карту. Возвращает {fits, n_ctx, note, parts}."""
    total = total_gb(weights_gb)
    v, s = voice_gb(), stt_gb()
    fixed = weights_gb + v + s + _RESERVE_GB
    for ctx in _CTX_STEPS:
        need = fixed + kv_gb(weights_gb, ctx)
        if need <= total:
            note = (f"мозг {weights_gb:.1f} + голос {v:.1f} + слух {s:.1f} "
                    f"+ запас {_RESERVE_GB:.1f} + окно {ctx} "
                    f"({kv_gb(weights_gb, ctx):.1f}) = {need:.1f} из "
                    f"{total:.1f} ГБ — влезает")
            return {"fits": True, "n_ctx": ctx, "note": note,
                    "parts": {"weights": weights_gb, "voice": v, "stt": s,
                              "reserve": _RESERVE_GB, "total": total}}
    # не влезло даже с минимальным окном — называем жертву вслух
    lack = fixed + kv_gb(weights_gb, _CTX_STEPS[-1]) - total
    note = (f"не сходится даже с окном {_CTX_STEPS[-1]}: не хватает "
            f"{lack:.1f} ГБ. Либо лёгкий голос вместо клона "
            f"(освободит {v:.1f}), либо модель поменьше")
    return {"fits": False, "n_ctx": _CTX_STEPS[-1], "note": note,
            "parts": {"weights": weights_gb, "voice": v, "stt": s,
                      "reserve": _RESERVE_GB, "total": total}}
