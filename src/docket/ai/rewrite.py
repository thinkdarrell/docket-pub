"""Stage 2 — Smart Brevity LLM rewrite worker.

Receives a single agenda item + Stage 1 StructuredFacts, calls Haiku 4.5
using Anthropic's tool-use API to enforce the ItemRewrite schema, and returns
the validated rewrite + the exact model ID Anthropic served.

The `extra_instruction` parameter is used by the reconcile auto-retry path
(Task B5) to inject an override prompt appended at the end of the user message.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
section 3.1–3.2, decisions #42, #87, #91, #94.
"""

from __future__ import annotations

import json
import logging

import anthropic

from docket.ai.cache import cache_get, cache_key, cache_put
from docket.ai.exceptions import AIPermanentRowError
from docket.ai.extraction_schema import StructuredFacts
from docket.ai.rewrite_schema import ItemRewrite

log = logging.getLogger(__name__)

ITEM_REWRITE_PROMPT_VERSION = 3

# Decision #94(a): max_retries=0 so 429s bubble up to AdaptiveWorkerPool
# instead of being silently retried by the SDK.
anthropic_client = anthropic.Anthropic(max_retries=0)


STAGE2_TOOL = {
    "name": "submit_item_rewrite",
    "description": "Submit the citizen-facing rewrite for one agenda item.",
    "input_schema": {
        "type": "object",
        "required": [
            "is_substantive", "headline", "why_it_matters",
            "significance_rationale", "significance_score",
            "consent_placement_rationale", "consent_placement_score",
            "suggested_badge_slugs", "confidence",
        ],
        "properties": {
            "is_substantive": {"type": "boolean"},
            "headline": {"type": ["string", "null"]},
            "why_it_matters": {"type": ["string", "null"]},
            "significance_rationale": {"type": "string"},
            "significance_score": {"type": ["number", "null"]},
            "consent_placement_rationale": {"type": "string"},
            "consent_placement_score": {"type": ["number", "null"]},
            "suggested_badge_slugs": {
                "type": "array",
                "items": {"type": "string"},
            },
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
    },
}


SYSTEM_PROMPT = """You are rewriting a single agenda item for citizens reading docket.pub.

You receive:
  (a) the raw item title + description, and
  (b) structured facts extracted in Stage 1: funding source, counterparty,
      procurement method, location (ward/district, neighborhood, address,
      parcel_id), action type, next steps (committee, hearing date/time,
      comment-period end, implementation date).

FIRST decide: is this a substantive item or a procedural item?

PROCEDURAL items are routine meeting mechanics whose title already
conveys everything: roll call, pledge of allegiance, invocation,
motion to adjourn, approval of prior minutes, opening of public comment,
"minutes not ready" notices, recognition of visitors, awards/presentations,
reading of communications, vouchers/bills/payroll for payment, claims,
recess, executive session close-out. For these:
  - Set is_substantive = false
  - Set headline = null, why_it_matters = null
  - Set both numeric values to null
  - Set rationales = "" (empty)
  - Set suggested_badge_slugs = []
  - Set confidence based on how clearly procedural the item is

SUBSTANTIVE items are decisions, debates, contracts, ordinances,
appointments, zoning cases, settlements, abatements (tax or weed),
liquor licenses, annexations — anything whose outcome matters. For these:

(1) Write a HEADLINE (≤60 chars) — result-oriented, active voice.
    Must be ≥10 characters with substantive content (decision #87).

    Good headlines:
      "Council awards $4.2M HVAC contract to Acme Industries"
      "Settlement: City pays $250K for 2024 use-of-force claim"
      "Sole-source: Flock licenses extended 5 years for $1.8M"
      "BPRA: 14 blighted properties move toward demolition"
      "Land Bank acquires 6 tax-delinquent parcels in District 4"
      "Body-cam footage release rules tighten to 30 days"
      "Annexation: Hidden Lake parcel joins city limits"

    Bad headlines (would fail validation or quality bar):
      "Approval"                    ← too short (<10 chars)
      "Item passed"                 ← lazy, no info
      "Resolution No. 2026-0142"    ← procedural identifier, not content
      "Authorizes Mayor"            ← city-first framing
      "Whereas the Council..."      ← banned legalese
      "$1.8M contract"              ← missing what/who
      "Important decision today"    ← vague, no actor or consequence

(2) Write WHY IT MATTERS (≤200 chars; one sentence preferred, two short
    sentences allowed for items with multiple impact vectors).

    Identify the DIRECT CONSEQUENCE for residents. Ask: will this change
    their taxes, their commute, their property rights, their utility costs,
    or their neighborhood's safety? If no direct consequence exists,
    describe the specific change to public services or city operations.

    Use RESIDENT-first framing, not CITY-first framing.

    Good (resident-first): "Higher water rates for homes in Wards 4 and 7
      starting August. Affects ~3,400 households."
    Good (resident-first): "Smoother commute on Highway 280; project
      finishes summer 2027."
    Good (resident-first): "Body-cam footage rules tighten — police must
      release video within 30 days of force incidents."
    Good (resident-first): "Land Bank takes over abandoned house at 123
      Main; clears tax debt to make it sale-ready."
    Bad (city-first):      "Authorizes the Mayor to enter into an agreement
      to fund operations of the Birmingham Water Works."
    Bad (procedure-first): "Approves contract amendment #4 with vendor X."
    Bad (vague):           "Important policy change affecting residents."
    Bad (jargon-laden):    "Whereas, pursuant to Section 2.31, hereby
      authorizing said procurement of aforesaid services."

(3) Score significance_score 0-10 (0 = trivial, 10 = major impact).
    Write the rationale BEFORE the numeric value.

(4) Score consent_placement_score 0-10 (0 = should never be on consent /
    high public interest; 10 = perfect consent candidate / routine).
    Write the rationale BEFORE the numeric value.

(5) Suggest BADGE SLUGS from the per-city policy badge list provided
    in the user message. Include only badges you are reasonably confident
    apply. Empty list is acceptable.

BANNED WORDS — HARD (avoid entirely):
  Whereas, Heretofore, Hereinafter, Hereby, Hereto, Hereof, Notwithstanding,
  Aforesaid, Aforementioned, Pursuant to, Be it resolved, In the matter of,
  For and on behalf of.

BANNED WORDS — SOFT (replace with natural English):
  Appropriation → "set aside" / "spend"
  Resolution → "decision" / "vote" (or drop entirely)
  Ordinance → "law" / "rule"
  Procurement → "buy" / "purchase"
  Allocation → "set aside"
  Encumber / Encumbrance → "commit funds"
  Authorize (passive) → "approve" / "let"

Write in active voice. Lead with the RESULT, not the PROCESS.

NEGATIVE INSTRUCTIONS — do NOT lead with phrases like:
  "The City Council approved..."
  "This resolution authorizes..."
  "The Mayor is hereby authorized to..."
  "By a vote of X-Y, the Council..."
Start the headline and why_it_matters DIRECTLY with the consequence.

Confidence: "high" if the item's text is unambiguous AND Stage 1 facts
are populated; "medium" if title is clear but details are sparse;
"low" if you had to guess at intent or Stage 1 returned mostly nulls.
"""


def _extract_tool_input(response, tool_name: str) -> dict:
    """Extract the input dict from the matching tool_use block in the response.

    Mirrors client.py AIClient._extract_tool_input.
    """
    for block in response.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        block_name = getattr(block, "name", None)
        # Accept the block iff:
        #   - its name matches exactly, OR
        #   - its name is missing (some SDK shapes omit it on forced tool_use), OR
        #   - its name is not a string (test mocks return MagicMock here).
        if not isinstance(block_name, str) or block_name == tool_name:
            return dict(block.input)
    raise AIPermanentRowError(f"No tool_use block named {tool_name} in response")


def build_user_message(
    item,
    facts: StructuredFacts,
    enabled_policy_badges: list[str],
    *,
    extra_instruction: str | None = None,
) -> str:
    """Build the per-item user message for Stage 2.

    `item` is any object exposing: title, description, sponsor,
    dollars_amount, topic, is_consent, and city_name.
    """
    city_name = getattr(item, 'city_name', 'Unknown')
    policy_slugs_csv = ", ".join(enabled_policy_badges) if enabled_policy_badges else "(none)"
    facts_json = json.dumps(facts.model_dump(mode='json'), indent=2)

    parts = [
        f"City: {city_name}",
        f"Available policy badge slugs: {policy_slugs_csv}",
        "",
        f"Title: {item.title or ''}",
        f"Description: {item.description or ''}",
        f"Sponsor: {item.sponsor or 'unknown'}",
        f"Dollar amount: {item.dollars_amount or 0}",
        f"Topic (legacy): {item.topic or 'uncategorized'}",
        f"Is on consent agenda: {bool(item.is_consent)}",
        "",
        "Stage 1 structured facts:",
        facts_json,
    ]

    if extra_instruction:
        parts.append("")
        parts.append(extra_instruction)

    return "\n".join(parts).rstrip()


def rewrite_item(
    item,
    facts: StructuredFacts,
    enabled_policy_badges: list[str],
    *,
    model: str = "claude-haiku-4-5-20251001",
    extra_instruction: str | None = None,
) -> tuple[ItemRewrite, str]:
    """Run Stage 2 against a single item.

    Returns (ItemRewrite, model_id_returned). Caller persists into
    `agenda_items.headline`, `agenda_items.why_it_matters`, etc.

    Cache hits return the previously-served response without re-calling
    the API. Cache key includes the full user message so any input change
    invalidates automatically.
    """
    user_msg = build_user_message(item, facts, enabled_policy_badges,
                                  extra_instruction=extra_instruction)

    # Try cache first (canonical input is the full user_msg)
    pre_cache = cache_key(model, ITEM_REWRITE_PROMPT_VERSION, user_msg)
    cached = cache_get(pre_cache)
    if cached is not None:
        log.debug("stage 2 cache hit for item %s", getattr(item, 'id', '?'))
        # Re-validate via Pydantic in case schema tightened across versions
        return ItemRewrite.model_validate(cached['response']), cached['model']

    # Cache miss — call the API using tool-use to enforce the ItemRewrite schema
    response = anthropic_client.messages.create(
        model=model,
        max_tokens=1024,
        tools=[STAGE2_TOOL],
        tool_choice={"type": "tool", "name": STAGE2_TOOL["name"]},
        system=[
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user", "content": user_msg}],
    )

    # Anthropic may serve a slightly different model variant; key off that
    served_model = response.model

    payload = _extract_tool_input(response, STAGE2_TOOL["name"])
    rewrite = ItemRewrite.model_validate(payload)

    # Cache against the served model id (decision #42).
    # Guarded: a transient DB error here would otherwise drop an
    # already-billed Anthropic result on the floor.
    real_key = cache_key(served_model, ITEM_REWRITE_PROMPT_VERSION, user_msg)
    try:
        cache_put(real_key, model=served_model, prompt_version=ITEM_REWRITE_PROMPT_VERSION,
                  payload={'response': payload, 'model': served_model})
    except Exception:
        log.warning("stage 2 cache_put failed for item %s; result still returned",
                    getattr(item, 'id', '?'), exc_info=True)

    return rewrite, served_model
