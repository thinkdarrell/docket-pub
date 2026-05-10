"""Cross-stage conflict resolution actions (G4 — spec decision #93).

Each resolution action:
- Validates inputs (length caps + Pydantic for fact edits).
- Updates ``agenda_items`` (clearing/setting fields per the action).
- Records an audit row in ``processing_status_audit`` with the
  from/to status, action verb, actor, and action-specific payload.
- Returns a result dict the route handler renders into the swap-target
  partial.

Two of the four actions (``re_prompt_stage_2``, ``edit_stage_1_facts``)
re-run Stage 2 of the v3 pipeline. They use a private helper
``_rerun_stage2`` that calls ``rewrite.rewrite_item`` ->
``floors.apply_score_floors`` -> ``reconcile.reconcile_stages``. This
helper is a minimal Stage 2 re-run path; B5 (the cross-track
convergence task) will later subsume it into a full per-item
orchestrator. G4 ships before B5 because decision #93 is required
before ``IMPACT_FIRST_ENABLED=true`` flips the worker.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
decisions #45, #72, #93.

Plan deviation: the plan imports ``get_enabled_policy_slugs`` from
``docket.services.badges`` — neither that module nor that function
exists in this branch. The closest analog is
:func:`docket.services.query.list_enabled_badges`, which returns a
list of dicts (process + policy). For Stage 2 re-runs we want only
policy slugs (process badges are always-on and the Stage 2 prompt
doesn't gate on them), so :func:`_get_enabled_policy_slugs` below
filters that list down to ``kind == 'policy'`` slugs.

Plan deviation: ``apply_score_floors`` in this branch has the signature
``(cur, item, facts, ai, city_id)``. The plan's
``_rerun_stage2(item, facts, override_instruction=None)`` invokes it as
``apply_score_floors(facts, item_view, rewrite)`` — wrong order and
missing ``cur`` + ``city_id``. The helper here threads a short-lived
cursor and the item's ``municipality_id`` through to the call.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal

from docket.ai.extraction_schema import StructuredFacts
from docket.ai.floors import apply_score_floors
from docket.ai.reconcile import reconcile_stages
from docket.ai.rewrite import rewrite_item
from docket.db import db
from docket.services.query import list_enabled_badges

log = logging.getLogger(__name__)


# Length caps mirror ItemRewrite Pydantic constraints (rewrite_schema.py).
HEADLINE_MIN = 10
HEADLINE_MAX = 60
WHY_IT_MATTERS_MIN = 1
WHY_IT_MATTERS_MAX = 200
OVERRIDE_INSTRUCTION_MAX = 500
REASON_MAX = 500


class ConflictValidationError(ValueError):
    """Raised when admin input fails length/format validation."""


class ConflictAlreadyResolvedError(RuntimeError):
    """Raised when a TOCTOU race fires: between the load-conflict-item read
    and the persistence UPDATE, another admin (or the worker) flipped the
    item out of cross_stage_conflict state. The route maps this to 409 +
    a plain-text "this item was resolved during your LLM call" message
    rendered into the form's .form-error span via the htmx:response-error
    handler. Decision #12.
    """


@dataclass
class ResolutionResult:
    """Returned by every resolution function. Route maps to swap-target."""
    item_id: int
    new_status: str  # 'completed' or 'cross_stage_conflict' (re-prompt may stay)
    action: str
    success: bool  # False only when re-prompt/edit-facts still conflicts
    detail: str | None = None  # human-readable note for the swap target


def _get_enabled_policy_slugs(city_id: int) -> list[str]:
    """Return policy-badge slugs enabled for ``city_id`` as a list[str].

    Plan deviation shim — see module docstring. ``list_enabled_badges``
    returns process + policy dicts; rewrite.rewrite_item expects
    ``enabled_policy_badges: list[str]`` of policy slugs only.
    """
    rows = list_enabled_badges(city_id)
    return [r["slug"] for r in rows if r.get("kind") == "policy"]


def _audit(cur, item_id: int, from_status: str, to_status: str,
            action: str, actor: str, *,
            reason: str | None = None,
            payload: dict | None = None) -> None:
    """Write a single processing_status_audit row.

    Mirrors the G2 retry/escalate pattern (admin.py:300-311) for shape
    consistency."""
    cur.execute(
        """
        INSERT INTO processing_status_audit
          (agenda_item_id, from_status, to_status, action,
           actor, actor_role, reason, payload)
        VALUES
          (%s,
           %s::processing_status_enum,
           %s::processing_status_enum,
           %s, %s, 'admin', %s, %s::jsonb)
        """,
        (item_id, from_status, to_status, action, actor, reason,
         json.dumps(payload) if payload else None),
    )


def _load_conflict_item(cur, item_id: int) -> dict | None:
    """Fetch the item + meeting context for a resolution action.

    Returns None if the item doesn't exist OR isn't in cross_stage_conflict.
    Both 'not found' and 'wrong state' map to 404 at the route layer
    so admins can't silently overwrite a completed item.
    """
    cur.execute(
        """
        SELECT ai.id, ai.title, ai.description, ai.sponsor,
               ai.dollars_amount, ai.topic, ai.is_consent,
               ai.extracted_facts, ai.score_overrides,
               ai.processing_status::text AS processing_status,
               m.id   AS municipality_id,
               m.name AS city_name
          FROM agenda_items ai
          JOIN meetings mt ON mt.id = ai.meeting_id
          JOIN municipalities m ON m.id = mt.municipality_id
         WHERE ai.id = %s
        """,
        (item_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    item = dict(zip([
        "id", "title", "description", "sponsor", "dollars_amount",
        "topic", "is_consent", "extracted_facts", "score_overrides",
        "processing_status", "municipality_id", "city_name",
    ], row))
    if item["processing_status"] != "cross_stage_conflict":
        return None
    return item


# ---------------------------------------------------------------------------
# Action 1 — Accept Stage 1 (manual headline/why_it_matters)
# ---------------------------------------------------------------------------


def accept_stage_1(item_id: int, *,
                    manual_headline: str,
                    manual_why_it_matters: str,
                    actor: str) -> ResolutionResult:
    """Admin says: 'this IS substantive — here's what it should say.'

    Persists manual headline + why_it_matters; flips
    ``processing_status`` to 'completed'. Stage 1 facts kept intact
    (Stage 1 was correct, decision #93 path 1).

    Length caps mirror ItemRewrite Pydantic constraints to ensure
    consistency with LLM-generated outputs (decision #87).

    Raises ConflictValidationError if input fails validation.
    Raises LookupError if the item isn't in cross_stage_conflict.
    """
    headline = manual_headline.strip()
    why = manual_why_it_matters.strip()

    if len(headline) < HEADLINE_MIN or len(headline) > HEADLINE_MAX:
        raise ConflictValidationError(
            f"manual_headline must be {HEADLINE_MIN}-{HEADLINE_MAX} chars"
        )
    if len(why) < WHY_IT_MATTERS_MIN or len(why) > WHY_IT_MATTERS_MAX:
        raise ConflictValidationError(
            f"manual_why_it_matters must be {WHY_IT_MATTERS_MIN}-"
            f"{WHY_IT_MATTERS_MAX} chars"
        )

    with db() as conn, conn.cursor() as cur:
        item = _load_conflict_item(cur, item_id)
        if item is None:
            raise LookupError(f"item {item_id} not in cross_stage_conflict")

        cur.execute(
            """
            UPDATE agenda_items
               SET headline = %s,
                   why_it_matters = %s,
                   processing_status = 'completed'::processing_status_enum
             WHERE id = %s
            """,
            (headline, why, item_id),
        )
        _audit(
            cur, item_id,
            from_status="cross_stage_conflict",
            to_status="completed",
            action="accept_stage1",
            actor=actor,
            payload={
                "manual_headline": headline,
                "manual_why_it_matters": why,
            },
        )

    log.info("admin accept_stage1: item_id=%s actor=%s", item_id, actor)
    return ResolutionResult(
        item_id=item_id,
        new_status="completed",
        action="accept_stage1",
        success=True,
        detail="Stage 1 accepted; manual headline + why_it_matters applied.",
    )
