import json

import pytest
from pydantic import ValidationError

from docket.ai.transcripts import schemas as S

MIG_EVENT_TYPES = ('item_opened', 'item_deferred', 'consent_amendment', 'motion', 'second',
                   'amendment', 'vote', 'executive_session_motion', 'recusal',
                   'procedural_ruling', 'roll_call', 'recess', 'reconvene', 'adjourn',
                   'public_comment', 'statement')


def test_event_types_match_migration_035():
    assert tuple(S.EVENT_TYPES) == MIG_EVENT_TYPES
    assert S.EVENTS_SCHEMA["properties"]["events"]["items"]["properties"]["event_type"]["enum"] == list(MIG_EVENT_TYPES)


def _closed(schema: dict) -> bool:
    if schema.get("type") == "object" or isinstance(schema.get("properties"), dict):
        if schema.get("additionalProperties") is not False:
            return False
        if set(schema.get("required", [])) != set(schema.get("properties", {})):
            return False
        return all(_closed(v) for v in schema["properties"].values())
    if "items" in schema:
        return _closed(schema["items"])
    return True


@pytest.mark.parametrize("schema", [S.SPEAKER_SCHEMA, S.EVENTS_SCHEMA, S.JUDGE_SCHEMA, S.HUNTER_SCHEMA])
def test_schemas_are_closed_objects_with_every_property_required(schema):
    # Structured outputs want every property listed in required and no open objects.
    assert _closed(schema), json.dumps(schema)[:200]


def test_event_round_trips_through_pydantic():
    ev = S.ExtractedEvent.model_validate({
        "event_type": "vote", "scope": "item", "agenda_item_refs": [912],
        "actor_text": "Council President", "actor_member_id": None,
        "summary": "Item 12 passes 8-0",
        "detail": {"result": "passed", "yeas": 8, "nays": 0, "method": "voice"},
        "segment_seq": 6, "page": None, "quote": "Item 12 passes, 8 to 0.",
    })
    assert ev.detail.result == "passed" and ev.detail.abstentions is None
    assert "unlisted_item" in S.EVENT_DETAIL_SCHEMA["properties"]


def test_bad_event_type_rejected():
    with pytest.raises(ValidationError):
        S.ExtractedEvent.model_validate({"event_type": "pledge", "scope": "meeting", "agenda_item_refs": [],
                                         "actor_text": None, "actor_member_id": None, "summary": "x",
                                         "detail": {}, "segment_seq": None, "page": None, "quote": None})


def test_speaker_assignment_confidence_bounds():
    with pytest.raises(ValidationError):
        S.SpeakerAssignment.model_validate({"cluster_label": "S1", "council_member_id": None, "display_name": "Clerk",
                                            "role": "clerk", "confidence": 1.4, "method": "sample_inference",
                                            "evidence_quote": "x", "evidence_quote_2": None})


def _count_unions(node) -> int:
    if isinstance(node, dict):
        n = 1 if isinstance(node.get("type"), list) or "anyOf" in node else 0
        return n + sum(_count_unions(v) for v in node.values())
    if isinstance(node, list):
        return sum(_count_unions(v) for v in node)
    return 0


@pytest.mark.parametrize("schema", [S.SPEAKER_SCHEMA, S.EVENTS_SCHEMA, S.JUDGE_SCHEMA, S.HUNTER_SCHEMA])
def test_schemas_stay_under_api_union_limit(schema):
    assert _count_unions(schema) <= 16


def test_empty_detail_values_normalize_to_none():
    d = S.EventDetail.model_validate({"action": "", "items": [], "result": "passed", "present": ["A"]})
    assert d.action is None and d.items is None
    assert d.compact() == {"result": "passed", "present": ["A"]}


def test_verdict_category_validated_by_literal_even_without_schema_enum():
    base = {"candidate_id": 1, "is_real": False, "severity": None, "title": None, "description": None,
            "transcript_quote": None, "minutes_quote": None, "confidence": 0.5, "dismiss_reason": "x"}
    assert S.Verdict.model_validate({**base, "category": None}).category is None
    with pytest.raises(ValidationError):
        S.Verdict.model_validate({**base, "category": "bogus"})
