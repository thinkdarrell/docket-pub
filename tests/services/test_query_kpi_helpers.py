"""Unit tests for P3 KPI + freshness query helpers."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from docket.services import query


BHM_ID = 1  # Birmingham — first municipality, stable across local + Railway.


def test_count_meetings_ytd_returns_int():
    n = query.count_meetings_ytd(BHM_ID)
    assert isinstance(n, int)
    assert n >= 0


def test_count_meetings_ytd_matches_raw_sql():
    n = query.count_meetings_ytd(BHM_ID)
    from docket.db import db_cursor
    with db_cursor() as cur:
        cur.execute("""
            SELECT count(*) AS n FROM meetings
            WHERE municipality_id = %s
              AND meeting_date >= date_trunc('year', now())::date
        """, (BHM_ID,))
        expected = cur.fetchone()["n"]
    assert n == expected


def test_sum_dollars_ytd_returns_decimal():
    total = query.sum_dollars_ytd(BHM_ID)
    assert isinstance(total, Decimal)
    assert total >= 0


def test_count_contested_votes_ytd_uses_nays_aggregate():
    """count_contested_votes_ytd matches list_contested_votes' definition
    (votes.nays > 0), scoped to YTD."""
    n = query.count_contested_votes_ytd(BHM_ID)
    from docket.db import db_cursor
    with db_cursor() as cur:
        cur.execute("""
            SELECT count(*) AS n FROM votes v
            JOIN meetings m ON m.id = v.meeting_id
            WHERE m.municipality_id = %s
              AND m.meeting_date >= date_trunc('year', now())::date
              AND v.nays > 0
        """, (BHM_ID,))
        expected = cur.fetchone()["n"]
    assert n == expected


def test_most_recent_ingest_at_returns_datetime_or_none():
    """Returns a datetime when meetings exist, None when they don't.

    Local test DB may have no meetings for BHM (id=1); Railway has many.
    The function must never error, and the return type must be datetime|None.
    """
    ts = query.most_recent_ingest_at(BHM_ID)
    assert ts is None or isinstance(ts, datetime)


def test_most_recent_ingest_at_none_for_nonexistent_city():
    ts = query.most_recent_ingest_at(999999)
    assert ts is None


def test_freshness_state_good():
    now = datetime.now(timezone.utc)
    state = query._freshness_state(now - timedelta(hours=4))
    assert state["state"] == "good"
    assert state["label"] == "Live"


def test_freshness_state_warn():
    now = datetime.now(timezone.utc)
    state = query._freshness_state(now - timedelta(days=2))
    assert state["state"] == "warn"


def test_freshness_state_bad():
    now = datetime.now(timezone.utc)
    state = query._freshness_state(now - timedelta(days=10))
    assert state["state"] == "bad"


def test_freshness_state_unknown_for_none():
    state = query._freshness_state(None)
    assert state["state"] == "unknown"
    assert state["last_synced"] is None


def test_kpi_stats_for_municipality_returns_four_dicts():
    municipality = query.get_municipality("birmingham")
    stats = query._kpi_stats_for_municipality(municipality)
    assert isinstance(stats, list)
    assert len(stats) == 4
    for stat in stats:
        assert "label" in stat
        assert "value" in stat


def test_kpi_stats_first_card_is_meetings_tracked():
    municipality = query.get_municipality("birmingham")
    stats = query._kpi_stats_for_municipality(municipality)
    assert stats[0]["label"] == "Meetings tracked"


def test_list_recent_meetings_for_city_returns_city_only():
    """SQL-side city filter — never gets crowded out by other cities."""
    rows = query.list_recent_meetings_for_city("birmingham", days=30, limit=20)
    assert isinstance(rows, list)
    for r in rows:
        assert r["municipality_slug"] == "birmingham", (
            f"got cross-city row: {r['municipality_slug']}"
        )


def test_list_recent_meetings_for_city_respects_window():
    """meeting_date must be within `days` of today and <= today."""
    from datetime import date, timedelta
    rows = query.list_recent_meetings_for_city("birmingham", days=7, limit=20)
    today = date.today()
    cutoff = today - timedelta(days=7)
    for r in rows:
        assert cutoff <= r["meeting_date"] <= today, (
            f"meeting_date {r['meeting_date']} outside [{cutoff}, {today}]"
        )


def test_list_upcoming_meetings_for_city_returns_city_only():
    rows = query.list_upcoming_meetings_for_city("birmingham", days=60, limit=20)
    for r in rows:
        assert r["municipality_slug"] == "birmingham"


def test_list_upcoming_meetings_for_city_only_future():
    """meeting_date must be > today and <= today + days."""
    from datetime import date, timedelta
    rows = query.list_upcoming_meetings_for_city("birmingham", days=30, limit=20)
    today = date.today()
    horizon = today + timedelta(days=30)
    for r in rows:
        assert today < r["meeting_date"] <= horizon
