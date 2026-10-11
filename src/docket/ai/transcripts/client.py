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
