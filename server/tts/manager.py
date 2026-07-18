"""TTS-менеджер. Приоритет: Qwen3-TTS-streaming (клон голоса Сайки).

Фоллбэки: Silero (локальный, CPU) → edge-tts (онлайн).
Выход всегда: генератор (pcm_float32_bytes, sample_rate).
"""
import asyncio
import io
import logging
import re
import threading
import time

import numpy as np

from server.config import CFG, resolve
from server import diagnostics

log = logging.getLogger("saika.tts")

SENTENCE_RE = re.compile(r"[^.!?…]+[.!?…]+|\s*[^.!?…]+$")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_RE.findall(text) if s.strip()]


class Qwen3Engine:
    name = "qwen3"

    def __init__(self):
        self.model = None
        self.prompt = None
        self.lock = threading.Lock()        # сериализация синтеза
        self.load_lock = threading.Lock()   # одна загрузка за раз

    def load(self):
        # Под замком: без него два потока (диалог + фоновая починка) грузят
        # модель параллельно, и один успевает заговорить до готовности
        # клон-промпта -> «Either voice_clone_prompt or ref_audio must be
        # provided». self.model/prompt публикуются только целиком, в конце.
        with self.load_lock:
            if self.model is not None and self.prompt is not None:
                return
            # Единственная защита, что осталась: не грузим, если VRAM реально
            # нет (иначе нативный краш 0xC0000005). Порог ~4 ГБ ≈ сколько
            # берёт модель; хватает памяти — грузимся как обычно, на плавность
            # это не влияет. Мало — уходим на silero, а не роняем процесс.
            try:
                from server import system_control as _sc
                advice = _sc.vram_advice(4000)
            except Exception:
                advice = ""
            if advice:
                raise RuntimeError("Не хватает видеопамяти для клон-голоса: "
                                   + advice)
            import torch
            from qwen_tts import Qwen3TTSModel

            cfg = CFG.get("tts.qwen3", {})
            attn = cfg.get("attn", "auto")
            kwargs = dict(device_map="cuda:0", dtype=torch.bfloat16)
            tried = ["flash_attention_2", "sdpa"] if attn == "auto" else [attn]

            model_id = cfg.get("model", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")
            # Модель уже в кэше? Грузим по локальному пути — вообще без сети.
            # Иначе флаки-DNS до huggingface.co кладёт загрузку ретраями.
            model_src = model_id
            try:
                from huggingface_hub import snapshot_download
                model_src = snapshot_download(model_id, local_files_only=True)
                log.info("Qwen3-TTS: беру из локального кэша (%s)", model_src)
            except Exception:
                log.info("Qwen3-TTS: в кэше нет — качаю с HF (%s)", model_id)

            model, last = None, None
            for impl in tried:
                try:
                    model = Qwen3TTSModel.from_pretrained(
                        model_src, attn_implementation=impl, **kwargs)
                    log.info("Qwen3-TTS загружен (attn=%s)", impl)
                    break
                except Exception as e:
                    last = e
                    model = None
            if not model:
                raise RuntimeError(f"Qwen3-TTS не загрузился: {last}")

            ref_wav = resolve(CFG.get("tts.voice_ref_wav"))
            ref_text = CFG.get("tts.voice_ref_text", "")
            if not ref_wav.exists() or not ref_text:
                raise RuntimeError(
                    "Нет референса голоса (voice_ref_wav / voice_ref_text). "
                    "Запусти setup/first_run.py — он подготовит и расшифрует голос.")
            prompt = model.create_voice_clone_prompt(
                ref_audio=str(ref_wav), ref_text=ref_text)

            # публикуем только полностью готовую пару
            self.model, self.prompt = model, prompt

            if cfg.get("optimize", True):
                try:
                    torch.set_float32_matmul_precision("high")
                    self.model.enable_streaming_optimizations(
                        decode_window_frames=cfg.get("decode_window_frames", 80),
                        use_compile=True, use_cuda_graphs=False,
                        compile_mode="reduce-overhead",
                        use_fast_codebook=True,
                        compile_codebook_predictor=True, compile_talker=True)
                    # прогрев компиляции — под замком синтеза, чтобы
                    # параллельный speak не влез в середину
                    with self.lock:
                        for warm in ("Прогрев номер один.", "Прогрев номер два."):
                            for _ in self._stream(warm):
                                pass
                except Exception as e:
                    log.warning("Оптимизации Qwen3-TTS не включились: %s", e)

    def _stream(self, text):
        cfg = CFG.get("tts.qwen3", {})
        return self.model.stream_generate_voice_clone(
            text=text,
            language=cfg.get("language", "Russian"),
            voice_clone_prompt=self.prompt,
            emit_every_frames=cfg.get("emit_every_frames", 4),
            decode_window_frames=cfg.get("decode_window_frames", 80),
            overlap_samples=0)

    def speak(self, text):
        self.load()
        with self.lock:
            for chunk, sr in self._stream(text):
                yield np.asarray(chunk, dtype=np.float32).tobytes(), sr

    def unload(self):
        with self.load_lock:
            self.model = None
            self.prompt = None

    def is_loaded(self):
        return self.model is not None and self.prompt is not None


class SileroEngine:
    name = "silero"

    def __init__(self):
        self.model = None

    def load(self):
        if self.model:
            return
        import torch

        self.model, _ = torch.hub.load(
            "snakers4/silero-models", "silero_tts",
            language="ru", speaker="v4_ru", trust_repo=True)

    def speak(self, text):
        self.load()
        cfg = CFG.get("tts.silero", {})
        sr = cfg.get("sample_rate", 48000)
        audio = self.model.apply_tts(
            text=text, speaker=cfg.get("speaker", "xenia"), sample_rate=sr)
        yield audio.numpy().astype(np.float32).tobytes(), sr

    def unload(self):
        self.model = None

    def is_loaded(self):
        return self.model is not None


class EdgeEngine:
    name = "edge"

    def load(self):
        import edge_tts  # noqa: F401 — просто проверка что установлен

    def speak(self, text):
        import edge_tts
        import soundfile as sf

        async def synth():
            voice = CFG.get("tts.edge.voice", "ru-RU-SvetlanaNeural")
            comm = edge_tts.Communicate(text, voice)
            buf = io.BytesIO()
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            buf.seek(0)
            return buf

        buf = asyncio.run(synth())
        data, sr = sf.read(buf, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        yield data.tobytes(), sr

    def unload(self):
        pass

    def is_loaded(self):
        return None  # онлайн-сервис, модели в памяти нет — UI прячет кнопку


class TTSManager:
    def __init__(self, on_problem=None):
        self.engines = {"qwen3": Qwen3Engine(), "silero": SileroEngine(),
                        "edge": EdgeEngine()}
        self.health = {n: "unknown" for n in self.engines}
        self.last_error = {}  # name -> человеческая причина последней ошибки (UI)
        self.last_diag = {}   # name -> полный разбор diagnostics.classify
        self.on_problem = on_problem
        self._last_space_report = 0.0  # троттлинг совета «мало памяти»

    # ---------- ручная загрузка/выгрузка (кнопки в UI) ----------
    def load_engine(self, name):
        if name not in self.engines:
            raise ValueError(f"Нет такого движка: {name}")
        # отключённый движок (qwen3, роняющий процесс) руками грузить нельзя —
        # иначе нативный краш убьёт сервер
        if name in set(CFG.get("tts.disabled", [])):
            raise RuntimeError(
                f"{name} отключён (нативно роняет процесс на этом ПК). "
                "Убери его из tts.disabled в config.json, если хочешь пробовать.")
        try:
            self.engines[name].load()
            self.health[name] = "ok"
            self.last_error.pop(name, None)
            self.last_diag.pop(name, None)
        except Exception as e:
            self.health[name] = "broken"
            diag = diagnostics.classify("tts." + name, str(e))
            self.last_error[name] = diag["human"]
            self.last_diag[name] = diag
            if self.on_problem:
                self.on_problem("tts." + name, diag["human"], diag["action"], diag)
            raise

    def unload_engine(self, name):
        engine = self.engines.get(name)
        if engine:
            engine.unload()
        self.last_error.pop(name, None)
        if self.health.get(name) == "broken":
            self.health[name] = "unknown"

    @property
    def current_name(self):
        return CFG.get("tts.engine", "qwen3")

    def set_engine(self, name):
        if name not in self.engines:
            raise ValueError(name)
        CFG.set("tts.engine", name)

    def _chain(self):
        order = CFG.get("tts.fallback_order", list(self.engines))
        # движки из tts.disabled НЕ трогаем совсем (напр. qwen3, который
        # нативно роняет процесс на этом ПК) — иначе фоллбэк в него = краш
        disabled = set(CFG.get("tts.disabled", []))
        current = self.current_name
        chain = [current] + [n for n in order if n != current]
        return [n for n in chain
                if self.health.get(n) != "broken" and n not in disabled]

    def speak(self, text):
        """Генератор (pcm_f32_bytes, sample_rate). Сам падает на фоллбэк."""
        if not CFG.get("tts.enabled", True):
            return
        for name in self._chain():
            engine = self.engines[name]
            try:
                yielded = False
                for item in engine.speak(text):
                    yielded = True
                    yield item
                self.health[name] = "ok"
                if yielded:
                    return
            except Exception as e:
                diag = diagnostics.classify("tts." + name, str(e))
                self.last_error[name] = diag["human"]
                self.last_diag[name] = diag
                log.error("TTS %s сломался [%s]: %s", name, diag["category"], e)
                # Нехватка памяти — это ВРЕМЕННО. НЕ помечаем движок сломанным:
                # на следующей фразе снова пробуем клон-голос и сами вернёмся к
                # нему, как только VRAM освободится. Совет «закрой лишнее» шлём
                # не чаще раза в минуту, чтобы не спамить.
                if diag["category"] == "space":
                    now = time.time()
                    if self.on_problem and now - self._last_space_report > 60:
                        self._last_space_report = now
                        self.on_problem("tts." + name, diag["human"],
                                        diag["action"], diag)
                    continue  # тихо переходим на запасной голос для этой фразы
                self.health[name] = "broken"
                if self.on_problem:
                    self.on_problem("tts." + name, diag["human"], diag["action"], diag)
                threading.Thread(target=self._repair, args=(name, diag),
                                 daemon=True).start()
        log.error("Все TTS-движки недоступны")

    def _repair(self, name, diag=None):
        # сеть/память/офлайн перезагрузкой не лечатся — не долбим впустую
        cat = (diag or {}).get("category", "unknown")
        if cat in ("network", "space", "offline"):
            log.info("TTS %s: причина '%s' — жду условий, не переустанавливаю",
                     name, cat)
            return
        try:
            engine = self.engines[name]
            engine.unload()
            engine.load()
            self.health[name] = "ok"
            self.last_error.pop(name, None)
            self.last_diag.pop(name, None)
            if self.on_problem:
                self.on_problem("tts." + name, "", "движок восстановлен")
        except Exception as e:
            d = diagnostics.classify("tts." + name, str(e))
            self.last_error[name] = d["human"]
            log.warning("TTS %s: починка не удалась (%s)", name, e)

    def status(self):
        loaded = {}
        for name, eng in self.engines.items():
            try:
                loaded[name] = eng.is_loaded() if hasattr(eng, "is_loaded") \
                    else None
            except Exception:
                loaded[name] = False
        return {"current": self.current_name, "health": self.health,
                "engines": list(self.engines), "loaded": loaded,
                "errors": self.last_error, "diag": self.last_diag}
