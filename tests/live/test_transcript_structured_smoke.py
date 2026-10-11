# tests/live/test_transcript_structured_smoke.py
"""LIVE: output_config.format on both transcript models. ~$0.02 per run.

Run: venv/bin/python -m pytest -m live tests/live/test_transcript_structured_smoke.py -v -s
Exercises every JSON Schema feature the production schemas use (nullable
type arrays, enums, nested arrays of objects, additionalProperties false)
so a rejected keyword fails here, before Task 7 builds on it.
"""
import os

import pytest

from docket.ai.transcripts.client import StructuredClient
from docket.config import AI_TRANSCRIPT_COMPARE_MODEL, AI_TRANSCRIPT_EVENTS_MODEL

pytestmark = pytest.mark.live

DUMMY = "test-dummy-key-not-for-real-api-calls"


@pytest.fixture
def client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or key == DUMMY:
        pytest.skip("real ANTHROPIC_API_KEY not set")
    return StructuredClient(api_key=key)


PROBE_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_type": {"type": "string", "enum": ["motion", "vote", "statement"]},
                    "agenda_item_refs": {"type": "array", "items": {"type": "integer"}},
                    "actor_member_id": {"type": ["integer", "null"]},
                    "quote": {"type": ["string", "null"]},
                    "detail": {
                        "type": "object",
                        "properties": {"result": {"type": ["string", "null"]},
                                       "yeas": {"type": ["integer", "null"]}},
                        "required": ["result", "yeas"],
                        "additionalProperties": False,
                    },
                },
                "required": ["event_type", "agenda_item_refs", "actor_member_id", "quote", "detail"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["events"],
    "additionalProperties": False,
}

USER = ("Transcript:\n[seq=4 t=00:10:02 Chair] Motion to approve item 12. Is there a second?\n"
        "[seq=5 t=00:10:05 Speaker 3] Second.\n[seq=6 t=00:10:09 Chair] All in favor. Item 12 passes, 8 to 0.\n"
        "Agenda items: id 912 = Item 12. Emit one motion event and one vote event. "
        "Quote the exact transcript text for each. actor_member_id is null here.")


@pytest.mark.parametrize("model", [AI_TRANSCRIPT_EVENTS_MODEL, AI_TRANSCRIPT_COMPARE_MODEL])
def test_structured_output_round_trip(client, model):
    assert client.count_tokens(model=model, system="You extract council events.", user=USER) > 20
    res = client.call(model=model, system="You extract council events as JSON.", user=USER,
                      schema=PROBE_SCHEMA, max_tokens=4000, effort="low")
    assert res.stop_reason == "end_turn"
    types = [e["event_type"] for e in res.data["events"]]
    assert "motion" in types and "vote" in types
    vote = next(e for e in res.data["events"] if e["event_type"] == "vote")
    assert vote["agenda_item_refs"] == [912]
    assert vote["detail"]["yeas"] == 8
    assert vote["quote"] and "passes" in vote["quote"]
    assert res.usage.input_tokens > 0 and res.usage.output_tokens > 0
    print(f"\n{model}: {res.data}")


from docket.ai.transcripts import schemas as S


@pytest.mark.parametrize("schema,model", [
    (S.SPEAKER_SCHEMA, AI_TRANSCRIPT_EVENTS_MODEL),
    (S.EVENTS_SCHEMA, AI_TRANSCRIPT_EVENTS_MODEL),
    (S.JUDGE_SCHEMA, AI_TRANSCRIPT_COMPARE_MODEL),
    (S.HUNTER_SCHEMA, AI_TRANSCRIPT_COMPARE_MODEL),
])
def test_production_schemas_are_accepted(client, schema, model):
    """Each schema is accepted by the model that will use it. Empty-list answers are fine."""
    res = client.call(model=model, system="Return an empty result that fits the schema.",
                      user="There is no input. Return the schema's top-level array empty.",
                      schema=schema, max_tokens=2000, effort="low")
    (key,) = schema["properties"].keys()
    assert res.data[key] == []
