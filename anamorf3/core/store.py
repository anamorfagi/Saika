"""Durable sessions, turn boundaries, tasks and event cursor. No live CFG."""
from __future__ import annotations
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

class Store:
    def __init__(self, path):
        self.path = str(Path(path).resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions(
                    id TEXT PRIMARY KEY, root TEXT NOT NULL, title TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks(
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    state TEXT NOT NULL, input TEXT NOT NULL, mode TEXT NOT NULL,
                    output TEXT NOT NULL DEFAULT '', checkpoint TEXT NOT NULL DEFAULT '{}',
                    detail TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS turns(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL UNIQUE, messages TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, type TEXT NOT NULL,
                    source TEXT NOT NULL, data TEXT NOT NULL, ts REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS events_task ON events(task_id,seq);
                CREATE INDEX IF NOT EXISTS turns_session ON turns(session_id,seq);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db: yield db
        finally: db.close()

    def session(self, root, title=''):
        root = Path(root).resolve(strict=True)
        if not root.is_dir(): raise ValueError('project root must be a directory')
        sid = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (sid,str(root),title or root.name,time.time()))
        return self.get_session(sid)

    def get_session(self, sid):
        with self.connect() as db: row = db.execute('SELECT * FROM sessions WHERE id=?',(sid,)).fetchone()
        if row is None: raise KeyError(sid)
        return dict(row)

    def create_task(self, sid, text, mode='auto'):
        self.get_session(sid)
        if mode not in ('auto','local','cloud'): raise ValueError('unknown mode')
        if not isinstance(text,str) or not text.strip(): raise ValueError('empty task')
        if len(text)>100_000: raise ValueError('input too large')
        tid, now = uuid.uuid4().hex, time.time()
        with self.connect() as db:
            db.execute('INSERT INTO tasks(id,session_id,state,input,mode,created,updated) VALUES(?,?,?,?,?,?,?)',
                       (tid,sid,'queued',text,mode,now,now))
        return self.task(tid)

    def task(self, tid):
        with self.connect() as db: row=db.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
        if row is None: raise KeyError(tid)
        result=dict(row); result['checkpoint']=json.loads(result['checkpoint']); return result

    def update(self, tid, **values):
        if not values or not set(values)<= {'state','output','checkpoint','detail'}: raise ValueError('invalid update')
        if 'checkpoint' in values: values['checkpoint']=encode(values['checkpoint'])
        values['updated']=time.time()
        with self.connect() as db:
            db.execute('UPDATE tasks SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),tid))

    def append_turn(self, sid, tid, messages):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO turns(session_id,task_id,messages,created) VALUES(?,?,?,?)',
                       (sid,tid,encode(messages),time.time()))

    def history(self, sid, max_chars=48_000):
        # Bound complete turns; never orphan an assistant tool_call or result.
        out=[]; size=0
        with self.connect() as db:
            rows=db.execute('SELECT messages FROM turns WHERE session_id=? ORDER BY seq DESC LIMIT 100',(sid,)).fetchall()
        for row in rows:
            block=row['messages']
            if size+len(block)>max_chars: break
            out.insert(0,json.loads(block)); size+=len(block)
        return [m for turn in out for m in turn]

    def record_event(self, ev):
        with self.connect() as db:
            db.execute('INSERT INTO events(task_id,type,source,data,ts) VALUES(?,?,?,?,?)',
                       (ev.task_id,ev.type,ev.source,encode(ev.data),ev.ts))

    def events(self, after=0, task_id=None, limit=200):
        limit=max(1,min(int(limit),1000))
        with self.connect() as db:
            if task_id:
                rows=db.execute('SELECT * FROM events WHERE seq>? AND task_id=? ORDER BY seq LIMIT ?',
                                (after,task_id,limit)).fetchall()
            else: rows=db.execute('SELECT * FROM events WHERE seq>? ORDER BY seq LIMIT ?',(after,limit)).fetchall()
        return [dict(r, data=json.loads(r['data'])) for r in rows]

    def interrupt_stale(self):
        # Called only by the owner at cold start, never by a second observer.
        with self.connect() as db:
            ids=[r[0] for r in db.execute("SELECT id FROM tasks WHERE state='running'")]
            db.execute("UPDATE tasks SET state='failed',detail='process interrupted; actions must be inspected',updated=? WHERE state='running'",(time.time(),))
        return ids
