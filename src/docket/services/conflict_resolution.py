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

from docket.ai.extraction_schema import StructuredFacts
# NOTE: rewrite_item is re-exported here as a module-level symbol for
# backward compatibility with existing G4 TOCTOU tests that monkeypatch
# ``docket.services.conflict_resolution.rewrite_item``. Post-B5 refactor,
# this module no longer calls rewrite_item directly — the pipeline owns
# the Stage 2 LLM call. Tests that want to intercept Stage 2 should
# monkeypatch ``docket.ai.pipeline.rewrite_item`` going forward.
from docket.ai.rewrite import rewrite_item  # noqa: F401  (test-compat re-export)
from docket.db import db

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

    The SELECT uses ``FOR UPDATE OF ai`` so concurrent admin actions on the
    same agenda_items row serialize at this point. This closes the
    read-then-write race window for accept_stage_1 / accept_stage_2 (where
    two admins with different manual headlines would otherwise both pass
    through and the later writer would silently overwrite). For the
    LLM-touching paths (re_prompt_stage_2, edit_stage_1_facts) the lock
    releases when the surrounding ``with db()`` block exits — i.e., before
    the LLM call — so those paths still rely on the TOCTOU predicates on
    their persistence UPDATEs (decision #12) to catch races that happen
    during the LLM window.
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
           FOR UPDATE OF ai
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


class _ItemView:
    """Lightweight item view for the v3 pipeline.

    pipeline._rerun_from_stage2 expects an object exposing: id, title,
    description, sponsor, dollars_amount, topic, is_consent, city_name,
    AND city_id (decision #92: per-city badge writes). This wrapper
    converts a DB row dict into that shape, mapping ``municipality_id``
    → ``city_id`` since the pipeline's contract uses ``city_id``.
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
        # Map municipality_id (DB column) → city_id (pipeline contract).
        self.city_id = item.get("municipality_id")
        # Wave 0's evaluate_data_quality / Stage 2 prompt construction
        # touch these — provide safe defaults since admin paths don't
        # re-run Wave 0 anyway (we're past it; the item is in
        # cross_stage_conflict).
        self.source_type = "agenda"
        self.raw_text = None


def re_prompt_stage_2(item_id: int, *,
                       override_instruction: str,
                       actor: str) -> ResolutionResult:
    """Admin writes a one-liner override; system re-runs Stage 2 via
    pipeline._rerun_from_stage2. The pipeline writes the resolution
    atomically; this function focuses on input validation, TOCTOU
    detection, and audit logging.

    Post-B5: the Stage 2 + 2.5 + reconcile + persist path is centralized
    in docket.ai.pipeline. This function focuses on admin-action
    semantics: input validation, TOCTOU detection, audit logging.

    If the new Stage 2 rewrite reconciles cleanly, the pipeline persists
    the new headline/why_it_matters/scores and the row's status flips
    to 'completed'. If reconcile still finds conflicts, the pipeline
    persists the row at 'cross_stage_conflict' and this function
    records the failed-resolution attempt in the audit log.

    Raises ConflictValidationError on input issues.
    Raises LookupError if item not in cross_stage_conflict.
    Raises ConflictAlreadyResolvedError on TOCTOU race-loss (decision #13).

    Anthropic SDK transient errors (``APIConnectionError``,
    ``RateLimitError``, ``InternalServerError``) propagate unwrapped
    from the pipeline and surface to the Flask route as 500.
    Tightening that to 503 is deferred (B-S6 NICE-TO-HAVE).
    """
    override = override_instruction.strip()
    if len(override) < 1 or len(override) > OVERRIDE_INSTRUCTION_MAX:
        raise ConflictValidationError(
            f"override_instruction must be 1-{OVERRIDE_INSTRUCTION_MAX} chars"
        )

    # Phase 1: load item, validate facts.
    from pydantic import ValidationError as PydanticValidationError
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
        try:
            facts = StructuredFacts.model_validate(item["extracted_facts"])
        except PydanticValidationError as e:
            raise ConflictValidationError(
                f"stored extracted_facts failed validation: {e}"
            )

    # Phase 2: call the pipeline with the concurrency guard (decision #13).
    # The pipeline's Phase C UPDATE has the
    # `AND processing_status = 'cross_stage_conflict'` predicate, so
    # if another admin resolved the row during our LLM call window,
    # the pipeline raises PipelineConcurrencyError and rolls back its
    # whole atomic block (extraction + rewrite + scores + badges).
    from docket.ai.pipeline import (
        PipelineConcurrencyError,
        _rerun_from_stage2,
    )
    item_view = _ItemView(item)
    try:
        pipeline_status = _rerun_from_stage2(
            item_view, facts,
            override_instruction=override,
            expected_status="cross_stage_conflict",
        )
    except PipelineConcurrencyError as e:
        # Race lost. Pipeline already rolled back; write the lost-race
        # audit in a fresh transaction so the trail survives.
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT processing_status::text FROM agenda_items WHERE id = %s",
                (item_id,),
            )
            row = cur.fetchone()
            current_status = row[0] if row else "unknown"
            _audit(
                cur, item_id,
                from_status=current_status,
                to_status=current_status,
                action="re_prompt_stage2_lost_race",
                actor=actor,
                payload={
                    "override_instruction": override,
                    "pipeline_error": str(e),
                    "actual_status_at_lost_race": current_status,
                },
            )
        log.info(
            "admin re_prompt_stage2 lost race: item_id=%s actor=%s "
            "current_status=%s",
            item_id, actor, current_status,
        )
        raise ConflictAlreadyResolvedError(
            f"item {item_id} was resolved by another admin "
            f"during the re-prompt (current status: {current_status})"
        )

    # Phase 3: pipeline succeeded — write the normal audit row.
    # Read score_overrides + headline back so the audit payload carries
    # the same keys G4's tests assert on (reconcile_action, conflicts,
    # final_*).
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT score_overrides, headline, why_it_matters,
                   significance_score, consent_placement_score
              FROM agenda_items WHERE id = %s
            """,
            (item_id,),
        )
        post = cur.fetchone()
        post_overrides = post[0] if post and post[0] else {}
        post_headline = post[1] if post else None
        post_why = post[2] if post else None
        post_sig = post[3] if post else None
        post_consent = post[4] if post else None

        reconcile_action = (
            "mark_cross_stage_conflict"
            if pipeline_status == "cross_stage_conflict"
            else "accept"
        )

        _audit(
            cur, item_id,
            from_status="cross_stage_conflict",
            to_status=pipeline_status,
            action="re_prompt_stage2",
            actor=actor,
            payload={
                "override_instruction": override,
                "pipeline_status": pipeline_status,
                "reconcile_action": reconcile_action,
                "conflicts": post_overrides.get("conflicts", []),
                "final_headline": post_headline,
                "final_why_it_matters": post_why,
                "final_significance": post_sig,
                "final_consent": post_consent,
            },
        )

    log.info(
        "admin re_prompt_stage2: item_id=%s actor=%s status=%s",
        item_id, actor, pipeline_status,
    )
    return ResolutionResult(
        item_id=item_id,
        new_status=pipeline_status,
        action="re_prompt_stage2",
        success=(pipeline_status == "completed"),
        detail=(
            "Stage 2 re-ran with override; reconcile accepted."
            if pipeline_status == "completed" else
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
    with the corrected facts via pipeline._rerun_from_stage2.

    Post-B5: Stage 2 + 2.5 + reconcile + persist are centralized in the
    pipeline. This function focuses on:
      - Pydantic input validation
      - Early ``extracted_facts`` UPDATE with TOCTOU guard (pre-LLM
        race detection saves LLM spend)
      - Late TOCTOU guard via pipeline's ``expected_status``
      - Audit trail (success, early-race-loss, late-race-loss)

    new_facts_json is validated via the StructuredFacts Pydantic model.
    On validation failure raises ConflictValidationError.

    Raises LookupError if item not in cross_stage_conflict.
    Raises ConflictAlreadyResolvedError on TOCTOU race-loss (decision #13).
    """
    if reason is not None:
        reason = reason.strip()
        if len(reason) > REASON_MAX:
            raise ConflictValidationError(
                f"reason must be at most {REASON_MAX} chars"
            )
        reason = reason or None

    # Validate via Pydantic before any DB write. Catch the specific
    # pydantic.ValidationError, not bare Exception, per engineer review.
    from pydantic import ValidationError as PydanticValidationError
    try:
        facts = StructuredFacts.model_validate(new_facts_json)
    except PydanticValidationError as e:
        raise ConflictValidationError(f"new_facts_json failed validation: {e}")

    # Phase 1: load item + pre-LLM TOCTOU-guarded UPDATE of extracted_facts.
    # The early UPDATE saves LLM spend on lost races.
    race_lost_pre_llm = False
    current_status_pre_llm = "unknown"
    canon_facts = facts.model_dump(mode="json")
    with db() as conn, conn.cursor() as cur:
        item = _load_conflict_item(cur, item_id)
        if item is None:
            raise LookupError(f"item {item_id} not in cross_stage_conflict")

        # TOCTOU-guarded UPDATE: a concurrent admin who flipped the row
        # out of cross_stage_conflict between _load_conflict_item and
        # here would otherwise see their just-resolved facts clobbered.
        cur.execute(
            """
            UPDATE agenda_items
               SET extracted_facts = %s::jsonb
             WHERE id = %s
               AND processing_status = 'cross_stage_conflict'::processing_status_enum
            """,
            (json.dumps(canon_facts), item_id),
        )
        if cur.rowcount == 0:
            cur.execute(
                "SELECT processing_status::text FROM agenda_items WHERE id = %s",
                (item_id,),
            )
            current = cur.fetchone()
            current_status_pre_llm = current[0] if current else "unknown"
            _audit(
                cur, item_id,
                from_status=current_status_pre_llm,
                to_status=current_status_pre_llm,
                action="edit_stage1_facts_lost_race_pre_llm",
                actor=actor,
                reason=reason,
                payload={
                    "new_facts_json": canon_facts,
                    "would_have_set_extracted_facts": True,
                    "lost_race_phase": "pre_llm",
                },
            )
            race_lost_pre_llm = True

    # Raise after the `with db()` block so the audit row commits.
    if race_lost_pre_llm:
        log.info(
            "admin edit_stage1_facts lost race pre-LLM: item_id=%s actor=%s "
            "current_status=%s",
            item_id, actor, current_status_pre_llm,
        )
        raise ConflictAlreadyResolvedError(
            f"item {item_id} was resolved by another admin before the "
            "edit-facts LLM call (current status: "
            + current_status_pre_llm + ")"
        )

    # Phase 2: call the pipeline with the late TOCTOU guard
    # (expected_status='cross_stage_conflict'). The pipeline writes
    # everything atomically; if a race fires inside its LLM window, the
    # pipeline raises PipelineConcurrencyError and rolls back.
    from docket.ai.pipeline import (
        PipelineConcurrencyError,
        _rerun_from_stage2,
    )
    item_view = _ItemView(item)
    try:
        pipeline_status = _rerun_from_stage2(
            item_view, facts,
            expected_status="cross_stage_conflict",
        )
    except PipelineConcurrencyError as e:
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT processing_status::text FROM agenda_items WHERE id = %s",
                (item_id,),
            )
            row = cur.fetchone()
            current_status = row[0] if row else "unknown"
            _audit(
                cur, item_id,
                from_status=current_status,
                to_status=current_status,
                action="edit_stage1_facts_lost_race",
                actor=actor,
                reason=reason,
                payload={
                    "new_facts_json": canon_facts,
                    "pipeline_error": str(e),
                    "actual_status_at_lost_race": current_status,
                },
            )
        log.info(
            "admin edit_stage1_facts lost race: item_id=%s actor=%s "
            "current_status=%s",
            item_id, actor, current_status,
        )
        raise ConflictAlreadyResolvedError(
            f"item {item_id} was resolved by another admin during the "
            f"edit-facts LLM call (current status: {current_status})"
        )

    # Phase 3: pipeline succeeded — write the normal audit row.
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT score_overrides, headline, why_it_matters,
                   significance_score, consent_placement_score
              FROM agenda_items WHERE id = %s
            """,
            (item_id,),
        )
        post = cur.fetchone()
        post_overrides = post[0] if post and post[0] else {}
        post_headline = post[1] if post else None
        post_why = post[2] if post else None
        post_sig = post[3] if post else None
        post_consent = post[4] if post else None

        reconcile_action = (
            "mark_cross_stage_conflict"
            if pipeline_status == "cross_stage_conflict"
            else "accept"
        )

        _audit(
            cur, item_id,
            from_status="cross_stage_conflict",
            to_status=pipeline_status,
            action="edit_stage1_facts",
            actor=actor,
            reason=reason,
            payload={
                "new_facts_json": canon_facts,
                "pipeline_status": pipeline_status,
                "reconcile_action": reconcile_action,
                "conflicts": post_overrides.get("conflicts", []),
                "final_headline": post_headline,
                "final_why_it_matters": post_why,
                "final_significance": post_sig,
                "final_consent": post_consent,
            },
        )

    log.info(
        "admin edit_stage1_facts: item_id=%s actor=%s status=%s",
        item_id, actor, pipeline_status,
    )
    return ResolutionResult(
        item_id=item_id,
        new_status=pipeline_status,
        action="edit_stage1_facts",
        success=(pipeline_status == "completed"),
        detail=(
            "Facts corrected; Stage 2 re-ran and reconcile accepted."
            if pipeline_status == "completed" else
            "Facts corrected and Stage 2 re-ran, but reconcile still "
            "found conflicts. Review the updated reasons."
        ),
    )
