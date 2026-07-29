"""СТЕНОГРАММА — непрерывная расшифровка того, что слышно (2026-07-28).

ПОВОД. Включили ролик, распознавание слышит всё, а в чат попадает хорошо
если треть. Причина не в движке: конвейер слуха собран под РАЗГОВОР, где
после реплики есть пауза. Диктор на видео говорит сплошняком, паузы короче
порога, кусок растёт до предельных 25 секунд, движок молотит его секунды —
и всё это время следующая речь ждёт в очереди. Отсюда и «треть».

ЧТО ДЕЛАЕМ. Отдельный режим, в котором слух настроен не на диалог, а на
поток: паузу считаем за конец фразы уже через треть секунды, кусок рубим
через семь секунд. Текст идёт чаще и мельче — зато идёт весь.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ, А НЕ ПРОСТО ЛЕНТА В ЧАТЕ. У стенограммы другие
требования, чем у диалога:
- она склеивает мелкие куски обратно в человеческие предложения;
- ей нужны знаки препинания и заглавные буквы — распознавание отдаёт голый
  нижний регистр, и на длинном тексте это нечитаемо;
- у каждой реплики метка говорящего и метка того, КАК это было сказано;
- всё это должно лечь в файл, который потом можно открыть и прочитать.

ЗНАКИ ПРЕПИНАНИЯ. Через silero_te, если он поставлен: это маленькая офлайн-
модель, которая как раз восстанавливает пунктуацию и регистр для русского.
Нет её — текст остаётся как есть, но собирается и сохраняется всё равно.
Не ставить точки — плохо; терять текст, потому что нечем ставить точки, —
хуже.

МЕТКА НАСТРОЕНИЯ БЕРЁТСЯ ИЗ ГОЛОСА, А НЕ ИЗ СЛОВ. Тон и громкость уже
меряются в отпечатке голоса, и они говорят про то, КАК сказано, честнее
любого разбора текста: по словам «ну отлично» не отличить радость от злости,
по голосу — отличается сразу.
"""
import logging
import threading
import time
from pathlib import Path

from server.config import CFG, ROOT

log = logging.getLogger("saika.transcript")

DIR = ROOT / "data" / "transcript"
MAX_LINES = 4000


class Transcript:
    def __init__(self):
        self.lines: list = []        # {ts, who, text, mood, engine}
        self.on = False
        self._te = None
        self._te_tried = False
        self._lock = threading.Lock()
        self.file = ""
        self._pending = ""           # незаконченное предложение
        self._pending_who = ""
        self._pending_ts = 0.0
        self._pending_mood = ""

    # ------------------------------------------------------------ пунктуация
    def _enhance(self, text: str) -> str:
        """Знаки препинания, если модель УЖЕ в памяти. Никогда не грузит её
        сама — только пинает фоновую загрузку и возвращает текст как есть.

        ГРАБЛИ 2026-07-28, поймано живым логом владельца: первый вызов
        torch.hub.load СКАЧИВАЕТ silero-models с github, а github может
        отвечать минутами. Загрузка жила прямо здесь — и первый же кусок,
        которому захотелось запятых, повесил поток распознавания на 2.5
        минуты: фразы копились в очереди, «транскриб перестал фурычить»,
        а потом вся очередь выстрелила разом. Сетевая загрузка не имеет
        права стоять на пути звука — никакая и никогда."""
        if not CFG.get("transcript.punctuate", True):
            return text
        if self._te is None:
            self._warm_bg()
            return text
        try:
            return self._te(text, lan="ru")
        except Exception as e:
            log.debug("silero_te не справился: %s", e)
            return text

    def _warm_bg(self):
        """Поднять silero_te в отдельном потоке. Пока он не готов, текст
        идёт без знаков; готов — следующая фраза уже с ними.

        Повторяем не чаще раза в полчаса: одна неудача (github мигнул) не
        должна оставлять СУТОЧНУЮ запись без запятых до перезапуска."""
        now = time.time()
        if self._te_tried and now - getattr(self, "_te_ts", 0) < 1800:
            return
        self._te_tried = True
        self._te_ts = now

        def run():
            try:
                # под общим замком: параллельное ленивое поднятие двух
                # торчёвых моделей роняет вторую (см. server/torch_gate.py)
                from server.torch_gate import TORCH_GATE
                with TORCH_GATE:
                    import torch
                    torch.set_num_threads(1)
                    res = torch.hub.load(
                        repo_or_dir="snakers4/silero-models", model="silero_te")
                # ГРАБЛИ 2026-07-29: «too many values to unpack (expected 4)».
                # Пакет обновился и стал возвращать пять значений вместо
                # четырёх, причём НУЖНОЕ — последнее: это функция apply_te,
                # а не сама модель. Жёсткая распаковка ломается на каждом
                # обновлении silero; берём последнее вызываемое и сразу
                # проверяем его живой строкой — если не отвечает, честно
                # работаем без знаков препинания.
                te = None
                if isinstance(res, (tuple, list)):
                    cands = [x for x in res if callable(x)]
                    te = cands[-1] if cands else (res[0] if res else None)
                else:
                    te = res
                if te is None:
                    raise RuntimeError("silero_te вернул что-то незнакомое")
                probe = te("привет как дела", lan="ru")
                if not isinstance(probe, str) or not probe.strip():
                    raise RuntimeError("silero_te молчит на проверочной фразе")
                self._te = te
                log.info("Стенограмма: silero_te поднят — знаки препинания "
                         "есть (проверка: %r)", probe[:40])
            except Exception as e:
                log.info("Стенограмма: silero_te недоступен (%s) — пишу как "
                         "распознано", str(e)[:120])

        threading.Thread(target=run, daemon=True, name="silero-te").start()

    # ---------------------------------------------------------------- приём
    def add(self, text: str, who: str = "", mood: str = "", engine: str = ""):
        """Кусок распознанной речи. Мелкие куски склеиваем в предложения:
        поток режется по паузам в треть секунды, и без склейки стенограмма
        превращается в столбик из двух слов."""
        text = (text or "").strip()
        if not self.on or not text:
            return None
        with self._lock:
            same = (who == self._pending_who and
                    time.time() - self._pending_ts < 6.0)
            if same and self._pending and not self._pending[-1:] in ".!?":
                self._pending += " " + text
            else:
                if self._pending:
                    self._flush(engine)
                self._pending = text
                self._pending_who = who
                self._pending_mood = mood
            self._pending_ts = time.time()
            # длинное предложение закрываем сами: ждать точки от диктора,
            # который говорит абзацами, можно до вечера
            if len(self._pending) > int(CFG.get("transcript.max_chars", 320)):
                r = self._flush(engine)
                self._autosave()
                return r
        self._autosave()
        return None

    def _autosave(self):
        """Раз в десять минут — на диск. Суточная запись не имеет права
        пропасть из-за одного падения процесса на восьмом часу (2026-07-29,
        владелец затевает дневной стресс-тест). Пишем В ТОТ ЖЕ файл."""
        if not self.on or time.time() - getattr(self, "_auto_ts", 0) < 600:
            return
        self._auto_ts = time.time()
        try:
            self.save()
            log.info("Стенограмма: автосохранение (%d строк)", len(self.lines))
        except Exception as e:
            log.warning("Стенограмма: автосохранение не удалось: %s", e)

    def _flush(self, engine=""):
        if not self._pending:
            return None
        line = {"ts": self._pending_ts or time.time(),
                "who": self._pending_who, "mood": self._pending_mood,
                "text": self._enhance(self._pending), "engine": engine}
        self.lines.append(line)
        del self.lines[:-MAX_LINES]
        self._pending = ""
        return line

    def flush(self, engine=""):
        with self._lock:
            return self._flush(engine)

    # ---------------------------------------------------------------- режим
    def start(self):
        self.on = True
        self.lines = []
        self._pending = ""
        self.file = ""
        # имя файла фиксируется на старте: автосохранение переписывает ОДИН
        # файл, а не плодит по файлу каждые десять минут
        self._stamp = time.strftime("%Y%m%d_%H%M")
        self._auto_ts = time.time()
        log.info("Стенограмма: пишу")
        return self.status()

    def stop(self):
        self.flush()
        self.on = False
        log.info("Стенограмма: остановлена, строк %d", len(self.lines))
        return self.status()

    def status(self):
        return {"on": bool(self.on), "lines": len(self.lines),
                "chars": sum(len(x["text"]) for x in self.lines),
                "file": self.file,
                "punctuate": bool(CFG.get("transcript.punctuate", True)),
                "te": bool(self._te),
                "tail": self.lines[-3:]}

    # ----------------------------------------------------------------- файл
    def save(self):
        self.flush()
        DIR.mkdir(parents=True, exist_ok=True)
        stamp = getattr(self, "_stamp", "") or time.strftime("%Y%m%d_%H%M")
        p = DIR / f"transcript_{stamp}.md"
        head = [f"# Стенограмма — {time.strftime('%d.%m.%Y %H:%M')}", ""]
        who_prev = None
        body = []
        for x in self.lines:
            t = time.strftime("%H:%M:%S", time.localtime(x["ts"]))
            who = x["who"] or "неизвестный голос"
            if who != who_prev:
                body.append("")
                body.append(f"**{who}**"
                            + (f" · _{x['mood']}_" if x["mood"] else ""))
                who_prev = who
            body.append(f"`{t}` {x['text']}")
        p.write_text("\n".join(head + body) + "\n", "utf-8")
        self.file = p.name
        log.info("Стенограмма: сохранена %s (%d строк)", p.name, len(self.lines))
        return {"ok": True, "file": p.name, "lines": len(self.lines)}


def mood_of(pitch: float, energy: float, base_lo=0, base_hi=0):
    """Как это было сказано — из голоса, а не из слов.

    Нарочно грубо и мало слов: четыре состояния, которые слышны любому и не
    требуют веры в модель. Тонкие оттенки («сарказм») тут были бы выдумкой."""
    if not energy:
        return ""
    hi = base_hi or 0
    lo = base_lo or 0
    rel = 0.5
    if hi > lo > 0:
        rel = (pitch - lo) / max(1e-6, hi - lo)
    if energy > 0.72 and rel > 0.6:
        return "на подъёме"
    if energy > 0.72:
        return "громко"
    if energy < 0.28:
        return "тихо"
    if rel > 0.72:
        return "оживлённо"
    return "ровно"


TRANSCRIPT = Transcript()
