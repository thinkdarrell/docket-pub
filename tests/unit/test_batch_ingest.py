"""Tests for `docket.ai.batch_ingest` — Anthropic Batches API result ingestion."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


VALID_STAGE1_TOOL_INPUT = {
    "funding_source": "general_fund",
    "counterparty": "Acme HVAC Inc.",
    "procurement_method": "competitive",
    "location": None,
    "action_type": "contract_award",
    "next_steps": {},
    "parcels_affected": None,
    "acres_affected": None,
}


def _mock_stage1_message(tool_input: dict = None) -> MagicMock:
    """Build a Message-like object as returned by Anthropic Batches results."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "submit_extracted_facts"
    block.input = tool_input if tool_input is not None else VALID_STAGE1_TOOL_INPUT
    msg = MagicMock()
    msg.content = [block]
    return msg


def _mock_succeeded_result(custom_id: str, message) -> MagicMock:
    r = MagicMock()
    r.custom_id = custom_id
    r.result.type = "succeeded"
    r.result.message = message
    return r


def _mock_errored_result(custom_id: str, kind: str = "errored") -> MagicMock:
    r = MagicMock()
    r.custom_id = custom_id
    r.result.type = kind
    return r


# ---------------------------------------------------------------------------
# Helper-level coverage that doesn't need the DB
# ---------------------------------------------------------------------------


def test_extract_tool_input_from_message_picks_matching_block():
    from docket.ai.batch_ingest import _extract_tool_input_from_message

    msg = _mock_stage1_message({"funding_source": "general_fund"})
    out = _extract_tool_input_from_message(msg, "submit_extracted_facts")
    assert out == {"funding_source": "general_fund"}


def test_extract_tool_input_from_message_raises_when_no_block():
    from docket.ai.batch_ingest import _extract_tool_input_from_message
    from docket.ai.exceptions import AIPermanentRowError

    msg = MagicMock()
    msg.content = []  # no tool_use blocks
    with pytest.raises(AIPermanentRowError):
        _extract_tool_input_from_message(msg, "submit_extracted_facts")


def test_validate_stage1_payload_coerces_unknown_enum_then_validates():
    from docket.ai.batch_ingest import _validate_stage1_payload

    payload = dict(VALID_STAGE1_TOOL_INPUT)
    payload["funding_source"] = "grant"  # not in enum; coerce → 'unknown'
    facts = _validate_stage1_payload(payload, item_id=42)
    assert facts.funding_source == "unknown"


def test_validate_stage1_payload_raises_permanent_on_unfixable():
    from docket.ai.batch_ingest import _validate_stage1_payload
    from docket.ai.exceptions import AIPermanentRowError

    payload = dict(VALID_STAGE1_TOOL_INPUT)
    payload["acres_affected"] = "nope"  # type mismatch — coercion can't help
    with pytest.raises(AIPermanentRowError):
        _validate_stage1_payload(payload, item_id=42)


def test_validate_stage2_payload_truncates_overlong_headline():
    from docket.ai.batch_ingest import _validate_stage2_payload

    payload = {
        "is_substantive": True,
        "headline": "x" * 75,
        "why_it_matters": "Real consequence for residents.",
        "significance_rationale": "rationale",
        "significance_score": 7,
        "consent_placement_rationale": "rationale",
        "consent_placement_score": 2,
        "suggested_badge_slugs": [],
        "confidence": "high",
    }
    rewrite = _validate_stage2_payload(payload, item_id=42)
    assert len(rewrite.headline) <= 60


# ---------------------------------------------------------------------------
# ingest_batch / poll_and_ingest with mocked DB + Anthropic
# ---------------------------------------------------------------------------


def test_ingest_batch_returns_skipped_when_no_row():
    from docket.ai.batch_ingest import ingest_batch

    with patch("docket.ai.batch_ingest.db") as mock_db:
        cur = mock_db.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = None
        out = ingest_batch("msgbatch_unknown")
    assert out == {"skipped_no_row": True}


def test_ingest_batch_short_circuits_when_already_ingested():
    """If ingested_at is set, ingest_batch returns immediately without touching Anthropic."""
    from datetime import datetime, timezone

    from docket.ai.batch_ingest import ingest_batch

    with patch("docket.ai.batch_ingest.db") as mock_db, \
         patch("docket.ai.batch_ingest.anthropic.Anthropic") as anthropic_cls:
        cur = mock_db.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (
            7,  # batch_pk
            "stage1",
            datetime(2026, 5, 11, 20, 0, tzinfo=timezone.utc),
        )
        out = ingest_batch("msgbatch_already_done")
    assert out == {"already_ingested": True}
    anthropic_cls.assert_not_called()


def test_poll_and_ingest_iterates_in_flight_then_ready_batches():
    """End-to-end orchestration: poll_batch called for in_flight rows,
    ingest_batch called for ready rows, summary fields populated."""
    from docket.ai.batch_ingest import poll_and_ingest

    # Two SELECTs: in-flight (returns one batch), ready (returns two batches).
    fetchall_returns = [
        [("batch_in_progress_001",)],
        [("batch_ended_a",), ("batch_ended_b",)],
    ]
    cur_mock = MagicMock()
    cur_mock.fetchall.side_effect = fetchall_returns

    db_ctx = MagicMock()
    db_ctx.__enter__.return_value = db_ctx
    db_ctx.cursor.return_value.__enter__.return_value = cur_mock

    with patch("docket.ai.batch_ingest.db", return_value=db_ctx) as _db, \
         patch("docket.ai.batch_ingest.poll_batch") as mock_poll, \
         patch("docket.ai.batch_ingest.ingest_batch") as mock_ingest:
        mock_ingest.side_effect = [
            {"succeeded": 10, "errored": 1, "skipped": 0, "stage": "stage1"},
            {"succeeded": 8, "errored": 0, "skipped": 0, "stage": "stage2"},
        ]
        summary = poll_and_ingest()

    mock_poll.assert_called_once_with("batch_in_progress_001")
    assert mock_ingest.call_count == 2
    assert summary.batches_polled == 1
    assert summary.batches_ingested == 2
    assert summary.items_succeeded == 18
    assert summary.items_errored == 1
    assert summary.batch_ids_ingested == ["batch_ended_a", "batch_ended_b"]


def test_poll_and_ingest_continues_when_one_batch_errors():
    """A failure in one ingest_batch must not stop the rest of the queue."""
    from docket.ai.batch_ingest import poll_and_ingest

    cur_mock = MagicMock()
    cur_mock.fetchall.side_effect = [
        [],                                       # no in-flight
        [("batch_a",), ("batch_b",)],             # two ready
    ]
    db_ctx = MagicMock()
    db_ctx.__enter__.return_value = db_ctx
    db_ctx.cursor.return_value.__enter__.return_value = cur_mock

    with patch("docket.ai.batch_ingest.db", return_value=db_ctx), \
         patch("docket.ai.batch_ingest.poll_batch"), \
         patch("docket.ai.batch_ingest.ingest_batch") as mock_ingest:
        mock_ingest.side_effect = [
            RuntimeError("simulated download failure"),
            {"succeeded": 5, "errored": 0, "skipped": 0, "stage": "stage1"},
        ]
        summary = poll_and_ingest()

    # Both batches were attempted; the bad one didn't kill the second.
    assert mock_ingest.call_count == 2
    assert summary.batches_ingested == 1
    assert summary.items_succeeded == 5
