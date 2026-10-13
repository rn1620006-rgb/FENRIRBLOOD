import contextlib
import sqlite3
from pathlib import Path
from . import config


def connect():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(config.DB_PATH, timeout=12, isolation_level=None, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=12000")
    db.execute("PRAGMA journal_mode=WAL")
    return db


def initialize():
    with contextlib.closing(connect()) as db:
        db.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        for path in sorted((config.ROOT / "migrations").glob("*.sql")):
            version = path.name.split("_")[0]
            if db.execute("SELECT 1 FROM schema_migrations WHERE version=?", (version,)).fetchone():
                continue
            db.executescript(path.read_text(encoding="utf-8"))
            db.execute("INSERT INTO schema_migrations(version,applied_at) VALUES (?,datetime('now'))", (version,))


@contextlib.contextmanager
def transaction(immediate=False):
    with contextlib.closing(connect()) as db:
        db.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield db
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise


def rows(sql, values=()):
    with contextlib.closing(connect()) as db:
        return [dict(x) for x in db.execute(sql, values).fetchall()]


def one(sql, values=()):
    with contextlib.closing(connect()) as db:
        row = db.execute(sql, values).fetchone()
        return dict(row) if row else None
