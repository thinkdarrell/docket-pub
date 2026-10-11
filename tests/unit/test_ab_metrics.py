# tests/unit/test_ab_metrics.py
from collections import Counter

from docket.ai.transcripts.ab import compare_event_lists, event_keys, render_report
from docket.ai.transcripts.client import build_request
from docket.ai.transcripts.schemas import ExtractedEvent


def _ev(et, refs):
    return ExtractedEvent.model_validate({"event_type": et, "scope": "item", "agenda_item_refs": refs, "actor_text": None,
                                          "actor_member_id": None, "summary": et, "detail": {}, "segment_seq": 1, "page": None, "quote": None})


def test_event_keys_are_multisets():
    assert event_keys([_ev("motion", [1]), _ev("motion", [1]), _ev("vote", [1])]) == Counter({("motion", frozenset({1})): 2, ("vote", frozenset({1})): 1})


def test_compare_event_lists_precision_recall_and_per_type():
    ref = [_ev("motion", [1]), _ev("vote", [1]), _ev("statement", [1]), _ev("statement", [2])]
    cand = [_ev("motion", [1]), _ev("vote", [1]), _ev("statement", [1]), _ev("recess", [])]
    m = compare_event_lists(ref, cand)
    assert m["recall"] == 0.75 and m["precision"] == 0.75
    assert m["per_type_recall"]["motion"] == 1.0 and m["per_type_recall"]["statement"] == 0.5


def test_build_request_omits_effort_for_models_that_reject_it():
    req = build_request(model="claude-haiku-4-5-20251001", system="S", user="U", schema={"type": "object"}, effort=None)
    assert "effort" not in req["output_config"] and req["output_config"]["format"]["type"] == "json_schema"


def test_report_states_the_decision_rule_and_a_verdict():
    results = [{"meeting_id": 1, "haiku": {"recall": 0.95, "precision": 0.9, "per_type_recall": {"motion": 1.0, "vote": 1.0, "statement": 0.85},
                                            "cost_usd": 0.05, "latency_s": 20.0, "tokens": 40000},
                "sonnet": {"cost_usd": 0.20, "latency_s": 35.0, "tokens": 40000}, "material_recall": {"haiku": 1.0, "sonnet": 1.0}, "skipped": None}]
    text = render_report(results)
    assert "Decision rule" in text and "recall" in text and "Verdict" in text and "meeting 1" in text
