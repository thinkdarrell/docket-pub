"""The backfill's dry run on a database migration 045 has not reached.

Before the pull request merges, production has neither table and Birmingham's
metadata does not name its committee pages. The operator's dry run must still
run: it makes the tables and the key inside its own transaction and rolls
them back with everything else. Without the dry run the script refuses.

Pattern: tests/integration/test_045_migration.py, whose fixture this copies.
The adapter's fetches are replaced; nothing reaches the network. The script
is imported inside each test, so the file collects before it exists.

Plan `committee-documents`, M6.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import pytest

from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Migration test must not run against Railway prod.",
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "committee_documents"
ROOT = "https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/"
PAGE_URL = ROOT + "budget-finance-committee"
PDF_URL = "https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/cdbefore/bf-minutes.pdf"


@pytest.fixture
def before_045():
    """Every migration applied, then 045 rolled back; the teardown re-applies it."""
    with db() as conn:
        runner.apply_migrations(conn)
        runner.rollback_migration(conn, 45)
    yield
    with db() as conn:
        runner.apply_migrations(conn)
    with db_cursor() as cur:
        cur.execute("DELETE FROM committee_documents WHERE url LIKE %s", ("%/cdbefore/%",))
        cur.execute("DELETE FROM meetings WHERE external_id LIKE 'cdoc-%'")


@pytest.fixture(autouse=True)
def net(monkeypatch):
    from docket.adapters import committee_documents as adapter

    fragment = (
        "<h4>OCTOBER 12, 2026</h4>"
        '<article class="media media--type-document" '
        f'name="{html.escape("BUDGET AND FINANCE COMMITTEE MEETING MINUTES, October 12, 2026.pdf")}" '
        f'file="{PDF_URL}"></article>'
    )
    page = ('<html><body><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"body": fragment}}}) + "</script></body></html>")

    def fetch_page(url):
        if url != PAGE_URL:
            raise RuntimeError("no such page in this test")
        return page

    monkeypatch.setattr(adapter, "fetch_page", fetch_page)
    monkeypatch.setattr(adapter, "fetch_pdf", lambda url: (FIXTURES / "bf_minutes_2026-10-12.pdf").read_bytes())


def _state() -> tuple:
    with db_cursor() as cur:
        cur.execute(
            "SELECT to_regclass('committee_documents') IS NOT NULL AS documents, "
            "       to_regclass('committee_items') IS NOT NULL AS items"
        )
        tables = cur.fetchone()
        cur.execute("SELECT metadata ? 'committee_document_pages' AS has_key FROM municipalities "
                    "WHERE slug = 'birmingham'")
        has_key = cur.fetchone()["has_key"]
        cur.execute("SELECT count(*) AS n FROM meetings")
        return tables["documents"], tables["items"], has_key, cur.fetchone()["n"]


def test_a_dry_run_makes_the_tables_for_itself_and_leaves_none_behind(before_045, capsys):
    from scripts import backfill_committee_documents as script

    before = _state()
    assert before[:3] == (False, False, False)

    script.main(["--city", "birmingham", "--dry-run"])

    assert _state() == before
    out = capsys.readouterr().out
    assert "the tables of migration 045 are absent" in out
    assert "new listings 1, read 1, read again 0" in out
    assert "cdoc-budget-finance-2026-10-12" in out
    assert out.rstrip().endswith("dry run: nothing written")


def test_without_dry_run_the_script_makes_no_table_and_exits_with_an_error(before_045, capsys):
    from scripts import backfill_committee_documents as script

    before = _state()

    with pytest.raises(SystemExit) as exit_info:
        script.main(["--city", "birmingham"])

    assert exit_info.value.code not in (0, None)
    assert _state() == before
