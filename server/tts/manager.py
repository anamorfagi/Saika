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


# ─────────────── эмоция реплики (2026-07-26) ───────────────
# Метку тона сервер уже считает для жестов аватара (server/tone.py,
# _tone_cls в main.py). Раньше она влияла только на движение — теперь ещё
# и на голос. Формулировки короткие и в императиве: модели читают их как
# инструкцию, а не как описание.
_EMOTION = {"cls": None}
_EMO_TEXT = {
    "hostile": "Скажи это резко и холодно, с раздражением.",
    "vulgar":  "Скажи это грубовато и насмешливо.",
    "flirt":   "Скажи это мягко и игриво, с улыбкой в голосе.",
    "praise":  "Скажи это тепло и радостно.",
    "provoke": "Скажи это с иронией и вызовом.",
}


def set_emotion(cls):
    """Тон следующей реплики. Зовётся из main.py по tone.detect()."""
    _EMOTION["cls"] = cls or None


def _emotion_instruction():
    if not CFG.get("tts.emotion", True):
        return ""
    manual = str(CFG.get("tts.emotion_instruct", "") or "").strip()
    if manual:
        return manual
    return _EMO_TEXT.get(_EMOTION["cls"] or "", "")


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
                # 5500, не 4000: сама модель ~3.5-4 ГБ, но пик при загрузке
                # выше (буферы + KV) — с порогом 4000 проходили проверку и
                # умирали нативно уже внутри from_pretrained
                advice = _sc.vram_advice(5500)
            except Exception:
                advice = ""
            if advice:
                raise RuntimeError("Не хватает видеопамяти для клон-голоса: "
                                   + advice)
            # Отдельно — системная память: веса при загрузке проходят через
            # ОЗУ/коммит Windows. Если коммит забит (LM Studio + виспер +
            # браузер), процесс убивается БЕЗ трейсбека или падает с
            # os error 1455 «файл подкачки слишком мал». Ловим заранее.
            try:
                import psutil
                _avail_gb = psutil.virtual_memory().available / 1e9
            except Exception:
                _avail_gb = None
            if _avail_gb is not None and _avail_gb < 8:
                raise RuntimeError(
                    f"Мало свободной ОЗУ для загрузки клон-голоса "
                    f"({_avail_gb:.1f} ГБ, нужно ~8): закрой лишнее или "
                    f"увеличь файл подкачки Windows. Пока говорю запасным "
                    f"голосом.")
            # под общим замком тяжёлых загрузок: на старте ECAPA, Vosk и
            # этот движок поднимаются одновременно, и параллельный импорт
            # внутренностей torch роняет пришедшего вторым с «Duplicate
            # registration» (см. server/torch_gate.py; живой лог 2026-07-28 —
            # qwen3 падал с этой ошибкой два запуска подряд)
            from server.torch_gate import TORCH_GATE
            with TORCH_GATE:
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
        kw = dict(
            text=text,
            language=cfg.get("language", "Russian"),
            voice_clone_prompt=self.prompt,
            emit_every_frames=cfg.get("emit_every_frames", 4),
            decode_window_frames=cfg.get("decode_window_frames", 80),
            overlap_samples=0)
        # ЭМОЦИЯ (2026-07-26). У серии Qwen3-TTS есть чекпоинты VoiceDesign и
        # CustomVoice, где тембр и эмоция задаются инструкцией на естественном
        # языке. Но они НЕ клонируют голос по образцу — то есть переход на них
        # означал бы потерю собственного голоса Сайки. Поэтому пробуем передать
        # инструкцию прямо в клон-режим: если сборка её понимает — получаем и
        # свой голос, и эмоцию; если нет, TypeError ловится и всё работает
        # как раньше. Проверять руками не нужно, код разберётся сам.
        instr = _emotion_instruction()
        if instr:
            for key in ("instruct", "instruction", "emotion", "style"):
                try:
                    return self.model.stream_generate_voice_clone(
                        **kw, **{key: instr})
                except TypeError:
                    continue
                except Exception:
                    break        # сборка знает поле, но споткнулась — без него
        return self.model.stream_generate_voice_clone(**kw)

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

    # ⚠️ ЛИЦЕНЗИЯ (2026-07-26). Был speaker="v4_ru" — он под CC-BY-NC, то
    # есть коммерческое использование запрещено, а проект планируется
    # монетизировать. MIT только у v5_cis_base / v5_cis_base_nostress.
    # Поэтому дефолт сменён; старый пакет остаётся доступным через
    # tts.silero.model, если кому-то важно именно его звучание.
    DEFAULT_PACK = "v5_cis_base"

    def load(self):
        if self.model:
            return
        import torch
        cfg = CFG.get("tts.silero", {})
        pack = cfg.get("model", self.DEFAULT_PACK)
        # если запрошенного пакета нет (переименовали, не докачался) —
        # честно пробуем запасной, но НЕ уходим молча на NC-версию:
        # только на второй MIT-вариант
        for cand in (pack, "v5_cis_base_nostress"):
            try:
                self.model, _ = torch.hub.load(
                    "snakers4/silero-models", "silero_tts",
                    language="ru", speaker=cand, trust_repo=True)
                if cand != pack:
                    log.warning("Silero: пакет %s не поднялся, взяла %s",
                                pack, cand)
                self.pack = cand
                return
            except Exception as e:
                last = e
        raise RuntimeError(f"Silero не загрузился: {last}")

    def speak(self, text):
        self.load()
        cfg = CFG.get("tts.silero", {})
        sr = cfg.get("sample_rate", 48000)
        want = cfg.get("speaker", "")
        # У v5_cis_base набор дикторов ДРУГОЙ, чем у v4_ru (xenia там нет).
        # Не угадываем имена: спрашиваем модель и берём первого, если
        # настроенного диктора в пакете не оказалось.
        voices = list(getattr(self.model, "speakers", []) or [])
        spk = want if want in voices else (voices[0] if voices else want)
        if want and spk != want:
            log.info("Silero: диктора «%s» в пакете нет — говорю голосом "
                     "«%s» (есть: %s)", want, spk, ", ".join(voices[:8]))
            try:
                CFG.set("tts.silero.speaker", spk)   # чтобы не искать заново
            except Exception:
                pass
        audio = self.model.apply_tts(text=text, speaker=spk, sample_rate=sr)
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


class OffEngine:
    """БЕЗ ОЗВУЧКИ (2026-07-27, просьба владельца: быстрые тестовые пуски).

    Не движок, а осознанный выбор «молчать»: Qwen3-TTS компилируется под
    минуту и занимает несколько гигабайт VRAM — при отладке мозгов это
    просто налог. Сделан именно ПУНКТОМ СПИСКА, а не галочкой где-то в
    настройках, потому что выбирается он там же, где остальные голоса, и
    возвращается одним кликом.

    Пустой speak() тут только для полноты контракта: настоящее выключение
    живёт в TTSManager.speak — иначе цепочка фолбэка увидела бы «движок
    ничего не выдал» и заботливо озвучила следующим по списку."""
    name = "off"

    def load(self):
        pass

    def speak(self, text):
        return
        yield          # noqa — делает функцию генератором, как у остальных

    def unload(self):
        pass

    def is_loaded(self):
        return None    # нечего грузить — UI прячет кнопку загрузки


class TTSManager:
    def __init__(self, on_problem=None):
        self.engines = {"off": OffEngine(), "qwen3": Qwen3Engine(),
                        "silero": SileroEngine(), "edge": EdgeEngine()}
        # Доп. движки (2026-07-26): Piper (MIT, офлайн, CPU), XTTS-v2 и
        # F5-TTS-ru (клонирование). Подмешиваются отдельным модулем, чтобы
        # этот файл не разрастался и чтобы поломка нового движка не задела
        # три проверенных. Не поставились зависимости — движок просто не
        # появится в списке, озвучка работает как раньше.
        try:
            from server.tts import extra as _extra
            for _n, _cls in _extra.EXTRA_ENGINES.items():
                if _n in set(CFG.get("tts.hidden", [])):
                    continue
                try:
                    self.engines[_n] = _cls()
                except Exception as _e:
                    log.debug("движок %s не создался: %s", _n, _e)
            self.meta = dict(_extra.ENGINE_META)
        except Exception as _e:
            log.debug("доп. движки недоступны: %s", _e)
            self.meta = {}
        self.health = {n: "unknown" for n in self.engines}
        self.last_error = {}  # name -> человеческая причина последней ошибки (UI)
        self.last_diag = {}   # name -> полный разбор diagnostics.classify
        self.on_problem = on_problem
        self._last_space_report = 0.0  # троттлинг совета «мало памяти»

    def engine_meta(self, name=None):
        """Название, лицензия, умеет ли клонировать голос, примечание.
        Лицензия тут не формальность: у Silero она запрещает коммерческое
        использование, и владелец должен видеть это ДО того, как построит
        на нём билд на продажу."""
        m = getattr(self, "meta", {}) or {}
        if name:
            return m.get(name, {})
        return {n: m.get(n, {}) for n in self.engines}

    def voices(self):
        """Каталог голосов по движкам — для отдельной вкладки в интерфейсе."""
        try:
            from server.tts import extra as _extra
            return _extra.voices_catalog(self.engines)
        except Exception as e:
            log.debug("каталог голосов недоступен: %s", e)
            return {}

    def set_voice(self, engine, voice):
        from server.tts import extra as _extra
        return _extra.set_voice(engine, voice)

    def preview(self, engine, text=None):
        """Синтез короткой фразы выбранным движком — «послушать» в интерфейсе.
        Возвращает (float32-байты, частота). Ошибки НЕ глушим: человек нажал
        кнопку и должен увидеть причину, а не тишину."""
        name = engine or self.current_name
        eng = self.engines.get(name)
        if eng is None:
            raise ValueError(f"нет движка {name}")
        phrase = (text or CFG.get("tts.preview_text")
                  or "Привет. Это мой голос — как тебе?")
        chunks, sr = [], 24000
        for pcm, rate in eng.speak(phrase):
            chunks.append(pcm)
            sr = rate
        return b"".join(chunks), sr

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

    # голос-времянка на время загрузки тяжёлого движка (быстрый старт
    # 2026-07-23): пока qwen3 компилируется ~60с, отвечает лёгкий silero/
    # edge. Выставляется/снимается ТОЛЬКО автопуском, конфиг не трогает —
    # выбор владельца не перезаписывается, и при падении на середине
    # загрузки конфиг не остаётся замусоренным времянкой.
    boot_override = None

    @property
    def current_name(self):
        return self.boot_override or CFG.get("tts.engine", "qwen3")

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
        # запасные: сначала ЛЮБИМЫЕ (tts.favorites — вкус владельца важнее
        # секундомера), внутри — по замеренной скорости на этом ПК
        # «off» не запасной вариант: свалиться в тишину при поломке движка
        # — это не фолбэк, а молчание без объяснений
        backups = [n for n in order if n != current and n != "off"]
        try:
            from server import ratings
            scores = ratings.tts_scores()
            backups.sort(key=lambda n: -scores.get(n, 0))
            favs = [f for f in CFG.get("tts.favorites", []) if f in backups]
            backups.sort(key=lambda n: favs.index(n) if n in favs
                         else len(favs) + 1)
        except Exception:
            pass
        chain = [current] + backups
        return [n for n in chain
                if self.health.get(n) != "broken" and n not in disabled]

    def speak(self, text):
        """Генератор (pcm_f32_bytes, sample_rate). Сам падает на фоллбэк."""
        if not CFG.get("tts.enabled", True):
            return
        # «без озвучки» — выбор, а не поломка: выходим ДО цепочки фолбэка,
        # иначе она увидит движок, не выдавший ни одного чанка, и озвучит
        # следующим по списку (ровно то, от чего человек и отказался)
        if self.current_name == "off":
            return
        for name in self._chain():
            engine = self.engines[name]
            try:
                yielded = False
                t0 = time.time()
                audio_s = 0.0
                for item in engine.speak(text):
                    yielded = True
                    try:  # секунды синтезированного аудио (float32 → /4)
                        pcm, sr = item
                        audio_s += (len(pcm) // 4) / float(sr)
                    except Exception:
                        pass
                    yield item
                self.health[name] = "ok"
                if yielded:
                    # рейтинг голоса: скорость синтеза на ЭТОМ железе
                    wall = time.time() - t0
                    if wall > 0.05 and audio_s > 0.2:
                        try:
                            from server import ratings
                            ratings.record_tts(name, audio_s / wall)
                        except Exception:
                            pass
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

    def benchmark_missing(self):
        """Разовый бенч незамеренных запасных голосов: синтезируем короткую
        фразу, пишем скорость в рейтинг. Без этого у нового движка нет
        оценки, и выбор «по рейтингу» слеп (edge мог быть лучшим, но с нулём
        замеров никогда не выигрывал). qwen3 не бенчим — он меряется при
        реальном использовании, чтобы зря не занимать VRAM."""
        try:
            from server import ratings
            have = ratings.tts_scores()
        except Exception:
            return
        for name in CFG.get("tts.fallback_order", []):
            if name == "qwen3" or have.get(name):
                continue
            engine = self.engines.get(name)
            if not engine or name in set(CFG.get("tts.disabled", [])):
                continue
            try:
                t0 = time.time()
                audio_s = 0.0
                for pcm, sr in engine.speak("Проверка скорости голоса."):
                    audio_s += (len(pcm) // 4) / float(sr)
                wall = time.time() - t0
                if wall > 0 and audio_s > 0:
                    ratings.record_tts(name, audio_s / wall)
                    log.info("Бенч голоса %s: %.2fx реального времени",
                             name, audio_s / wall)
            except Exception as e:
                log.info("Бенч голоса %s не удался: %s", name, e)

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
                "errors": self.last_error, "diag": self.last_diag,
                # meta (2026-07-26): название, лицензия, умеет ли клонировать.
                # Едет вместе со статусом, чтобы интерфейсу не нужен был
                # второй запрос на каждое открытие меню голоса.
                "meta": self.engine_meta()}
