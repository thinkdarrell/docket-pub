"""docket.services.errors_queue: the two writes behind the admin errors queue.

``retry_item`` and ``escalate_item`` hold the statements the routes
``POST /admin/errors/<id>/retry`` and ``POST /admin/errors/<id>/escalate``
executed themselves before plan `admin-routes-call-services`, M2. Each is one
transaction: read the item, update it, write one ``processing_status_audit``
row.

One city is seeded whose slug begins ``errq_test_``; the autouse fixture
deletes the audit rows of its items (the audit table's foreign key does not
cascade), then its meetings (items go with them), then the city, before and
after every test. Each service name is imported inside the test, so the file
collects before the module exists. Runs in the services tier (DATABASE_URL
names docket_test_*).
"""

from __future__ import annotations

import json
import uuid

import pytest

from docket.db import db_cursor

PREFIX = "errq_test_"
NO_SUCH_ID = 999999999
ACTOR = "errq-operator"

_ITEMS_OF_PREFIX = (
    "(SELECT ai.id FROM agenda_items ai "
    "JOIN meetings mt ON mt.id = ai.meeting_id "
    "JOIN municipalities m ON m.id = mt.municipality_id "
    "WHERE m.slug LIKE %s)"
)


def _delete_seeded() -> None:
    like = (PREFIX + "%",)
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM processing_status_audit WHERE agenda_item_id IN " + _ITEMS_OF_PREFIX,
            like,
        )
        cur.execute(
            "DELETE FROM meetings WHERE municipality_id IN "
            "(SELECT id FROM municipalities WHERE slug LIKE %s)",
            like,
        )
        cur.execute("DELETE FROM municipalities WHERE slug LIKE %s", like)


@pytest.fixture(autouse=True)
def _clean():
    _delete_seeded()
    yield
    _delete_seeded()


@pytest.fixture
def meeting() -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO municipalities (slug, name, adapter_class, adapter_config, active)
               VALUES (%s, 'Errq test city', 'GranicusAdapter', '{}', TRUE) RETURNING id""",
            (PREFIX + "city",),
        )
        city_id = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO meetings (municipality_id, title, meeting_date)
               VALUES (%s, 'Errq test meeting', '2026-04-15') RETURNING id""",
            (city_id,),
        )
        return cur.fetchone()["id"]


def _item(meeting_id: int, *, status: str = "failed_permanent", attempts: int = 3,
          overrides: dict | None = None, session: str | None = None,
          error: str | None = None) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO agenda_items
                 (meeting_id, title, processing_status, processing_attempts,
                  score_overrides, backfill_session_id, last_error_at,
                  last_error_message)
               VALUES (%s, 'Errq test item', %s::processing_status_enum, %s,
                       %s::jsonb, %s::uuid,
                       CASE WHEN %s::text IS NULL THEN NULL ELSE NOW() END, %s)
               RETURNING id""",
            (meeting_id, status, attempts,
             json.dumps(overrides) if overrides is not None else None,
             session, error, error),
        )
        return cur.fetchone()["id"]


def _read(item_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute(
            """SELECT processing_status::text AS status, processing_attempts,
                      backfill_session_id, last_error_at, last_error_message,
                      score_overrides
                 FROM agenda_items WHERE id = %s""",
            (item_id,),
        )
        return dict(cur.fetchone())


def _audit_rows(item_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(
            """SELECT from_status::text AS from_status, to_status::text AS to_status,
                      action, actor, actor_role, reason, payload
                 FROM processing_status_audit
                WHERE agenda_item_id = %s ORDER BY id""",
            (item_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def _audit_reading() -> tuple[int, int]:
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n, COALESCE(MAX(id), 0) AS top FROM processing_status_audit")
        row = cur.fetchone()
        return row["n"], row["top"]


# --- retry_item --------------------------------------------------------------


def test_retry_item_returns_the_prior_status_and_resets_the_five_columns(meeting):
    from docket.services.errors_queue import retry_item

    iid = _item(meeting, status="failed_permanent", attempts=7,
                session=str(uuid.uuid4()), error="boom",
                overrides={"final_significance": 9.0})

    assert retry_item(iid, ACTOR) == "failed_permanent"

    row = _read(iid)
    assert row["status"] == "pending"
    assert row["processing_attempts"] == 0
    assert row["backfill_session_id"] is None
    assert row["last_error_at"] is None
    assert row["last_error_message"] is None
    # A retry is a pipeline unsticker: the scores stay.
    assert row["score_overrides"] == {"final_significance": 9.0}


def test_retry_item_writes_one_audit_row_with_action_retry(meeting):
    from docket.services.errors_queue import retry_item

    iid = _item(meeting, status="cross_stage_conflict")

    assert retry_item(iid, ACTOR) == "cross_stage_conflict"

    assert _audit_rows(iid) == [{
        "from_status": "cross_stage_conflict",
        "to_status": "pending",
        "action": "retry",
        "actor": ACTOR,
        "actor_role": "admin",
        "reason": "Admin retry from errors queue",
        "payload": None,
    }]


def test_retry_item_touches_that_item_only(meeting):
    from docket.services.errors_queue import retry_item

    other = _item(meeting, status="failed_permanent", attempts=5, error="other boom")
    iid = _item(meeting, status="failed_permanent", attempts=3)
    before = _read(other)

    retry_item(iid, ACTOR)

    assert _read(other) == before
    assert _audit_rows(other) == []


def test_retry_item_for_an_unknown_item_is_none_and_writes_nothing(meeting):
    from docket.services.errors_queue import retry_item

    iid = _item(meeting, status="failed_permanent", attempts=3, error="boom")
    item_before = _read(iid)
    audit_before = _audit_reading()

    assert retry_item(NO_SUCH_ID, ACTOR) is None

    assert _audit_reading() == audit_before
    assert _read(iid) == item_before


# --- escalate_item -----------------------------------------------------------


def test_escalate_item_keeps_the_keys_already_there_and_adds_the_two(meeting):
    from docket.services.errors_queue import escalate_item

    existing = {"final_significance": 9.0, "triggers": ["floor"], "admin_override_used": False}
    iid = _item(meeting, status="failed_permanent", attempts=4, overrides=existing)

    assert escalate_item(iid, ACTOR) == "failed_permanent"

    row = _read(iid)
    assert row["score_overrides"] == {
        **existing,
        "admin_escalated": True,
        "admin_escalated_by": ACTOR,
    }
    # An escalation flags; it does not move the item or spend its budget.
    assert row["status"] == "failed_permanent"
    assert row["processing_attempts"] == 4


def test_escalate_item_on_null_score_overrides_stores_exactly_the_two_keys(meeting):
    from docket.services.errors_queue import escalate_item

    iid = _item(meeting, status="failed_permanent", overrides=None)
    assert _read(iid)["score_overrides"] is None

    escalate_item(iid, ACTOR)

    assert _read(iid)["score_overrides"] == {
        "admin_escalated": True,
        "admin_escalated_by": ACTOR,
    }


def test_escalate_item_writes_one_audit_row_whose_from_and_to_status_are_equal(meeting):
    from docket.services.errors_queue import escalate_item

    iid = _item(meeting, status="cross_stage_conflict")

    assert escalate_item(iid, ACTOR) == "cross_stage_conflict"

    assert _audit_rows(iid) == [{
        "from_status": "cross_stage_conflict",
        "to_status": "cross_stage_conflict",
        "action": "escalate",
        "actor": ACTOR,
        "actor_role": "admin",
        "reason": "Admin escalated from errors queue (manual review needed)",
        "payload": {"admin_escalated": True},
    }]


def test_escalate_item_touches_that_item_only(meeting):
    from docket.services.errors_queue import escalate_item

    other = _item(meeting, status="failed_permanent", overrides={"final_consent": 2.0})
    iid = _item(meeting, status="failed_permanent")
    before = _read(other)

    escalate_item(iid, ACTOR)

    assert _read(other) == before
    assert _audit_rows(other) == []


def test_escalate_item_for_an_unknown_item_is_none_and_writes_nothing(meeting):
    from docket.services.errors_queue import escalate_item

    iid = _item(meeting, status="failed_permanent", overrides={"final_consent": 2.0})
    item_before = _read(iid)
    audit_before = _audit_reading()

    assert escalate_item(NO_SUCH_ID, ACTOR) is None

    assert _audit_reading() == audit_before
    assert _read(iid) == item_before
