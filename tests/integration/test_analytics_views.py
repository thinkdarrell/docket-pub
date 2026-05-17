"""Integration tests for db/umami_views.sql against a live Umami v3 schema.

Loads tests/fixtures/umami_schema_v3.sql into a throwaway Postgres database,
applies db/umami_views.sql, inserts hand-crafted rows, and asserts each view
aggregates correctly.

Run with:
    DATABASE_URL=postgresql://docket@localhost:5432/docket_db \
        venv/bin/pytest tests/integration/test_analytics_views.py -v
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2 as psycopg
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "umami_schema_v3.sql"
VIEWS = REPO_ROOT / "db" / "umami_views.sql"


# ---------------------------------------------------------------------------
# Infrastructure helpers
# ---------------------------------------------------------------------------

def _psql_path() -> str:
    """Return the first usable psql binary on the host.

    Prefers the pg18 homebrew path (matches Railway's PG 18) but falls back to
    the pg16 homebrew path and then bare 'psql' on PATH.
    """
    candidates = [
        "/opt/homebrew/opt/postgresql@18/bin/psql",
        "/opt/homebrew/opt/postgresql@16/bin/psql",
        "psql",
    ]
    for candidate in candidates:
        try:
            subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                check=True,
            )
            return candidate
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    pytest.skip("psql not available — install postgresql client tools")


@pytest.fixture(scope="module")
def umami_db():
    """Create a fresh throwaway DB, load Umami v3 schema + views, yield DSN.

    Scope is *module* so the six tests share one DB setup / teardown cycle and
    don't pay the fixture cost six times.  Each test uses a separate connection
    and rolls back so they stay independent of each other's inserts.
    """
    base_url = os.environ.get("DATABASE_URL")
    if not base_url:
        pytest.skip("DATABASE_URL not set — set it to your local postgres dev DB")

    psql = _psql_path()
    test_db = f"docket_test_umami_{os.getpid()}_{uuid.uuid4().hex[:8]}"

    # --- Create throwaway database ---
    admin = psycopg.connect(base_url)
    admin.set_session(autocommit=True)
    try:
        with admin.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{test_db}"')
            cur.execute(f'CREATE DATABASE "{test_db}"')
    finally:
        admin.close()

    # Derive DSN for the new DB by swapping out the dbname segment.
    test_dsn = base_url.rsplit("/", 1)[0] + "/" + test_db

    try:
        # --- Load Umami v3 schema fixture ---
        # The fixture was pg_dump'd from PG 18.  Two PG 18-only statements are
        # stripped before loading so the fixture is portable to PG 16:
        #
        #   SET transaction_timeout = 0   — added in PG 17; PG 16 rejects it.
        #   \restrict / \unrestrict       — pg_dump 18 metacommands; unknown to PG 16
        #                                   psql but only produce warnings, not errors,
        #                                   so they are kept as-is (harmless).
        _PG18_ONLY = {
            "SET transaction_timeout",
        }
        fixture_sql = "\n".join(
            ln
            for ln in FIXTURE.read_text().splitlines()
            if not any(ln.strip().startswith(tok) for tok in _PG18_ONLY)
        )
        try:
            subprocess.run(
                [psql, test_dsn, "-v", "ON_ERROR_STOP=1", "-q"],
                input=fixture_sql,
                text=True,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"psql fixture load failed:\n{e.stderr}") from e

        # --- Apply views, stripping GRANT blocks (umami_reader role doesn't exist locally) ---
        # The GRANT section in umami_views.sql is multi-line:
        #   GRANT USAGE ON SCHEMA public TO umami_reader;
        #   GRANT SELECT ON
        #     v_pageviews_daily,
        #     ...
        #   TO umami_reader;
        # A simple per-line filter leaves the view-name lines as orphaned SQL, so
        # we use a small state machine: skip from any GRANT line until the next
        # semicolon (inclusive).
        views_lines = VIEWS.read_text().splitlines()
        filtered: list[str] = []
        in_grant = False
        for ln in views_lines:
            stripped = ln.strip()
            if in_grant:
                if stripped.endswith(";"):
                    in_grant = False  # end of GRANT block — drop this line too
                # else: interior of GRANT block — drop
            elif stripped.upper().startswith("GRANT"):
                in_grant = True
                if stripped.endswith(";"):
                    in_grant = False  # single-line GRANT — drop and done
                # else: multi-line GRANT starts here — stay in_grant
            else:
                filtered.append(ln)
        views_sql = "\n".join(filtered)
        try:
            subprocess.run(
                [psql, test_dsn, "-v", "ON_ERROR_STOP=1", "-q"],
                input=views_sql,
                text=True,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"psql views load failed:\n{e.stderr}") from e

        yield test_dsn

    finally:
        # --- Teardown — always runs even if fixture/views load raised ---
        admin = psycopg.connect(base_url)
        admin.set_session(autocommit=True)
        try:
            with admin.cursor() as cur:
                cur.execute(f'DROP DATABASE IF EXISTS "{test_db}"')
        finally:
            admin.close()


# ---------------------------------------------------------------------------
# Per-test connection fixture (rolls back after each test)
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(umami_db):
    """Open a connection to the throwaway DB, roll back after the test."""
    c = psycopg.connect(umami_db)
    yield c
    try:
        c.rollback()
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------

def _insert_session(
    conn,
    *,
    session_id,
    country=None,
    region=None,
    city=None,
) -> None:
    """Insert a row in the `session` table.

    Required before any website_event can reference this session_id because the
    schema defines session_id as NOT NULL with no default (Prisma requires it).
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO session "
            "(session_id, website_id, created_at, country, region, city) "
            "VALUES (%s, gen_random_uuid(), NOW(), %s, %s, %s)",
            (str(session_id), country, region, city),
        )


def _insert_pageview(
    conn,
    *,
    day_offset: int = 0,
    path: str,
    session_id=None,
    referrer_domain: str | None = None,
) -> None:
    """Insert a pageview (event_type=1) into website_event.

    If session_id is provided the caller must have already inserted a session
    row for it.  If omitted, a new random session is auto-created.
    """
    ts = datetime.now(timezone.utc) - timedelta(days=day_offset)
    sid = session_id if session_id is not None else uuid.uuid4()
    if session_id is None:
        _insert_session(conn, session_id=sid)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO website_event "
            "(event_id, website_id, session_id, visit_id, created_at, "
            " url_path, event_type, referrer_domain) "
            "VALUES (gen_random_uuid(), gen_random_uuid(), %s, gen_random_uuid(), "
            "        %s, %s, 1, %s)",
            (str(sid), ts, path, referrer_domain),
        )


def _insert_custom_event(
    conn,
    *,
    day_offset: int = 0,
    event_name: str,
    props: dict,
) -> None:
    """Insert a custom event (event_type=2) + one event_data row per prop.

    data_type=1 is Umami's integer code for string values (verified against
    the v3 schema — event_data.data_type is unconstrained integer, Umami uses
    1=string, 2=number, 3=boolean, 4=date, 5=array, 6=object).
    """
    ts = datetime.now(timezone.utc) - timedelta(days=day_offset)
    event_id = uuid.uuid4()
    sid = uuid.uuid4()
    website_id = uuid.uuid4()
    _insert_session(conn, session_id=sid)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO website_event "
            "(event_id, website_id, session_id, visit_id, created_at, "
            " url_path, event_type, event_name) "
            "VALUES (%s, %s, %s, gen_random_uuid(), %s, '/', 2, %s)",
            (str(event_id), str(website_id), str(sid), ts, event_name),
        )
        for k, v in props.items():
            cur.execute(
                "INSERT INTO event_data "
                "(event_data_id, website_event_id, website_id, "
                " data_key, string_value, data_type) "
                "VALUES (gen_random_uuid(), %s, %s, %s, %s, 1)",
                (str(event_id), str(website_id), k, str(v)),
            )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_v_pageviews_daily_normalizes_meeting_ids(conn):
    """Meeting paths like /meetings/123 and /meetings/456 collapse to /meetings/[id].

    Item paths like /items/999 collapse separately to /items/[id].
    """
    _insert_pageview(conn, path="/al/birmingham/meetings/123")
    _insert_pageview(conn, path="/al/birmingham/meetings/456")
    _insert_pageview(conn, path="/al/birmingham/items/999")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT normalized_path, pageviews "
            "FROM v_pageviews_daily "
            "ORDER BY normalized_path"
        )
        rows = {row[0]: row[1] for row in cur.fetchall()}

    assert rows.get("/al/birmingham/meetings/[id]") == 2, (
        f"Expected meetings/[id]=2, got {rows}"
    )
    assert rows.get("/al/birmingham/items/[id]") == 1, (
        f"Expected items/[id]=1, got {rows}"
    )
    # The two distinct meeting IDs must NOT appear as separate rows.
    assert "/al/birmingham/meetings/123" not in rows
    assert "/al/birmingham/meetings/456" not in rows


def test_v_pageviews_daily_preserves_city_and_badge_slugs(conn):
    """City-level and badge-slug paths must NOT be collapsed — they are kept as-is."""
    _insert_pageview(conn, path="/al/birmingham/")
    _insert_pageview(conn, path="/al/birmingham/blight/")
    _insert_pageview(conn, path="/al/mobile/zoning/")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT normalized_path FROM v_pageviews_daily ORDER BY normalized_path"
        )
        paths = {row[0] for row in cur.fetchall()}

    assert "/al/birmingham/" in paths, f"City path missing from {paths}"
    assert "/al/birmingham/blight/" in paths, f"Blight slug missing from {paths}"
    assert "/al/mobile/zoning/" in paths, f"Zoning slug missing from {paths}"


def test_v_event_counts_daily_aggregates_by_name(conn):
    """Two outbound_source_click events + one search_submit → correct event_count per name."""
    _insert_custom_event(conn, event_name="outbound_source_click", props={"source_type": "granicus_video"})
    _insert_custom_event(conn, event_name="outbound_source_click", props={"source_type": "minutes_pdf"})
    _insert_custom_event(conn, event_name="search_submit", props={"query": "blight"})

    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_name, event_count "   # column is event_count, not count
            "FROM v_event_counts_daily "
            "ORDER BY event_name"
        )
        rows = {row[0]: row[1] for row in cur.fetchall()}

    assert rows.get("outbound_source_click") == 2, (
        f"Expected outbound_source_click=2, got {rows}"
    )
    assert rows.get("search_submit") == 1, (
        f"Expected search_submit=1, got {rows}"
    )


def test_v_event_props_daily_breaks_down_property_values(conn):
    """v_event_props_daily must group by (event_name, prop_key, prop_value)."""
    _insert_custom_event(
        conn,
        event_name="outbound_source_click",
        props={"source_type": "granicus_video"},
    )
    _insert_custom_event(
        conn,
        event_name="outbound_source_click",
        props={"source_type": "granicus_video"},
    )
    _insert_custom_event(
        conn,
        event_name="outbound_source_click",
        props={"source_type": "minutes_pdf"},
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT prop_key, prop_value, event_count "
            "FROM v_event_props_daily "
            "WHERE event_name = 'outbound_source_click' "
            "ORDER BY prop_value"
        )
        rows = {row[1]: row[2] for row in cur.fetchall()}

    assert rows.get("granicus_video") == 2, (
        f"Expected granicus_video=2, got {rows}"
    )
    assert rows.get("minutes_pdf") == 1, (
        f"Expected minutes_pdf=1, got {rows}"
    )


def test_v_referrers_daily_filters_null_referrers(conn):
    """NULL referrer_domain rows must be excluded from v_referrers_daily."""
    _insert_pageview(conn, path="/al/birmingham/", referrer_domain="hacker-news.firebaseapp.com")
    _insert_pageview(conn, path="/al/birmingham/", referrer_domain="hacker-news.firebaseapp.com")
    _insert_pageview(conn, path="/al/birmingham/", referrer_domain="google.com")
    _insert_pageview(conn, path="/al/birmingham/", referrer_domain=None)  # must be excluded

    with conn.cursor() as cur:
        cur.execute(
            "SELECT referrer_domain, pageviews "
            "FROM v_referrers_daily "
            "ORDER BY referrer_domain"
        )
        rows = {row[0]: row[1] for row in cur.fetchall()}

    assert rows.get("hacker-news.firebaseapp.com") == 2, (
        f"Expected hacker-news=2, got {rows}"
    )
    assert rows.get("google.com") == 1, (
        f"Expected google.com=1, got {rows}"
    )
    # NULL must not appear (the view WHERE clause filters it out).
    assert None not in rows, f"NULL referrer leaked into view: {rows}"
    # Exactly two distinct domains expected.
    assert len(rows) == 2, f"Expected 2 referrer rows, got {rows}"


def test_v_geo_daily_joins_session(conn):
    """v_geo_daily must JOIN website_event → session and aggregate geo correctly."""
    sid = uuid.uuid4()
    _insert_session(conn, session_id=sid, country="US", region="AL", city="Birmingham")

    # Three pageviews all referencing the same session.
    _insert_pageview(conn, path="/al/birmingham/", session_id=sid)
    _insert_pageview(conn, path="/al/birmingham/meetings/1", session_id=sid)
    _insert_pageview(conn, path="/al/birmingham/meetings/2", session_id=sid)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT country, region, city, pageviews, sessions "
            "FROM v_geo_daily "
            "WHERE country = 'US' AND city = 'Birmingham'"
        )
        rows = cur.fetchall()

    assert len(rows) == 1, f"Expected 1 geo row, got {rows}"
    country, region, city, pageviews, sessions = rows[0]
    # session.country is char(2) — may have trailing space padding; strip it.
    assert country.strip() == "US", f"country mismatch: {country!r}"
    assert region == "AL", f"region mismatch: {region!r}"
    assert city == "Birmingham", f"city mismatch: {city!r}"
    assert pageviews == 3, f"Expected 3 pageviews, got {pageviews}"
    assert sessions == 1, f"Expected 1 session, got {sessions}"
