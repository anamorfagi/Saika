"""Память Сайки — единый поток событий с тремя горизонтами сжатия.

RAW (2-4 часа, дословно)
  │ автосжатие каждые 2 часа            — LLM суммаризует блок в эпизод
EPISODES (дни/недели, суть+эмоция)      — векторный поиск (ChromaDB)
  │ автосжатие раз в неделю
CORE (месяцы/годы, образы людей)        — json-паттерны с confidence

Категории людей: owner / regular / stranger.
Правила против переполнения: decay by salience, compression ratio,
hard cap с приоритетом (owner и регуляры защищены).
"""
import json
import logging
import sqlite3
import threading
import time
from datetime import datetime

from anamorf.config import CFG, resolve

log = logging.getLogger("saika.memory")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    person_id TEXT NOT NULL,
    role TEXT NOT NULL,           -- user / assistant
    text TEXT NOT NULL,
    salience REAL DEFAULT 0.5,
    compressed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS episodes(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_start REAL, ts_end REAL,
    person_id TEXT,
    summary TEXT,
    emotion TEXT,
    salience REAL DEFAULT 0.5,
    consolidated INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS days(
    date TEXT PRIMARY KEY,        -- 2026-08-15
    digest TEXT,                  -- о чём был день, по людям
    threads TEXT,                 -- нити, которые в этот день трогали
    ts REAL
);
CREATE TABLE IF NOT EXISTS persons(
    id TEXT PRIMARY KEY,
    name TEXT,
    category TEXT DEFAULT 'stranger',   -- owner / regular / stranger
    sessions INTEGER DEFAULT 0,
    messages INTEGER DEFAULT 0,
    last_seen REAL,
    core_json TEXT DEFAULT '{}',
    confidence REAL DEFAULT 0.3
);
"""

SUMMARIZE_PROMPT = """Ты — модуль памяти AI-компаньона Сайки. Сожми диалог в один эпизод памяти.
Сохрани: суть разговора, эмоцию, важные факты о человеке, решения.
Ответь строго JSON: {"summary": "...", "emotion": "...", "salience": 0.0-1.0,
"thread": "..."}
salience — важность: эмоционально сильное, уникальное, важные факты = выше.
thread — КОРОТКОЕ (2-4 слова) имя темы, к которой относится кусок:
«запуск Сайки», «голос и озвучка», «поиск игр на диске». Одна и та же тема
в разные дни должна называться ОДИНАКОВО — по имени человек потом просит
вспомнить нить целиком. Если тема бытовая и разовая — пиши «разное».

Диалог:
"""

CORE_PROMPT = """Ты — модуль памяти AI-компаньона Сайки. Вот текущий образ человека (JSON)
и новые эпизоды за неделю. Обнови образ: устойчивые факты, стиль, что работает над,
триггеры, последнее состояние. Не выдумывай. Ответь строго JSON:
{"core": {...}, "confidence": 0.0-1.0}

Текущий образ:
{current}

Новые эпизоды:
{episodes}
"""


class Memory:
    def __init__(self):
        self.db_path = resolve(CFG.get("memory.db_path"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        # МИГРАЦИЯ ЖИВОЙ БАЗЫ (2026-08-15): у владельца она копится с
        # июля, дропать её нельзя — досыпаем колонку, если её нет.
        try:
            have = {r[1] for r in self._conn.execute(
                "PRAGMA table_info(episodes)")}
            if "thread" not in have:
                self._conn.execute("ALTER TABLE episodes ADD COLUMN thread TEXT")
        except Exception as e:
            log.warning("миграция episodes.thread не прошла: %s", e)
        self._conn.commit()
        self._chroma = None
        self._ensure_owner()

    # ---------- ChromaDB (ленивая, необязательная) ----------
    def _collection(self):
        if self._chroma is None:
            try:
                import chromadb
                client = chromadb.PersistentClient(
                    path=str(resolve(CFG.get("memory.chroma_path"))))
                self._chroma = client.get_or_create_collection("episodes")
            except Exception as e:
                log.warning("ChromaDB недоступна, RAG по ключевым словам: %s", e)
                self._chroma = False
        return self._chroma

    def _ensure_owner(self):
        owner = CFG.get("owner", {"name": "Owner", "id": "owner"})
        with self.lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO persons(id,name,category,last_seen) "
                "VALUES(?,?,?,?)",
                (owner.get("id", "owner"), owner.get("name", "Owner"),
                 "owner", time.time()))
            self._conn.commit()

    # ---------- запись потока ----------
    def add_event(self, person_id, role, text, salience=0.5):
        with self.lock:
            self._conn.execute(
                "INSERT INTO events(ts,person_id,role,text,salience) VALUES(?,?,?,?,?)",
                (time.time(), person_id, role, text, salience))
            if role == "user":
                self._conn.execute(
                    "UPDATE persons SET messages=messages+1,last_seen=? WHERE id=?",
                    (time.time(), person_id))
            self._conn.commit()
        self._promote(person_id)
        self._trim_raw()

    def drop_last(self, person_id, role=None, n=1) -> int:
        """Забыть последние n событий (2026-07-26, для «↻ переспросить»).

        Нужно именно удаление из RAW, а не пометка: иначе при регенерации
        отвергнутый ответ остаётся в истории, модель видит и его, и новый
        вопрос — и второй раз выдаёт то же самое, только с извинениями.
        Сжатые в эпизоды события НЕ трогаем: их уже переписала LLM, там
        отдельной реплики может не существовать.
        """
        with self.lock:
            if role:
                rows = self._conn.execute(
                    "SELECT id FROM events WHERE person_id=? AND role=? "
                    "AND compressed=0 ORDER BY id DESC LIMIT ?",
                    (person_id, role, n)).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id FROM events WHERE person_id=? AND compressed=0 "
                    "ORDER BY id DESC LIMIT ?", (person_id, n)).fetchall()
            ids = [r[0] for r in rows]
            if not ids:
                return 0
            self._conn.execute(
                "DELETE FROM events WHERE id IN (%s)"
                % ",".join("?" * len(ids)), ids)
            self._conn.commit()
        return len(ids)

    def _promote(self, person_id):
        """stranger -> regular по критерию 3+ сессий или 30+ сообщений."""
        with self.lock:
            row = self._conn.execute(
                "SELECT category,sessions,messages FROM persons WHERE id=?",
                (person_id,)).fetchone()
            if not row:
                self._conn.execute(
                    "INSERT INTO persons(id,name,last_seen) VALUES(?,?,?)",
                    (person_id, person_id, time.time()))
                self._conn.commit()
                return
            cat, sessions, messages = row
            if cat == "stranger" and (
                sessions >= CFG.get("memory.regular_min_sessions", 3)
                or messages >= CFG.get("memory.regular_min_messages", 30)
            ):
                self._conn.execute(
                    "UPDATE persons SET category='regular' WHERE id=?", (person_id,))
                self._conn.commit()

    def _trim_raw(self):
        limit = CFG.get("memory.raw_limit_messages", 4000)
        with self.lock:
            self._conn.execute(
                "DELETE FROM events WHERE compressed=1 AND id NOT IN "
                "(SELECT id FROM events ORDER BY id DESC LIMIT ?)", (limit,))
            self._conn.commit()

    def recent_raw(self, person_id=None, limit=30, since_ts=0.0,
                   with_ts=False):
        """Последние сообщения. with_ts=True — кортежи (ts, role, text):
        нужно якорю истории в main.py (стабильный префикс для KV-кэша)."""
        q = ("SELECT ts,role,text FROM events" if with_ts
             else "SELECT role,text FROM events")
        conds, args = [], []
        if person_id:
            conds.append("person_id=?")
            args.append(person_id)
        if since_ts:
            # «новый диалог»: сообщения до отметки не попадают в контекст
            # (в долгой памяти/эпизодах они остаются)
            conds.append("ts>?")
            args.append(since_ts)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self.lock:
            rows = self._conn.execute(q, args).fetchall()
        return list(reversed(rows))

    # ---------- сжатие RAW -> EPISODES ----------
    def compress_raw(self, llm_chat_once):
        cutoff = time.time() - CFG.get("memory.raw_limit_hours", 4) * 3600
        with self.lock:
            rows = self._conn.execute(
                "SELECT id,ts,person_id,role,text FROM events "
                "WHERE compressed=0 AND ts<? ORDER BY id", (cutoff,)).fetchall()
        if len(rows) < 4:
            return
        by_person = {}
        for r in rows:
            by_person.setdefault(r[2], []).append(r)
        for person_id, events in by_person.items():
            dialog = "\n".join(f"{r[3]}: {r[4]}" for r in events)
            try:
                raw = llm_chat_once([
                    {"role": "user", "content": SUMMARIZE_PROMPT + dialog[:8000]}])
                data = _extract_json(raw)
                summary = data.get("summary", dialog[:300])
                emotion = data.get("emotion", "")
                salience = float(data.get("salience", 0.5))
                thread = str(data.get("thread") or "").strip()[:60]
            except Exception as e:
                log.warning("Суммаризация не удалась (%s), сохраняю обрезок", e)
                summary, emotion, salience = dialog[:300], "", 0.3
                thread = ""
            cat = self.person(person_id).get("category", "stranger")
            if cat == "stranger":
                summary = f"[случайный собеседник] {summary[:150]}"
                salience = min(salience, 0.3)
            with self.lock:
                cur = self._conn.execute(
                    "INSERT INTO episodes(ts_start,ts_end,person_id,summary,"
                    "emotion,salience,thread) VALUES(?,?,?,?,?,?,?)",
                    (events[0][1], events[-1][1], person_id, summary,
                     emotion, salience, thread))
                ep_id = cur.lastrowid
                self._conn.executemany(
                    "UPDATE events SET compressed=1 WHERE id=?",
                    [(r[0],) for r in events])
                self._conn.commit()
            col = self._collection()
            if col:
                try:
                    col.add(ids=[str(ep_id)], documents=[summary],
                            metadatas=[{"person_id": person_id,
                                        "salience": salience,
                                        "thread": thread or "разное"}])
                except Exception as e:
                    log.warning("Chroma add failed: %s", e)
        self._enforce_caps()

    # ---------- сжатие EPISODES -> CORE ----------
    def consolidate_core(self, llm_chat_once):
        with self.lock:
            persons = self._conn.execute(
                "SELECT id,core_json FROM persons WHERE category!='stranger'"
            ).fetchall()
        for person_id, core_json in persons:
            with self.lock:
                eps = self._conn.execute(
                    "SELECT id,summary,emotion FROM episodes "
                    "WHERE person_id=? AND consolidated=0 ORDER BY id",
                    (person_id,)).fetchall()
            if len(eps) < 3:
                continue
            ep_text = "\n".join(f"- {e[1]} (эмоция: {e[2]})" for e in eps)
            try:
                raw = llm_chat_once([{
                    "role": "user",
                    "content": CORE_PROMPT.replace("{current}", core_json)
                                          .replace("{episodes}", ep_text[:8000])}])
                data = _extract_json(raw)
                with self.lock:
                    self._conn.execute(
                        "UPDATE persons SET core_json=?,confidence=? WHERE id=?",
                        (json.dumps(data.get("core", {}), ensure_ascii=False),
                         float(data.get("confidence", 0.5)), person_id))
                    self._conn.executemany(
                        "UPDATE episodes SET consolidated=1 WHERE id=?",
                        [(e[0],) for e in eps])
                    self._conn.commit()
            except Exception as e:
                log.warning("Консолидация CORE для %s не удалась: %s", person_id, e)
        self._cleanup_strangers()

    # ---------- правила против переполнения ----------
    def _enforce_caps(self):
        cap = CFG.get("memory.episode_hard_cap", 10000)
        with self.lock:
            n = self._conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            if n > cap:
                # удаляем старые низкосалиентные, защищая owner/regular
                self._conn.execute("""
                    DELETE FROM episodes WHERE id IN (
                        SELECT e.id FROM episodes e
                        JOIN persons p ON p.id = e.person_id
                        WHERE p.category='stranger'
                        ORDER BY e.salience ASC, e.id ASC LIMIT ?)""",
                    (n - cap,))
                self._conn.commit()

    def _cleanup_strangers(self):
        ttl = CFG.get("memory.stranger_ttl_days", 30) * 86400
        cutoff = time.time() - ttl
        with self.lock:
            self._conn.execute("""
                DELETE FROM episodes WHERE person_id IN (
                    SELECT id FROM persons
                    WHERE category='stranger' AND last_seen<?)""", (cutoff,))
            self._conn.execute(
                "DELETE FROM persons WHERE category='stranger' AND last_seen<?",
                (cutoff,))
            self._conn.commit()

    # ---------- чтение для контекста ----------
    def person(self, person_id) -> dict:
        with self.lock:
            row = self._conn.execute(
                "SELECT id,name,category,core_json,confidence FROM persons "
                "WHERE id=?", (person_id,)).fetchone()
        if not row:
            return {"id": person_id, "category": "stranger", "core": {}}
        return {"id": row[0], "name": row[1], "category": row[2],
                "core": json.loads(row[3] or "{}"), "confidence": row[4]}

    def relevant_episodes(self, query, person_id, k=None):
        k = k or CFG.get("memory.rag_top_k", 5)
        col = self._collection()
        if col:
            try:
                res = col.query(query_texts=[query], n_results=k,
                                where={"person_id": person_id})
                return res.get("documents", [[]])[0]
            except Exception as e:
                log.warning("Chroma query failed: %s", e)
        # фоллбэк: последние эпизоды из SQLite
        with self.lock:
            rows = self._conn.execute(
                "SELECT summary FROM episodes WHERE person_id=? "
                "ORDER BY id DESC LIMIT ?", (person_id, k)).fetchall()
        return [r[0] for r in rows]

    # ---------- день и нити ----------
    # ЗАЧЕМ ЭТОТ СЛОЙ (2026-08-15, дословная просьба владельца): «я хочу
    # чтобы она могла за весь день болтовню держать от десятков людей и
    # могла вспоминать нити разговоров, а ближайшие 4 часа более хорошо в
    # подробностях».
    #
    # Слои уже были: RAW дословно, эпизоды по кускам, CORE про человека.
    # Не хватало ровно середины — «что было СЕГОДНЯ» и «о чём вообще шла
    # речь». Эпизод знает свой кусок времени и своего человека, но не
    # знает, что три эпизода за день — одна и та же тема. Отсюда нить:
    # короткое имя темы, которое суммаризатор ставит сам, одинаково для
    # разных дней. По нему потом можно поднять всю ветку разом.
    #
    # Дневная сводка складывается ИЗ ЭПИЗОДОВ, а не из сырья: сырьё за
    # день — это десятки тысяч символов, в промпт оно не поедет никогда.

    DAY_FMT = "%Y-%m-%d"

    def _day_bounds(self, date_str=None):
        import datetime as _dt
        d = (_dt.datetime.strptime(date_str, self.DAY_FMT).date()
             if date_str else _dt.date.today())
        start = _dt.datetime.combine(d, _dt.time.min).timestamp()
        return d.strftime(self.DAY_FMT), start, start + 86400

    def day_digest(self, date_str=None, rebuild=False) -> str:
        """Короткая сводка дня: кто приходил и о чём говорили.

        Кэшируется в таблице days: пересобирать её на каждую фразу — это
        лишний проход по базе там, где день меняется раз в полчаса.
        """
        key, t0, t1 = self._day_bounds(date_str)
        if not rebuild:
            with self.lock:
                row = self._conn.execute(
                    "SELECT digest,ts FROM days WHERE date=?", (key,)).fetchone()
            if row and row[0] and (time.time() - (row[1] or 0)
                                   < CFG.get("memory.day_cache_s", 900)):
                return row[0]
        with self.lock:
            eps = self._conn.execute(
                "SELECT person_id,summary,thread,salience FROM episodes "
                "WHERE ts_start>=? AND ts_start<? ORDER BY salience DESC, id",
                (t0, t1)).fetchall()
            live = self._conn.execute(
                "SELECT person_id,COUNT(*) FROM events "
                "WHERE ts>=? AND ts<? AND compressed=0 GROUP BY person_id",
                (t0, t1)).fetchall()
        if not eps and not live:
            return ""
        by_person = {}
        for pid, summary, thread, sal in eps:
            by_person.setdefault(pid, []).append((thread or "разное", summary))
        parts = []
        for pid, items in by_person.items():
            name = self.person(pid).get("name") or pid
            seen, lines = set(), []
            for thread, summary in items[:6]:
                if thread in seen:
                    continue
                seen.add(thread)
                lines.append("%s — %s" % (thread, (summary or "")[:160]))
            parts.append("%s: %s" % (name, "; ".join(lines)))
        for pid, n in live:
            name = self.person(pid).get("name") or pid
            parts.append("%s: ещё %d свежих реплик, они целиком в разговоре "
                         "выше" % (name, n))
        digest = " | ".join(parts)
        with self.lock:
            self._conn.execute(
                "INSERT INTO days(date,digest,threads,ts) VALUES(?,?,?,?) "
                "ON CONFLICT(date) DO UPDATE SET digest=excluded.digest,"
                "threads=excluded.threads,ts=excluded.ts",
                (key, digest,
                 json.dumps(sorted({t for _p, _s, t, _x in eps if t}),
                            ensure_ascii=False),
                 time.time()))
            self._conn.commit()
        return digest

    def threads(self, days: int = 7, limit: int = 12) -> list:
        """Нити за последние дни: [(имя, сколько эпизодов, когда трогали)]."""
        since = time.time() - days * 86400
        with self.lock:
            rows = self._conn.execute(
                "SELECT thread,COUNT(*),MAX(ts_end) FROM episodes "
                "WHERE thread IS NOT NULL AND thread!='' AND thread!='разное' "
                "AND ts_end>=? GROUP BY thread ORDER BY MAX(ts_end) DESC "
                "LIMIT ?", (since, limit)).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def thread_recall(self, name: str, limit: int = 12) -> list:
        """Поднять нить целиком — по имени, а если не совпало точно, то по
        похожести (человек назовёт её своими словами, не нашими)."""
        name = (name or "").strip()
        if not name:
            return []
        with self.lock:
            rows = self._conn.execute(
                "SELECT summary,ts_start FROM episodes WHERE thread=? "
                "ORDER BY id DESC LIMIT ?", (name, limit)).fetchall()
            if not rows:
                rows = self._conn.execute(
                    "SELECT summary,ts_start FROM episodes "
                    "WHERE thread LIKE ? OR summary LIKE ? "
                    "ORDER BY id DESC LIMIT ?",
                    ("%" + name + "%", "%" + name + "%", limit)).fetchall()
        return [(r[0], r[1]) for r in rows]

    def build_context(self, person_id, query, limit_chars: int = 0) -> str:
        """CORE-образ + релевантные эпизоды. RAW добавляет main как историю чата.

        limit_chars (2026-07-26) — потолок в символах. До него потолка не
        было вообще, и этот кусок рос вместе с памятью: у владельца он
        разросся так, что промпт распух до 16 тысяч символов, а платить за
        это приходилось КАЖДЫМ ходом — в облаке кэша префикса нет, провайдер
        жуёт всё заново. Режем самый разговорчивый источник (эпизоды),
        образ собеседника бережём: он короткий и важный.
        """
        limit = int(limit_chars or CFG.get("memory.context_chars", 3000) or 0)
        parts = []
        p = self.person(person_id)
        core = ""
        if p.get("core"):
            core = ("Образ собеседника (" + p.get("name", person_id) + "): "
                    + json.dumps(p["core"], ensure_ascii=False))
            # даже образ бывает раздутым — оставляем ему не больше половины
            if limit and len(core) > limit // 2:
                core = core[:limit // 2].rstrip() + "…"
            parts.append(core)
        # СЕГОДНЯШНИЙ ДЕНЬ ОТДЕЛЬНОЙ СТРОКОЙ. Раньше в промпт ехали только
        # «релевантные эпизоды» — то есть похожие на текущий вопрос. На
        # вопрос «что мы сегодня делали» похожего не находилось ничего, и
        # она честно не помнила день, который сама же и прожила.
        day_room = int(CFG.get("memory.day_chars", 700))
        if limit and day_room > limit // 3:
            day_room = limit // 3
        try:
            day = self.day_digest()
        except Exception as e:
            log.debug("сводка дня пропущена: %s", e)
            day = ""
        if day and day_room > 60:
            parts.append("Сегодня уже было: " + day[:day_room])
        try:
            th = [t for t, _n, _ts in self.threads()][:6]
        except Exception:
            th = []
        if th:
            parts.append("Открытые нити (могу поднять любую целиком, "
                         "спроси): " + ", ".join(th))
        eps = self.relevant_episodes(query, person_id)
        if eps:
            room = (limit - sum(len(x) for x in parts) - 24) if limit else 0
            keep = []
            for e in eps:
                line = "- " + e
                if room:
                    if len(line) + 1 > room:
                        break        # лучше меньше эпизодов, чем обрубок
                    room -= len(line) + 1
                keep.append(line)
            if keep:
                parts.append("Из прошлых разговоров:\n" + "\n".join(keep))
        return "\n".join(parts)

    def stats(self):
        with self.lock:
            ev = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            ep = self._conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            pe = self._conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0]
        return {"events": ev, "episodes": ep, "persons": pe}


def _extract_json(text: str) -> dict:
    """LLM любят оборачивать JSON в болтовню — вырезаем первый {...}."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("нет JSON в ответе")
    return json.loads(text[start:end + 1])


def start_scheduler(memory: Memory, llm_chat_once):
    """APScheduler: RAW->EPISODES каждые N минут, EPISODES->CORE раз в неделю."""
    from apscheduler.schedulers.background import BackgroundScheduler

    sched = BackgroundScheduler(daemon=True)
    sched.add_job(lambda: memory.compress_raw(llm_chat_once), "interval",
                  minutes=CFG.get("memory.compress_raw_every_min", 30),
                  id="raw2episodes")
    sched.add_job(lambda: memory.consolidate_core(llm_chat_once), "interval",
                  days=CFG.get("memory.core_update_every_days", 7),
                  id="episodes2core",
                  next_run_time=datetime.now())
    sched.start()
    return sched
