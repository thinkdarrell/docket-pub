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
    """Prompt v4 raised headline cap from 60 → 80. 90 chars exceeds the
    new cap and exercises the truncate-on-validate path."""
    from docket.ai.batch_ingest import _validate_stage2_payload

    payload = {
        "is_substantive": True,
        "headline": "x" * 90,
        "why_it_matters": "Real consequence for residents.",
        "significance_rationale": "rationale",
        "significance_score": 7,
        "consent_placement_rationale": "rationale",
        "consent_placement_score": 2,
        "suggested_badge_slugs": [],
        "confidence": "high",
    }
    rewrite = _validate_stage2_payload(payload, item_id=42)
    assert len(rewrite.headline) <= 80


# ---------------------------------------------------------------------------
# Stage 2 assertion-error retry (issue #26)
# ---------------------------------------------------------------------------

_ASSERTION_FAILING_STAGE2 = {
    "is_substantive": True,
    "headline": "Council approves new HVAC contract",
    "why_it_matters": "Better climate control in public buildings.",
    "significance_rationale": "Capital project.",
    "significance_score": None,  # null score on substantive → assert fires
    "consent_placement_rationale": "High-dollar.",
    "consent_placement_score": None,
    "suggested_badge_slugs": [],
    "confidence": "medium",
}

_VALID_STAGE2 = {
    **_ASSERTION_FAILING_STAGE2,
    "significance_score": 7,
    "consent_placement_score": 2,
}


def _mock_stage2_message(payload: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = "submit_item_rewrite"
    block.input = payload
    msg = MagicMock()
    msg.model = "claude-haiku-4-5-20251001"
    msg.content = [block]
    return msg


def test_validate_stage2_payload_no_retry_without_ctx():
    """Without retry_ctx, assertion-class failures raise immediately (preserves
    existing behavior for callers that don't supply context)."""
    from docket.ai.batch_ingest import _validate_stage2_payload
    from docket.ai.exceptions import AIPermanentRowError

    with pytest.raises(AIPermanentRowError, match="batch validation failed after coercion"):
        _validate_stage2_payload(dict(_ASSERTION_FAILING_STAGE2), item_id=42)


def test_validate_stage2_payload_retries_assertion_error_with_ctx():
    """retry_ctx triggers a Haiku re-call when remaining errors are
    assertion-class; a valid retry response unblocks the row."""
    from types import SimpleNamespace
    from docket.ai.batch_ingest import _validate_stage2_payload
    from docket.ai.extraction_schema import NextSteps, StructuredFacts
    from docket.ai.rewrite_schema import ItemRewrite

    item = SimpleNamespace(
        id=42, city_name='Birmingham',
        title='HVAC contract', description='body',
        sponsor=None, dollars_amount=100000, topic='contracts', is_consent=False,
    )
    facts = StructuredFacts(
        funding_source='general_fund', counterparty='Acme', procurement_method='competitive',
        location=None, action_type='contract_award', next_steps=NextSteps(),
        parcels_affected=None, acres_affected=None,
    )

    good_resp = _mock_stage2_message(_VALID_STAGE2)
    with patch("docket.ai.rewrite.anthropic_client") as mock_client:
        mock_client.messages.create.return_value = good_resp
        rewrite = _validate_stage2_payload(
            dict(_ASSERTION_FAILING_STAGE2), item_id=42,
            retry_ctx=(item, facts, []),
        )

    assert isinstance(rewrite, ItemRewrite)
    assert rewrite.significance_score == 7
    assert mock_client.messages.create.call_count == 1, \
        "exactly one retry call to Haiku is expected"


def test_validate_stage2_payload_raises_when_retry_also_fails():
    """If the retry response is also invalid, still raise AIPermanentRowError."""
    from types import SimpleNamespace
    from docket.ai.batch_ingest import _validate_stage2_payload
    from docket.ai.exceptions import AIPermanentRowError
    from docket.ai.extraction_schema import NextSteps, StructuredFacts

    item = SimpleNamespace(
        id=42, city_name='Birmingham', title='X', description='',
        sponsor=None, dollars_amount=0, topic='other', is_consent=False,
    )
    facts = StructuredFacts(
        funding_source='general_fund', counterparty=None, procurement_method='not_applicable',
        location=None, action_type='other', next_steps=NextSteps(),
        parcels_affected=None, acres_affected=None,
    )

    bad_resp = _mock_stage2_message(_ASSERTION_FAILING_STAGE2)
    with patch("docket.ai.rewrite.anthropic_client") as mock_client:
        mock_client.messages.create.return_value = bad_resp
        with pytest.raises(AIPermanentRowError, match="assertion-error retry"):
            _validate_stage2_payload(
                dict(_ASSERTION_FAILING_STAGE2), item_id=42,
                retry_ctx=(item, facts, []),
            )


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


# ---------------------------------------------------------------------------
# Cost telemetry — ingest_batch must populate ai_batches.cost_usd from the
# per-message usage returned by Anthropic. Regression: prior to 2026-05-14
# the UPDATE only set ingested_at, so all batches had cost_usd=NULL.
# ---------------------------------------------------------------------------


def test_ingest_batch_writes_cost_usd_from_message_usage():
    """ingest_batch must accumulate message.usage across all successful
    results and write the calculated USD cost to ai_batches.cost_usd."""
    from docket.ai.batch_ingest import ingest_batch

    # Two successful Stage 1 messages with known usage.
    # Haiku pricing (per docket.ai.pricing): input=$1/M, output=$5/M.
    # Per-message: 1000 input + 200 output = $0.001 + $0.001 = $0.002.
    # Two messages = $0.004 total.
    def _msg_with_usage(input_t, output_t, model="claude-haiku-4-5-20251001"):
        m = _mock_stage1_message()
        m.model = model
        usage = MagicMock()
        usage.input_tokens = input_t
        usage.output_tokens = output_t
        usage.cache_creation_input_tokens = 0
        usage.cache_read_input_tokens = 0
        m.usage = usage
        return m

    results = [
        _mock_succeeded_result("stage1-101-v1", _msg_with_usage(1000, 200)),
        _mock_succeeded_result("stage1-102-v1", _msg_with_usage(1000, 200)),
    ]

    captured_sql = []

    with patch("docket.ai.batch_ingest.db") as mock_db, \
         patch("docket.ai.batch_ingest.anthropic.Anthropic") as anthropic_cls, \
         patch("docket.ai.batch_ingest._ingest_stage1_message") as ingest_msg:
        cur = mock_db.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        # Initial SELECT for the ai_batches row: returns (batch_pk, stage, ingested_at=None)
        cur.fetchone.return_value = (42, "stage1", None)
        # Capture every cur.execute call so we can assert on the UPDATE.
        cur.execute.side_effect = lambda *args, **kwargs: captured_sql.append(args)

        anthropic_client = MagicMock()
        anthropic_cls.return_value = anthropic_client
        anthropic_client.messages.batches.results.return_value = iter(results)

        ingest_msg.return_value = None  # both successful ingests are no-ops

        out = ingest_batch("msgbatch_cost_test")

    assert out["succeeded"] == 2
    # Find the UPDATE on ai_batches and verify cost_usd is non-zero.
    updates = [c for c in captured_sql if "UPDATE ai_batches" in c[0]]
    assert len(updates) == 1
    sql, params = updates[0]
    assert "cost_usd" in sql, "UPDATE must write cost_usd column"
    assert params[1] == 42  # batch_pk
    # Expected: 2 messages × (1000 * $1/M input + 200 * $5/M output)
    #         = 2 × ($0.001 + $0.001) = $0.004
    expected_cost = 2 * (1000 * (1.0 / 1_000_000) + 200 * (5.0 / 1_000_000))
    assert abs(params[0] - expected_cost) < 1e-9, (
        f"Expected cost ~${expected_cost:.6f}, got ${params[0]:.6f}"
    )


def test_ingest_batch_writes_zero_cost_when_no_successful_results():
    """A batch where every result errored should still write cost_usd=0
    (not NULL) so the column reliably reflects ingest history."""
    from docket.ai.batch_ingest import ingest_batch

    errored = MagicMock()
    errored.custom_id = "stage1-999-v1"
    errored.result.type = "errored"

    captured_sql = []

    with patch("docket.ai.batch_ingest.db") as mock_db, \
         patch("docket.ai.batch_ingest.anthropic.Anthropic") as anthropic_cls, \
         patch("docket.ai.batch_ingest._mark_failed_permanent"):
        cur = mock_db.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (43, "stage1", None)
        cur.execute.side_effect = lambda *args, **kwargs: captured_sql.append(args)

        anthropic_client = MagicMock()
        anthropic_cls.return_value = anthropic_client
        anthropic_client.messages.batches.results.return_value = iter([errored])

        out = ingest_batch("msgbatch_all_errored")

    assert out["errored"] == 1
    assert out["succeeded"] == 0
    updates = [c for c in captured_sql if "UPDATE ai_batches" in c[0]]
    assert len(updates) == 1
    _, params = updates[0]
    assert params[0] == 0.0  # cost_usd
    assert params[1] == 43  # batch_pk
