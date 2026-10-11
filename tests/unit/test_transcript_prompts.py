from docket.ai.transcripts import prompts as P


def test_versions_are_200_series():
    for v in (P.SPEAKER_PROMPT_VERSION, P.EVENTS_PROMPT_VERSION, P.COMPARE_PROMPT_VERSION):
        assert 200 <= v < 300


def test_materiality_fragment_is_byte_identical_in_all_three_prompts():
    frag = P.MATERIALITY_FRAGMENT
    assert len(frag) > 400
    for text in (P.EVENTS_TRANSCRIPT_SYSTEM, P.JUDGE_SYSTEM, P.HUNTER_SYSTEM):
        assert frag in text
    # The minutes side extracts what is written, not what is material; it must not filter.
    assert frag not in P.EVENTS_MINUTES_SYSTEM


def test_fragment_carries_pilot_examples():
    f = P.MATERIALITY_FRAGMENT
    assert "not in the packet" in f           # positive example (O'Quinn)
    assert "criminal justice information" in f  # positive example (city attorney)
    assert "clarifying question" in f           # negative example


def test_speaker_prompt_states_the_two_signal_rule_and_response_rule():
    s = P.SPEAKER_SYSTEM
    assert "two independent signals" in s
    assert "here" in s and "present" in s and "aye" in s
    assert "quote the utterance" in s.lower()


def test_extraction_prompts_handle_consent_by_number_and_unlisted_items():
    for text in (P.EVENTS_TRANSCRIPT_SYSTEM, P.EVENTS_MINUTES_SYSTEM):
        assert "unlisted_item" in text and "by number" in text


def test_prompts_tell_the_model_to_quote_exactly_as_shown():
    for text in (P.JUDGE_SYSTEM, P.HUNTER_SYSTEM, P.EVENTS_TRANSCRIPT_SYSTEM, P.EVENTS_MINUTES_SYSTEM):
        assert "exactly as shown" in text


def test_extraction_prompts_match_the_non_nullable_detail_schema():
    for text in (P.EVENTS_TRANSCRIPT_SYSTEM, P.EVENTS_MINUTES_SYSTEM):
        assert 'use ""' in text
        assert "leave the others null" not in text
