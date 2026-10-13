"""Persistent PostgreSQL in production; SQLite for local tests and development."""
import contextlib
import sqlite3
from . import config

def is_postgres():
    return bool(config.DATABASE_URL)

def _convert(sql):
    if sql.lstrip().upper().startswith("INSERT OR IGNORE INTO "):
        sql = sql.replace("INSERT OR IGNORE INTO ", "INSERT INTO ", 1) + " ON CONFLICT DO NOTHING"
    return sql.replace("?", "%s")

class PGConnection:
    def __init__(self, raw):
        self.raw = raw
    def execute(self, sql, params=()):
        return self.raw.execute(_convert(sql), tuple(params))
    def close(self):
        self.raw.close()

def connect():
    if is_postgres():
        import psycopg
        from psycopg.rows import dict_row
        raw = psycopg.connect(
            config.DATABASE_URL,
            row_factory=dict_row,
            autocommit=True,
            connect_timeout=8,
            options="-c search_path=" + config.DATABASE_SCHEMA,
        )
        # Set up an isolated application schema on new Neon databases.
        from psycopg import sql as pgsql
        raw.execute(pgsql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(pgsql.Identifier(config.DATABASE_SCHEMA)))
        return PGConnection(raw)
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
            sql = path.read_text(encoding="utf-8")
            if is_postgres():
                with db.raw.transaction():
                    db.execute("SELECT pg_advisory_xact_lock(7200131726)")
                    if db.execute("SELECT 1 FROM schema_migrations WHERE version=?", (version,)).fetchone():
                        continue
                    for statement in sql.split(";"):
                        statement = statement.strip()
                        if statement:
                            db.execute(statement.replace("datetime('now')", "now()::text"))
                    db.execute("INSERT INTO schema_migrations(version,applied_at) VALUES (?,?)", (version, "applied"))
            else:
                db.executescript(sql)
                db.execute("INSERT INTO schema_migrations(version,applied_at) VALUES (?,datetime('now'))", (version,))
        if is_postgres():
            with db.raw.transaction():
                db.execute("CREATE TABLE IF NOT EXISTS media_blobs (media_id TEXT PRIMARY KEY REFERENCES media(id) ON DELETE CASCADE, data BYTEA NOT NULL)")

@contextlib.contextmanager
def transaction(immediate=False):
    with contextlib.closing(connect()) as db:
        if is_postgres():
            with db.raw.transaction():
                if immediate:
                    # Serialize capacity checks, founder approvals, and other critical writes.
                    db.execute("SELECT pg_advisory_xact_lock(7200131727)")
                yield db
        else:
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
