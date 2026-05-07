"""Stage 1 — Structured fact extraction.

Calls Haiku 4.5 using Anthropic's tool-use API to enforce the StructuredFacts
schema, then validates the returned dict through Pydantic.

Using tools= + tool_choice= forces Anthropic to return input matching the
declared input_schema — the same pattern used in the v2 pipeline (client.py).
Without this, Haiku invents its own schema (e.g. returning vendor_name /
dollar_amount / project_name / action_type='procurement_award').

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
section 2.3, decisions #36-39, #87, #91, #94.
"""

from __future__ import annotations

import logging

import anthropic

from docket.ai.cache import cache_get, cache_key, cache_put
from docket.ai.exceptions import AIPermanentRowError
from docket.ai.extraction_schema import StructuredFacts

log = logging.getLogger(__name__)

EXTRACTION_PROMPT_VERSION = 1

# Decision #94(a): max_retries=0 so 429s bubble up to AdaptiveWorkerPool
# (decision #81) instead of being silently retried by the SDK.
anthropic_client = anthropic.Anthropic(max_retries=0)


STAGE1_TOOL = {
    "name": "submit_extracted_facts",
    "description": "Submit the structured facts extracted from one agenda item.",
    "input_schema": {
        "type": "object",
        "required": [
            "funding_source", "counterparty", "procurement_method", "location",
            "action_type", "next_steps", "parcels_affected", "acres_affected",
        ],
        "properties": {
            "funding_source": {
                "type": "string",
                "enum": [
                    "general_fund", "arpa", "esser", "cares", "state_grant",
                    "federal_grant", "bond", "special_tax", "private", "sponsorship",
                    "tif", "capital_improvement", "mixed", "unknown",
                ],
            },
            "counterparty": {"type": ["string", "null"]},
            "procurement_method": {
                "type": "string",
                "enum": [
                    "competitive", "sole_source", "no_bid", "rfp",
                    "emergency", "unknown", "not_applicable",
                ],
            },
            "location": {
                "type": ["object", "null"],
                "properties": {
                    "ward_or_district": {"type": ["string", "null"]},
                    "neighborhood": {"type": ["string", "null"]},
                    "address": {"type": ["string", "null"]},
                    "parcel_id": {"type": ["string", "null"]},
                },
            },
            "action_type": {
                "type": "string",
                "enum": [
                    "contract_award", "contract_amendment", "ordinance", "resolution",
                    "appointment_executive", "appointment_board", "appointment_advisory",
                    "zoning", "demolition", "weed_abatement", "tax_abatement",
                    "settlement", "emergency_procurement", "appropriation",
                    "budget_amendment", "proclamation", "public_hearing_set",
                    "annexation", "liquor_license", "right_of_way", "bid_rejection",
                    "other",
                ],
            },
            "next_steps": {
                "type": "object",
                "properties": {
                    "committee_referral": {"type": ["string", "null"]},
                    "public_hearing_date": {"type": ["string", "null"]},
                    "public_hearing_time": {"type": ["string", "null"]},
                    "comment_period_end": {"type": ["string", "null"]},
                    "implementation_date": {"type": ["string", "null"]},
                },
            },
            "parcels_affected": {"type": ["integer", "null"]},
            "acres_affected": {"type": ["number", "null"]},
        },
    },
}


SYSTEM_PROMPT = """You extract structured facts from a single municipal-government agenda item.

Do not invent facts. If a field cannot be determined from the input, return null.

For action_type='appointment*', also classify the appointment as one of:
  - appointment_executive: Mayor's cabinet, Department Head, Police Chief,
    City Attorney, City Clerk, Finance Director, Fire Chief, Library Director
  - appointment_board: Board of Education, Board of Adjustment, Planning
    Commission, Housing Authority, Library Board, BJCTA, IDB
  - appointment_advisory: citizen advisory committees, task forces,
    ad-hoc bodies, ceremonial proclamation honorees

For procurement_method, choose the most specific applicable value:
  - competitive, sole_source, no_bid, rfp, emergency, unknown, not_applicable

For next_steps, extract ONLY explicitly-stated future actions.
Do not infer. If the resolution doesn't say "set for public hearing on June 5,"
do not populate public_hearing_date.

Return ALL the schema's keys; use null when unknown.
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


def build_user_message(item) -> str:
    """Build the per-item user message. `item` is any object exposing the
    required attributes (title, description, sponsor, dollars_amount, topic,
    is_consent)."""
    parts = [
        f"Title: {item.title or ''}",
        f"Description: {item.description or ''}",
        f"Sponsor: {item.sponsor or 'unknown'}",
        f"Dollar amount: ${item.dollars_amount or 0:,}",
        f"Topic (legacy): {item.topic or 'uncategorized'}",
        f"Is on consent agenda: {bool(item.is_consent)}",
    ]
    return "\n".join(parts)


def extract_facts_for_item(item, *, model: str = "claude-haiku-4-5-20251001") -> tuple[StructuredFacts, str]:
    """Run Stage 1 against a single item.

    Returns (StructuredFacts, model_id_returned). Caller persists into
    `agenda_items.extracted_facts` and `agenda_items.ai_extraction_version`.

    Cache hits return the previously-served response without re-calling
    the API. Cache key includes the model ID returned in the prior
    response — version bumps invalidate.
    """
    user_msg = build_user_message(item)

    # Try cache first (canonical input is the user_msg)
    pre_cache = cache_key(model, EXTRACTION_PROMPT_VERSION, user_msg)
    cached = cache_get(pre_cache)
    if cached is not None:
        log.debug("stage 1 cache hit for item %s", getattr(item, 'id', '?'))
        # Re-validate via Pydantic in case schema tightened across versions
        return StructuredFacts.model_validate(cached['response']), cached['model']

    # Cache miss — call the API using tool-use to enforce the StructuredFacts schema
    response = anthropic_client.messages.create(
        model=model,
        max_tokens=1024,
        tools=[STAGE1_TOOL],
        tool_choice={"type": "tool", "name": STAGE1_TOOL["name"]},
        system=[
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user", "content": user_msg}],
    )

    # Anthropic may serve a slightly different model variant; key off that
    served_model = response.model

    payload = _extract_tool_input(response, STAGE1_TOOL["name"])
    facts = StructuredFacts.model_validate(payload)

    # Cache against the served model id (decision #42).
    # Guarded: a transient DB error here would otherwise drop an
    # already-billed Anthropic result on the floor.
    real_key = cache_key(served_model, EXTRACTION_PROMPT_VERSION, user_msg)
    try:
        cache_put(real_key, model=served_model, prompt_version=EXTRACTION_PROMPT_VERSION,
                  payload={'response': payload, 'model': served_model})
    except Exception:
        log.warning("stage 1 cache_put failed for item %s; result still returned",
                    getattr(item, 'id', '?'), exc_info=True)

    return facts, served_model


def persist_extraction(cur, item_id: int, facts: StructuredFacts, version: int) -> None:
    """Write Stage 1 output to agenda_items.extracted_facts.

    Caller controls the transaction. `cur` is a psycopg cursor.
    """
    cur.execute(
        """
        UPDATE agenda_items
        SET extracted_facts = %s::jsonb,
            ai_extraction_version = %s,
            processing_status = 'extracted'::processing_status_enum
        WHERE id = %s
        """,
        [facts.model_dump_json(), version, item_id],
    )
