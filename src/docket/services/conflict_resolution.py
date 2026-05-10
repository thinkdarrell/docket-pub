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


# ---------------------------------------------------------------------------
# Action 2 — Accept Stage 2 (clear Stage 1 facts, mark procedural)
# ---------------------------------------------------------------------------


def accept_stage_2(item_id: int, *,
                    actor: str,
                    reason: str | None = None) -> ResolutionResult:
    """Admin says: 'Stage 2 was right — this IS procedural.'

    Clears Stage 1 facts that confused the reconcile gate; clears
    headline/why_it_matters; flips status to 'completed'. The item
    will render via the procedural Smart Brevity Card variant
    (just title, no headline/why_it_matters) — same as any other
    procedural item.

    No LLM call.

    Raises LookupError if item not in cross_stage_conflict.
    """
    if reason is not None:
        reason = reason.strip()
        if len(reason) > REASON_MAX:
            raise ConflictValidationError(
                f"reason must be at most {REASON_MAX} chars"
            )
        reason = reason or None

    with db() as conn, conn.cursor() as cur:
        item = _load_conflict_item(cur, item_id)
        if item is None:
            raise LookupError(f"item {item_id} not in cross_stage_conflict")

        cur.execute(
            """
            UPDATE agenda_items
               SET extracted_facts = NULL,
                   headline = NULL,
                   why_it_matters = NULL,
                   processing_status = 'completed'::processing_status_enum
             WHERE id = %s
            """,
            (item_id,),
        )
        _audit(
            cur, item_id,
            from_status="cross_stage_conflict",
            to_status="completed",
            action="accept_stage2",
            actor=actor,
            reason=reason,
        )

    log.info("admin accept_stage2: item_id=%s actor=%s", item_id, actor)
    return ResolutionResult(
        item_id=item_id,
        new_status="completed",
        action="accept_stage2",
        success=True,
        detail="Stage 1 facts cleared; item marked procedural.",
    )


# ---------------------------------------------------------------------------
# Action 3 — Re-prompt Stage 2 (admin override + Stage 2 re-run)
# ---------------------------------------------------------------------------


@dataclass
class _RerunOutcome:
    rewrite: Any  # ItemRewrite
    score_overrides_obj: Any  # ScoreOverrides from floors
    reconcile_action: str  # 'accept' | 'mark_cross_stage_conflict' | 'retry_stage2_with_override'
    conflicts: list[str]
    served_model: str


class _ItemView:
    """Lightweight item view for the v3 pipeline.

    rewrite.rewrite_item expects an object exposing: title, description,
    sponsor, dollars_amount, topic, is_consent, city_name. This wrapper
    converts a DB row dict into that shape.
    """
    def __init__(self, item: dict):
        self.id = item.get("id")
        self.title = item.get("title")
        self.description = item.get("description")
        self.sponsor = item.get("sponsor")
        self.dollars_amount = item.get("dollars_amount")
        self.topic = item.get("topic")
        self.is_consent = item.get("is_consent")
        self.city_name = item.get("city_name")


def _rerun_stage2(
    item: dict,
    facts: StructuredFacts,
    *,
    override_instruction: str | None = None,
) -> _RerunOutcome:
    """Run Stage 2 of the v3 pipeline against an item with optional override.

    Calls rewrite.rewrite_item -> floors.apply_score_floors ->
    reconcile.reconcile_stages. Returns the structured outcome the
    caller persists.

    This is a minimal Stage 2 re-run helper — B5 will subsume it when
    the cross-track per-item orchestrator lands. Until then this
    duplication is intentional (the orchestrator doesn't exist yet,
    and G4 must ship before FINAL-3 IMPACT_FIRST_ENABLED=true).

    The LLM call (``rewrite_item``) runs without holding a DB
    connection; the short ``apply_score_floors`` cursor is opened only
    for its per-city threshold lookup after the LLM call returns.
    """
    enabled_policy_slugs = _get_enabled_policy_slugs(item["municipality_id"])
    item_view = _ItemView(item)

    # Stage 2 LLM call — runs outside any held DB connection.
    rewrite, served_model = rewrite_item(
        item_view,
        facts,
        enabled_policy_slugs,
        extra_instruction=override_instruction,
    )

    # Stage 2.5 deterministic floors — needs a cursor for per-city threshold
    # lookups; uses a short fresh transaction (read-only).
    with db() as conn, conn.cursor() as cur:
        score_overrides_obj = apply_score_floors(
            cur, item_view, facts, rewrite, city_id=item["municipality_id"],
        )

    # Pass already_retried=True — admin re-runs are explicit, not the
    # auto-retry path. If reconcile still finds conflicts, mark and stop.
    result = reconcile_stages(facts, rewrite, item_view, already_retried=True)

    return _RerunOutcome(
        rewrite=rewrite,
        score_overrides_obj=score_overrides_obj,
        reconcile_action=result.action,
        conflicts=result.conflicts,
        served_model=served_model,
    )


def re_prompt_stage_2(item_id: int, *,
                       override_instruction: str,
                       actor: str) -> ResolutionResult:
    """Admin writes a one-liner override; system re-runs Stage 2.

    If the new Stage 2 rewrite reconciles cleanly (action='accept'),
    persist the new headline/why_it_matters/scores and flip status to
    completed.

    If reconcile still finds conflicts, leave status at
    cross_stage_conflict but record the failed-resolution attempt in
    the audit log. Admin can try a different action.

    Raises ConflictValidationError on input issues.
    Raises LookupError if item not in cross_stage_conflict.
    Raises ConflictAlreadyResolvedError on TOCTOU race-loss (decision #12).
    Bubbles up AIBudgetExceeded / AITransientError from the API call.
    """
    override = override_instruction.strip()
    if len(override) < 1 or len(override) > OVERRIDE_INSTRUCTION_MAX:
        raise ConflictValidationError(
            f"override_instruction must be 1-{OVERRIDE_INSTRUCTION_MAX} chars"
        )

    with db() as conn, conn.cursor() as cur:
        item = _load_conflict_item(cur, item_id)
        if item is None:
            raise LookupError(f"item {item_id} not in cross_stage_conflict")

        # Validate stored extracted_facts via Pydantic before re-running.
        # If the JSONB drifted, this surfaces it cleanly.
        if item["extracted_facts"] is None:
            raise ConflictValidationError(
                "item has no extracted_facts — re_prompt_stage_2 needs Stage 1 facts"
            )
        facts = StructuredFacts.model_validate(item["extracted_facts"])

    # Run Stage 2 OUTSIDE the transaction so the LLM call doesn't hold
    # the DB connection. The persist + audit happen in a fresh
    # transaction below.
    outcome = _rerun_stage2(item, facts, override_instruction=override)

    success = outcome.reconcile_action == "accept"
    new_status = "completed" if success else "cross_stage_conflict"

    score_overrides_payload = {
        "conflicts": outcome.conflicts,
        "original_ai_significance": outcome.score_overrides_obj.original_ai_significance,
        "final_significance": outcome.score_overrides_obj.final_significance,
        "original_ai_consent": outcome.score_overrides_obj.original_ai_consent,
        "final_consent": outcome.score_overrides_obj.final_consent,
        "triggers": outcome.score_overrides_obj.triggers,
        "admin_override_used": True,
    }

    # Decision #12 — TOCTOU guard. Both UPDATE branches scope the WHERE
    # to ``processing_status = 'cross_stage_conflict'`` so a concurrent
    # admin who resolved the row during our LLM call wins; ours becomes
    # a 0-row UPDATE and we raise ConflictAlreadyResolvedError. We still
    # write a race-loss audit row (decision #13) so the trail of "admin
    # tried X but lost the race" is preserved.
    with db() as conn, conn.cursor() as cur:
        if success:
            cur.execute(
                """
                UPDATE agenda_items
                   SET headline = %s,
                       why_it_matters = %s,
                       significance_score = %s,
                       consent_placement_score = %s,
                       score_overrides = %s::jsonb,
                       processing_status = 'completed'::processing_status_enum
                 WHERE id = %s
                   AND processing_status = 'cross_stage_conflict'::processing_status_enum
                """,
                (
                    outcome.rewrite.headline,
                    outcome.rewrite.why_it_matters,
                    outcome.score_overrides_obj.final_significance,
                    outcome.score_overrides_obj.final_consent,
                    json.dumps(score_overrides_payload),
                    item_id,
                ),
            )
        else:
            # Still conflicting; just refresh score_overrides with the
            # new conflict list. Same TOCTOU guard.
            cur.execute(
                """
                UPDATE agenda_items
                   SET score_overrides = %s::jsonb
                 WHERE id = %s
                   AND processing_status = 'cross_stage_conflict'::processing_status_enum
                """,
                (json.dumps(score_overrides_payload), item_id),
            )

        race_lost = cur.rowcount == 0
        if race_lost:
            # Race lost — another admin resolved the row during our LLM
            # call. Read the current status so the audit row's
            # to_status reflects reality (not what we expected).
            cur.execute(
                "SELECT processing_status::text FROM agenda_items WHERE id = %s",
                (item_id,),
            )
            current = cur.fetchone()
            current_status = current[0] if current else "unknown"
            _audit(
                cur, item_id,
                from_status=current_status,
                to_status=current_status,
                action="re_prompt_stage2_lost_race",
                actor=actor,
                payload={
                    "override_instruction": override,
                    "would_have_set_status": new_status,
                    "served_model": outcome.served_model,
                    "is_substantive": outcome.rewrite.is_substantive,
                },
            )
            log.info(
                "admin re_prompt_stage2 lost race: item_id=%s actor=%s "
                "current_status=%s",
                item_id, actor, current_status,
            )
        else:
            _audit(
                cur, item_id,
                from_status="cross_stage_conflict",
                to_status=new_status,
                action="re_prompt_stage2",
                actor=actor,
                payload={
                    "override_instruction": override,
                    "reconcile_action": outcome.reconcile_action,
                    "conflicts": outcome.conflicts,
                    "served_model": outcome.served_model,
                    "is_substantive": outcome.rewrite.is_substantive,
                },
            )

    # Raise AFTER the `with db()` block so the race-loss audit row
    # commits before the route handler sees the exception. (db() rolls
    # back on any exception inside the block — raising in-block would
    # discard the audit row we just wrote.)
    if race_lost:
        raise ConflictAlreadyResolvedError(
            f"item {item_id} was resolved by another admin during the "
            "LLM call (current status: " + current_status + ")"
        )

    log.info(
        "admin re_prompt_stage2: item_id=%s actor=%s reconcile=%s",
        item_id, actor, outcome.reconcile_action,
    )
    return ResolutionResult(
        item_id=item_id,
        new_status=new_status,
        action="re_prompt_stage2",
        success=success,
        detail=(
            "Stage 2 re-ran with override; reconcile accepted."
            if success else
            "Stage 2 re-ran but reconcile still found conflicts. "
            "Try Edit Stage 1 facts or Accept Stage 2."
        ),
    )


# ---------------------------------------------------------------------------
# Action 4 — Edit Stage 1 facts (correct facts + Stage 2 re-run)
# ---------------------------------------------------------------------------


def edit_stage_1_facts(item_id: int, *,
                        new_facts_json: dict,
                        actor: str,
                        reason: str | None = None) -> ResolutionResult:
    """Admin corrects misclassified Stage 1 facts; system re-runs Stage 2
    with the corrected facts.

    new_facts_json is validated via the StructuredFacts Pydantic model.
    On validation failure raises ConflictValidationError.

    Persistence + reconciliation matches re_prompt_stage_2: if reconcile
    accepts -> completed; if reconcile still conflicts -> status stays at
    cross_stage_conflict.

    Raises LookupError if item not in cross_stage_conflict.
    Raises ConflictAlreadyResolvedError on TOCTOU race-loss (decision #12).
    """
    if reason is not None:
        reason = reason.strip()[:REASON_MAX] or None

    # Validate via Pydantic before any DB write.
    try:
        facts = StructuredFacts.model_validate(new_facts_json)
    except Exception as e:  # pydantic.ValidationError or otherwise
        raise ConflictValidationError(f"new_facts_json failed validation: {e}")

    # Persist the corrected facts in the SAME transaction that loads + audits.
    with db() as conn, conn.cursor() as cur:
        item = _load_conflict_item(cur, item_id)
        if item is None:
            raise LookupError(f"item {item_id} not in cross_stage_conflict")

        # Replace extracted_facts before the LLM call so the audit row's
        # payload references the canonicalized JSON the model_dump emits.
        canon_facts = facts.model_dump(mode="json")
        cur.execute(
            "UPDATE agenda_items SET extracted_facts = %s::jsonb WHERE id = %s",
            (json.dumps(canon_facts), item_id),
        )

    # Run Stage 2 outside the transaction (LLM I/O); refetch the item with
    # the now-current facts JSON for the rerun helper.
    outcome = _rerun_stage2(item, facts, override_instruction=None)

    success = outcome.reconcile_action == "accept"
    new_status = "completed" if success else "cross_stage_conflict"

    score_overrides_payload = {
        "conflicts": outcome.conflicts,
        "original_ai_significance": outcome.score_overrides_obj.original_ai_significance,
        "final_significance": outcome.score_overrides_obj.final_significance,
        "original_ai_consent": outcome.score_overrides_obj.original_ai_consent,
        "final_consent": outcome.score_overrides_obj.final_consent,
        "triggers": outcome.score_overrides_obj.triggers,
        "admin_facts_edit": True,
    }

    # Decision #12 — TOCTOU guard, same shape as re_prompt_stage_2. The
    # initial extracted_facts UPDATE earlier in this function is also at
    # risk; if a concurrent admin flipped the row to 'completed' between
    # _load_conflict_item and that UPDATE, the early UPDATE silently
    # affected 0 rows but the LLM call still ran. We still detect the
    # race here at persistence time and audit it. (Hardening the early
    # facts UPDATE the same way is possible but adds a transaction round
    # trip; the cost of running an extra LLM call on a lost race is the
    # tradeoff we accept for v1.)
    with db() as conn, conn.cursor() as cur:
        if success:
            cur.execute(
                """
                UPDATE agenda_items
                   SET headline = %s,
                       why_it_matters = %s,
                       significance_score = %s,
                       consent_placement_score = %s,
                       score_overrides = %s::jsonb,
                       processing_status = 'completed'::processing_status_enum
                 WHERE id = %s
                   AND processing_status = 'cross_stage_conflict'::processing_status_enum
                """,
                (
                    outcome.rewrite.headline,
                    outcome.rewrite.why_it_matters,
                    outcome.score_overrides_obj.final_significance,
                    outcome.score_overrides_obj.final_consent,
                    json.dumps(score_overrides_payload),
                    item_id,
                ),
            )
        else:
            cur.execute(
                """
                UPDATE agenda_items
                   SET score_overrides = %s::jsonb
                 WHERE id = %s
                   AND processing_status = 'cross_stage_conflict'::processing_status_enum
                """,
                (json.dumps(score_overrides_payload), item_id),
            )

        race_lost = cur.rowcount == 0
        if race_lost:
            cur.execute(
                "SELECT processing_status::text FROM agenda_items WHERE id = %s",
                (item_id,),
            )
            current = cur.fetchone()
            current_status = current[0] if current else "unknown"
            _audit(
                cur, item_id,
                from_status=current_status,
                to_status=current_status,
                action="edit_stage1_facts_lost_race",
                actor=actor,
                reason=reason,
                payload={
                    "new_facts_json": canon_facts,
                    "would_have_set_status": new_status,
                    "served_model": outcome.served_model,
                    "is_substantive": outcome.rewrite.is_substantive,
                },
            )
            log.info(
                "admin edit_stage1_facts lost race: item_id=%s actor=%s "
                "current_status=%s",
                item_id, actor, current_status,
            )
        else:
            _audit(
                cur, item_id,
                from_status="cross_stage_conflict",
                to_status=new_status,
                action="edit_stage1_facts",
                actor=actor,
                reason=reason,
                payload={
                    "new_facts_json": canon_facts,
                    "reconcile_action": outcome.reconcile_action,
                    "conflicts": outcome.conflicts,
                    "served_model": outcome.served_model,
                    "is_substantive": outcome.rewrite.is_substantive,
                },
            )

    # Raise after the `with db()` block so the race-loss audit row
    # commits before the route handler sees the exception.
    if race_lost:
        raise ConflictAlreadyResolvedError(
            f"item {item_id} was resolved by another admin during the "
            "LLM call (current status: " + current_status + ")"
        )

    log.info(
        "admin edit_stage1_facts: item_id=%s actor=%s reconcile=%s",
        item_id, actor, outcome.reconcile_action,
    )
    return ResolutionResult(
        item_id=item_id,
        new_status=new_status,
        action="edit_stage1_facts",
        success=success,
        detail=(
            "Facts corrected; Stage 2 re-ran and reconcile accepted."
            if success else
            "Facts corrected and Stage 2 re-ran, but reconcile still "
            "found conflicts. Review the updated reasons."
        ),
    )
