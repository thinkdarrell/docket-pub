"""Stage 1 — Structured fact extraction.

Calls Haiku 4.5 with a system prompt + user message, parses the JSON
response into a StructuredFacts Pydantic model, and returns the
validated facts + the exact model ID Anthropic served.

Spec: docs/superpowers/specs/2026-05-05-impact-first-refactor-design.md
section 2.3, decisions #36-39, #87, #91, #94.
"""

from __future__ import annotations

import json
import logging
import re

import anthropic

from docket.ai.cache import cache_get, cache_key, cache_put
from docket.ai.extraction_schema import StructuredFacts

log = logging.getLogger(__name__)

EXTRACTION_PROMPT_VERSION = 1

# Decision #94(a): max_retries=0 so 429s bubble up to AdaptiveWorkerPool
# (decision #81) instead of being silently retried by the SDK.
anthropic_client = anthropic.Anthropic(max_retries=0)


_MARKDOWN_FENCE_RE = re.compile(r'^```(?:json)?\s*\n?', re.MULTILINE)
_MARKDOWN_FENCE_END_RE = re.compile(r'\n?```\s*$', re.MULTILINE)


def _strip_markdown_fences(text: str) -> str:
    """Decision #94(b): strip ```json or ``` wrappers before json.loads().

    Some Haiku responses wrap JSON in markdown fences despite the system
    prompt asking for raw JSON. This avoids JSONDecodeErrors.
    """
    text = text.strip()
    text = _MARKDOWN_FENCE_RE.sub('', text, count=1)
    text = _MARKDOWN_FENCE_END_RE.sub('', text, count=1)
    return text.strip()


SYSTEM_PROMPT = """You extract structured facts from a single municipal-government agenda item.
You output JSON matching the schema below — no prose, no markdown, no commentary.

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

    # Cache miss — call the API
    response = anthropic_client.messages.create(
        model=model,
        max_tokens=1024,
        system=[
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user", "content": user_msg}],
    )

    # Anthropic may serve a slightly different model variant; key off that
    served_model = response.model

    raw_text = response.content[0].text
    # Decision #94(b): strip markdown fences before json.loads
    raw_text = _strip_markdown_fences(raw_text)
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Stage 1 returned non-JSON: {raw_text[:200]!r}") from e

    facts = StructuredFacts.model_validate(parsed)

    # Cache against the served model id (decision #42)
    real_key = cache_key(served_model, EXTRACTION_PROMPT_VERSION, user_msg)
    cache_put(real_key, model=served_model, prompt_version=EXTRACTION_PROMPT_VERSION,
              payload={'response': parsed, 'model': served_model})

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
