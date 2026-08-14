"""TTS-менеджер. Приоритет: Qwen3-TTS-streaming (клон голоса Сайки).

Фоллбэки: Silero (локальный, CPU) → edge-tts (онлайн).
Выход всегда: генератор (pcm_float32_bytes, sample_rate).
"""
import asyncio
import io
import json
import logging
import re
import threading
import time

import numpy as np

from server.config import CFG, ROOT, resolve
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
    now = _EMO_TEXT.get(_EMOTION["cls"] or "", "")
    # ПОСТОЯННЫЙ ТОН КОСТЮМА (2026-08-13). Эмоция — про эту реплику, тон —
    # про персонажа целиком, и одно другому не мешает: сперва «как говорит
    # этот герой вообще», потом «а сейчас он раздражён».
    tone = str(CFG.get("tts.tone", "") or "").strip()
    return " ".join(p for p in (tone, now) if p)


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
            # МИНЫ SPEECHBRAIN — ДО ИМПОРТА (2026-07-29, живой лог:
            # 22:13:21,517 qwen3 упал «LazyModule(k2_fsa) failed», а
            # 22:13:21,608 отпечаток голоса обезвредил мины — на 91мс ПОЗЖЕ.
            # Автопуск озвучки и прогрев голосов бегут параллельно, и кто
            # первый — лотерея. Со второй попытки (22:17:52) движок вставал
            # без единой жалобы, потому что мины уже сняты. Не полагаемся на
            # чужой прогрев: снимаем сами, вызов повторный — дешёвый no-op.)
            try:
                from server.torch_gate import defuse_speechbrain
                defuse_speechbrain()
            except Exception as _e:
                log.debug("обезвреживание speechbrain: %s", _e)
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
                    # РЕЖИМ КОМПИЛЯЦИИ ПО СВОБОДНОЙ VRAM (2026-07-29,
                    # владелец: «память съедает аж 15 ГБ в начале»).
                    # reduce-overhead включает CUDA-графы, а графы ПИНЯТ
                    # память под каждый размер входа — прогрев записал 9
                    # разных графов, и это гигабайты пиков. Когда памяти
                    # впритык — компилируем в default: чуть медленнее на
                    # старте фразы, зато без прожорливых графов и без
                    # «Железо на пределе: VRAM 95%» сразу после загрузки.
                    # CUDA-ГРАФЫ БОЛЬШЕ НЕ ПО УМОЛЧАНИЮ (2026-08-14, живой
                    # обвал). В логе владельца прямо перед смертью процесса:
                    #
                    #   [__cudagraphs] CUDAGraph supports dynamic shapes by
                    #   recording a new graph for each distinct input size.
                    #   We have observed 9 distinct sizes.
                    #   [] Saika crashed (code -1073741819)
                    #
                    # -1073741819 — это access violation. Режим
                    # reduce-overhead включает CUDA-графы, а фразы у живого
                    # человека каждый раз разной длины: на каждый новый
                    # размер пишется новый граф, они делят один пул памяти,
                    # и рано или поздно кто-то пишет в чужое. Выигрыш —
                    # доли секунды на старте фразы. Цена — падение сервера
                    # посреди разговора. Обмен невыгодный (PHILOSOPHY §0.5:
                    # стабильность важнее скорости).
                    #
                    # Режим остаётся управляемым: tts.qwen3.compile_mode =
                    # "reduce-overhead" в config вернёт прежнее поведение
                    # тому, у кого оно не падает.
                    _mode = str(cfg.get("compile_mode", "") or "") or "default"
                    self.model.enable_streaming_optimizations(
                        decode_window_frames=cfg.get("decode_window_frames", 80),
                        use_compile=True, use_cuda_graphs=False,
                        compile_mode=_mode,
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

    def _model_file(self, pack):
        """Где torch.hub держит чекпоинт этого пакета."""
        import torch
        from pathlib import Path as _P
        return (_P(torch.hub.get_dir()) / "snakers4_silero-models_master" /
                "src" / "silero" / "model" / f"{pack}.pt")

    def _drop_if_corrupt(self, pack) -> bool:
        """Битый чекпоинт удаляем САМИ, до попытки загрузки (2026-07-29).

        ПОВОД — две недели незакрывающейся петли у владельца. Оборванная
        закачка оставляет файл ПОЛНОГО имени, но без «оглавления» zip в
        конце (central directory пишется последней). torch.hub видит файл
        на месте и говорит «уже скачано» — открывает, падает, и так каждый
        раз. Наша же починка «удаляю битый файл и качаю заново» чистила не
        тот каталог и в этот кэш не заглядывала.

        Проверка стоит миллисекунды (читается только оглавление), а лечение
        честное: нет оглавления — файла нет, torch скачает заново. Заодно
        подбираем .partial-обрубки, которые копятся от сорванных попыток.
        Важно на плохом интернете: перекачивается ТОЛЬКО битое.
        """
        try:
            f = self._model_file(pack)
        except Exception:
            return False
        if not f.exists():
            return False
        try:
            import zipfile
            with zipfile.ZipFile(f) as z:
                z.namelist()
            return False                     # целый — не трогаем
        except Exception as e:
            try:
                size = f.stat().st_size
                f.unlink()
                for junk in f.parent.glob(f.name + "*.partial"):
                    junk.unlink()
                log.warning("Silero: чекпоинт %s битый (%s, %.1f МБ) — удалила, "
                            "качаю заново", pack, type(e).__name__, size / 1e6)
                return True
            except Exception as e2:
                log.warning("Silero: чекпоинт %s битый, но удалить не вышло "
                            "(%s) — закрой Сайку и снеси файл руками: %s",
                            pack, e2, f)
                return False

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
                self._drop_if_corrupt(cand)   # обрубок мешает torch'у качать
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


# ═══ ХЛЕБНАЯ КРОШКА ПРОТИВ ПЕТЛИ КРАШЕЙ (2026-08-14) ═══
# Нативный обвал (0xC0000005) убивает процесс мгновенно — ни try, ни
# finally питона не срабатывают, лога тоже не остаётся. Единственный
# способ узнать, на чём умерли, — оставить след НА ДИСКЕ перед опасным
# местом и убрать его после успеха. Файл пережил перезапуск — значит
# прошлый старт умер ровно здесь.
#
# Зачем это, если Беймакс уже умеет распознать краш по логу: он переводит
# tts.engine на запасной, но автопуск потом СОРТИРУЕТ цепочку по ручным
# оценкам владельца — и qwen3 с его высокой палочкой прыгает обратно на
# первое место. Три перезапуска подряд с одним и тем же крахом. Крошка
# закрывает петлю: два обвала на загрузке — движок уходит в tts.disabled,
# который загрузчик уже уважает, и человек видит почему.
_CRUMB = ROOT / "data" / "tts_loading.txt"
_STRIKES = ROOT / "data" / "tts_strikes.json"
_HEAVY = ("qwen3", "omni", "xtts", "f5")     # те, кто умеет ронять процесс


def _crumb_set(name: str):
    if not any(h in name.lower() for h in _HEAVY):
        return
    try:
        _CRUMB.parent.mkdir(parents=True, exist_ok=True)
        _CRUMB.write_text(name, encoding="utf-8")
    except Exception:
        pass


def _crumb_clear():
    try:
        _CRUMB.unlink(missing_ok=True)
    except Exception:
        pass


def crash_guard() -> str:
    """Зовётся на старте ДО загрузки голосов. Возвращает пояснение, если
    пришлось кого-то отключить, иначе пусто."""
    try:
        if not _CRUMB.exists():
            return ""
        name = (_CRUMB.read_text(encoding="utf-8").strip() or "").lower()
        _crumb_clear()
        if not name:
            return ""
        try:
            st = json.loads(_STRIKES.read_text("utf-8"))
        except Exception:
            st = {}
        st[name] = int(st.get(name, 0)) + 1
        _STRIKES.write_text(json.dumps(st, ensure_ascii=False),
                            encoding="utf-8")
        if st[name] < 2:
            log.warning("Озвучка «%s» уронила процесс при загрузке "
                        "(попытка %d). Ещё один раз — отключу.", name, st[name])
            return ""
        dis = list(CFG.get("tts.disabled", []) or [])
        if name not in dis:
            dis.append(name)
            CFG.set("tts.disabled", dis)
        return (f"Голос «{name}» дважды подряд обрушил процесс при загрузке "
                "— отключила его, чтобы система вообще поднялась. Это не "
                "поломка кода: чаще всего не хватает видеопамяти. Освободи "
                "VRAM и убери его из tts.disabled в настройках.")
    except Exception as e:
        log.debug("страж крашей озвучки: %s", e)
        return ""


def note_good(name: str):
    """Движок поднялся — снимаем с него прошлые «страйки»."""
    try:
        st = json.loads(_STRIKES.read_text("utf-8"))
        if st.pop((name or "").lower(), None) is not None:
            _STRIKES.write_text(json.dumps(st, ensure_ascii=False),
                                encoding="utf-8")
    except Exception:
        pass


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
            # ЗАГРУЗКА ОЗВУЧКИ — ПОД ТЕМ ЖЕ ЗАМКОМ, ЧТО И ОСТАЛЬНОЙ ТОРЧ
            # (2026-08-14, живой краш: три перезапуска подряд с
            # -1073741819 — это access violation, нативный обвал).
            #
            # Замок TORCH_GATE заведён ровно для того, чтобы две модели не
            # въезжали в память одновременно, и им пользуются слух,
            # отпечаток голоса и стенограмма. ОЗВУЧКУ сюда забыли — а она
            # самый тяжёлый загрузчик из всех: qwen3-TTS не просто читает
            # веса, он компилирует (inductor) и пишет CUDA-графы. Пока это
            # шло вторым в очереди, обвала не случалось; стоило по просьбе
            # владельца пустить голос ПЕРВЫМ — компиляция совпала с
            # загрузкой GigaAM, PANNs и ECAPA, и процесс лёг.
            #
            # Порядок «голос первым» при этом сохраняется: замок не меняет
            # очередь, он лишь запрещает лезть в память вдвоём.
            from server.torch_gate import TORCH_GATE
            with TORCH_GATE:
                _crumb_set(name)
                try:
                    self.engines[name].load()
                finally:
                    _crumb_clear()
            self.health[name] = "ok"
            note_good(name)
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
        # ВЫБРАЛ ДВИЖОК — ЗНАЧИТ ХОЧЕШЬ СЛЫШАТЬ (2026-07-29). Жёсткая
        # разгрузка пишет tts.enabled=False В КОНФИГ, то есть навсегда, а не
        # на сеанс. Владелец жал её несколько раз за день, потом тыкал в
        # движки — те честно грузились и висели «в памяти», а speak() на
        # первой же строке выходил по выключенному флагу. Снаружи: оба
        # движка зелёные, спектр не шелохнётся, «не озвучивается ни одна
        # строка». Выбор движка — самое ясное «включи звук», какое человек
        # может сделать; молчать после него нельзя.
        if name != "off" and not CFG.get("tts.enabled", True):
            CFG.set("tts.enabled", True)
            log.info("Озвучка была выключена разгрузкой — включаю обратно: "
                     "выбран движок «%s»", name)

    def _priority(self):
        """ПОРЯДОК ВЛАДЕЛЬЦА ГЛАВНЕЕ СЕКУНДОМЕРА (2026-07-29, живой гнев:
        «по какой причине это включается вторым, когда я его в самый низ
        опустил». Раньше запасной выбирался по замеренной скорости +
        любимым, а порядок в меню был просто витриной — человек двигал
        строку и справедливо ждал, что двинул ПРИОРИТЕТ. Теперь
        tts.fallback_order — закон: что выше в списке, то и запасной.
        Скорость решает только для движков, которых в списке нет.
        Умолчание: Silero в самом хвосте («как старушка говорит» — быстрый,
        но по качеству последний из живых, и лицензия у него запрещает
        коммерцию; пусть спасает, лишь когда больше некому)."""
        # Рейтинг = тот же, что видит человек полосками в меню: ручная
        # оценка (он её и двигал!) поверх базового КАЧЕСТВА голоса; скорость
        # синтеза — только при равных. Раньше решала одна скорость — и
        # Silero («как старушка») лез вторым, как его ни опускай.
        base = {"qwen3": 9, "piper": 7, "omni": 7, "xtts": 6, "f5ru": 6,
                "edge": 5, "silero": 3}
        manual, speed = {}, {}
        try:
            from server import ratings
            manual = ratings.manual_scores() or {}
            speed = ratings.tts_scores() or {}
        except Exception:
            pass

        def eff(n):
            return manual.get(n, base.get(n, 6))

        backups = [n for n in self.engines
                   if n != self.current_name and n != "off"]
        backups.sort(key=lambda n: (-eff(n), -speed.get(n, 0)))
        # «off» не запасной вариант: свалиться в тишину при поломке движка
        # — это не фолбэк, а молчание без объяснений
        return [self.current_name] + backups

    def _chain(self):
        # движки из tts.disabled НЕ трогаем совсем (напр. qwen3, который
        # нативно роняет процесс на этом ПК) — иначе фоллбэк в него = краш
        disabled = set(CFG.get("tts.disabled", []))
        return [n for n in self._priority()
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
                # ФОРМА ГОЛОСА (2026-08-13): темп и высота применяются
                # ЗДЕСЬ, над готовым PCM — один код на все семь движков.
                # Иначе «говори помедленнее» звучало бы по-разному у Qwen3,
                # Edge и Piper, а у Piper с Silero не работало бы вовсе.
                from server.tts import shape as _shape
                _sp, _semi = _shape.settings()
                for item in engine.speak(text):
                    yielded = True
                    try:
                        pcm, sr = item
                        pcm = _shape.apply(pcm, sr, _sp, _semi)
                        item = (pcm, sr)
                        # секунды синтезированного аудио (float32 → /4)
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
                # «ЕЩЁ ГРУЖУСЬ» — НЕ ПОЛОМКА (2026-08-14, живой лог: omni
                # ломался и «чинился» по три раза в секунду, засыпая и лог,
                # и чат. Владелец резонно: «хули квен падает постоянно и
                # омни». Ничего не падало: OmniVoice честно отвечает «модель
                # ещё грузится», а мы записывали это в сломанные, звали
                # ремонт и тут же объявляли починку. Прогрев — нормальное
                # состояние, а не авария: тихо берём другой голос на эту
                # фразу и пробуем снова на следующей.
                if ("ещё грузит" in str(e) or "еще грузит" in str(e)
                        or "loading" in str(e).lower()):
                    log.info("Голос «%s» ещё греется — эту фразу скажу "
                             "другим", name)
                    continue
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
                # порядок запасных, как его видит фолбэк — интерфейс рисует
                # список ИМЕННО в нём и даёт перетаскивать (2026-07-29)
                "order": [n for n in self._chain() if n != "off"],
                "errors": self.last_error, "diag": self.last_diag,
                # meta (2026-07-26): название, лицензия, умеет ли клонировать.
                # Едет вместе со статусом, чтобы интерфейсу не нужен был
                # второй запрос на каждое открытие меню голоса.
                "meta": self.engine_meta()}
