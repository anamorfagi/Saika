"""ЧЕРНОВИК РАСПОЗНАВАНИЯ — слова появляются сразу (2026-07-28).

ПОВОД. Точный движок (GigaAM) отдаёт текст ТОЛЬКО когда кусок закончился:
человек говорит две секунды, ещё секунда уходит на распознавание — и всё
это время на экране пусто, а потом разом падает абзац. Ощущается как «она
не слышит», хотя она слышит прекрасно.

РЕШЕНИЕ — ЧЕРНОВИК И ЧИСТОВИК, а не «ускорить точный движок». Ускорить его
нельзя: он по устройству работает целыми кусками. Зато рядом можно повесить
ПОТОКОВЫЙ движок, который выдаёт слова по мере их произнесения. Vosk ровно
такой, он уже есть в проекте и уже умеет отдавать промежуточный результат —
им никто не пользовался, потому что для диалога он не нужен.

Черновик серый и неточный, живёт на экране секунду-две и исчезает, как
только приходит чистовик. Никакой правды он не утверждает — он показывает,
что она СЛЫШИТ, пока думает. Это разные вещи, и путать их нельзя: в память,
в имена и в стенограмму уходит только чистовик.

ЦЕНА. Vosk — это десятки мегабайт и доли процента процессора, он не трогает
видеопамять и не конкурирует с основным движком. Нет модели Vosk на диске —
черновика просто не будет, всё остальное работает как работало.
"""
import json
import logging
import time

from server.config import CFG, resolve

log = logging.getLogger("saika.draft")


class Draft:
    def __init__(self):
        self.rec = None
        self.model = None
        self.ok = True
        self.error = ""
        self._tried = False
        self.last = ""
        self.last_ts = 0.0
        self.ms = 0.0     # скользящая цена одного куска

    def enabled(self):
        return bool(CFG.get("stt.draft", True))

    def _load(self):
        if self.rec is not None or self._tried:
            return self.rec
        self._tried = True
        try:
            from vosk import Model, KaldiRecognizer, SetLogLevel
            # ТИШИНА В КОНСОЛИ (2026-07-29, владелец: «логи странные» —
            # в консоль сыпались одинокие «&» строками. Это болтовня Kaldi
            # изнутри Vosk: он печатает диагностику МИМО питоновского
            # логгера, прямо в stderr, и на длинном системном звуке она
            # превращается в поток мусора, за которым не видно настоящих
            # сообщений. -1 = молчать.
            try:
                SetLogLevel(-1)
            except Exception:
                pass
            d = resolve(CFG.get("stt.engines.vosk.model_dir"))
            if not d or not d.exists():
                raise FileNotFoundError(f"нет модели Vosk: {d}")
            self.model = Model(str(d))
            self.rec = KaldiRecognizer(self.model,
                                       CFG.get("stt.sample_rate", 16000))
            self.rec.SetWords(False)
            log.info("Черновик распознавания: Vosk поднят")
        except Exception as e:
            self.ok, self.error = False, str(e)[:160]
            log.info("Черновика не будет (%s) — текст появится, как обычно, "
                     "целой фразой", self.error)
        return self.rec

    def feed(self, pcm16):
        """-> строка черновика, если она изменилась, иначе пусто.

        Зовётся из того же потока слуха, что и основной движок, — сразу
        после него. Порядок важен: если чистовик уже вернул фразу, черновик
        на этом куске не нужен."""
        if not self.enabled() or not self.ok:
            return ""
        rec = self._load()
        if rec is None:
            return ""
        try:
            t0 = time.monotonic()
            if rec.AcceptWaveform(pcm16.tobytes()):
                # кусок закрылся — черновик обнуляем: дальше слово скажет
                # точный движок, и спорить с ним черновику незачем
                self.last = ""
                return ""
            txt = (json.loads(rec.PartialResult()).get("partial") or "").strip()
            now = time.monotonic()
            # САМОЗАЩИТА (2026-07-28): звук идёт по 100мс кусками, и если
            # черновик стабильно жуёт кусок дольже 70мс, он съедает горячий
            # цикл слуха — а слух важнее черновика всегда. Отключаемся сами.
            self.ms = self.ms * 0.9 + (now - t0) * 1000 * 0.1
            if self.ms > 70:
                self.ok = False
                self.error = "слишком медленный на этом звуке — отключился"
                log.warning("Черновик: жую кусок %.0fмс из 100 — отключаюсь, "
                            "слух важнее", self.ms)
                return ""
            # не чаще пяти раз в секунду и только когда текст ИЗМЕНИЛСЯ:
            # иначе в вебсокет улетает по десять одинаковых строк в секунду
            if txt and txt != self.last and now - self.last_ts > 0.2:
                self.last, self.last_ts = txt, now
                return txt
        except Exception as e:
            self.ok, self.error = False, str(e)[:160]
            log.warning("Черновик отвалился (%s) — дальше без него", self.error)
        return ""

    def reset(self):
        self.last = ""

    def status(self):
        return {"on": self.enabled() and self.ok, "error": self.error}


DRAFT = Draft()
