"""docket.services.query: the two reads behind the AI dashboard (/admin/ai).

``ai_pipeline_summary`` (pending counts, the seven-day cost sums, the last
twenty runs) and ``transcript_pipeline_summary`` (transcript status counts,
transcript stage costs, citation-missing rates) hold the statements
``src/docket/web/admin.py`` executed itself, in two transactions, before
plan `admin-routes-call-services`, M3.

Seeded rows carry the prefix ``admai_test_``: the city slug (meetings, their
items, transcripts and discrepancies go with the city's meetings) and the
``notes`` of every ``ai_runs`` row; they are deleted before and after every
test. Both functions read whole tables that other tests also fill, so a
count is asserted as the difference between a reading before the seed and
one after, and the grouped lists are asserted under a stage name and a
prompt version no other test uses. Each service name is imported inside the
test, so the file collects before the functions exist. Runs in the services
tier (DATABASE_URL names docket_test_*).
"""

from __future__ import annotations

import datetime
import decimal
import json

import pytest

from docket.db import db_cursor

PREFIX = "admai_test_"
CITY_SLUG = PREFIX + "city"
OWN_STAGE = "transcript_admai_test"
OWN_PROMPT_VERSION = 98765431
ITEM_VERSION = 7
MEETING_VERSION = 4
DEBOUNCE = 5


def _delete_seeded() -> None:
    like = (PREFIX + "%",)
    with db_cursor() as cur:
        cur.execute("DELETE FROM ai_runs WHERE notes LIKE %s", like)
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
def city() -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO municipalities (slug, name, adapter_class, adapter_config, active)
               VALUES (%s, 'Admai Test City', 'GranicusAdapter', '{}', TRUE) RETURNING id""",
            (CITY_SLUG,),
        )
        return cur.fetchone()["id"]


def _meeting(city_id: int, *, version=None, adopted: bool = False, phase: str | None = None) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, title, meeting_date, ai_prompt_version,
                                     minutes_adopted_at, ai_metadata)
               VALUES (%s, 'Admai test meeting', '2026-04-15', %s,
                       CASE WHEN %s THEN NOW() END, %s::jsonb)
               RETURNING id""",
            (city_id, version, adopted,
             json.dumps({"phase": phase}) if phase is not None else None),
        )
        return cur.fetchone()["id"]


def _item(meeting_id: int, *, version=None, minutes_old: int = 60) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO agenda_items (meeting_id, title, ai_prompt_version, created_at)
               VALUES (%s, 'Admai test item', %s, NOW() - (%s || ' minutes')::interval)
               RETURNING id""",
            (meeting_id, version, minutes_old),
        )
        return cur.fetchone()["id"]


def _run(*, stage: str = "items", days_old: float = 0, cost: str = "0", usage: dict | None = None,
         rows_processed: int = 0, rows_failed: int = 0, model: str = "admai-model") -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO ai_runs (started_at, stage, model, rows_processed, rows_failed,
                                    usage, cost_usd, notes)
               VALUES (NOW() - (%s || ' days')::interval, %s, %s, %s, %s, %s::jsonb, %s, %s)
               RETURNING id""",
            (days_old, stage, model, rows_processed, rows_failed,
             json.dumps(usage or {}), cost, PREFIX + "run"),
        )
        return cur.fetchone()["id"]


def _transcript(meeting_id: int, status: str) -> None:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO transcripts (meeting_id, status) VALUES (%s, %s)",
            (meeting_id, status),
        )


def _discrepancy(meeting_id: int, *, citation_match: str, review_state: str = "proposed",
                 prompt_version: int = OWN_PROMPT_VERSION) -> None:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO minutes_discrepancies
                      (meeting_id, category, severity, title, description,
                       citation_match, review_state, prompt_version)
               VALUES (%s, 'wording', 'material', 'Admai test discrepancy',
                       'Seeded by the AI dashboard service test.', %s, %s, %s)""",
            (meeting_id, citation_match, review_state, prompt_version),
        )


def _pipeline(item_version: int = ITEM_VERSION, meeting_version: int = MEETING_VERSION,
              debounce: int = DEBOUNCE) -> dict:
    from docket.services.query import ai_pipeline_summary

    return ai_pipeline_summary(item_version, meeting_version, debounce)


# --- ai_pipeline_summary -----------------------------------------------------


def test_ai_pipeline_summary_returns_the_four_keys():
    summary = _pipeline()

    assert set(summary) == {"items_pending", "meetings_pending", "seven_day", "runs"}
    assert set(summary["seven_day"]) == {"total", "cache_reads", "regular_reads"}
    assert isinstance(summary["items_pending"], int)
    assert isinstance(summary["meetings_pending"], int)
    assert isinstance(summary["seven_day"]["total"], float)
    assert isinstance(summary["runs"], list)


def test_ai_pipeline_summary_counts_an_item_with_no_version_or_an_older_one(city):
    meeting = _meeting(city, version=MEETING_VERSION)
    before = _pipeline()["items_pending"]

    _item(meeting, version=None)
    assert _pipeline()["items_pending"] == before + 1
    _item(meeting, version=ITEM_VERSION - 1)
    assert _pipeline()["items_pending"] == before + 2
    _item(meeting, version=ITEM_VERSION)
    assert _pipeline()["items_pending"] == before + 2
    _item(meeting, version=ITEM_VERSION + 1)
    assert _pipeline()["items_pending"] == before + 2


def test_ai_pipeline_summary_measures_items_against_the_item_version_it_is_given(city):
    meeting = _meeting(city, version=MEETING_VERSION)
    _item(meeting, version=5)

    # 5 is older than item version 7 and not older than item version 5; the
    # meeting version (4 in both calls) decides nothing here.
    assert _pipeline(item_version=7)["items_pending"] == _pipeline(item_version=5)["items_pending"] + 1


def test_ai_pipeline_summary_leaves_out_an_item_younger_than_the_debounce(city):
    meeting = _meeting(city, version=MEETING_VERSION)
    before_short = _pipeline(debounce=5)["items_pending"]
    before_long = _pipeline(debounce=120)["items_pending"]

    _item(meeting, version=None, minutes_old=60)
    _item(meeting, version=None, minutes_old=0)

    assert _pipeline(debounce=5)["items_pending"] == before_short + 1
    assert _pipeline(debounce=120)["items_pending"] == before_long


def test_ai_pipeline_summary_counts_an_unadopted_meeting_whose_items_are_all_done(city):
    before = _pipeline()["meetings_pending"]

    done = _meeting(city, version=None)
    _item(done, version=ITEM_VERSION)
    assert _pipeline()["meetings_pending"] == before + 1

    _meeting(city, version=MEETING_VERSION - 1)  # an older version, no items at all
    assert _pipeline()["meetings_pending"] == before + 2

    _meeting(city, version=MEETING_VERSION)  # current: not pending
    assert _pipeline()["meetings_pending"] == before + 2

    waiting = _meeting(city, version=None)  # an item still pending: not yet
    _item(waiting, version=None, minutes_old=0)
    assert _pipeline()["meetings_pending"] == before + 2


def test_ai_pipeline_summary_measures_meetings_against_both_versions_it_is_given(city):
    before = _pipeline()["meetings_pending"]

    # Version 5 is current for meetings (4) though older than the item version (7).
    _meeting(city, version=5)
    assert _pipeline()["meetings_pending"] == before

    # Its item at version 5 is pending for items (7), so the meeting waits,
    # though 5 is not older than the meeting version (4).
    waiting = _meeting(city, version=None)
    _item(waiting, version=5)
    assert _pipeline()["meetings_pending"] == before
    assert _pipeline(item_version=5)["meetings_pending"] == before + 1
    assert _pipeline(meeting_version=6)["meetings_pending"] == before + 1


def test_ai_pipeline_summary_counts_an_adopted_meeting_until_its_phase_is_adopted(city):
    before = _pipeline()["meetings_pending"]

    _meeting(city, version=MEETING_VERSION, adopted=True)  # no metadata at all
    assert _pipeline()["meetings_pending"] == before + 1

    _meeting(city, version=MEETING_VERSION, adopted=True, phase="draft")
    assert _pipeline()["meetings_pending"] == before + 2

    _meeting(city, version=MEETING_VERSION, adopted=True, phase="adopted")
    assert _pipeline()["meetings_pending"] == before + 2

    # Adopted, never summarised, phase already adopted: the first arm wants
    # minutes not adopted, the second a phase other than adopted. Neither.
    _meeting(city, version=None, adopted=True, phase="adopted")
    assert _pipeline()["meetings_pending"] == before + 2

    # Not adopted and current, whatever its phase: neither arm.
    _meeting(city, version=MEETING_VERSION, adopted=False, phase="draft")
    assert _pipeline()["meetings_pending"] == before + 2


def test_ai_pipeline_summary_sums_cost_and_tokens_of_the_last_seven_days():
    before = _pipeline()["seven_day"]

    _run(days_old=1, cost="1.2500", usage={"cache_read_input_tokens": 100, "input_tokens": 40})
    _run(days_old=6, cost="0.5000", usage={"cache_read_input_tokens": 7, "input_tokens": 3})
    _run(days_old=8, cost="9.0000", usage={"cache_read_input_tokens": 9000, "input_tokens": 900})
    after = _pipeline()["seven_day"]

    assert after["total"] - before["total"] == pytest.approx(1.75)
    assert after["cache_reads"] - before["cache_reads"] == 107
    assert after["regular_reads"] - before["regular_reads"] == 43


def test_ai_pipeline_summary_lists_the_last_twenty_runs_newest_id_first():
    ids = [_run(stage="admai_stage", days_old=30, cost="0.1234", rows_processed=n, rows_failed=1)
           for n in range(21)]

    runs = _pipeline()["runs"]

    assert [r["id"] for r in runs] == sorted(ids, reverse=True)[:20]
    newest = dict(runs[0])
    assert isinstance(newest.pop("started_at"), datetime.datetime)
    assert newest == {
        "id": ids[-1], "stage": "admai_stage", "model": "admai-model",
        "rows_processed": 20, "rows_failed": 1, "cost_usd": decimal.Decimal("0.1234"),
    }


# --- transcript_pipeline_summary ---------------------------------------------


def _transcripts() -> dict:
    from docket.services.query import transcript_pipeline_summary

    return transcript_pipeline_summary()


def test_transcript_pipeline_summary_returns_the_three_keys():
    summary = _transcripts()

    assert set(summary) == {"transcript_status_counts", "transcript_stage_costs", "citation_missing"}
    assert all(isinstance(summary[key], list) for key in summary)


def test_transcript_pipeline_summary_counts_transcripts_by_status_in_status_order(city):
    before = {r["status"]: r["n"] for r in _transcripts()["transcript_status_counts"]}

    _transcript(_meeting(city), "uploaded")
    _transcript(_meeting(city), "compared")
    _transcript(_meeting(city), "compared")
    rows = _transcripts()["transcript_status_counts"]

    after = {r["status"]: r["n"] for r in rows}
    assert after["compared"] - before.get("compared", 0) == 2
    assert after["uploaded"] - before.get("uploaded", 0) == 1
    assert after.get("failed", 0) == before.get("failed", 0)
    assert all(set(r) == {"status", "n"} for r in rows)
    statuses = [r["status"] for r in rows]
    assert statuses == sorted(statuses)
    assert len(statuses) == len(set(statuses))


def test_transcript_pipeline_summary_sums_a_transcript_stage_over_seven_days():
    _run(stage=OWN_STAGE, days_old=1, cost="0.4000", rows_processed=3, rows_failed=1)
    _run(stage=OWN_STAGE, days_old=5, cost="0.2500", rows_processed=4, rows_failed=2)
    _run(stage=OWN_STAGE, days_old=8, cost="9.0000", rows_processed=100, rows_failed=100)

    rows = _transcripts()["transcript_stage_costs"]

    mine = [dict(r) for r in rows if r["stage"] == OWN_STAGE]
    assert len(mine) == 1
    assert mine[0].pop("cost") == pytest.approx(0.65)
    assert mine[0] == {"stage": OWN_STAGE, "runs": 2, "rows_processed": 7, "rows_failed": 3}
    stages = [r["stage"] for r in rows]
    assert stages == sorted(stages)


def test_transcript_pipeline_summary_lists_transcript_compare_and_no_other_kind_of_stage():
    before = {r["stage"]: r["runs"] for r in _transcripts()["transcript_stage_costs"]}

    _run(stage="transcript_compare", days_old=1, cost="0.4321", rows_processed=1)
    _run(stage="admai_test_items", days_old=1, cost="0.4321", rows_processed=1)
    _run(stage="x_transcript_admai", days_old=1, cost="0.4321", rows_processed=1)
    rows = _transcripts()["transcript_stage_costs"]

    after = {r["stage"]: r["runs"] for r in rows}
    assert after["transcript_compare"] - before.get("transcript_compare", 0) == 1
    assert "admai_test_items" not in after
    assert "x_transcript_admai" not in after
    assert all(stage.startswith("transcript_") for stage in after)


def test_transcript_pipeline_summary_gives_the_citation_missing_rate_of_a_prompt_version(city):
    meeting = _meeting(city)
    _discrepancy(meeting, citation_match="missing")
    _discrepancy(meeting, citation_match="exact")
    _discrepancy(meeting, citation_match="missing", review_state="dismissed_by_model")
    _discrepancy(meeting, citation_match="missing", prompt_version=OWN_PROMPT_VERSION + 1)

    rows = _transcripts()["citation_missing"]

    mine = [dict(r) for r in rows if r["prompt_version"] == OWN_PROMPT_VERSION]
    assert mine == [
        {"prompt_version": OWN_PROMPT_VERSION, "total": 2, "missing": 1,
         "rate": decimal.Decimal("50.0")}
    ]
    assert str(mine[0]["rate"]) == "50.0"
    versions = [r["prompt_version"] for r in rows]
    assert versions == sorted(versions)
    assert OWN_PROMPT_VERSION + 1 in versions
