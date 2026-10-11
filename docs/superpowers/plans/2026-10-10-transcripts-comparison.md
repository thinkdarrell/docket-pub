# Meeting Transcripts Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the raw transcripts the Legion uploads into resolved speakers, an event timeline, and a human-reviewed public "Minutes vs. Video" comparison, run by one Railway cron task.

**Architecture:** A new `docket.ai.transcripts` package holds three LLM stages (speaker resolution and event extraction on Sonnet 5.5, comparison on Opus 5.5 as judge and hunter) plus deterministic steps (index-point item assignment, a word-count fitness gate, minutes capture with page offsets, the aligner, the citation guard, the vote check). A `transcript_pipeline` cron task claims `transcripts` rows by status with the OCR skip-locked pattern and advances them `uploaded → speakers_resolved → events_extracted → compared`. Every LLM call goes through a structured-outputs sibling of the v2 client that writes `ai_runs` rows so the daily budget applies. Discrepancies land as `proposed`, an admin queue approves or rejects them, and only `approved` rows render publicly behind the `MINUTES_VS_VIDEO_UI` flag, which the operator flips once the 70 percent ship gate is met.

**Tech Stack:** Python 3.10, Flask + Jinja + HTMX 2, PostgreSQL 18 (pg_trgm), psycopg2, anthropic SDK 0.104.1 (`output_config.format` structured outputs, `count_tokens`, `stop_details`), pydantic 2, pdfplumber, requests, APScheduler, pytest.

**Spec:** `docs/superpowers/specs/2026-10-05-meeting-transcripts-design.md` (Sections 3 and 4 are this plan's core; Section 5 admin queue, speaker correction, public block, operational surfaces; Section 6 live tests and ship gate)

**Plan 1 (done, PR #99, live):** `docs/superpowers/plans/2026-10-07-transcripts-foundation.md`. Migration 035, the `transcriber` role, the producer, the transcript page, item excerpt, search, data debt, scale check. This plan adds one migration, 036 (final-review fix wave): it drops the `minutes_discrepancies_has_event` CHECK and adds `minutes_texts.last_checked_at`; every table it writes already exists.

**Facts from the first real run (2026-10-10) this plan accounts for:**

- Real rows exist on Railway: meeting 2543 (2026-10-06, 104 min, about 11.3K words, 192 segments, 24 diarization clusters) and about ten more arriving. Task 3 exports meeting 2543 as the stage fixture; the plan 1 fixture (three segments) is too small for anything but route tests.
- Granicus has junk clips that get transcribed anyway (meeting 2544 is a 6-minute "mic check", 24 words). Task 4's fitness gate moves such rows to `low_speech` before any LLM call and Task 4 surfaces them on the data debt page regardless of recording length.
- Diarization over-clusters: 24 clusters for one meeting. Speaker resolution (Tasks 6 and 7) expects many clusters per person and merges them by resolving each to the same member.
- The first ~15 minutes of a meeting is pre-meeting silence recorded as one `is_silence` turn. Every stage filters `is_silence = FALSE AND text <> ''`.
- Speaker rows are keyed by `(meeting_id, cluster_label)` (migration 035), not by transcript id. Writes use that key and never touch `is_manual = TRUE` rows.
- The plan 1 upload leaves `transcript_segments.agenda_item_id` NULL. Task 4 adds the deterministic index-point assignment the spec describes, so the transcript page gets item markers as soon as the worker touches a transcript.
- Consent items are mostly silent in the audio (PR #104 notes): the chair reads item numbers only, so agenda titles never appear. The extraction prompt passes the agenda with numbers and ids and tells the model to map spoken numbers to ids; the consent motion and vote carry every id in the effective block.
- Items added on the floor have no `agenda_items` row (PR #104 notes). Events about them carry an empty `agenda_item_refs` and name the item in `detail.unlisted_item`; the aligner groups those by that text (Task 10) instead of dropping them into the meeting-level bucket.
- 19 junk Monday test-stream meetings were hidden by hand on 2026-10-11 (PR #103 runbook). The claim query excludes `is_hidden` meetings, and the fitness gate catches the next mic-check clip before it costs an LLM call.

## Global Constraints

- Birmingham only. Every claim query filters `mu.slug = 'birmingham'`, `m.external_id ~ '^[0-9]+$'`, and `m.is_hidden = FALSE`.
- Models: `claude-sonnet-5-5` for speaker resolution and event extraction, `claude-opus-5-5` for comparison. Haiku (`claude-haiku-4-5-20251001`, the id already in `PRICING`) only in the Task 18 experiment. Model ids come from `docket.config`, never hard-coded in a stage.
- Structured outputs, never forced tool choice. Requests carry `output_config={"effort": ..., "format": {"type": "json_schema", "schema": ...}}` and never a `tool_choice` or `thinking` key (Opus 5.5 and Sonnet 5.5 return 400 on forced `tool_choice`; Opus 5.5 returns 400 on `thinking: disabled`). `effort` is always set explicitly because Opus 5.5 defaults to `medium`.
- Stop reason is checked before parsing. `refusal` and `max_tokens` fail the row as `AIPermanentRowError`; the pipeline maps that to `needs_review` with the reason.
- Every LLM call writes an `ai_runs` row through `docket.ai.worker._open_run` / `_close_run` so `AI_DAILY_BUDGET_USD` sees the spend. `ai_runs.stage` values for this plan: `transcript_speakers`, `transcript_events`, `transcript_compare`, `transcript_ab`. `ai_runs.stage` has no CHECK constraint; `ai_batches.stage` does and is not touched.
- Prompt versions are the 200-series: `SPEAKER_PROMPT_VERSION = 200`, `EVENTS_PROMPT_VERSION = 200`, `COMPARE_PROMPT_VERSION = 200`. They are written only to `meeting_events.prompt_version` and `minutes_discrepancies.prompt_version`, never to `agenda_items.ai_rewrite_version` or `meetings.ai_prompt_version`, so the `>= 3` card dispatcher and the `mv_city_backfill_ratio` gate never see them.
- Token ceiling: `count_tokens` runs before every call; a count above `TRANSCRIPT_TOKEN_CEILING` (default 500,000) holds the transcript as `needs_review` with reason `token_ceiling`. No chunking.
- Candidate cap: more than `TRANSCRIPT_CANDIDATE_CAP` (default 40) aligner candidates holds the transcript as `needs_review` with reason `candidate_cap`.
- Fitness floor: `TRANSCRIPT_MIN_WORDS` (default 300). An `uploaded` transcript under the floor becomes `low_speech` with `last_error = 'word_count N below floor 300'` and spends no LLM call.
- Failure states per stage: `stage_attempts` is bumped at claim time, 24-hour backoff lives in the claim query, the third failed attempt sets `failed`. `stage_attempts` resets to 0 when a stage succeeds.
- The materiality fragment `MATERIALITY_FRAGMENT` is one string included verbatim in the transcript extraction prompt, the judge prompt, and the hunter prompt. A unit test asserts byte equality.
- The citation guard normalizes both sides identically (NFKC, soft hyphens removed, hyphenated line breaks joined, quotes unified, whitespace collapsed, lowercased) before substring matching, then a fuzzy window pass at ratio ≥ 0.92. `citation_match` records which pass matched. Rows with `citation_match = 'missing'` cannot be approved until a reviewer attaches a citation that the guard verifies.
- Only `review_state = 'approved'` rows render publicly, and only when `current_app.config["MINUTES_VS_VIDEO_UI"]` is true. `stale`, `proposed`, `rejected`, `dismissed_by_model` never render publicly.
- Model text is never overwritten. Admin edits go to `admin_title` and `admin_description`.
- Manual speaker assignments (`is_manual = TRUE`) are never changed by the stage; the UPDATE carries `AND is_manual = FALSE`.
- New admin routes live in their own blueprint `admin_transcripts` with login enforced in `before_request` and CSRF validated on every POST (session token, hidden `csrf_token` field). Repo-wide CSRF for the older admin routes is issue #83 and stays out of scope.
- Public copy for the comparison block uses the honesty-protocol voice: what was compared, that a person reviewed it, that the minutes remain the official record, link to `/about/how-we-read-minutes/`. No em dashes in new user-facing copy.
- Transcript text and model text are never marked `| safe` in a template.
- Live tests carry `pytestmark = pytest.mark.live` and skip when `ANTHROPIC_API_KEY` is unset or equals the root conftest's dummy value `test-dummy-key-not-for-real-api-calls`. Run them with `pytest -m live tests/live/<file>`.
- Integration tests refuse to run when `DATABASE_URL` contains `railway.internal`, `railway.app`, or `rlwy.net`, and own their cleanup (no global rollback).
- Commits use `git -c user.email=hello@docket.pub` and end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Run the root suite as `venv/bin/python -m pytest tests ...` and the producer suite separately as `pytest transcriber/tests`; both directories are packages named `tests`, so a bare `pytest` fails collection (PR #103 runbook note). The venv at the repo root has anthropic 0.104.1.

## Review Focus

Inputs the spec implies but no obvious task test covers, most likely to bite first. Each has a test pinned to the owning task below.

1. **A minutes URL that returns an HTML page (login wall, Granicus error) instead of a PDF.** Expected: minutes capture returns None, the transcript stops at `events_extracted` with `compare_skipped_reason = 'minutes_unavailable'`, nothing is marked `failed`, and the next day's tick retries. Pinned to Tasks 8 and 9.
2. **A judge verdict whose quoted excerpt the guard cannot find on either side.** Expected: the row is still written as `proposed` with `citation_match = 'missing'` and confidence halved, it appears in the queue with the Approve button disabled, and `approve()` refuses it server-side with a flashed error and no state change. Pinned to Tasks 11 and 14.
3. **An admin approving a row that a re-comparison set to `stale` between page load and click.** Expected: a flashed error on redirect, no state change, the row stays `stale`. Pinned to Task 14.
4. **Two clusters resolved to the same council member, one by the model and one by hand.** Expected: the transcript page's speaker index lists the member once with combined turn counts, and the search `speaker:` filter returns both clusters' turns. Pinned to Task 16.
5. **A consent item pulled on the floor and also recorded as pulled in the minutes.** Expected: both effective consent blocks exclude it, the item becomes its own group on both sides, and no `consent_block`, `omission`, or `addition` candidate is produced for the pull itself. Pinned to Task 10.

## File Structure

**`src/docket/ai/transcripts/` (new package, all LLM stages and deterministic steps):**
- `__init__.py`
- `client.py` — `StructuredClient` (structured-outputs sibling of v2 `AIClient`), `build_request`, `count_tokens`, stop-reason checks (Task 1)
- `prompts.py` — 200-series versions, `MATERIALITY_FRAGMENT`, system prompts for all five calls (Task 2)
- `schemas.py` — JSON schemas for `output_config.format` and the pydantic models that validate responses (Task 2)
- `pipeline.py` — claim SQL, `run_transcript_pipeline`, status advance, failure mapping, fitness gate, index-point assignment (Task 4)
- `speakers.py` — roster, roll-call and chair-address signal finders, utterance sampler, prompt rendering, resolution writes (Tasks 6 and 7)
- `minutes.py` — PDF download with the browser user agent, page-aware extraction, `minutes_texts` upsert and change detection (Task 8)
- `events.py` — transcript and minutes rendering, extraction calls, `meeting_events` writes, segment re-assignment from `item_opened` (Task 9)
- `aligner.py` — pure: effective consent blocks, grouping, pairing, LCS sequence check, actor matching, vote-outcome check, `Candidate` (Task 10)
- `guard.py` — pure: normalization, exact and fuzzy citation matching, offset mapping, `canonical_statute` (Task 5)
- `compare.py` — judge and hunter prompts, candidate cap, discrepancy writes, re-comparison reconciliation (Tasks 11 and 12)
- `alerts.py` — `post_alert`, stalled-producer check (Task 13)
- `ab.py` — Haiku vs Sonnet extraction comparison used by the script (Task 18)

**Repo root (Railway app), modified:**
- `src/docket/config.py` — model names, ceilings, caps, floor, webhook URL (Task 1)
- `src/docket/ai/pricing.py` — `claude-sonnet-5-5` and `claude-opus-5-5` rates (Task 1)
- `src/docket/ai/exceptions.py` — `TranscriptHeld` (Task 4)
- `src/docket/worker/tasks.py`, `src/docket/worker/scheduler.py`, `src/docket/worker/health.py` — `transcript_pipeline` at 10:00 America/Chicago (Task 4)
- `src/docket/services/transcripts.py` — public predicate for failed-after-upload rows, too-short debt rows, `speaker_index` (Tasks 4 and 16)
- `src/docket/services/discrepancies.py` — queue reads, approve/reject/edit, ship-gate ratio, public reads (Task 14)
- `src/docket/services/speaker_correction.py` — cluster listing, reassign, release (Task 15)
- `src/docket/web/csrf.py` — session CSRF token helper (Task 14)
- `src/docket/web/admin_transcripts.py` — blueprint: discrepancy queue, speaker correction, retry (Tasks 14 and 15)
- `src/docket/web/admin.py` — AI panel rows (Task 17)
- `src/docket/web/public.py` — meeting and item context, `/minutes-vs-video/`, transcript page speaker index (Task 16)
- `src/docket/web/__init__.py` — register blueprint, `MINUTES_VS_VIDEO_UI` flag, CSRF global (Tasks 14 and 16)
- Templates: `admin/review_discrepancies.html`, `admin/_discrepancy_row.html`, `admin/speaker_correction.html`, `admin/ai_panel.html`, `partials/minutes_vs_video.html`, `minutes_vs_video.html`, `partials/transcript_body.html`, `meeting_detail.html`, `item_detail.html`, `about_methodology.html`, `data_debt.html`
- `scripts/export_transcript_fixture.py` (Task 3), `scripts/transcript_recompare.py` (Task 12), `scripts/transcript_extraction_ab.py` (Task 18)
- `docs/runbooks/transcript-pipeline.md` (Task 19)

**Tests:**
- `tests/support/__init__.py`, `tests/support/transcript_fixtures.py` — fixture bundle loader and installer, SRT parser (Task 3)
- `tests/fixtures/transcript_2543/` — exported real rows (Task 3)
- `tests/unit/test_transcript_client.py`, `test_transcript_prompts.py`, `test_transcript_schemas.py`, `test_transcript_fitness.py`, `test_speaker_signals.py`, `test_minutes_extract.py`, `test_events_render.py`, `test_aligner.py`, `test_guard.py`, `test_compare_render.py`, `test_alerts.py`, `test_csrf.py`, `test_ship_gate.py`
- `tests/integration/test_transcript_pipeline.py`, `test_speaker_stage.py`, `test_events_stage.py`, `test_compare_stage.py`, `test_recompare.py`, `test_admin_discrepancies.py`, `test_admin_speakers.py`, `test_minutes_vs_video_public.py`
- `tests/live/test_transcript_structured_smoke.py` (Task 1), `tests/live/test_transcript_pilot_e2e.py`, `tests/live/test_transcript_chaotic.py`, `tests/live/test_transcript_ab.py` (Task 18)

---

### Task 1: Structured-outputs client, pricing, config, and the first live smoke test

**Files:**
- Create: `src/docket/ai/transcripts/__init__.py`, `src/docket/ai/transcripts/client.py`
- Modify: `src/docket/config.py`, `src/docket/ai/pricing.py:33-46`
- Test: `tests/unit/test_transcript_client.py`, `tests/live/test_transcript_structured_smoke.py`

**Interfaces:**
- Consumes: `docket.ai.exceptions` (`AIFatalError`, `AIPermanentRowError`, `AIRateLimited`, `AITransientError`), `docket.ai.pricing.Usage`, `docket.ai.pricing.track_usage`.
- Produces:
  - `build_request(*, model: str, system: str, user: str, schema: dict, max_tokens: int = 16000, effort: str = "medium") -> dict` — the exact kwargs for `messages.stream(...)`; never contains `tool_choice`, `tools`, or `thinking`.
  - `class StructuredClient` with `count_tokens(*, model, system, user) -> int` and `call(*, model, system, user, schema, max_tokens=16000, effort="medium") -> StructuredResult`.
  - `@dataclass(frozen=True) StructuredResult(data: dict, usage: Usage, model: str, stop_reason: str)`.
  - Config: `AI_TRANSCRIPT_SPEAKER_MODEL`, `AI_TRANSCRIPT_EVENTS_MODEL` (both default `claude-sonnet-5-5`), `AI_TRANSCRIPT_COMPARE_MODEL` (default `claude-opus-5-5`), `TRANSCRIPT_TOKEN_CEILING = 500000`, `TRANSCRIPT_CANDIDATE_CAP = 40`, `TRANSCRIPT_PER_TICK = 5`, `TRANSCRIPT_MIN_WORDS = 300`, `ALERT_WEBHOOK_URL: str | None`.
  - `PRICING["claude-sonnet-5-5"]` and `PRICING["claude-opus-5-5"]`.

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/unit/test_transcript_client.py
"""StructuredClient: request shape, stop-reason handling, retry ladder, usage."""
import json
from unittest.mock import MagicMock, patch

import pytest
from anthropic import RateLimitError

from docket.ai.exceptions import AIPermanentRowError, AIRateLimited
from docket.ai.transcripts.client import StructuredClient, build_request

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
          "required": ["answer"], "additionalProperties": False}


def _message(text: str | None, stop_reason: str = "end_turn", category: str | None = None):
    msg = MagicMock()
    msg.stop_reason = stop_reason
    msg.stop_details = MagicMock(category=category) if stop_reason == "refusal" else None
    thinking = MagicMock(); thinking.type = "thinking"; thinking.thinking = ""
    blocks = [thinking]
    if text is not None:
        tb = MagicMock(); tb.type = "text"; tb.text = text
        blocks.append(tb)
    msg.content = blocks
    msg.usage = MagicMock(input_tokens=120, cache_creation_input_tokens=0,
                          cache_read_input_tokens=100, output_tokens=30)
    return msg


def _client_with(message):
    with patch("docket.ai.transcripts.client.Anthropic") as cls:
        inst = MagicMock()
        cls.return_value = inst
        inst.messages.stream.return_value.__enter__.return_value.get_final_message.return_value = message
        c = StructuredClient(api_key="k")
        return c, inst


def test_build_request_uses_output_config_and_never_tool_choice():
    req = build_request(model="claude-opus-5-5", system="S", user="U", schema=SCHEMA, effort="high")
    assert req["output_config"] == {"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}}
    assert "tool_choice" not in req and "tools" not in req and "thinking" not in req
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert req["messages"] == [{"role": "user", "content": "U"}]


def test_call_parses_first_text_block_and_skips_thinking():
    c, inst = _client_with(_message(json.dumps({"answer": "yes"})))
    res = c.call(model="claude-sonnet-5-5", system="S", user="U", schema=SCHEMA)
    assert res.data == {"answer": "yes"}
    assert res.usage.input_tokens == 120 and res.usage.cache_read_input_tokens == 100
    kwargs = inst.messages.stream.call_args.kwargs
    assert kwargs["output_config"]["format"]["schema"] is SCHEMA
    assert "tool_choice" not in kwargs


def test_refusal_stop_reason_is_permanent_row_error():
    c, _ = _client_with(_message(None, stop_reason="refusal", category="cyber"))
    with pytest.raises(AIPermanentRowError, match="refusal: cyber"):
        c.call(model="claude-opus-5-5", system="S", user="U", schema=SCHEMA)


def test_max_tokens_stop_reason_is_permanent_row_error():
    c, _ = _client_with(_message('{"answer": "trunc', stop_reason="max_tokens"))
    with pytest.raises(AIPermanentRowError, match="max_tokens"):
        c.call(model="claude-opus-5-5", system="S", user="U", schema=SCHEMA)


def test_invalid_json_is_permanent_row_error():
    c, _ = _client_with(_message("not json"))
    with pytest.raises(AIPermanentRowError, match="invalid JSON"):
        c.call(model="claude-opus-5-5", system="S", user="U", schema=SCHEMA)


def test_rate_limit_honors_retry_after_then_raises():
    with patch("docket.ai.transcripts.client.Anthropic") as cls, \
         patch("docket.ai.transcripts.client.time.sleep") as sleep:
        inst = MagicMock(); cls.return_value = inst
        resp = MagicMock(); resp.headers = {"retry-after": "7"}; resp.status_code = 429
        inst.messages.stream.side_effect = RateLimitError("rl", response=resp, body=None)
        c = StructuredClient(api_key="k")
        with pytest.raises(AIRateLimited):
            c.call(model="claude-opus-5-5", system="S", user="U", schema=SCHEMA)
        assert sleep.call_args_list[0].args[0] == 7.0
        assert inst.messages.stream.call_count == 3


def test_count_tokens_passes_system_and_user():
    with patch("docket.ai.transcripts.client.Anthropic") as cls:
        inst = MagicMock(); cls.return_value = inst
        inst.messages.count_tokens.return_value = MagicMock(input_tokens=4321)
        c = StructuredClient(api_key="k")
        assert c.count_tokens(model="claude-sonnet-5-5", system="S", user="U") == 4321
        kwargs = inst.messages.count_tokens.call_args.kwargs
        assert kwargs["model"] == "claude-sonnet-5-5"
        assert kwargs["messages"] == [{"role": "user", "content": "U"}]


def test_pricing_has_both_new_models():
    from docket.ai.pricing import PRICING, Usage, calculate_cost_usd
    for m in ("claude-sonnet-5-5", "claude-opus-5-5"):
        assert set(PRICING[m]) == {"input", "output", "cache_creation", "cache_read"}
    cost = calculate_cost_usd("claude-opus-5-5", Usage(1_000_000, 0, 0, 0))
    assert abs(cost - 4.00) < 1e-9
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/unit/test_transcript_client.py -v`
Expected: all FAIL with `ModuleNotFoundError: docket.ai.transcripts`.

- [ ] **Step 3: Config and pricing**

Append to `src/docket/config.py`:

```python
# Transcript pipeline (spec 2026-10-05 Sections 3-4; plan 2026-10-10).
# Sonnet 5.5 resolves speakers and extracts events; Opus 5.5 judges and
# hunts discrepancies. Haiku is an A/B experiment, never a default here.
AI_TRANSCRIPT_SPEAKER_MODEL: str = os.environ.get("AI_TRANSCRIPT_SPEAKER_MODEL", "claude-sonnet-5-5")
AI_TRANSCRIPT_EVENTS_MODEL: str = os.environ.get("AI_TRANSCRIPT_EVENTS_MODEL", "claude-sonnet-5-5")
AI_TRANSCRIPT_COMPARE_MODEL: str = os.environ.get("AI_TRANSCRIPT_COMPARE_MODEL", "claude-opus-5-5")
# Guards against runaway cost from a bad input, not against long meetings:
# a twelve-hour hearing plus a 300-page packet is about 300K tokens.
TRANSCRIPT_TOKEN_CEILING: int = int(os.environ.get("TRANSCRIPT_TOKEN_CEILING", "500000"))
# More candidates than this usually means a timestamp offset, not 40 problems.
TRANSCRIPT_CANDIDATE_CAP: int = int(os.environ.get("TRANSCRIPT_CANDIDATE_CAP", "40"))
TRANSCRIPT_PER_TICK: int = int(os.environ.get("TRANSCRIPT_PER_TICK", "5"))
# Granicus junk clips (a 6-minute mic check had 24 words) get transcribed;
# anything under this many words is not a meeting and gets no LLM call.
TRANSCRIPT_MIN_WORDS: int = int(os.environ.get("TRANSCRIPT_MIN_WORDS", "300"))
# Outbound alert webhook (Slack or Discord incoming webhook). Unset = silent.
ALERT_WEBHOOK_URL: str | None = os.environ.get("ALERT_WEBHOOK_URL") or None
```

In `src/docket/ai/pricing.py`, extend `PRICING` (rates per token; Anthropic first-party list price 2026-10-10: Sonnet 5.5 $2 / $10 per MTok with $0.20 cache reads, Opus 5.5 $4 / $20 with $0.20 cache reads; cache creation is 1.25x input on both):

```python
    "claude-sonnet-5-5": {
        "input":          2.00 / 1_000_000,
        "output":        10.00 / 1_000_000,
        "cache_creation": 2.50 / 1_000_000,
        "cache_read":     0.20 / 1_000_000,
    },
    "claude-opus-5-5": {
        "input":          4.00 / 1_000_000,
        "output":        20.00 / 1_000_000,
        "cache_creation": 5.00 / 1_000_000,
        "cache_read":     0.20 / 1_000_000,
    },
```

Update the module docstring's "Verified against" date to 2026-10-10.

- [ ] **Step 4: Write the client**

`src/docket/ai/transcripts/__init__.py`:

```python
"""Transcript LLM stages: speaker resolution, event extraction, comparison.

Spec: docs/superpowers/specs/2026-10-05-meeting-transcripts-design.md, Sections 3-4.
Every Anthropic call in this package goes through ``client.StructuredClient``.
"""
```

`src/docket/ai/transcripts/client.py`:

```python
"""Structured-outputs sibling of ``docket.ai.client.AIClient``.

Mirrors v2's retry ladder exactly (RateLimitError honors retry-after,
timeouts and 5xx back off, 401/403 are fatal, other 4xx are permanent) and
keeps v2's system-prompt cache breakpoint. It replaces forced tool choice,
which Opus 5.5 and Sonnet 5.5 reject with a 400, with
``output_config.format`` (spec decision H). Calls stream so a long event
list never trips the SDK's non-streaming timeout; ``stop_reason`` is checked
before the JSON is parsed; usage is emitted through ``track_usage`` so the
pipeline can roll it into ``ai_runs.cost_usd``.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from anthropic import Anthropic, APIError, APIStatusError, APITimeoutError, RateLimitError

from docket.ai.exceptions import AIFatalError, AIPermanentRowError, AIRateLimited, AITransientError
from docket.ai.pricing import Usage, track_usage

log = logging.getLogger(__name__)

MAX_RETRIES = 3


@dataclass(frozen=True)
class StructuredResult:
    data: dict
    usage: Usage
    model: str
    stop_reason: str


def build_request(*, model: str, system: str, user: str, schema: dict,
                  max_tokens: int = 16000, effort: str = "medium") -> dict[str, Any]:
    """Parameter dict for ``messages.stream``; same shape the Batches API takes.

    No ``tools``, no ``tool_choice``, no ``thinking``: the 5.5 models reject
    forced tool choice and Opus 5.5 rejects disabled thinking. Effort is set
    explicitly because Opus 5.5 defaults to ``medium``.
    """
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
        "output_config": {"effort": effort,
                          "format": {"type": "json_schema", "schema": schema}},
    }


class StructuredClient:
    def __init__(self, api_key: str | None = None):
        from docket.config import ANTHROPIC_API_KEY
        key = api_key or ANTHROPIC_API_KEY
        if not key:
            raise AIFatalError("ANTHROPIC_API_KEY is not set")
        self._client = Anthropic(api_key=key)

    def count_tokens(self, *, model: str, system: str, user: str) -> int:
        """Server-side count for the ceiling check. Free; model-specific."""
        resp = self._client.messages.count_tokens(
            model=model,
            system=[{"type": "text", "text": system}],
            messages=[{"role": "user", "content": user}],
        )
        return int(resp.input_tokens)

    def call(self, *, model: str, system: str, user: str, schema: dict,
             max_tokens: int = 16000, effort: str = "medium") -> StructuredResult:
        params = build_request(model=model, system=system, user=user, schema=schema,
                               max_tokens=max_tokens, effort=effort)

        def _once():
            with self._client.messages.stream(**params) as stream:
                return stream.get_final_message()

        message = _with_retries(_once)
        stop = getattr(message, "stop_reason", None) or ""
        if stop == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) if details is not None else None
            raise AIPermanentRowError(f"refusal: {category or 'uncategorized'}")
        if stop == "max_tokens":
            raise AIPermanentRowError(f"max_tokens: output hit the {max_tokens} ceiling")
        text = next((b.text for b in message.content if getattr(b, "type", None) == "text"), None)
        if text is None:
            raise AIPermanentRowError("no text block in structured response")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise AIPermanentRowError(f"invalid JSON in structured response: {e}") from e
        usage = _extract_usage(message)
        track_usage(model, usage)
        return StructuredResult(data=data, usage=usage, model=model, stop_reason=stop)


def _with_retries(fn: Callable[[], Any]):
    """v2 ``AIClient._call_with_retries`` ladder, lifted out so it wraps any callable."""
    last_exc: Exception | None = None
    delay = 2.0
    for attempt in range(MAX_RETRIES):
        try:
            return fn()
        except RateLimitError as e:
            last_exc = e
            retry_after = float(e.response.headers.get("retry-after", delay)) if hasattr(e, "response") else delay
            log.warning("Rate limited (attempt %d/%d); sleeping %.1fs", attempt + 1, MAX_RETRIES, retry_after)
            time.sleep(retry_after)
            delay *= 2
        except APITimeoutError as e:
            last_exc = e
            log.warning("Timeout (attempt %d/%d); backoff %.1fs", attempt + 1, MAX_RETRIES, delay)
            time.sleep(delay)
            delay *= 2
        except APIStatusError as e:
            if e.status_code in (401, 403):
                raise AIFatalError(f"Auth error from Anthropic: {e}") from e
            if e.status_code == 400:
                raise AIPermanentRowError(f"Bad request to Anthropic: {e}") from e
            if e.status_code >= 500:
                last_exc = e
                log.warning("5xx (attempt %d/%d); backoff %.1fs", attempt + 1, MAX_RETRIES, delay)
                time.sleep(delay)
                delay *= 2
            else:
                raise AIPermanentRowError(f"Unexpected status from Anthropic: {e}") from e
        except APIError as e:
            last_exc = e
            log.warning("Generic API error (attempt %d/%d): %s", attempt + 1, MAX_RETRIES, e)
            time.sleep(delay)
            delay *= 2
    if isinstance(last_exc, RateLimitError):
        raise AIRateLimited("Rate limit retries exhausted") from last_exc
    raise AITransientError(f"Transient retries exhausted: {last_exc}") from last_exc


def _extract_usage(message) -> Usage:
    u = message.usage
    return Usage(
        input_tokens=getattr(u, "input_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        output_tokens=getattr(u, "output_tokens", 0) or 0,
    )
```

- [ ] **Step 5: Run to verify pass**

Run: `venv/bin/python -m pytest tests/unit/test_transcript_client.py tests/unit/test_ai_pricing.py -v`
Expected: all PASS (the existing pricing tests still pass with two more models).

- [ ] **Step 6: Write the live smoke test (house rule: before any prompt exists)**

```python
# tests/live/test_transcript_structured_smoke.py
"""LIVE: output_config.format on both transcript models. ~$0.02 per run.

Run: venv/bin/python -m pytest -m live tests/live/test_transcript_structured_smoke.py -v -s
Exercises every JSON Schema feature the production schemas use (nullable
type arrays, enums, nested arrays of objects, additionalProperties false)
so a rejected keyword fails here, before Task 7 builds on it.
"""
import os

import pytest

from docket.ai.transcripts.client import StructuredClient
from docket.config import AI_TRANSCRIPT_COMPARE_MODEL, AI_TRANSCRIPT_EVENTS_MODEL

pytestmark = pytest.mark.live

DUMMY = "test-dummy-key-not-for-real-api-calls"


@pytest.fixture
def client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or key == DUMMY:
        pytest.skip("real ANTHROPIC_API_KEY not set")
    return StructuredClient(api_key=key)


PROBE_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_type": {"type": "string", "enum": ["motion", "vote", "statement"]},
                    "agenda_item_refs": {"type": "array", "items": {"type": "integer"}},
                    "actor_member_id": {"type": ["integer", "null"]},
                    "quote": {"type": ["string", "null"]},
                    "detail": {
                        "type": "object",
                        "properties": {"result": {"type": ["string", "null"]},
                                       "yeas": {"type": ["integer", "null"]}},
                        "required": ["result", "yeas"],
                        "additionalProperties": False,
                    },
                },
                "required": ["event_type", "agenda_item_refs", "actor_member_id", "quote", "detail"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["events"],
    "additionalProperties": False,
}

USER = ("Transcript:\n[seq=4 t=00:10:02 Chair] Motion to approve item 12. Is there a second?\n"
        "[seq=5 t=00:10:05 Speaker 3] Second.\n[seq=6 t=00:10:09 Chair] All in favor. Item 12 passes, 8 to 0.\n"
        "Agenda items: id 912 = Item 12. Emit one motion event and one vote event. "
        "Quote the exact transcript text for each. actor_member_id is null here.")


@pytest.mark.parametrize("model", [AI_TRANSCRIPT_EVENTS_MODEL, AI_TRANSCRIPT_COMPARE_MODEL])
def test_structured_output_round_trip(client, model):
    assert client.count_tokens(model=model, system="You extract council events.", user=USER) > 20
    res = client.call(model=model, system="You extract council events as JSON.", user=USER,
                      schema=PROBE_SCHEMA, max_tokens=4000, effort="low")
    assert res.stop_reason == "end_turn"
    types = [e["event_type"] for e in res.data["events"]]
    assert "motion" in types and "vote" in types
    vote = next(e for e in res.data["events"] if e["event_type"] == "vote")
    assert vote["agenda_item_refs"] == [912]
    assert vote["detail"]["yeas"] == 8
    assert vote["quote"] and "passes" in vote["quote"]
    assert res.usage.input_tokens > 0 and res.usage.output_tokens > 0
    print(f"\n{model}: {res.data}")
```

- [ ] **Step 7: Run the live smoke test**

Run: `ANTHROPIC_API_KEY=$(railway variables --service docket-web --kv | grep '^ANTHROPIC_API_KEY=' | cut -d= -f2-) venv/bin/python -m pytest -m live tests/live/test_transcript_structured_smoke.py -v -s`
Expected: 2 PASS, both models return the schema shape. If either model rejects a schema keyword (400 → `AIPermanentRowError: Bad request`), fix the schema style here and carry the fix into Task 2 before continuing. Record the printed outputs in the PR description.

- [ ] **Step 8: Commit**

```bash
git add src/docket/ai/transcripts/__init__.py src/docket/ai/transcripts/client.py src/docket/config.py src/docket/ai/pricing.py tests/unit/test_transcript_client.py tests/live/test_transcript_structured_smoke.py
git -c user.email=hello@docket.pub commit -m "feat(ai): structured-outputs client for transcript stages; price Sonnet 5.5 and Opus 5.5

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: 200-series prompt family, materiality fragment, and response schemas

**Files:**
- Create: `src/docket/ai/transcripts/prompts.py`, `src/docket/ai/transcripts/schemas.py`
- Test: `tests/unit/test_transcript_prompts.py`, `tests/unit/test_transcript_schemas.py`, `tests/live/test_transcript_structured_smoke.py` (add one test)

**Interfaces:**
- Produces (prompts): `SPEAKER_PROMPT_VERSION = 200`, `EVENTS_PROMPT_VERSION = 200`, `COMPARE_PROMPT_VERSION = 200`, `MATERIALITY_FRAGMENT: str`, `SPEAKER_SYSTEM`, `EVENTS_TRANSCRIPT_SYSTEM`, `EVENTS_MINUTES_SYSTEM`, `JUDGE_SYSTEM`, `HUNTER_SYSTEM` (all `str`).
- Produces (schemas): JSON schema dicts `SPEAKER_SCHEMA`, `EVENTS_SCHEMA`, `JUDGE_SCHEMA`, `HUNTER_SCHEMA`; pydantic models `SpeakerAssignment`, `SpeakerResolution(assignments: list[SpeakerAssignment])`, `EventDetail`, `ExtractedEvent`, `EventList(events: list[ExtractedEvent])`, `Verdict`, `JudgeResult(verdicts: list[Verdict])`, `HuntedDiscrepancy`, `HunterResult(discrepancies: list[HuntedDiscrepancy])`; `EVENT_TYPES: tuple[str, ...]` matching migration 035's CHECK list exactly.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_transcript_prompts.py
from docket.ai.transcripts import prompts as P


def test_versions_are_200_series():
    for v in (P.SPEAKER_PROMPT_VERSION, P.EVENTS_PROMPT_VERSION, P.COMPARE_PROMPT_VERSION):
        assert 200 <= v < 300


def test_materiality_fragment_is_byte_identical_in_all_three_prompts():
    frag = P.MATERIALITY_FRAGMENT
    assert len(frag) > 400
    for text in (P.EVENTS_TRANSCRIPT_SYSTEM, P.JUDGE_SYSTEM, P.HUNTER_SYSTEM):
        assert frag in text
    # The minutes side extracts what is written, not what is material; it must not filter.
    assert frag not in P.EVENTS_MINUTES_SYSTEM


def test_fragment_carries_pilot_examples():
    f = P.MATERIALITY_FRAGMENT
    assert "not in the packet" in f           # positive example (O'Quinn)
    assert "criminal justice information" in f  # positive example (city attorney)
    assert "clarifying question" in f           # negative example


def test_speaker_prompt_states_the_two_signal_rule_and_response_rule():
    s = P.SPEAKER_SYSTEM
    assert "two independent signals" in s
    assert "here" in s and "present" in s and "aye" in s
    assert "quote the utterance" in s.lower()


def test_extraction_prompts_handle_consent_by_number_and_unlisted_items():
    for text in (P.EVENTS_TRANSCRIPT_SYSTEM, P.EVENTS_MINUTES_SYSTEM):
        assert "unlisted_item" in text and "by number" in text


def test_prompts_tell_the_model_to_quote_exactly_as_shown():
    for text in (P.JUDGE_SYSTEM, P.HUNTER_SYSTEM, P.EVENTS_TRANSCRIPT_SYSTEM, P.EVENTS_MINUTES_SYSTEM):
        assert "exactly as shown" in text
```

```python
# tests/unit/test_transcript_schemas.py
import json

import pytest
from pydantic import ValidationError

from docket.ai.transcripts import schemas as S

MIG_EVENT_TYPES = ('item_opened', 'item_deferred', 'consent_amendment', 'motion', 'second',
                   'amendment', 'vote', 'executive_session_motion', 'recusal',
                   'procedural_ruling', 'roll_call', 'recess', 'reconvene', 'adjourn',
                   'public_comment', 'statement')


def test_event_types_match_migration_035():
    assert tuple(S.EVENT_TYPES) == MIG_EVENT_TYPES
    assert S.EVENTS_SCHEMA["properties"]["events"]["items"]["properties"]["event_type"]["enum"] == list(MIG_EVENT_TYPES)


def _closed(schema: dict) -> bool:
    if schema.get("type") == "object" or isinstance(schema.get("properties"), dict):
        if schema.get("additionalProperties") is not False:
            return False
        if set(schema.get("required", [])) != set(schema.get("properties", {})):
            return False
        return all(_closed(v) for v in schema["properties"].values())
    if "items" in schema:
        return _closed(schema["items"])
    return True


@pytest.mark.parametrize("schema", [S.SPEAKER_SCHEMA, S.EVENTS_SCHEMA, S.JUDGE_SCHEMA, S.HUNTER_SCHEMA])
def test_schemas_are_closed_objects_with_every_property_required(schema):
    # Structured outputs want every property listed in required and no open objects.
    assert _closed(schema), json.dumps(schema)[:200]


def test_event_round_trips_through_pydantic():
    ev = S.ExtractedEvent.model_validate({
        "event_type": "vote", "scope": "item", "agenda_item_refs": [912],
        "actor_text": "Council President", "actor_member_id": None,
        "summary": "Item 12 passes 8-0",
        "detail": {"result": "passed", "yeas": 8, "nays": 0, "method": "voice"},
        "segment_seq": 6, "page": None, "quote": "Item 12 passes, 8 to 0.",
    })
    assert ev.detail.result == "passed" and ev.detail.abstentions is None
    assert "unlisted_item" in S.EVENT_DETAIL_SCHEMA["properties"]


def test_bad_event_type_rejected():
    with pytest.raises(ValidationError):
        S.ExtractedEvent.model_validate({"event_type": "pledge", "scope": "meeting", "agenda_item_refs": [],
                                         "actor_text": None, "actor_member_id": None, "summary": "x",
                                         "detail": {}, "segment_seq": None, "page": None, "quote": None})


def test_speaker_assignment_confidence_bounds():
    with pytest.raises(ValidationError):
        S.SpeakerAssignment.model_validate({"cluster_label": "S1", "council_member_id": None, "display_name": "Clerk",
                                            "role": "clerk", "confidence": 1.4, "method": "sample_inference",
                                            "evidence_quote": "x", "evidence_quote_2": None})
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/unit/test_transcript_prompts.py tests/unit/test_transcript_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `prompts.py`**

```python
# src/docket/ai/transcripts/prompts.py
"""200-series prompt family for the transcript stages.

The item and meeting dispatchers gate on ``ai_rewrite_version >= 3`` and
``ai_prompt_version``; these versions are written only to
``meeting_events.prompt_version`` and ``minutes_discrepancies.prompt_version``.
Bumping a stage's version resets that stage and later ones only
(pipeline.reset_for_version).
"""
from __future__ import annotations

SPEAKER_PROMPT_VERSION = 200
EVENTS_PROMPT_VERSION = 200
COMPARE_PROMPT_VERSION = 200

# One fragment, included byte-for-byte in the transcript extraction prompt,
# the judge prompt, and the hunter prompt (spec Section 3, shared materiality).
MATERIALITY_FRAGMENT = """## What counts as material

A statement or difference is material when it changes or records one of:
- a commitment (who will do what, by when),
- a dollar figure (an amount, a rate, a budget line),
- a legal position or a statute citation (including the stated ground for an executive session),
- a stated reason for a decision,
- a procedural ruling (point of order, suspension of rules, an attorney's ruling on what the body may do),
- a vote outcome, who moved or seconded, a recusal, or the order of a vote relative to a closed session.

Positive examples from the 2026-02-17 Birmingham meeting, Item 15:
- The city attorney explaining that the agreement verifies Alabama Power's license plate reader cameras give access to the Alabama criminal justice information system and binds them to its rules. That is a material fact about what the item does.
- Councilor O'Quinn noting that the agreement itself is not in the packet. That is a material fact about what the council was asked to approve.
- The attorney recommending executive session "under 36-25A-7(a)(4) to discuss security plans and measures." The cited ground is a legal position.

Negative examples:
- A clarifying question answered with a procedural fact ("Is this item 14 or 15?" "Fifteen."). Not material.
- Invocation, pledge, thanks, roll-call responses, and the chair restating which item is up. Not material.
- Wording differences that leave the meaning intact ("approved" versus "adopted"). Minor, not material.

Extraction captures at a lower threshold (record anything that might be material). Comparison filters at the threshold above.
"""

SPEAKER_SYSTEM = """You identify who is speaking in a machine transcript of a Birmingham, Alabama city council meeting.

The transcript was split into anonymous speaker clusters by a diarization model. The diarizer over-splits: one person often appears as several clusters, and occasionally two people share one cluster. Resolving several clusters to the same person is normal and expected.

You are given the roster of council members seated on the meeting date (with ids), deterministic candidate signals the pipeline found (roll-call pairs and chair addresses, each with the exact utterances), and for every cluster a sample of its utterances spread across the meeting with speaking-time statistics.

Rules:
- Signals, in priority order: a roll-call pair (the clerk reads a name and the next cluster answers with a short response such as "here", "present", "yes", "no", or "aye"); the chair addressing a member by name followed by that cluster speaking substantively; self-identification; then the content of the sampled utterances.
- Never trust "the next cluster to speak" blindly. A roll-call response counts only if the next utterance is short and matches an expected response. A floor yield counts only if the next utterance is substantive (more than a few words) and reads as the addressed member speaking; a cough, a mic bump, or a two-word interjection is skipped and the following cluster is considered instead.
- High confidence (0.85 or above) requires two independent signals agreeing, for example a roll-call pair and a later address by the chair. A single signal caps at medium confidence (0.75). Content-only inference caps at 0.55.
- For every assignment, quote the utterance you relied on in evidence_quote, exactly as shown in the transcript. If a second independent signal exists, quote it in evidence_quote_2. The pipeline verifies these quotes against the cluster's own text and lowers confidence when they do not match.
- A cluster that clearly mixes two voices gets confidence below 0.5 and role "unknown".
- Non-council speakers (mayor, clerk, city attorney, department staff, members of the public) get a role and a display_name when the transcript names them, and council_member_id null. Roles: council, mayor, clerk, attorney, staff, public, unknown.
- Use council_member_id only for ids in the roster you were given. Never invent a name.

Return one assignment per cluster label you were given, in the same order.
"""

_QUOTE_RULE = """Quote source text exactly as shown, including transcription errors, odd capitalization, and artifacts. Do not clean up, paraphrase, or fix spelling inside a quote. The pipeline verifies every quote by substring match against the same text you are reading."""

EVENTS_TRANSCRIPT_SYSTEM = f"""You extract the event timeline from a machine transcript of a Birmingham city council meeting.

Each transcript line is `[seq=N t=HH:MM:SS Speaker] text`. The agenda is listed with ids, item numbers, titles, and consent flags. Index-point markers (`=== Item ...`) show where the clerk clicked an item open; they can be a few seconds late.

Emit events of these types only: item_opened, item_deferred, consent_amendment, motion, second, amendment, vote, executive_session_motion, recusal, procedural_ruling, roll_call, recess, reconvene, adjourn, public_comment, statement. Fill `detail` fields that apply and leave the others null. Set `scope` to item, consent_block, or meeting, and `agenda_item_refs` to the agenda item ids the event concerns (a consent motion and vote list every item in the block; a meeting-level event has an empty list). Set `segment_seq` to the seq of the line where the event happens and `quote` to that line's text or the part of it that shows the event. Leave `page` null.

The chair usually reads consent items by number only ("items 3 through 14 and 17"), so agenda titles rarely appear in the audio: map spoken numbers to the agenda ids you were given, and give the consent motion and vote every id in the block as moved, after any items pulled or added on the floor. An item taken up that is not on the agenda list has no id: leave `agenda_item_refs` empty and put the item as the chair described it in `detail.unlisted_item`.

Fold a second into `motion.detail.seconder`; emit a standalone `second` only when the second is contested. Record vote tallies as spoken (`result`, `yeas`, `nays`, `abstentions`, `method`, and `roll_call_names` when names were read). For an executive session motion record `stated_reason` and `statute_cite` as spoken. Do not extract invocation, pledge, or ordinary clarifying exchanges.

{_QUOTE_RULE}

{MATERIALITY_FRAGMENT}
Record `statement` events for anything that meets the lower extraction threshold, with `detail.kind` one of commitment, dollar_figure, legal_position, stated_reason, material_fact and `detail.as_stated` carrying the words used.

Order events by seq. Return JSON only.
"""

EVENTS_MINUTES_SYSTEM = f"""You extract the event timeline from the official minutes of a Birmingham city council meeting, as text extracted from the clerk's PDF.

Page markers `[[page N]]` show where each page starts. The agenda is listed with ids, item numbers, titles, and consent flags.

Emit events of these types only: item_opened, item_deferred, consent_amendment, motion, second, amendment, vote, executive_session_motion, recusal, procedural_ruling, roll_call, recess, reconvene, adjourn, public_comment, statement. Fill `detail` fields that apply and leave the others null. Set `scope` and `agenda_item_refs` as the minutes describe them (a consent motion and vote list every item the minutes group under it). Set `page` to the page the event appears on and `quote` to the sentence or clause in the minutes that records it. Leave `segment_seq` null.

Minutes refer to consent items by number and resolution number; map them to the agenda ids you were given. An item the minutes record that is not on the agenda list has no id: leave `agenda_item_refs` empty and put the item as the minutes describe it in `detail.unlisted_item`.

Record the minutes as written, in the order written. Do not infer what probably happened; the comparison stage judges that. Record vote tallies, movers, seconders, and stated reasons exactly as the minutes state them. For an executive session motion record `stated_reason` and `statute_cite` as written, including when the minutes paraphrase a statute without a number.

{_QUOTE_RULE}

Order events by their position in the text. Return JSON only.
"""

JUDGE_SYSTEM = f"""You judge candidate discrepancies between what was said at a Birmingham city council meeting (machine transcript) and what the official minutes record.

A deterministic aligner paired the two event timelines and produced candidates: a transcript event with no minutes counterpart (omission), a minutes event with no transcript counterpart (addition), a pair with differing details (wording, speaker, vote_outcome), or a pair out of order (sequence). For each candidate you receive both timelines, the candidate's events, and a window of the transcript around the transcript event and of the minutes around the minutes event.

For each candidate decide whether it is a real discrepancy a careful reader of both records would agree is there. Dismiss candidates that are artifacts: the same action recorded in different words, a transcription error, an aligner pairing mistake, or an ordinary exchange that the minutes rightly omit. When a candidate is real, assign the category (vote_outcome, omission, addition, wording, sequence, speaker) and severity, write a one-line title and a two-to-four sentence description in plain language that names what each record says, and quote the supporting excerpt from each side. When you dismiss a candidate, give the reason in dismiss_reason and leave the other fields null.

Severity: material when the discrepancy changes a legal basis, an outcome, who acted, a recusal, or the order of a vote relative to a closed session. Minor when wording differs and the meaning does not.

{_QUOTE_RULE} A quote must come from the window you were shown for that side.

{MATERIALITY_FRAGMENT}
Return one verdict per candidate_id, in the order given. Return JSON only.
"""

HUNTER_SYSTEM = f"""You look for discrepancies between what was said at a Birmingham city council meeting (machine transcript) and what the official minutes record that a deterministic aligner missed.

You receive the full transcript, the full minutes text, both extracted timelines, and the list of candidates the aligner already found (do not repeat those). Report only discrepancies that are not already in that list and that a careful reader of both records would agree are there. Prefer precision over volume; an empty list is a good answer when the records agree.

For each discrepancy give category (vote_outcome, omission, addition, wording, sequence, speaker), severity, a one-line title, a two-to-four sentence description that names what each record says, the agenda item ids concerned, the transcript quote with its segment_seq when the transcript side exists, and the minutes quote with its page when the minutes side exists. At least one side must be quoted.

Severity: material when the discrepancy changes a legal basis, an outcome, who acted, a recusal, or the order of a vote relative to a closed session. Minor when wording differs and the meaning does not.

{_QUOTE_RULE}

{MATERIALITY_FRAGMENT}
Return JSON only.
"""
```

- [ ] **Step 4: Write `schemas.py`**

```python
# src/docket/ai/transcripts/schemas.py
"""JSON schemas for output_config.format and the pydantic models that validate responses.

Every object is closed (additionalProperties false) and lists every property
in `required`; optional values are nullable types. Keep the pydantic models
and the dicts in sync: the schema is what the API enforces, the model is what
the stage code trusts.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EVENT_TYPES: tuple[str, ...] = (
    "item_opened", "item_deferred", "consent_amendment", "motion", "second", "amendment", "vote",
    "executive_session_motion", "recusal", "procedural_ruling", "roll_call", "recess",
    "reconvene", "adjourn", "public_comment", "statement",
)
SCOPES = ("item", "consent_block", "meeting")
CATEGORIES = ("vote_outcome", "omission", "addition", "wording", "sequence", "speaker")
SEVERITIES = ("material", "minor")
ROLES = ("council", "mayor", "clerk", "attorney", "staff", "public", "unknown")
SPEAKER_METHODS = ("roll_call", "addressed_by_chair", "self_identification", "sample_inference")


def _nullable(t: str) -> dict:
    return {"type": [t, "null"]}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _arr(items: dict) -> dict:
    return {"type": "array", "items": items}


_STR_ARR = _arr({"type": "string"})

SPEAKER_SCHEMA = _obj({
    "assignments": _arr(_obj({
        "cluster_label": {"type": "string"},
        "council_member_id": _nullable("integer"),
        "display_name": _nullable("string"),
        "role": {"type": "string", "enum": list(ROLES)},
        "confidence": {"type": "number"},
        "method": {"type": "string", "enum": list(SPEAKER_METHODS)},
        "evidence_quote": {"type": "string"},
        "evidence_quote_2": _nullable("string"),
    }))
})

EVENT_DETAIL_SCHEMA = _obj({
    "action": _nullable("string"), "to_date": _nullable("string"), "as_stated": _nullable("string"),
    "items": _nullable("array") | {"items": {"type": "integer"}},
    "requested_by": _nullable("string"), "mover": _nullable("string"), "seconder": _nullable("string"),
    "what_changed": _nullable("string"), "result": _nullable("string"),
    "yeas": _nullable("integer"), "nays": _nullable("integer"), "abstentions": _nullable("integer"),
    "roll_call_names": _nullable("array") | {"items": {"type": "string"}},
    "method": _nullable("string"), "stated_reason": _nullable("string"), "statute_cite": _nullable("string"),
    "member": _nullable("string"), "kind": _nullable("string"), "ruling": _nullable("string"),
    "present": _nullable("array") | {"items": {"type": "string"}},
    "absent": _nullable("array") | {"items": {"type": "string"}},
    "clock_time": _nullable("string"), "speaker_text": _nullable("string"), "topic": _nullable("string"),
    # Floor-added items have no agenda_items row (PR #104 notes): name them here, leave agenda_item_refs empty.
    "unlisted_item": _nullable("string"),
})

EVENTS_SCHEMA = _obj({
    "events": _arr(_obj({
        "event_type": {"type": "string", "enum": list(EVENT_TYPES)},
        "scope": {"type": "string", "enum": list(SCOPES)},
        "agenda_item_refs": _arr({"type": "integer"}),
        "actor_text": _nullable("string"),
        "actor_member_id": _nullable("integer"),
        "summary": {"type": "string"},
        "detail": EVENT_DETAIL_SCHEMA,
        "segment_seq": _nullable("integer"),
        "page": _nullable("integer"),
        "quote": _nullable("string"),
    }))
})

JUDGE_SCHEMA = _obj({
    "verdicts": _arr(_obj({
        "candidate_id": {"type": "integer"},
        "is_real": {"type": "boolean"},
        "category": {"type": ["string", "null"], "enum": list(CATEGORIES) + [None]},
        "severity": {"type": ["string", "null"], "enum": list(SEVERITIES) + [None]},
        "title": _nullable("string"),
        "description": _nullable("string"),
        "transcript_quote": _nullable("string"),
        "minutes_quote": _nullable("string"),
        "confidence": {"type": "number"},
        "dismiss_reason": _nullable("string"),
    }))
})

HUNTER_SCHEMA = _obj({
    "discrepancies": _arr(_obj({
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "agenda_item_refs": _arr({"type": "integer"}),
        "transcript_quote": _nullable("string"),
        "transcript_segment_seq": _nullable("integer"),
        "minutes_quote": _nullable("string"),
        "minutes_page": _nullable("integer"),
        "confidence": {"type": "number"},
    }))
})


# --- pydantic models -------------------------------------------------------

class SpeakerAssignment(BaseModel):
    cluster_label: str
    council_member_id: int | None
    display_name: str | None
    role: Literal["council", "mayor", "clerk", "attorney", "staff", "public", "unknown"]
    confidence: float = Field(ge=0.0, le=1.0)
    method: Literal["roll_call", "addressed_by_chair", "self_identification", "sample_inference"]
    evidence_quote: str
    evidence_quote_2: str | None = None


class SpeakerResolution(BaseModel):
    assignments: list[SpeakerAssignment]


class EventDetail(BaseModel):
    action: str | None = None
    to_date: str | None = None
    as_stated: str | None = None
    items: list[int] | None = None
    requested_by: str | None = None
    mover: str | None = None
    seconder: str | None = None
    what_changed: str | None = None
    result: str | None = None
    yeas: int | None = None
    nays: int | None = None
    abstentions: int | None = None
    roll_call_names: list[str] | None = None
    method: str | None = None
    stated_reason: str | None = None
    statute_cite: str | None = None
    member: str | None = None
    kind: str | None = None
    ruling: str | None = None
    present: list[str] | None = None
    absent: list[str] | None = None
    clock_time: str | None = None
    speaker_text: str | None = None
    topic: str | None = None
    unlisted_item: str | None = None

    def compact(self) -> dict:
        """Only the non-null fields, for the JSONB column."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


class ExtractedEvent(BaseModel):
    event_type: Literal[EVENT_TYPES]  # type: ignore[valid-type]
    scope: Literal["item", "consent_block", "meeting"]
    agenda_item_refs: list[int]
    actor_text: str | None
    actor_member_id: int | None
    summary: str
    detail: EventDetail
    segment_seq: int | None
    page: int | None
    quote: str | None


class EventList(BaseModel):
    events: list[ExtractedEvent]


class Verdict(BaseModel):
    candidate_id: int
    is_real: bool
    category: Literal[CATEGORIES] | None  # type: ignore[valid-type]
    severity: Literal["material", "minor"] | None
    title: str | None
    description: str | None
    transcript_quote: str | None
    minutes_quote: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    dismiss_reason: str | None


class JudgeResult(BaseModel):
    verdicts: list[Verdict]


class HuntedDiscrepancy(BaseModel):
    category: Literal[CATEGORIES]  # type: ignore[valid-type]
    severity: Literal["material", "minor"]
    title: str
    description: str
    agenda_item_refs: list[int]
    transcript_quote: str | None
    transcript_segment_seq: int | None
    minutes_quote: str | None
    minutes_page: int | None
    confidence: float = Field(ge=0.0, le=1.0)


class HunterResult(BaseModel):
    discrepancies: list[HuntedDiscrepancy]
```

`Literal[EVENT_TYPES]` with a tuple variable is not valid at runtime; write the literals out (`Literal["item_opened", "item_deferred", ...]`) in the file and keep `EVENT_TYPES` as the single list the schema and the test use. The `_nullable("array") | {...}` merge gives `{"type": ["array", "null"], "items": {...}}`.

- [ ] **Step 5: Run to verify pass**

Run: `venv/bin/python -m pytest tests/unit/test_transcript_prompts.py tests/unit/test_transcript_schemas.py -v`
Expected: all PASS.

- [ ] **Step 6: Add the production-schema acceptance probe to the live smoke test**

Append to `tests/live/test_transcript_structured_smoke.py`:

```python
from docket.ai.transcripts import schemas as S


@pytest.mark.parametrize("schema,model", [
    (S.SPEAKER_SCHEMA, AI_TRANSCRIPT_EVENTS_MODEL),
    (S.EVENTS_SCHEMA, AI_TRANSCRIPT_EVENTS_MODEL),
    (S.JUDGE_SCHEMA, AI_TRANSCRIPT_COMPARE_MODEL),
    (S.HUNTER_SCHEMA, AI_TRANSCRIPT_COMPARE_MODEL),
])
def test_production_schemas_are_accepted(client, schema, model):
    """Each schema is accepted by the model that will use it. Empty-list answers are fine."""
    res = client.call(model=model, system="Return an empty result that fits the schema.",
                      user="There is no input. Return the schema's top-level array empty.",
                      schema=schema, max_tokens=2000, effort="low")
    (key,) = schema["properties"].keys()
    assert res.data[key] == []
```

Run: `ANTHROPIC_API_KEY=... venv/bin/python -m pytest -m live tests/live/test_transcript_structured_smoke.py -v`
Expected: 6 PASS. A 400 here means a schema keyword the API rejects (for example the `enum` containing `null`); fix in `schemas.py` and re-run before Task 7.

- [ ] **Step 7: Commit**

```bash
git add src/docket/ai/transcripts/prompts.py src/docket/ai/transcripts/schemas.py tests/unit/test_transcript_prompts.py tests/unit/test_transcript_schemas.py tests/live/test_transcript_structured_smoke.py
git -c user.email=hello@docket.pub commit -m "feat(ai): 200-series transcript prompts, materiality fragment, response schemas

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Real-row fixture from meeting 2543 and the fixture loaders

**Files:**
- Create: `scripts/export_transcript_fixture.py`, `tests/support/__init__.py`, `tests/support/transcript_fixtures.py`, `tests/fixtures/transcript_2543/` (exported files + `README.md`)
- Test: `tests/unit/test_transcript_fixtures.py`, `tests/integration/test_fixture_install.py`

**Interfaces:**
- Produces:
  - `scripts/export_transcript_fixture.py --meeting-id N --out DIR` — read-only export of `meetings`, `agenda_items`, roster, `transcript_segments`, `transcript_speakers` (embedding dropped), `votes` + `member_votes` + `vote_agenda_items`, and the minutes PDF text when the download works. Files: `meeting.json`, `agenda_items.json`, `roster.json`, `segments.json`, `speakers.json`, `votes.json`, `minutes.txt`, `minutes_pages.json`.
  - `tests.support.transcript_fixtures.Bundle` dataclass; `load_bundle(name: str) -> Bundle`; `pilot_bundle() -> Bundle` (meeting 15 from the plan 1 pilot files: SRT segments offset by `PILOT_CLIP_OFFSET_S = 3290.0`, minutes text split on form feeds into pages, one agenda item "15" with `video_timestamp_seconds=3309`, `external_id='1950-15'`); `parse_srt(path, *, offset_s=0.0, cluster_label=None) -> list[dict]`.
  - `install_bundle(bundle, *, status="uploaded", external_id="999543") -> Installed` with `meeting_id`, `transcript_id`, `item_ids: dict[int, int]` (fixture id → local id), `member_ids: dict[int, int]`, `cleanup()`. Members are matched to existing `council_members` rows by name, else inserted with `term_start = '2025-10-28'`. `agenda_item_refs` in later tests are remapped through `item_ids`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_transcript_fixtures.py
from pathlib import Path

from tests.support.transcript_fixtures import PILOT_CLIP_OFFSET_S, load_bundle, parse_srt, pilot_bundle


def test_parse_srt_offsets_and_numbers_segments():
    segs = parse_srt(Path("tests/fixtures/transcript_pilot/2026-02-17_clip1950_item15_small-en.srt"),
                     offset_s=PILOT_CLIP_OFFSET_S, cluster_label="S0")
    assert segs[0]["seq"] == 0 and segs[0]["start_s"] == 3290.0
    assert segs[1]["start_s"] == 3290.0 + 5.86
    assert all(s["cluster_label"] == "S0" and s["is_silence"] is False for s in segs)
    assert "CGI access security agreement" in segs[0]["text"]


def test_pilot_bundle_has_minutes_pages_and_item_15():
    b = pilot_bundle()
    assert b.meeting["meeting_date"] == "2026-02-17"
    assert len(b.minutes_pages) > 10 and b.minutes_pages[0] == 0
    assert "pending litigation" in b.minutes_text
    (item,) = b.agenda_items
    assert item["item_number"] == "15" and item["video_timestamp_seconds"] == 3309
    assert len(b.roster) >= 9


def test_2543_bundle_is_the_real_meeting():
    b = load_bundle("transcript_2543")
    assert b.meeting["meeting_date"] == "2026-10-06"
    assert len(b.segments) > 150
    clusters = {s["cluster_label"] for s in b.segments if s["cluster_label"]}
    assert len(clusters) >= 20                      # the over-clustering the stages must survive
    assert any(s["is_silence"] for s in b.segments)  # the pre-meeting silence turn
    assert sum(len(s["text"].split()) for s in b.segments) > 10_000
```

```python
# tests/integration/test_fixture_install.py
import pytest

from docket.config import DATABASE_URL
from docket.db import db_cursor
from tests.support.transcript_fixtures import install_bundle, load_bundle, pilot_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


def test_install_and_cleanup_round_trip():
    inst = install_bundle(load_bundle("transcript_2543"))
    try:
        with db_cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM transcript_segments WHERE transcript_id=%s", [inst.transcript_id])
            assert cur.fetchone()["n"] > 150
            cur.execute("SELECT status, word_count FROM transcripts WHERE id=%s", [inst.transcript_id])
            row = cur.fetchone()
            assert row["status"] == "uploaded" and row["word_count"] > 10_000
            cur.execute("SELECT count(*) AS n FROM transcript_speakers WHERE meeting_id=%s", [inst.meeting_id])
            assert cur.fetchone()["n"] >= 20
    finally:
        inst.cleanup()
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM meetings WHERE id=%s", [inst.meeting_id])
        assert cur.fetchone() is None


def test_pilot_install_has_minutes_and_item():
    inst = install_bundle(pilot_bundle(), external_id="999015")
    try:
        with db_cursor() as cur:
            cur.execute("SELECT text, page_offsets FROM minutes_texts WHERE meeting_id=%s", [inst.meeting_id])
            row = cur.fetchone()
            assert "Executive Session" in row["text"] and len(row["page_offsets"]) > 10
            cur.execute("SELECT external_id FROM agenda_items WHERE meeting_id=%s", [inst.meeting_id])
            assert cur.fetchone()["external_id"] == "1950-15"
    finally:
        inst.cleanup()
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/unit/test_transcript_fixtures.py -v`
Expected: FAIL, `ModuleNotFoundError: tests.support`.

- [ ] **Step 3: Write the export script**

```python
#!/usr/bin/env python
# scripts/export_transcript_fixture.py
"""Export one meeting's transcript rows as a test fixture bundle (read-only).

    DATABASE_URL=$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-) \
      venv/bin/python scripts/export_transcript_fixture.py --meeting-id 2543 --out tests/fixtures/transcript_2543

Embeddings are dropped (they are phase 2 input and large). Minutes text is
included only when the minutes PDF downloads; the pipeline's own extractor
(docket.ai.transcripts.minutes) does the page-aware extraction so the fixture
matches production byte-for-byte.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from docket.db import db_cursor


def _rows(cur, sql, params):
    cur.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def export(meeting_id: int, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with db_cursor() as cur:
        meeting = _rows(cur, """SELECT id, external_id, title, meeting_date::text, meeting_type, video_url,
                                        minutes_url, agenda_url FROM meetings WHERE id=%s""", [meeting_id])[0]
        items = _rows(cur, """SELECT id, external_id, item_number, title, is_consent, video_timestamp_seconds
                                FROM agenda_items WHERE meeting_id=%s ORDER BY video_timestamp_seconds NULLS LAST, id""",
                      [meeting_id])
        roster = _rows(cur, """SELECT cm.id, cm.name FROM council_members cm JOIN meetings m ON m.municipality_id = cm.municipality_id
                                WHERE m.id=%s AND m.meeting_date >= cm.term_start
                                  AND m.meeting_date < COALESCE(cm.term_end, m.meeting_date + INTERVAL '1 day')
                                ORDER BY cm.name""", [meeting_id])
        segs = _rows(cur, """SELECT s.seq, s.start_s, s.end_s, s.text, s.cluster_label, s.is_silence,
                                    s.avg_logprob, s.no_speech_prob
                               FROM transcript_segments s JOIN transcripts t ON t.id = s.transcript_id
                              WHERE t.meeting_id=%s ORDER BY s.seq""", [meeting_id])
        speakers = _rows(cur, """SELECT cluster_label, council_member_id, display_name, role, confidence, method, is_manual
                                   FROM transcript_speakers WHERE meeting_id=%s ORDER BY cluster_label""", [meeting_id])
        tr = _rows(cur, """SELECT version, engine, asr_model, diarization_model, audio_duration_s, speech_ratio, word_count
                             FROM transcripts WHERE meeting_id=%s""", [meeting_id])[0]
        votes = _rows(cur, """SELECT v.id, v.external_id, v.result, v.yeas, v.nays, v.abstentions, v.source, v.raw_text,
                                     COALESCE(json_agg(json_build_object('agenda_item_id', vai.agenda_item_id,
                                              'association_type', vai.association_type)) FILTER (WHERE vai.id IS NOT NULL), '[]') AS links
                                FROM votes v LEFT JOIN vote_agenda_items vai ON vai.vote_id = v.id AND vai.is_active
                               WHERE v.meeting_id=%s GROUP BY v.id ORDER BY v.id""", [meeting_id])
    meeting["transcript"] = tr
    (out / "meeting.json").write_text(json.dumps(meeting, indent=1, default=str))
    (out / "agenda_items.json").write_text(json.dumps(items, indent=1, default=str))
    (out / "roster.json").write_text(json.dumps(roster, indent=1))
    (out / "segments.json").write_text(json.dumps(segs, indent=1))
    (out / "speakers.json").write_text(json.dumps(speakers, indent=1))
    (out / "votes.json").write_text(json.dumps(votes, indent=1, default=str))
    if meeting.get("minutes_url"):
        from docket.ai.transcripts.minutes import download_minutes, extract_pages
        pdf = download_minutes(meeting["minutes_url"])
        if pdf:
            text, offsets = extract_pages(pdf)
            (out / "minutes.txt").write_text(text)
            (out / "minutes_pages.json").write_text(json.dumps(offsets))
    print(f"exported meeting {meeting_id}: {len(segs)} segments, {len(speakers)} clusters, {len(items)} items -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--meeting-id", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    export(a.meeting_id, a.out)
```

The minutes branch imports Task 8's module; until Task 8 lands, run the export without minutes (the `try/except ImportError` around that import prints "minutes skipped: module not yet available"). Add that guard.

- [ ] **Step 4: Write the loader and installer**

`tests/support/__init__.py` is empty. `tests/support/transcript_fixtures.py`:

```python
"""Fixture bundles for the transcript stages: the real meeting 2543 export and the meeting 15 pilot."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from docket.db import db_cursor

FIXTURES = Path("tests/fixtures")
PILOT = FIXTURES / "transcript_pilot"
PILOT_CLIP_OFFSET_S = 3290.0   # expected.json: the clip starts about 3290 s into the full video

_SRT_TIME = re.compile(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)")


def _t(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(path: Path, *, offset_s: float = 0.0, cluster_label: str | None = None) -> list[dict]:
    out, seq = [], 0
    blocks = path.read_text().strip().split("\n\n")
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        m = _SRT_TIME.match(lines[1])
        if not m:
            continue
        g = m.groups()
        text = " ".join(l.strip() for l in lines[2:]).strip()
        out.append({"seq": seq, "start_s": round(_t(*g[:4]) + offset_s, 3), "end_s": round(_t(*g[4:]) + offset_s, 3),
                    "text": text, "cluster_label": cluster_label, "is_silence": False,
                    "avg_logprob": None, "no_speech_prob": None})
        seq += 1
    return out


@dataclass
class Bundle:
    meeting: dict
    agenda_items: list[dict]
    roster: list[dict]
    segments: list[dict]
    speakers: list[dict] = field(default_factory=list)
    votes: list[dict] = field(default_factory=list)
    minutes_text: str | None = None
    minutes_pages: list[int] | None = None


def load_bundle(name: str) -> Bundle:
    d = FIXTURES / name
    j = lambda f: json.loads((d / f).read_text())
    minutes = (d / "minutes.txt").read_text() if (d / "minutes.txt").exists() else None
    pages = j("minutes_pages.json") if (d / "minutes_pages.json").exists() else None
    return Bundle(meeting=j("meeting.json"), agenda_items=j("agenda_items.json"), roster=j("roster.json"),
                  segments=j("segments.json"), speakers=j("speakers.json"),
                  votes=j("votes.json") if (d / "votes.json").exists() else [],
                  minutes_text=minutes, minutes_pages=pages)


PILOT_ROSTER_2026 = ["Darrell O'Quinn", "Wardine Alexander", "LaTonya Tate", "Clinton Woods", "J.T. Moore",
                     "Carol Clarke", "Crystal Smitherman", "Hunter Williams", "Valerie Abbott"]


def pilot_bundle() -> Bundle:
    raw = (PILOT / "2026-02-17_clip1950_minutes.txt").read_text()
    pages_text = raw.split("\f")
    offsets, pos = [], 0
    for p in pages_text:
        offsets.append(pos)
        pos += len(p) + 1
    text = "\n".join(pages_text)
    return Bundle(
        meeting={"id": 15, "external_id": "1950", "title": "City Council Meeting", "meeting_date": "2026-02-17",
                 "meeting_type": "council",
                 "video_url": "https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=1950",
                 "minutes_url": "https://bhamal.granicus.com/MinutesViewer.php?view_id=2&clip_id=1950",
                 "transcript": {"version": 1, "engine": "whisper.cpp", "asr_model": "ggml-small.en",
                                "diarization_model": None, "audio_duration_s": 530.6, "speech_ratio": 0.9,
                                "word_count": 650}},
        agenda_items=[{"id": 1501, "external_id": "1950-15", "item_number": "15",
                       "title": "Ordinance: CJI access security agreement with ALEA and Alabama Power",
                       "is_consent": False, "video_timestamp_seconds": 3309.0}],
        roster=[{"id": 9000 + i, "name": n} for i, n in enumerate(PILOT_ROSTER_2026)],
        segments=parse_srt(PILOT / "2026-02-17_clip1950_item15_small-en.srt", offset_s=PILOT_CLIP_OFFSET_S,
                           cluster_label="S0"),
        speakers=[{"cluster_label": "S0", "council_member_id": None, "display_name": None, "role": None,
                   "confidence": None, "method": None, "is_manual": False}],
        votes=[],
        minutes_text=text, minutes_pages=offsets,
    )


@dataclass
class Installed:
    meeting_id: int
    transcript_id: int
    item_ids: dict[int, int]
    member_ids: dict[int, int]
    _inserted_members: list[int]

    def cleanup(self) -> None:
        with db_cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE id=%s", [self.meeting_id])   # cascades to every transcript table
            if self._inserted_members:
                cur.execute("DELETE FROM council_members WHERE id = ANY(%s)", [self._inserted_members])


def install_bundle(b: Bundle, *, status: str = "uploaded", external_id: str = "999543") -> Installed:
    tr = b.meeting["transcript"]
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
        muni = cur.fetchone()["id"]
        member_ids, inserted = {}, []
        for m in b.roster:
            cur.execute("SELECT id FROM council_members WHERE municipality_id=%s AND name=%s ORDER BY id LIMIT 1",
                        [muni, m["name"]])
            row = cur.fetchone()
            if row:
                member_ids[m["id"]] = row["id"]
            else:
                cur.execute("""INSERT INTO council_members (municipality_id, name, term_start, active)
                               VALUES (%s, %s, '2025-10-28', TRUE) RETURNING id""", [muni, m["name"]])
                member_ids[m["id"]] = cur.fetchone()["id"]; inserted.append(member_ids[m["id"]])
        cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, meeting_type, external_id, video_url, minutes_url)
                       VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                    [muni, b.meeting["title"], b.meeting["meeting_date"], b.meeting.get("meeting_type") or "council",
                     external_id, b.meeting.get("video_url"), b.meeting.get("minutes_url")])
        mid = cur.fetchone()["id"]
        cur.execute("INSERT INTO processing_status (meeting_id) VALUES (%s)", [mid])
        item_ids = {}
        for it in b.agenda_items:
            cur.execute("""INSERT INTO agenda_items (meeting_id, external_id, item_number, title, is_consent, video_timestamp_seconds)
                           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                        [mid, it.get("external_id"), it.get("item_number"), it["title"], bool(it.get("is_consent")),
                         it.get("video_timestamp_seconds")])
            item_ids[it["id"]] = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcripts (meeting_id, status, version, engine, asr_model, diarization_model,
                                                audio_duration_s, speech_ratio, word_count, uploaded_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now()) RETURNING id""",
                    [mid, status, tr["version"], tr.get("engine"), tr.get("asr_model"), tr.get("diarization_model"),
                     tr.get("audio_duration_s"), tr.get("speech_ratio"), tr.get("word_count")])
        tid = cur.fetchone()["id"]
        sp_ids = {}
        for sp in b.speakers:
            cur.execute("""INSERT INTO transcript_speakers (meeting_id, cluster_label, council_member_id, display_name, role,
                                                            confidence, method, is_manual)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                        [mid, sp["cluster_label"], member_ids.get(sp.get("council_member_id")), sp.get("display_name"),
                         sp.get("role"), sp.get("confidence"), sp.get("method"), bool(sp.get("is_manual"))])
            sp_ids[sp["cluster_label"]] = cur.fetchone()["id"]
        for s in b.segments:
            cur.execute("""INSERT INTO transcript_segments (transcript_id, seq, start_s, end_s, text, cluster_label, speaker_id,
                                                            is_silence, avg_logprob, no_speech_prob)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        [tid, s["seq"], s["start_s"], s["end_s"], s["text"], s.get("cluster_label"),
                         sp_ids.get(s.get("cluster_label")), bool(s.get("is_silence")), s.get("avg_logprob"),
                         s.get("no_speech_prob")])
        for v in b.votes:
            cur.execute("""INSERT INTO votes (meeting_id, external_id, result, yeas, nays, abstentions, source, raw_text)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                        [mid, v.get("external_id"), v["result"], v.get("yeas"), v.get("nays"), v.get("abstentions"),
                         v.get("source") or "minutes_text", v.get("raw_text")])
            vid = cur.fetchone()["id"]
            for link in v.get("links") or []:
                if link["agenda_item_id"] in item_ids:
                    cur.execute("""INSERT INTO vote_agenda_items (vote_id, agenda_item_id, association_type, match_confidence)
                                   VALUES (%s, %s, %s, 1.0)""", [vid, item_ids[link["agenda_item_id"]], link["association_type"]])
        if b.minutes_text is not None:
            cur.execute("""INSERT INTO minutes_texts (meeting_id, source_url, pdf_sha256, text, page_offsets)
                           VALUES (%s, %s, 'fixture', %s, %s::jsonb)""",
                        [mid, b.meeting.get("minutes_url"), b.minutes_text, json.dumps(b.minutes_pages or [0])])
    return Installed(mid, tid, item_ids, member_ids, inserted)
```

- [ ] **Step 5: Export meeting 2543 (operator step, read-only, public proxy)**

Run:

```bash
DATABASE_URL=$(railway variables --service docket-web --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-) \
  venv/bin/python scripts/export_transcript_fixture.py --meeting-id 2543 --out tests/fixtures/transcript_2543
```

Expected: `exported meeting 2543: 192 segments, 24 clusters, N items`. Write `tests/fixtures/transcript_2543/README.md` with provenance (meeting 2543 = Birmingham City Council 2026-10-06, Granicus clip in `meeting.json`, transcribed on the Legion 2026-10-10 with faster-whisper large-v3 + pyannote 3.1, exported with this script, embeddings dropped, minutes absent if not yet adopted). If `segments.json` exceeds 2 MB, something is wrong (192 segments is about 150 KB).

- [ ] **Step 6: Run to verify pass**

Run: `venv/bin/python -m pytest tests/unit/test_transcript_fixtures.py tests/integration/test_fixture_install.py -v`
Expected: 5 PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/export_transcript_fixture.py tests/support tests/fixtures/transcript_2543 tests/unit/test_transcript_fixtures.py tests/integration/test_fixture_install.py
git -c user.email=hello@docket.pub commit -m "test(transcripts): meeting 2543 fixture bundle, pilot bundle, installer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Pipeline skeleton — claim, fitness gate, index points, status advance, cron

**Files:**
- Create: `src/docket/ai/transcripts/pipeline.py`
- Modify: `src/docket/ai/exceptions.py`, `src/docket/worker/tasks.py`, `src/docket/worker/scheduler.py`, `src/docket/worker/health.py:20`, `src/docket/services/transcripts.py` (`public_predicate`, debt labels)
- Test: `tests/unit/test_transcript_fitness.py`, `tests/integration/test_transcript_pipeline.py`, `tests/unit/test_worker_scheduler_transcripts.py`

**Interfaces:**
- Consumes: `docket.ai.worker._open_run`, `_close_run`, `_today_spend`, `RunSummary`, `BudgetExceededError`; `docket.ai.pricing.usage_capture`, `calculate_cost_usd`; `StructuredClient` (Task 1).
- Produces:
  - `class TranscriptHeld(AIError)` with `.reason: str` (one of `token_ceiling`, `candidate_cap`, `schema_invalid`, `refusal`, `max_tokens`, `permanent`) in `docket.ai.exceptions`.
  - `@dataclass StageOutcome(next_status: str, skipped_reason: str | None = None, detail: str = "")`.
  - `claim_next() -> dict | None` with keys `id, meeting_id, status, version, word_count, compare_skipped_reason`.
  - `assign_index_points(transcript_id: int, meeting_id: int) -> int` (segments updated).
  - `fitness_reason(word_count: int | None, floor: int) -> str | None`.
  - `process_claim(claim: dict, *, client, notes: str) -> str` returning one of `advanced, skipped, low_speech, held, failed, transient, rate_limited`.
  - `run_transcript_pipeline(*, limit: int = TRANSCRIPT_PER_TICK, notes: str = "cron_transcripts", force_budget: bool = False, client=None) -> PipelineSummary`.
  - `_stage_fn(stage: str) -> Callable[[dict], StageOutcome]` resolving `speakers.run_speaker_stage`, `events.run_events_stage`, `compare.run_compare_stage` lazily (Tasks 7, 9, 11 supply them; tests patch this).
  - `mark_needs_review(transcript_id, reason, detail)`, `mark_transient(transcript_id, detail) -> str` (returns resulting status), `advance(transcript_id, outcome: StageOutcome)`.
  - Worker: `TASKS["transcript_pipeline"]`, cron 10:00 America/Chicago, `HEALTHCHECK_TRANSCRIPT_PIPELINE_UUID`.
  - `docket.services.transcripts.public_predicate(alias: str) -> str` used by `get_public_transcript`, `excerpt_for_item`, `search_transcripts`.

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/unit/test_transcript_fitness.py
from docket.ai.transcripts.pipeline import CLAIM_SQL, STAGE_FOR_STATUS, fitness_reason


def test_fitness_floor_catches_the_mic_check():
    assert fitness_reason(24, 300) == "word_count 24 below floor 300"
    assert fitness_reason(None, 300) == "word_count unknown"
    assert fitness_reason(300, 300) is None
    assert fitness_reason(11_300, 300) is None


def test_claim_sql_is_birmingham_newest_first_skip_locked():
    assert "mu.slug = 'birmingham'" in CLAIM_SQL
    assert "FOR UPDATE OF t SKIP LOCKED" in CLAIM_SQL
    assert "ORDER BY m.meeting_date DESC" in CLAIM_SQL
    assert "interval '24 hours'" in CLAIM_SQL
    assert "t.stage_attempts < 3" in CLAIM_SQL


def test_status_stage_map():
    assert STAGE_FOR_STATUS == {"uploaded": "speakers", "speakers_resolved": "events", "events_extracted": "compare"}
```

```python
# tests/unit/test_worker_scheduler_transcripts.py
from docket.worker.scheduler import build_scheduler
from docket.worker.tasks import TASKS
from docket.worker.health import TASK_UUID_ENV


def test_transcript_pipeline_is_registered_at_10_central():
    sched = build_scheduler("America/Chicago")
    job = sched.get_job("transcript_pipeline")
    assert job is not None
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "10" and fields["minute"] == "0"
    assert "transcript_pipeline" in TASKS
    assert TASK_UUID_ENV["transcript_pipeline"] == "HEALTHCHECK_TRANSCRIPT_PIPELINE_UUID"
```

- [ ] **Step 2: Write the failing integration tests**

```python
# tests/integration/test_transcript_pipeline.py
"""Claim order, fitness gate, index points, advance/hold/fail mapping, public predicate."""
from datetime import date
from unittest.mock import MagicMock

import pytest

from docket.ai.exceptions import AIPermanentRowError, AITransientError, TranscriptHeld
from docket.ai.transcripts import pipeline as P
from docket.config import DATABASE_URL
from docket.db import db_cursor
from docket.services import transcripts as tsvc

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


def _mk(status="uploaded", word_count=5000, meeting_date=date(2026, 9, 1), external_id="999801", *, segments=True):
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, external_id, video_url)
                       VALUES (%s, 'PL test', %s, %s, 'https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=1')
                       RETURNING id""", [muni, meeting_date, external_id])
        mid = cur.fetchone()["id"]
        cur.execute("INSERT INTO processing_status (meeting_id) VALUES (%s)", [mid])
        cur.execute("""INSERT INTO agenda_items (meeting_id, item_number, title, external_id, video_timestamp_seconds)
                       VALUES (%s, '1', 'First', %s, 900), (%s, '2', 'Second', %s, 1500) RETURNING id""",
                    [mid, external_id + "-1", mid, external_id + "-2"])
        i1, i2 = [r["id"] for r in cur.fetchall()]
        cur.execute("""INSERT INTO transcripts (meeting_id, status, version, word_count, uploaded_at)
                       VALUES (%s, %s, 1, %s, now()) RETURNING id""", [mid, status, word_count])
        tid = cur.fetchone()["id"]
        if segments:
            cur.execute("""INSERT INTO transcript_segments (transcript_id, seq, start_s, end_s, text, cluster_label, is_silence) VALUES
                           (%s, 0, 0, 890, '', NULL, TRUE),
                           (%s, 1, 905, 910, 'Item one is up.', 'S0', FALSE),
                           (%s, 2, 1510, 1515, 'Now item two.', 'S1', FALSE)""", [tid, tid, tid])
    return {"meeting_id": mid, "transcript_id": tid, "items": (i1, i2)}


def _rm(*fx):
    with db_cursor() as cur:
        for f in fx:
            cur.execute("DELETE FROM meetings WHERE id=%s", [f["meeting_id"]])


def _row(tid):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM transcripts WHERE id=%s", [tid])
        return cur.fetchone()


def test_claim_newest_first_and_bumps_attempts():
    a = _mk(meeting_date=date(2026, 8, 1), external_id="999811")
    b = _mk(meeting_date=date(2026, 9, 15), external_id="999812")
    try:
        c = P.claim_next()
        assert c["id"] == b["transcript_id"] and c["status"] == "uploaded"
        assert _row(b["transcript_id"])["stage_attempts"] == 1
        # Backoff: the row just claimed is not claimable again inside 24h.
        c2 = P.claim_next()
        assert c2["id"] == a["transcript_id"]
        assert P.claim_next() is None
    finally:
        _rm(a, b)


def test_no_minutes_rows_are_claimable_only_once_minutes_url_exists():
    fx = _mk(status="events_extracted")
    try:
        with db_cursor() as cur:
            cur.execute("UPDATE transcripts SET compare_skipped_reason='no_minutes' WHERE id=%s", [fx["transcript_id"]])
        assert P.claim_next() is None
        with db_cursor() as cur:
            cur.execute("UPDATE meetings SET minutes_url='https://x/MinutesViewer.php?clip_id=1' WHERE id=%s", [fx["meeting_id"]])
        assert P.claim_next()["id"] == fx["transcript_id"]
    finally:
        _rm(fx)


def test_fitness_gate_moves_mic_check_to_low_speech_without_llm(monkeypatch):
    fx = _mk(word_count=24)
    client = MagicMock()
    monkeypatch.setattr(P, "_stage_fn", lambda stage: (_ for _ in ()).throw(AssertionError("stage ran")))
    try:
        claim = P.claim_next()
        assert P.process_claim(claim, client=client, notes="t") == "low_speech"
        row = _row(fx["transcript_id"])
        assert row["status"] == "low_speech" and "below floor" in row["last_error"]
        client.call.assert_not_called()
        # Not public any more; surfaced as debt even though the recording is short.
        assert tsvc.get_public_transcript(fx["meeting_id"]) is None
        with db_cursor() as cur:
            cur.execute("UPDATE transcripts SET audio_duration_s=360 WHERE id=%s", [fx["transcript_id"]])
            cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'"); muni = cur.fetchone()["id"]
        debt = [d for d in tsvc.list_transcript_debt(muni) if d["meeting_id"] == fx["meeting_id"]]
        assert debt and debt[0]["friendly_label"] == "Too short to analyze (24 words)"
    finally:
        _rm(fx)


def test_index_points_assign_segments_before_speaker_stage(monkeypatch):
    fx = _mk()
    monkeypatch.setattr(P, "_stage_fn", lambda stage: (lambda claim, client: P.StageOutcome("speakers_resolved")))
    try:
        claim = P.claim_next()
        assert P.process_claim(claim, client=MagicMock(), notes="t") == "advanced"
        with db_cursor() as cur:
            cur.execute("SELECT seq, agenda_item_id, assignment_method FROM transcript_segments WHERE transcript_id=%s ORDER BY seq",
                        [fx["transcript_id"]])
            rows = cur.fetchall()
        i1, i2 = fx["items"]
        assert rows[0]["agenda_item_id"] is None            # pre-meeting silence, before the first index point
        assert (rows[1]["agenda_item_id"], rows[1]["assignment_method"]) == (i1, "index_point")
        assert (rows[2]["agenda_item_id"], rows[2]["assignment_method"]) == (i2, "index_point")
        row = _row(fx["transcript_id"])
        assert row["status"] == "speakers_resolved" and row["stage_attempts"] == 0
    finally:
        _rm(fx)


@pytest.mark.parametrize("exc,expected_status,expected_reason", [
    (TranscriptHeld("token_ceiling", "612000 tokens"), "needs_review", "token_ceiling"),
    (AIPermanentRowError("refusal: cyber"), "needs_review", "permanent"),
])
def test_holds_go_to_needs_review_with_reason(monkeypatch, exc, expected_status, expected_reason):
    fx = _mk()
    def boom(claim, client): raise exc
    monkeypatch.setattr(P, "_stage_fn", lambda stage: boom)
    try:
        assert P.process_claim(P.claim_next(), client=MagicMock(), notes="t") == "held"
        row = _row(fx["transcript_id"])
        assert row["status"] == expected_status and row["needs_review_reason"] == expected_reason
        # Uploaded transcript stays public after a worker-stage hold.
        assert tsvc.get_public_transcript(fx["meeting_id"]) is not None
    finally:
        _rm(fx)


def test_third_transient_failure_marks_failed(monkeypatch):
    fx = _mk()
    def boom(claim, client): raise AITransientError("5xx")
    monkeypatch.setattr(P, "_stage_fn", lambda stage: boom)
    try:
        with db_cursor() as cur:
            cur.execute("UPDATE transcripts SET stage_attempts=2 WHERE id=%s", [fx["transcript_id"]])
        assert P.process_claim(P.claim_next(), client=MagicMock(), notes="t") == "failed"
        row = _row(fx["transcript_id"])
        assert row["status"] == "failed" and row["stage_attempts"] == 3 and "5xx" in row["last_error"]
        assert tsvc.get_public_transcript(fx["meeting_id"]) is not None   # segments exist; page stays up
    finally:
        _rm(fx)


def test_failed_without_upload_is_still_not_public():
    fx = _mk(status="failed", segments=False)
    try:
        with db_cursor() as cur:
            cur.execute("UPDATE transcripts SET uploaded_at=NULL WHERE id=%s", [fx["transcript_id"]])
        assert tsvc.get_public_transcript(fx["meeting_id"]) is None
    finally:
        _rm(fx)


def test_each_processed_claim_writes_an_ai_run(monkeypatch):
    fx = _mk()
    monkeypatch.setattr(P, "_stage_fn", lambda stage: (lambda claim, client: P.StageOutcome("speakers_resolved")))
    try:
        P.process_claim(P.claim_next(), client=MagicMock(), notes="pytest_pipeline")
        with db_cursor() as cur:
            cur.execute("SELECT stage, model, rows_processed, finished_at FROM ai_runs WHERE notes='pytest_pipeline' ORDER BY id DESC LIMIT 1")
            run = cur.fetchone()
        assert run["stage"] == "transcript_speakers" and run["rows_processed"] == 1 and run["finished_at"] is not None
    finally:
        _rm(fx)
        with db_cursor() as cur:
            cur.execute("DELETE FROM ai_runs WHERE notes='pytest_pipeline'")
```

- [ ] **Step 3: Run to verify failure**

Run: `venv/bin/python -m pytest tests/unit/test_transcript_fitness.py tests/unit/test_worker_scheduler_transcripts.py tests/integration/test_transcript_pipeline.py -v`
Expected: FAIL (`ModuleNotFoundError: docket.ai.transcripts.pipeline`, `ImportError: TranscriptHeld`).

- [ ] **Step 4: Exception, public predicate, debt label**

Append to `src/docket/ai/exceptions.py`:

```python
class TranscriptHeld(AIError):
    """A transcript stage must stop and park the row as needs_review.

    ``reason`` is the short machine label stored in
    ``transcripts.needs_review_reason`` (token_ceiling, candidate_cap,
    schema_invalid, refusal, max_tokens, permanent); the message is the detail.
    """

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason
```

In `src/docket/services/transcripts.py`, under `PUBLIC_STATUSES` add:

```python
# A worker-stage failure after upload (speaker resolution, extraction,
# comparison) must not take a readable transcript off the site. Producer
# failures never set uploaded_at, so they stay hidden.
_PUBLIC_PREDICATE = ("({a}.status = ANY(%s) OR ({a}.status IN ('failed', 'needs_review') "
                     "AND {a}.uploaded_at IS NOT NULL))")


def public_predicate(alias: str) -> str:
    return _PUBLIC_PREDICATE.format(a=alias)
```

Rewrite `get_public_transcript`'s query as `FROM transcripts t WHERE t.meeting_id = %s AND {public_predicate('t')}` with the same `[meeting_id, list(PUBLIC_STATUSES)]` parameter order, and the `transcripts t` joins in `excerpt_for_item` (`AND {public_predicate('t')}` replacing `AND t.status = ANY(%s)`) and `search_transcripts` (replace the `"t.status = ANY(%s)"` element of `where` with `public_predicate("t")`). Select columns explicitly with the `t.` prefix in `get_public_transcript`.

Replace `list_transcript_debt`'s `OR (t.status = 'low_speech' AND COALESCE(t.audio_duration_s, 0) >= %s)` with:

```sql
                     OR (t.status = 'low_speech'
                         AND (COALESCE(t.audio_duration_s, 0) >= %s
                              OR (t.word_count IS NOT NULL AND t.word_count < %s)))
```

add `t.word_count` to the SELECT, pass `TRANSCRIPT_MIN_WORDS` after `SHORT_MEETING_S` in the parameter list, and compute labels as:

```python
    for r in rows:
        if r["status"] == "low_speech" and r["word_count"] is not None and r["word_count"] < TRANSCRIPT_MIN_WORDS:
            r["friendly_label"] = f"Too short to analyze ({r['word_count']} words)"
        else:
            r["friendly_label"] = TRANSCRIPT_DEBT_LABELS.get(r["status"], "Transcript problem")
```

Import `TRANSCRIPT_MIN_WORDS` from `docket.config`. Run `venv/bin/python -m pytest tests/integration/test_transcript_routes.py tests/integration/test_transcript_search.py -v`; the plan 1 tests still pass because their `failed` rows never have `uploaded_at` set before `_publish` (and `test_404_while_not_public` uses `claimed`). If a plan 1 test sets `failed` after `_publish` and expects 404, its premise has changed; update it to expect 200 and keep a separate `uploaded_at IS NULL` case.

- [ ] **Step 5: Write `pipeline.py`**

```python
# src/docket/ai/transcripts/pipeline.py
"""One cron task drives three stages: uploaded -> speakers_resolved -> events_extracted -> compared.

Claim pattern is the OCR one (CTE, FOR UPDATE SKIP LOCKED, newest meeting
first, attempts bumped at claim time, 24-hour backoff in the WHERE clause).
Every processed claim opens and closes an ``ai_runs`` row through the v2
worker helpers so ``AI_DAILY_BUDGET_USD`` sees the spend. Stage modules are
imported lazily so this module has no import-time dependency on them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from docket.ai.exceptions import (AIFatalError, AIPermanentRowError, AIRateLimited, AITransientError,
                                  TranscriptHeld)
from docket.ai.pricing import PRICING, Usage, calculate_cost_usd, usage_add, usage_capture
from docket.config import (AI_DAILY_BUDGET_USD, AI_TRANSCRIPT_COMPARE_MODEL, AI_TRANSCRIPT_EVENTS_MODEL,
                           AI_TRANSCRIPT_SPEAKER_MODEL, TRANSCRIPT_MIN_WORDS, TRANSCRIPT_PER_TICK)
from docket.db import db, db_cursor

log = logging.getLogger(__name__)

STAGE_FOR_STATUS = {"uploaded": "speakers", "speakers_resolved": "events", "events_extracted": "compare"}
RUN_NAME = {"speakers": "transcript_speakers", "events": "transcript_events", "compare": "transcript_compare"}
MODEL_FOR_STAGE = {"speakers": AI_TRANSCRIPT_SPEAKER_MODEL, "events": AI_TRANSCRIPT_EVENTS_MODEL,
                   "compare": AI_TRANSCRIPT_COMPARE_MODEL}

CLAIM_SQL = """
WITH candidate AS (
    SELECT t.id
      FROM transcripts t
      JOIN meetings m        ON m.id  = t.meeting_id
      JOIN municipalities mu ON mu.id = m.municipality_id
     WHERE mu.slug = 'birmingham'
       AND m.external_id ~ '^[0-9]+$'
       AND m.is_hidden = FALSE
       AND t.status IN ('uploaded', 'speakers_resolved', 'events_extracted')
       AND (t.status <> 'events_extracted'
            OR t.compare_skipped_reason IS NULL
            OR t.compare_skipped_reason = 'minutes_changed'
            OR (t.compare_skipped_reason IN ('no_minutes', 'minutes_unavailable')
                AND m.minutes_url IS NOT NULL))
       AND t.stage_attempts < 3
       AND (t.last_attempted_at IS NULL OR t.last_attempted_at < now() - interval '24 hours')
     ORDER BY m.meeting_date DESC, t.id
     LIMIT 1
     FOR UPDATE OF t SKIP LOCKED
)
UPDATE transcripts t
   SET stage_attempts = t.stage_attempts + 1, last_attempted_at = now(), updated_at = now()
  FROM candidate
 WHERE t.id = candidate.id
RETURNING t.id, t.meeting_id, t.status, t.version, t.word_count, t.compare_skipped_reason
"""


@dataclass
class StageOutcome:
    next_status: str
    skipped_reason: str | None = None
    detail: str = ""


@dataclass
class PipelineSummary:
    processed: int = 0
    advanced: int = 0
    skipped: int = 0
    low_speech: int = 0
    held: int = 0
    failed: int = 0
    transient: int = 0
    stopped_reason: str | None = None


def fitness_reason(word_count: int | None, floor: int = TRANSCRIPT_MIN_WORDS) -> str | None:
    if word_count is None:
        return "word_count unknown"
    if word_count < floor:
        return f"word_count {word_count} below floor {floor}"
    return None


def claim_next() -> dict | None:
    with db_cursor() as cur:
        cur.execute(CLAIM_SQL)
        row = cur.fetchone()
        return dict(row) if row else None


def assign_index_points(transcript_id: int, meeting_id: int) -> int:
    """Initial agenda_item_id from Granicus index points (spec: 'index point drift').

    Each unassigned, non-silence segment gets the item whose index point is the
    latest one at or before the segment's start. Segments before the first index
    point (pre-meeting) stay NULL. Confident item_opened events re-assign later
    with assignment_method = 'event'; manual assignments are never touched.
    """
    with db_cursor() as cur:
        cur.execute(
            """UPDATE transcript_segments s
                  SET agenda_item_id = x.item_id, assignment_method = 'index_point'
                 FROM (SELECT s2.id AS seg_id,
                              (SELECT a.id FROM agenda_items a
                                WHERE a.meeting_id = %s AND a.video_timestamp_seconds IS NOT NULL
                                  AND a.video_timestamp_seconds <= s2.start_s
                                ORDER BY a.video_timestamp_seconds DESC, a.id LIMIT 1) AS item_id
                         FROM transcript_segments s2
                        WHERE s2.transcript_id = %s AND s2.assignment_method IS NULL AND s2.is_silence = FALSE) x
                WHERE s.id = x.seg_id AND x.item_id IS NOT NULL""",
            [meeting_id, transcript_id],
        )
        return cur.rowcount


def advance(transcript_id: int, outcome: StageOutcome) -> None:
    with db_cursor() as cur:
        cur.execute(
            """UPDATE transcripts
                  SET status = %s, stage_attempts = 0, last_error = NULL, needs_review_reason = NULL,
                      compare_skipped_reason = %s, updated_at = now()
                WHERE id = %s""",
            [outcome.next_status, outcome.skipped_reason, transcript_id],
        )
        if outcome.skipped_reason in ("no_minutes", "minutes_unavailable"):
            # Retry daily without burning the three-attempt cap (Review Focus 1).
            cur.execute("UPDATE transcripts SET stage_attempts = 0 WHERE id = %s", [transcript_id])


def mark_low_speech(transcript_id: int, detail: str) -> None:
    with db_cursor() as cur:
        cur.execute("""UPDATE transcripts SET status = 'low_speech', last_error = %s, stage_attempts = 0,
                              updated_at = now() WHERE id = %s""", [detail, transcript_id])


def mark_needs_review(transcript_id: int, reason: str, detail: str) -> None:
    with db_cursor() as cur:
        cur.execute("""UPDATE transcripts SET status = 'needs_review', needs_review_reason = %s,
                              last_error = %s, updated_at = now() WHERE id = %s""",
                    [reason, detail[:2000], transcript_id])


def mark_transient(transcript_id: int, detail: str) -> str:
    """Record the error; the third failed attempt becomes `failed`. Returns the status."""
    with db_cursor() as cur:
        cur.execute("""UPDATE transcripts
                          SET last_error = %s, updated_at = now(),
                              status = CASE WHEN stage_attempts >= 3 THEN 'failed' ELSE status END
                        WHERE id = %s RETURNING status""", [detail[:2000], transcript_id])
        return cur.fetchone()["status"]


def _stage_fn(stage: str) -> Callable[..., StageOutcome]:
    if stage == "speakers":
        from docket.ai.transcripts.speakers import run_speaker_stage
        return run_speaker_stage
    if stage == "events":
        from docket.ai.transcripts.events import run_events_stage
        return run_events_stage
    from docket.ai.transcripts.compare import run_compare_stage
    return run_compare_stage


def _cost(emissions: list[tuple[str, Usage]]) -> tuple[float, Usage]:
    total = Usage(0, 0, 0, 0)
    cost = 0.0
    for model, u in emissions:
        total = usage_add(total, u)
        cost += calculate_cost_usd(model, u)
    return cost, total


def process_claim(claim: dict, *, client, notes: str) -> str:
    from docket.ai.transcripts.alerts import post_alert
    from docket.ai.worker import RunSummary, _close_run, _open_run

    stage = STAGE_FOR_STATUS[claim["status"]]
    tid, mid = claim["id"], claim["meeting_id"]
    if stage == "speakers":
        reason = fitness_reason(claim.get("word_count"))
        if reason:
            mark_low_speech(tid, reason)
            log.info("transcript %s meeting %s -> low_speech (%s)", tid, mid, reason)
            return "low_speech"
        assign_index_points(tid, mid)

    run_name, model = RUN_NAME[stage], MODEL_FOR_STAGE[stage]
    with db() as conn:
        run_id = _open_run(conn, run_name, model, notes)
    summary = RunSummary(stage=run_name)
    emissions: list[tuple[str, Usage]] = []
    outcome = "transient"
    try:
        with usage_capture() as emissions:
            result = _stage_fn(stage)(claim, client=client)
        advance(tid, result)
        summary.rows_processed = 1
        outcome = "advanced" if result.skipped_reason is None else "skipped"
        log.info("transcript %s meeting %s: %s -> %s %s", tid, mid, claim["status"], result.next_status,
                 result.skipped_reason or "")
    except TranscriptHeld as e:
        mark_needs_review(tid, e.reason, str(e))
        summary.rows_failed = 1
        outcome = "held"
        post_alert("transcript_needs_review", f"Transcript for meeting {mid} held: {e.reason} ({e})",
                   meeting_id=mid, stage=stage, reason=e.reason)
    except AIPermanentRowError as e:
        mark_needs_review(tid, "permanent", str(e))
        summary.rows_failed = 1
        outcome = "held"
        post_alert("transcript_needs_review", f"Transcript for meeting {mid} held after {stage}: {e}",
                   meeting_id=mid, stage=stage, reason="permanent")
    except AIRateLimited as e:
        mark_transient(tid, f"rate limited: {e}")
        summary.rows_failed = 1
        outcome = "rate_limited"
    except AITransientError as e:
        status = mark_transient(tid, str(e))
        summary.rows_failed = 1
        outcome = "failed" if status == "failed" else "transient"
        if status == "failed":
            post_alert("transcript_failed", f"Transcript for meeting {mid} failed at {stage}: {e}",
                       meeting_id=mid, stage=stage)
    except AIFatalError:
        raise
    except Exception as e:  # a bug in a stage must not take the cron down
        log.exception("transcript %s stage %s crashed", tid, stage)
        status = mark_transient(tid, f"{type(e).__name__}: {e}")
        summary.rows_failed = 1
        outcome = "failed" if status == "failed" else "transient"
    finally:
        summary.cost_usd, summary.usage = _cost(emissions)
        with db() as conn:
            _close_run(conn, run_id, summary)
    return outcome


def _validate_models() -> None:
    for stage, model in MODEL_FOR_STAGE.items():
        if model not in PRICING:
            raise AIFatalError(f"{stage} model {model!r} has no PRICING entry; add it before running")


def run_transcript_pipeline(*, limit: int = TRANSCRIPT_PER_TICK, notes: str = "cron_transcripts",
                            force_budget: bool = False, client=None) -> PipelineSummary:
    from docket.ai.transcripts.alerts import alert_if_producer_stalled
    from docket.ai.transcripts.client import StructuredClient
    from docket.ai.worker import BudgetExceededError, _today_spend

    _validate_models()
    reset_for_versions()
    client = client or StructuredClient()
    s = PipelineSummary()
    for _ in range(limit):
        with db() as conn:
            spent = _today_spend(conn)
        if spent >= AI_DAILY_BUDGET_USD and not force_budget:
            if s.processed == 0:
                raise BudgetExceededError(
                    f"Today's AI spend ${spent:.2f} >= budget ${AI_DAILY_BUDGET_USD:.2f}; pass force_budget=True to override")
            s.stopped_reason = "budget"
            break
        claim = claim_next()
        if claim is None:
            break
        outcome = process_claim(claim, client=client, notes=notes)
        s.processed += 1
        setattr(s, outcome if outcome != "rate_limited" else "transient",
                getattr(s, outcome if outcome != "rate_limited" else "transient") + 1)
        if outcome == "rate_limited":
            s.stopped_reason = "rate_limited"
            break
    sweep_minutes_changes()
    alert_if_producer_stalled()
    log.info("transcript_pipeline %s", s)
    return s


def reset_for_versions() -> int:
    """Bumping a prompt version resets that stage and later ones only (spec: re-runs are per stage)."""
    from docket.ai.transcripts.prompts import COMPARE_PROMPT_VERSION, EVENTS_PROMPT_VERSION
    with db_cursor() as cur:
        cur.execute("""UPDATE transcripts t SET status = 'speakers_resolved', stage_attempts = 0, compare_skipped_reason = NULL
                        WHERE t.status IN ('events_extracted', 'compared')
                          AND EXISTS (SELECT 1 FROM meeting_events e WHERE e.meeting_id = t.meeting_id
                                         AND e.source = 'transcript' AND e.prompt_version < %s)""",
                    [EVENTS_PROMPT_VERSION])
        n = cur.rowcount
        cur.execute("""UPDATE transcripts t SET status = 'events_extracted', stage_attempts = 0
                        WHERE t.status = 'compared'
                          AND EXISTS (SELECT 1 FROM minutes_discrepancies d WHERE d.meeting_id = t.meeting_id
                                         AND d.prompt_version < %s)""", [COMPARE_PROMPT_VERSION])
        return n + cur.rowcount


def sweep_minutes_changes(limit: int = 10) -> int:
    """Placeholder until Task 12 fills it: returns 0."""
    return 0
```

Task 12 replaces `sweep_minutes_changes`; Task 13 supplies `alerts.post_alert` and `alert_if_producer_stalled`. Until Task 13 lands, create `src/docket/ai/transcripts/alerts.py` with no-op versions of both functions so the pipeline imports:

```python
# src/docket/ai/transcripts/alerts.py  (Task 4 stub; Task 13 replaces the bodies)
from __future__ import annotations


def post_alert(kind: str, text: str, **fields) -> bool:
    return False


def alert_if_producer_stalled() -> bool:
    return False
```

- [ ] **Step 6: Worker wiring**

In `src/docket/worker/tasks.py` add after `_do_video_ocr`:

```python
def _do_transcript_pipeline() -> None:
    """Spec 2026-10-05 Section 3: advance up to TRANSCRIPT_PER_TICK transcripts through the LLM stages."""
    from docket.ai.transcripts.pipeline import run_transcript_pipeline

    try:
        s = run_transcript_pipeline(notes="cron_transcripts")
    except BudgetExceededError as e:
        log.info("transcript_pipeline skipped: %s", e)
        return
    log.info("transcript_pipeline processed=%d advanced=%d skipped=%d low_speech=%d held=%d failed=%d transient=%d stop=%s",
             s.processed, s.advanced, s.skipped, s.low_speech, s.held, s.failed, s.transient, s.stopped_reason)


def task_transcript_pipeline() -> None:
    _safe_run("transcript_pipeline", _do_transcript_pipeline)
```

and `"transcript_pipeline": task_transcript_pipeline,` in `TASKS`. In `scheduler.py` add after the `vote_matching` job:

```python
    # Transcript LLM stages (speakers -> events -> comparison), after vote
    # matching so the deterministic vote check sees today's minutes votes.
    # Spec: docs/superpowers/specs/2026-10-05-meeting-transcripts-design.md §3
    sched.add_job(
        TASKS["transcript_pipeline"],
        CronTrigger(hour=10, minute=0, timezone=timezone),
        id="transcript_pipeline",
        coalesce=True,
        max_instances=1,
    )
```

Update the module docstrings' job counts. In `health.py` add `"transcript_pipeline": "HEALTHCHECK_TRANSCRIPT_PIPELINE_UUID",` to `TASK_UUID_ENV`.

- [ ] **Step 7: Run to verify pass**

Run: `venv/bin/python -m pytest tests/unit/test_transcript_fitness.py tests/unit/test_worker_scheduler_transcripts.py tests/integration/test_transcript_pipeline.py tests/integration/test_transcript_routes.py tests/integration/test_transcript_search.py tests/unit/test_ai_worker_run.py -v`
Expected: all PASS. (`tests/unit/test_ai_worker_run.py` guards that importing the worker helpers from the pipeline changed nothing.)

- [ ] **Step 8: Commit**

```bash
git add src/docket/ai/transcripts/pipeline.py src/docket/ai/transcripts/alerts.py src/docket/ai/exceptions.py src/docket/worker/tasks.py src/docket/worker/scheduler.py src/docket/worker/health.py src/docket/services/transcripts.py tests/unit/test_transcript_fitness.py tests/unit/test_worker_scheduler_transcripts.py tests/integration/test_transcript_pipeline.py
git -c user.email=hello@docket.pub commit -m "feat(worker): transcript_pipeline task; claim, fitness gate, index points, status advance

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Citation guard (pure)

**Files:**
- Create: `src/docket/ai/transcripts/guard.py`
- Test: `tests/unit/test_guard.py`

**Interfaces:**
- Produces:
  - `normalize(s: str) -> str` — NFKC, soft hyphens removed, hyphen + line break joined, curly quotes unified, whitespace collapsed, lowercased.
  - `normalize_with_map(s: str) -> tuple[str, list[int]]` — same normalization plus, for every normalized character, the index of the original character it came from.
  - `@dataclass(frozen=True) CitationMatch(kind: Literal["exact","fuzzy","missing"], start: int | None, end: int | None, ratio: float)` with offsets into the original source.
  - `find_citation(excerpt: str, source: str, *, fuzzy_threshold: float = 0.92) -> CitationMatch`.
  - `canonical_statute(s: str) -> str` — spoken or written statute cites to one comparable string (`"36, 25, a seven a four"` and `"36-25A-7(a)(4)"` both become `"3625a7a4"`).
  - `window(source: str, start: int, end: int, radius: int) -> str`.
  - Used by Tasks 7, 9, 11, 14.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_guard.py
from docket.ai.transcripts.guard import canonical_statute, find_citation, normalize, normalize_with_map, window


def test_normalize_handles_pdf_artifacts():
    raw = "The ﬁrst  “Executive­Session” was ap-\nproved at 10:20 o’clock"
    assert normalize(raw) == 'the first "executivesession" was approved at 10:20 o\'clock'


def test_hyphenated_line_breaks_join_with_or_without_trailing_space():
    assert normalize("ap-\nproved") == normalize("ap- \nproved") == normalize("ap-\n proved") == "approved"
    assert normalize("well-known rule") == "well-known rule"          # an in-line hyphen is kept


def test_fuzzy_pass_is_anchored_and_bounded_on_long_sources():
    filler = ("the council considered routine business and heard from staff about the schedule. " * 2500)   # ~200K chars
    source = filler + "upon the roll being called the vote was as fol lows: Ayes: nine" + filler
    cm = find_citation("upon the roll being called the vote was as follows: Ayes: nine", source)
    assert cm.kind == "fuzzy" and "roll being called" in source[cm.start:cm.end]
    # No three consecutive words of this quote exist in the source: missing, with no sweep.
    assert find_citation("zebra quartz umbrella nine", source).kind == "missing"


def test_normalize_with_map_points_back_into_the_original():
    raw = "Said  ordinance  ADOPTED."
    norm, m = normalize_with_map(raw)
    assert norm == "said ordinance adopted."
    i = norm.index("adopted")
    assert raw[m[i]:m[i + len("adopted") - 1] + 1] == "ADOPTED"


def test_exact_match_returns_original_offsets():
    source = "Councilmember O’Quinn made a motion which was seconded by Councilmember Tate to\ngo into Executive Session"
    cm = find_citation("O'Quinn made a motion which was seconded by Councilmember Tate to go into Executive Session", source)
    assert cm.kind == "exact"
    assert source[cm.start:cm.end].startswith("O’Quinn made a motion")
    assert source[cm.start:cm.end].endswith("Executive Session")


def test_fuzzy_pass_catches_a_stray_space_inside_a_word():
    source = "upon the roll being called the vote was as fol lows: Ayes: nine"
    cm = find_citation("upon the roll being called the vote was as follows: Ayes: nine", source)
    assert cm.kind == "fuzzy" and cm.ratio >= 0.92
    assert "roll being called" in source[cm.start:cm.end]


def test_missing_when_the_quote_is_not_there():
    cm = find_citation("the council adjourned sine die", "Item 15 passes. We stand in recess.")
    assert cm.kind == "missing" and cm.start is None


def test_exact_beats_fuzzy_and_empty_excerpt_is_missing():
    assert find_citation("", "anything").kind == "missing"
    assert find_citation("   ", "anything").kind == "missing"


def test_canonical_statute_unifies_spoken_and_written_forms():
    assert canonical_statute("36-25A-7(a)(4)") == "3625a7a4"
    assert canonical_statute("36, 25, a seven a four") == "3625a7a4"
    assert canonical_statute("Section 36-25A-7 (a)(3)") == "section3625a7a3"
    assert canonical_statute("thirty six twenty five A seven a four") == "3625a7a4"


def test_window_clamps_to_source():
    src = "abcdefghij"
    assert window(src, 4, 6, 3) == "bcdefghi"
    assert window(src, 0, 2, 50) == src
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/unit/test_guard.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write `guard.py`**

```python
# src/docket/ai/transcripts/guard.py
"""Hallucination guard: every quoted excerpt must be found in the text the model saw.

Both sides are normalized the same way before matching (spec Section 3,
"Hallucination guard"); a fuzzy window pass catches what the normalizer
misses, such as a stray space inside a word from the PDF extractor. The
offsets returned point into the ORIGINAL source so callers can compute
`char_offset`, pages, and segment positions.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

_QUOTES = {"‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"',
           "′": "'", "″": '"'}
_SOFT_HYPHEN = "­"


def normalize_with_map(s: str) -> tuple[str, list[int]]:
    out: list[str] = []
    idx: list[int] = []
    i, n = 0, len(s)
    pending_space = False
    while i < n:
        ch = s[i]
        if ch == _SOFT_HYPHEN:
            i += 1
            continue
        # "ap-\nproved", "ap- \nproved", "ap-\n proved" -> "approved": a hyphen followed by
        # optional spaces and a line break joins the word (pdfplumber emits all three).
        if ch == "-":
            j = i + 1
            while j < n and s[j] in " \t":
                j += 1
            if j < n and s[j] in "\r\n":
                i = j
                while i < n and s[i] in " \t\r\n":
                    i += 1
                continue
        if ch.isspace():
            pending_space = True
            i += 1
            continue
        if pending_space and out:
            out.append(" ")
            idx.append(i)
            pending_space = False
        elif pending_space:
            pending_space = False
        ch = _QUOTES.get(ch, ch)
        for c in unicodedata.normalize("NFKC", ch).lower():
            out.append(c)
            idx.append(i)
        i += 1
    return "".join(out), idx


def normalize(s: str) -> str:
    return normalize_with_map(s)[0]


@dataclass(frozen=True)
class CitationMatch:
    kind: Literal["exact", "fuzzy", "missing"]
    start: int | None
    end: int | None
    ratio: float


MISSING = CitationMatch("missing", None, None, 0.0)
MAX_FUZZY_ANCHORS = 50


def find_citation(excerpt: str, source: str, *, fuzzy_threshold: float = 0.92) -> CitationMatch:
    ne = normalize(excerpt)
    if not ne:
        return MISSING
    ns, m = normalize_with_map(source)
    pos = ns.find(ne)
    if pos >= 0:
        return CitationMatch("exact", m[pos], m[pos + len(ne) - 1] + 1, 1.0)
    # Fuzzy pass, anchored: never a full sweep of the source. An anchor is an exact
    # hit of any three-word shingle of the excerpt; windows are tried only where the
    # excerpt would sit around each anchor. A quote with no three consecutive words
    # intact anywhere in the source is reported missing. Cost is O(anchors), not
    # O(len(source)), so a 300-page minutes text costs the same as a short one.
    words = ne.split(" ")
    anchors: set[int] = set()
    for k in range(max(1, len(words) - 2)):
        shingle = " ".join(words[k:k + 3])
        if len(shingle) < 8:
            continue
        off = ne.find(shingle)
        pos = ns.find(shingle)
        while pos >= 0 and len(anchors) < MAX_FUZZY_ANCHORS:
            anchors.add(max(0, pos - off))
            pos = ns.find(shingle, pos + 1)
    wlen = int(len(ne) * 1.15) + 4
    best, best_pos = 0.0, -1
    for a in sorted(anchors):
        for start in range(max(0, a - 8), min(a + 9, len(ns)), 4):
            seg = ns[start:start + wlen]
            sm = SequenceMatcher(None, ne, seg, autojunk=False)
            if sm.quick_ratio() < fuzzy_threshold:
                continue
            r = sm.ratio()
            if r > best:
                best, best_pos = r, start
    if best < fuzzy_threshold:
        return MISSING
    # Tighten to the matched blocks so the offsets hug the quote.
    seg = ns[best_pos:best_pos + wlen]
    blocks = [b for b in SequenceMatcher(None, ne, seg, autojunk=False).get_matching_blocks() if b.size]
    lo = best_pos + blocks[0].b
    hi = best_pos + blocks[-1].b + blocks[-1].size
    return CitationMatch("fuzzy", m[lo], m[hi - 1] + 1, best)


_NUM_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
              "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
              "thirteen": "13", "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
              "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30", "forty": "40",
              "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90"}
_TENS = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}


def canonical_statute(s: str) -> str:
    """Comparable form for a statute cite, spoken or written."""
    words = re.findall(r"[a-z]+|\d+", normalize(s))
    out: list[str] = []
    i = 0
    while i < len(words):
        w = words[i]
        if w in _TENS and i + 1 < len(words) and words[i + 1] in _NUM_WORDS and len(_NUM_WORDS[words[i + 1]]) == 1:
            out.append(str(int(_NUM_WORDS[w]) + int(_NUM_WORDS[words[i + 1]])))
            i += 2
            continue
        out.append(_NUM_WORDS.get(w, w))
        i += 1
    return "".join(out)


def window(source: str, start: int, end: int, radius: int) -> str:
    return source[max(0, start - radius):min(len(source), end + radius)]
```

- [ ] **Step 4: Run to verify pass**

Run: `venv/bin/python -m pytest tests/unit/test_guard.py -v`
Expected: 10 PASS. If `test_fuzzy_pass_catches_a_stray_space_inside_a_word` reports a ratio just under 0.92, do not lower the threshold; check that an anchor was found (the shingle `the roll being` is intact in the source) and that the jittered window starts cover the anchor offset. The long-source test must finish in well under a second; if it does not, the anchor loop is sweeping.

- [ ] **Step 5: Commit**

```bash
git add src/docket/ai/transcripts/guard.py tests/unit/test_guard.py
git -c user.email=hello@docket.pub commit -m "feat(ai): citation guard with normalized exact and fuzzy matching

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Speaker resolution signals and prompt packet (deterministic)

**Files:**
- Create: `src/docket/ai/transcripts/speakers.py` (deterministic half; Task 7 adds the stage)
- Test: `tests/unit/test_speaker_signals.py`

**Interfaces:**
- Consumes: `guard.normalize`.
- Produces:
  - `@dataclass(frozen=True) RosterMember(id: int, name: str, surname: str)`; `roster_for_meeting(meeting_id: int) -> list[RosterMember]` (the canonical half-open predicate from `docket.analysis.ocr.rosters`).
  - `surname(name: str) -> str`; `mentioned_members(text: str, roster) -> list[RosterMember]`.
  - `is_short_response(text) -> bool` (≤ 3 words, one of `here present yes no aye nay yeah`); `is_substantive(text) -> bool` (≥ 8 words).
  - `@dataclass RollCallPair(name_seq, name_text, member: RosterMember, response_seq, response_cluster, response_text)`; `find_roll_call_pairs(segments, roster, max_gap_s=8.0) -> list[RollCallPair]`.
  - `@dataclass ChairAddress(address_seq, address_text, member, next_seq, next_cluster, next_text)`; `find_chair_addresses(segments, roster, max_gap_s=20.0) -> list[ChairAddress]`.
  - `@dataclass ClusterStats(label, speaking_s, utterances, first_s, words)`; `cluster_stats(segments) -> dict[str, ClusterStats]` (ordered by first appearance).
  - `sample_utterances(segments, per_cluster=6, min_words=6, max_words=60) -> dict[str, list[dict]]`.
  - `@dataclass SpeakerPacket(roster, roll_calls, addresses, stats, samples)`; `build_packet(segments, roster) -> SpeakerPacket`; `render_speaker_user(packet, meeting: dict) -> str`.
  - Segments are dicts with `seq, start_s, end_s, text, cluster_label, is_silence` (the shape `list_segments` and the fixture loader produce). Every function ignores `is_silence` rows and empty text.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_speaker_signals.py
from docket.ai.transcripts.speakers import (ClusterStats, RosterMember, build_packet, cluster_stats,
                                             find_chair_addresses, find_roll_call_pairs, is_short_response,
                                             mentioned_members, render_speaker_user, sample_utterances, surname)

R = [RosterMember(1, "Darrell O'Quinn", "oquinn"), RosterMember(2, "LaTonya Tate", "tate"),
     RosterMember(3, "Crystal Smitherman", "smitherman"), RosterMember(4, "Hunter Williams", "williams")]


def seg(seq, start, text, cluster, dur=3.0, silence=False):
    return {"seq": seq, "start_s": float(start), "end_s": float(start) + dur, "text": text,
            "cluster_label": cluster, "is_silence": silence}


def test_surname_strips_suffixes_and_punctuation():
    assert surname("Darrell O'Quinn") == "oquinn"
    assert surname("J.T. Moore") == "moore"
    assert surname("Clinton Woods Jr.") == "woods"
    assert surname("Valerie A. Abbott, III") == "abbott"


def test_mentioned_members_tolerates_asr_spelling():
    assert [m.id for m in mentioned_members("Council member O Quinn", R)] == [1]
    assert [m.id for m in mentioned_members("Councilor Smithermann, you have the floor", R)] == [3]
    assert mentioned_members("the tate modern is in london", R) == [R[1]]   # surname hit; the finders add context
    assert mentioned_members("no names here", R) == []


def test_is_short_response():
    assert is_short_response("Here.") and is_short_response("Present") and is_short_response("Yes, here")
    assert not is_short_response("Here is what I think about the budget")


def test_roll_call_pairs_require_short_response_from_another_cluster():
    segs = [seg(0, 900, "Councilor O'Quinn.", "S0"), seg(1, 903, "Here.", "S7", dur=1),
            seg(2, 905, "Councilor Tate.", "S0"), seg(3, 907, "I want to talk about the budget for a while here", "S3"),
            seg(4, 920, "Councilor Smitherman.", "S0"), seg(5, 940, "Present.", "S9", dur=1)]   # 17 s gap: too late
    pairs = find_roll_call_pairs(segs, R)
    assert [(p.member.id, p.response_cluster, p.response_text) for p in pairs] == [(1, "S7", "Here.")]


def test_roll_call_ignores_same_cluster_response():
    segs = [seg(0, 900, "Councilor Williams.", "S0"), seg(1, 902, "Here.", "S0", dur=1)]
    assert find_roll_call_pairs(segs, R) == []


def test_chair_address_skips_interjections_and_needs_substance():
    segs = [seg(0, 3300, "Councilor O'Quinn, you are recognized.", "S0"),
            seg(1, 3304, "Thank you.", "S4", dur=1),                      # interjection, skipped
            seg(2, 3306, "Yeah, I would just like to hear a layman's summary of what is going on here.", "S7"),
            seg(3, 3400, "as Councilor Tate said earlier", "S7"),          # mention without title/question: not an address
            seg(4, 3405, "The budget office has eleven line items for this program this year.", "S2")]
    adds = find_chair_addresses(segs, R)
    assert [(a.member.id, a.next_cluster) for a in adds] == [(1, "S7")]


def test_cluster_stats_ignore_silence_and_order_by_first_appearance():
    segs = [seg(0, 0, "", None, dur=890, silence=True), seg(1, 900, "a b c", "S3", dur=5), seg(2, 910, "d e", "S1", dur=2),
            seg(3, 920, "f g h i", "S3", dur=4)]
    st = cluster_stats(segs)
    assert list(st) == ["S3", "S1"]
    assert st["S3"] == ClusterStats("S3", 9.0, 2, 900.0, 7)


def test_sample_utterances_spread_across_meeting_and_bounded():
    segs = [seg(i, 900 + i * 10, " ".join(["word"] * (6 + i % 5)), "S3") for i in range(60)]
    samples = sample_utterances(segs, per_cluster=6)
    s = samples["S3"]
    assert len(s) == 6
    assert s[0]["seq"] < s[2]["seq"] < s[5]["seq"]
    assert s[0]["start_s"] < 1000 and s[-1]["start_s"] > 1400
    long = [seg(0, 900, " ".join(["w"] * 200), "S1")]
    assert len(sample_utterances(long)["S1"][0]["text"].split()) <= 60


def test_render_lists_every_cluster_and_the_signals():
    segs = [seg(0, 900, "Councilor O'Quinn.", "S0"), seg(1, 903, "Here.", "S7", dur=1),
            seg(2, 910, "Good morning everyone, we are called to order for the regular meeting.", "S0"),
            seg(3, 1000, "I move approval of the consent agenda as presented this morning.", "S7")]
    packet = build_packet(segs, R)
    text = render_speaker_user(packet, {"id": 2543, "meeting_date": "2026-10-06", "title": "City Council Meeting"})
    assert "1: Darrell O'Quinn" in text
    assert "S0" in text and "S7" in text
    assert "Roll-call candidate pairs" in text and '"Here."' in text
    assert "seq=3" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/unit/test_speaker_signals.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write the deterministic half of `speakers.py`**

```python
# src/docket/ai/transcripts/speakers.py
"""Speaker resolution: deterministic signals + Sonnet 5.5 judgment, written to transcript_speakers.

Diarization over-clusters (24 clusters on a 104-minute meeting), so this stage
expects many clusters per person and resolves each cluster independently; two
clusters resolved to the same member is the merge. Signals (spec Section 3):
roll-call pairs, chair addresses, self-identification, sampled utterances.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from docket.ai.transcripts.guard import normalize
from docket.db import db_cursor

RESPONSE_WORDS = {"here", "present", "yes", "no", "aye", "nay", "yeah"}
_TITLE_RE = re.compile(r"\b(council\s*(?:or|member|man|woman)|councilmember|councilor|president|pro\s*tem|"
                       r"madam|mister|mr|ms|mrs|dr)\b", re.I)
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


@dataclass(frozen=True)
class RosterMember:
    id: int
    name: str
    surname: str


def surname(name: str) -> str:
    toks = [t for t in re.split(r"[\s,]+", name.strip()) if t]
    while toks and re.sub(r"\W", "", toks[-1]).lower() in _SUFFIXES:
        toks.pop()
    return re.sub(r"[^a-z]", "", toks[-1].lower()) if toks else ""


def roster_for_meeting(meeting_id: int) -> list[RosterMember]:
    with db_cursor() as cur:
        cur.execute(
            """SELECT cm.id, cm.name
                 FROM council_members cm
                 JOIN meetings m ON m.municipality_id = cm.municipality_id
                WHERE m.id = %s
                  AND m.meeting_date >= cm.term_start
                  AND m.meeting_date < COALESCE(cm.term_end, m.meeting_date + INTERVAL '1 day')
                ORDER BY cm.name, cm.id""",
            [meeting_id],
        )
        return [RosterMember(r["id"], r["name"], surname(r["name"])) for r in cur.fetchall()]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+", normalize(text))


def mentioned_members(text: str, roster: list[RosterMember]) -> list[RosterMember]:
    """Surname hits in the text, tolerant of ASR spelling ("O Quinn", "Smithermann")."""
    toks = _tokens(text)
    joined = {toks[i] + toks[i + 1] for i in range(len(toks) - 1)} | set(toks)   # "o quinn" -> "oquinn"
    hits: list[RosterMember] = []
    for m in roster:
        if m.surname in joined:
            hits.append(m)
            continue
        if len(m.surname) >= 5 and any(len(t) >= 5 and SequenceMatcher(None, t, m.surname).ratio() >= 0.85
                                        for t in joined):
            hits.append(m)
    return hits


def is_short_response(text: str) -> bool:
    toks = _tokens(text)
    return 0 < len(toks) <= 3 and any(t in RESPONSE_WORDS for t in toks)


def is_substantive(text: str) -> bool:
    return len(_tokens(text)) >= 8


def _speech(segments: list[dict]) -> list[dict]:
    return [s for s in segments if not s.get("is_silence") and (s.get("text") or "").strip()]


@dataclass
class RollCallPair:
    name_seq: int
    name_text: str
    member: RosterMember
    response_seq: int
    response_cluster: str | None
    response_text: str


def find_roll_call_pairs(segments: list[dict], roster: list[RosterMember], max_gap_s: float = 8.0) -> list[RollCallPair]:
    segs = _speech(segments)
    out: list[RollCallPair] = []
    for i, s in enumerate(segs):
        hits = mentioned_members(s["text"], roster)
        if len(hits) != 1 or len(_tokens(s["text"])) > 6:
            continue   # a roll call reads one short name at a time
        for nxt in segs[i + 1:i + 4]:
            if nxt["start_s"] - s["end_s"] > max_gap_s:
                break
            if nxt.get("cluster_label") == s.get("cluster_label"):
                continue
            if is_short_response(nxt["text"]):
                out.append(RollCallPair(s["seq"], s["text"], hits[0], nxt["seq"], nxt.get("cluster_label"), nxt["text"]))
                break
    return out


@dataclass
class ChairAddress:
    address_seq: int
    address_text: str
    member: RosterMember
    next_seq: int
    next_cluster: str | None
    next_text: str


def find_chair_addresses(segments: list[dict], roster: list[RosterMember], max_gap_s: float = 20.0) -> list[ChairAddress]:
    """A member named with a title (or a question), then the next SUBSTANTIVE utterance from another cluster.

    Interjections of three words or fewer (a cough, "thank you", a mic bump)
    are skipped and the following cluster is considered instead.
    """
    segs = _speech(segments)
    out: list[ChairAddress] = []
    for i, s in enumerate(segs):
        hits = mentioned_members(s["text"], roster)
        if len(hits) != 1 or not (_TITLE_RE.search(s["text"]) or "?" in s["text"]):
            continue
        for nxt in segs[i + 1:i + 5]:
            if nxt["start_s"] - s["end_s"] > max_gap_s:
                break
            if nxt.get("cluster_label") == s.get("cluster_label"):
                continue
            if len(_tokens(nxt["text"])) <= 3:
                continue          # interjection; keep looking
            if is_substantive(nxt["text"]):
                out.append(ChairAddress(s["seq"], s["text"], hits[0], nxt["seq"], nxt.get("cluster_label"), nxt["text"]))
            break                 # a non-substantive, non-interjection reply ends the search either way
    return out


@dataclass(frozen=True)
class ClusterStats:
    label: str
    speaking_s: float
    utterances: int
    first_s: float
    words: int


def cluster_stats(segments: list[dict]) -> dict[str, ClusterStats]:
    acc: dict[str, list] = {}
    for s in _speech(segments):
        cl = s.get("cluster_label")
        if cl is None:
            continue
        a = acc.setdefault(cl, [0.0, 0, s["start_s"], 0])
        a[0] += s["end_s"] - s["start_s"]
        a[1] += 1
        a[3] += len(s["text"].split())
    return {cl: ClusterStats(cl, round(a[0], 1), a[1], a[2], a[3]) for cl, a in acc.items()}


def sample_utterances(segments: list[dict], per_cluster: int = 6, min_words: int = 6,
                      max_words: int = 60) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    for s in _speech(segments):
        if s.get("cluster_label") is None or len(s["text"].split()) < min_words:
            continue
        by.setdefault(s["cluster_label"], []).append(s)
    out: dict[str, list[dict]] = {}
    for cl, utts in by.items():
        n = len(utts)
        idxs = sorted({round(i * (n - 1) / max(1, per_cluster - 1)) for i in range(min(per_cluster, n))})
        out[cl] = [{"seq": utts[i]["seq"], "start_s": utts[i]["start_s"],
                    "text": " ".join(utts[i]["text"].split()[:max_words])} for i in idxs]
    return out


@dataclass
class SpeakerPacket:
    roster: list[RosterMember]
    roll_calls: list[RollCallPair]
    addresses: list[ChairAddress]
    stats: dict[str, ClusterStats]
    samples: dict[str, list[dict]] = field(default_factory=dict)


def build_packet(segments: list[dict], roster: list[RosterMember]) -> SpeakerPacket:
    return SpeakerPacket(roster, find_roll_call_pairs(segments, roster), find_chair_addresses(segments, roster),
                         cluster_stats(segments), sample_utterances(segments))


def hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def render_speaker_user(packet: SpeakerPacket, meeting: dict) -> str:
    lines = [f"Meeting: {meeting.get('title')} on {meeting.get('meeting_date')} (meeting id {meeting.get('id')})", "",
             "Roster seated on this date (council_member_id: name):"]
    lines += [f"  {m.id}: {m.name}" for m in packet.roster]
    lines += ["", "Roll-call candidate pairs (a name read, then a short response from another cluster):"]
    lines += [f'  [seq={p.name_seq}] "{p.name_text}" -> [seq={p.response_seq} cluster {p.response_cluster}] "{p.response_text}"'
              for p in packet.roll_calls] or ["  (none found)"]
    lines += ["", "Chair addresses (a member named with a title, then a substantive utterance from another cluster):"]
    lines += [f'  [seq={a.address_seq}] "{a.address_text}" -> [seq={a.next_seq} cluster {a.next_cluster}] "{a.next_text}"'
              for a in packet.addresses] or ["  (none found)"]
    lines += ["", "Clusters, in order of first appearance, with sampled utterances:"]
    for cl, st in packet.stats.items():
        lines.append(f"\n{cl}: {st.speaking_s:.0f} s speaking, {st.utterances} utterances, {st.words} words, first heard {hms(st.first_s)}")
        for u in packet.samples.get(cl, []):
            lines.append(f'  [seq={u["seq"]} t={hms(u["start_s"])}] "{u["text"]}"')
        if not packet.samples.get(cl):
            lines.append("  (no utterance of six words or more)")
    lines += ["", f"Return exactly {len(packet.stats)} assignments, one per cluster label above, in this order: "
              + ", ".join(packet.stats)]
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify pass**

Run: `venv/bin/python -m pytest tests/unit/test_speaker_signals.py -v`
Expected: 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/docket/ai/transcripts/speakers.py tests/unit/test_speaker_signals.py
git -c user.email=hello@docket.pub commit -m "feat(ai): speaker resolution signals: roll-call pairs, chair addresses, samples

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Speaker resolution stage

**Files:**
- Modify: `src/docket/ai/transcripts/speakers.py` (append the stage)
- Test: `tests/integration/test_speaker_stage.py`

**Interfaces:**
- Consumes: `StructuredClient.call` / `count_tokens` (Task 1), `SPEAKER_SYSTEM`, `SPEAKER_PROMPT_VERSION` (Task 2), `SPEAKER_SCHEMA`, `SpeakerResolution` (Task 2), `guard.normalize` (Task 5), `StageOutcome`, `TranscriptHeld` (Task 4), fixture bundle (Task 3).
- Produces:
  - `load_speech_segments(transcript_id: int) -> list[dict]` (non-silence, non-empty, ordered by seq, with `cluster_label`).
  - `CONFIDENCE_CAPS = {"two_signals": 0.95, "one_signal": 0.75, "sample_inference": 0.55}`; `apply_confidence_rules(assignment, cluster_texts: dict[str, str], roster_ids: set[int]) -> tuple[float, str, bool]` returning `(confidence, db_method, quote_verified)`.
  - `write_assignments(meeting_id, transcript_id, assignments) -> int` (rows updated, manual rows skipped).
  - `run_speaker_stage(claim: dict, *, client) -> StageOutcome` with `next_status = "speakers_resolved"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_speaker_stage.py
"""Speaker stage against the real meeting 2543 rows with a mocked model."""
import json
from unittest.mock import MagicMock

import pytest

from docket.ai.exceptions import TranscriptHeld
from docket.ai.pricing import Usage
from docket.ai.transcripts import speakers as SP
from docket.ai.transcripts.client import StructuredResult
from docket.config import DATABASE_URL
from docket.db import db_cursor
from tests.support.transcript_fixtures import install_bundle, load_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


@pytest.fixture
def inst():
    i = install_bundle(load_bundle("transcript_2543"))
    yield i
    i.cleanup()


def _client(assignments, tokens=50_000):
    c = MagicMock()
    c.count_tokens.return_value = tokens
    c.call.return_value = StructuredResult({"assignments": assignments}, Usage(100, 0, 0, 50), "claude-sonnet-5-5", "end_turn")
    return c


def _claim(inst):
    return {"id": inst.transcript_id, "meeting_id": inst.meeting_id, "status": "uploaded", "version": 1,
            "word_count": 11_300, "compare_skipped_reason": None}


def _cluster_texts(inst):
    segs = SP.load_speech_segments(inst.transcript_id)
    by = {}
    for s in segs:
        by.setdefault(s["cluster_label"], []).append(s["text"])
    return {k: " ".join(v) for k, v in by.items()}


def test_stage_writes_every_cluster_and_merges_two_clusters_to_one_member(inst):
    texts = _cluster_texts(inst)
    labels = list(texts)
    member_id = next(iter(inst.member_ids.values()))
    quote_a = texts[labels[0]].split(".")[0][:80]
    quote_b = texts[labels[1]].split(".")[0][:80]
    assignments = [{"cluster_label": labels[0], "council_member_id": member_id, "display_name": None, "role": "council",
                    "confidence": 0.9, "method": "roll_call", "evidence_quote": quote_a, "evidence_quote_2": None},
                   {"cluster_label": labels[1], "council_member_id": member_id, "display_name": None, "role": "council",
                    "confidence": 0.9, "method": "addressed_by_chair", "evidence_quote": quote_b, "evidence_quote_2": None}]
    assignments += [{"cluster_label": l, "council_member_id": None, "display_name": None, "role": "unknown",
                     "confidence": 0.3, "method": "sample_inference", "evidence_quote": "x", "evidence_quote_2": None}
                    for l in labels[2:]]
    out = SP.run_speaker_stage(_claim(inst), client=_client(assignments))
    assert out.next_status == "speakers_resolved"
    with db_cursor() as cur:
        cur.execute("""SELECT cluster_label, council_member_id, confidence, method, needs_review
                         FROM transcript_speakers WHERE meeting_id=%s ORDER BY cluster_label""", [inst.meeting_id])
        rows = {r["cluster_label"]: r for r in cur.fetchall()}
    assert rows[labels[0]]["council_member_id"] == member_id and rows[labels[1]]["council_member_id"] == member_id
    # One verified signal each -> capped at 0.75 (medium), still displayed (floor 0.6).
    assert rows[labels[0]]["confidence"] == pytest.approx(0.75) and rows[labels[0]]["method"] == "roll_call"
    assert rows[labels[2]]["method"] == "llm_inference" and rows[labels[2]]["needs_review"] is True
    # Every non-silence segment is linked to its cluster's speaker row.
    with db_cursor() as cur:
        cur.execute("""SELECT count(*) AS n FROM transcript_segments WHERE transcript_id=%s AND is_silence=FALSE AND speaker_id IS NULL""",
                    [inst.transcript_id])
        assert cur.fetchone()["n"] == 0


def test_unverified_quote_downgrades_and_two_verified_quotes_reach_high(inst):
    texts = _cluster_texts(inst)
    labels = list(texts)
    member_id = next(iter(inst.member_ids.values()))
    sentences = [s.strip() for s in texts[labels[0]].split(".") if len(s.split()) >= 4]
    good = [{"cluster_label": labels[0], "council_member_id": member_id, "display_name": None, "role": "council",
             "confidence": 0.95, "method": "roll_call", "evidence_quote": sentences[0][:80], "evidence_quote_2": sentences[1][:80]}]
    bad = [{"cluster_label": labels[1], "council_member_id": member_id, "display_name": None, "role": "council",
            "confidence": 0.95, "method": "roll_call", "evidence_quote": "this sentence was never said by anyone",
            "evidence_quote_2": None}]
    rest = [{"cluster_label": l, "council_member_id": None, "display_name": None, "role": "unknown", "confidence": 0.2,
             "method": "sample_inference", "evidence_quote": "x", "evidence_quote_2": None} for l in labels[2:]]
    SP.run_speaker_stage(_claim(inst), client=_client(good + bad + rest))
    with db_cursor() as cur:
        cur.execute("SELECT cluster_label, confidence, method FROM transcript_speakers WHERE meeting_id=%s", [inst.meeting_id])
        rows = {r["cluster_label"]: r for r in cur.fetchall()}
    assert rows[labels[0]]["confidence"] == pytest.approx(0.95)
    assert rows[labels[1]]["confidence"] == pytest.approx(0.55) and rows[labels[1]]["method"] == "llm_inference"


def test_manual_rows_are_never_overwritten(inst):
    texts = _cluster_texts(inst)
    labels = list(texts)
    with db_cursor() as cur:
        cur.execute("""UPDATE transcript_speakers SET is_manual=TRUE, display_name='City Attorney', role='attorney',
                              confidence=1.0, method='manual' WHERE meeting_id=%s AND cluster_label=%s""",
                    [inst.meeting_id, labels[0]])
    assignments = [{"cluster_label": l, "council_member_id": None, "display_name": "Wrong Name", "role": "public",
                    "confidence": 0.9, "method": "self_identification", "evidence_quote": "x", "evidence_quote_2": None}
                   for l in labels]
    SP.run_speaker_stage(_claim(inst), client=_client(assignments))
    with db_cursor() as cur:
        cur.execute("SELECT display_name, role, is_manual FROM transcript_speakers WHERE meeting_id=%s AND cluster_label=%s",
                    [inst.meeting_id, labels[0]])
        row = cur.fetchone()
    assert (row["display_name"], row["role"], row["is_manual"]) == ("City Attorney", "attorney", True)


def test_member_id_outside_roster_is_dropped(inst):
    labels = list(_cluster_texts(inst))
    assignments = [{"cluster_label": l, "council_member_id": 999_999, "display_name": None, "role": "council",
                    "confidence": 0.9, "method": "roll_call", "evidence_quote": "x", "evidence_quote_2": None} for l in labels]
    SP.run_speaker_stage(_claim(inst), client=_client(assignments))
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM transcript_speakers WHERE meeting_id=%s AND council_member_id IS NOT NULL", [inst.meeting_id])
        assert cur.fetchone()["n"] == 0


def test_token_ceiling_holds_before_calling(inst):
    c = _client([], tokens=600_000)
    with pytest.raises(TranscriptHeld) as ei:
        SP.run_speaker_stage(_claim(inst), client=c)
    assert ei.value.reason == "token_ceiling"
    c.call.assert_not_called()


def test_schema_invalid_response_is_held(inst):
    c = _client([{"cluster_label": "S0", "confidence": "high"}])
    with pytest.raises(TranscriptHeld) as ei:
        SP.run_speaker_stage(_claim(inst), client=c)
    assert ei.value.reason == "schema_invalid"


def test_prompt_contains_every_cluster_and_silence_is_excluded(inst):
    c = _client([])
    try:
        SP.run_speaker_stage(_claim(inst), client=c)
    except TranscriptHeld:
        pass   # zero assignments for 24 clusters is schema-valid but incomplete: held as schema_invalid
    user = c.call.call_args.kwargs["user"]
    for label in _cluster_texts(inst):
        assert f"\n{label}:" in user
    assert "No speech detected" not in user
    assert c.call.call_args.kwargs["schema"]["properties"]["assignments"]
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/integration/test_speaker_stage.py -v`
Expected: FAIL, `AttributeError: module has no attribute run_speaker_stage`.

- [ ] **Step 3: Append the stage to `speakers.py`**

```python
# --- stage ------------------------------------------------------------------
import logging

from pydantic import ValidationError

from docket.ai.exceptions import TranscriptHeld
from docket.ai.transcripts.prompts import SPEAKER_SYSTEM
from docket.ai.transcripts.schemas import SPEAKER_SCHEMA, SpeakerAssignment, SpeakerResolution
from docket.config import AI_TRANSCRIPT_SPEAKER_MODEL, TRANSCRIPT_TOKEN_CEILING

log = logging.getLogger(__name__)

CONFIDENCE_CAPS = {"two_signals": 0.95, "one_signal": 0.75, "sample_inference": 0.55}
_DB_METHOD = {"roll_call": "roll_call", "addressed_by_chair": "addressed_by_chair",
              "self_identification": "llm_inference", "sample_inference": "llm_inference"}


def load_speech_segments(transcript_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute("""SELECT seq, start_s, end_s, text, cluster_label, is_silence
                         FROM transcript_segments
                        WHERE transcript_id = %s AND is_silence = FALSE AND text <> ''
                        ORDER BY seq""", [transcript_id])
        return [dict(r) for r in cur.fetchall()]


def _meeting(meeting_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute("SELECT id, title, meeting_date::text FROM meetings WHERE id = %s", [meeting_id])
        return dict(cur.fetchone())


def apply_confidence_rules(a: SpeakerAssignment, cluster_texts: dict[str, str],
                           roster_ids: set[int]) -> tuple[float, str, bool]:
    """Spec: two independent signals -> high; one -> medium cap; content-only -> below display floor.

    The model's quotes are verified against the cluster's own text. An
    unverified primary quote drops the assignment to sample_inference.
    """
    text = normalize(cluster_texts.get(a.cluster_label, ""))
    q1 = bool(a.evidence_quote.strip()) and normalize(a.evidence_quote) in text
    q2 = bool(a.evidence_quote_2 and a.evidence_quote_2.strip()) and normalize(a.evidence_quote_2 or "") in text \
        and normalize(a.evidence_quote_2 or "") != normalize(a.evidence_quote)
    method = a.method
    if method != "sample_inference" and not q1:
        method = "sample_inference"
    if method == "sample_inference":
        cap = CONFIDENCE_CAPS["sample_inference"]
    elif q1 and q2:
        cap = CONFIDENCE_CAPS["two_signals"]
    else:
        cap = CONFIDENCE_CAPS["one_signal"]
    conf = min(a.confidence, cap)
    return round(conf, 3), _DB_METHOD[method], q1


def write_assignments(meeting_id: int, transcript_id: int, resolved: list[tuple[SpeakerAssignment, float, str]],
                      roster: list[RosterMember]) -> int:
    names = {m.id: m.name for m in roster}
    updated = 0
    with db_cursor() as cur:
        for a, conf, method in resolved:
            member_id = a.council_member_id if a.council_member_id in names else None
            display = names.get(member_id) if member_id else (a.display_name or None)
            role = a.role if (member_id or a.role != "council") else "unknown"
            cur.execute(
                """UPDATE transcript_speakers
                      SET council_member_id = %s, display_name = %s, role = %s, confidence = %s, method = %s,
                          needs_review = %s
                    WHERE meeting_id = %s AND cluster_label = %s AND is_manual = FALSE""",
                [member_id, display, role, conf, method, conf < 0.6, meeting_id, a.cluster_label],
            )
            updated += cur.rowcount
        # Segments uploaded before a speaker row existed, or re-uploaded, get linked here.
        cur.execute("""UPDATE transcript_segments s SET speaker_id = sp.id
                         FROM transcript_speakers sp
                        WHERE s.transcript_id = %s AND sp.meeting_id = %s
                          AND sp.cluster_label = s.cluster_label AND s.speaker_id IS DISTINCT FROM sp.id""",
                    [transcript_id, meeting_id])
    return updated


def run_speaker_stage(claim: dict, *, client) -> "StageOutcome":
    from docket.ai.transcripts.pipeline import StageOutcome

    tid, mid = claim["id"], claim["meeting_id"]
    segments = load_speech_segments(tid)
    roster = roster_for_meeting(mid)
    packet = build_packet(segments, roster)
    if not packet.stats:
        return StageOutcome("speakers_resolved", detail="no speech clusters")
    user = render_speaker_user(packet, _meeting(mid))
    model = AI_TRANSCRIPT_SPEAKER_MODEL
    tokens = client.count_tokens(model=model, system=SPEAKER_SYSTEM, user=user)
    if tokens > TRANSCRIPT_TOKEN_CEILING:
        raise TranscriptHeld("token_ceiling", f"{tokens} tokens > ceiling {TRANSCRIPT_TOKEN_CEILING}")
    res = client.call(model=model, system=SPEAKER_SYSTEM, user=user, schema=SPEAKER_SCHEMA,
                      max_tokens=16000, effort="medium")
    try:
        parsed = SpeakerResolution.model_validate(res.data)
    except ValidationError as e:
        raise TranscriptHeld("schema_invalid", f"speaker response failed validation: {e}") from e
    labels = set(packet.stats)
    got = {a.cluster_label for a in parsed.assignments}
    if not labels <= got:
        raise TranscriptHeld("schema_invalid", f"missing assignments for clusters {sorted(labels - got)[:5]}")
    cluster_texts: dict[str, str] = {}
    for s in segments:
        if s.get("cluster_label"):
            cluster_texts[s["cluster_label"]] = cluster_texts.get(s["cluster_label"], "") + " " + s["text"]
    roster_ids = {m.id for m in roster}
    resolved = []
    for a in parsed.assignments:
        if a.cluster_label not in labels:
            continue
        conf, method, _ = apply_confidence_rules(a, cluster_texts, roster_ids)
        resolved.append((a, conf, method))
    n = write_assignments(mid, tid, resolved, roster)
    log.info("speakers: meeting %s clusters=%d updated=%d roll_calls=%d addresses=%d tokens=%d",
             mid, len(labels), n, len(packet.roll_calls), len(packet.addresses), tokens)
    return StageOutcome("speakers_resolved", detail=f"{n} clusters")
```

Move the `import logging` and `log = ...` to the top of the module when appending; the stage imports from `pipeline` lazily inside the function to avoid a cycle.

- [ ] **Step 4: Run to verify pass**

Run: `venv/bin/python -m pytest tests/integration/test_speaker_stage.py tests/unit/test_speaker_signals.py -v`
Expected: all PASS.

- [ ] **Step 5: Live smoke on meeting 2543 before anything builds on the stage (house rule)**

Run, against the local database with the fixture installed, using the real model once (about $0.15):

```bash
ANTHROPIC_API_KEY=... venv/bin/python - <<'PY'
from tests.support.transcript_fixtures import install_bundle, load_bundle
from docket.ai.transcripts.client import StructuredClient
from docket.ai.transcripts import speakers as SP
from docket.db import db_cursor
inst = install_bundle(load_bundle("transcript_2543"))
try:
    claim = {"id": inst.transcript_id, "meeting_id": inst.meeting_id, "status": "uploaded", "version": 1, "word_count": 11300, "compare_skipped_reason": None}
    print(SP.run_speaker_stage(claim, client=StructuredClient()))
    with db_cursor() as cur:
        cur.execute("""SELECT sp.cluster_label, cm.name, sp.display_name, sp.role, sp.confidence, sp.method
                         FROM transcript_speakers sp LEFT JOIN council_members cm ON cm.id = sp.council_member_id
                        WHERE sp.meeting_id=%s ORDER BY sp.confidence DESC NULLS LAST""", [inst.meeting_id])
        for r in cur.fetchall(): print(dict(r))
finally:
    inst.cleanup()
PY
```

Expected: 24 rows; several clusters resolve to the same council members at 0.75 or 0.95; the chair (council president) and clerk identified by role; no `council_member_id` outside the roster. Paste the output into the PR. If the model returns fewer than 24 assignments, strengthen the closing line of `render_speaker_user` before continuing.

- [ ] **Step 6: Commit**

```bash
git add src/docket/ai/transcripts/speakers.py tests/integration/test_speaker_stage.py
git -c user.email=hello@docket.pub commit -m "feat(ai): speaker resolution stage with verified quotes and confidence caps

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Minutes capture with page offsets and change detection

**Files:**
- Create: `src/docket/ai/transcripts/minutes.py`
- Test: `tests/unit/test_minutes_extract.py`, `tests/integration/test_minutes_capture.py`

**Interfaces:**
- Consumes: `docket.analysis.ocr.frame_io.BROWSER_USER_AGENT`, pdfplumber, `requests`.
- Produces:
  - `download_minutes(url: str, timeout: int = 30) -> bytes | None` — browser user agent, `%PDF-` check, `None` on any `requests.RequestException` or non-PDF body.
  - `extract_pages(pdf_bytes: bytes) -> tuple[str, list[int]]` — `page.extract_text()` without layout mode, pages joined by `"\n"`, `page_offsets[i]` = character offset where page `i+1` starts.
  - `page_for_offset(page_offsets: list[int], offset: int) -> int` (1-based).
  - `@dataclass MinutesCapture(minutes_text_id: int, text: str, page_offsets: list[int], sha256: str, changed: bool, is_new: bool)`.
  - `capture_minutes(meeting_id: int, minutes_url: str) -> MinutesCapture | None` — upserts `minutes_texts`; `changed` is true when a row existed with a different `pdf_sha256` or `source_url`.
  - `load_minutes(meeting_id: int) -> MinutesCapture | None` (no download).
  - `recheck_minutes(meeting_id: int) -> bool | None` — downloads, compares sha, upserts on change; `True` changed, `False` same, `None` unavailable. Used by Task 12.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_minutes_extract.py
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from docket.ai.transcripts.minutes import download_minutes, extract_pages, page_for_offset

AGENDA_PDF = Path("tests/fixtures/granicus_bham_agenda_2026_05_19.pdf")


def test_extract_pages_offsets_line_up_with_text():
    text, offsets = extract_pages(AGENDA_PDF.read_bytes())
    assert offsets[0] == 0 and len(text) > 500
    assert offsets == sorted(offsets) and all(o <= len(text) for o in offsets)
    import pdfplumber, io
    with pdfplumber.open(io.BytesIO(AGENDA_PDF.read_bytes())) as pdf:
        assert len(offsets) == len(pdf.pages)
        first_line = (pdf.pages[0].extract_text() or "").splitlines()[0]
    assert text.startswith(first_line)
    assert "\f" not in text


def test_page_for_offset_is_one_based_and_bisects():
    assert page_for_offset([0, 100, 250], 0) == 1
    assert page_for_offset([0, 100, 250], 99) == 1
    assert page_for_offset([0, 100, 250], 100) == 2
    assert page_for_offset([0, 100, 250], 9999) == 3


@patch("docket.ai.transcripts.minutes.requests.get")
def test_download_sends_browser_user_agent_and_rejects_html(get):
    get.return_value = MagicMock(content=b"<html>login</html>", status_code=200)
    get.return_value.raise_for_status = lambda: None
    assert download_minutes("https://bhamal.granicus.com/MinutesViewer.php?clip_id=1") is None
    assert get.call_args.kwargs["headers"]["User-Agent"].startswith("Mozilla/5.0")
    get.return_value.content = b"%PDF-1.4 ..."
    assert download_minutes("https://x") == b"%PDF-1.4 ..."
    get.side_effect = requests.ConnectionError("boom")
    assert download_minutes("https://x") is None
```

```python
# tests/integration/test_minutes_capture.py
from pathlib import Path

import pytest

from docket.ai.transcripts import minutes as M
from docket.config import DATABASE_URL
from docket.db import db_cursor

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)
PDF = Path("tests/fixtures/granicus_bham_agenda_2026_05_19.pdf").read_bytes()
URL = "https://bhamal.granicus.com/MinutesViewer.php?view_id=2&clip_id=999"


@pytest.fixture
def meeting():
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, external_id, minutes_url)
                       VALUES (%s, 'MC test', '2026-09-03', '999903', %s) RETURNING id""", [muni, URL])
        mid = cur.fetchone()["id"]
    yield mid
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id=%s", [mid])


def test_capture_inserts_then_detects_change(meeting, monkeypatch):
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30: PDF)
    c1 = M.capture_minutes(meeting, URL)
    assert c1.is_new and not c1.changed and len(c1.page_offsets) >= 1 and len(c1.sha256) == 64
    c2 = M.capture_minutes(meeting, URL)
    assert not c2.is_new and not c2.changed and c2.minutes_text_id == c1.minutes_text_id
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30: PDF + b"\n% corrected")
    c3 = M.capture_minutes(meeting, URL)
    assert c3.changed and c3.sha256 != c1.sha256 and c3.minutes_text_id == c1.minutes_text_id
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM minutes_texts WHERE meeting_id=%s", [meeting])
        assert cur.fetchone()["n"] == 1
    assert M.recheck_minutes(meeting) is False


def test_html_page_instead_of_pdf_returns_none_and_writes_nothing(meeting, monkeypatch):
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30: None)
    assert M.capture_minutes(meeting, URL) is None
    assert M.load_minutes(meeting) is None
    assert M.recheck_minutes(meeting) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/unit/test_minutes_extract.py tests/integration/test_minutes_capture.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write `minutes.py`**

```python
# src/docket/ai/transcripts/minutes.py
"""Minutes PDF -> text with page offsets, stored once per meeting in minutes_texts.

The existing minutes_parser.extract_text_from_pdf joins pages and drops the
page boundaries; the comparison needs `page` on every minutes event and
discrepancy, so this extractor keeps offsets. Layout mode is deliberately off
(single-column minutes; layout mode is what introduces column breaks).
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
from bisect import bisect_right
from dataclasses import dataclass

import pdfplumber
import requests

from docket.analysis.ocr.frame_io import BROWSER_USER_AGENT
from docket.db import db_cursor

log = logging.getLogger(__name__)


def download_minutes(url: str, timeout: int = 30) -> bytes | None:
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=True,
                            headers={"User-Agent": BROWSER_USER_AGENT})
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning("minutes download failed %s: %s", url, e)
        return None
    if not resp.content[:5] == b"%PDF-":
        log.warning("minutes URL did not return a PDF: %s", url)
        return None
    return resp.content


def extract_pages(pdf_bytes: bytes) -> tuple[str, list[int]]:
    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            pages.append((page.extract_text() or "").replace("\f", ""))
    offsets, pos = [], 0
    for p in pages:
        offsets.append(pos)
        pos += len(p) + 1          # the "\n" joiner
    return "\n".join(pages), offsets


def page_for_offset(page_offsets: list[int], offset: int) -> int:
    return max(1, bisect_right(page_offsets, offset))


@dataclass
class MinutesCapture:
    minutes_text_id: int
    text: str
    page_offsets: list[int]
    sha256: str
    changed: bool
    is_new: bool


def load_minutes(meeting_id: int) -> MinutesCapture | None:
    with db_cursor() as cur:
        cur.execute("SELECT id, text, page_offsets, pdf_sha256 FROM minutes_texts WHERE meeting_id = %s", [meeting_id])
        row = cur.fetchone()
    if not row:
        return None
    return MinutesCapture(row["id"], row["text"], list(row["page_offsets"]), row["pdf_sha256"], False, False)


def capture_minutes(meeting_id: int, minutes_url: str) -> MinutesCapture | None:
    pdf = download_minutes(minutes_url)
    if pdf is None:
        return None
    sha = hashlib.sha256(pdf).hexdigest()
    with db_cursor() as cur:
        cur.execute("SELECT id, pdf_sha256, source_url, text, page_offsets FROM minutes_texts WHERE meeting_id = %s", [meeting_id])
        existing = cur.fetchone()
        if existing and existing["pdf_sha256"] == sha and existing["source_url"] == minutes_url:
            return MinutesCapture(existing["id"], existing["text"], list(existing["page_offsets"]), sha, False, False)
        text, offsets = extract_pages(pdf)
        cur.execute(
            """INSERT INTO minutes_texts (meeting_id, source_url, pdf_sha256, text, page_offsets, extracted_at)
               VALUES (%s, %s, %s, %s, %s::jsonb, now())
               ON CONFLICT (meeting_id) DO UPDATE
                 SET source_url = EXCLUDED.source_url, pdf_sha256 = EXCLUDED.pdf_sha256, text = EXCLUDED.text,
                     page_offsets = EXCLUDED.page_offsets, extracted_at = now()
               RETURNING id""",
            [meeting_id, minutes_url, sha, text, json.dumps(offsets)],
        )
        mt_id = cur.fetchone()["id"]
    return MinutesCapture(mt_id, text, offsets, sha, changed=existing is not None, is_new=existing is None)


def recheck_minutes(meeting_id: int) -> bool | None:
    with db_cursor() as cur:
        cur.execute("SELECT minutes_url FROM meetings WHERE id = %s", [meeting_id])
        row = cur.fetchone()
    if not row or not row["minutes_url"]:
        return None
    cap = capture_minutes(meeting_id, row["minutes_url"])
    return None if cap is None else cap.changed
```

- [ ] **Step 4: Run to verify pass**

Run: `venv/bin/python -m pytest tests/unit/test_minutes_extract.py tests/integration/test_minutes_capture.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/docket/ai/transcripts/minutes.py tests/unit/test_minutes_extract.py tests/integration/test_minutes_capture.py
git -c user.email=hello@docket.pub commit -m "feat(ai): minutes capture with page offsets, browser UA, change detection

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Event extraction stage (both sides) and segment re-assignment

**Files:**
- Create: `src/docket/ai/transcripts/events.py`
- Test: `tests/unit/test_events_render.py`, `tests/integration/test_events_stage.py`

**Interfaces:**
- Consumes: `StructuredClient` (Task 1); `EVENTS_TRANSCRIPT_SYSTEM`, `EVENTS_MINUTES_SYSTEM`, `EVENTS_PROMPT_VERSION` (Task 2); `EVENTS_SCHEMA`, `EventList`, `ExtractedEvent` (Task 2); `guard.find_citation` (Task 5); `speakers.roster_for_meeting`, `speakers.mentioned_members`, `speakers.hms` (Task 6); `minutes.capture_minutes`, `load_minutes`, `page_for_offset` (Task 8); `StageOutcome`, `TranscriptHeld` (Task 4); `docket.services.transcripts.speaker_ordinals`, `SPEAKER_CONFIDENCE_FLOOR`.
- Produces:
  - `load_segments_with_speakers(transcript_id) -> list[dict]` keys `id, seq, start_s, end_s, text, cluster_label, agenda_item_id, speaker_name, speaker_confidence`.
  - `load_agenda(meeting_id) -> list[dict]` keys `id, item_number, title, is_consent, external_id, video_timestamp_seconds`.
  - `render_agenda(agenda) -> str`; `render_transcript(segments, agenda, ordinals) -> str` (one `[seq=N t=HH:MM:SS Label] text` line per segment, `=== Item ... ===` marker where `agenda_item_id` changes); `render_minutes(text, page_offsets) -> str` (`[[page N]]` markers).
  - `extract_side(*, client, model, system, user) -> EventList` (ceiling check, call, validate; raises `TranscriptHeld`).
  - `match_actor(text: str | None, roster) -> int | None` (exactly one surname hit).
  - `write_events(meeting_id, source, events: list[ExtractedEvent], *, segments=None, minutes=None, roster, valid_item_ids) -> list[dict]` — replaces that source's rows; returns the inserted rows with ids, `seq`, `start_s`, `segment_id`, `page`, `char_offset`.
  - `reassign_segments_from_events(transcript_id, transcript_event_rows) -> int`.
  - `extract_minutes_side(meeting_id, *, client) -> str` returning `"ok"`, `"no_minutes"`, or `"minutes_unavailable"`.
  - `run_events_stage(claim, *, client) -> StageOutcome` (`events_extracted`; `skipped_reason` set when the minutes side could not run).

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/unit/test_events_render.py
from docket.ai.transcripts.events import render_agenda, render_minutes, render_transcript

AGENDA = [{"id": 10, "item_number": "1", "title": "Minutes approval", "is_consent": False, "external_id": "1-1", "video_timestamp_seconds": 900.0},
          {"id": 11, "item_number": "2", "title": "Consent: street closure", "is_consent": True, "external_id": "1-2", "video_timestamp_seconds": 1500.0}]


def test_render_transcript_labels_speakers_and_marks_items():
    segs = [{"id": 1, "seq": 0, "start_s": 0, "end_s": 890, "text": "", "cluster_label": None, "agenda_item_id": None, "is_silence": True,
             "speaker_name": None, "speaker_confidence": None},
            {"id": 2, "seq": 1, "start_s": 905, "end_s": 910, "text": "We are called to order.", "cluster_label": "S0", "agenda_item_id": 10,
             "is_silence": False, "speaker_name": "Darrell O'Quinn", "speaker_confidence": 0.75},
            {"id": 3, "seq": 2, "start_s": 1510, "end_s": 1515, "text": "Move approval.", "cluster_label": "S4", "agenda_item_id": 11,
             "is_silence": False, "speaker_name": "Maybe Someone", "speaker_confidence": 0.4}]
    out = render_transcript(segs, AGENDA, {"S0": 1, "S4": 2})
    assert "No speech" not in out and "[seq=0" not in out                     # silence excluded
    assert "=== Item 1 (agenda_item_id=10): Minutes approval ===" in out
    assert "[seq=1 t=00:15:05 Darrell O'Quinn] We are called to order." in out
    assert "[seq=2 t=00:25:10 Speaker 2] Move approval." in out                 # below the 0.6 floor -> Speaker N
    assert out.index("agenda_item_id=10") < out.index("agenda_item_id=11")


def test_render_agenda_flags_consent():
    out = render_agenda(AGENDA)
    assert "id=10 Item 1: Minutes approval" in out and "id=11 Item 2 [consent]: Consent: street closure" in out


def test_render_minutes_inserts_page_markers():
    text = "page one text\npage two text\npage three"
    out = render_minutes(text, [0, 14, 28])
    assert out.startswith("[[page 1]]\npage one text")
    assert "[[page 2]]\npage two text" in out and "[[page 3]]\npage three" in out
```

- [ ] **Step 2: Write the failing integration tests**

```python
# tests/integration/test_events_stage.py
from unittest.mock import MagicMock

import pytest

from docket.ai.exceptions import TranscriptHeld
from docket.ai.pricing import Usage
from docket.ai.transcripts import events as EV
from docket.ai.transcripts import minutes as M
from docket.ai.transcripts.client import StructuredResult
from docket.config import DATABASE_URL
from docket.db import db_cursor
from tests.support.transcript_fixtures import install_bundle, load_bundle, pilot_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


def _ev(**kw):
    base = {"event_type": "motion", "scope": "item", "agenda_item_refs": [], "actor_text": None, "actor_member_id": None,
            "summary": "s", "detail": {}, "segment_seq": None, "page": None, "quote": None}
    base.update(kw)
    return base


def _client(transcript_events, minutes_events=None, tokens=80_000):
    c = MagicMock()
    c.count_tokens.return_value = tokens
    results = [StructuredResult({"events": transcript_events}, Usage(10, 0, 0, 5), "m", "end_turn")]
    if minutes_events is not None:
        results.append(StructuredResult({"events": minutes_events}, Usage(10, 0, 0, 5), "m", "end_turn"))
    c.call.side_effect = results
    return c


def _claim(inst, status="speakers_resolved"):
    return {"id": inst.transcript_id, "meeting_id": inst.meeting_id, "status": status, "version": 1,
            "word_count": 650, "compare_skipped_reason": None}


@pytest.fixture
def pilot():
    i = install_bundle(pilot_bundle(), external_id="999015")
    yield i
    i.cleanup()


def test_both_sides_written_with_anchors_and_pages(pilot, monkeypatch):
    item = pilot.item_ids[1501]
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30: None)   # fixture row already holds the text
    t_events = [_ev(event_type="item_opened", agenda_item_refs=[item], segment_seq=0, quote="executed a contract vendor CGI"),
                _ev(event_type="executive_session_motion", agenda_item_refs=[item], segment_seq=40,
                    detail={"stated_reason": "security plans", "statute_cite": "36, 25, a seven a four"},
                    quote=None),
                _ev(event_type="vote", agenda_item_refs=[item], segment_seq=70, detail={"result": "passed", "method": "voice"},
                    quote="Item 15 passes")]
    m_events = [_ev(event_type="vote", agenda_item_refs=[item], page=1, detail={"result": "passed"},
                    quote="said ordinance adopted"),
                _ev(event_type="executive_session_motion", agenda_item_refs=[item], page=1, actor_text="O'Quinn",
                    detail={"stated_reason": "pending litigation", "mover": "O'Quinn", "seconder": "Tate"},
                    quote="go into Executive Session at the recommendation of the City Attorney")]
    out = EV.run_events_stage(_claim(pilot), client=_client(t_events, m_events))
    assert out.next_status == "events_extracted" and out.skipped_reason is None
    with db_cursor() as cur:
        cur.execute("""SELECT source, seq, event_type, start_s, segment_id, page, char_offset, actor_member_id, agenda_item_refs, prompt_version
                         FROM meeting_events WHERE meeting_id=%s ORDER BY source, seq""", [pilot.meeting_id])
        rows = [dict(r) for r in cur.fetchall()]
    t = [r for r in rows if r["source"] == "transcript"]
    m = [r for r in rows if r["source"] == "minutes"]
    assert [r["event_type"] for r in t] == ["item_opened", "executive_session_motion", "vote"]
    assert t[0]["start_s"] == pytest.approx(3290.0) and t[0]["segment_id"] is not None
    assert all(r["prompt_version"] == 200 for r in rows)
    assert m[1]["char_offset"] is not None and m[1]["page"] >= 1          # guard found the quote; page from offsets
    assert m[1]["actor_member_id"] == pilot.member_ids[9000]              # "O'Quinn" matched to the roster id
    assert all(r["agenda_item_refs"] == [item] for r in rows)


def test_no_minutes_url_skips_minutes_side_without_failing(monkeypatch):
    inst = install_bundle(load_bundle("transcript_2543"), status="speakers_resolved")
    try:
        with db_cursor() as cur:
            cur.execute("UPDATE meetings SET minutes_url=NULL WHERE id=%s", [inst.meeting_id])
        c = _client([_ev(event_type="adjourn", scope="meeting", segment_seq=5, quote="x")])
        out = EV.run_events_stage(_claim(inst), client=c)
        assert out.next_status == "events_extracted" and out.skipped_reason == "no_minutes"
        assert c.call.call_count == 1
    finally:
        inst.cleanup()


def test_unavailable_minutes_is_a_skip_not_a_failure(pilot, monkeypatch):
    with db_cursor() as cur:
        cur.execute("DELETE FROM minutes_texts WHERE meeting_id=%s", [pilot.meeting_id])
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30: None)   # Review Focus 1: an HTML page came back
    out = EV.run_events_stage(_claim(pilot), client=_client([_ev(event_type="adjourn", scope="meeting", segment_seq=5, quote="x")]))
    assert out.skipped_reason == "minutes_unavailable" and out.next_status == "events_extracted"


def test_item_opened_events_reassign_segments(pilot, monkeypatch):
    item = pilot.item_ids[1501]
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30: None)
    with db_cursor() as cur:   # pretend the index point put the first segments on nothing
        cur.execute("UPDATE transcript_segments SET agenda_item_id=NULL, assignment_method=NULL WHERE transcript_id=%s", [pilot.transcript_id])
        cur.execute("UPDATE transcript_segments SET assignment_method='manual', agenda_item_id=NULL WHERE transcript_id=%s AND seq=3",
                    [pilot.transcript_id])
    EV.run_events_stage(_claim(pilot), client=_client(
        [_ev(event_type="item_opened", agenda_item_refs=[item], segment_seq=2, quote="x")], []))
    with db_cursor() as cur:
        cur.execute("SELECT seq, agenda_item_id, assignment_method FROM transcript_segments WHERE transcript_id=%s ORDER BY seq", [pilot.transcript_id])
        rows = cur.fetchall()
    assert rows[1]["agenda_item_id"] is None                                   # before the opening
    assert (rows[2]["agenda_item_id"], rows[2]["assignment_method"]) == (item, "event")
    assert (rows[3]["agenda_item_id"], rows[3]["assignment_method"]) == (None, "manual")   # manual untouched
    assert rows[10]["assignment_method"] == "event"


def test_invalid_item_refs_are_dropped_and_ceiling_holds(pilot, monkeypatch):
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30: None)
    EV.run_events_stage(_claim(pilot), client=_client([_ev(event_type="motion", agenda_item_refs=[123456789], segment_seq=2, quote="x")], []))
    with db_cursor() as cur:
        cur.execute("SELECT agenda_item_refs FROM meeting_events WHERE meeting_id=%s AND source='transcript'", [pilot.meeting_id])
        assert cur.fetchone()["agenda_item_refs"] == []
    with pytest.raises(TranscriptHeld) as ei:
        EV.run_events_stage(_claim(pilot), client=_client([], [], tokens=700_000))
    assert ei.value.reason == "token_ceiling"


def test_rerun_replaces_only_that_source(pilot, monkeypatch):
    monkeypatch.setattr(M, "download_minutes", lambda url, timeout=30: None)
    EV.run_events_stage(_claim(pilot), client=_client([_ev(event_type="adjourn", scope="meeting", segment_seq=5, quote="x")],
                                                      [_ev(event_type="adjourn", scope="meeting", page=1, quote="y")]))
    EV.run_events_stage(_claim(pilot), client=_client([_ev(event_type="recess", scope="meeting", segment_seq=5, quote="x")],
                                                      [_ev(event_type="adjourn", scope="meeting", page=1, quote="y")]))
    with db_cursor() as cur:
        cur.execute("SELECT source, event_type FROM meeting_events WHERE meeting_id=%s ORDER BY source", [pilot.meeting_id])
        assert [(r["source"], r["event_type"]) for r in cur.fetchall()] == [("minutes", "adjourn"), ("transcript", "recess")]
```

- [ ] **Step 3: Run to verify failure**

Run: `venv/bin/python -m pytest tests/unit/test_events_render.py tests/integration/test_events_stage.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 4: Write `events.py`**

```python
# src/docket/ai/transcripts/events.py
"""Event extraction: one Sonnet 5.5 call per side, rows into meeting_events.

Transcript side always runs. Minutes side runs when the meeting has a
minutes URL and the PDF downloads; otherwise the transcript stops at
events_extracted with compare_skipped_reason set and is re-claimed when
minutes appear (pipeline.CLAIM_SQL). Confident item_opened events re-assign
segments with assignment_method = 'event' (spec: index point drift).
"""
from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from docket.ai.exceptions import TranscriptHeld
from docket.ai.transcripts.guard import find_citation
from docket.ai.transcripts.minutes import MinutesCapture, capture_minutes, load_minutes, page_for_offset
from docket.ai.transcripts.prompts import EVENTS_MINUTES_SYSTEM, EVENTS_PROMPT_VERSION, EVENTS_TRANSCRIPT_SYSTEM
from docket.ai.transcripts.schemas import EVENTS_SCHEMA, EventList, ExtractedEvent
from docket.ai.transcripts.speakers import RosterMember, hms, mentioned_members, roster_for_meeting
from docket.config import AI_TRANSCRIPT_EVENTS_MODEL, TRANSCRIPT_TOKEN_CEILING
from docket.db import db_cursor
from docket.services.transcripts import SPEAKER_CONFIDENCE_FLOOR, speaker_ordinals

log = logging.getLogger(__name__)


def load_segments_with_speakers(transcript_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute("""SELECT s.id, s.seq, s.start_s, s.end_s, s.text, s.cluster_label, s.agenda_item_id, s.is_silence,
                              COALESCE(cm.name, sp.display_name) AS speaker_name, sp.confidence AS speaker_confidence
                         FROM transcript_segments s
                         LEFT JOIN transcript_speakers sp ON sp.id = s.speaker_id
                         LEFT JOIN council_members cm ON cm.id = sp.council_member_id
                        WHERE s.transcript_id = %s ORDER BY s.seq""", [transcript_id])
        return [dict(r) for r in cur.fetchall()]


def load_agenda(meeting_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute("""SELECT id, item_number, title, is_consent, external_id, video_timestamp_seconds
                         FROM agenda_items WHERE meeting_id = %s
                        ORDER BY video_timestamp_seconds NULLS LAST, id""", [meeting_id])
        return [dict(r) for r in cur.fetchall()]


def render_agenda(agenda: list[dict]) -> str:
    lines = ["Agenda items (id, number, title):"]
    for a in agenda:
        flag = " [consent]" if a.get("is_consent") else ""
        lines.append(f"  id={a['id']} Item {a.get('item_number') or '?'}{flag}: {a['title']}")
    return "\n".join(lines)


def _label(seg: dict, ordinals: dict[str, int]) -> str:
    name, conf = seg.get("speaker_name"), seg.get("speaker_confidence")
    if name and (conf is None or conf >= SPEAKER_CONFIDENCE_FLOOR):
        return name
    cl = seg.get("cluster_label")
    return f"Speaker {ordinals.get(cl, 0)}" if cl else "Unknown speaker"


def render_transcript(segments: list[dict], agenda: list[dict], ordinals: dict[str, int]) -> str:
    by_id = {a["id"]: a for a in agenda}
    lines, current = [], object()
    for s in segments:
        if s.get("is_silence") or not (s.get("text") or "").strip():
            continue
        if s.get("agenda_item_id") != current and s.get("agenda_item_id") in by_id:
            a = by_id[s["agenda_item_id"]]
            lines.append(f"=== Item {a.get('item_number') or '?'} (agenda_item_id={a['id']}): {a['title']} ===")
        current = s.get("agenda_item_id")
        lines.append(f"[seq={s['seq']} t={hms(s['start_s'])} {_label(s, ordinals)}] {s['text'].strip()}")
    return "\n".join(lines)


def render_minutes(text: str, page_offsets: list[int]) -> str:
    out, offsets = [], list(page_offsets) + [len(text)]
    for i in range(len(page_offsets)):
        out.append(f"[[page {i + 1}]]\n{text[offsets[i]:offsets[i + 1]].rstrip(chr(10))}")
    return "\n".join(out)


def extract_side(*, client, model: str, system: str, user: str) -> EventList:
    tokens = client.count_tokens(model=model, system=system, user=user)
    if tokens > TRANSCRIPT_TOKEN_CEILING:
        raise TranscriptHeld("token_ceiling", f"{tokens} tokens > ceiling {TRANSCRIPT_TOKEN_CEILING}")
    res = client.call(model=model, system=system, user=user, schema=EVENTS_SCHEMA, max_tokens=64000, effort="medium")
    try:
        return EventList.model_validate(res.data)
    except ValidationError as e:
        raise TranscriptHeld("schema_invalid", f"events response failed validation: {e}") from e


def match_actor(text: str | None, roster: list[RosterMember]) -> int | None:
    if not text:
        return None
    hits = mentioned_members(text, roster)
    return hits[0].id if len(hits) == 1 else None


def write_events(meeting_id: int, source: str, events: list[ExtractedEvent], *, segments: list[dict] | None = None,
                 minutes: MinutesCapture | None = None, roster: list[RosterMember], valid_item_ids: set[int]) -> list[dict]:
    by_seq = {s["seq"]: s for s in (segments or [])}
    roster_ids = {m.id for m in roster}
    rows: list[dict] = []
    with db_cursor() as cur:
        cur.execute("DELETE FROM meeting_events WHERE meeting_id = %s AND source = %s", [meeting_id, source])
        for i, ev in enumerate(events):
            refs = [r for r in ev.agenda_item_refs if r in valid_item_ids]
            actor = ev.actor_member_id if ev.actor_member_id in roster_ids else match_actor(ev.actor_text, roster)
            start_s = segment_id = page = char_offset = None
            if source == "transcript":
                seg = by_seq.get(ev.segment_seq) if ev.segment_seq is not None else None
                if seg:
                    start_s, segment_id = seg["start_s"], seg["id"]
            else:
                page = ev.page
                if minutes and ev.quote:
                    cm = find_citation(ev.quote, minutes.text)
                    if cm.kind != "missing":
                        char_offset = cm.start
                        page = page_for_offset(minutes.page_offsets, cm.start)
            cur.execute(
                """INSERT INTO meeting_events (meeting_id, source, seq, event_type, scope, agenda_item_refs, actor_member_id,
                                               actor_text, summary, detail, start_s, page, char_offset, segment_id, prompt_version)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
                   RETURNING id""",
                [meeting_id, source, i, ev.event_type, ev.scope, refs, actor, ev.actor_text, ev.summary,
                 json.dumps({**ev.detail.compact(), **({"quote": ev.quote} if ev.quote else {})}),
                 start_s, page, char_offset, segment_id, EVENTS_PROMPT_VERSION],
            )
            rows.append({"id": cur.fetchone()["id"], "seq": i, "event_type": ev.event_type, "agenda_item_refs": refs,
                         "start_s": start_s, "segment_id": segment_id, "segment_seq": ev.segment_seq, "page": page,
                         "char_offset": char_offset})
    return rows


def reassign_segments_from_events(transcript_id: int, transcript_rows: list[dict]) -> int:
    opens = sorted([r for r in transcript_rows if r["event_type"] == "item_opened" and r.get("segment_seq") is not None
                    and len(r["agenda_item_refs"]) == 1], key=lambda r: r["segment_seq"])
    n = 0
    with db_cursor() as cur:
        for i, r in enumerate(opens):
            lo = r["segment_seq"]
            hi = opens[i + 1]["segment_seq"] if i + 1 < len(opens) else None
            cur.execute(
                """UPDATE transcript_segments SET agenda_item_id = %s, assignment_method = 'event'
                    WHERE transcript_id = %s AND is_silence = FALSE AND seq >= %s AND (%s::int IS NULL OR seq < %s)
                      AND assignment_method IS DISTINCT FROM 'manual'""",
                [r["agenda_item_refs"][0], transcript_id, lo, hi, hi],
            )
            n += cur.rowcount
    return n


def _meeting(meeting_id: int) -> dict:
    with db_cursor() as cur:
        cur.execute("SELECT id, title, meeting_date::text, minutes_url FROM meetings WHERE id = %s", [meeting_id])
        return dict(cur.fetchone())


def extract_minutes_side(meeting_id: int, *, client) -> str:
    meeting = _meeting(meeting_id)
    if not meeting.get("minutes_url"):
        return "no_minutes"
    minutes = capture_minutes(meeting_id, meeting["minutes_url"]) or load_minutes(meeting_id)
    if minutes is None:
        return "minutes_unavailable"
    agenda = load_agenda(meeting_id)
    roster = roster_for_meeting(meeting_id)
    user = (f"Meeting: {meeting['title']} on {meeting['meeting_date']}\n\n{render_agenda(agenda)}\n\n"
            f"Minutes text:\n{render_minutes(minutes.text, minutes.page_offsets)}")
    parsed = extract_side(client=client, model=AI_TRANSCRIPT_EVENTS_MODEL, system=EVENTS_MINUTES_SYSTEM, user=user)
    rows = write_events(meeting_id, "minutes", parsed.events, minutes=minutes, roster=roster,
                        valid_item_ids={a["id"] for a in agenda})
    log.info("events: meeting %s minutes side %d events", meeting_id, len(rows))
    return "ok"


def run_events_stage(claim: dict, *, client) -> "StageOutcome":
    from docket.ai.transcripts.pipeline import StageOutcome

    tid, mid = claim["id"], claim["meeting_id"]
    meeting = _meeting(mid)
    segments = load_segments_with_speakers(tid)
    agenda = load_agenda(mid)
    roster = roster_for_meeting(mid)
    user = (f"Meeting: {meeting['title']} on {meeting['meeting_date']}\n\n{render_agenda(agenda)}\n\n"
            f"Transcript:\n{render_transcript(segments, agenda, speaker_ordinals(tid))}")
    parsed = extract_side(client=client, model=AI_TRANSCRIPT_EVENTS_MODEL, system=EVENTS_TRANSCRIPT_SYSTEM, user=user)
    rows = write_events(mid, "transcript", parsed.events, segments=segments, roster=roster,
                        valid_item_ids={a["id"] for a in agenda})
    reassigned = reassign_segments_from_events(tid, rows)
    log.info("events: meeting %s transcript side %d events, %d segments re-assigned", mid, len(rows), reassigned)
    minutes_status = extract_minutes_side(mid, client=client)
    skipped = None if minutes_status == "ok" else minutes_status
    return StageOutcome("events_extracted", skipped_reason=skipped, detail=f"{len(rows)} transcript events; minutes {minutes_status}")
```

The quote is stored inside `detail.quote` so the comparison stage can show the judge the exact text the extractor relied on without re-reading segments.

- [ ] **Step 5: Run to verify pass**

Run: `venv/bin/python -m pytest tests/unit/test_events_render.py tests/integration/test_events_stage.py -v`
Expected: 9 PASS.

- [ ] **Step 6: Live smoke on meeting 2543's transcript side (house rule, about $0.40)**

```bash
ANTHROPIC_API_KEY=... venv/bin/python - <<'PY'
from tests.support.transcript_fixtures import install_bundle, load_bundle
from docket.ai.transcripts.client import StructuredClient
from docket.ai.transcripts import events as EV
from docket.db import db_cursor
inst = install_bundle(load_bundle("transcript_2543"), status="speakers_resolved")
try:
    with db_cursor() as cur: cur.execute("UPDATE meetings SET minutes_url=NULL WHERE id=%s", [inst.meeting_id])
    claim = {"id": inst.transcript_id, "meeting_id": inst.meeting_id, "status": "speakers_resolved", "version": 1, "word_count": 11300, "compare_skipped_reason": None}
    print(EV.run_events_stage(claim, client=StructuredClient()))
    with db_cursor() as cur:
        cur.execute("SELECT event_type, count(*) FROM meeting_events WHERE meeting_id=%s GROUP BY 1 ORDER BY 2 DESC", [inst.meeting_id])
        print([tuple(r.values()) for r in cur.fetchall()])
        cur.execute("SELECT seq, event_type, agenda_item_refs, start_s, summary FROM meeting_events WHERE meeting_id=%s ORDER BY seq LIMIT 25", [inst.meeting_id])
        for r in cur.fetchall(): print(dict(r))
finally:
    inst.cleanup()
PY
```

Expected: dozens of events, every `motion`/`vote` carrying item refs, `start_s` set on every row, `item_opened` events in time order, no `statement` events during roll call. Paste the type counts into the PR.

- [ ] **Step 7: Commit**

```bash
git add src/docket/ai/transcripts/events.py tests/unit/test_events_render.py tests/integration/test_events_stage.py
git -c user.email=hello@docket.pub commit -m "feat(ai): event extraction stage for transcript and minutes sides

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Deterministic aligner (pure)

**Files:**
- Create: `src/docket/ai/transcripts/aligner.py`
- Test: `tests/unit/test_aligner.py`

**Interfaces:**
- Consumes: `guard.canonical_statute`, `guard.normalize` (Task 5).
- Produces:
  - `@dataclass(frozen=True) Event(id: int, source: str, seq: int, event_type: str, scope: str, item_refs: frozenset[int], actor_member_id: int | None, actor_text: str | None, summary: str, detail: dict, start_s: float | None, page: int | None, char_offset: int | None)`; `event_from_row(row: dict) -> Event`.
  - `@dataclass Candidate(candidate_id: int, kind: str, category: str, transcript_event: Event | None, minutes_event: Event | None, note: str, item_refs: frozenset[int], vote_row: dict | None = None)` where `kind` ∈ `omission, addition, mismatch, sequence, consent_block, vote_outcome`.
  - `MINUTED_TYPES: frozenset[str]` — event types the minutes are expected to record (omission/addition candidates are produced only for these).
  - `effective_consent_block(published: set[int], events: list[Event]) -> set[int]`.
  - `group_key(ev: Event, consent_block: set[int]) -> tuple`.
  - `details_differ(t: Event, m: Event) -> str | None` returning the mismatch category.
  - `pair_group(t_evs, m_evs) -> tuple[list[tuple[Event, Event]], list[Event], list[Event]]`.
  - `sequence_candidates(pairs) -> list[tuple[Event, Event]]` (pairs outside the longest increasing subsequence of minutes order).
  - `vote_outcome_candidates(t_events, votes: list[dict]) -> list[Candidate]` — `votes` rows have `id, result, yeas, nays, abstentions, raw_text, item_ids: list[int]`.
  - `align(t_events: list[Event], m_events: list[Event], *, consent_items: set[int], votes: list[dict]) -> list[Candidate]` — candidates numbered from 1 in a stable order (consent_block, mismatch, omission, addition, sequence, vote_outcome).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_aligner.py
from docket.ai.transcripts.aligner import (MINUTED_TYPES, Event, align, details_differ, effective_consent_block,
                                            pair_group, sequence_candidates)

_id = iter(range(1, 10_000))


def ev(source, seq, event_type, refs=(), *, actor=None, actor_text=None, detail=None, scope="item", start_s=None, page=None):
    return Event(next(_id), source, seq, event_type, scope, frozenset(refs), actor, actor_text, f"{event_type} {sorted(refs)}",
                 detail or {}, start_s, page, None)


CONSENT = {20, 21, 22}


def test_effective_consent_block_applies_pulls_and_adds():
    evs = [ev("transcript", 0, "consent_amendment", scope="consent_block", detail={"action": "pulled", "items": [21]}),
           ev("transcript", 1, "consent_amendment", scope="consent_block", detail={"action": "added", "items": [30]})]
    assert effective_consent_block(CONSENT, evs) == {20, 22, 30}


def test_consent_amendments_apply_in_sequence_order():
    # Pulled, then put back before the vote: the item is in the effective block again.
    evs = [ev("transcript", 0, "consent_amendment", scope="consent_block", detail={"action": "pulled", "items": [21]}),
           ev("transcript", 1, "consent_amendment", scope="consent_block", detail={"action": "added", "items": [21]})]
    assert effective_consent_block(CONSENT, evs) == CONSENT
    assert effective_consent_block(CONSENT, list(reversed(evs))) == {20, 22}   # order matters; callers pass seq order


def test_consent_vote_satisfies_the_block_and_pulled_item_gets_its_own_group():
    t = [ev("transcript", 0, "consent_amendment", scope="consent_block", detail={"action": "pulled", "items": [21]}),
         ev("transcript", 1, "motion", {20, 22}, scope="consent_block"), ev("transcript", 2, "vote", {20, 22}, scope="consent_block", detail={"result": "passed"}),
         ev("transcript", 3, "motion", {21}), ev("transcript", 4, "vote", {21}, detail={"result": "passed"})]
    m = [ev("minutes", 0, "consent_amendment", scope="consent_block", detail={"action": "pulled", "items": [21]}),
         ev("minutes", 1, "motion", {20, 22}, scope="consent_block"), ev("minutes", 2, "vote", {20, 22}, scope="consent_block", detail={"result": "passed"}),
         ev("minutes", 3, "motion", {21}), ev("minutes", 4, "vote", {21}, detail={"result": "passed"})]
    assert align(t, m, consent_items=CONSENT, votes=[]) == []           # Review Focus 5: pulled on both sides -> no candidate


def test_item_pulled_on_video_but_consented_in_minutes_is_a_candidate():
    t = [ev("transcript", 0, "consent_amendment", scope="consent_block", detail={"action": "pulled", "items": [21]}),
         ev("transcript", 1, "vote", {20, 22}, scope="consent_block", detail={"result": "passed"}),
         ev("transcript", 2, "vote", {21}, detail={"result": "passed"})]
    m = [ev("minutes", 0, "vote", {20, 21, 22}, scope="consent_block", detail={"result": "passed"})]
    cands = align(t, m, consent_items=CONSENT, votes=[])
    kinds = sorted(c.kind for c in cands)
    assert "consent_block" in kinds
    cb = next(c for c in cands if c.kind == "consent_block")
    assert cb.item_refs == frozenset({21}) and cb.category == "addition"
    # The consent vote itself must NOT also show up as an omission/addition pair mismatch.
    assert not any(c.kind in ("omission", "addition") and c.item_refs == frozenset({20, 22}) for c in cands)


def test_omission_and_addition_only_for_minuted_types():
    t = [ev("transcript", 0, "item_opened", {5}), ev("transcript", 1, "public_comment", scope="meeting"),
         ev("transcript", 2, "statement", {5}, detail={"kind": "legal_position", "as_stated": "x"}),
         ev("transcript", 3, "motion", {5}, detail={"action": "approve"})]
    m = [ev("minutes", 0, "motion", {5}, detail={"action": "approve"}), ev("minutes", 1, "recusal", {5}, detail={"member": "Tate"})]
    cands = align(t, m, consent_items=set(), votes=[])
    assert [(c.kind, c.transcript_event.event_type if c.transcript_event else None,
             c.minutes_event.event_type if c.minutes_event else None) for c in cands] == [
        ("omission", "statement", None), ("addition", None, "recusal")]
    assert "item_opened" not in MINUTED_TYPES and "public_comment" not in MINUTED_TYPES


def test_reopened_item_is_one_group_and_pairs_in_order():
    t = [ev("transcript", 0, "item_opened", {7}), ev("transcript", 1, "motion", {7}, detail={"action": "table"}),
         ev("transcript", 5, "item_opened", {7}), ev("transcript", 6, "motion", {7}, detail={"action": "approve"}),
         ev("transcript", 7, "vote", {7}, detail={"result": "passed"})]
    m = [ev("minutes", 0, "motion", {7}, detail={"action": "table"}), ev("minutes", 1, "motion", {7}, detail={"action": "approve"}),
         ev("minutes", 2, "vote", {7}, detail={"result": "passed"})]
    assert align(t, m, consent_items=set(), votes=[]) == []


def test_floor_added_item_groups_by_unlisted_text_not_meeting_bucket():
    t = [ev("transcript", 1, "motion", detail={"action": "approve", "unlisted_item": "Resolution honoring Coach Smith"}),
         ev("transcript", 2, "vote", detail={"result": "passed", "unlisted_item": "Resolution honoring Coach Smith"}),
         ev("transcript", 3, "adjourn", scope="meeting")]
    m = [ev("minutes", 1, "motion", detail={"action": "approve", "unlisted_item": "resolution honoring coach smith"}),
         ev("minutes", 2, "vote", detail={"result": "passed", "unlisted_item": "resolution honoring coach smith"}),
         ev("minutes", 3, "adjourn", scope="meeting")]
    assert align(t, m, consent_items=set(), votes=[]) == []
    # Without the unlisted text the motion would fall into the meeting bucket and pair with nothing.
    only_t = [ev("transcript", 1, "motion", detail={"action": "approve", "unlisted_item": "Resolution honoring Coach Smith"})]
    cands = align(only_t, [], consent_items=set(), votes=[])
    assert len(cands) == 1 and cands[0].kind == "omission" and cands[0].item_refs == frozenset()


def test_tabled_vs_postponed_is_a_wording_mismatch():
    t = ev("transcript", 1, "item_deferred", {7}, detail={"action": "table"})
    m = ev("minutes", 1, "item_deferred", {7}, detail={"action": "postpone", "to_date": "2026-03-03"})
    assert details_differ(t, m) == "wording"


def test_statute_cite_compares_canonically_and_differs_when_grounds_differ():
    same = (ev("transcript", 1, "executive_session_motion", {15}, detail={"statute_cite": "36, 25, a seven a four", "stated_reason": "security plans"}),
            ev("minutes", 1, "executive_session_motion", {15}, detail={"statute_cite": "36-25A-7(a)(4)", "stated_reason": "security plans and measures"}))
    assert details_differ(*same) is None
    diff = (same[0], ev("minutes", 1, "executive_session_motion", {15}, detail={"stated_reason": "pending litigation, controversies not yet litigated"}))
    assert details_differ(*diff) == "wording"


def test_actor_mismatch_by_member_id_is_speaker_and_unresolved_actors_do_not_match_phonetically():
    t = ev("transcript", 1, "motion", {7}, actor=101, detail={"action": "approve"})
    m = ev("minutes", 1, "motion", {7}, actor=102, detail={"action": "approve"})
    assert details_differ(t, m) == "speaker"
    m2 = ev("minutes", 1, "motion", {7}, actor=None, actor_text="Councilor Smythe", detail={"action": "approve"})
    assert details_differ(t, m2) is None


def test_vote_tally_mismatch_is_vote_outcome():
    t = ev("transcript", 1, "vote", {7}, detail={"result": "passed", "yeas": 8, "nays": 1})
    m = ev("minutes", 1, "vote", {7}, detail={"result": "passed", "yeas": 9, "nays": 0})
    assert details_differ(t, m) == "vote_outcome"
    assert details_differ(t, ev("minutes", 1, "vote", {7}, detail={"result": "passed"})) is None   # no tally recorded: not a mismatch


def test_sequence_detects_the_pilot_shape():
    t = [ev("transcript", 0, "motion", {15}), ev("transcript", 1, "executive_session_motion", {15}, detail={"stated_reason": "security"}),
         ev("transcript", 2, "recess", scope="meeting"), ev("transcript", 3, "reconvene", scope="meeting"),
         ev("transcript", 4, "vote", {15}, detail={"result": "passed"})]
    m = [ev("minutes", 0, "motion", {15}), ev("minutes", 1, "vote", {15}, detail={"result": "passed"}),
         ev("minutes", 2, "executive_session_motion", {15}, detail={"stated_reason": "security"}),
         ev("minutes", 3, "recess", scope="meeting"), ev("minutes", 4, "reconvene", scope="meeting")]
    cands = align(t, m, consent_items=set(), votes=[])
    seq = [c for c in cands if c.kind == "sequence"]
    assert len(seq) == 1
    assert {seq[0].transcript_event.event_type, seq[0].minutes_event.event_type} <= {"vote", "executive_session_motion"}


def test_sequence_candidates_use_longest_increasing_subsequence():
    pairs = [(ev("transcript", i, "motion", {i}), ev("minutes", j, "motion", {i})) for i, j in [(0, 0), (1, 2), (2, 1), (3, 3)]]
    out = sequence_candidates(pairs)
    assert len(out) == 1 and out[0][0].seq in (1, 2)


def test_vote_outcome_against_votes_rows():
    t = [ev("transcript", 4, "vote", {15}, detail={"result": "failed", "yeas": 3, "nays": 5})]
    votes = [{"id": 900, "result": "passed", "yeas": 8, "nays": 0, "abstentions": None, "raw_text": "...adopted", "item_ids": [15]},
             {"id": 901, "result": "passed", "yeas": 8, "nays": 0, "abstentions": None, "raw_text": "...", "item_ids": [16]}]
    cands = align(t, [], consent_items=set(), votes=votes)
    vo = [c for c in cands if c.kind == "vote_outcome"]
    assert len(vo) == 1 and vo[0].vote_row["id"] == 900 and vo[0].category == "vote_outcome"
    assert vo[0].minutes_event is None and vo[0].transcript_event.seq == 4


def test_candidate_ids_are_stable_and_start_at_one():
    t = [ev("transcript", 0, "motion", {1}, detail={"action": "approve"})]
    cands = align(t, [], consent_items=set(), votes=[])
    assert [c.candidate_id for c in cands] == [1]
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/unit/test_aligner.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Write `aligner.py`**

```python
# src/docket/ai/transcripts/aligner.py
"""Pair the two event timelines before any model judges (spec Section 4, "Alignment").

1. Group by agenda item references, not by time (a reopened item is one group).
2. Effective consent blocks per side: published consent minus pulled plus added.
3. Within a group, pair by type and order; leftovers are omission/addition
   candidates (only for event types the minutes normally record).
4. LCS over paired events across the meeting; out-of-order pairs are sequence candidates.
5. Actors compare as council_member_ids only. No phonetic matching.
6. Vote tallies compare against existing `votes` rows (minutes-derived baseline).
"""
from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass, field

from docket.ai.transcripts.guard import canonical_statute, normalize

MINUTED_TYPES = frozenset({"motion", "amendment", "vote", "executive_session_motion", "recusal", "procedural_ruling",
                           "item_deferred", "consent_amendment", "statement", "recess", "reconvene", "adjourn"})
_ACTOR_TYPES = {"motion", "amendment", "executive_session_motion", "recusal", "item_deferred"}


@dataclass(frozen=True)
class Event:
    id: int
    source: str
    seq: int
    event_type: str
    scope: str
    item_refs: frozenset[int]
    actor_member_id: int | None
    actor_text: str | None
    summary: str
    detail: dict
    start_s: float | None
    page: int | None
    char_offset: int | None


def event_from_row(row: dict) -> Event:
    return Event(row["id"], row["source"], row["seq"], row["event_type"], row["scope"],
                 frozenset(row.get("agenda_item_refs") or []), row.get("actor_member_id"), row.get("actor_text"),
                 row["summary"], dict(row.get("detail") or {}), row.get("start_s"), row.get("page"), row.get("char_offset"))


@dataclass
class Candidate:
    candidate_id: int
    kind: str
    category: str
    transcript_event: Event | None
    minutes_event: Event | None
    note: str
    item_refs: frozenset[int] = field(default_factory=frozenset)
    vote_row: dict | None = None


def effective_consent_block(published: set[int], events: list[Event]) -> set[int]:
    """Events must be in timeline order (load_events orders by seq); a pull then an add re-admits the item."""
    block = set(published)
    for ev in sorted(events, key=lambda e: e.seq):
        if ev.event_type != "consent_amendment":
            continue
        items = set(ev.detail.get("items") or []) or set(ev.item_refs)
        if ev.detail.get("action") == "pulled":
            block -= items
        elif ev.detail.get("action") == "added":
            block |= items
    return block


def group_key(ev: Event, consent_block: set[int]) -> tuple:
    if not ev.item_refs and ev.detail.get("unlisted_item"):
        return ("unlisted", normalize(ev.detail["unlisted_item"])[:60])   # floor-added item, no agenda row
    if ev.scope == "meeting" or not ev.item_refs:
        return ("meeting",)
    if ev.scope == "consent_block" or (len(ev.item_refs) > 1 and ev.item_refs <= consent_block):
        return ("consent",)
    return ("item", tuple(sorted(ev.item_refs)))


def _tokens(s: str | None) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", normalize(s or "")))


def _jaccard(a: str | None, b: str | None) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / len(ta | tb) if (ta or tb) else 1.0


def details_differ(t: Event, m: Event) -> str | None:
    td, md = t.detail, m.detail
    if t.event_type == "vote":
        if td.get("result") and md.get("result") and normalize(td["result"]) != normalize(md["result"]):
            return "vote_outcome"
        for k in ("yeas", "nays", "abstentions"):
            if td.get(k) is not None and md.get(k) is not None and td[k] != md[k]:
                return "vote_outcome"
        return None
    if t.event_type in _ACTOR_TYPES and t.actor_member_id and m.actor_member_id and t.actor_member_id != m.actor_member_id:
        return "speaker"
    if t.event_type == "executive_session_motion":
        tc, mc = td.get("statute_cite"), md.get("statute_cite")
        if tc and mc and canonical_statute(tc) != canonical_statute(mc):
            return "wording"
        if _jaccard(td.get("stated_reason"), md.get("stated_reason")) < 0.5:
            return "wording"
        return None
    if t.event_type in ("item_deferred", "motion", "consent_amendment", "procedural_ruling"):
        for k in ("action", "to_date", "kind"):
            if td.get(k) and md.get(k) and normalize(td[k]) != normalize(md[k]):
                return "wording"
    if t.event_type in ("amendment", "statement", "procedural_ruling", "motion"):
        key = "what_changed" if t.event_type == "amendment" else ("ruling" if t.event_type == "procedural_ruling" else "as_stated")
        if td.get(key) and md.get(key) and _jaccard(td[key], md[key]) < 0.4:
            return "wording"
    return None


def pair_group(t_evs: list[Event], m_evs: list[Event]):
    pairs, t_only, m_only = [], [], []
    types = {e.event_type for e in t_evs} | {e.event_type for e in m_evs}
    for et in sorted(types):
        ts = [e for e in t_evs if e.event_type == et]
        ms = [e for e in m_evs if e.event_type == et]
        for a, b in zip(ts, ms):
            pairs.append((a, b))
        t_only += ts[len(ms):]
        m_only += ms[len(ts):]
    return pairs, t_only, m_only


def sequence_candidates(pairs: list[tuple[Event, Event]]) -> list[tuple[Event, Event]]:
    """Pairs not on the longest increasing subsequence of minutes order (sorted by transcript order)."""
    ordered = sorted(pairs, key=lambda p: p[0].seq)
    seqs = [p[1].seq for p in ordered]
    tails, prev, idx_at = [], [-1] * len(seqs), []
    for i, v in enumerate(seqs):
        k = bisect_left(tails, v)
        if k == len(tails):
            tails.append(v); idx_at.append(i)
        else:
            tails[k] = v; idx_at[k] = i
        prev[i] = idx_at[k - 1] if k else -1
    keep, i = set(), idx_at[-1] if idx_at else -1
    while i != -1:
        keep.add(i); i = prev[i]
    return [p for i, p in enumerate(ordered) if i not in keep]


def vote_outcome_candidates(t_events: list[Event], votes: list[dict]) -> list[Candidate]:
    out = []
    for ev in t_events:
        if ev.event_type != "vote" or not ev.item_refs:
            continue
        for v in votes:
            if not (set(v.get("item_ids") or []) & ev.item_refs):
                continue
            td = ev.detail
            differs = (td.get("result") and v.get("result") and normalize(td["result"]) != normalize(v["result"])) or any(
                td.get(k) is not None and v.get(k) is not None and td[k] != v[k] for k in ("yeas", "nays", "abstentions"))
            if differs:
                out.append(Candidate(0, "vote_outcome", "vote_outcome", ev, None,
                                     f"transcript says {td.get('result')} {td.get('yeas')}-{td.get('nays')}; "
                                     f"minutes vote row {v['id']} says {v.get('result')} {v.get('yeas')}-{v.get('nays')}",
                                     ev.item_refs, vote_row=v))
    return out


def align(t_events: list[Event], m_events: list[Event], *, consent_items: set[int], votes: list[dict]) -> list[Candidate]:
    t_block = effective_consent_block(consent_items, t_events)
    m_block = effective_consent_block(consent_items, m_events)
    cands: list[Candidate] = []
    for item in sorted(m_block - t_block):   # in the minutes' consent block, handled separately on video
        ref = next((e for e in m_events if item in e.item_refs and e.event_type == "vote"), None) or \
              next((e for e in m_events if item in e.item_refs), None)
        tref = next((e for e in t_events if item in e.item_refs), None)
        cands.append(Candidate(0, "consent_block", "addition", tref, ref,
                               "pulled from consent on video; still inside the consent block in the minutes", frozenset({item})))
    for item in sorted(t_block - m_block):
        ref = next((e for e in t_events if item in e.item_refs), None)
        mref = next((e for e in m_events if item in e.item_refs), None)
        cands.append(Candidate(0, "consent_block", "omission", ref, mref,
                               "inside the consent block on video; handled separately in the minutes", frozenset({item})))
    settled = (m_block - t_block) | (t_block - m_block)

    groups: dict[tuple, tuple[list[Event], list[Event]]] = {}
    for ev in t_events:
        if ev.event_type == "consent_amendment" and (set(ev.detail.get("items") or []) | set(ev.item_refs)) & settled:
            continue
        groups.setdefault(group_key(ev, t_block), ([], []))[0].append(ev)
    for ev in m_events:
        if ev.event_type == "consent_amendment" and (set(ev.detail.get("items") or []) | set(ev.item_refs)) & settled:
            continue
        groups.setdefault(group_key(ev, m_block), ([], []))[1].append(ev)

    all_pairs, mism, omis, adds = [], [], [], []
    for key, (ts, ms) in groups.items():
        if key[0] == "item" and settled & set(key[1]):
            continue   # the pulled item's own group is covered by the consent_block candidate
        pairs, t_only, m_only = pair_group(ts, ms)
        all_pairs += pairs
        for a, b in pairs:
            cat = details_differ(a, b)
            if cat:
                mism.append(Candidate(0, "mismatch", cat, a, b, f"{a.event_type}: {cat} differs", a.item_refs | b.item_refs))
        omis += [Candidate(0, "omission", "omission", e, None, f"{e.event_type} on video, not in minutes", e.item_refs)
                 for e in t_only if e.event_type in MINUTED_TYPES]
        adds += [Candidate(0, "addition", "addition", None, e, f"{e.event_type} in minutes, not on video", e.item_refs)
                 for e in m_only if e.event_type in MINUTED_TYPES]
    seqs = [Candidate(0, "sequence", "sequence", a, b, "paired events occur in a different order", a.item_refs | b.item_refs)
            for a, b in sequence_candidates(all_pairs)]
    ordered = cands + mism + omis + adds + seqs + vote_outcome_candidates(t_events, votes)
    for i, c in enumerate(ordered, start=1):
        c.candidate_id = i
    return ordered
```

- [ ] **Step 4: Run to verify pass**

Run: `venv/bin/python -m pytest tests/unit/test_aligner.py -v`
Expected: 15 PASS. The pilot-shape test must yield exactly one sequence candidate; if two appear, the LIS tie-break picked the wrong pair; the sort key in `sequence_candidates` is transcript seq, and `bisect_left` keeps the earliest minutes seq on ties.

- [ ] **Step 5: Commit**

```bash
git add src/docket/ai/transcripts/aligner.py tests/unit/test_aligner.py
git -c user.email=hello@docket.pub commit -m "feat(ai): deterministic aligner: consent blocks, pairing, LCS sequence, vote check

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: Comparison stage — judge, hunter, deterministic vote check, candidate cap

**Files:**
- Create: `src/docket/ai/transcripts/compare.py`
- Test: `tests/unit/test_compare_render.py`, `tests/integration/test_compare_stage.py`

**Interfaces:**
- Consumes: `aligner.align`, `Event`, `Candidate`, `event_from_row` (Task 10); `guard.find_citation`, `window` (Task 5); `JUDGE_SYSTEM`, `HUNTER_SYSTEM`, `COMPARE_PROMPT_VERSION` (Task 2); `JUDGE_SCHEMA`, `HUNTER_SCHEMA`, `JudgeResult`, `HunterResult` (Task 2); `events.load_segments_with_speakers`, `render_transcript`, `render_minutes`, `load_agenda`, `extract_minutes_side` (Task 9); `minutes.load_minutes` (Task 8); `speakers.hms`; `StageOutcome`, `TranscriptHeld` (Task 4); `TRANSCRIPT_CANDIDATE_CAP`, `AI_TRANSCRIPT_COMPARE_MODEL`.
- Produces:
  - `load_events(meeting_id, source) -> list[Event]`; `load_votes(meeting_id) -> list[dict]` (`source = 'minutes_text'`, with `item_ids` from active `vote_agenda_items`); `load_consent_items(meeting_id) -> set[int]`.
  - `@dataclass TranscriptText(joined: str, bounds: list[tuple[int, int, dict]])`; `transcript_text(segments) -> TranscriptText`; `segment_at(tt, offset) -> dict | None`.
  - `transcript_window(segments, start_s, radius_s=45.0) -> str`; `minutes_window(minutes, char_offset, radius=600) -> str`.
  - `render_judge_user(candidates, t_events, m_events, segments, minutes) -> str`; `render_hunter_user(candidates, t_events, m_events, transcript_rendered, minutes_rendered) -> str`.
  - `cite(quote: str | None, *, side: str, tt: TranscriptText | None, minutes) -> tuple[str, str | None, float | None, int | None]` returning `(kind, excerpt, start_s, page)`.
  - `nearest_event(events: list[Event], *, start_s=None, char_offset=None, item_refs=frozenset()) -> Event | None`.
  - `build_rows(meeting_id, candidates, verdicts, hunted, *, tt, minutes, t_events, m_events) -> list[dict]` — one dict per `minutes_discrepancies` row (keys match the columns).
  - `insert_rows(meeting_id, rows) -> int` (Task 12 wraps this with reconciliation).
  - `run_compare_stage(claim, *, client) -> StageOutcome` (`compared`).
  - `citation_match_for(kinds: list[str]) -> str` (`missing` if any cited side missing, else `fuzzy` if any fuzzy, else `exact`).

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/unit/test_compare_render.py
from docket.ai.transcripts.aligner import Candidate, Event
from docket.ai.transcripts.compare import (TranscriptText, citation_match_for, nearest_event, render_judge_user, segment_at,
                                           transcript_text, transcript_window)

SEGS = [{"id": 1, "seq": 0, "start_s": 3290.0, "end_s": 3295.0, "text": "executed a contract vendor CGI access", "cluster_label": "S0",
         "speaker_name": None, "speaker_confidence": None, "is_silence": False, "agenda_item_id": 1},
        {"id": 2, "seq": 1, "start_s": 3295.0, "end_s": 3300.0, "text": "three years between the agency and Alabama power", "cluster_label": "S0",
         "speaker_name": "Clerk", "speaker_confidence": 0.9, "is_silence": False, "agenda_item_id": 1},
        {"id": 3, "seq": 2, "start_s": 3400.0, "end_s": 3405.0, "text": "we will go into executive session", "cluster_label": "S2",
         "speaker_name": None, "speaker_confidence": None, "is_silence": False, "agenda_item_id": 1}]


def test_transcript_text_maps_offsets_back_to_segments():
    tt = transcript_text(SEGS)
    off = tt.joined.index("Alabama power")
    assert segment_at(tt, off)["seq"] == 1
    assert segment_at(tt, tt.joined.index("executive"))["start_s"] == 3400.0


def test_transcript_window_is_time_bounded_and_labeled():
    w = transcript_window(SEGS, 3292.0, radius_s=10)
    assert "[seq=0 t=00:54:50 Speaker 1]" in w and "[seq=1 t=00:54:55 Clerk]" in w and "executive session" not in w


def _ev(id_, source, seq, et, refs=(1,), start_s=None, char_offset=None):
    return Event(id_, source, seq, et, "item", frozenset(refs), None, None, f"{et}", {}, start_s, None, char_offset)


def test_nearest_event_prefers_same_item_then_distance():
    evs = [_ev(1, "transcript", 0, "motion", (1,), start_s=100), _ev(2, "transcript", 1, "vote", (2,), start_s=3401),
           _ev(3, "transcript", 2, "statement", (1,), start_s=3300)]
    assert nearest_event(evs, start_s=3400, item_refs=frozenset({1})).id == 3
    assert nearest_event(evs, start_s=3400).id == 2
    assert nearest_event([], start_s=1) is None
    m = [_ev(7, "minutes", 0, "vote", char_offset=100), _ev(8, "minutes", 1, "recess", char_offset=900)]
    assert nearest_event(m, char_offset=850).id == 8


def test_citation_match_for_takes_the_worst_side():
    assert citation_match_for(["exact", "exact"]) == "exact"
    assert citation_match_for(["exact", "fuzzy"]) == "fuzzy"
    assert citation_match_for(["fuzzy", "missing"]) == "missing"
    assert citation_match_for([]) == "missing"


def test_judge_prompt_numbers_candidates_and_shows_both_windows():
    t = _ev(10, "transcript", 1, "executive_session_motion", start_s=3400.0)
    m = _ev(20, "minutes", 3, "executive_session_motion", char_offset=30)
    cand = Candidate(1, "mismatch", "wording", t, m, "statute differs", frozenset({1}))
    minutes = type("M", (), {"text": "Councilmember O'Quinn made a motion to go into Executive Session to discuss pending litigation",
                             "page_offsets": [0]})()
    user = render_judge_user([cand], [t], [m], SEGS, minutes)
    assert "### Candidate 1" in user and "wording" in user
    assert "Transcript window" in user and "we will go into executive session" in user
    assert "Minutes window (page 1)" in user and "pending litigation" in user
    assert "Transcript timeline" in user and "Minutes timeline" in user
```

- [ ] **Step 2: Write the failing integration tests**

```python
# tests/integration/test_compare_stage.py
"""Comparison stage on the pilot fixture with mocked judge/hunter answers."""
from unittest.mock import MagicMock

import pytest

from docket.ai.exceptions import TranscriptHeld
from docket.ai.pricing import Usage
from docket.ai.transcripts import compare as C
from docket.ai.transcripts.client import StructuredResult
from docket.config import DATABASE_URL
from docket.db import db_cursor
from tests.support.transcript_fixtures import install_bundle, pilot_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


@pytest.fixture
def pilot():
    i = install_bundle(pilot_bundle(), external_id="999015", status="events_extracted")
    yield i
    i.cleanup()


def _seed_events(inst):
    """Hand-written timelines reproducing the pilot: exec session before the vote on video, after it in the minutes."""
    item = inst.item_ids[1501]
    with db_cursor() as cur:
        cur.execute("SELECT id, seq, start_s, text FROM transcript_segments WHERE transcript_id=%s ORDER BY seq", [inst.transcript_id])
        segs = cur.fetchall()
        exec_seg = next(s for s in segs if "executive session" in s["text"].lower())
        vote_seg = next(s for s in segs if "passes" in s["text"].lower())
        cur.execute("SELECT text FROM minutes_texts WHERE meeting_id=%s", [inst.meeting_id])
        mtext = cur.fetchone()["text"]
        adopted_off = mtext.index("said ordinance adopted") if "said ordinance adopted" in mtext else mtext.lower().index("ordinance adopted")
        exec_off = mtext.index("go into Executive Session")
        rows = [("transcript", 0, "motion", [item], None, exec_seg["start_s"] - 60, None, None, None, {"action": "approve"}),
                ("transcript", 1, "executive_session_motion", [item], None, exec_seg["start_s"], None, None, exec_seg["id"],
                 {"stated_reason": "security plans and measures", "statute_cite": "36, 25, a seven a four", "quote": exec_seg["text"]}),
                ("transcript", 2, "vote", [item], None, vote_seg["start_s"], None, None, vote_seg["id"],
                 {"result": "passed", "method": "voice", "quote": vote_seg["text"]}),
                ("minutes", 0, "motion", [item], None, None, 1, adopted_off - 200, None, {"action": "approve"}),
                ("minutes", 1, "vote", [item], None, None, 1, adopted_off, None, {"result": "passed", "quote": "said ordinance adopted"}),
                ("minutes", 2, "executive_session_motion", [item], None, None, 1, exec_off, None,
                 {"stated_reason": "pending litigation, controversies not yet litigated", "mover": "O'Quinn", "seconder": "Tate",
                  "quote": "go into Executive Session at the recommendation of the City Attorney"})]
        import json
        for src, seq, et, refs, actor, start_s, page, off, seg_id, detail in rows:
            cur.execute("""INSERT INTO meeting_events (meeting_id, source, seq, event_type, scope, agenda_item_refs, actor_member_id,
                                                       summary, detail, start_s, page, char_offset, segment_id, prompt_version)
                           VALUES (%s, %s, %s, %s, 'item', %s, %s, %s, %s::jsonb, %s, %s, %s, %s, 200)""",
                        [inst.meeting_id, src, seq, et, refs, actor, f"{et}", json.dumps(detail), start_s, page, off, seg_id])
    return {"item": item, "exec_text": exec_seg["text"], "vote_text": vote_seg["text"]}


def _client(verdicts_fn, hunted=None, tokens=90_000):
    c = MagicMock()
    c.count_tokens.return_value = tokens

    def call(**kw):
        if kw["schema"] is C.JUDGE_SCHEMA:
            cands = kw["user"]
            return StructuredResult({"verdicts": verdicts_fn(cands)}, Usage(1000, 0, 0, 200), "claude-opus-5-5", "end_turn")
        return StructuredResult({"discrepancies": hunted or []}, Usage(1000, 0, 0, 100), "claude-opus-5-5", "end_turn")
    c.call.side_effect = call
    return c


def _claim(inst, reason=None):
    return {"id": inst.transcript_id, "meeting_id": inst.meeting_id, "status": "events_extracted", "version": 1,
            "word_count": 650, "compare_skipped_reason": reason}


def _ids_in_prompt(user):
    import re
    return [int(x) for x in re.findall(r"### Candidate (\d+)", user)]


def test_pilot_candidates_become_proposed_rows_with_verified_citations(pilot):
    info = _seed_events(pilot)

    def verdicts(user):
        out = []
        for cid in _ids_in_prompt(user):
            block = user.split(f"### Candidate {cid}")[1].split("### Candidate")[0]
            if "sequence" in block.split("\n")[0]:
                out.append({"candidate_id": cid, "is_real": True, "category": "sequence", "severity": "material",
                            "title": "Executive session before the vote on video, after it in the minutes",
                            "description": "The video shows the executive session motion before the vote. The minutes record it after adoption.",
                            "transcript_quote": info["exec_text"], "minutes_quote": "said ordinance adopted", "confidence": 0.9,
                            "dismiss_reason": None})
            elif "wording" in block.split("\n")[0]:
                out.append({"candidate_id": cid, "is_real": True, "category": "wording", "severity": "material",
                            "title": "Different statutory ground for the executive session",
                            "description": "On video the attorney cites security plans. The minutes cite pending litigation.",
                            "transcript_quote": info["exec_text"], "minutes_quote": "go into Executive Session at the recommendation of the City Attorney",
                            "confidence": 0.85, "dismiss_reason": None})
            else:
                out.append({"candidate_id": cid, "is_real": False, "category": None, "severity": None, "title": None, "description": None,
                            "transcript_quote": None, "minutes_quote": None, "confidence": 0.7, "dismiss_reason": "same action, different words"})
        return out

    out = C.run_compare_stage(_claim(pilot), client=_client(verdicts))
    assert out.next_status == "compared"
    with db_cursor() as cur:
        cur.execute("""SELECT category, severity, review_state, citation_match, confidence, origin, agenda_item_id,
                              transcript_event_id, minutes_event_id, transcript_start_s, minutes_page, prompt_version
                         FROM minutes_discrepancies WHERE meeting_id=%s ORDER BY category""", [pilot.meeting_id])
        rows = [dict(r) for r in cur.fetchall()]
    proposed = [r for r in rows if r["review_state"] == "proposed"]
    assert sorted(r["category"] for r in proposed) == ["sequence", "wording"]
    assert all(r["severity"] == "material" and r["citation_match"] in ("exact", "fuzzy") for r in proposed)
    assert all(r["agenda_item_id"] == info["item"] and r["prompt_version"] == 200 and r["origin"] == "aligner" for r in proposed)
    assert all(r["transcript_event_id"] and r["minutes_event_id"] for r in proposed)
    assert all(r["transcript_start_s"] and r["minutes_page"] >= 1 for r in proposed)   # page from page_offsets, not the seeded 1
    with db_cursor() as cur:
        cur.execute("SELECT status, compare_skipped_reason FROM transcripts WHERE id=%s", [pilot.transcript_id])
        assert tuple(cur.fetchone().values()) == ("compared", None)


def test_unfound_quote_is_kept_as_missing_with_halved_confidence(pilot):
    _seed_events(pilot)

    def verdicts(user):
        return [{"candidate_id": cid, "is_real": True, "category": "wording", "severity": "minor", "title": "t", "description": "d",
                 "transcript_quote": "words nobody said at this meeting", "minutes_quote": "words not in the minutes either",
                 "confidence": 0.8, "dismiss_reason": None} for cid in _ids_in_prompt(user)]

    C.run_compare_stage(_claim(pilot), client=_client(verdicts))
    with db_cursor() as cur:
        cur.execute("SELECT citation_match, confidence, review_state FROM minutes_discrepancies WHERE meeting_id=%s", [pilot.meeting_id])
        rows = cur.fetchall()
    assert rows and all(r["citation_match"] == "missing" and r["review_state"] == "proposed" for r in rows)
    assert all(abs(r["confidence"] - 0.4) < 1e-6 for r in rows)          # Review Focus 2


def test_dismissed_candidates_are_stored_with_reason(pilot):
    _seed_events(pilot)
    verdicts = lambda user: [{"candidate_id": cid, "is_real": False, "category": None, "severity": None, "title": None, "description": None,
                              "transcript_quote": None, "minutes_quote": None, "confidence": 0.6, "dismiss_reason": "aligner pairing mistake"}
                             for cid in _ids_in_prompt(user)]
    C.run_compare_stage(_claim(pilot), client=_client(verdicts))
    with db_cursor() as cur:
        cur.execute("SELECT review_state, reject_reason FROM minutes_discrepancies WHERE meeting_id=%s", [pilot.meeting_id])
        rows = cur.fetchall()
    assert rows and all(r["review_state"] == "dismissed_by_model" and r["reject_reason"] == "aligner pairing mistake" for r in rows)


def test_hunter_rows_are_model_initiated_and_linked_to_nearest_event(pilot):
    info = _seed_events(pilot)
    hunted = [{"category": "omission", "severity": "material", "title": "Attorney's LPR explanation not minuted",
               "description": "The attorney explained what the agreement gives Alabama Power access to; the minutes do not record it.",
               "agenda_item_refs": [info["item"]], "transcript_quote": info["exec_text"], "transcript_segment_seq": None,
               "minutes_quote": None, "minutes_page": None, "confidence": 0.7}]
    verdicts = lambda user: [{"candidate_id": cid, "is_real": False, "category": None, "severity": None, "title": None, "description": None,
                              "transcript_quote": None, "minutes_quote": None, "confidence": 0.5, "dismiss_reason": "x"} for cid in _ids_in_prompt(user)]
    C.run_compare_stage(_claim(pilot), client=_client(verdicts, hunted))
    with db_cursor() as cur:
        cur.execute("""SELECT origin, category, transcript_event_id, minutes_event_id, citation_match, transcript_start_s
                         FROM minutes_discrepancies WHERE meeting_id=%s AND origin='model_initiated'""", [pilot.meeting_id])
        (row,) = cur.fetchall()
    assert row["category"] == "omission" and row["transcript_event_id"] is not None and row["minutes_event_id"] is None
    assert row["citation_match"] == "exact" and row["transcript_start_s"] is not None


def test_candidate_cap_holds_the_transcript(pilot, monkeypatch):
    _seed_events(pilot)
    monkeypatch.setattr(C, "TRANSCRIPT_CANDIDATE_CAP", 1)
    c = _client(lambda user: [])
    with pytest.raises(TranscriptHeld) as ei:
        C.run_compare_stage(_claim(pilot), client=c)
    assert ei.value.reason == "candidate_cap"
    c.call.assert_not_called()


def test_vote_outcome_rows_are_deterministic_and_skip_the_judge(pilot):
    info = _seed_events(pilot)
    with db_cursor() as cur:
        cur.execute("""INSERT INTO votes (meeting_id, result, yeas, nays, source, raw_text) VALUES (%s, 'failed', 3, 5, 'minutes_text',
                       'upon the roll being called the vote was as follows ... the motion failed') RETURNING id""", [pilot.meeting_id])
        vid = cur.fetchone()["id"]
        cur.execute("""INSERT INTO vote_agenda_items (vote_id, agenda_item_id, association_type, match_confidence)
                       VALUES (%s, %s, 'explicit', 1.0)""", [vid, info["item"]])
    seen = {}
    def verdicts(user):
        seen["user"] = user
        return [{"candidate_id": cid, "is_real": False, "category": None, "severity": None, "title": None, "description": None,
                 "transcript_quote": None, "minutes_quote": None, "confidence": 0.5, "dismiss_reason": "x"} for cid in _ids_in_prompt(user)]
    C.run_compare_stage(_claim(pilot), client=_client(verdicts))
    assert "vote_outcome" not in seen["user"].split("Transcript timeline")[0]     # not sent to the judge
    with db_cursor() as cur:
        cur.execute("""SELECT title, severity, review_state, minutes_excerpt, transcript_event_id, minutes_event_id
                         FROM minutes_discrepancies WHERE meeting_id=%s AND category='vote_outcome'""", [pilot.meeting_id])
        (row,) = cur.fetchall()
    assert row["severity"] == "material" and row["review_state"] == "proposed"
    assert "motion failed" in row["minutes_excerpt"] and row["transcript_event_id"] and row["minutes_event_id"] is None
```

- [ ] **Step 3: Run to verify failure**

Run: `venv/bin/python -m pytest tests/unit/test_compare_render.py tests/integration/test_compare_stage.py -v`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 4: Write `compare.py`**

```python
# src/docket/ai/transcripts/compare.py
"""Comparison: aligner candidates -> Opus 5.5 judge; full texts -> Opus 5.5 hunter; rows into minutes_discrepancies.

Vote outcomes are deterministic (spec decision J) and never go to the judge.
Every quoted excerpt is verified by the guard against the same text the
model saw; a quote the guard cannot find keeps the row with
citation_match = 'missing' and half the confidence, so the queue shows it
and a reviewer must attach a citation before it can be approved.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import ValidationError

from docket.ai.exceptions import TranscriptHeld
from docket.ai.transcripts.aligner import Candidate, Event, align, event_from_row
from docket.ai.transcripts.events import (extract_minutes_side, load_agenda, load_segments_with_speakers, render_minutes,
                                           render_transcript)
from docket.ai.transcripts.guard import find_citation, window
from docket.ai.transcripts.minutes import MinutesCapture, load_minutes, page_for_offset
from docket.ai.transcripts.prompts import COMPARE_PROMPT_VERSION, HUNTER_SYSTEM, JUDGE_SYSTEM
from docket.ai.transcripts.schemas import HUNTER_SCHEMA, JUDGE_SCHEMA, HunterResult, JudgeResult
from docket.ai.transcripts.speakers import hms
from docket.config import AI_TRANSCRIPT_COMPARE_MODEL, TRANSCRIPT_CANDIDATE_CAP, TRANSCRIPT_TOKEN_CEILING
from docket.db import db_cursor
from docket.services.transcripts import SPEAKER_CONFIDENCE_FLOOR, speaker_ordinals

log = logging.getLogger(__name__)

# --- loaders ----------------------------------------------------------------

def load_events(meeting_id: int, source: str) -> list[Event]:
    with db_cursor() as cur:
        cur.execute("""SELECT id, source, seq, event_type, scope, agenda_item_refs, actor_member_id, actor_text, summary, detail,
                              start_s, page, char_offset FROM meeting_events
                        WHERE meeting_id = %s AND source = %s ORDER BY seq""", [meeting_id, source])
        return [event_from_row(dict(r)) for r in cur.fetchall()]


def load_votes(meeting_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute("""SELECT v.id, v.result, v.yeas, v.nays, v.abstentions, v.raw_text,
                              COALESCE(array_agg(vai.agenda_item_id) FILTER (WHERE vai.id IS NOT NULL), '{}') AS item_ids
                         FROM votes v LEFT JOIN vote_agenda_items vai ON vai.vote_id = v.id AND vai.is_active
                        WHERE v.meeting_id = %s AND v.source = 'minutes_text'
                        GROUP BY v.id ORDER BY v.id""", [meeting_id])
        return [dict(r) for r in cur.fetchall()]


def load_consent_items(meeting_id: int) -> set[int]:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM agenda_items WHERE meeting_id = %s AND is_consent", [meeting_id])
        return {r["id"] for r in cur.fetchall()}


# --- text helpers -----------------------------------------------------------

@dataclass
class TranscriptText:
    joined: str
    bounds: list[tuple[int, int, dict]]


def transcript_text(segments: list[dict]) -> TranscriptText:
    parts, bounds, pos = [], [], 0
    for s in segments:
        if s.get("is_silence") or not (s.get("text") or "").strip():
            continue
        t = s["text"].strip()
        bounds.append((pos, pos + len(t), s))
        parts.append(t)
        pos += len(t) + 1
    return TranscriptText(" ".join(parts), bounds)


def segment_at(tt: TranscriptText, offset: int) -> dict | None:
    for lo, hi, seg in tt.bounds:
        if lo <= offset <= hi:
            return seg
    return None


def _label(seg: dict, ordinals: dict[str, int]) -> str:
    name, conf = seg.get("speaker_name"), seg.get("speaker_confidence")
    if name and (conf is None or conf >= SPEAKER_CONFIDENCE_FLOOR):
        return name
    return f"Speaker {ordinals.get(seg.get('cluster_label'), 0)}" if seg.get("cluster_label") else "Unknown speaker"


def transcript_window(segments: list[dict], start_s: float, radius_s: float = 45.0, ordinals: dict | None = None) -> str:
    ords = ordinals if ordinals is not None else {}
    if not ords:
        seen: dict[str, int] = {}
        for s in segments:
            cl = s.get("cluster_label")
            if cl and cl not in seen and not s.get("is_silence"):
                seen[cl] = len(seen) + 1
        ords = seen
    lines = [f"[seq={s['seq']} t={hms(s['start_s'])} {_label(s, ords)}] {s['text'].strip()}" for s in segments
             if not s.get("is_silence") and (s.get("text") or "").strip() and abs(s["start_s"] - start_s) <= radius_s]
    return "\n".join(lines)


def minutes_window(minutes: MinutesCapture, char_offset: int, radius: int = 600) -> str:
    return window(minutes.text, char_offset, char_offset, radius)


def render_timeline(events: list[Event]) -> str:
    return "\n".join(f"#{e.id} seq={e.seq} {e.event_type} items={sorted(e.item_refs)} "
                     f"{'t=' + hms(e.start_s) if e.start_s is not None else ('page ' + str(e.page) if e.page else '')}: {e.summary}"
                     for e in events)


def _event_line(e: Event | None, side: str) -> str:
    if e is None:
        return f"{side} event: none"
    where = f"seq {e.seq}, t={hms(e.start_s)}" if e.start_s is not None else f"page {e.page}"
    return f"{side} event #{e.id} ({where}): {e.event_type} — {e.summary}; detail {e.detail}"


def render_judge_user(candidates: list[Candidate], t_events, m_events, segments, minutes) -> str:
    out = ["Candidates:"]
    for c in candidates:
        out.append(f"\n### Candidate {c.candidate_id} — {c.kind} ({c.category}) items {sorted(c.item_refs)}")
        out.append(c.note)
        out.append(_event_line(c.transcript_event, "Transcript"))
        out.append(_event_line(c.minutes_event, "Minutes"))
        if c.transcript_event and c.transcript_event.start_s is not None:
            out.append("Transcript window:\n" + transcript_window(segments, c.transcript_event.start_s))
        if c.minutes_event and minutes is not None and c.minutes_event.char_offset is not None:
            page = page_for_offset(minutes.page_offsets, c.minutes_event.char_offset)
            out.append(f"Minutes window (page {page}):\n" + minutes_window(minutes, c.minutes_event.char_offset))
    out += ["\nTranscript timeline:", render_timeline(t_events), "\nMinutes timeline:", render_timeline(m_events)]
    return "\n".join(out)


def render_hunter_user(candidates, t_events, m_events, transcript_rendered: str, minutes_rendered: str) -> str:
    known = "\n".join(f"- {c.kind} ({c.category}) items {sorted(c.item_refs)}: {c.note}" for c in candidates) or "- none"
    return (f"Candidates the aligner already found (do not repeat):\n{known}\n\nTranscript timeline:\n{render_timeline(t_events)}\n\n"
            f"Minutes timeline:\n{render_timeline(m_events)}\n\nFull transcript:\n{transcript_rendered}\n\nFull minutes:\n{minutes_rendered}")


# --- citations ---------------------------------------------------------------

def cite(quote: str | None, *, side: str, tt: TranscriptText | None, minutes: MinutesCapture | None):
    """-> (kind, excerpt, start_s, page). kind is 'missing' when there is no quote or no match."""
    if not quote or not quote.strip():
        return "missing", None, None, None
    if side == "transcript":
        if tt is None:
            return "missing", quote, None, None
        cm = find_citation(quote, tt.joined)
        if cm.kind == "missing":
            return "missing", quote, None, None
        seg = segment_at(tt, cm.start)
        return cm.kind, tt.joined[cm.start:cm.end], (seg["start_s"] if seg else None), None
    if minutes is None:
        return "missing", quote, None, None
    cm = find_citation(quote, minutes.text)
    if cm.kind == "missing":
        return "missing", quote, None, None
    return cm.kind, minutes.text[cm.start:cm.end], None, page_for_offset(minutes.page_offsets, cm.start)


def citation_match_for(kinds: list[str]) -> str:
    if not kinds or "missing" in kinds:
        return "missing"
    return "fuzzy" if "fuzzy" in kinds else "exact"


def nearest_event(events: list[Event], *, start_s: float | None = None, char_offset: int | None = None,
                  item_refs: frozenset = frozenset()) -> Event | None:
    def dist(e: Event) -> float:
        if start_s is not None and e.start_s is not None:
            return abs(e.start_s - start_s)
        if char_offset is not None and e.char_offset is not None:
            return abs(e.char_offset - char_offset)
        return float("inf")
    pool = [e for e in events if item_refs and e.item_refs & item_refs] or events
    pool = [e for e in pool if dist(e) != float("inf")]
    return min(pool, key=dist) if pool else None


# --- row assembly -----------------------------------------------------------

def build_rows(meeting_id: int, candidates: list[Candidate], verdicts, hunted, *, tt: TranscriptText,
               minutes: MinutesCapture | None, t_events: list[Event], m_events: list[Event]) -> list[dict]:
    by_id = {c.candidate_id: c for c in candidates}
    rows: list[dict] = []

    def base(cat, sev, title, desc, t_ev, m_ev, refs, origin):
        return {"meeting_id": meeting_id, "agenda_item_id": min(refs) if refs else None, "category": cat, "severity": sev,
                "title": title, "description": desc, "transcript_event_id": t_ev.id if t_ev else None,
                "minutes_event_id": m_ev.id if m_ev else None, "origin": origin, "prompt_version": COMPARE_PROMPT_VERSION,
                "transcript_excerpt": None, "transcript_start_s": t_ev.start_s if t_ev else None, "minutes_excerpt": None,
                "minutes_page": m_ev.page if m_ev else None, "citation_match": "missing", "confidence": None,
                "review_state": "proposed", "reject_reason": None}

    # Deterministic vote outcomes (spec J): no model involved.
    for c in candidates:
        if c.kind != "vote_outcome":
            continue
        v = c.vote_row or {}
        row = base("vote_outcome", "material", f"Vote tally differs from the minutes for item {sorted(c.item_refs)}",
                   c.note, c.transcript_event, None, c.item_refs, "aligner")
        kind, exc, start_s, _ = cite(c.transcript_event.detail.get("quote"), side="transcript", tt=tt, minutes=None)
        row.update(transcript_excerpt=exc, transcript_start_s=start_s or row["transcript_start_s"],
                   minutes_excerpt=(v.get("raw_text") or "")[-300:] or None, minutes_page=None,
                   citation_match=citation_match_for([kind, "exact" if v.get("raw_text") else "missing"]), confidence=0.9)
        rows.append(row)

    for v in verdicts:
        c = by_id.get(v.candidate_id)
        if c is None:
            continue
        if not v.is_real:
            row = base(c.category, "minor", c.note[:200], v.dismiss_reason or "dismissed by model", c.transcript_event,
                       c.minutes_event, c.item_refs, "aligner")
            row.update(review_state="dismissed_by_model", reject_reason=v.dismiss_reason, confidence=v.confidence)
            rows.append(row)
            continue
        row = base(v.category or c.category, v.severity or "minor", v.title or c.note[:200], v.description or c.note,
                   c.transcript_event, c.minutes_event, c.item_refs, "aligner")
        kinds = []
        if c.transcript_event is not None:
            k, exc, start_s, _ = cite(v.transcript_quote, side="transcript", tt=tt, minutes=None)
            kinds.append(k); row.update(transcript_excerpt=exc, transcript_start_s=start_s or row["transcript_start_s"])
        if c.minutes_event is not None:
            k, exc, _, page = cite(v.minutes_quote, side="minutes", tt=None, minutes=minutes)
            kinds.append(k); row.update(minutes_excerpt=exc, minutes_page=page or row["minutes_page"])
        match = citation_match_for(kinds)
        row.update(citation_match=match, confidence=round(v.confidence * (0.5 if match == "missing" else 1.0), 3))
        rows.append(row)

    for h in hunted:
        refs = frozenset(h.agenda_item_refs)
        kt, t_exc, start_s, _ = cite(h.transcript_quote, side="transcript", tt=tt, minutes=None)
        km, m_exc, _, page = cite(h.minutes_quote, side="minutes", tt=None, minutes=minutes)
        t_ev = nearest_event(t_events, start_s=start_s, item_refs=refs) if h.transcript_quote else None
        m_ev = None
        if h.minutes_quote and minutes is not None:
            cm = find_citation(h.minutes_quote, minutes.text)
            m_ev = nearest_event(m_events, char_offset=cm.start if cm.kind != "missing" else None, item_refs=refs)
        if t_ev is None and m_ev is None:
            log.warning("hunter row dropped: no event to anchor it (%s)", h.title)
            continue
        row = base(h.category, h.severity, h.title, h.description, t_ev, m_ev, refs, "model_initiated")
        kinds = [k for k, q in ((kt, h.transcript_quote), (km, h.minutes_quote)) if q]
        match = citation_match_for(kinds)
        row.update(transcript_excerpt=t_exc, transcript_start_s=start_s or row["transcript_start_s"], minutes_excerpt=m_exc,
                   minutes_page=page or row["minutes_page"], citation_match=match,
                   confidence=round(h.confidence * (0.5 if match == "missing" else 1.0), 3))
        rows.append(row)
    return rows


_COLS = ("meeting_id", "agenda_item_id", "category", "severity", "title", "description", "transcript_event_id", "minutes_event_id",
         "transcript_excerpt", "transcript_start_s", "minutes_excerpt", "minutes_page", "citation_match", "confidence", "origin",
         "review_state", "reject_reason", "prompt_version")


def insert_rows(meeting_id: int, rows: list[dict]) -> int:
    with db_cursor() as cur:
        for r in rows:
            cur.execute(f"INSERT INTO minutes_discrepancies ({', '.join(_COLS)}) VALUES ({', '.join(['%s'] * len(_COLS))})",
                        [r[c] for c in _COLS])
    return len(rows)


def write_rows(meeting_id: int, rows: list[dict]) -> int:
    """Task 12 replaces this with reconcile(); until then a plain insert."""
    return insert_rows(meeting_id, rows)


# --- stage ------------------------------------------------------------------

def _call(client, *, system: str, user: str, schema: dict, model_cls, max_tokens: int):
    tokens = client.count_tokens(model=AI_TRANSCRIPT_COMPARE_MODEL, system=system, user=user)
    if tokens > TRANSCRIPT_TOKEN_CEILING:
        raise TranscriptHeld("token_ceiling", f"{tokens} tokens > ceiling {TRANSCRIPT_TOKEN_CEILING}")
    res = client.call(model=AI_TRANSCRIPT_COMPARE_MODEL, system=system, user=user, schema=schema, max_tokens=max_tokens, effort="high")
    try:
        return model_cls.model_validate(res.data)
    except ValidationError as e:
        raise TranscriptHeld("schema_invalid", f"{model_cls.__name__} failed validation: {e}") from e


def run_compare_stage(claim: dict, *, client) -> "StageOutcome":
    from docket.ai.transcripts.pipeline import StageOutcome

    tid, mid = claim["id"], claim["meeting_id"]
    m_events = load_events(mid, "minutes")
    if not m_events or claim.get("compare_skipped_reason") == "minutes_changed":
        status = extract_minutes_side(mid, client=client)
        if status != "ok":
            return StageOutcome("events_extracted", skipped_reason=status, detail="minutes side unavailable at compare time")
        m_events = load_events(mid, "minutes")
    t_events = load_events(mid, "transcript")
    minutes = load_minutes(mid)
    segments = load_segments_with_speakers(tid)
    tt = transcript_text(segments)
    candidates = align(t_events, m_events, consent_items=load_consent_items(mid), votes=load_votes(mid))
    judged = [c for c in candidates if c.kind != "vote_outcome"]
    if len(judged) > TRANSCRIPT_CANDIDATE_CAP:
        raise TranscriptHeld("candidate_cap", f"{len(judged)} candidates > cap {TRANSCRIPT_CANDIDATE_CAP}")
    verdicts = []
    if judged:
        judge = _call(client, system=JUDGE_SYSTEM, user=render_judge_user(judged, t_events, m_events, segments, minutes),
                      schema=JUDGE_SCHEMA, model_cls=JudgeResult, max_tokens=32000)
        verdicts = judge.verdicts
    agenda = load_agenda(mid)
    hunter = _call(client, system=HUNTER_SYSTEM,
                   user=render_hunter_user(candidates, t_events, m_events, render_transcript(segments, agenda, speaker_ordinals(tid)),
                                           render_minutes(minutes.text, minutes.page_offsets) if minutes else ""),
                   schema=HUNTER_SCHEMA, model_cls=HunterResult, max_tokens=16000)
    rows = build_rows(mid, candidates, verdicts, hunter.discrepancies, tt=tt, minutes=minutes, t_events=t_events, m_events=m_events)
    n = write_rows(mid, rows)
    proposed = sum(1 for r in rows if r["review_state"] == "proposed")
    log.info("compare: meeting %s candidates=%d judged=%d rows=%d proposed=%d hunted=%d", mid, len(candidates), len(judged), n,
             proposed, len(hunter.discrepancies))
    return StageOutcome("compared", detail=f"{proposed} proposed of {n} rows")
```

- [ ] **Step 5: Run to verify pass**

Run: `venv/bin/python -m pytest tests/unit/test_compare_render.py tests/integration/test_compare_stage.py -v`
Expected: 11 PASS. In `test_pilot_candidates_become_proposed_rows_with_verified_citations`, the aligner must produce exactly one `sequence` and one `wording` candidate from the seeded timelines (the `motion` pair matches; the exec-session pair differs on `stated_reason`; the LIS drops one pair). If the test sees a `speaker` candidate too, the seeded minutes event's `mover` is being compared as text; `details_differ` compares actors by member id only.

- [ ] **Step 6: Commit**

```bash
git add src/docket/ai/transcripts/compare.py tests/unit/test_compare_render.py tests/integration/test_compare_stage.py
git -c user.email=hello@docket.pub commit -m "feat(ai): comparison stage: judge, hunter, deterministic vote check, candidate cap

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: Re-comparison — minutes change sweep, stale reconciliation, operator script

**Files:**
- Modify: `src/docket/ai/transcripts/compare.py` (`reconcile`, `write_rows`), `src/docket/ai/transcripts/pipeline.py` (`sweep_minutes_changes`, `claim_meeting`, `run_for_meeting`)
- Create: `scripts/transcript_recompare.py`
- Test: `tests/unit/test_reconcile_match.py`, `tests/integration/test_recompare.py`

**Interfaces:**
- Produces:
  - `compare.match_stale(new_row: dict, stale_rows: list[dict]) -> dict | None` — by `category` + `transcript_event_id`; additions (no transcript event) by `category` + `agenda_item_id` + normalized `minutes_excerpt` similarity ≥ `ADDITION_MATCH_RATIO = 0.8`.
  - `compare.reconcile(meeting_id, rows) -> dict(inserted: int, updated: int, stale: int)`; `write_rows` now calls it.
  - `pipeline.sweep_minutes_changes(limit: int = 10) -> int` — `compared` transcripts whose `minutes_texts.extracted_at` is older than 7 days, oldest first; `recheck_minutes`; on change set `status = 'events_extracted'`, `compare_skipped_reason = 'minutes_changed'`, `stage_attempts = 0`.
  - `pipeline.claim_meeting(meeting_id) -> dict | None` (same UPDATE as `CLAIM_SQL` with `t.meeting_id = %s` and no backoff clause); `pipeline.run_for_meeting(meeting_id, *, notes="cli_transcripts", client=None, until="compared") -> list[str]` (processes stages in order until the status is reached or a non-advance outcome).
  - `scripts/transcript_recompare.py --meeting-id N [--now]` — forces `minutes_changed` and optionally runs the stages immediately.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_reconcile_match.py
from docket.ai.transcripts.compare import match_stale


def _row(cat, tev, item=5, mexc="Councilmember Tate made a motion to table item five"):
    return {"category": cat, "transcript_event_id": tev, "agenda_item_id": item, "minutes_excerpt": mexc}


def test_match_by_category_and_transcript_event():
    stale = [_row("wording", 10), _row("sequence", 10), _row("wording", 11)]
    assert match_stale(_row("wording", 10), stale) is stale[0]
    assert match_stale(_row("omission", 10), stale) is None


def test_additions_match_by_item_and_similar_minutes_excerpt():
    stale = [_row("addition", None, 5, "Councilmember Tate made a motion to table item five"),
             _row("addition", None, 6, "Councilmember Tate made a motion to table item five")]
    new = _row("addition", None, 5, "Councilmember Tate made  a motion to table item 5")
    assert match_stale(new, stale) is stale[0]
    assert match_stale(_row("addition", None, 5, "completely different text about a recess"), stale) is None
```

```python
# tests/integration/test_recompare.py
"""Minutes change -> stale -> re-proposed in place; unmatched approvals stay stale; public reads exclude stale."""
from unittest.mock import MagicMock

import pytest

from docket.ai.pricing import Usage
from docket.ai.transcripts import compare as C
from docket.ai.transcripts import minutes as M
from docket.ai.transcripts import pipeline as P
from docket.ai.transcripts.client import StructuredResult
from docket.config import DATABASE_URL
from docket.db import db_cursor
from tests.integration.test_compare_stage import _claim, _client, _ids_in_prompt, _seed_events
from tests.support.transcript_fixtures import install_bundle, pilot_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


@pytest.fixture
def pilot():
    i = install_bundle(pilot_bundle(), external_id="999015", status="events_extracted")
    yield i
    i.cleanup()


def _real_all(info):
    def verdicts(user):
        out = []
        for cid in _ids_in_prompt(user):
            head = user.split(f"### Candidate {cid}")[1].split("\n")[0]
            cat = "sequence" if "sequence" in head else ("wording" if "wording" in head else "omission")
            out.append({"candidate_id": cid, "is_real": True, "category": cat, "severity": "material", "title": f"{cat} title",
                        "description": "desc", "transcript_quote": info["exec_text"], "minutes_quote": "go into Executive Session",
                        "confidence": 0.9, "dismiss_reason": None})
        return out
    return verdicts


def _states(mid):
    with db_cursor() as cur:
        cur.execute("SELECT id, category, review_state, previous_review_state FROM minutes_discrepancies WHERE meeting_id=%s ORDER BY id", [mid])
        return [dict(r) for r in cur.fetchall()]


def test_recompare_updates_matched_rows_in_place_and_leaves_others_stale(pilot):
    info = _seed_events(pilot)
    C.run_compare_stage(_claim(pilot), client=_client(_real_all(info)))
    first = _states(pilot.meeting_id)
    assert sorted(r["category"] for r in first) == ["sequence", "wording"]
    with db_cursor() as cur:   # the admin approves both
        cur.execute("UPDATE minutes_discrepancies SET review_state='approved', reviewed_at=now(), reviewed_by='t' WHERE meeting_id=%s", [pilot.meeting_id])

    # Second comparison: only the wording candidate is still judged real.
    def verdicts(user):
        out = []
        for cid in _ids_in_prompt(user):
            head = user.split(f"### Candidate {cid}")[1].split("\n")[0]
            real = "wording" in head
            out.append({"candidate_id": cid, "is_real": real, "category": "wording" if real else None, "severity": "material" if real else None,
                        "title": "wording title v2" if real else None, "description": "desc v2" if real else None,
                        "transcript_quote": info["exec_text"] if real else None, "minutes_quote": "go into Executive Session" if real else None,
                        "confidence": 0.9, "dismiss_reason": None if real else "now matches"})
        return out
    C.run_compare_stage(_claim(pilot), client=_client(verdicts))
    second = _states(pilot.meeting_id)
    wording = next(r for r in second if r["category"] == "wording" and r["review_state"] != "dismissed_by_model")
    sequence = next(r for r in second if r["category"] == "sequence" and r["review_state"] != "dismissed_by_model")
    assert wording["id"] == next(r["id"] for r in first if r["category"] == "wording")      # updated in place, no duplicate
    assert (wording["review_state"], wording["previous_review_state"]) == ("proposed", "approved")
    assert sequence["review_state"] == "stale"                                               # corrected minutes no longer show it
    with db_cursor() as cur:
        cur.execute("SELECT title FROM minutes_discrepancies WHERE id=%s", [wording["id"]])
        assert cur.fetchone()["title"] == "wording title v2"
    assert len([r for r in second if r["review_state"] in ("proposed", "approved", "stale")]) == 2


def test_sweep_flags_changed_minutes_for_recompare(pilot, monkeypatch):
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status='compared' WHERE id=%s", [pilot.transcript_id])
        cur.execute("UPDATE minutes_texts SET extracted_at = now() - interval '10 days' WHERE meeting_id=%s", [pilot.meeting_id])
    monkeypatch.setattr(M, "recheck_minutes", lambda mid: True)
    assert P.sweep_minutes_changes() >= 1
    with db_cursor() as cur:
        cur.execute("SELECT status, compare_skipped_reason, stage_attempts FROM transcripts WHERE id=%s", [pilot.transcript_id])
        assert tuple(cur.fetchone().values()) == ("events_extracted", "minutes_changed", 0)
    assert P.claim_next()["id"] == pilot.transcript_id       # claimable immediately


def test_unchanged_minutes_are_left_alone(pilot, monkeypatch):
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status='compared' WHERE id=%s", [pilot.transcript_id])
        cur.execute("UPDATE minutes_texts SET extracted_at = now() - interval '10 days' WHERE meeting_id=%s", [pilot.meeting_id])
    monkeypatch.setattr(M, "recheck_minutes", lambda mid: False)
    P.sweep_minutes_changes()
    with db_cursor() as cur:
        cur.execute("SELECT status FROM transcripts WHERE id=%s", [pilot.transcript_id])
        assert cur.fetchone()["status"] == "compared"


def test_run_for_meeting_drives_stages_in_order(pilot, monkeypatch):
    calls = []
    def fake(stage):
        nxt = {"speakers": "speakers_resolved", "events": "events_extracted", "compare": "compared"}[stage]
        return lambda claim, client: (calls.append(stage), P.StageOutcome(nxt))[1]
    monkeypatch.setattr(P, "_stage_fn", fake)
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status='uploaded', word_count=5000 WHERE id=%s", [pilot.transcript_id])
    outcomes = P.run_for_meeting(pilot.meeting_id, client=MagicMock(), notes="pytest_run_for_meeting")
    assert calls == ["speakers", "events", "compare"] and outcomes == ["advanced", "advanced", "advanced"]
    with db_cursor() as cur:
        cur.execute("DELETE FROM ai_runs WHERE notes='pytest_run_for_meeting'")
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/unit/test_reconcile_match.py tests/integration/test_recompare.py -v`
Expected: FAIL (`ImportError: match_stale`, `AttributeError: sweep_minutes_changes` returns 0 / no `run_for_meeting`).

- [ ] **Step 3: Reconciliation in `compare.py`**

Replace `write_rows` and add:

```python
from difflib import SequenceMatcher
from docket.ai.transcripts.guard import normalize as _norm

ADDITION_MATCH_RATIO = 0.8


def match_stale(new_row: dict, stale_rows: list[dict]) -> dict | None:
    if new_row.get("transcript_event_id") is not None:
        for s in stale_rows:
            if s["category"] == new_row["category"] and s.get("transcript_event_id") == new_row["transcript_event_id"]:
                return s
        return None
    best, best_ratio = None, 0.0
    for s in stale_rows:
        if s["category"] != new_row["category"] or s.get("agenda_item_id") != new_row.get("agenda_item_id"):
            continue
        r = SequenceMatcher(None, _norm(s.get("minutes_excerpt") or ""), _norm(new_row.get("minutes_excerpt") or "")).ratio()
        if r > best_ratio:
            best, best_ratio = s, r
    return best if best_ratio >= ADDITION_MATCH_RATIO else None


def reconcile(meeting_id: int, rows: list[dict]) -> dict:
    """Spec Section 4, 'Re-comparison'. Transcript event ids are stable across a minutes-side re-run.

    approved/proposed -> stale first; matched stale rows are updated in place and
    re-proposed with previous_review_state; rejected rows that match stay rejected
    (the reviewer already said no); old model dismissals are replaced wholesale.
    """
    with db_cursor() as cur:
        cur.execute("DELETE FROM minutes_discrepancies WHERE meeting_id = %s AND review_state = 'dismissed_by_model'", [meeting_id])
        cur.execute("""UPDATE minutes_discrepancies SET previous_review_state = review_state, review_state = 'stale'
                        WHERE meeting_id = %s AND review_state IN ('approved', 'proposed')""", [meeting_id])
        cur.execute("""SELECT id, category, transcript_event_id, agenda_item_id, minutes_excerpt, review_state, previous_review_state
                         FROM minutes_discrepancies WHERE meeting_id = %s AND review_state IN ('stale', 'rejected')""", [meeting_id])
        pool = [dict(r) for r in cur.fetchall()]
        inserted = updated = 0
        used: set[int] = set()
        for r in rows:
            match = match_stale(r, [p for p in pool if p["id"] not in used]) if r["review_state"] == "proposed" else None
            if match is None:
                cur.execute(f"INSERT INTO minutes_discrepancies ({', '.join(_COLS)}) VALUES ({', '.join(['%s'] * len(_COLS))})",
                            [r[c] for c in _COLS])
                inserted += 1
                continue
            used.add(match["id"])
            new_state = "rejected" if match["review_state"] == "rejected" else "proposed"
            cur.execute("""UPDATE minutes_discrepancies
                              SET title = %s, description = %s, severity = %s, minutes_event_id = %s, minutes_excerpt = %s,
                                  minutes_page = %s, transcript_excerpt = %s, transcript_start_s = %s, citation_match = %s,
                                  confidence = %s, prompt_version = %s, review_state = %s,
                                  previous_review_state = CASE WHEN %s = 'rejected' THEN previous_review_state ELSE previous_review_state END
                            WHERE id = %s""",
                        [r["title"], r["description"], r["severity"], r["minutes_event_id"], r["minutes_excerpt"], r["minutes_page"],
                         r["transcript_excerpt"], r["transcript_start_s"], r["citation_match"], r["confidence"], r["prompt_version"],
                         new_state, new_state, match["id"]])
            updated += 1
        cur.execute("SELECT count(*) AS n FROM minutes_discrepancies WHERE meeting_id = %s AND review_state = 'stale'", [meeting_id])
        stale = cur.fetchone()["n"]
    return {"inserted": inserted, "updated": updated, "stale": stale}


def write_rows(meeting_id: int, rows: list[dict]) -> int:
    r = reconcile(meeting_id, rows)
    log.info("compare: meeting %s reconcile inserted=%d updated=%d stale=%d", meeting_id, r["inserted"], r["updated"], r["stale"])
    return r["inserted"] + r["updated"]
```

On a first comparison the pool is empty, so every row inserts (Task 11's tests still pass).

- [ ] **Step 4: Sweep, targeted claim, and `run_for_meeting` in `pipeline.py`**

Replace the placeholder `sweep_minutes_changes` and add:

```python
def sweep_minutes_changes(limit: int = 10) -> int:
    """Re-download minutes for compared meetings at most once a week; a changed PDF re-runs the minutes side."""
    from docket.ai.transcripts.minutes import recheck_minutes
    with db_cursor() as cur:
        cur.execute("""SELECT t.id, t.meeting_id FROM transcripts t
                         JOIN minutes_texts mt ON mt.meeting_id = t.meeting_id
                         JOIN meetings m ON m.id = t.meeting_id
                        WHERE t.status = 'compared' AND m.minutes_url IS NOT NULL
                          AND mt.extracted_at < now() - interval '7 days'
                        ORDER BY mt.extracted_at LIMIT %s""", [limit])
        rows = [dict(r) for r in cur.fetchall()]
    flagged = 0
    for r in rows:
        changed = recheck_minutes(r["meeting_id"])
        if changed:
            with db_cursor() as cur:
                cur.execute("""UPDATE transcripts SET status = 'events_extracted', compare_skipped_reason = 'minutes_changed',
                                      stage_attempts = 0, last_attempted_at = NULL, updated_at = now() WHERE id = %s""", [r["id"]])
            flagged += 1
            log.info("minutes changed for meeting %s; re-comparison queued", r["meeting_id"])
        elif changed is False:
            with db_cursor() as cur:   # bump extracted_at so the next sweep moves on
                cur.execute("UPDATE minutes_texts SET extracted_at = now() WHERE meeting_id = %s", [r["meeting_id"]])
    return flagged


CLAIM_MEETING_SQL = CLAIM_SQL.replace("AND t.stage_attempts < 3\n       AND (t.last_attempted_at IS NULL OR t.last_attempted_at < now() - interval '24 hours')",
                                      "AND t.meeting_id = %s")


def claim_meeting(meeting_id: int) -> dict | None:
    assert "t.meeting_id = %s" in CLAIM_MEETING_SQL
    with db_cursor() as cur:
        cur.execute(CLAIM_MEETING_SQL, [meeting_id])
        row = cur.fetchone()
        return dict(row) if row else None


def run_for_meeting(meeting_id: int, *, notes: str = "cli_transcripts", client=None, until: str = "compared") -> list[str]:
    from docket.ai.transcripts.client import StructuredClient
    client = client or StructuredClient()
    outcomes: list[str] = []
    for _ in range(3):
        claim = claim_meeting(meeting_id)
        if claim is None or claim["status"] == until:
            break
        outcome = process_claim(claim, client=client, notes=notes)
        outcomes.append(outcome)
        if outcome not in ("advanced", "skipped"):
            break
    return outcomes
```

Add a unit assertion in `tests/unit/test_transcript_fitness.py` that `CLAIM_MEETING_SQL` contains `t.meeting_id = %s` and no `interval '24 hours'` (the string replace must have matched).

- [ ] **Step 5: Operator script**

```python
#!/usr/bin/env python
# scripts/transcript_recompare.py
"""Force a re-comparison for one meeting (corrected minutes, prompt tuning, a bad run).

    venv/bin/python scripts/transcript_recompare.py --meeting-id 2543          # queue for the next cron tick
    venv/bin/python scripts/transcript_recompare.py --meeting-id 2543 --now    # run the stages now (needs ANTHROPIC_API_KEY)

Approved rows are set stale and re-proposed in place when the same discrepancy
comes back (compare.reconcile), so nothing approved is silently lost.
"""
from __future__ import annotations

import argparse
import logging

from docket.db import db_cursor
from docket.ai.transcripts.pipeline import run_for_meeting

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ap = argparse.ArgumentParser()
ap.add_argument("--meeting-id", type=int, required=True)
ap.add_argument("--now", action="store_true")
a = ap.parse_args()
with db_cursor() as cur:
    cur.execute("""UPDATE transcripts SET status = 'events_extracted', compare_skipped_reason = 'minutes_changed',
                          stage_attempts = 0, last_attempted_at = NULL WHERE meeting_id = %s
                      AND status IN ('events_extracted', 'compared', 'needs_review', 'failed') RETURNING id""", [a.meeting_id])
    if cur.fetchone() is None:
        raise SystemExit("no transcript past event extraction for that meeting")
print("queued" if not a.now else run_for_meeting(a.meeting_id, notes="cli_recompare"))
```

- [ ] **Step 6: Run to verify pass**

Run: `venv/bin/python -m pytest tests/unit/test_reconcile_match.py tests/unit/test_transcript_fitness.py tests/integration/test_recompare.py tests/integration/test_compare_stage.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/docket/ai/transcripts/compare.py src/docket/ai/transcripts/pipeline.py scripts/transcript_recompare.py tests/unit/test_reconcile_match.py tests/unit/test_transcript_fitness.py tests/integration/test_recompare.py
git -c user.email=hello@docket.pub commit -m "feat(ai): re-comparison: minutes change sweep, stale reconciliation, recompare script

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 13: Alert webhook and the stalled-producer check

**Files:**
- Modify: `src/docket/ai/transcripts/alerts.py` (replace the Task 4 stub)
- Test: `tests/unit/test_alerts.py`, `tests/integration/test_producer_stalled.py`

**Interfaces:**
- Consumes: `ALERT_WEBHOOK_URL`, `TRANSCRIPT_BACKFILL_SINCE`, `requests`.
- Produces:
  - `post_alert(kind: str, text: str, **fields) -> bool` — POSTs `{"text": text, "content": text, "kind": kind, "source": "docket.pub worker", ...fields}` (Slack reads `text`, Discord reads `content`); `False` and no request when the URL is unset; exceptions logged and swallowed.
  - `producer_stalled() -> dict | None` — the newest Birmingham meeting with video, dated on or after `TRANSCRIPT_BACKFILL_SINCE` and more than 7 days ago, with no `transcripts` row, when no `producer_heartbeats.last_seen_at` is newer than 7 days. Returns `{"meeting_id", "meeting_date", "last_heartbeat"}` or `None`.
  - `alert_if_producer_stalled() -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_alerts.py
from unittest.mock import MagicMock, patch

import requests

from docket.ai.transcripts import alerts as A


def test_no_url_means_no_request(monkeypatch):
    monkeypatch.setattr(A, "ALERT_WEBHOOK_URL", None)
    with patch("docket.ai.transcripts.alerts.requests.post") as post:
        assert A.post_alert("transcript_failed", "x", meeting_id=1) is False
        post.assert_not_called()


def test_payload_fits_slack_and_discord(monkeypatch):
    monkeypatch.setattr(A, "ALERT_WEBHOOK_URL", "https://hooks.example/abc")
    with patch("docket.ai.transcripts.alerts.requests.post") as post:
        post.return_value = MagicMock(status_code=204, ok=True)
        assert A.post_alert("transcript_needs_review", "Transcript 7 held: candidate_cap", meeting_id=7, stage="compare") is True
        kw = post.call_args.kwargs
        assert post.call_args.args[0] == "https://hooks.example/abc" and kw["timeout"] == 10
        body = kw["json"]
        assert body["text"] == body["content"] == "Transcript 7 held: candidate_cap"
        assert body["kind"] == "transcript_needs_review" and body["meeting_id"] == 7 and body["stage"] == "compare"


def test_network_errors_are_swallowed(monkeypatch):
    monkeypatch.setattr(A, "ALERT_WEBHOOK_URL", "https://hooks.example/abc")
    with patch("docket.ai.transcripts.alerts.requests.post", side_effect=requests.ConnectionError("down")):
        assert A.post_alert("x", "y") is False
```

```python
# tests/integration/test_producer_stalled.py
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from docket.ai.transcripts import alerts as A
from docket.config import DATABASE_URL
from docket.db import db_cursor

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


@pytest.fixture
def old_meeting_without_transcript():
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, external_id, video_url)
                       VALUES (%s, 'stall test', %s, '999777', 'https://bhamal.granicus.com/MediaPlayer.php?clip_id=999777') RETURNING id""",
                    [muni, date.today() - timedelta(days=10)])
        mid = cur.fetchone()["id"]
        cur.execute("DELETE FROM producer_heartbeats WHERE host LIKE 'pytest-%%'")
    yield mid
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id=%s", [mid])
        cur.execute("DELETE FROM producer_heartbeats WHERE host LIKE 'pytest-%%'")


def test_stalled_when_no_recent_heartbeat(old_meeting_without_transcript, monkeypatch):
    with db_cursor() as cur:
        cur.execute("UPDATE producer_heartbeats SET last_seen_at = now() - interval '30 days'")   # any real rows are old for this test
    s = A.producer_stalled()
    assert s is not None and s["meeting_id"] == old_meeting_without_transcript
    monkeypatch.setattr(A, "ALERT_WEBHOOK_URL", "https://hooks.example/abc")
    with patch("docket.ai.transcripts.alerts.requests.post") as post:
        post.return_value.ok = True
        assert A.alert_if_producer_stalled() is True
        assert "no transcript" in post.call_args.kwargs["json"]["text"]


def test_recent_heartbeat_means_not_stalled(old_meeting_without_transcript):
    with db_cursor() as cur:
        cur.execute("INSERT INTO producer_heartbeats (host, last_seen_at, last_status) VALUES ('pytest-legion', now(), 'idle')")
    assert A.producer_stalled() is None
    assert A.alert_if_producer_stalled() is False
```

Note for the first test: it ages every heartbeat row to 30 days. Add a module-level fixture that snapshots `producer_heartbeats` before and restores it after, so a developer's local heartbeat rows are not left aged; on CI the table is empty.

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/unit/test_alerts.py tests/integration/test_producer_stalled.py -v`
Expected: FAIL (stub returns False; `producer_stalled` missing).

- [ ] **Step 3: Write `alerts.py`**

```python
# src/docket/ai/transcripts/alerts.py
"""Outbound alerts (spec Section 3, "Alerting"): the first active alert in the codebase.

One env-gated webhook URL. Slack reads `text`, Discord reads `content`; both
are sent. Fired on a transcript entering failed or needs_review (pipeline),
on a tripped candidate cap (TranscriptHeld), and once a day when the desktop
looks stalled.
"""
from __future__ import annotations

import logging

import requests

from docket.config import ALERT_WEBHOOK_URL, TRANSCRIPT_BACKFILL_SINCE
from docket.db import db_cursor

log = logging.getLogger(__name__)
STALL_DAYS = 7


def post_alert(kind: str, text: str, **fields) -> bool:
    if not ALERT_WEBHOOK_URL:
        return False
    payload = {"text": text, "content": text, "kind": kind, "source": "docket.pub worker", **fields}
    try:
        resp = requests.post(ALERT_WEBHOOK_URL, json=payload, timeout=10)
        if not resp.ok:
            log.warning("alert webhook returned %s", resp.status_code)
            return False
        return True
    except requests.RequestException as e:
        log.warning("alert webhook failed: %s", e)
        return False


def producer_stalled() -> dict | None:
    with db_cursor() as cur:
        cur.execute(
            """SELECT m.id AS meeting_id, m.meeting_date
                 FROM meetings m JOIN municipalities mu ON mu.id = m.municipality_id
                 LEFT JOIN transcripts t ON t.meeting_id = m.id
                WHERE mu.slug = 'birmingham' AND m.external_id ~ '^[0-9]+$' AND m.is_hidden = FALSE
                  AND m.video_url IS NOT NULL AND t.id IS NULL
                  AND m.meeting_date >= %s::date AND m.meeting_date < CURRENT_DATE - %s
                ORDER BY m.meeting_date DESC LIMIT 1""",
            [TRANSCRIPT_BACKFILL_SINCE, STALL_DAYS],
        )
        meeting = cur.fetchone()
        if not meeting:
            return None
        cur.execute("SELECT max(last_seen_at) AS hb FROM producer_heartbeats")
        hb = cur.fetchone()["hb"]
        cur.execute("SELECT %s::timestamptz IS NOT NULL AND %s::timestamptz > now() - make_interval(days => %s) AS fresh", [hb, hb, STALL_DAYS])
        if cur.fetchone()["fresh"]:
            return None
    return {"meeting_id": meeting["meeting_id"], "meeting_date": str(meeting["meeting_date"]), "last_heartbeat": str(hb) if hb else None}


def alert_if_producer_stalled() -> bool:
    s = producer_stalled()
    if s is None:
        return False
    return post_alert("producer_stalled",
                      f"Legion looks stalled: meeting {s['meeting_id']} ({s['meeting_date']}) has video and no transcript; "
                      f"last producer heartbeat {s['last_heartbeat'] or 'never'}.", **s)
```

- [ ] **Step 4: Run to verify pass**

Run: `venv/bin/python -m pytest tests/unit/test_alerts.py tests/integration/test_producer_stalled.py tests/integration/test_transcript_pipeline.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/docket/ai/transcripts/alerts.py tests/unit/test_alerts.py tests/integration/test_producer_stalled.py
git -c user.email=hello@docket.pub commit -m "feat(worker): alert webhook for held/failed transcripts and a stalled producer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 14: CSRF helper, discrepancy services, and the admin review queue

**Files:**
- Create: `src/docket/web/csrf.py`, `src/docket/services/discrepancies.py`, `src/docket/web/admin_transcripts.py`, `src/docket/web/templates/admin/review_discrepancies.html`, `src/docket/web/templates/admin/_discrepancy_row.html`
- Modify: `src/docket/web/__init__.py:176-180` (register blueprint, CSRF global), `src/docket/web/templates/admin/ai_panel.html:12-14` and `admin/members.html:11-21` (nav link)
- Test: `tests/unit/test_csrf.py`, `tests/integration/test_admin_discrepancies.py`

**Interfaces:**
- Consumes: `guard.find_citation`, `compare.transcript_text`, `events.load_segments_with_speakers`, `minutes.load_minutes`, `chapter_url` Jinja global, `format_timestamp`/`format_date` filters, `authed_admin_client` fixture pattern.
- Produces:
  - `csrf.csrf_token() -> str` (Jinja global; creates `session["csrf_token"]` on first use), `csrf.validate_csrf() -> None` (aborts 400 on a POST without a matching `csrf_token` form field or `X-CSRF-Token` header), `csrf.register(app)`.
  - `discrepancies.list_queue(*, state="proposed", category=None, meeting_id=None, limit=50, offset=0) -> list[dict]` with the row columns plus `meeting_title, meeting_date, municipality_slug, video_url, minutes_url, item_number, item_external_id, item_title, display_title, display_description`.
  - `discrepancies.get(discrepancy_id) -> dict | None`.
  - `class DiscrepancyStateError(Exception)`, `class CitationNotFound(Exception)` — the blueprint turns both into a flashed error and a redirect back to the queue (a raw error page would lose the reviewer's place); 404 stays for unknown ids and 400 for a missing CSRF token or reject reason.
  - `approve(discrepancy_id, actor, note=None)`, `reject(discrepancy_id, actor, reason)`, `edit_and_approve(discrepancy_id, actor, admin_title, admin_description, transcript_excerpt=None, minutes_excerpt=None)`.
  - `held_transcripts() -> list[dict]`; `retry_transcript(meeting_id) -> str` (new status).
  - `list_public_for_meeting(meeting_id)`, `list_public_for_item(item_id)`, `list_public_recent(limit=50, offset=0)` — `approved` only (Task 16 consumes).
  - `ship_gate(rows: list[dict]) -> dict` and `approval_ratio() -> dict` (Task 17 consumes): keys `approved, rejected, total, meetings, ratio, window_complete, gate_met`.
  - Blueprint `admin_transcripts` (`url_prefix="/admin"`), endpoints `admin_transcripts.review_discrepancies`, `.approve`, `.reject`, `.edit_approve`, `.retry_transcript`.

- [ ] **Step 1: Write the failing unit test for CSRF**

```python
# tests/unit/test_csrf.py
import pytest
from flask import Flask, session

from docket.web import csrf


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "t"
    app.config["TESTING"] = True
    csrf.register(app)

    @app.route("/tok")
    def tok():
        return csrf.csrf_token()

    @app.route("/post", methods=["POST"])
    def post():
        csrf.validate_csrf()
        return "ok"
    return app


def test_token_is_stable_within_a_session_and_exposed_to_jinja(app):
    c = app.test_client()
    a, b = c.get("/tok").get_data(as_text=True), c.get("/tok").get_data(as_text=True)
    assert a == b and len(a) == 64
    assert app.jinja_env.globals["csrf_token"] is csrf.csrf_token


def test_post_without_token_is_400_and_with_token_is_ok(app):
    c = app.test_client()
    tok = c.get("/tok").get_data(as_text=True)
    assert c.post("/post").status_code == 400
    assert c.post("/post", data={"csrf_token": "wrong"}).status_code == 400
    assert c.post("/post", data={"csrf_token": tok}).status_code == 200
    assert c.post("/post", headers={"X-CSRF-Token": tok}).status_code == 200
```

- [ ] **Step 2: Write the failing integration tests**

```python
# tests/integration/test_admin_discrepancies.py
"""Queue list, approve/reject/edit, citation and stale guards, CSRF, auth."""
import pytest

from docket.config import DATABASE_URL
from docket.db import db_cursor
from docket.services import discrepancies as D
from docket.web import create_app
from tests.support.transcript_fixtures import install_bundle, pilot_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)
TOK = "test-csrf-token"


@pytest.fixture(scope="module")
def app():
    a = create_app()
    a.config["TESTING"] = True
    return a


@pytest.fixture
def admin(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s["admin_user"] = "tester"
        s["csrf_token"] = TOK
    return c


@pytest.fixture
def pilot():
    i = install_bundle(pilot_bundle(), external_id="999015", status="compared")
    yield i
    i.cleanup()


def _event(mid, source, seq, et, item):
    with db_cursor() as cur:
        cur.execute("""INSERT INTO meeting_events (meeting_id, source, seq, event_type, scope, agenda_item_refs, summary, detail, prompt_version)
                       VALUES (%s, %s, %s, %s, 'item', %s, 'e', '{}', 200) RETURNING id""", [mid, source, seq, et, [item]])
        return cur.fetchone()["id"]


def _disc(inst, **kw):
    item = inst.item_ids[1501]
    t = _event(inst.meeting_id, "transcript", kw.pop("tseq", 1), "executive_session_motion", item)
    m = _event(inst.meeting_id, "minutes", kw.pop("mseq", 1), "executive_session_motion", item)
    row = {"meeting_id": inst.meeting_id, "agenda_item_id": item, "category": "wording", "severity": "material",
           "title": "Different statutory ground", "description": "Video cites (a)(4); minutes cite pending litigation.",
           "transcript_event_id": t, "minutes_event_id": m, "transcript_excerpt": "we will go into executive session",
           "transcript_start_s": 3400.0, "minutes_excerpt": "go into Executive Session", "minutes_page": 12,
           "citation_match": "exact", "confidence": 0.9, "origin": "aligner", "review_state": "proposed", "prompt_version": 200}
    row.update(kw)
    cols = list(row)
    with db_cursor() as cur:
        cur.execute(f"INSERT INTO minutes_discrepancies ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id",
                    [row[c] for c in cols])
        return cur.fetchone()["id"]


def _state(did):
    with db_cursor() as cur:
        cur.execute("SELECT review_state, reviewed_by, reject_reason, admin_title, admin_description, title, citation_match, transcript_excerpt FROM minutes_discrepancies WHERE id=%s", [did])
        return dict(cur.fetchone())


def test_queue_lists_material_first_with_both_excerpts_and_links(admin, pilot):
    minor = _disc(pilot, severity="minor", title="Minor wording", tseq=2, mseq=2)
    material = _disc(pilot)
    html = admin.get("/admin/review/discrepancies").get_data(as_text=True)
    assert html.index("Different statutory ground") < html.index("Minor wording")
    assert "we will go into executive session" in html and "go into Executive Session" in html
    assert "p. 12" in html and "00:56:40" in html                         # minutes page, transcript timestamp
    assert "MinutesViewer.php" in html and "meta_id=" not in html          # minutes link; chapter link needs numeric meta_id (pilot's is '1950-15')
    assert f"/admin/review/discrepancies/{material}/approve" in html


def test_filters_by_state_category_and_meeting(admin, pilot):
    _disc(pilot, review_state="dismissed_by_model", reject_reason="same words", title="Dismissed one")
    _disc(pilot, category="sequence", title="Sequence one", tseq=3, mseq=3)
    assert "Dismissed one" not in admin.get("/admin/review/discrepancies").get_data(as_text=True)
    assert "Dismissed one" in admin.get("/admin/review/discrepancies?state=dismissed_by_model").get_data(as_text=True)
    only_seq = admin.get("/admin/review/discrepancies?category=sequence").get_data(as_text=True)
    assert "Sequence one" in only_seq and "Different statutory ground" not in only_seq
    assert "Sequence one" in admin.get(f"/admin/review/discrepancies?meeting_id={pilot.meeting_id}").get_data(as_text=True)


def test_approve_sets_state_and_reviewer(admin, pilot):
    did = _disc(pilot)
    r = admin.post(f"/admin/review/discrepancies/{did}/approve", data={"csrf_token": TOK})
    assert r.status_code in (302, 303) and "/admin/review/discrepancies" in r.headers["Location"]
    s = _state(did)
    assert s["review_state"] == "approved" and s["reviewed_by"] == "tester"
    assert "approved" in admin.get("/admin/review/discrepancies").get_data(as_text=True).lower()


def test_missing_citation_cannot_be_approved_until_attached(admin, pilot):
    did = _disc(pilot, citation_match="missing", transcript_excerpt="words nobody said", confidence=0.4)
    html = admin.get("/admin/review/discrepancies").get_data(as_text=True)
    assert "disabled" in html.split(f"/discrepancies/{did}/approve")[0][-400:]           # Review Focus 2: button disabled
    r = admin.post(f"/admin/review/discrepancies/{did}/approve", data={"csrf_token": TOK})
    assert r.status_code in (302, 303) and _state(did)["review_state"] == "proposed"
    assert "attach a citation" in admin.get("/admin/review/discrepancies").get_data(as_text=True)   # flashed, not an error page
    # Reviewer attaches a transcript excerpt that the guard can find in the pilot transcript.
    r = admin.post(f"/admin/review/discrepancies/{did}/edit-approve",
                   data={"csrf_token": TOK, "admin_title": "Statutory ground differs", "admin_description": "Edited.",
                         "transcript_excerpt": "executive session", "minutes_excerpt": "go into Executive Session"})
    assert r.status_code in (302, 303)
    s = _state(did)
    assert s["review_state"] == "approved" and s["citation_match"] in ("exact", "fuzzy")
    assert s["admin_title"] == "Statutory ground differs" and s["title"] == "Different statutory ground"   # model text kept
    bad = _disc(pilot, citation_match="missing", tseq=5, mseq=5)
    r = admin.post(f"/admin/review/discrepancies/{bad}/edit-approve",
                   data={"csrf_token": TOK, "admin_title": "x", "admin_description": "y", "transcript_excerpt": "not in there at all"})
    assert r.status_code in (302, 303) and _state(bad)["review_state"] == "proposed"
    assert "not found in the transcript" in admin.get("/admin/review/discrepancies").get_data(as_text=True)


def test_stale_row_cannot_be_approved(admin, pilot):
    did = _disc(pilot, review_state="stale")
    r = admin.post(f"/admin/review/discrepancies/{did}/approve", data={"csrf_token": TOK})   # Review Focus 3
    assert r.status_code in (302, 303) and _state(did)["review_state"] == "stale"
    assert "row is stale" in admin.get("/admin/review/discrepancies?state=stale").get_data(as_text=True)
    assert "Different statutory ground" in admin.get("/admin/review/discrepancies?state=stale").get_data(as_text=True)


def test_reject_requires_reason(admin, pilot):
    did = _disc(pilot)
    assert admin.post(f"/admin/review/discrepancies/{did}/reject", data={"csrf_token": TOK}).status_code == 400
    r = admin.post(f"/admin/review/discrepancies/{did}/reject", data={"csrf_token": TOK, "reason": "same action, different words"})
    assert r.status_code in (302, 303)
    s = _state(did)
    assert s["review_state"] == "rejected" and s["reject_reason"] == "same action, different words"


def test_csrf_and_login_are_enforced(app, admin, pilot):
    did = _disc(pilot)
    assert admin.post(f"/admin/review/discrepancies/{did}/approve").status_code == 400                      # no token
    anon = app.test_client()
    r = anon.post(f"/admin/review/discrepancies/{did}/approve", data={"csrf_token": TOK})
    assert r.status_code in (302, 303) and "/admin/login" in r.headers["Location"]
    assert anon.get("/admin/review/discrepancies").status_code in (302, 303)
    assert _state(did)["review_state"] == "proposed"


def test_held_tab_lists_transcripts_and_retry_resets_them(admin, pilot):
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status='needs_review', needs_review_reason='candidate_cap', last_error='44 candidates' WHERE id=%s",
                    [pilot.transcript_id])
    html = admin.get("/admin/review/discrepancies?state=held").get_data(as_text=True)
    assert "candidate_cap" in html and "44 candidates" in html
    r = admin.post(f"/admin/transcripts/{pilot.meeting_id}/retry", data={"csrf_token": TOK})
    assert r.status_code in (302, 303)
    with db_cursor() as cur:
        cur.execute("SELECT status, stage_attempts, needs_review_reason FROM transcripts WHERE id=%s", [pilot.transcript_id])
        row = cur.fetchone()
    assert row["status"] == "uploaded" and row["stage_attempts"] == 0 and row["needs_review_reason"] is None  # no resolved speakers, no events -> start over


def test_public_reads_return_only_approved(pilot):
    a = _disc(pilot, review_state="approved")
    _disc(pilot, review_state="proposed", tseq=2, mseq=2)
    _disc(pilot, review_state="stale", tseq=3, mseq=3)
    rows = D.list_public_for_meeting(pilot.meeting_id)
    assert [r["id"] for r in rows] == [a]
    assert D.list_public_for_item(pilot.item_ids[1501])[0]["id"] == a
    assert any(r["id"] == a for r in D.list_public_recent())
```

- [ ] **Step 3: Run to verify failure**

Run: `venv/bin/python -m pytest tests/unit/test_csrf.py tests/integration/test_admin_discrepancies.py -v`
Expected: FAIL, `ModuleNotFoundError: docket.web.csrf`.

- [ ] **Step 4: Write `csrf.py` and register it**

```python
# src/docket/web/csrf.py
"""Session-token CSRF for the admin_transcripts blueprint (issue #83 tracks the older admin routes).

Templates render ``<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">``;
HTMX requests may send ``X-CSRF-Token`` instead. Validation runs in the
blueprint's before_request for every state-changing method.
"""
from __future__ import annotations

import hmac
import secrets

from flask import abort, request, session

_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def csrf_token() -> str:
    tok = session.get("csrf_token")
    if not tok:
        tok = secrets.token_hex(32)
        session["csrf_token"] = tok
    return tok


def validate_csrf() -> None:
    if request.method not in _UNSAFE:
        return
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    expected = session.get("csrf_token")
    if not (sent and expected and hmac.compare_digest(sent, expected)):
        abort(400, "CSRF token missing or invalid")


def register(app) -> None:
    app.jinja_env.globals["csrf_token"] = csrf_token
```

In `src/docket/web/__init__.py`, next to the other blueprint registrations:

```python
    from docket.web import csrf as _csrf
    from docket.web.admin_transcripts import bp as admin_transcripts_bp
    _csrf.register(app)
    app.register_blueprint(admin_transcripts_bp)
```

- [ ] **Step 5: Write `services/discrepancies.py`**

```python
# src/docket/services/discrepancies.py
"""Reads and state changes for minutes_discrepancies (admin queue, public block, ship gate)."""
from __future__ import annotations

from docket.db import db_cursor

QUEUE_STATES = ("proposed", "approved", "rejected", "dismissed_by_model", "stale")
SHIP_GATE_MEETINGS = 10
SHIP_GATE_CANDIDATES = 30
SHIP_GATE_RATIO = 0.70


class DiscrepancyStateError(Exception):
    """The row is not in a state that allows this action (409)."""


class CitationNotFound(Exception):
    """A reviewer-supplied excerpt could not be found in the source text (400)."""


_SELECT = """
    SELECT d.*, m.title AS meeting_title, m.meeting_date, m.video_url, m.minutes_url, mu.slug AS municipality_slug,
           ai.item_number, ai.external_id AS item_external_id, ai.title AS item_title,
           COALESCE(d.admin_title, d.title) AS display_title,
           COALESCE(d.admin_description, d.description) AS display_description
      FROM minutes_discrepancies d
      JOIN meetings m ON m.id = d.meeting_id
      JOIN municipalities mu ON mu.id = m.municipality_id
      LEFT JOIN agenda_items ai ON ai.id = d.agenda_item_id
"""


def list_queue(*, state: str = "proposed", category: str | None = None, meeting_id: int | None = None,
               limit: int = 50, offset: int = 0) -> list[dict]:
    where, params = ["d.review_state = %s"], [state]
    if category:
        where.append("d.category = %s"); params.append(category)
    if meeting_id:
        where.append("d.meeting_id = %s"); params.append(meeting_id)
    with db_cursor() as cur:
        cur.execute(f"""{_SELECT} WHERE {' AND '.join(where)}
                        ORDER BY (d.severity = 'material') DESC, m.meeting_date DESC, d.confidence DESC NULLS LAST, d.id
                        LIMIT %s OFFSET %s""", [*params, limit, offset])
        return [dict(r) for r in cur.fetchall()]


def get(discrepancy_id: int) -> dict | None:
    with db_cursor() as cur:
        cur.execute(f"{_SELECT} WHERE d.id = %s", [discrepancy_id])
        row = cur.fetchone()
        return dict(row) if row else None


def approve(discrepancy_id: int, actor: str, note: str | None = None) -> None:
    with db_cursor() as cur:
        cur.execute("""UPDATE minutes_discrepancies
                          SET review_state = 'approved', reviewed_at = now(), reviewed_by = %s, review_note = COALESCE(%s, review_note)
                        WHERE id = %s AND review_state = 'proposed' AND citation_match <> 'missing'""",
                    [actor, note, discrepancy_id])
        if cur.rowcount == 0:
            cur.execute("SELECT review_state, citation_match FROM minutes_discrepancies WHERE id = %s", [discrepancy_id])
            row = cur.fetchone()
            if row is None:
                raise LookupError(discrepancy_id)
            if row["citation_match"] == "missing":
                raise DiscrepancyStateError("attach a citation before approving")
            raise DiscrepancyStateError(f"row is {row['review_state']}, not proposed")


def reject(discrepancy_id: int, actor: str, reason: str) -> None:
    if not (reason or "").strip():
        raise ValueError("reason required")
    with db_cursor() as cur:
        cur.execute("""UPDATE minutes_discrepancies SET review_state = 'rejected', reject_reason = %s, reviewed_at = now(), reviewed_by = %s
                        WHERE id = %s AND review_state = 'proposed'""", [reason.strip(), actor, discrepancy_id])
        if cur.rowcount == 0:
            raise DiscrepancyStateError("row is not proposed")


def _attach_citation(row: dict, transcript_excerpt: str | None, minutes_excerpt: str | None) -> tuple[str, dict]:
    from docket.ai.transcripts.compare import transcript_text, segment_at, citation_match_for
    from docket.ai.transcripts.events import load_segments_with_speakers
    from docket.ai.transcripts.guard import find_citation
    from docket.ai.transcripts.minutes import load_minutes, page_for_offset
    updates, kinds = {}, []
    if transcript_excerpt and transcript_excerpt.strip():
        with db_cursor() as cur:
            cur.execute("SELECT id FROM transcripts WHERE meeting_id = %s", [row["meeting_id"]])
            tid = cur.fetchone()["id"]
        tt = transcript_text(load_segments_with_speakers(tid))
        cm = find_citation(transcript_excerpt, tt.joined)
        if cm.kind == "missing":
            raise CitationNotFound("transcript excerpt not found in the transcript")
        seg = segment_at(tt, cm.start)
        updates.update(transcript_excerpt=tt.joined[cm.start:cm.end], transcript_start_s=seg["start_s"] if seg else row["transcript_start_s"])
        kinds.append(cm.kind)
    if minutes_excerpt and minutes_excerpt.strip():
        minutes = load_minutes(row["meeting_id"])
        cm = find_citation(minutes_excerpt, minutes.text) if minutes else None
        if cm is None or cm.kind == "missing":
            raise CitationNotFound("minutes excerpt not found in the minutes text")
        updates.update(minutes_excerpt=minutes.text[cm.start:cm.end], minutes_page=page_for_offset(minutes.page_offsets, cm.start))
        kinds.append(cm.kind)
    if not kinds:
        raise CitationNotFound("no excerpt supplied")
    return citation_match_for(kinds), updates


def edit_and_approve(discrepancy_id: int, actor: str, admin_title: str, admin_description: str,
                     transcript_excerpt: str | None = None, minutes_excerpt: str | None = None) -> None:
    row = get(discrepancy_id)
    if row is None:
        raise LookupError(discrepancy_id)
    if row["review_state"] != "proposed":
        raise DiscrepancyStateError(f"row is {row['review_state']}, not proposed")
    updates = {"admin_title": admin_title.strip() or None, "admin_description": admin_description.strip() or None}
    if row["citation_match"] == "missing" or transcript_excerpt or minutes_excerpt:
        match, cit = _attach_citation(row, transcript_excerpt, minutes_excerpt)
        updates.update(cit, citation_match=match)
    sets = ", ".join(f"{k} = %s" for k in updates)
    with db_cursor() as cur:
        cur.execute(f"UPDATE minutes_discrepancies SET {sets} WHERE id = %s", [*updates.values(), discrepancy_id])
    approve(discrepancy_id, actor)


def held_transcripts() -> list[dict]:
    with db_cursor() as cur:
        cur.execute("""SELECT t.id AS transcript_id, t.meeting_id, t.status, t.needs_review_reason, t.last_error, t.stage_attempts,
                              t.updated_at, m.title AS meeting_title, m.meeting_date, mu.slug AS municipality_slug
                         FROM transcripts t JOIN meetings m ON m.id = t.meeting_id JOIN municipalities mu ON mu.id = m.municipality_id
                        WHERE t.status IN ('needs_review', 'failed') AND t.uploaded_at IS NOT NULL
                        ORDER BY m.meeting_date DESC""")
        return [dict(r) for r in cur.fetchall()]


def retry_transcript(meeting_id: int) -> str:
    """Put a held/failed transcript back at the earliest stage whose output is missing."""
    with db_cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM meeting_events WHERE meeting_id = %s AND source = 'transcript') AS ev", [meeting_id])
        has_events = cur.fetchone()["ev"]
        cur.execute("SELECT EXISTS (SELECT 1 FROM transcript_speakers WHERE meeting_id = %s AND method IS NOT NULL) AS sp", [meeting_id])
        has_speakers = cur.fetchone()["sp"]
        status = "events_extracted" if has_events else ("speakers_resolved" if has_speakers else "uploaded")
        cur.execute("""UPDATE transcripts SET status = %s, stage_attempts = 0, last_attempted_at = NULL, needs_review_reason = NULL,
                              last_error = NULL, compare_skipped_reason = NULL, updated_at = now()
                        WHERE meeting_id = %s AND status IN ('needs_review', 'failed')""", [status, meeting_id])
        if cur.rowcount == 0:
            raise DiscrepancyStateError("transcript is not held or failed")
    return status


# --- public reads (approved only) --------------------------------------------

_PUBLIC_ORDER = "ORDER BY (d.severity = 'material') DESC, d.reviewed_at DESC, d.id"


def list_public_for_meeting(meeting_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(f"{_SELECT} WHERE d.meeting_id = %s AND d.review_state = 'approved' AND m.is_hidden = FALSE {_PUBLIC_ORDER}", [meeting_id])
        return [dict(r) for r in cur.fetchall()]


def list_public_for_item(item_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(f"{_SELECT} WHERE d.agenda_item_id = %s AND d.review_state = 'approved' AND m.is_hidden = FALSE {_PUBLIC_ORDER}", [item_id])
        return [dict(r) for r in cur.fetchall()]


def list_public_recent(limit: int = 50, offset: int = 0) -> list[dict]:
    with db_cursor() as cur:
        cur.execute(f"""{_SELECT} WHERE d.review_state = 'approved' AND m.is_hidden = FALSE
                        ORDER BY m.meeting_date DESC, (d.severity = 'material') DESC, d.id LIMIT %s OFFSET %s""", [limit, offset])
        return [dict(r) for r in cur.fetchall()]


# --- ship gate -----------------------------------------------------------------

def ship_gate(rows: list[dict]) -> dict:
    """Spec Section 6: >= 70% of material candidates approved over the first 10 reviewed meetings
    or the first 30 reviewed candidates, whichever comes first. `rows` are material rows in
    review_state approved/rejected ordered by reviewed_at with keys meeting_id, review_state."""
    approved = rejected = 0
    meetings: list[int] = []
    for r in rows:
        if r["meeting_id"] not in meetings:
            if len(meetings) == SHIP_GATE_MEETINGS:
                break
            meetings.append(r["meeting_id"])
        if r["review_state"] == "approved":
            approved += 1
        else:
            rejected += 1
        if approved + rejected >= SHIP_GATE_CANDIDATES:
            break
    total = approved + rejected
    ratio = approved / total if total else 0.0
    complete = total >= SHIP_GATE_CANDIDATES or len(meetings) >= SHIP_GATE_MEETINGS
    return {"approved": approved, "rejected": rejected, "total": total, "meetings": len(meetings),
            "ratio": round(ratio, 3), "window_complete": complete, "gate_met": complete and ratio >= SHIP_GATE_RATIO}


def approval_ratio() -> dict:
    with db_cursor() as cur:
        cur.execute("""SELECT meeting_id, review_state FROM minutes_discrepancies
                        WHERE severity = 'material' AND review_state IN ('approved', 'rejected') AND reviewed_at IS NOT NULL
                        ORDER BY reviewed_at, id""")
        return ship_gate([dict(r) for r in cur.fetchall()])
```

- [ ] **Step 6: Write the blueprint**

```python
# src/docket/web/admin_transcripts.py
"""Admin: discrepancy review queue, held transcripts, speaker correction (Task 15)."""
from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from docket.services import discrepancies as D
from docket.web.csrf import validate_csrf

bp = Blueprint("admin_transcripts", __name__, url_prefix="/admin")
PAGE = 50
CATEGORIES = ("vote_outcome", "omission", "addition", "wording", "sequence", "speaker")


@bp.before_request
def _guard():
    if request.endpoint and request.endpoint.startswith("admin_transcripts."):
        if "admin_user" not in session:
            return redirect(url_for("auth.login", next=request.path))
        validate_csrf()


def _back():
    return request.form.get("next") or request.headers.get("Referer") or url_for("admin_transcripts.review_discrepancies")


@bp.route("/review/discrepancies")
def review_discrepancies():
    state = request.args.get("state", "proposed")
    category = request.args.get("category") or None
    meeting_id = request.args.get("meeting_id", type=int)
    offset = max(0, request.args.get("offset", 0, type=int))
    held = D.held_transcripts() if state == "held" else []
    rows = [] if state == "held" else D.list_queue(state=state, category=category, meeting_id=meeting_id, limit=PAGE + 1, offset=offset)
    next_offset = offset + PAGE if len(rows) > PAGE else None
    return render_template("admin/review_discrepancies.html", rows=rows[:PAGE], held=held, state=state, category=category,
                           meeting_id=meeting_id, offset=offset, next_offset=next_offset, categories=CATEGORIES,
                           gate=D.approval_ratio(), states=D.QUEUE_STATES + ("held",))


def _fail(discrepancy_id: int, e: Exception):
    """A state race or a bad excerpt is a reviewer-facing message, not an error page."""
    flash(f"Discrepancy #{discrepancy_id} not changed: {e}", "error")
    return redirect(_back())


@bp.post("/review/discrepancies/<int:discrepancy_id>/approve")
def approve(discrepancy_id: int):
    try:
        D.approve(discrepancy_id, session.get("admin_user", "unknown"), request.form.get("note"))
    except LookupError:
        abort(404)
    except D.DiscrepancyStateError as e:
        return _fail(discrepancy_id, e)
    flash(f"Discrepancy #{discrepancy_id} approved.")
    return redirect(_back())


@bp.post("/review/discrepancies/<int:discrepancy_id>/reject")
def reject(discrepancy_id: int):
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        abort(400, "reason required")
    try:
        D.reject(discrepancy_id, session.get("admin_user", "unknown"), reason)
    except D.DiscrepancyStateError as e:
        return _fail(discrepancy_id, e)
    flash(f"Discrepancy #{discrepancy_id} rejected.")
    return redirect(_back())


@bp.post("/review/discrepancies/<int:discrepancy_id>/edit-approve")
def edit_approve(discrepancy_id: int):
    try:
        D.edit_and_approve(discrepancy_id, session.get("admin_user", "unknown"),
                           request.form.get("admin_title", ""), request.form.get("admin_description", ""),
                           request.form.get("transcript_excerpt"), request.form.get("minutes_excerpt"))
    except LookupError:
        abort(404)
    except (D.CitationNotFound, D.DiscrepancyStateError) as e:
        return _fail(discrepancy_id, e)
    flash(f"Discrepancy #{discrepancy_id} edited and approved. Only what docket.pub shows changed; the model text is kept.")
    return redirect(_back())


@bp.post("/transcripts/<int:meeting_id>/retry")
def retry_transcript(meeting_id: int):
    try:
        status = D.retry_transcript(meeting_id)
    except D.DiscrepancyStateError as e:
        flash(f"Transcript for meeting {meeting_id} not changed: {e}", "error")
        return redirect(_back())
    flash(f"Transcript for meeting {meeting_id} reset to {status}; the next cron tick picks it up.")
    return redirect(_back())
```

- [ ] **Step 7: Templates**

`admin/review_discrepancies.html` (mirrors `admin/errors.html`):

```html
{% extends "base.html" %}
{% block title %}Minutes vs. video queue — Admin — docket.pub{% endblock %}
{% block content %}
<div style="display: flex; justify-content: space-between; align-items: center;">
  <h1>Minutes vs. video queue</h1>
  <form method="post" action="{{ url_for('auth.logout') }}" style="margin: 0;">
    <button type="submit" style="font-size: 0.85rem;">Sign Out ({{ session.get('admin_user', '') }})</button>
  </form>
</div>
<p><a href="{{ url_for('admin.list_members') }}">← Council Members</a> &middot;
   <a href="{{ url_for('admin.review_conflicts') }}">Conflicts</a> &middot;
   <a href="{{ url_for('admin.ai_panel') }}">AI Pipeline</a></p>
<p class="t-meta">Proposed by the comparison pipeline; nothing here is public until approved. Material first.
   Ship gate: {{ gate.approved }}/{{ gate.total }} material approved ({{ (gate.ratio * 100) | round }}%) over {{ gate.meetings }} meetings
   — {{ 'met' if gate.gate_met else ('window open' if not gate.window_complete else 'not met') }}.</p>
{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}<ul class="queue-flash">{% for cat, msg in messages %}<li{% if cat == 'error' %} style="color: var(--color-danger, #a00);"{% endif %}>{{ msg }}</li>{% endfor %}</ul>{% endif %}
{% endwith %}
<nav class="t-meta" style="margin: 8px 0;">
  {% for s in states %}<a href="{{ url_for('admin_transcripts.review_discrepancies', state=s) }}"{% if s == state %} style="font-weight: 700;"{% endif %}>{{ s.replace('_', ' ') }}</a>{% if not loop.last %} &middot; {% endif %}{% endfor %}
</nav>
{% if state != 'held' %}
<form method="get" class="audit-filter">
  <input type="hidden" name="state" value="{{ state }}">
  <label>Category <select name="category"><option value="">any</option>{% for c in categories %}<option value="{{ c }}"{% if c == category %} selected{% endif %}>{{ c }}</option>{% endfor %}</select></label>
  <label>Meeting id <input type="number" name="meeting_id" value="{{ meeting_id or '' }}"></label>
  <button type="submit">Filter</button>
  <a href="{{ url_for('admin_transcripts.review_discrepancies', state=state) }}">Reset</a>
</form>
{% endif %}
{% if state == 'held' %}
  <section class="cal-panel">
  {% if not held %}<p class="t-meta">No transcripts held for review or failed.</p>{% else %}
    <table class="queue-table"><thead><tr><th>Meeting</th><th>Status</th><th>Reason</th><th>Error</th><th>Actions</th></tr></thead><tbody>
    {% for t in held %}<tr>
      <td><a href="/al/{{ t.municipality_slug }}/meetings/{{ t.meeting_id }}/">{{ t.meeting_title }}</a> <span class="t-meta">{{ t.meeting_date | format_date }}</span></td>
      <td>{{ t.status }}</td><td><code>{{ t.needs_review_reason or '' }}</code></td>
      <td class="t-mono" style="font-size: 12px;">{{ (t.last_error or '') | truncate(160) }}</td>
      <td><form method="post" action="{{ url_for('admin_transcripts.retry_transcript', meeting_id=t.meeting_id) }}" style="display:inline;">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button type="submit" style="font-size: 0.85rem;">Retry</button></form>
          <a href="{{ url_for('admin_transcripts.speaker_correction', meeting_id=t.meeting_id) }}" style="font-size: 0.85rem; margin-left: 6px;">Fix speakers</a></td>
    </tr>{% endfor %}</tbody></table>
  {% endif %}
  </section>
{% elif not rows %}
  <section class="cal-panel"><h2>Empty</h2><p class="t-meta">No {{ state.replace('_', ' ') }} discrepancies match.</p></section>
{% else %}
  <section class="cal-panel">
    <table class="queue-table discrepancy-queue">
      <thead><tr><th>Discrepancy</th><th>On video</th><th>In the minutes</th><th>Actions</th></tr></thead>
      <tbody>{% for row in rows %}{% include 'admin/_discrepancy_row.html' %}{% endfor %}</tbody>
    </table>
    {% if next_offset is not none %}
      <nav class="queue-pager"><a href="{{ url_for('admin_transcripts.review_discrepancies', state=state, category=category or none, meeting_id=meeting_id or none, offset=next_offset) }}">Load more →</a></nav>
    {% endif %}
  </section>
{% endif %}
<style>
  .discrepancy-queue td { vertical-align: top; }
  .discrepancy-queue blockquote { margin: 4px 0; padding-left: 8px; border-left: 3px solid var(--color-rule, #ddd); font-size: 13px; }
  .discrepancy-queue .chip { display: inline-block; padding: 1px 6px; border-radius: 10px; font-size: 11px; border: 1px solid var(--color-rule, #ddd); margin-right: 4px; }
  .discrepancy-queue .chip.material { font-weight: 700; }
  .discrepancy-queue details { margin-top: 6px; }
  .discrepancy-queue textarea, .discrepancy-queue input[type=text] { width: 100%; font-size: 13px; }
</style>
{% endblock %}
```

`admin/_discrepancy_row.html`:

```html
<tr id="disc-{{ row.id }}">
  <td style="max-width: 320px;">
    <span class="chip {{ row.severity }}">{{ row.severity }}</span><span class="chip">{{ row.category }}</span>
    {% if row.origin == 'model_initiated' %}<span class="chip">hunter</span>{% endif %}
    {% if row.previous_review_state %}<span class="chip">re-review (was {{ row.previous_review_state }})</span>{% endif %}
    <div><strong>{{ row.display_title }}</strong></div>
    <div class="t-meta">{{ row.display_description }}</div>
    <div class="t-meta" style="margin-top: 4px;">
      <a href="/al/{{ row.municipality_slug }}/meetings/{{ row.meeting_id }}/">{{ row.meeting_title }}</a> · {{ row.meeting_date | format_date }}
      {% if row.item_number %}· Item {{ row.item_number }}{% endif %}
      · confidence {{ '%.2f' | format(row.confidence or 0) }} · citation {{ row.citation_match }} · #{{ row.id }}
    </div>
  </td>
  <td style="max-width: 300px;">
    {% if row.transcript_excerpt %}<blockquote>{{ row.transcript_excerpt }}</blockquote>{% else %}<span class="t-meta">no transcript excerpt</span>{% endif %}
    {% if row.transcript_start_s is not none %}
      <span class="t-mono t-meta">{{ row.transcript_start_s | format_timestamp }}</span>
      · <a href="/al/{{ row.municipality_slug }}/meetings/{{ row.meeting_id }}/transcript/">transcript</a>
      {% set ch = chapter_url(row.video_url, row.item_external_id) %}{% if ch %} · <a href="{{ ch }}" target="_blank" rel="noreferrer">video chapter ↗</a>{% endif %}
    {% endif %}
  </td>
  <td style="max-width: 300px;">
    {% if row.minutes_excerpt %}<blockquote>{{ row.minutes_excerpt }}</blockquote>{% else %}<span class="t-meta">no minutes excerpt</span>{% endif %}
    {% if row.minutes_page %}<span class="t-meta">p. {{ row.minutes_page }}</span>{% endif %}
    {% if row.minutes_url %} · <a href="{{ row.minutes_url }}" target="_blank" rel="noreferrer">minutes ↗</a>{% endif %}
  </td>
  <td style="min-width: 220px;">
    {% if row.review_state == 'proposed' %}
      <form method="post" action="{{ url_for('admin_transcripts.approve', discrepancy_id=row.id) }}" style="display:inline;">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <button type="submit" style="font-size: 0.85rem;"{% if row.citation_match == 'missing' %} disabled title="Attach a citation first (edit below)"{% endif %}>Approve</button>
      </form>
      <details><summary style="font-size: 0.85rem;">Reject</summary>
        <form method="post" action="{{ url_for('admin_transcripts.reject', discrepancy_id=row.id) }}">
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
          <input type="text" name="reason" placeholder="Reason (required)" required>
          <button type="submit" style="font-size: 0.85rem;">Reject</button>
        </form></details>
      <details><summary style="font-size: 0.85rem;">Edit, then approve</summary>
        <form method="post" action="{{ url_for('admin_transcripts.edit_approve', discrepancy_id=row.id) }}">
          <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
          <input type="text" name="admin_title" value="{{ row.admin_title or row.title }}">
          <textarea name="admin_description" rows="3">{{ row.admin_description or row.description }}</textarea>
          {% if row.citation_match == 'missing' %}
            <p class="t-meta">This row has no verified citation. Paste the exact words from each side; the guard must find them.</p>
            <input type="text" name="transcript_excerpt" placeholder="Transcript excerpt (as written in the transcript)">
            <input type="text" name="minutes_excerpt" placeholder="Minutes excerpt (as written in the minutes)">
          {% endif %}
          <p class="t-meta">This changes only what docket.pub shows. The model's title and description are kept.</p>
          <button type="submit" style="font-size: 0.85rem;">Save and approve</button>
        </form></details>
    {% else %}
      <span class="t-meta">{{ row.review_state }}{% if row.reviewed_by %} by {{ row.reviewed_by }}{% endif %}{% if row.reject_reason %}: {{ row.reject_reason }}{% endif %}</span>
    {% endif %}
  </td>
</tr>
```

The "Fix speakers" link resolves to `admin_transcripts.speaker_correction` which Task 15 adds; until then leave it out of the held tab or Jinja raises `BuildError`. Add it in Task 15 Step 5.

Add `<a href="{{ url_for('admin_transcripts.review_discrepancies') }}">Minutes vs. video</a> &middot;` to the nav `<p>` in `admin/ai_panel.html` and `admin/members.html`.

- [ ] **Step 8: Run to verify pass**

Run: `venv/bin/python -m pytest tests/unit/test_csrf.py tests/integration/test_admin_discrepancies.py tests/integration/test_admin_queues.py tests/integration/test_auth_session.py -v`
Expected: all PASS (existing admin tests unaffected: the CSRF check is scoped to the new blueprint).

- [ ] **Step 9: Commit**

```bash
git add src/docket/web/csrf.py src/docket/services/discrepancies.py src/docket/web/admin_transcripts.py src/docket/web/__init__.py src/docket/web/templates/admin/review_discrepancies.html src/docket/web/templates/admin/_discrepancy_row.html src/docket/web/templates/admin/ai_panel.html src/docket/web/templates/admin/members.html tests/unit/test_csrf.py tests/integration/test_admin_discrepancies.py
git -c user.email=hello@docket.pub commit -m "feat(admin): minutes-vs-video review queue with CSRF, citation and stale guards

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 15: Admin speaker correction

**Files:**
- Create: `src/docket/services/speaker_correction.py`, `src/docket/web/templates/admin/speaker_correction.html`
- Modify: `src/docket/web/admin_transcripts.py` (three routes), `src/docket/web/templates/admin/review_discrepancies.html` (held tab link)
- Test: `tests/integration/test_admin_speakers.py`

**Interfaces:**
- Consumes: `speakers.roster_for_meeting` (Task 6), `docket.services.transcripts.speaker_ordinals`.
- Produces:
  - `list_clusters(meeting_id) -> list[dict]` — per `transcript_speakers` row: `cluster_label, ordinal, council_member_id, member_name, display_name, role, confidence, method, is_manual, needs_review, speaking_s, utterances, samples: list[dict(seq, start_s, text)]` (first, middle, last utterance of six words or more), ordered by ordinal.
  - `roster_options(meeting_id) -> list[dict(id, name)]`.
  - `reassign(meeting_id, cluster_label, *, council_member_id: int | None, display_name: str | None, role: str, actor: str) -> None` — sets `is_manual = TRUE, method = 'manual', confidence = 1.0, needs_review = FALSE`; `ValueError` for a member not on that meeting's roster or an unknown role; `LookupError` for an unknown cluster.
  - `release(meeting_id, cluster_label) -> None` — `is_manual = FALSE, needs_review = TRUE` so the next stage run may re-resolve it.
  - Routes: `GET /admin/transcripts/<meeting_id>/speakers` (`admin_transcripts.speaker_correction`), `POST /admin/transcripts/<meeting_id>/speakers/<cluster_label>` (`.reassign_speaker`), `POST /admin/transcripts/<meeting_id>/speakers/<cluster_label>/release` (`.release_speaker`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_admin_speakers.py
import pytest

from docket.config import DATABASE_URL
from docket.db import db_cursor
from docket.services import speaker_correction as SC
from docket.web import create_app
from tests.support.transcript_fixtures import install_bundle, load_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)
TOK = "test-csrf-token"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True
    return a


@pytest.fixture
def admin(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s["admin_user"] = "tester"; s["csrf_token"] = TOK
    return c


@pytest.fixture
def inst():
    i = install_bundle(load_bundle("transcript_2543"), status="speakers_resolved")
    yield i
    i.cleanup()


def _row(mid, label):
    with db_cursor() as cur:
        cur.execute("SELECT council_member_id, display_name, role, confidence, method, is_manual, needs_review FROM transcript_speakers WHERE meeting_id=%s AND cluster_label=%s",
                    [mid, label])
        return dict(cur.fetchone())


def test_page_lists_every_cluster_with_samples_and_roster(admin, inst):
    clusters = SC.list_clusters(inst.meeting_id)
    assert len(clusters) >= 20 and clusters[0]["ordinal"] == 1
    assert all(1 <= len(c["samples"]) <= 3 for c in clusters if c["utterances"])
    html = admin.get(f"/admin/transcripts/{inst.meeting_id}/speakers").get_data(as_text=True)
    for c in clusters:
        assert f"Speaker {c['ordinal']}" in html and c["cluster_label"] in html
    assert "<option" in html and any(m["name"] in html for m in SC.roster_options(inst.meeting_id))


def test_reassign_two_clusters_to_one_member_sets_manual(admin, inst):
    labels = [c["cluster_label"] for c in SC.list_clusters(inst.meeting_id)][:2]
    member = SC.roster_options(inst.meeting_id)[0]
    for l in labels:
        r = admin.post(f"/admin/transcripts/{inst.meeting_id}/speakers/{l}",
                       data={"csrf_token": TOK, "council_member_id": member["id"], "role": "council"})
        assert r.status_code in (302, 303)
    for l in labels:
        row = _row(inst.meeting_id, l)
        assert row["council_member_id"] == member["id"] and row["is_manual"] and row["method"] == "manual"
        assert row["confidence"] == 1.0 and row["needs_review"] is False and row["display_name"] == member["name"]


def test_free_text_name_for_non_council_and_release(admin, inst):
    label = SC.list_clusters(inst.meeting_id)[3]["cluster_label"]
    r = admin.post(f"/admin/transcripts/{inst.meeting_id}/speakers/{label}",
                   data={"csrf_token": TOK, "council_member_id": "", "display_name": "City Attorney", "role": "attorney"})
    assert r.status_code in (302, 303)
    row = _row(inst.meeting_id, label)
    assert (row["display_name"], row["role"], row["is_manual"], row["council_member_id"]) == ("City Attorney", "attorney", True, None)
    r = admin.post(f"/admin/transcripts/{inst.meeting_id}/speakers/{label}/release", data={"csrf_token": TOK})
    assert r.status_code in (302, 303)
    row = _row(inst.meeting_id, label)
    assert row["is_manual"] is False and row["needs_review"] is True and row["display_name"] == "City Attorney"


def test_member_outside_roster_and_bad_role_are_400(admin, inst):
    label = SC.list_clusters(inst.meeting_id)[0]["cluster_label"]
    assert admin.post(f"/admin/transcripts/{inst.meeting_id}/speakers/{label}",
                      data={"csrf_token": TOK, "council_member_id": 999999, "role": "council"}).status_code == 400
    assert admin.post(f"/admin/transcripts/{inst.meeting_id}/speakers/{label}",
                      data={"csrf_token": TOK, "display_name": "X", "role": "wizard"}).status_code == 400
    assert admin.post(f"/admin/transcripts/{inst.meeting_id}/speakers/NOPE", data={"csrf_token": TOK, "display_name": "X", "role": "staff"}).status_code == 404
    assert admin.post(f"/admin/transcripts/{inst.meeting_id}/speakers/{label}", data={"display_name": "X", "role": "staff"}).status_code == 400  # CSRF


def test_transcript_page_shows_the_corrected_name(admin, inst):
    c = SC.list_clusters(inst.meeting_id)[0]
    SC.reassign(inst.meeting_id, c["cluster_label"], council_member_id=None, display_name="Zelda Testname", role="staff", actor="t")
    html = admin.get(f"/al/birmingham/meetings/{inst.meeting_id}/transcript/").get_data(as_text=True)
    assert "Zelda Testname" in html
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/integration/test_admin_speakers.py -v`
Expected: FAIL, `ModuleNotFoundError: docket.services.speaker_correction`.

- [ ] **Step 3: Write the service**

```python
# src/docket/services/speaker_correction.py
"""Admin speaker correction: the manual shield for transcript_speakers (spec Section 5)."""
from __future__ import annotations

import logging

from docket.ai.transcripts.speakers import roster_for_meeting
from docket.db import db_cursor
from docket.services.transcripts import speaker_ordinals

log = logging.getLogger(__name__)
ROLES = ("council", "mayor", "clerk", "attorney", "staff", "public", "unknown")


def roster_options(meeting_id: int) -> list[dict]:
    return [{"id": m.id, "name": m.name} for m in roster_for_meeting(meeting_id)]


def list_clusters(meeting_id: int) -> list[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT id FROM transcripts WHERE meeting_id = %s", [meeting_id])
        t = cur.fetchone()
        if not t:
            return []
        tid = t["id"]
        cur.execute(
            """WITH utt AS (
                   SELECT s.cluster_label, s.seq, s.start_s, s.text, s.end_s - s.start_s AS dur,
                          row_number() OVER (PARTITION BY s.cluster_label ORDER BY s.seq) AS rn,
                          count(*) OVER (PARTITION BY s.cluster_label) AS n
                     FROM transcript_segments s
                    WHERE s.transcript_id = %s AND s.is_silence = FALSE AND s.text <> ''
               )
               SELECT sp.cluster_label, sp.council_member_id, cm.name AS member_name, sp.display_name, sp.role, sp.confidence,
                      sp.method, sp.is_manual, sp.needs_review,
                      COALESCE((SELECT sum(dur) FROM utt WHERE utt.cluster_label = sp.cluster_label), 0) AS speaking_s,
                      COALESCE((SELECT max(n) FROM utt WHERE utt.cluster_label = sp.cluster_label), 0) AS utterances,
                      COALESCE((SELECT json_agg(json_build_object('seq', u.seq, 'start_s', u.start_s, 'text', u.text) ORDER BY u.seq)
                                  FROM utt u WHERE u.cluster_label = sp.cluster_label
                                   AND array_length(regexp_split_to_array(u.text, '\s+'), 1) >= 6
                                   AND u.rn IN (1, (u.n + 1) / 2, u.n)), '[]'::json) AS samples
                 FROM transcript_speakers sp
                 LEFT JOIN council_members cm ON cm.id = sp.council_member_id
                WHERE sp.meeting_id = %s""",
            [tid, meeting_id],
        )
        rows = [dict(r) for r in cur.fetchall()]
    ords = speaker_ordinals(tid)
    for r in rows:
        r["ordinal"] = ords.get(r["cluster_label"], 0)
        r["samples"] = list(r["samples"] or [])[:3]
    rows.sort(key=lambda r: (r["ordinal"] == 0, r["ordinal"], r["cluster_label"]))
    return rows


def reassign(meeting_id: int, cluster_label: str, *, council_member_id: int | None, display_name: str | None,
             role: str, actor: str) -> None:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    name = (display_name or "").strip() or None
    if council_member_id is not None:
        match = next((m for m in roster_for_meeting(meeting_id) if m.id == council_member_id), None)
        if match is None:
            raise ValueError("council member is not on this meeting's roster")
        name, role = match.name, "council"
    elif not name:
        raise ValueError("a council member or a display name is required")
    with db_cursor() as cur:
        cur.execute("""UPDATE transcript_speakers
                          SET council_member_id = %s, display_name = %s, role = %s, confidence = 1.0, method = 'manual',
                              is_manual = TRUE, needs_review = FALSE
                        WHERE meeting_id = %s AND cluster_label = %s""",
                    [council_member_id, name, role, meeting_id, cluster_label])
        if cur.rowcount == 0:
            raise LookupError(cluster_label)
    log.info("speaker correction: meeting %s cluster %s -> %s (%s) by %s", meeting_id, cluster_label, name, role, actor)


def release(meeting_id: int, cluster_label: str) -> None:
    with db_cursor() as cur:
        cur.execute("""UPDATE transcript_speakers SET is_manual = FALSE, needs_review = TRUE
                        WHERE meeting_id = %s AND cluster_label = %s""", [meeting_id, cluster_label])
        if cur.rowcount == 0:
            raise LookupError(cluster_label)
```

- [ ] **Step 4: Routes (append to `admin_transcripts.py`)**

```python
from docket.services import speaker_correction as SC


@bp.route("/transcripts/<int:meeting_id>/speakers")
def speaker_correction(meeting_id: int):
    clusters = SC.list_clusters(meeting_id)
    if not clusters:
        abort(404)
    with db_cursor() as cur:
        cur.execute("""SELECT m.id, m.title, m.meeting_date, mu.slug FROM meetings m JOIN municipalities mu ON mu.id = m.municipality_id
                        WHERE m.id = %s""", [meeting_id])
        meeting = dict(cur.fetchone())
    return render_template("admin/speaker_correction.html", meeting=meeting, clusters=clusters,
                           roster=SC.roster_options(meeting_id), roles=SC.ROLES)


@bp.post("/transcripts/<int:meeting_id>/speakers/<cluster_label>")
def reassign_speaker(meeting_id: int, cluster_label: str):
    member = request.form.get("council_member_id", type=int)
    try:
        SC.reassign(meeting_id, cluster_label, council_member_id=member, display_name=request.form.get("display_name"),
                    role=request.form.get("role", "unknown"), actor=session.get("admin_user", "unknown"))
    except ValueError as e:
        abort(400, str(e))
    except LookupError:
        abort(404)
    flash(f"Cluster {cluster_label} reassigned.")
    return redirect(url_for("admin_transcripts.speaker_correction", meeting_id=meeting_id))


@bp.post("/transcripts/<int:meeting_id>/speakers/<cluster_label>/release")
def release_speaker(meeting_id: int, cluster_label: str):
    try:
        SC.release(meeting_id, cluster_label)
    except LookupError:
        abort(404)
    flash(f"Cluster {cluster_label} released; the next speaker run may re-resolve it.")
    return redirect(url_for("admin_transcripts.speaker_correction", meeting_id=meeting_id))
```

Add `from docket.db import db_cursor` at the top of the blueprint.

- [ ] **Step 5: Template and the held-tab link**

`admin/speaker_correction.html`:

```html
{% extends "base.html" %}
{% block title %}Speakers — {{ meeting.title }} — Admin — docket.pub{% endblock %}
{% block content %}
<h1>Speakers: {{ meeting.title }} <span class="t-meta">{{ meeting.meeting_date | format_date }}</span></h1>
<p><a href="{{ url_for('admin_transcripts.review_discrepancies') }}">← Minutes vs. video queue</a> &middot;
   <a href="/al/{{ meeting.slug }}/meetings/{{ meeting.id }}/transcript/">Public transcript</a></p>
<p class="t-meta">One row per diarization cluster. Assigning two clusters to the same person merges a fragmented speaker.
   Saving locks the row (manual); the pipeline never overwrites a locked row. Release to let the next run try again.</p>
{% with messages = get_flashed_messages() %}{% if messages %}<ul class="queue-flash">{% for m in messages %}<li>{{ m }}</li>{% endfor %}</ul>{% endif %}{% endwith %}
<section class="cal-panel">
<table class="queue-table">
  <thead><tr><th>Cluster</th><th>Resolved as</th><th>Samples</th><th>Reassign</th></tr></thead>
  <tbody>
  {% for c in clusters %}
  <tr>
    <td><strong>Speaker {{ c.ordinal }}</strong><div class="t-mono t-meta">{{ c.cluster_label }} · {{ c.speaking_s | round }} s · {{ c.utterances }} turns</div></td>
    <td>{{ c.member_name or c.display_name or '—' }}<div class="t-meta">{{ c.role or 'unknown' }} · {{ '%.2f' | format(c.confidence or 0) }} · {{ c.method or 'unresolved' }}
        {% if c.is_manual %}· <strong>manual</strong>{% endif %}{% if c.needs_review %}· needs review{% endif %}</div></td>
    <td style="max-width: 360px;">{% for s in c.samples %}<blockquote class="t-meta" style="margin: 2px 0;"><span class="t-mono">{{ s.start_s | format_timestamp }}</span> {{ s.text | truncate(180) }}</blockquote>{% endfor %}</td>
    <td>
      <form method="post" action="{{ url_for('admin_transcripts.reassign_speaker', meeting_id=meeting.id, cluster_label=c.cluster_label) }}">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <select name="council_member_id"><option value="">— not a council member —</option>
          {% for m in roster %}<option value="{{ m.id }}"{% if m.id == c.council_member_id %} selected{% endif %}>{{ m.name }}</option>{% endfor %}</select>
        <input type="text" name="display_name" placeholder="or a name (City Attorney, Clerk)" value="{{ '' if c.council_member_id else (c.display_name or '') }}">
        <select name="role">{% for r in roles %}<option value="{{ r }}"{% if r == (c.role or 'unknown') %} selected{% endif %}>{{ r }}</option>{% endfor %}</select>
        <button type="submit" style="font-size: 0.85rem;">Save</button>
      </form>
      {% if c.is_manual %}
      <form method="post" action="{{ url_for('admin_transcripts.release_speaker', meeting_id=meeting.id, cluster_label=c.cluster_label) }}" style="margin-top: 4px;">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"><button type="submit" style="font-size: 0.85rem;">Release</button>
      </form>
      {% endif %}
    </td>
  </tr>
  {% endfor %}
  </tbody>
</table>
</section>
{% endblock %}
```

In `admin/review_discrepancies.html`'s held tab, add the "Fix speakers" link (Task 14 left it out), and add a per-row link in `_discrepancy_row.html`'s meeting line: `· <a href="{{ url_for('admin_transcripts.speaker_correction', meeting_id=row.meeting_id) }}">speakers</a>`.

- [ ] **Step 6: Run to verify pass**

Run: `venv/bin/python -m pytest tests/integration/test_admin_speakers.py tests/integration/test_admin_discrepancies.py tests/integration/test_speaker_stage.py -v`
Expected: all PASS (`test_manual_rows_are_never_overwritten` in the stage tests is the other half of this shield).

- [ ] **Step 7: Commit**

```bash
git add src/docket/services/speaker_correction.py src/docket/web/admin_transcripts.py src/docket/web/templates/admin/speaker_correction.html src/docket/web/templates/admin/review_discrepancies.html src/docket/web/templates/admin/_discrepancy_row.html tests/integration/test_admin_speakers.py
git -c user.email=hello@docket.pub commit -m "feat(admin): speaker correction page with manual shield and release

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 16: Public "Minutes vs. Video" block, listing page, methodology section, and the speaker index

**Files:**
- Create: `src/docket/web/templates/partials/minutes_vs_video.html`, `src/docket/web/templates/minutes_vs_video.html`
- Modify: `src/docket/web/__init__.py:55-57` (flag), `src/docket/web/public.py` (`meeting_detail`, `item_detail`, `meeting_transcript`, new `minutes_vs_video_index`), `src/docket/web/templates/meeting_detail.html:241-246`, `item_detail.html:104-105`, `transcript.html`, `about_methodology.html`, `src/docket/services/transcripts.py` (`speaker_index`)
- Test: `tests/integration/test_minutes_vs_video_public.py`

**Interfaces:**
- Consumes: `discrepancies.list_public_for_meeting`, `list_public_for_item`, `list_public_recent` (Task 14); `chapter_url`; `format_timestamp`, `format_date`.
- Produces:
  - `app.config["MINUTES_VS_VIDEO_UI"]` from env `MINUTES_VS_VIDEO_UI` (`"true"` enables; default off). Templates read `config.MINUTES_VS_VIDEO_UI`.
  - `GET /minutes-vs-video/` (`public.minutes_vs_video_index`), 404 while the flag is off; `?offset=` pagination of 50.
  - `partials/minutes_vs_video.html` expects `discrepancies` (list from the services above), `municipality`, and optional `block_context` (`"meeting"` or `"item"`).
  - `docket.services.transcripts.speaker_index(transcript_id) -> list[dict(name, member_id, turns, seconds, cluster_labels)]` — resolved speakers only (manual, or confidence ≥ `SPEAKER_CONFIDENCE_FLOOR`), one entry per name, ordered by seconds descending.
  - `transcript.html` hero gains a "Who spoke" list linking each name to `/search?city=<slug>&q=speaker:"<name>"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_minutes_vs_video_public.py
import pytest

from docket.config import DATABASE_URL
from docket.db import db_cursor
from docket.services import transcripts as tsvc
from docket.web import create_app
from tests.integration.test_admin_discrepancies import _disc
from tests.support.transcript_fixtures import install_bundle, load_bundle, pilot_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)
HONESTY = "The minutes remain the official record"


@pytest.fixture
def app():
    a = create_app(); a.config["TESTING"] = True
    return a


@pytest.fixture
def pilot():
    i = install_bundle(pilot_bundle(), external_id="999015", status="compared")
    yield i
    i.cleanup()


def test_flag_off_hides_block_and_listing(app, pilot):
    app.config["MINUTES_VS_VIDEO_UI"] = False
    _disc(pilot, review_state="approved")
    c = app.test_client()
    html = c.get(f"/al/birmingham/meetings/{pilot.meeting_id}/").get_data(as_text=True)
    assert "Minutes vs. video" not in html and "Different statutory ground" not in html
    assert c.get("/minutes-vs-video/").status_code == 404


def test_flag_on_renders_only_approved_rows_with_honesty_copy(app, pilot):
    app.config["MINUTES_VS_VIDEO_UI"] = True
    _disc(pilot, review_state="approved", admin_title="Statutory ground differs (edited)")
    _disc(pilot, review_state="proposed", title="Proposed one", tseq=2, mseq=2)
    _disc(pilot, review_state="stale", title="Stale one", tseq=3, mseq=3)
    c = app.test_client()
    html = c.get(f"/al/birmingham/meetings/{pilot.meeting_id}/").get_data(as_text=True)
    assert "Minutes vs. video" in html and "Statutory ground differs (edited)" in html
    assert "Proposed one" not in html and "Stale one" not in html
    assert "we will go into executive session" in html and "go into Executive Session" in html
    assert HONESTY in html and "/about/how-we-read-minutes/" in html and "reviewed by a person" in html
    assert "p. 12" in html and "00:56:40" in html
    item_html = c.get(f"/al/birmingham/items/{pilot.item_ids[1501]}/").get_data(as_text=True)
    assert "Statutory ground differs (edited)" in item_html and "Proposed one" not in item_html
    listing = c.get("/minutes-vs-video/").get_data(as_text=True)
    assert "Statutory ground differs (edited)" in listing and HONESTY in listing


def test_flag_on_with_nothing_approved_renders_no_section(app, pilot):
    app.config["MINUTES_VS_VIDEO_UI"] = True
    _disc(pilot, review_state="proposed")
    html = app.test_client().get(f"/al/birmingham/meetings/{pilot.meeting_id}/").get_data(as_text=True)
    assert "Minutes vs. video" not in html


def test_speaker_index_merges_clusters_by_person_and_links_search(app):
    inst = install_bundle(load_bundle("transcript_2543"), status="speakers_resolved")
    try:
        with db_cursor() as cur:
            cur.execute("SELECT cluster_label FROM transcript_speakers WHERE meeting_id=%s ORDER BY cluster_label LIMIT 3", [inst.meeting_id])
            a, b, c3 = [r["cluster_label"] for r in cur.fetchall()]
            cur.execute("SELECT id FROM council_members WHERE id = ANY(%s) AND name NOT LIKE %s ORDER BY id LIMIT 1",
                        [list(inst.member_ids.values()), "%''%"])      # autoescape would turn an apostrophe into &#39;
            member = cur.fetchone()["id"]
            cur.execute("""UPDATE transcript_speakers SET council_member_id=%s, confidence=0.75, method='roll_call' WHERE meeting_id=%s AND cluster_label=%s""",
                        [member, inst.meeting_id, a])
            cur.execute("""UPDATE transcript_speakers SET council_member_id=%s, confidence=1.0, method='manual', is_manual=TRUE WHERE meeting_id=%s AND cluster_label=%s""",
                        [member, inst.meeting_id, b])                                              # Review Focus 4: one by model, one by hand
            cur.execute("""UPDATE transcript_speakers SET display_name='Low Conf', confidence=0.4, method='llm_inference' WHERE meeting_id=%s AND cluster_label=%s""",
                        [inst.meeting_id, c3])
            cur.execute("SELECT name FROM council_members WHERE id=%s", [member]); name = cur.fetchone()["name"]
        idx = tsvc.speaker_index(inst.transcript_id)
        assert [e["name"] for e in idx] == [name]                      # merged, low-confidence cluster excluded
        assert set(idx[0]["cluster_labels"]) == {a, b} and idx[0]["turns"] > 0
        html = app.test_client().get(f"/al/birmingham/meetings/{inst.meeting_id}/transcript/").get_data(as_text=True)
        assert "Who spoke" in html and html.count(f">{name}<") >= 1
        assert f'/search?city=birmingham&amp;q=speaker%3A%22{name.replace(" ", "+")}%22' in html or f'speaker:&#34;{name}&#34;' in html
        search = app.test_client().get(f'/search?city=birmingham&q=speaker:"{name}"').get_data(as_text=True)
        assert "From transcripts" in search
    finally:
        inst.cleanup()


def test_methodology_page_describes_transcripts_and_comparison(app):
    html = app.test_client().get("/about/how-we-read-minutes/").get_data(as_text=True)
    assert "Transcripts" in html and "Minutes vs. video" in html and HONESTY in html
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/integration/test_minutes_vs_video_public.py -v`
Expected: FAIL (`AttributeError: speaker_index`, 404 on the listing, missing copy).

- [ ] **Step 3: Flag, service, routes**

In `src/docket/web/__init__.py` next to `SMART_BREVITY_UI`:

```python
    # Spec 2026-10-05 ship gate: the public "Minutes vs. Video" block stays off until
    # >= 70% of material candidates are approved; the operator flips this by hand.
    app.config["MINUTES_VS_VIDEO_UI"] = (
        os.environ.get("MINUTES_VS_VIDEO_UI", "").strip().lower() == "true"
    )
```

Append to `src/docket/services/transcripts.py`:

```python
def speaker_index(transcript_id: int) -> list[dict]:
    """Resolved speakers for the 'Who spoke' list, merged by person across clusters."""
    with db_cursor() as cur:
        cur.execute(
            """SELECT COALESCE(cm.name, sp.display_name) AS name, sp.council_member_id AS member_id,
                      array_agg(DISTINCT sp.cluster_label) AS cluster_labels,
                      count(*) AS turns, COALESCE(sum(s.end_s - s.start_s), 0) AS seconds
                 FROM transcript_segments s
                 JOIN transcript_speakers sp ON sp.id = s.speaker_id
                 LEFT JOIN council_members cm ON cm.id = sp.council_member_id
                WHERE s.transcript_id = %s AND s.is_silence = FALSE
                  AND COALESCE(cm.name, sp.display_name) IS NOT NULL
                  AND (sp.is_manual OR sp.confidence >= %s)
                GROUP BY 1, 2
                ORDER BY seconds DESC, name""",
            [transcript_id, SPEAKER_CONFIDENCE_FLOOR],
        )
        return [dict(r) for r in cur.fetchall()]
```

In `public.py`:

- `meeting_detail`: after `has_transcript`, add `discrepancies = dsvc.list_public_for_meeting(meeting_id) if current_app.config.get("MINUTES_VS_VIDEO_UI") else []` (import `from docket.services import discrepancies as dsvc` and `current_app`) and pass `discrepancies=discrepancies`.
- `item_detail`: `item_discrepancies = dsvc.list_public_for_item(item_id) if current_app.config.get("MINUTES_VS_VIDEO_UI") else []`, pass it.
- `meeting_transcript`: add `speakers=tsvc.speaker_index(transcript.id)` to `ctx`.
- New route:

```python
@bp.route("/minutes-vs-video/")
def minutes_vs_video_index():
    """Every approved discrepancy, newest meeting first (spec Section 5). Behind the ship-gate flag."""
    if not current_app.config.get("MINUTES_VS_VIDEO_UI"):
        abort(404)
    from docket.services import discrepancies as dsvc
    offset = max(0, request.args.get("offset", 0, type=int))
    rows = dsvc.list_public_recent(limit=51, offset=offset)
    return render_template("minutes_vs_video.html", rows=rows[:50],
                           next_offset=offset + 50 if len(rows) > 50 else None)
```

- [ ] **Step 4: Templates**

`partials/minutes_vs_video.html`:

```html
{# Public "Minutes vs. Video" block. Only review_state = 'approved' rows reach this template
   (services.discrepancies.list_public_*), and only while config.MINUTES_VS_VIDEO_UI is on. #}
{% if discrepancies %}
<section class="feed minutes-vs-video" id="minutes-vs-video">
  <header class="feed-head"><div>
    <div class="t-eyebrow">Minutes vs. video</div>
    <h2 class="feed-title t-display" style="font-size: 24px;">Where the official minutes and the recording differ</h2>
  </div></header>
  <p class="t-meta">docket.pub compared a machine transcript of the meeting video with the adopted minutes. Each difference below was
     reviewed by a person before it appeared here. The minutes remain the official record; the transcript is machine-generated and can be wrong.
     <a class="link" href="/about/how-we-read-minutes/">How we read meetings</a>.</p>
  <ol class="mvv-list" style="list-style: none; padding: 0;">
  {% for d in discrepancies %}
    <li class="mvv-row" id="mvv-{{ d.id }}" style="padding: 12px 0; border-top: 1px solid var(--color-rule, #e5e5e5);">
      <div class="t-meta"><span class="chip">{{ d.category.replace('_', ' ') }}</span> <span class="chip{% if d.severity == 'material' %} is-accent{% endif %}">{{ d.severity }}</span>
        {% if block_context != 'meeting' %}· <a class="link" href="/al/{{ d.municipality_slug }}/meetings/{{ d.meeting_id }}/">{{ d.meeting_title }}</a> · {{ d.meeting_date | format_date }}{% endif %}
        {% if d.item_number and block_context != 'item' %}· <a class="link" href="/al/{{ d.municipality_slug }}/items/{{ d.agenda_item_id }}/">Item {{ d.item_number }}</a>{% endif %}</div>
      <h3 style="margin: 4px 0;">{{ d.display_title }}</h3>
      <p>{{ d.display_description }}</p>
      <div class="mvv-sides" style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
        <div><div class="t-eyebrow">On the video</div>
          {% if d.transcript_excerpt %}<blockquote>{{ d.transcript_excerpt }}</blockquote>{% endif %}
          {% if d.transcript_start_s is not none %}<a class="link t-mono" href="/al/{{ d.municipality_slug }}/meetings/{{ d.meeting_id }}/transcript/">{{ d.transcript_start_s | format_timestamp }} in the transcript</a>
            {% set ch = chapter_url(d.video_url, d.item_external_id) %}{% if ch %} · <a class="link" href="{{ ch }}" target="_blank" rel="noreferrer">video chapter ↗</a>{% endif %}{% endif %}</div>
        <div><div class="t-eyebrow">In the minutes</div>
          {% if d.minutes_excerpt %}<blockquote>{{ d.minutes_excerpt }}</blockquote>{% endif %}
          {% if d.minutes_page %}<span class="t-meta">p. {{ d.minutes_page }}</span>{% endif %}
          {% if d.minutes_url %} · <a class="link" href="{{ d.minutes_url }}" target="_blank" rel="noreferrer">official minutes ↗</a>{% endif %}</div>
      </div>
    </li>
  {% endfor %}
  </ol>
</section>
<style>
  .minutes-vs-video blockquote { margin: 4px 0; padding-left: 10px; border-left: 3px solid var(--color-rule, #ddd); }
  @media (max-width: 640px) { .mvv-sides { grid-template-columns: 1fr !important; } }
</style>
{% endif %}
```

`minutes_vs_video.html`:

```html
{% extends "base.html" %}
{% block title %}Minutes vs. video — docket.pub{% endblock %}
{% block content %}
<section class="hero hero--detail">
  <div class="t-eyebrow">Minutes vs. video</div>
  <h1 class="hero-title t-display">Where the official minutes and the recording differ</h1>
  <p class="hero-sub">Each entry was proposed by software comparing a machine transcript with the adopted minutes, then reviewed by a person. The minutes remain the official record. <a class="link" href="/about/how-we-read-minutes/">How we read meetings</a>.</p>
</section>
{% with discrepancies = rows, block_context = 'index' %}{% include "partials/minutes_vs_video.html" %}{% endwith %}
{% if not rows %}<section class="feed"><p class="t-meta">Nothing approved yet.</p></section>{% endif %}
{% if next_offset %}<nav class="queue-pager"><a class="link" href="{{ url_for('public.minutes_vs_video_index', offset=next_offset) }}">Older →</a></nav>{% endif %}
{% endblock %}
```

The partial's `{% if discrepancies %}` wraps the section, so the hero's honesty sentence is what carries `HONESTY` on an empty listing; keep "The minutes remain the official record" in both places.

In `meeting_detail.html`, between the Votes section's closing `{% endif %}` (line 241) and the transcript container:

```html
{# ── Minutes vs. video (approved discrepancies; behind the ship-gate flag) ── #}
{% if config.MINUTES_VS_VIDEO_UI and discrepancies %}
  {% with block_context = 'meeting' %}{% include "partials/minutes_vs_video.html" %}{% endwith %}
{% endif %}
```

In `item_detail.html` after the transcript excerpt include (line 105):

```html
{% if config.MINUTES_VS_VIDEO_UI and item_discrepancies %}
  {% with discrepancies = item_discrepancies, block_context = 'item' %}{% include "partials/minutes_vs_video.html" %}{% endwith %}
{% endif %}
```

In `transcript.html` after the `<p class="t-meta">` in the hero:

```html
  {% if speakers %}
  <div class="transcript-speakers t-meta" style="margin-top: 8px;">
    <span class="t-eyebrow">Who spoke</span>
    {% for sp in speakers %}
      <a class="link" href="/search?city={{ municipality.slug }}&q={{ ('speaker:"' ~ sp.name ~ '"') | urlencode }}" title="{{ sp.turns }} turns, {{ sp.seconds | format_timestamp }}">{{ sp.name }}</a>{% if not loop.last %} · {% endif %}
    {% endfor %}
    <span class="t-meta">· names assigned by software; <a class="link" href="/about/how-we-read-minutes/">how</a></span>
  </div>
  {% endif %}
```

In `about_methodology.html`, add a section after the "Honesty protocol" section, in the page's existing section markup:

```html
<section class="feed">
  <header class="feed-head"><div>
    <div class="t-eyebrow">Transcripts</div>
    <h2 class="feed-title t-display">Machine transcripts and "Minutes vs. video"</h2>
  </div></header>
  <p class="hero-sub">Birmingham council videos are transcribed by speech-recognition software (faster-whisper large-v3) with automatic speaker separation. Speaker names are assigned by software from roll calls, the chair addressing members, and what was said; low-confidence speakers show as "Speaker N". Every transcript page says so and links to the recording.</p>
  <p class="hero-sub">When a meeting has both a transcript and adopted minutes, software extracts a timeline of motions, votes, executive sessions, and material statements from each and compares them. Differences are proposed, then a person reads both excerpts and approves or rejects each one. Only approved differences appear in "Minutes vs. video", each with a verbatim quote from both sides. The minutes remain the official record; a transcript can mishear a word, and a difference is a reason to check the recording, not a finding of fault.</p>
</section>
```

- [ ] **Step 5: Run to verify pass**

Run: `venv/bin/python -m pytest tests/integration/test_minutes_vs_video_public.py tests/integration/test_transcript_routes.py tests/integration/test_transcript_search.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/docket/web/__init__.py src/docket/web/public.py src/docket/services/transcripts.py src/docket/web/templates/partials/minutes_vs_video.html src/docket/web/templates/minutes_vs_video.html src/docket/web/templates/meeting_detail.html src/docket/web/templates/item_detail.html src/docket/web/templates/transcript.html src/docket/web/templates/about_methodology.html tests/integration/test_minutes_vs_video_public.py
git -c user.email=hello@docket.pub commit -m "feat(web): Minutes vs. Video block and listing behind MINUTES_VS_VIDEO_UI; speaker index

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 17: Admin AI panel rows and the ship-gate readout

**Files:**
- Modify: `src/docket/web/admin.py:480` (`ai_panel`), `src/docket/web/templates/admin/ai_panel.html`
- Test: `tests/unit/test_ship_gate.py`, `tests/integration/test_admin_ai_panel_transcripts.py`

**Interfaces:**
- Consumes: `discrepancies.approval_ratio`, `ship_gate` (Task 14).
- Produces: `ai_panel` context gains `transcript_status_counts: list[dict(status, n)]`, `transcript_stage_costs: list[dict(stage, runs, cost, rows_processed, rows_failed)]` (7 days, stages `LIKE 'transcript_%'`), `citation_missing: list[dict(prompt_version, total, missing, rate)]`, `gate: dict`, `mvv_flag: bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_ship_gate.py
from docket.services.discrepancies import ship_gate


def _rows(spec):
    """spec: list of (meeting_id, state) in reviewed order."""
    return [{"meeting_id": m, "review_state": s} for m, s in spec]


def test_empty_window_is_not_met():
    g = ship_gate([])
    assert g == {"approved": 0, "rejected": 0, "total": 0, "meetings": 0, "ratio": 0.0, "window_complete": False, "gate_met": False}


def test_thirty_candidates_close_the_window_first():
    rows = _rows([(1, "approved")] * 25 + [(2, "rejected")] * 5 + [(3, "rejected")] * 20)
    g = ship_gate(rows)
    assert g["total"] == 30 and g["meetings"] == 2 and g["window_complete"]
    assert g["ratio"] == 0.833 and g["gate_met"]


def test_ten_meetings_close_the_window_first():
    rows = _rows([(m, "approved" if m % 2 else "rejected") for m in range(1, 13)])   # 12 meetings, one row each
    g = ship_gate(rows)
    assert g["meetings"] == 10 and g["total"] == 10 and g["window_complete"]
    assert g["ratio"] == 0.5 and not g["gate_met"]


def test_open_window_reports_ratio_but_not_met():
    g = ship_gate(_rows([(1, "approved")] * 9))
    assert g["ratio"] == 1.0 and not g["window_complete"] and not g["gate_met"]
```

```python
# tests/integration/test_admin_ai_panel_transcripts.py
import pytest

from docket.config import DATABASE_URL
from docket.db import db_cursor
from docket.web import create_app

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


def test_panel_shows_gate_stage_costs_and_statuses():
    app = create_app(); app.config["TESTING"] = True; app.config["MINUTES_VS_VIDEO_UI"] = False
    c = app.test_client()
    with c.session_transaction() as s:
        s["admin_user"] = "tester"
    with db_cursor() as cur:
        cur.execute("""INSERT INTO ai_runs (started_at, finished_at, stage, model, rows_processed, rows_failed, cost_usd, notes)
                       VALUES (now(), now(), 'transcript_compare', 'claude-opus-5-5', 1, 0, 0.4321, 'pytest_panel') RETURNING id""")
        rid = cur.fetchone()["id"]
    try:
        html = c.get("/admin/ai").get_data(as_text=True)
        assert "Minutes vs. video gate" in html and "flag off" in html
        assert "transcript_compare" in html and "0.4321" in html
        assert "Transcript pipeline" in html            # status table heading
        assert "citation" in html.lower()
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM ai_runs WHERE id=%s", [rid])
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/unit/test_ship_gate.py tests/integration/test_admin_ai_panel_transcripts.py -v`
Expected: unit PASS already (Task 14 shipped `ship_gate`); integration FAIL on the missing copy.

- [ ] **Step 3: Queries in `ai_panel`**

Before `render_template` in `ai_panel()`:

```python
    from docket.services import discrepancies as dsvc
    with db_cursor() as cur:
        cur.execute("SELECT status, count(*) AS n FROM transcripts GROUP BY status ORDER BY status")
        transcript_status_counts = [dict(r) for r in cur.fetchall()]
        cur.execute("""SELECT stage, count(*) AS runs, COALESCE(SUM(cost_usd), 0)::float AS cost,
                              SUM(rows_processed) AS rows_processed, SUM(rows_failed) AS rows_failed
                         FROM ai_runs WHERE stage LIKE 'transcript_%%' AND started_at > NOW() - INTERVAL '7 days'
                        GROUP BY stage ORDER BY stage""")
        transcript_stage_costs = [dict(r) for r in cur.fetchall()]
        cur.execute("""SELECT prompt_version, count(*) AS total,
                              count(*) FILTER (WHERE citation_match = 'missing') AS missing,
                              round(100.0 * count(*) FILTER (WHERE citation_match = 'missing') / count(*), 1) AS rate
                         FROM minutes_discrepancies WHERE review_state <> 'dismissed_by_model'
                        GROUP BY prompt_version ORDER BY prompt_version""")
        citation_missing = [dict(r) for r in cur.fetchall()]
    gate = dsvc.approval_ratio()
    mvv_flag = bool(current_app.config.get("MINUTES_VS_VIDEO_UI"))
```

and pass all five into the template.

- [ ] **Step 4: Template additions (`admin/ai_panel.html`, after the Recent runs table)**

```html
<h2>Minutes vs. video gate</h2>
<div class="kpi-grid" style="grid-template-columns: repeat(4, 1fr); margin-bottom: 16px;">
  <div class="kpi"><div class="kpi-label t-label">Material approved</div><div class="kpi-value t-display t-tnum">{{ gate.approved }}/{{ gate.total }}</div></div>
  <div class="kpi"><div class="kpi-label t-label">Approval ratio</div><div class="kpi-value t-display t-tnum">{{ (gate.ratio * 100) | round }}%</div></div>
  <div class="kpi"><div class="kpi-label t-label">Meetings reviewed</div><div class="kpi-value t-display t-tnum">{{ gate.meetings }}/10</div></div>
  <div class="kpi {% if gate.gate_met %}is-accent{% endif %}"><div class="kpi-label t-label">Gate</div>
    <div class="kpi-value t-display">{{ 'met' if gate.gate_met else ('open' if not gate.window_complete else 'not met') }} · {{ 'flag on' if mvv_flag else 'flag off' }}</div></div>
</div>
<p class="t-meta">Rule: at least 70% of material candidates approved over the first 10 reviewed meetings or the first 30 reviewed candidates, whichever comes first. The public block is enabled by setting <code>MINUTES_VS_VIDEO_UI=true</code> on the web service; the flip is manual.
   Citation misses above 10% over the first ten meetings mean the normalizer or prompt needs tuning before the queue is used in earnest.</p>
<table><thead><tr><th>Prompt version</th><th>Rows</th><th>Citation missing</th><th>Rate</th></tr></thead><tbody>
{% for r in citation_missing %}<tr><td>{{ r.prompt_version }}</td><td>{{ r.total }}</td><td>{{ r.missing }}</td><td>{{ r.rate }}%</td></tr>{% else %}<tr><td colspan="4" class="t-meta">No discrepancies yet.</td></tr>{% endfor %}
</tbody></table>

<h2>Transcript pipeline</h2>
<table><thead><tr><th>Status</th><th>Transcripts</th></tr></thead><tbody>
{% for r in transcript_status_counts %}<tr><td><code>{{ r.status }}</code></td><td class="t-mono">{{ r.n }}</td></tr>{% endfor %}
</tbody></table>
<table style="margin-top: 12px;"><thead><tr><th>Stage (7d)</th><th>Runs</th><th>Processed</th><th>Failed</th><th>Cost</th></tr></thead><tbody>
{% for r in transcript_stage_costs %}<tr><td><code>{{ r.stage }}</code></td><td>{{ r.runs }}</td><td>{{ r.rows_processed }}</td><td>{{ r.rows_failed }}</td><td class="t-mono">${{ "%.4f"|format(r.cost) }}</td></tr>
{% else %}<tr><td colspan="5" class="t-meta">No transcript stage runs in the last 7 days.</td></tr>{% endfor %}
</tbody></table>
<p><a href="{{ url_for('admin_transcripts.review_discrepancies') }}">Open the review queue →</a></p>
```

- [ ] **Step 5: Run to verify pass**

Run: `venv/bin/python -m pytest tests/unit/test_ship_gate.py tests/integration/test_admin_ai_panel_transcripts.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/docket/web/admin.py src/docket/web/templates/admin/ai_panel.html tests/unit/test_ship_gate.py tests/integration/test_admin_ai_panel_transcripts.py
git -c user.email=hello@docket.pub commit -m "feat(admin): AI panel shows transcript stages, citation-miss rate, and the ship gate

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 18: Haiku 4.5 extraction A/B (experiment) and the live pipeline tests

**Files:**
- Create: `src/docket/ai/transcripts/ab.py`, `scripts/transcript_extraction_ab.py`, `tests/unit/test_ab_metrics.py`, `tests/live/test_transcript_pilot_e2e.py`, `tests/live/test_transcript_chaotic.py`, `tests/live/test_transcript_ab.py`
- Modify: `src/docket/config.py` (`AI_TRANSCRIPT_AB_MODEL`), `src/docket/ai/transcripts/client.py` (`effort=None` omits the key)

**Interfaces:**
- Consumes: `events.render_transcript`, `render_agenda`, `load_segments_with_speakers`, `load_agenda` (Task 9); `EVENTS_TRANSCRIPT_SYSTEM`, `EVENTS_SCHEMA`, `EventList` (Task 2); `StructuredClient` (Task 1); `docket.ai.worker._open_run`/`_close_run`/`RunSummary`; `pipeline.run_for_meeting` (Task 12); fixture bundles (Task 3).
- Produces:
  - `AI_TRANSCRIPT_AB_MODEL = os.environ.get("AI_TRANSCRIPT_AB_MODEL", "claude-haiku-4-5-20251001")` (the id already in `PRICING`). Haiku 4.5 rejects `output_config.effort`, so `build_request(..., effort=None)` omits the key.
  - `ab.event_keys(events: list[ExtractedEvent]) -> Counter[tuple[str, frozenset[int]]]`; `ab.compare_event_lists(reference, candidate) -> dict(precision, recall, per_type_recall: dict, n_ref, n_cand)`.
  - `ab.material_labels(meeting_id) -> set[tuple[str, frozenset[int]]]` — approved `omission` discrepancies' transcript event keys (the labeled material set the spec asks for).
  - `ab.run_ab(meeting_ids: list[int], *, client, notes_prefix="ab") -> list[dict]` (per meeting: both models' metrics, cost, latency, tokens, skipped reason) and `ab.render_report(results) -> str` (markdown with the decision rule).
  - `scripts/transcript_extraction_ab.py --meetings 10 [--out PATH]`.

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/unit/test_ab_metrics.py
from collections import Counter

from docket.ai.transcripts.ab import compare_event_lists, event_keys, render_report
from docket.ai.transcripts.client import build_request
from docket.ai.transcripts.schemas import ExtractedEvent


def _ev(et, refs):
    return ExtractedEvent.model_validate({"event_type": et, "scope": "item", "agenda_item_refs": refs, "actor_text": None,
                                          "actor_member_id": None, "summary": et, "detail": {}, "segment_seq": 1, "page": None, "quote": None})


def test_event_keys_are_multisets():
    assert event_keys([_ev("motion", [1]), _ev("motion", [1]), _ev("vote", [1])]) == Counter({("motion", frozenset({1})): 2, ("vote", frozenset({1})): 1})


def test_compare_event_lists_precision_recall_and_per_type():
    ref = [_ev("motion", [1]), _ev("vote", [1]), _ev("statement", [1]), _ev("statement", [2])]
    cand = [_ev("motion", [1]), _ev("vote", [1]), _ev("statement", [1]), _ev("recess", [])]
    m = compare_event_lists(ref, cand)
    assert m["recall"] == 0.75 and m["precision"] == 0.75
    assert m["per_type_recall"]["motion"] == 1.0 and m["per_type_recall"]["statement"] == 0.5


def test_build_request_omits_effort_for_models_that_reject_it():
    req = build_request(model="claude-haiku-4-5-20251001", system="S", user="U", schema={"type": "object"}, effort=None)
    assert "effort" not in req["output_config"] and req["output_config"]["format"]["type"] == "json_schema"


def test_report_states_the_decision_rule_and_a_verdict():
    results = [{"meeting_id": 1, "haiku": {"recall": 0.95, "precision": 0.9, "per_type_recall": {"motion": 1.0, "vote": 1.0, "statement": 0.85},
                                            "cost_usd": 0.05, "latency_s": 20.0, "tokens": 40000},
                "sonnet": {"cost_usd": 0.20, "latency_s": 35.0, "tokens": 40000}, "material_recall": {"haiku": 1.0, "sonnet": 1.0}, "skipped": None}]
    text = render_report(results)
    assert "Decision rule" in text and "recall" in text and "Verdict" in text and "meeting 1" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/bin/python -m pytest tests/unit/test_ab_metrics.py -v`
Expected: FAIL (`ModuleNotFoundError: docket.ai.transcripts.ab`; the `effort=None` test fails with `"effort" in output_config`).

- [ ] **Step 3: Client and config tweaks**

In `client.build_request`, change the signature to `effort: str | None = "medium"` and build `output_config` as:

```python
    output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
    if effort is not None:
        output_config["effort"] = effort
```

(`StructuredClient.call` gets the same `effort: str | None` type.) Update the docstring: "Haiku 4.5 rejects `effort`; pass `None` for it." Add to `config.py`:

```python
AI_TRANSCRIPT_AB_MODEL: str = os.environ.get("AI_TRANSCRIPT_AB_MODEL", "claude-haiku-4-5-20251001")
```

- [ ] **Step 4: Write `ab.py`**

```python
# src/docket/ai/transcripts/ab.py
"""Haiku 4.5 vs Sonnet 5.5 event extraction A/B (spec Section 3, 'Haiku experiment').

Not a code path the pipeline uses. Runs the transcript-side extraction on
both models for N compared meetings, records each call in ai_runs (stage
transcript_ab), scores Haiku against Sonnet as the reference and both against
the labeled material set (approved omission discrepancies), and renders a
markdown report. If Haiku passes the decision rule, the operator sets
AI_TRANSCRIPT_EVENTS_MODEL; nothing flips automatically.
"""
from __future__ import annotations

import time
from collections import Counter
from datetime import date

from docket.ai.pricing import Usage, calculate_cost_usd, usage_capture
from docket.ai.transcripts.events import load_agenda, load_segments_with_speakers, render_agenda, render_transcript
from docket.ai.transcripts.prompts import EVENTS_TRANSCRIPT_SYSTEM
from docket.ai.transcripts.schemas import EVENTS_SCHEMA, EventList, ExtractedEvent
from docket.config import AI_TRANSCRIPT_AB_MODEL, AI_TRANSCRIPT_EVENTS_MODEL
from docket.db import db, db_cursor
from docket.services.transcripts import speaker_ordinals

HAIKU_WINDOW_TOKENS = 180_000      # Haiku 4.5 has a 200K window; leave room for output
ACTION_TYPES = ("motion", "vote", "executive_session_motion", "amendment", "item_deferred", "recusal")


def event_keys(events: list[ExtractedEvent]) -> Counter:
    return Counter((e.event_type, frozenset(e.agenda_item_refs)) for e in events)


def compare_event_lists(reference: list[ExtractedEvent], candidate: list[ExtractedEvent]) -> dict:
    ref, cand = event_keys(reference), event_keys(candidate)
    hit = sum((ref & cand).values())
    per_type: dict[str, float] = {}
    for et in {k[0] for k in ref}:
        r = Counter({k: v for k, v in ref.items() if k[0] == et})
        c = Counter({k: v for k, v in cand.items() if k[0] == et})
        per_type[et] = round(sum((r & c).values()) / sum(r.values()), 3)
    return {"precision": round(hit / sum(cand.values()), 3) if cand else 0.0,
            "recall": round(hit / sum(ref.values()), 3) if ref else 0.0,
            "per_type_recall": per_type, "n_ref": sum(ref.values()), "n_cand": sum(cand.values())}


def material_labels(meeting_id: int) -> set[tuple[str, frozenset[int]]]:
    with db_cursor() as cur:
        cur.execute("""SELECT e.event_type, e.agenda_item_refs FROM minutes_discrepancies d
                         JOIN meeting_events e ON e.id = d.transcript_event_id
                        WHERE d.meeting_id = %s AND d.review_state = 'approved' AND d.category = 'omission'""", [meeting_id])
        return {(r["event_type"], frozenset(r["agenda_item_refs"])) for r in cur.fetchall()}


def _one(client, model: str, user: str, effort: str | None, notes: str) -> tuple[list[ExtractedEvent], dict]:
    from docket.ai.worker import RunSummary, _close_run, _open_run
    with db() as conn:
        run_id = _open_run(conn, "transcript_ab", model, notes)
    summary = RunSummary(stage="transcript_ab")
    t0 = time.monotonic()
    try:
        with usage_capture() as emissions:
            res = client.call(model=model, system=EVENTS_TRANSCRIPT_SYSTEM, user=user, schema=EVENTS_SCHEMA, max_tokens=32000, effort=effort)
        events = EventList.model_validate(res.data).events
        summary.rows_processed = 1
    except Exception:
        summary.rows_failed = 1
        raise
    finally:
        for m, u in emissions:
            summary.cost_usd += calculate_cost_usd(m, u)
            summary.usage = Usage(summary.usage.input_tokens + u.input_tokens, summary.usage.cache_creation_input_tokens + u.cache_creation_input_tokens,
                                  summary.usage.cache_read_input_tokens + u.cache_read_input_tokens, summary.usage.output_tokens + u.output_tokens)
        with db() as conn:
            _close_run(conn, run_id, summary)
    return events, {"cost_usd": round(summary.cost_usd, 4), "latency_s": round(time.monotonic() - t0, 1), "tokens": summary.usage.input_tokens}


def run_ab(meeting_ids: list[int], *, client, notes_prefix: str = "ab") -> list[dict]:
    results = []
    for mid in meeting_ids:
        with db_cursor() as cur:
            cur.execute("SELECT t.id FROM transcripts t WHERE t.meeting_id = %s", [mid])
            tid = cur.fetchone()["id"]
            cur.execute("SELECT title, meeting_date::text FROM meetings WHERE id = %s", [mid])
            meeting = dict(cur.fetchone())
        agenda = load_agenda(mid)
        user = (f"Meeting: {meeting['title']} on {meeting['meeting_date']}\n\n{render_agenda(agenda)}\n\n"
                f"Transcript:\n{render_transcript(load_segments_with_speakers(tid), agenda, speaker_ordinals(tid))}")
        row = {"meeting_id": mid, "skipped": None}
        if client.count_tokens(model=AI_TRANSCRIPT_AB_MODEL, system=EVENTS_TRANSCRIPT_SYSTEM, user=user) > HAIKU_WINDOW_TOKENS:
            row["skipped"] = "transcript exceeds Haiku's window"
            results.append(row)
            continue
        sonnet_events, sonnet_meta = _one(client, AI_TRANSCRIPT_EVENTS_MODEL, user, "medium", f"{notes_prefix}_sonnet")
        haiku_events, haiku_meta = _one(client, AI_TRANSCRIPT_AB_MODEL, user, None, f"{notes_prefix}_haiku")
        labels = material_labels(mid)
        def mat(evs):
            return round(len(labels & set(event_keys(evs))) / len(labels), 3) if labels else None
        row.update(sonnet=sonnet_meta, haiku={**compare_event_lists(sonnet_events, haiku_events), **haiku_meta},
                   material_recall={"sonnet": mat(sonnet_events), "haiku": mat(haiku_events)}, labels=len(labels))
        results.append(row)
    return results


def render_report(results: list[dict]) -> str:
    scored = [r for r in results if not r.get("skipped")]
    lines = [f"# Haiku 4.5 vs Sonnet 5.5 extraction A/B ({date.today().isoformat()})", "",
             f"Meetings scored: {len(scored)}; skipped: {len(results) - len(scored)}. Reference = Sonnet 5.5 output; "
             "keys = (event_type, agenda item ids) multisets. Material recall = share of approved omission events each model found.", "",
             "## Decision rule", "",
             "Haiku takes the extraction stage only if, across the scored meetings, its recall against Sonnet is at least 0.90 on "
             "motion, vote, executive_session_motion, amendment, item_deferred, and recusal events, at least 0.80 on statement events, "
             "its material recall is not below Sonnet's, and its cost is at most half of Sonnet's. Otherwise Sonnet stays.", "",
             "| meeting | Haiku recall | Haiku precision | action-type recall (min) | statement recall | material recall H/S | cost H/S | latency H/S |",
             "|---|---|---|---|---|---|---|---|"]
    agg_action, agg_stmt, h_cost, s_cost = [], [], 0.0, 0.0
    for r in scored:
        h = r["haiku"]
        action = [h["per_type_recall"][t] for t in ACTION_TYPES if t in h["per_type_recall"]]
        stmt = h["per_type_recall"].get("statement")
        agg_action += action
        if stmt is not None:
            agg_stmt.append(stmt)
        h_cost += h["cost_usd"]; s_cost += r["sonnet"]["cost_usd"]
        mr = r["material_recall"]
        lines.append(f"| meeting {r['meeting_id']} | {h['recall']} | {h['precision']} | {min(action) if action else 'n/a'} | {stmt if stmt is not None else 'n/a'} | "
                     f"{mr['haiku']}/{mr['sonnet']} | ${h['cost_usd']}/${r['sonnet']['cost_usd']} | {h['latency_s']}s/{r['sonnet']['latency_s']}s |")
    for r in results:
        if r.get("skipped"):
            lines.append(f"| meeting {r['meeting_id']} | skipped: {r['skipped']} | | | | | | |")
    min_action = min(agg_action) if agg_action else 0.0
    min_stmt = min(agg_stmt) if agg_stmt else 0.0
    passes = bool(scored) and min_action >= 0.90 and min_stmt >= 0.80 and h_cost <= 0.5 * s_cost
    lines += ["", "## Verdict", "",
              f"Action-type recall floor {min_action}, statement recall floor {min_stmt}, cost ${h_cost:.2f} vs ${s_cost:.2f}. "
              + ("Haiku passes the rule: set `AI_TRANSCRIPT_EVENTS_MODEL=claude-haiku-4-5-20251001` on the worker and re-run the pilot live test."
                 if passes else "Haiku does not pass the rule: Sonnet 5.5 stays the extraction model.")]
    return "\n".join(lines)
```

- [ ] **Step 5: Script**

```python
#!/usr/bin/env python
# scripts/transcript_extraction_ab.py
"""Run the Haiku vs Sonnet extraction A/B over the N newest compared meetings and write the report.

    ANTHROPIC_API_KEY=... DATABASE_URL=... venv/bin/python scripts/transcript_extraction_ab.py --meetings 10

Cost: about $0.25 per meeting (one Sonnet + one Haiku extraction). Writes
docs/superpowers/experiments/<date>-haiku-extraction-ab.md by default.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

from docket.ai.transcripts.ab import render_report, run_ab
from docket.ai.transcripts.client import StructuredClient
from docket.db import db_cursor

logging.basicConfig(level=logging.INFO)
ap = argparse.ArgumentParser()
ap.add_argument("--meetings", type=int, default=10)
ap.add_argument("--out", type=Path, default=Path(f"docs/superpowers/experiments/{date.today().isoformat()}-haiku-extraction-ab.md"))
a = ap.parse_args()
with db_cursor() as cur:
    cur.execute("""SELECT t.meeting_id FROM transcripts t JOIN meetings m ON m.id = t.meeting_id
                    WHERE t.status = 'compared' AND m.is_hidden = FALSE ORDER BY m.meeting_date DESC LIMIT %s""", [a.meetings])
    ids = [r["meeting_id"] for r in cur.fetchall()]
results = run_ab(ids, client=StructuredClient())
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(render_report(results))
print(f"wrote {a.out}")
```

- [ ] **Step 6: Live tests**

```python
# tests/live/test_transcript_pilot_e2e.py
"""LIVE: full worker pass on the pilot fixture; asserts the two hand-verified discrepancies (spec Section 6, live test 2). ~$1."""
import os

import pytest

from docket.ai.transcripts import pipeline as P
from docket.ai.transcripts.client import StructuredClient
from docket.ai.transcripts.guard import canonical_statute, normalize
from docket.db import db_cursor
from tests.support.transcript_fixtures import install_bundle, pilot_bundle

pytestmark = pytest.mark.live
DUMMY = "test-dummy-key-not-for-real-api-calls"


@pytest.fixture
def client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or key == DUMMY:
        pytest.skip("real ANTHROPIC_API_KEY not set")
    return StructuredClient(api_key=key)


def test_pilot_reproduces_sequence_and_wording_discrepancies(client):
    inst = install_bundle(pilot_bundle(), external_id="999015", status="uploaded")
    try:
        with db_cursor() as cur:   # the pilot clip has one cluster and 650 words; skip the fitness floor for this test
            cur.execute("UPDATE transcripts SET word_count=5000 WHERE id=%s", [inst.transcript_id])
        outcomes = P.run_for_meeting(inst.meeting_id, client=client, notes="live_pilot_e2e")
        assert outcomes == ["advanced", "advanced", "advanced"], outcomes
        with db_cursor() as cur:
            cur.execute("""SELECT category, severity, review_state, title, description, transcript_excerpt, minutes_excerpt, citation_match
                             FROM minutes_discrepancies WHERE meeting_id=%s AND review_state='proposed'""", [inst.meeting_id])
            rows = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT summary, detail FROM meeting_events WHERE meeting_id=%s AND source='transcript' AND event_type='statement'", [inst.meeting_id])
            statements = [dict(r) for r in cur.fetchall()]
        print("\n".join(f"{r['category']}/{r['severity']}/{r['citation_match']}: {r['title']}" for r in rows))
        cats = {r["category"] for r in rows if r["severity"] == "material"}
        assert "sequence" in cats and "wording" in cats
        wording = [r for r in rows if r["category"] == "wording" and r["severity"] == "material"]
        blob = " ".join(canonical_statute(" ".join(filter(None, [r["title"], r["description"], r["transcript_excerpt"]]))) for r in wording)
        assert "3625a7a4" in blob, "the (a)(4) ground must appear on the transcript side"
        assert any("pending litigation" in normalize(r["minutes_excerpt"] or r["description"]) for r in wording)
        assert all(r["citation_match"] in ("exact", "fuzzy") for r in rows if r["severity"] == "material")
        assert any("packet" in normalize(s["summary"] + " " + str(s["detail"])) for s in statements), "O'Quinn's 'not in the packet' statement"
    finally:
        inst.cleanup()
        with db_cursor() as cur:
            cur.execute("DELETE FROM ai_runs WHERE notes='live_pilot_e2e'")
```

```python
# tests/live/test_transcript_chaotic.py
"""LIVE: public-comment stretch of the real 2543 transcript yields no action events (spec Section 6, live test 3). ~$0.15.

Set CHAOTIC_SEQ_RANGE="<first>-<last>" to the public-comment segment range of meeting 2543
(find it on the transcript page); the test skips when unset.
"""
import os

import pytest

from docket.ai.transcripts import events as EV
from docket.ai.transcripts.client import StructuredClient
from docket.db import db_cursor
from tests.support.transcript_fixtures import install_bundle, load_bundle

pytestmark = pytest.mark.live
DUMMY = "test-dummy-key-not-for-real-api-calls"


def test_public_comment_slice_has_no_fabricated_actions():
    key, rng = os.environ.get("ANTHROPIC_API_KEY"), os.environ.get("CHAOTIC_SEQ_RANGE")
    if not key or key == DUMMY or not rng:
        pytest.skip("needs a real ANTHROPIC_API_KEY and CHAOTIC_SEQ_RANGE")
    lo, hi = (int(x) for x in rng.split("-"))
    b = load_bundle("transcript_2543")
    b.segments = [s for s in b.segments if lo <= s["seq"] <= hi]
    b.speakers = [sp for sp in b.speakers if sp["cluster_label"] in {s["cluster_label"] for s in b.segments}]
    inst = install_bundle(b, status="speakers_resolved")
    try:
        with db_cursor() as cur:
            cur.execute("UPDATE meetings SET minutes_url=NULL WHERE id=%s", [inst.meeting_id])
        claim = {"id": inst.transcript_id, "meeting_id": inst.meeting_id, "status": "speakers_resolved", "version": 1, "word_count": 5000, "compare_skipped_reason": None}
        EV.run_events_stage(claim, client=StructuredClient(api_key=key))
        with db_cursor() as cur:
            cur.execute("SELECT event_type, count(*) AS n FROM meeting_events WHERE meeting_id=%s GROUP BY 1", [inst.meeting_id])
            counts = {r["event_type"]: r["n"] for r in cur.fetchall()}
        print(counts)
        assert not ({"motion", "vote", "amendment", "executive_session_motion", "item_deferred"} & set(counts)), counts
    finally:
        inst.cleanup()
```

```python
# tests/live/test_transcript_ab.py
"""LIVE: the A/B harness runs both models on the 2543 fixture and writes a report (spec Section 6, live test 4). ~$0.25."""
import os

import pytest

from docket.ai.transcripts.ab import render_report, run_ab
from docket.ai.transcripts.client import StructuredClient
from docket.db import db_cursor
from tests.support.transcript_fixtures import install_bundle, load_bundle

pytestmark = pytest.mark.live
DUMMY = "test-dummy-key-not-for-real-api-calls"


def test_ab_runs_both_models_and_records_runs():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or key == DUMMY:
        pytest.skip("real ANTHROPIC_API_KEY not set")
    inst = install_bundle(load_bundle("transcript_2543"), status="compared")
    try:
        results = run_ab([inst.meeting_id], client=StructuredClient(api_key=key), notes_prefix="live_ab")
        report = render_report(results)
        print(report)
        assert results[0]["skipped"] is None and 0.0 <= results[0]["haiku"]["recall"] <= 1.0
        with db_cursor() as cur:
            cur.execute("SELECT model, cost_usd FROM ai_runs WHERE notes IN ('live_ab_sonnet', 'live_ab_haiku') ORDER BY id DESC LIMIT 2")
            rows = cur.fetchall()
        assert {r["model"] for r in rows} == {"claude-sonnet-5-5", "claude-haiku-4-5-20251001"} and all(r["cost_usd"] > 0 for r in rows)
        assert "Verdict" in report
    finally:
        inst.cleanup()
        with db_cursor() as cur:
            cur.execute("DELETE FROM ai_runs WHERE notes IN ('live_ab_sonnet', 'live_ab_haiku')")
```

- [ ] **Step 7: Run unit tests, then the live tests once**

Run: `venv/bin/python -m pytest tests/unit/test_ab_metrics.py tests/unit/test_transcript_client.py -v`
Expected: all PASS.

Run (about $1.50 total): `ANTHROPIC_API_KEY=... venv/bin/python -m pytest -m live tests/live/test_transcript_pilot_e2e.py tests/live/test_transcript_ab.py -v -s`, then with `CHAOTIC_SEQ_RANGE` set, `tests/live/test_transcript_chaotic.py`.
Expected: all PASS. The pilot test is the acceptance criterion from the spec's "Pilot evidence" section; if it fails on the `sequence` assertion, inspect the printed rows: the usual cause is the judge dismissing the LIS pair as "same action", which is a prompt problem (JUDGE_SYSTEM's sequence guidance), not an aligner problem. Paste the printed discrepancy rows into the PR description.

- [ ] **Step 8: Commit**

```bash
git add src/docket/ai/transcripts/ab.py src/docket/ai/transcripts/client.py src/docket/config.py scripts/transcript_extraction_ab.py tests/unit/test_ab_metrics.py tests/unit/test_transcript_client.py tests/live/test_transcript_pilot_e2e.py tests/live/test_transcript_chaotic.py tests/live/test_transcript_ab.py
git -c user.email=hello@docket.pub commit -m "feat(ai): Haiku vs Sonnet extraction A/B harness; live pilot, chaotic, and A/B tests

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 19: Runbook, env example, CLAUDE.md, and the ship gate procedure

**Files:**
- Modify: `docs/runbooks/transcripts.md` (from PR #103; merge #103 first or rebase this branch onto it), `.env.example`, `CLAUDE.md` (worker tasks line, transcripts pointer), `README.md` (cron list)
- Test: none (docs); `venv/bin/python -m pytest tests -q` as the final gate

**Interfaces:** none.

- [ ] **Step 1: Runbook additions to `docs/runbooks/transcripts.md`**

Replace the "Railway worker: nothing yet" bullet and the status-machine rows marked "Not used yet" with the plan 2 behavior, and add these sections:

```markdown
## Worker stages (plan 2)

`transcript_pipeline` runs at 10:00 America/Chicago (after vote matching) and
advances up to `TRANSCRIPT_PER_TICK` (default 5) transcripts one stage each:

| From | Stage | Model | To |
|---|---|---|---|
| `uploaded` | fitness gate (`TRANSCRIPT_MIN_WORDS`, default 300) then index-point item assignment, then speaker resolution | Sonnet 5.5 | `speakers_resolved` (or `low_speech` when under the floor) |
| `speakers_resolved` | event extraction: transcript side always; minutes side when the minutes PDF downloads | Sonnet 5.5 | `events_extracted` (`compare_skipped_reason` = `no_minutes` / `minutes_unavailable` when the minutes side did not run; re-claimed when minutes appear) |
| `events_extracted` | aligner, Opus judge, Opus hunter, deterministic vote check | Opus 5.5 | `compared` |

Per stage: three attempts with a 24-hour backoff, then `failed`. Schema failures,
refusals, token-ceiling breaches (`TRANSCRIPT_TOKEN_CEILING`), and candidate-cap
trips (`TRANSCRIPT_CANDIDATE_CAP`) go straight to `needs_review` with the reason.
A transcript that was uploaded stays public through `failed`/`needs_review`.
Every call writes `ai_runs` (stages `transcript_speakers`, `transcript_events`,
`transcript_compare`, `transcript_ab`) so `AI_DAILY_BUDGET_USD` applies.
Manual run: `railway ssh --service worker` then `python -m docket.worker.scheduler --run-once transcript_pipeline`.
One meeting: `venv/bin/python scripts/transcript_recompare.py --meeting-id N --now` (laptop, public DB URL, API key).

## Worker environment

`AI_TRANSCRIPT_SPEAKER_MODEL`, `AI_TRANSCRIPT_EVENTS_MODEL` (default `claude-sonnet-5-5`),
`AI_TRANSCRIPT_COMPARE_MODEL` (default `claude-opus-5-5`), `TRANSCRIPT_TOKEN_CEILING`,
`TRANSCRIPT_CANDIDATE_CAP`, `TRANSCRIPT_PER_TICK`, `TRANSCRIPT_MIN_WORDS`,
`ALERT_WEBHOOK_URL` (Slack or Discord incoming webhook; unset = silent),
`HEALTHCHECK_TRANSCRIPT_PIPELINE_UUID`. Web service: `MINUTES_VS_VIDEO_UI` (see ship gate).

## Review queue

`/admin/review/discrepancies`: proposed rows, material first. Approve, reject with a
reason, or edit title/description then approve (edits go to `admin_*` columns; the
model text is kept). Rows with `citation_match = 'missing'` cannot be approved until
you paste the exact excerpt and the guard finds it. Tabs: dismissed by model, stale
(re-comparison no longer shows it), held (needs_review/failed transcripts, with Retry).
Speaker fixes: `/admin/transcripts/<meeting_id>/speakers`; a saved row is manual and
never overwritten by the stage; Release lets the stage try again.

## Ship gate

The public "Minutes vs. Video" block and `/minutes-vs-video/` stay off until at least
70% of material candidates over the first 10 reviewed meetings or the first 30 reviewed
candidates (whichever comes first) are approved. `/admin/ai` shows the running ratio.
When it reads "met", set `MINUTES_VS_VIDEO_UI=true` on the `docket-web` service and
redeploy. The flip is manual and reversible.

## Re-comparison

Corrected minutes: the daily tick re-downloads each compared meeting's minutes at most
weekly; a changed PDF re-extracts the minutes side and re-runs the comparison. Approved
rows go `stale`, and a candidate that comes back is re-proposed in place (badged
"re-review") instead of duplicated. Unmatched approvals stay `stale` and visible under
the stale tab.

## Alerts

`ALERT_WEBHOOK_URL` receives a JSON post when a transcript enters `failed` or
`needs_review` and once a day when the Legion looks stalled (a meeting with video older
than seven days has no transcript and no heartbeat is newer than seven days).

## Haiku A/B

`venv/bin/python scripts/transcript_extraction_ab.py --meetings 10` writes
`docs/superpowers/experiments/<date>-haiku-extraction-ab.md` with the decision rule and
a verdict. Flip `AI_TRANSCRIPT_EVENTS_MODEL` only on a passing verdict.
```

Add a dated history line: "2026-10: plan 2 (worker stages, review queue, public block behind flag)".

- [ ] **Step 2: `.env.example`, `CLAUDE.md`, `README.md`**

Append the worker and web variables above to `.env.example` with one-line comments. In `CLAUDE.md`, update the `tasks.py` line to twelve tasks including `transcript_pipeline`, add `ai/transcripts/` to the layout tree with one line per module, and point at the runbook. In `README.md`, add `transcript_pipeline` (10:00) to the cron list and change the transcripts paragraph's "Plan 2 ... is designed but not built" to describe what is live and that the public block is behind `MINUTES_VS_VIDEO_UI`.

- [ ] **Step 3: Full suites**

Run: `venv/bin/python -m pytest tests -q` and `pytest transcriber/tests -q`.
Expected: everything that passed on main still passes plus the new tests; the 9 pre-existing failures noted in the plan 1 memory (mig-033 matview, blog routes, city overview, live timeouts) are the only failures, and none of them are in files this plan touched.

- [ ] **Step 4: Commit**

```bash
git add docs/runbooks/transcripts.md .env.example CLAUDE.md README.md
git -c user.email=hello@docket.pub commit -m "docs: transcript pipeline runbook, env, and ship-gate procedure for plan 2

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Operator steps after the code tasks

1. Merge PRs #103 and #104 (docs) before this branch so the runbook edits in Task 19 apply cleanly.
2. Deploy: `scripts/deploy.sh --service docket-web` then `--service worker`. Migrations run at container start; 036 applies.
3. Set worker variables: `AI_TRANSCRIPT_*` only if overriding defaults, `ALERT_WEBHOOK_URL`, `HEALTHCHECK_TRANSCRIPT_PIPELINE_UUID` (create the check in Healthchecks.io first, daily, grace 2h). Leave `MINUTES_VS_VIDEO_UI` unset on the web service.
4. First tick by hand: `railway ssh --service worker` then `python -m docket.worker.scheduler --run-once transcript_pipeline`. Expect five transcripts to move one stage each; check `/admin/ai` for the `transcript_speakers` runs and cost, and a transcript page for resolved names. Run the tick two more mornings (or let cron) until the newest meetings reach `compared`.
5. Review in `/admin/review/discrepancies`. Spot-check the first ten approvals against the video. If the citation-missing rate on `/admin/ai` is above 10 percent after ten meetings, tune the guard normalizer and the quote rule before approving more.
6. Once the ship gate reads "met", set `MINUTES_VS_VIDEO_UI=true` on `docket-web` and redeploy. Confirm a meeting page shows the block and `/minutes-vs-video/` lists the approvals.
7. Run the Haiku A/B: `scripts/transcript_extraction_ab.py --meetings 10`, read the report, decide the extraction model.
8. Backfill 2021 to 2025 on the Legion only after the current era is reviewed; raise `TRANSCRIPT_PER_TICK` to pace the worker, not parallelism (spec: concurrency).

## Self-review notes

- **Spec coverage, this plan:** Section 3 stages table → Tasks 7, 9, 11; speaker resolution signals and the two-signal rule → Tasks 6, 7; structured outputs + smoke test before prompts → Tasks 1, 2; hallucination guard, normalizer, fuzzy pass, `citation_match`, missing-citation handling, 10 percent tracking → Tasks 5, 11, 14, 17; deterministic vote outcomes → Tasks 10, 11; failure states, token ceiling, per-stage re-runs, concurrency (serial, per-tick cap) → Task 4; shared materiality fragment byte-for-byte → Task 2; request builders return parameter dicts → Task 1; Haiku experiment → Task 18; scheduling 10:00 → Task 4; alerting including the stalled desktop → Task 13. Section 4 event schema → Task 2; alignment steps 1 to 6 → Task 10; judge and hunter → Task 11; severity → Tasks 2, 11; candidate cap → Task 11; re-comparison and stale reconciliation → Task 12. Section 5 admin queue (filters, both excerpts, chapter and minutes links, approve/reject/edit, dismissed tab, needs_review rows) → Task 14; speaker correction → Task 15; public block, listing page, flag, honesty copy → Task 16; operational surfaces (data debt, AI panel rows, approve-to-reject ratio) → Tasks 4, 17. Section 6 live tests 1 to 4 → Tasks 1, 2, 18; ship gate → Tasks 14, 16, 17. Review Focus 1 → Tasks 8 and 9 (`test_html_page_instead_of_pdf_returns_none_and_writes_nothing`, `test_unavailable_minutes_is_a_skip_not_a_failure`); 2 → Tasks 11 and 14; 3 → Task 14; 4 → Task 16; 5 → Task 10.
- **Facts from the first run:** real-row fixture (Task 3), word-count fitness gate and its data-debt label (Task 4), 24-cluster resolution and merging (Tasks 6, 7, 15, 16), silence filtering in every loader (`is_silence = FALSE AND text <> ''`), `(meeting_id, cluster_label)` keyed writes (Task 7), index-point assignment the plan 1 upload left out (Task 4), consent-by-number and floor-added items from PR #104 (Tasks 2, 10).
- **Type consistency:** `StageOutcome(next_status, skipped_reason, detail)` is the one return type of all three stage functions and `advance()`; `TranscriptHeld.reason` values match `needs_review_reason` strings used in the queue's held tab; `Candidate.kind` values match `build_rows`' branches; `_COLS` in `compare.py` match the `minutes_discrepancies` columns and `reconcile()` reuses them; `discrepancies._SELECT` aliases (`display_title`, `item_external_id`, `municipality_slug`) are what both admin and public templates read; `speaker_ordinals` is the single source of "Speaker N" in `events.render_transcript`, `compare.transcript_window`, and the correction page.
- **Deliberate deviations from plan 1, with reasons:** `PUBLIC_STATUSES` is widened by `public_predicate()` so a worker-stage failure after upload does not take a readable transcript off the site (plan 1's 404-on-failed test concerned producer failures with no segments). `list_transcript_debt` lists `low_speech` rows under the word floor regardless of recording length because the mic-check clip is exactly the junk the page should surface.
- **Deliberate choices not in the spec:** rejected rows that match on re-comparison stay rejected (the reviewer already said no); old `dismissed_by_model` rows are replaced wholesale on re-comparison; `MINUTED_TYPES` limits omission/addition candidates to event types minutes record (item openings, public comment, roll calls, and standalone seconds never become candidates); a bump to `EVENTS_PROMPT_VERSION` re-extracts the transcript side, which changes transcript event ids and therefore strands approvals as `stale` (acceptable, documented in the runbook, keep rare).
- **House rules honored:** every new call site mirrors v2's retry ladder and cache breakpoint and is smoke-tested live before anything builds on it (Tasks 1, 2, 7, 9, 18); the memory rule's "forced tool choice" half is superseded by spec decision H because the 5.5 models reject it; CSRF is scoped to the new blueprint and issue #83 keeps the rest.
- **External plan review dispositions (2026-10-11), accepted:** fuzzy citation pass is now anchored on exact three-word shingles instead of sweeping the source (Task 5; `MAX_FUZZY_ANCHORS = 50`, long-source test added); hyphenated line breaks with a trailing or leading space join (Task 5); `effective_consent_block` sorts by seq and a pull-then-add test pins the order (Task 10); state races and bad excerpts in the review queue flash and redirect instead of returning 409/400 pages (Task 14), with the Review Focus 2 and 3 wording updated.
- **External plan review dispositions, rejected with evidence (do not re-raise):** "budget checked once before the loop": the `_today_spend` check is inside `for _ in range(limit)` immediately before `claim_next()`, and each claim's cost lands in `ai_runs` at `_close_run` before the next check. "Connection held open during the Opus call": `with db() as conn: run_id = _open_run(...)` closes before the stage runs and `_close_run` opens its own connection; `docket.db.db()` is a fresh `psycopg2.connect` per call, there is no pool. "Minutes packets blow the ceiling": Birmingham's MinutesViewer PDF is the clerk's minutes (the pilot's whole-meeting minutes are about 27K tokens), the spec sizes a 300-page packet at 150K tokens against a 500K ceiling, and the spec's reviewer dispositions already rejected chunking; no truncation heuristic. "24-hour penalty for a 529": transient 5xx and 529 are retried three times with backoff inside `_with_retries` before the row ever takes an attempt, the spec prescribes the 24-hour row backoff, and the task runs once a day so a shorter interval would change nothing. The `regex` module was not added as a dependency; the anchor heuristic needs none.
- **Known gaps left for later, on purpose:** splitting a mixed speaker cluster at segment level (phase 2); Batches mode (only if the 2021 to 2025 backfill is approved; builders already return parameter dicts); cross-meeting voice identification (embeddings are stored); `vote_outcome` candidates on pre-2026 meetings need the video OCR backfill mode the spec's side note describes, but the minutes-derived baseline works for every year.
