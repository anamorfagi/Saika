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

from anamorf.config import CFG, DATA_ROOT, resolve

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
        self._good = 0    # сколько кусков прожевали живыми (см. _load)

    def enabled(self):
        return bool(CFG.get("stt.draft", True))

    def _hangs(self):
        """Файл со счётчиком зависаний Vosk (переживает перезапуск)."""
        return DATA_ROOT / "data" / "draft_hangs.json"

    def _load(self):
        if self.rec is not None or self._tried:
            return self.rec
        self._tried = True
        # САМОЛЕЧЕНИЕ БЕЗ ДОКТОРА (2026-08-14, живой случай: «завис»).
        # Беймакс просыпается на ПАДЕНИИ — а тут процесс не упал, а встал
        # намертво внутри Kaldi на первом же куске звука. Зависание не
        # ловит никто: retry-цикл ждёт, доктор не зовётся, человек сидит
        # перед мёртвой консолью. Прервать нативный вызов изнутри питона
        # нельзя, поэтому лечим единственным доступным способом — НЕ
        # ВХОДИМ туда второй раз: метка чёрного ящика от прошлого запуска
        # говорит, что там уже умирали.
        # МЕТКА ЖИВЁТ ОДИН ЗАПУСК, А НЕ ВЕЧНО (2026-08-31, живой разбор).
        # Было: любое упоминание vosk в чёрном ящике выключало черновик
        # НАВСЕГДА — метку никто не снимал ни при удачном старте, ни при
        # выходе. Зависли один раз 27.08 в 13:48 — и по 31.08 включительно
        # черновика не было НИ РАЗУ, на каждом старте в логе честно
        # писалось «ВЫКЛЮЧЕН», а человек всё это время видел пустой экран
        # вместо растущих слов. Разовый зависон не имеет права хоронить
        # фичу. Теперь: метку снимаем сразу, зависания считаем отдельно, и
        # опускаем руки только после трёх подряд. Счётчик обнуляется, когда
        # черновик прожевал 300 кусков (~30с речи) живым — см. feed().
        try:
            from anamorf import stage
            last = stage.PATH.read_text(encoding="utf-8") \
                if stage.PATH.exists() else ""
            if "vosk" in last.lower():
                stage.clear()          # метка отработала — снимаем
                where = last.split("\t")[0]
                n = 0
                try:
                    n = int(json.loads(
                        self._hangs().read_text(encoding="utf-8")).get("n", 0))
                except Exception:
                    n = 0
                n += 1
                try:
                    f = self._hangs()
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_text(json.dumps({"n": n, "where": where}),
                                 encoding="utf-8")
                except Exception:
                    pass
                if n >= 3:
                    self.ok = False
                    self.error = "завис три раза подряд"
                    log.warning("Черновик распознавания ВЫКЛЮЧЕН: Vosk "
                                "завис %d раза подряд (%s). Точный движок "
                                "работает как работал — пропадёт только "
                                "серый текст по ходу фразы. Вернуть: "
                                "удалить data/draft_hangs.json.", n, where)
                    return None
                log.warning("Прошлый запуск завис внутри Vosk (%s) — пробую "
                            "ещё раз, попытка %d из 3", where, n)
        except Exception:
            pass
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
        # черновик держит СВОЙ нативный распознаватель (Kaldi внутри Vosk)
        # и работает по тому же звуку, что и основной движок
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
            from anamorf import stage
            stage.mark("черновик: vosk.AcceptWaveform")
            _acc = rec.AcceptWaveform(pcm16.tobytes())
            stage.clear()
            # ПРОЖИЛИ — ЗНАЧИТ ЗДОРОВЫ (2026-08-31). Тридцать секунд речи
            # без зависания снимают счёт прошлых зависаний: иначе три
            # старых обморока накопятся за месяцы и выключат черновик у
            # совершенно исправного Vosk.
            self._good += 1
            if self._good == 300:
                try:
                    self._hangs().unlink(missing_ok=True)
                except Exception:
                    pass
            if _acc:
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
