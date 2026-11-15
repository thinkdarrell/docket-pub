"""scripts/backfill_committee_documents.py: the operator's fill of production.

The script's ``main`` is called with an argument list; the adapter's two
fetches are replaced, so nothing reaches the network, and the one PDF is the
saved Budget and Finance minutes. A dry run must leave the row counts of
``committee_documents``, ``committee_items`` and ``meetings`` as they were.
The script is imported inside each test, so the file collects before it
exists. Reads and writes the throwaway database (DATABASE_URL names
docket_test_*); every row it leaves is deleted after.

Plan `committee-documents`, M6.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import pytest

from docket.db import db_cursor

FIXTURES = Path(__file__).parent.parent / "fixtures" / "committee_documents"
ROOT = "https://www.birminghamal.gov/government/city-council/council/council-committees-2025-2027/"
PAGE_URL = ROOT + "budget-finance-committee"
PDF_URL = "https://s3.us-east-2.amazonaws.com/assets.birminghamal.gov/cdscript/bf-minutes.pdf"
TABLES = ("committee_documents", "committee_items", "meetings")


def _counts() -> tuple[int, ...]:
    with db_cursor() as cur:
        out = []
        for table in TABLES:
            cur.execute(f"SELECT count(*) AS n FROM {table}")
            out.append(cur.fetchone()["n"])
        return tuple(out)


def _delete_all() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM committee_documents")
        cur.execute("DELETE FROM meetings WHERE external_id LIKE 'cdoc-%'")


@pytest.fixture(autouse=True)
def clean():
    _delete_all()
    yield
    _delete_all()


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


def test_a_dry_run_leaves_the_three_tables_row_counts_unchanged(capsys):
    from scripts import backfill_committee_documents as script

    before = _counts()

    script.main(["--city", "birmingham", "--dry-run"])

    assert _counts() == before
    out = capsys.readouterr().out
    assert "new listings 1, read 1, read again 0" in out
    assert "read           minutes    1" in out
    assert "date from the header 1, from the heading 0, no date 0; listing disagrees 0" in out
    assert "recommended_consent      9" in out
    assert "matched 0, created 1, ambiguous 0, unattached agendas 0, unattached minutes 0" in out
    assert "meetings it would create: 1" in out
    assert "2026-10-12  cdoc-budget-finance-2026-10-12  Budget and Finance Committee Meeting" in out
    assert out.rstrip().endswith("dry run: nothing written")
    budget = next(line for line in out.splitlines() if line.startswith("Budget and Finance"))
    assert budget.split()[-6:] == ["1", "0", "1", "1", "1", "0"]


def test_without_dry_run_the_script_writes_and_says_so(capsys):
    from scripts import backfill_committee_documents as script

    before = _counts()

    script.main(["--city", "birmingham"])

    after = _counts()
    assert tuple(a - b for a, b in zip(after, before)) == (1, 12, 1)
    out = capsys.readouterr().out
    assert "meetings created: 1" in out
    assert "dry run" not in out


def test_limit_is_the_number_of_documents_read(capsys, monkeypatch):
    from docket.services import committee_documents as service
    from scripts import backfill_committee_documents as script

    seen = []
    real = service.backfill

    def spy(*args, **kwargs):
        seen.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(service, "backfill", spy)

    script.main(["--city", "birmingham", "--dry-run", "--limit", "3"])
    script.main(["--city", "birmingham", "--dry-run"])

    assert [(k["limit"], k["dry_run"]) for _, k in seen] == [(3, True), (None, True)]


def test_an_unknown_city_exits_with_an_error_and_writes_nothing(capsys):
    from scripts import backfill_committee_documents as script

    before = _counts()
    with pytest.raises(SystemExit) as exit_info:
        script.main(["--city", "atlantis", "--dry-run"])
    assert exit_info.value.code not in (0, None)
    assert _counts() == before
