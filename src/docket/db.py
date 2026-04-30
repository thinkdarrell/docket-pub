"""Single source of truth for opening PostgreSQL connections.

Use this context manager instead of calling psycopg2.connect directly:

    from docket.db import db

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

from docket.config import DATABASE_URL


@contextmanager
def db() -> Iterator[psycopg2.extensions.connection]:
    """Yield a configured PostgreSQL connection; commit on success, rollback on error."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def db_cursor() -> Iterator[psycopg2.extras.RealDictCursor]:
    """Yield a RealDictCursor that returns rows as dicts. Auto-commits."""
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
