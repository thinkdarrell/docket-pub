from docket.services.transcripts import parse_speaker_token


def test_no_token():
    assert parse_speaker_token("license plate reader") == ("license plate reader", None)


def test_single_word_token_anywhere():
    assert parse_speaker_token("executive session speaker:oquinn") == ("executive session", "oquinn")
    assert parse_speaker_token("speaker:Tate recess") == ("recess", "Tate")


def test_quoted_token():
    assert parse_speaker_token('speaker:"Darrell O\'Quinn" packet') == ("packet", "Darrell O'Quinn")


def test_token_only():
    assert parse_speaker_token("speaker:smith") == ("", "smith")
