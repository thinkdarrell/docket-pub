"""JSON schemas for output_config.format and the pydantic models that validate responses.

Every object is closed (additionalProperties false) and lists every property
in `required`; optional values are nullable types. Keep the pydantic models
and the dicts in sync: the schema is what the API enforces, the model is what
the stage code trusts.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

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

# The API caps union-typed (nullable) parameters at 16 per schema, and the events schema
# would carry 30. So detail strings are plain strings where "" means "not applicable" and
# detail lists are plain arrays where [] means the same; EventDetail converts both back to
# None. Integers and the top-level event fields stay nullable (8 unions in all).
_S = {"type": "string"}
EVENT_DETAIL_SCHEMA = _obj({
    "action": _S, "to_date": _S, "as_stated": _S,
    "items": _arr({"type": "integer"}),
    "requested_by": _S, "mover": _S, "seconder": _S,
    "what_changed": _S, "result": _S,
    "yeas": _nullable("integer"), "nays": _nullable("integer"), "abstentions": _nullable("integer"),
    "roll_call_names": _STR_ARR,
    "method": _S, "stated_reason": _S, "statute_cite": _S,
    "member": _S, "kind": _S, "ruling": _S,
    "present": _STR_ARR,
    "absent": _STR_ARR,
    "clock_time": _S, "speaker_text": _S, "topic": _S,
    # Floor-added items have no agenda_items row (PR #104 notes): name them here, leave agenda_item_refs empty.
    "unlisted_item": _S,
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
        # The API rejects an enum next to a ["string", "null"] type; the Literal in Verdict enforces the values.
        "category": _nullable("string"),
        "severity": _nullable("string"),
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

    @model_validator(mode="before")
    @classmethod
    def _empty_means_none(cls, data):
        """The API schema uses "" / [] for "not applicable" (see EVENT_DETAIL_SCHEMA)."""
        if isinstance(data, dict):
            return {k: (None if v == "" or v == [] else v) for k, v in data.items()}
        return data

    def compact(self) -> dict:
        """Only the non-null fields, for the JSONB column."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


class ExtractedEvent(BaseModel):
    event_type: Literal[
        "item_opened", "item_deferred", "consent_amendment", "motion", "second", "amendment", "vote",
        "executive_session_motion", "recusal", "procedural_ruling", "roll_call", "recess",
        "reconvene", "adjourn", "public_comment", "statement",
    ]
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
    category: Literal["vote_outcome", "omission", "addition", "wording", "sequence", "speaker"] | None
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
    category: Literal["vote_outcome", "omission", "addition", "wording", "sequence", "speaker"]
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
