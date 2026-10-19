"""``query.get_published_note``: the one query ``/coverage/<id>`` used to run inline.

Runs against the throwaway database (plan birmingham-city-briefing, M3;
debt ``D7``). The route answers 404 when the helper returns ``None``, so
the helper's "404 shape" is ``None`` for an unknown id and for a note that
is not published; a published note comes back with its subjects hydrated.
"""
from __future__ import annotations

import pytest

from docket.config import DATABASE_URL
from docket.db import db
from docket.services import query
from docket.services.coverage_writer import create_note, set_status
from docket.web import create_app


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Refusing to run editorial-coverage tests against Railway DB.",
)


@pytest.fixture
def notes():
    """One published note and one draft, on a throwaway item; cleaned afterwards."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_users (username, password_hash, display_name) "
                "VALUES (%s, %s, %s) RETURNING id",
                ("note-admin", "x", "Note Tester"),
            )
            uid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO meetings (municipality_id, external_id, title, meeting_date) "
                "VALUES ((SELECT id FROM municipalities LIMIT 1), %s, %s, NOW()) RETURNING id",
                ("note-mtg", "Note Test"),
            )
            mtg_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO agenda_items (meeting_id, title) VALUES (%s, %s) RETURNING id",
                (mtg_id, "Note Test Item"),
            )
            item_id = cur.fetchone()[0]
        conn.commit()
    published = create_note(author_id=uid, body="Published note body.", partner_credit=None,
                            subjects=[("agenda_item", item_id, None)])
    set_status(published, "published")
    draft = create_note(author_id=uid, body="Draft note body.", partner_credit=None,
                        subjects=[("agenda_item", item_id, None)])
    yield {"published": published, "draft": draft, "item_id": item_id}
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM coverage_entries WHERE author_id = %s", (uid,))
            cur.execute("DELETE FROM agenda_items WHERE id = %s", (item_id,))
            cur.execute("DELETE FROM meetings WHERE id = %s", (mtg_id,))
            cur.execute("DELETE FROM admin_users WHERE id = %s", (uid,))
        conn.commit()


def test_get_published_note_404_shape(notes):
    assert query.get_published_note(0) is None
    assert query.get_published_note(notes["draft"]) is None
    note = query.get_published_note(notes["published"])
    assert note is not None
    assert note.id == notes["published"]
    assert note.kind == "note" and note.status == "published"
    assert [s.subject_id for s in note.subjects] == [notes["item_id"]]

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        assert c.get(f"/coverage/{notes['draft']}").status_code == 404
        assert c.get(f"/coverage/{notes['published']}").status_code == 200
