"""РАЗДЕЛЕНИЕ НАЛОЖЕННЫХ ГОЛОСОВ — две дорожки из одного микрофона.

ЗАПРОС ВЛАДЕЛЬЦА, дословно: «он не записывает одновременно несколько
дорожек текста от разных людей».

Половину этого умеет anamorf/stt/turns.py: он режет кусок по СМЕНЕ тембра
и каждую реплику отдаёт своим текстом со своим говорящим. Но там, где
двое говорят ОДНОВРЕМЕННО, резать нечего — в каждой миллисекунде звучат
оба сразу. Отпечаток голоса на таком куске показывает химеру, движок
слышит кашу, и в ленте появляется один рваный текст вместо двух.

Единственный честный способ — РАЗДЕЛИТЬ ИСТОЧНИКИ: из одной моно-дорожки
получить две, по одной на голос. Этим занимаются сети класса SepFormer
(трансформер поверх обучаемого энкодера, обучен на смесях двух дикторов).
Берём вариант whamr16k: он учился на смесях С ШУМОМ И РЕВЕРБЕРАЦИЕЙ, то
есть ровно на том, что даёт комнатный микрофон, а не на стерильной
студии.

МЕСТО В КОНВЕЙЕРЕ И ЦЕНА. Вызывается ТОЛЬКО на кусках, где turns.py уже
поднял флаг crowd — то есть на редких секундах, а не в горячем цикле.
Каждая из двух дорожек уходит в GigaAM отдельно и получает свою метку
голоса (уже по чистому звуку — там отпечаток снова работает как надо).

ТРИ ПРЕДОХРАНИТЕЛЯ, потому что железо одно на всех:
  - модель грузится лениво, в фоне и ТОЛЬКО когда слух молчит (тот же
    урок, что и с компиляцией голоса: не занимать видеокарту посреди
    разговора);
  - если очередь распознавания уже отстаёт — разделение пропускается,
    целый текст сейчас важнее двух;
  - длинные куски не берём: цена растёт квадратично по вниманию.
"""
import logging
import threading
import time

import numpy as np

from anamorf.config import CFG, ROOT

log = logging.getLogger("saika.unmix")

SR = 16000
STATE = {"ready": False, "off": False, "err": "", "n": 0, "ms": 0.0}
_model = None
_lock = threading.Lock()
_loading = False


def enabled() -> bool:
    return bool(CFG.get("stt.unmix.enabled", True)) and not STATE["off"]


def _load():
    """Поднять SepFormer. Зовётся из фонового потока — не из горячего цикла."""
    global _model, _loading
    try:
        from anamorf.torch_gate import TORCH_GATE
        with TORCH_GATE:
            import torch
            from speechbrain.inference.separation import SepformerSeparation
            src = str(CFG.get("stt.unmix.model",
                              "speechbrain/sepformer-whamr16k"))
            dst = ROOT / "models" / "sepformer"
            dev = "cuda" if (CFG.get("stt.unmix.device", "cuda") == "cuda"
                             and torch.cuda.is_available()) else "cpu"
            _model = SepformerSeparation.from_hparams(
                source=src, savedir=str(dst), run_opts={"device": dev})
            STATE["ready"] = True
            log.info("Разделение голосов: SepFormer поднят на %s "
                     "(источник %s)", dev, src)
    except Exception as e:
        STATE["off"] = True
        STATE["err"] = str(e)[:200]
        log.warning("Разделение голосов не поднялось (%s) — наложенные "
                    "куски останутся одной дорожкой, это не смертельно", e)
    finally:
        _loading = False


def warm(idle_cb=None):
    """Попросить поднять модель. idle_cb() -> True, если слух сейчас занят:
    тогда ждём паузы, как и прогрев голоса."""
    global _loading
    if _model is not None or _loading or STATE["off"] or not enabled():
        return
    _loading = True

    def _bg():
        try:
            cap = float(CFG.get("stt.unmix.warm_wait_max_s", 600))
            t0 = time.time()
            while callable(idle_cb) and time.time() - t0 < cap:
                try:
                    if not idle_cb():
                        break
                except Exception:
                    break
                time.sleep(2.0)
        except Exception:
            pass
        _load()

    threading.Thread(target=_bg, daemon=True, name="unmix-warm").start()


def split(pcm16: np.ndarray, sr: int = SR):
    """Моно-смесь -> [дорожка1, дорожка2] в int16, или None.

    None значит «не разделяла» — по любой причине: модель не готова,
    кусок слишком длинный, разделение выключено. Вызывающий в этом случае
    работает как раньше, одной дорожкой."""
    if not enabled() or _model is None or not STATE["ready"]:
        return None
    n = len(pcm16)
    max_s = float(CFG.get("stt.unmix.max_s", 10.0))
    min_s = float(CFG.get("stt.unmix.min_s", 0.8))
    if n < sr * min_s or n > sr * max_s:
        return None
    t0 = time.monotonic()
    try:
        import torch
        x = np.asarray(pcm16, dtype=np.float32).ravel() / 32768.0
        peak = float(np.max(np.abs(x))) or 1.0
        x = x / peak                       # сеть училась на нормированном
        with _lock:
            with torch.no_grad():
                est = _model.separate_batch(torch.tensor(x)[None, :])
        est = est[0].detach().cpu().numpy()     # (сэмплы, источники)
        outs = []
        for k in range(min(2, est.shape[-1])):
            t = est[:, k]
            m = float(np.max(np.abs(t))) or 1.0
            t = (t / m) * peak
            outs.append(np.clip(t * 32768.0, -32768, 32767).astype(np.int16))
        # ПУСТУЮ ДОРОЖКУ ВЫБРАСЫВАЕМ. Сеть всегда возвращает ДВА выхода,
        # даже когда в смеси на самом деле один человек: второй тогда —
        # тихий мусор. Пускать его в движок значит гарантированно получить
        # выдуманную фразу (эту цену мы уже платили на фантомах клавиатуры).
        thr = float(CFG.get("stt.unmix.track_min_rms", 0.012))
        keep = [t for t in outs
                if float(np.sqrt(np.mean((t / 32768.0) ** 2))) >= thr]
        STATE["n"] += 1
        STATE["ms"] = round((time.monotonic() - t0) * 1000)
        if len(keep) < 2:
            return None
        log.info("Разделение голосов: наложение разведено на 2 дорожки "
                 "(%.1fс звука, %.0fмс)", n / sr, STATE["ms"])
        return keep
    except Exception as e:
        log.debug("разделение голосов споткнулось: %s", e)
        return None


def status() -> dict:
    return {"enabled": enabled(), "ready": bool(STATE["ready"]),
            "error": STATE["err"], "splits": STATE["n"],
            "last_ms": STATE["ms"]}
