"""
Central SQLite access for the whole app.

Everything the app used to keep as separate JSON/CSV files (forms,
responses, the sentiment cache, the "active form" pointer) now lives in
one SQLite database file, so a single Render persistent disk is enough
to keep all of it alive across restarts and redeploys.

IMPORTANT (Render specific): SQLite is still just a file on disk. On
Render, a web service's local disk is EPHEMERAL unless you attach a
Persistent Disk and point DATABASE_PATH at a path inside it. Without a
persistent disk, this file is recreated empty every time the service
redeploys or restarts, exactly like the old JSON/CSV files were. See
config.py / the deployment notes for how to set DATABASE_PATH.
"""
import os
import sqlite3
from contextlib import contextmanager

from config import Config

SCHEMA = """
CREATE TABLE IF NOT EXISTS forms (
    form_id       TEXT PRIMARY KEY,
    topic         TEXT NOT NULL,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    questions_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS responses (
    response_id      TEXT PRIMARY KEY,
    form_id          TEXT NOT NULL REFERENCES forms(form_id),
    submitted_at     TEXT NOT NULL,
    respondent_token TEXT,
    answers_json     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_responses_form_id ON responses(form_id);

-- One respondent (identified by a token stored in their browser cookie)
-- may submit a given form only once. respondent_token is nullable
-- (older rows / tokens can't always be determined), so the uniqueness
-- is enforced by a partial unique index that only applies to non-null
-- tokens.
CREATE UNIQUE INDEX IF NOT EXISTS idx_responses_form_respondent
    ON responses(form_id, respondent_token)
    WHERE respondent_token IS NOT NULL;

CREATE TABLE IF NOT EXISTS sentiment_cache (
    response_id TEXT PRIMARY KEY REFERENCES responses(response_id),
    form_id     TEXT NOT NULL,
    sentiment   TEXT,
    score       REAL,
    summary     TEXT,
    keywords    TEXT
);
CREATE INDEX IF NOT EXISTS idx_sentiment_cache_form_id ON sentiment_cache(form_id);

-- Small generic key/value table. Currently used only to remember the
-- "active" form id, but kept generic in case something else needs it.
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def get_connection() -> sqlite3.Connection:
    Config.ensure_dirs()
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    # WAL mode plays nicer with gunicorn's multiple worker processes than
    # the default rollback journal (fewer "database is locked" errors).
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist yet. Safe to call on every boot."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def db_cursor():
    """
    Context manager yielding a cursor; commits on success, rolls back and
    re-raises on error, always closes the connection.

        with db_cursor() as cur:
            cur.execute("INSERT INTO ...", (...,))
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
