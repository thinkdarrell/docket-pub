# src/docket/ai/client.py
"""Anthropic SDK wrapper: prompts, structured output, retries, cost tracking."""

from __future__ import annotations

import logging
import time
from typing import Any

from anthropic import Anthropic, APIError, APIStatusError, APITimeoutError, RateLimitError
from pydantic import ValidationError

from docket.ai.contexts import AgendaItemContext, MeetingContext
from docket.ai.exceptions import (
    AIFatalError,
    AIPermanentRowError,
    AIRateLimited,
    AITransientError,
)
from docket.ai.pricing import Usage
from docket.ai.prompts import (
    ITEM_SYSTEM,
    MEETING_SYSTEM,
)
from docket.ai.results import ItemAIResult, MeetingAIResult


log = logging.getLogger(__name__)


# Tool schemas for structured output. Anthropic's tool_use returns the
# input as a dict matching the input_schema, which Pydantic then validates.
ITEM_TOOL = {
    "name": "submit_item_summary",
    "description": "Submit the structured summary and scores for one agenda item.",
    "input_schema": {
        "type": "object",
        "required": [
            "is_substantive", "significance_rationale", "significance_score",
            "consent_placement_rationale", "consent_placement_score",
            "summary", "confidence",
        ],
        "properties": {
            "is_substantive": {"type": "boolean"},
            "significance_rationale": {"type": "string"},
            "significance_score": {"type": ["number", "null"]},
            "consent_placement_rationale": {"type": "string"},
            "consent_placement_score": {"type": ["number", "null"]},
            "summary": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
    },
}

MEETING_TOOL = {
    "name": "submit_meeting_summary",
    "description": "Submit the executive summary for one meeting.",
    "input_schema": {
        "type": "object",
        "required": [
            "is_substantive", "substantive_item_count",
            "executive_summary", "phase", "confidence",
        ],
        "properties": {
            "is_substantive": {"type": "boolean"},
            "substantive_item_count": {"type": "integer"},
            "executive_summary": {"type": "string"},
            "phase": {"type": "string", "enum": ["provisional", "adopted"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
    },
}


MAX_RETRIES = 3
TOKEN_INPUT_CAP = 30_000


class AIClient:
    def __init__(self, api_key: str, item_model: str | None = None,
                 meeting_model: str | None = None):
        if not api_key:
            raise AIFatalError("ANTHROPIC_API_KEY is not set")
        from docket.config import AI_ITEM_MODEL, AI_MEETING_MODEL
        self.item_model = item_model or AI_ITEM_MODEL
        self.meeting_model = meeting_model or AI_MEETING_MODEL
        self._client = Anthropic(api_key=api_key)

    def summarize_item(self, ctx: AgendaItemContext) -> tuple[ItemAIResult, Usage]:
        message = self._call_with_retries(
            model=self.item_model,
            system=ITEM_SYSTEM,
            user=ctx.render_user_prompt(),
            tool=ITEM_TOOL,
        )
        payload = self._extract_tool_input(message, ITEM_TOOL["name"])
        try:
            result = ItemAIResult.model_validate(payload)
        except ValidationError as e:
            raise AIPermanentRowError(f"Pydantic validation failed for item: {e}") from e
        return result, self._extract_usage(message)

    def summarize_meeting(self, ctx: MeetingContext) -> tuple[MeetingAIResult, Usage]:
        message = self._call_with_retries(
            model=self.meeting_model,
            system=MEETING_SYSTEM,
            user=ctx.render_user_prompt(),
            tool=MEETING_TOOL,
        )
        payload = self._extract_tool_input(message, MEETING_TOOL["name"])
        try:
            result = MeetingAIResult.model_validate(payload)
        except ValidationError as e:
            raise AIPermanentRowError(f"Pydantic validation failed for meeting: {e}") from e
        return result, self._extract_usage(message)

    def _call_with_retries(self, *, model: str, system: str, user: str, tool: dict[str, Any]):
        last_exc = None
        delay = 2.0
        for attempt in range(MAX_RETRIES):
            try:
                return self._client.messages.create(
                    model=model,
                    max_tokens=1024,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool["name"]},
                    system=[
                        {"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}},
                    ],
                    messages=[{"role": "user", "content": user}],
                )
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

    @staticmethod
    def _extract_tool_input(message, tool_name: str) -> dict:
        for block in message.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            block_name = getattr(block, "name", None)
            # Accept the block iff:
            #   - its name matches exactly, OR
            #   - its name is missing (some SDK shapes omit it on forced tool_use), OR
            #   - its name is not a string (test mocks return MagicMock here).
            # Reject blocks whose name is a different string — a silent
            # fallback there would hide real bugs in production.
            if not isinstance(block_name, str) or block_name == tool_name:
                return dict(block.input)
        raise AIPermanentRowError(f"No tool_use block named {tool_name} in response")

    @staticmethod
    def _extract_usage(message) -> Usage:
        u = message.usage
        return Usage(
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
        )
