"""SQLite: veriler `veri/kongre.db` içinde (KONGRE_VERI ortam değişkeniyle değiştirilebilir)."""
import json
import os
import sqlite3
import threading
from pathlib import Path

DATA_DIR = Path(os.environ.get("KONGRE_VERI", Path(__file__).resolve().parent.parent / "veri"))
DB_PATH = DATA_DIR / "kongre.db"
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS congress_docs (
    id TEXT PRIMARY KEY,          -- 'H' + Clerk DocID, 'W' + OGE rapor özeti
    chamber TEXT, member TEXT, party TEXT, state_dst TEXT, filed TEXT, url TEXT,
    electronic INTEGER, n_tx INTEGER, error TEXT
);
CREATE TABLE IF NOT EXISTS congress_tx (
    id TEXT PRIMARY KEY,          -- rapor id + satır no
    doc_id TEXT, chamber TEXT, member TEXT, party TEXT, state_dst TEXT, filed TEXT, tx_date TEXT, notified TEXT,
    owner TEXT, asset TEXT, asset_type TEXT, ticker TEXT, type TEXT, partial INTEGER,
    amount TEXT, amt_lo REAL, amt_hi REAL, url TEXT
);
CREATE INDEX IF NOT EXISTS ix_congress_ticker ON congress_tx(ticker);
CREATE INDEX IF NOT EXISTS ix_congress_filed ON congress_tx(filed);
CREATE TABLE IF NOT EXISTS name_map (name TEXT PRIMARY KEY, ticker TEXT);
CREATE TABLE IF NOT EXISTS price_hist (ticker TEXT PRIMARY KEY, dates TEXT, closes TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def conn():
    c = getattr(_local, "conn", None)
    if c is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        _local.conn = c
    return c


def init():
    conn().executescript(SCHEMA)
    conn().commit()


def query(sql, args=()):
    return [dict(r) for r in conn().execute(sql, args).fetchall()]


def execute(sql, args=()):
    conn().execute(sql, args)
    conn().commit()


def executemany(sql, rows):
    conn().executemany(sql, rows)
    conn().commit()


def get_meta(key, default=None):
    r = conn().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(r[0]) if r else default


def set_meta(key, value):
    execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, json.dumps(value)))
