"""Smoke test: confirms the SQL predicate parses against a real database.
We aren't testing rows here — only that Postgres accepts the SQL we generate."""

import os

import pytest


pytestmark = pytest.mark.skipif(
    "railway.internal" in os.environ.get("DATABASE_URL", ""),
    reason="Skip when DATABASE_URL points at Railway VPC (test wants laptop/CI DB).",
)


def test_upcoming_predicate_compiles_against_real_db():
    """The predicate is a literal SQL fragment — confirm Postgres parses it
    without yelling about types or syntax. We don't care about the result
    set, only that EXPLAIN succeeds."""
    from docket.db import db_cursor
    from docket.services.meeting_time import UPCOMING_PREDICATE_SQL

    with db_cursor() as cur:
        cur.execute(
            f"EXPLAIN SELECT 1 FROM meetings WHERE {UPCOMING_PREDICATE_SQL}"
        )
        plan = cur.fetchall()
        assert plan
