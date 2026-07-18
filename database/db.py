"""PostgreSQL connection helpers (psycopg 3 + pgvector)."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

import config


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """Yield a connection with pgvector registered and dict rows."""
    conn = psycopg.connect(config.db_dsn(), row_factory=dict_row)
    try:
        register_vector(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema() -> None:
    """Run schema.sql to create all tables."""
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    sql = schema_path.read_text()
    # pgvector must be registered AFTER the extension exists; create it first on a raw conn.
    raw = psycopg.connect(config.db_dsn())
    try:
        with raw.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        raw.commit()
        register_vector(raw)
        with raw.cursor() as cur:
            cur.execute(sql)
        raw.commit()
    finally:
        raw.close()


def ping() -> bool:
    """Return True if the database is reachable and pgvector is installed."""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector';")
            row = cur.fetchone()
            return row is not None
    except Exception:
        return False
