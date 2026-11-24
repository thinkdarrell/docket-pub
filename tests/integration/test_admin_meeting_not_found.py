"""Route tests for two admin meeting POSTs on a meeting that does not exist.

Written against ``src/docket/web/admin.py`` while ``unhide_meeting`` and
``rescan_meeting_ocr`` still executed their own SQL, and seen to pass there,
so that the same file passing after the statements moved into
``docket.services.non_meetings`` and ``docket.services.video_ocr`` shows the
two routes still answer 404 (plan `admin-routes-call-services`, M4). The
hide route's 404 is already tested
(``tests/integration/test_admin_hide_meeting.py``).

Nothing is seeded and nothing is written, so there is nothing to clean up.
"""

from __future__ import annotations

import pytest

from docket.db import db_cursor

NO_SUCH_ID = 999999999


def _meeting_exists() -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM meetings WHERE id = %s", (NO_SUCH_ID,))
        return cur.fetchone() is not None


@pytest.mark.parametrize("action", ["unhide", "rescan-ocr"])
def test_meeting_post_for_an_unknown_meeting_is_404(authed_admin_client, action):
    assert not _meeting_exists()

    resp = authed_admin_client.post(f"/admin/meetings/{NO_SUCH_ID}/{action}")

    assert resp.status_code == 404
    assert not _meeting_exists()
