"""Exceptions raised by the AI pipeline."""

from __future__ import annotations


class AIError(Exception):
    """Base for all AI pipeline errors."""


class AIRateLimited(AIError):
    """Anthropic API returned 429 after retries exhausted. Worker should stop the batch."""


class AITransientError(AIError):
    """Anthropic API returned a 5xx or timeout after retries. Worker should skip the row."""


class AIFatalError(AIError):
    """Configuration error (bad API key, missing model). Worker should exit."""


class AIPermanentRowError(AIError):
    """This row cannot be processed and should be marked completed_failed."""


class TranscriptHeld(AIError):
    """A transcript stage must stop and park the row as needs_review.

    ``reason`` is the short machine label stored in
    ``transcripts.needs_review_reason`` (token_ceiling, candidate_cap,
    schema_invalid, refusal, max_tokens, permanent); the message is the detail.
    """

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason
