"""Дополнительные движки озвучки (2026-07-26).

ЗАЧЕМ ИМЕННО ЭТИ.

⚠️ Главное, что выяснилось при разборе: **лицензия Silero разрешает только
образовательное использование**, а он у нас основной запасной движок. Для
проекта, который планируется монетизировать (Сайка-соведущая), это мина:
работает — а использовать нельзя. Поэтому первым делом появился Piper.

**Piper** — MIT, ONNX, работает на CPU за десятки миллисекунд, четыре
русских голоса (denis, dmitri, irina, ruslan). Не клонирует голос, зато
никогда не отвалится: ни VRAM, ни сети, ни лицензионных вопросов у самого
кода. Идеальный запасной — то, чем Silero быть не может.

**XTTS-v2** — клонирование голоса, мультиязычный. ⚠️ веса под Coqui Public
Model License, она НЕКОММЕРЧЕСКАЯ. Даём попробовать, но в интерфейсе честно
помечаем: в билд на продажу такое не поедет.

**F5-TTS (русский дообуч)** — `Misha24-10/F5-TTS_RUSSIAN`, клонирование с
правильным русским произношением, ~2 с на GPU. Ставится отдельным
окружением: его зависимости конфликтуют с Qwen3-TTS так же, как у Voxtral
со слухом — тот же приём, что уже проверен в проекте.

⚠️ ПОЧЕМУ XTTS И F5 ПО УМОЛЧАНИЮ СПРЯТАНЫ (tts.hidden в config).
`coqui-tts` и `F5-TTS` пиннут старые transformers и numpy<2. В ОБЩЕМ venv они
сломают Qwen3-TTS — это ровно та грабля, из-за которой Voxtral живёт в
`.venv_voxtral` отдельно от слуха. Поэтому классы здесь есть и готовы, но в
список попадут только после того, как появится своё окружение и воркер.
Прямо сейчас реально работает **Piper**: он на onnxruntime, ничего не пиннет
и ставится за секунды.

Контракт движка тот же, что у остальных (см. anamorf/tts/manager.py):
`name`, `load()`, `speak(text)` -> генератор (pcm_float32_bytes, sample_rate),
`unload()`, `is_loaded()`. Плюс метаданные `license` / `voice_clone` —
менеджер отдаёт их в интерфейс.
"""
import io
import logging
import pathlib
import threading

import numpy as np

from anamorf.config import CFG, resolve

log = logging.getLogger("saika.tts.extra")

# Голоса Piper для русского. Все medium — x_low/high для ru не выложены.
PIPER_VOICES = {
    "irina":  "Ирина — женский, спокойный",
    "denis":  "Денис — мужской",
    "dmitri": "Дмитрий — мужской, ниже",
    "ruslan": "Руслан — мужской, дикторский",
}
PIPER_REPO = "rhasspy/piper-voices"


class PiperEngine:
    """MIT, ONNX, CPU. Самый надёжный запасной: ни VRAM, ни сети, ни
    лицензионных вопросов к коду."""

    name = "piper"
    license = "MIT (код). Голоса — своя лицензия у каждого, см. MODEL_CARD"
    voice_clone = False
    note = ("Быстрый офлайн-движок на CPU. Не клонирует голос Сайки, зато "
            "не отваливается никогда — держи его последним в цепочке "
            "фоллбэка вместо Silero.")

    def __init__(self):
        self.voice = None
        self.loaded_name = None
        self.load_lock = threading.Lock()

    # ── файлы голоса ──
    def _voice_files(self, name):
        """Скачать .onnx и .onnx.json голоса, вернуть пути. Кладём в
        models/piper — там же, где остальные модели проекта."""
        from huggingface_hub import hf_hub_download
        base = f"ru/ru_RU/{name}/medium/ru_RU-{name}-medium"
        local = resolve("models/piper")
        local.mkdir(parents=True, exist_ok=True)
        onnx = hf_hub_download(PIPER_REPO, base + ".onnx",
                               local_dir=str(local))
        cfg = hf_hub_download(PIPER_REPO, base + ".onnx.json",
                              local_dir=str(local))
        return onnx, cfg

    def load(self):
        # Голос может быть задан двумя способами: коротким именем из нашего
        # русского списка («irina») или полным ключом из индекса Piper
        # («ru_RU-irina-medium»), который приходит из витрины голосов.
        want = str(CFG.get("tts.piper.voice", "irina")).strip()
        if want not in PIPER_VOICES and "-" in want:
            return self._load_by_key(want)
        want = want.lower()
        if want not in PIPER_VOICES:
            want = "irina"
        with self.load_lock:
            if self.voice is not None and self.loaded_name == want:
                return
            try:
                from piper import PiperVoice
            except ImportError:
                raise RuntimeError(
                    "piper-tts не установлен. Запусти "
                    "setup\\ensure_features.py piper --force (или он "
                    "поставится сам при следующем старте).")
            onnx, cfg = self._voice_files(want)
            self.voice = PiperVoice.load(onnx, config_path=cfg)
            self.loaded_name = want
            log.info("Piper: голос %s готов", want)

    def _load_by_key(self, key):
        """Голос по полному ключу из индекса (ru_RU-irina-medium и т.п.)."""
        from huggingface_hub import hf_hub_download
        with self.load_lock:
            if self.voice is not None and self.loaded_name == key:
                return
            try:
                from piper import PiperVoice
            except ImportError:
                raise RuntimeError(
                    "piper-tts не установлен. Запусти "
                    "setup\\ensure_features.py piper --force")
            idx = _piper_index()
            entry = idx.get(key) or {}
            files = [f for f in (entry.get("files") or {})
                     if f.endswith(".onnx") or f.endswith(".onnx.json")]
            if not files:
                raise RuntimeError(f"голос {key} не найден в индексе Piper")
            local = _piper_dir()
            local.mkdir(parents=True, exist_ok=True)
            paths = {}
            for f in files:
                paths[f] = hf_hub_download(PIPER_REPO, f,
                                           local_dir=str(local))
            onnx = next(p for f, p in paths.items() if f.endswith(".onnx"))
            cfg = next((p for f, p in paths.items()
                        if f.endswith(".onnx.json")), None)
            self.voice = PiperVoice.load(onnx, config_path=cfg)
            self.loaded_name = key
            log.info("Piper: голос %s готов", key)

    def speak(self, text):
        self.load()
        v = self.voice
        # API piper-tts менялось: в новых версиях synthesize() отдаёт объекты
        # AudioChunk, в старых был synthesize_stream_raw() с сырым int16.
        # Поддерживаем оба — иначе обновление пакета молча ломает озвучку.
        sr = None
        try:
            sr = int(v.config.sample_rate)
        except Exception:
            pass
        if hasattr(v, "synthesize"):
            got = False
            for chunk in v.synthesize(text):
                raw = getattr(chunk, "audio_int16_bytes", None)
                if raw is None:
                    raw = getattr(chunk, "audio_int16_array", None)
                    if raw is not None:
                        raw = np.asarray(raw, dtype=np.int16).tobytes()
                if raw is None:                     # совсем другой формат
                    break
                rate = int(getattr(chunk, "sample_rate", sr or 22050))
                got = True
                yield self._to_float(raw), rate
            if got:
                return
        # старый путь
        for raw in v.synthesize_stream_raw(text):
            yield self._to_float(raw), int(sr or 22050)

    @staticmethod
    def _to_float(raw_int16: bytes) -> bytes:
        """int16 -> float32: остальной конвейер проекта работает во float."""
        a = np.frombuffer(raw_int16, dtype=np.int16).astype(np.float32) / 32768.0
        return a.tobytes()

    def unload(self):
        self.voice = None
        self.loaded_name = None

    def is_loaded(self):
        return self.voice is not None


class XttsEngine:
    """Клонирование голоса, мультиязычный. ⚠️ веса под НЕКОММЕРЧЕСКОЙ
    лицензией Coqui — попробовать можно, продавать нельзя."""

    name = "xtts"
    license = "⚠️ Coqui Public Model License — НЕкоммерческая"
    voice_clone = True
    note = ("Клонирует голос по образцу voice/ref.wav, знает русский. Но "
            "веса нельзя использовать в коммерческом продукте — для билда "
            "на продажу не подойдёт, только поиграться.")

    def __init__(self):
        self.tts = None
        self.load_lock = threading.Lock()

    def load(self):
        with self.load_lock:
            if self.tts is not None:
                return
            try:
                from TTS.api import TTS
            except ImportError:
                raise RuntimeError(
                    "coqui-tts не установлен. Ставится отдельно: "
                    "setup\\ensure_features.py xtts --force")
            # VRAM: XTTS-v2 берёт ~2.5 ГБ. Проверяем, как это делает Qwen3 —
            # чтобы вместо нативного краша уйти на следующий движок.
            try:
                from anamorf import system_control as _sc
                advice = _sc.vram_advice(3000)
                if advice:
                    raise RuntimeError("Не хватает видеопамяти для XTTS: "
                                       + advice)
            except ImportError:
                pass
            import torch
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            self.tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2"
                           ).to(dev)
            log.info("XTTS-v2 готов (%s)", dev)

    def _ref(self):
        p = resolve(CFG.get("tts.voice_ref_wav", "voice/ref.wav"))
        if not p.exists():
            p = resolve(CFG.get("tts.voice_ref", "voice/ref.mp3"))
        if not p.exists():
            raise RuntimeError("нет образца голоса (voice/ref.wav) — "
                               "клонировать нечего")
        return str(p)

    def speak(self, text):
        self.load()
        wav = self.tts.tts(text=text, speaker_wav=self._ref(),
                           language=CFG.get("tts.xtts.language", "ru"))
        a = np.asarray(wav, dtype=np.float32)
        yield a.tobytes(), int(CFG.get("tts.xtts.sample_rate", 24000))

    def unload(self):
        self.tts = None
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass

    def is_loaded(self):
        return self.tts is not None


class F5RuEngine:
    """F5-TTS, дообученный на русском (Misha24-10/F5-TTS_RUSSIAN).
    Живёт в своём окружении — его зависимости конфликтуют с Qwen3-TTS так
    же, как у Voxtral со слухом. Общается по HTTP, как остальные воркеры."""

    name = "f5ru"
    license = "код MIT, веса — проверь карточку модели перед продажей"
    voice_clone = True
    note = ("Клонирование с правильным русским произношением, ~2 с на GPU. "
            "Отдельное окружение .venv_f5 — ставится по кнопке, как Voxtral.")

    def __init__(self):
        self.ready = False

    def _port(self):
        return int(CFG.get("tts.f5ru.port", 8771))

    def load(self):
        import requests
        url = f"http://127.0.0.1:{self._port()}/health"
        try:
            r = requests.get(url, timeout=3)
            r.raise_for_status()
            self.ready = True
            return
        except Exception:
            pass
        # воркера нет — поднимаем тем же спавнером, что и остальные
        try:
            from anamorf.llm import locallm  # noqa: F401  (общий паттерн)
        except Exception:
            pass
        raise RuntimeError(
            "Воркер F5-TTS не запущен. Установка: "
            "setup\\install_f5.bat (заведёт .venv_f5 и скачает веса). "
            "Пока его нет — озвучка идёт другим движком.")

    def speak(self, text):
        import requests
        import soundfile as sf
        self.load()
        r = requests.post(f"http://127.0.0.1:{self._port()}/tts",
                          json={"text": text,
                                "ref": str(resolve(CFG.get(
                                    "tts.voice_ref_wav", "voice/ref.wav")))},
                          timeout=120)
        r.raise_for_status()
        data, sr = sf.read(io.BytesIO(r.content), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        yield data.tobytes(), int(sr)

    def unload(self):
        self.ready = False

    def is_loaded(self):
        return self.ready or None


class OmniVoiceEngine:
    """OmniVoice (k2-fsa): клон голоса, 646 языков, **Apache-2.0**.

    Главный аргумент — лицензия. Из всего, что умеет клонировать голос, это
    единственный вариант без ограничений на коммерческое использование:
    у XTTS-v2 веса под некоммерческой Coqui CPML, у Silero лицензия только
    образовательная. Для проекта, который планируется монетизировать, выбор
    очевиден.

    Русский в обучении представлен всерьёз — 20 338 часов, один из
    крупнейших языков набора. RTF 0.025 на GPU (в 40 раз быстрее реального
    времени), 0.6B параметров.

    Живёт в своём окружении (.venv_omni) и общается по HTTP — тот же приём,
    что у Voxtral: OmniVoice тестирован на torch 2.8, а у нас cu130, в общем
    venv они не уживутся.
    """

    name = "omni"
    license = "Apache-2.0 — можно и в коммерческом продукте"
    voice_clone = True
    note = ("Клонирует голос по voice/ref.wav + расшифровке из "
            "tts.voice_ref_text (она у нас уже есть). 646 языков, русский — "
            "20 338 часов в обучении. Единственный клон-движок с "
            "разрешительной лицензией. Требует своего окружения: "
            "setup\\install_omnivoice.bat")

    _setup_started = False

    def __init__(self):
        self.proc = None
        self._spawn_log = resolve("logs/omnivoice_spawn.log")

    @property
    def cfg(self):
        return CFG.get("tts.omni", {}) or {}

    def _url(self, path):
        return f"http://127.0.0.1:{self.cfg.get('port', 8772)}{path}"

    def _health(self):
        import requests
        try:
            r = requests.get(self._url("/health"), timeout=2)
            return r.json() if r.ok else None
        except Exception:
            return None

    def _venv_python(self):
        import os
        venv = resolve(self.cfg.get("venv", ".venv_omni"))
        return (venv / "Scripts" / "python.exe" if os.name == "nt"
                else venv / "bin" / "python")

    def load(self):
        import os
        import subprocess
        import time
        h = self._health()
        if h is not None:
            # ЖИВОЙ ВОРКЕР != РАБОЧИЙ ДВИЖОК (2026-08-15). Порт
            # отвечает, значит «загружено» — так это выглядело, пока
            # внутри лежал мёртвый импорт. Спрашиваем ещё и модель.
            if h.get("error"):
                raise RuntimeError(_omni_cure(str(h["error"])))
            return                      # воркер уже поднят (наш или прошлый)

        venv_py = self._venv_python()
        if not venv_py.exists():
            setup = resolve(self.cfg.get("setup", "setup/install_omnivoice.bat"))
            if os.name == "nt" and setup.exists() and not type(self)._setup_started:
                # окно установки открываем ОДИН раз, сами честно падаем:
                # менеджер уведёт озвучку на следующий движок и напишет
                # причину в интерфейс, а не будет молча ждать
                type(self)._setup_started = True
                subprocess.Popen(["cmd", "/c", "start",
                                  "Установка OmniVoice", str(setup)])
                raise RuntimeError(
                    "OmniVoice: окружения ещё нет — открыл окно установки. "
                    "Когда закончится, выбери движок заново.")
            raise RuntimeError(
                "OmniVoice: нет окружения .venv_omni — запусти "
                "setup\\install_omnivoice.bat")

        worker = resolve(self.cfg.get("worker", "workers/omnivoice_worker.py"))
        cmd = [str(venv_py), str(worker),
               "--port", str(self.cfg.get("port", 8772)),
               "--model", self.cfg.get("model", "k2-fsa/OmniVoice")]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log.info("OmniVoice: запускаю воркер: %s", " ".join(cmd))
        # ВЫВОД ПЕРЕХВАТЫВАЕМ (2026-07-26, поймано на живом запуске). Без
        # перенаправления stdout/stderr падение воркера ДО того, как он
        # настроит своё логирование (битый импорт, отсутствующая DLL), не
        # оставляет ни строчки: файла logs/omnivoice_worker.log просто нет,
        # а в UI видно только «упал с незнакомой ошибкой». Пишем в отдельный
        # spawn-лог — там видно самую раннюю ошибку.
        spawn_log = resolve("logs/omnivoice_spawn.log")
        spawn_log.parent.mkdir(parents=True, exist_ok=True)
        self._spawn_log = spawn_log
        fh = open(spawn_log, "wb")
        self.proc = subprocess.Popen(cmd, cwd=str(resolve(".")),
                                     creationflags=flags,
                                     stdout=fh, stderr=subprocess.STDOUT)
        deadline = time.time() + 60
        while time.time() < deadline:
            if self._health() is not None:
                return
            if self.proc.poll() is not None:
                if self._health() is not None:
                    # порт держит живой воркер (гонка перезапуска) — усыновляем
                    self.proc = None
                    return
                raise RuntimeError(
                    f"OmniVoice: воркер упал при старте "
                    f"(код {self.proc.returncode}). {self._tail()}")
            time.sleep(1)
        raise RuntimeError("OmniVoice: воркер не ответил за 60 с")

    def speak(self, text):
        import requests
        import soundfile as sf
        self.load()
        ref = resolve(CFG.get("tts.voice_ref_wav", "voice/ref.wav"))
        body = {"text": text,
                "ref": str(ref) if ref.exists() else "",
                # расшифровка образца обязательна для клонирования — она у
                # нас уже лежит в конфиге для Qwen3-TTS, переиспользуем
                "ref_text": CFG.get("tts.voice_ref_text", ""),
                "lang": self.cfg.get("language", "ru"),
                "steps": self.cfg.get("steps", 16)}
        r = requests.post(self._url("/tts"), json=body,
                          timeout=self.cfg.get("timeout_s", 120))
        r.raise_for_status()
        if r.headers.get("content-type", "").startswith("application/json"):
            j = r.json()
            # ОШИБКА ГЛАВНЕЕ ФЛАГА ЗАГРУЗКИ: пока проверяли loading
            # первым, настоящая причина («не собрался импорт») год
            # молчала под вывеской «ещё греется» (2026-08-15).
            if j.get("error"):
                raise RuntimeError(_omni_cure(str(j["error"])))
            if j.get("loading"):
                raise RuntimeError("OmniVoice ещё грузит модель — "
                                   "озвучиваю другим движком")
            raise RuntimeError("OmniVoice не отдал звук")
        data, sr = sf.read(io.BytesIO(r.content), dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        yield data.tobytes(), int(sr)

    def _tail(self, n=6):
        """Последние строки spawn-лога — то, что реально сказал воркер.
        Без этого в интерфейс уходил только код возврата, по которому
        починить нельзя ничего."""
        try:
            txt = self._spawn_log.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ("Лога нет — воркер не успел ничего сказать. Проверь "
                    "logs/omnivoice_spawn.log и logs/omnivoice_worker.log")
        lines = [x.strip() for x in txt.strip().splitlines() if x.strip()]
        if not lines:
            return "Лог пуст, см. logs/omnivoice_spawn.log"
        return "Сказал: " + " | ".join(lines[-n:])[:400]

    def unload(self):
        import requests
        try:
            requests.post(self._url("/admin/unload"), timeout=5)
        except Exception:
            pass

    def is_loaded(self):
        h = self._health()
        return bool(h and h.get("model_loaded")) if h else False


def _omni_cure(err: str) -> str:
    """Перевод ошибки воркера на язык, по которому можно чинить.

    Живой случай (13.08.2026, полтора дня «ещё греется»):
    ImportError: cannot import name 'HiggsAudioV2TokenizerModel' from
    'transformers' (C:\\AI\\Saika\\.venv\\Lib\\site-packages\\...).
    Путь в скобках — ОСНОВНОЙ .venv: окружение omni одалживает у него
    тяжёлые пакеты через main_env.pth, и transformers оттуда старее, чем
    нужно omnivoice. Лечится установкой своего transformers внутрь
    .venv_omni — основной venv при этом не трогается (там на нём живут
    Qwen3-TTS, GigaAM и Voxtral, ломать их нельзя).
    """
    e = err or ""
    if "HiggsAudio" in e or ("transformers" in e and "cannot import name" in e):
        return ("OmniVoice не собрался: ему нужен более свежий transformers, "
                "а он берёт его из основного .venv. Лечение — поставить свой "
                "в окружение движка: "
                ".venv_omni\\Scripts\\python.exe -m pip install -U "
                "--target .venv_omni\\Lib\\site-packages transformers "
                "(основной .venv не трогаем — на нём Qwen3 и слух). "
                "Исходная ошибка: " + e[:200])
    return "OmniVoice: " + e[:300]


# Что менеджер подмешивает к своим трём движкам.
EXTRA_ENGINES = {
    "piper": PiperEngine,
    "omni": OmniVoiceEngine,
    "xtts": XttsEngine,
    "f5ru": F5RuEngine,
}

# Метаданные ВСЕХ движков для интерфейса. Лицензия здесь не формальность:
# владелец собирается монетизировать проект, и «работает, но использовать
# нельзя» — худший вид сюрприза, чем «не работает».
ENGINE_META = {
    "qwen3": {
        "title": "Qwen3-TTS — голос Сайки",
        "license": "Apache-2.0",
        "voice_clone": True,
        "note": "Клон её голоса, основной движок. Тяжёлый: ~4 ГБ VRAM и "
                "около минуты на первую загрузку.",
    },
    "silero": {
        "title": "Silero",
        "license": "MIT — если пакет v5_cis_base (⚠️ v4_ru был CC-BY-NC)",
        "voice_clone": False,
        "note": "Быстрый и лёгкий. ВАЖНО: коммерчески пригодны только пакеты "
                "v5_cis_base и v5_cis_base_nostress (MIT); прежний v4_ru — "
                "CC-BY-NC. Дефолт сменён 2026-07-26, пакет задаётся в "
                "tts.silero.model. Набор дикторов у v5 другой, чем у v4.",
    },
    "edge": {
        "title": "Edge-TTS (онлайн)",
        "license": "неофициальный доступ к сервису Microsoft",
        "voice_clone": False,
        "note": "Хорошее качество бесплатно, но это неофициальный клиент "
                "чужого сервиса: может отвалиться в любой момент и требует "
                "интернет.",
    },
}
for _name, _cls in EXTRA_ENGINES.items():
    ENGINE_META[_name] = {
        "title": {"piper": "Piper (офлайн, MIT)",
                  "omni": "OmniVoice — клон голоса, Apache-2.0",
                  "xtts": "XTTS-v2 — клон голоса",
                  "f5ru": "F5-TTS русский — клон голоса"}[_name],
        "license": _cls.license,
        "voice_clone": _cls.voice_clone,
        "note": _cls.note,
    }


# ═══════════════════ КАТАЛОГ ГОЛОСОВ (2026-07-26) ═══════════════════
# Раньше в интерфейсе можно было выбрать только ДВИЖОК, а внутри движка
# голос задавался руками в config. Но у Edge их десятки, у Piper четыре, у
# Silero свой набор в каждом пакете — выбирать вслепую по имени в json
# неудобно. Отдельная вкладка перечисляет всё разом и даёт послушать.
#
# Где можем — спрашиваем сам движок (Edge отдаёт список по сети, Silero
# держит его в загруженной модели), где нельзя — статический список.
# Клонирующие движки (Qwen3, OmniVoice, XTTS, F5) устроены иначе: у них
# «голос» это файл-образец, поэтому их голоса — это содержимое папки voice/.

# Языки, которые нас интересуют у облачных наборов: русский плюс соседние,
# на которых Сайка может пошутить. Остальные 400 голосов только мешают.
EDGE_LOCALES = ("ru-RU", "uk-UA", "be-BY", "kk-KZ", "en-US", "en-GB")


def _edge_voices():
    try:
        import asyncio
        import edge_tts
    except Exception:
        return []
    try:
        # list_voices() — сетевой запрос; вызывается только при открытии
        # вкладки голосов, не в горячем пути озвучки
        data = asyncio.run(edge_tts.list_voices())
    except Exception as e:
        log.debug("Edge не отдал список голосов: %s", e)
        return []
    out = []
    for v in data:
        loc = v.get("Locale", "")
        if loc not in EDGE_LOCALES:
            continue
        short = v.get("ShortName", "")
        gender = {"Female": "женский", "Male": "мужской"}.get(
            v.get("Gender", ""), "")
        out.append({"id": short,
                    "title": short.split("-")[-1].replace("Neural", ""),
                    "lang": loc, "gender": gender,
                    "note": ", ".join(
                        (v.get("VoiceTag", {}) or {}).get("VoicePersonalities", [])
                    ) or ""})
    out.sort(key=lambda x: (x["lang"] != "ru-RU", x["lang"], x["title"]))
    return out


def _silero_voices(engine):
    """Список дикторов берём у ЗАГРУЖЕННОЙ модели: у каждого пакета он свой,
    угадывать имена нельзя (в v5_cis_base нет xenia из v4_ru)."""
    m = getattr(engine, "model", None)
    names = list(getattr(m, "speakers", []) or []) if m is not None else []
    if not names:
        return [{"id": "", "title": "загрузи движок, чтобы увидеть голоса",
                 "lang": "ru", "gender": "", "note":
                 "Silero отдаёт список дикторов только после загрузки"}]
    return [{"id": n, "title": n, "lang": "ru", "gender": "", "note": ""}
            for n in names]


def _ref_voices():
    """Голоса клонирующих движков — это файлы-образцы в voice/."""
    d = resolve("voice")
    if not d.exists():
        return []
    out = []
    for f in sorted(d.iterdir()):
        if f.suffix.lower() not in (".wav", ".mp3", ".flac", ".ogg"):
            continue
        out.append({"id": f.name, "title": f.stem, "lang": "любой",
                    "gender": "", "note": "образец для клонирования"})
    return out


# ───────────── витрина голосов Piper: ВСЕ, а не только скачанные ─────────────
# У Piper голосов сотни на десятках языков, и каждый — пара файлов на диске.
# Показывать только уже скачанные бессмысленно: человек не узнает, что есть
# ещё. Поэтому читаем официальный индекс `voices.json` из репозитория голосов
# и помечаем, что уже лежит локально, а что можно докачать одной кнопкой.
_PIPER_INDEX = {"data": None, "ts": 0.0}
_PIPER_INDEX_TTL = 3600.0

# Языки вперёд списка: русский первым, потом соседние и английский.
_LANG_FIRST = ("ru", "uk", "be", "kk", "en")


def _piper_dir():
    return resolve("models/piper")


def _piper_index(force=False) -> dict:
    """{key: запись} из voices.json репозитория. Кэш на час: файл большой,
    а меняется редко."""
    import time
    if (not force and _PIPER_INDEX["data"] is not None
            and time.time() - _PIPER_INDEX["ts"] < _PIPER_INDEX_TTL):
        return _PIPER_INDEX["data"]
    try:
        from huggingface_hub import hf_hub_download
        import json as _json
        path = hf_hub_download(PIPER_REPO, "voices.json",
                              local_dir=str(_piper_dir()))
        data = _json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        log.debug("индекс голосов Piper недоступен (%s) — показываю только "
                  "русские из встроенного списка", e)
        data = {}
    _PIPER_INDEX["data"] = data
    _PIPER_INDEX["ts"] = time.time()
    return data


def _piper_local(entry) -> bool:
    """Скачан ли голос: проверяем оба файла пары (.onnx и .onnx.json)."""
    files = list((entry or {}).get("files") or {})
    onnx = [f for f in files if f.endswith(".onnx")]
    if not onnx:
        return False
    base = _piper_dir()
    return all((base / f).exists() for f in files if
               f.endswith(".onnx") or f.endswith(".onnx.json"))


def piper_catalog(only_ru=False) -> list:
    """Все голоса Piper с пометкой, скачан ли. Пустой индекс -> встроенные."""
    idx = _piper_index()
    if not idx:
        return [{"id": k, "title": v.split("—")[0].strip(), "lang": "ru",
                 "gender": ("женский" if "женский" in v else "мужской"),
                 "note": v.split("—", 1)[-1].strip(),
                 "downloaded": True, "size_mb": None}
                for k, v in PIPER_VOICES.items()]
    out = []
    for key, e in idx.items():
        lang = ((e.get("language") or {}).get("family")
                or (e.get("language") or {}).get("code", "")).split("_")[0]
        if only_ru and lang != "ru":
            continue
        files = (e.get("files") or {})
        size = sum(int((v or {}).get("size_bytes") or 0)
                   for k, v in files.items() if k.endswith(".onnx"))
        out.append({
            "id": key,
            "title": e.get("name") or key,
            "lang": lang or "?",
            "gender": "",
            "note": (e.get("quality") or "") + (
                f" · {(e.get('num_speakers') or 1)} гол."
                if (e.get("num_speakers") or 1) > 1 else ""),
            "downloaded": _piper_local(e),
            "size_mb": round(size / 1e6, 1) if size else None,
        })
    # русский вперёд, дальше по языку и имени
    out.sort(key=lambda v: (_LANG_FIRST.index(v["lang"])
                            if v["lang"] in _LANG_FIRST else 99,
                            v["lang"], v["title"]))
    return out


def piper_download(key: str) -> str:
    """Скачать конкретный голос по ключу из индекса."""
    from huggingface_hub import hf_hub_download
    idx = _piper_index()
    entry = idx.get(key)
    if not entry:
        # индекса нет — пробуем как русский medium по нашей схеме
        if key in PIPER_VOICES:
            PiperEngine()._voice_files(key)
            return f"голос {key} скачан"
        raise ValueError(f"нет такого голоса Piper: {key}")
    got = 0
    for f in (entry.get("files") or {}):
        if not (f.endswith(".onnx") or f.endswith(".onnx.json")):
            continue
        hf_hub_download(PIPER_REPO, f, local_dir=str(_piper_dir()))
        got += 1
    log.info("Piper: голос %s скачан (%d файла)", key, got)
    return f"голос {key} скачан"


def piper_delete(key: str) -> str:
    """Удалить скачанный голос — освободить место. Голоса Piper мелкие
    (20-70 МБ), но их сотни, и папка быстро распухает."""
    idx = _piper_index()
    entry = idx.get(key)
    base = _piper_dir()
    targets = []
    if entry:
        targets = [base / f for f in (entry.get("files") or {})
                   if f.endswith(".onnx") or f.endswith(".onnx.json")]
    else:
        # индекса нет — ищем по нашей схеме имён для русских голосов
        stem = f"ru/ru_RU/{key}/medium/ru_RU-{key}-medium"
        targets = [base / (stem + ".onnx"), base / (stem + ".onnx.json")]
    freed, gone = 0, 0
    for t in targets:
        try:
            if t.exists():
                freed += t.stat().st_size
                t.unlink()
                gone += 1
        except Exception as e:
            log.warning("не смогла удалить %s: %s", t, e)
    if not gone:
        return f"голос {key} и так не скачан"
    log.info("Piper: голос %s удалён, освобождено %.1f МБ", key, freed / 1e6)
    return f"голос {key} удалён, освободилось {freed / 1e6:.1f} МБ"


def voices_catalog(engines: dict) -> dict:
    """{имя движка: [голоса]} для вкладки голосов."""
    out = {}
    for name, eng in (engines or {}).items():
        try:
            if name == "edge":
                out[name] = _edge_voices()
            elif name == "piper":
                out[name] = piper_catalog()
            elif name == "silero":
                out[name] = _silero_voices(eng)
            elif name in ("qwen3", "omni", "xtts", "f5ru"):
                out[name] = _ref_voices()
            else:
                out[name] = []
        except Exception as e:
            log.debug("голоса %s не собрались: %s", name, e)
            out[name] = []
    return out


# Куда писать выбранный голос у каждого движка. Клонирующие меняют не
# «голос», а файл-образец — поэтому у них общий ключ.
VOICE_KEY = {
    "piper": "tts.piper.voice",
    "silero": "tts.silero.speaker",
    "edge": "tts.edge.voice",
    "qwen3": "tts.voice_ref_wav",
    "omni": "tts.voice_ref_wav",
    "xtts": "tts.voice_ref_wav",
    "f5ru": "tts.voice_ref_wav",
}


def set_voice(engine: str, voice: str) -> str:
    """Выбрать голос внутри движка. Возвращает человеческое подтверждение."""
    key = VOICE_KEY.get(engine)
    if not key:
        raise ValueError(f"у движка {engine} нет выбора голоса")
    val = voice
    if key == "tts.voice_ref_wav":
        # у клонирующих движков значение — путь до образца
        val = str(resolve("voice") / voice) if voice else ""
        CFG.set("tts.voice_ref", val)          # держим пару в согласии
    CFG.set(key, val)
    log.info("Голос движка %s: %s", engine, voice)
    return f"{engine}: голос «{voice}»"
