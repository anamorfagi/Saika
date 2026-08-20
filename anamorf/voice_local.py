"""Локальный голосовой цикл (2026-07-20): микрофон ПК -> VAD/STT -> диалог ->
озвучка в колонки. Позволяет разговаривать с Сайкой БЕЗ браузера — например,
когда интерфейсом служит нативное UE-приложение (оно показывает картинку,
а звук ходит целиком на сервере).

Включается конфигом mic.server_capture (по умолчанию false, чтобы не
конфликтовать с браузерным микрофоном: включай ОДНО из двух).

Устройство: mic.device (индекс или имя из sounddevice.query_devices()),
пусто — системный микрофон по умолчанию.

Полудуплекс: пока Сайка говорит, микрофон игнорируется (иначе она слышит
саму себя из колонок и отвечает сама себе). Барж-ин голосом тут нет —
перебить можно из UI (interrupt), это осознанный компромисс v1.
"""
import logging
import queue
import threading
import time

log = logging.getLogger("saika.voice_local")


class LocalVoiceLoop:
    """deps передаются из main.py, чтобы не плодить циклические импорты."""

    def __init__(self, cfg, stt, run_dialog, broadcast, report_problem,
                 make_speaker, has_browser=lambda: False):
        self.cfg = cfg
        self.stt = stt
        self.run_dialog = run_dialog
        self.broadcast = broadcast          # dict -> всем WS-клиентам (для UI)
        self.report_problem = report_problem
        self.make_speaker = make_speaker    # фабрика _ServerSpeaker
        # открыт браузерный UI (WS-клиент) -> его микрофон главный, наш
        # молчит. Иначе одна фраза ловится ДВАЖДЫ (два ответа, каша звука)
        self.has_browser = has_browser
        self.speaking = threading.Event()   # Сайка говорит -> мик молчит
        self.stop = threading.Event()
        self._attn_until = 0.0

    # ---------- внимание (упрощённая копия логики ws_endpoint) ----------
    def _addressed(self, text: str) -> bool:
        t = (text or "").lower()
        for p in self.cfg.get("attention.name_prefixes", ["сайк"]):
            if p in t:
                return True
        return False

    def _should_answer(self, text: str) -> bool:
        if self.cfg.get("attention.always", False):
            return True
        if not self.cfg.get("attention.enabled", True):
            return True
        now = time.time()
        if self._addressed(text) or now < self._attn_until:
            self._attn_until = now + self.cfg.get("attention.window_s", 30)
            return True
        return False

    # ---------- захват микрофона ----------
    def _capture_loop(self, chunks: "queue.Queue"):
        import numpy as np
        import sounddevice as sd
        sr = self.cfg.get("stt.sample_rate", 16000)
        device = self.cfg.get("mic.device") or None
        block = int(sr * 0.25)  # чанки по 250 мс, как слал браузер

        def cb(indata, frames, t, status):
            if not self.speaking.is_set() and not self.has_browser():
                chunks.put(bytes(indata))

        with sd.InputStream(samplerate=sr, channels=1, dtype="int16",
                            blocksize=block, device=device, callback=cb):
            log.info("Локальный микрофон запущен (устройство: %s)",
                     device or "по умолчанию")
            while not self.stop.is_set():
                time.sleep(0.2)

    # ---------- обработка фраз ----------
    def _dialog(self, text: str):
        import numpy as np  # noqa: F401 (для симметрии с main)
        out: "queue.Queue" = queue.Queue()
        stop_event = threading.Event()
        spk = self.make_speaker()
        sr = 24000
        self.speaking.set()
        worker = threading.Thread(target=self.run_dialog,
                                  args=(text, out, stop_event), daemon=True)
        worker.start()
        try:
            while True:
                try:
                    item = out.get(timeout=5)
                except queue.Empty:
                    if not worker.is_alive():
                        break
                    continue
                if item is None:
                    break
                if isinstance(item, bytes):
                    try:
                        spk.play(item, sr)
                    except Exception as e:
                        self.report_problem("tts", str(e),
                                            "голосовой цикл без звука")
                    continue
                t = item.get("type")
                if t == "audio_meta":
                    sr = item.get("sr", sr)
                self.broadcast(item)  # UI (браузер/UE) видит токены и статусы
                if t == "done":
                    break
        finally:
            spk.close()
            # хвост эха: динамики затихают не мгновенно
            time.sleep(0.3)
            self.speaking.clear()

    def _stt_loop(self, chunks: "queue.Queue"):
        import numpy as np
        while not self.stop.is_set():
            try:
                raw = chunks.get(timeout=0.5)
            except queue.Empty:
                continue
            pcm = np.frombuffer(raw, dtype=np.int16)
            try:
                results = self.stt.process_chunk(pcm)
            except Exception as e:
                self.report_problem("stt", str(e), "чанк пропущен")
                continue
            for r in results:
                text = (r.get("text") or "").strip()
                if not text:
                    continue
                r["heard_at"] = time.strftime("%H:%M:%S")
                if self._should_answer(text):
                    self.broadcast({"type": "stt", **r})
                    self._dialog(text)
                    self._attn_until = (time.time() +
                                        self.cfg.get("attention.window_s", 30))
                else:
                    self.broadcast({"type": "stt_ignored", **r})

    # ---------- запуск ----------
    def start(self):
        try:
            import sounddevice  # noqa: F401
        except ImportError:
            self.report_problem(
                "stt", "нет пакета sounddevice",
                "pip install sounddevice — и серверный микрофон заработает")
            return False
        chunks: "queue.Queue" = queue.Queue()
        threading.Thread(target=self._capture_loop, args=(chunks,),
                         daemon=True).start()
        threading.Thread(target=self._stt_loop, args=(chunks,),
                         daemon=True).start()
        log.info("Голосовой цикл без браузера активен")
        return True
