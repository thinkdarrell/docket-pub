"""Route tests for the errors-queue POSTs on an item that does not exist.

Written against ``src/docket/web/admin.py`` while ``errors_retry`` and
``errors_escalate`` still executed their own SQL, and seen to pass there, so
that the same file passing after the statements moved into
``docket.services.errors_queue`` shows the two routes still answer 404 and
write nothing (plan `admin-routes-call-services`, M2).

Nothing is seeded and nothing is written, so there is nothing to clean up.
The audit table is read before and after the request and the two readings
compared; no test asserts the table's size against a fixed number.
"""

from __future__ import annotations

import pytest

from docket.db import db_cursor

NO_SUCH_ID = 999999999


def _audit_reading() -> tuple[int, int]:
    """(rows in processing_status_audit, the highest id among them)."""
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n, COALESCE(MAX(id), 0) AS top FROM processing_status_audit")
        row = cur.fetchone()
        return row["n"], row["top"]


def _item_exists() -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM agenda_items WHERE id = %s", (NO_SUCH_ID,))
        return cur.fetchone() is not None


@pytest.mark.parametrize("action", ["retry", "escalate"])
def test_errors_post_for_an_unknown_item_is_404_and_writes_no_audit_row(
    authed_admin_client, action
):
    assert not _item_exists()
    before = _audit_reading()

    resp = authed_admin_client.post(f"/admin/errors/{NO_SUCH_ID}/{action}")

    assert resp.status_code == 404
    assert _audit_reading() == before
    assert not _item_exists()
