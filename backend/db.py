import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

def now():
    return datetime.now(timezone.utc).isoformat()

def uid(prefix):
    return f"{prefix}-{uuid4().hex}"

def dumps(value):
    return json.dumps(value, ensure_ascii=False)

class Database:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS customers(id TEXT PRIMARY KEY, mobile TEXT UNIQUE NOT NULL);
              CREATE TABLE IF NOT EXISTS tokens(hash TEXT PRIMARY KEY, customer TEXT NOT NULL, expires REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS otps(mobile TEXT PRIMARY KEY, hash TEXT NOT NULL, expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS records(kind TEXT NOT NULL, id TEXT NOT NULL, owner TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(kind,id));
              CREATE INDEX IF NOT EXISTS records_owner ON records(kind,owner);
              CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, owner TEXT NOT NULL, step TEXT NOT NULL, channel TEXT NOT NULL, at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, order_id TEXT NOT NULL, path TEXT NOT NULL, body TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS turns(event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, request_hash TEXT NOT NULL, response TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

def put(db, kind, id, owner, body):
    db.execute('INSERT INTO records VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body', (kind, id, owner, dumps(body)))
    return body

def get(db, kind, id, owner=None):
    row = db.execute('SELECT owner,body FROM records WHERE kind=? AND id=?', (kind, id)).fetchone()
    if not row or (owner is not None and row['owner'] != owner):
        from fastapi import HTTPException
        raise HTTPException(404, 'Record not found')
    return json.loads(row['body'])

def listing(db, kind, owner):
    return [json.loads(r['body']) for r in db.execute('SELECT body FROM records WHERE kind=? AND owner=? ORDER BY rowid DESC', (kind, owner))]

def log(db, owner, step, channel='web'):
    db.execute('INSERT INTO events VALUES(?,?,?,?,?)', (uid('EV'), owner, step, channel, now()))
