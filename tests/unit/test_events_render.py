# tests/unit/test_events_render.py
from docket.ai.transcripts.events import render_agenda, render_minutes, render_transcript

AGENDA = [{"id": 10, "item_number": "1", "title": "Minutes approval", "is_consent": False, "external_id": "1-1", "video_timestamp_seconds": 900.0},
          {"id": 11, "item_number": "2", "title": "Consent: street closure", "is_consent": True, "external_id": "1-2", "video_timestamp_seconds": 1500.0}]


def test_render_transcript_labels_speakers_and_marks_items():
    segs = [{"id": 1, "seq": 0, "start_s": 0, "end_s": 890, "text": "", "cluster_label": None, "agenda_item_id": None, "is_silence": True,
             "speaker_name": None, "speaker_confidence": None},
            {"id": 2, "seq": 1, "start_s": 905, "end_s": 910, "text": "We are called to order.", "cluster_label": "S0", "agenda_item_id": 10,
             "is_silence": False, "speaker_name": "Darrell O'Quinn", "speaker_confidence": 0.75},
            {"id": 3, "seq": 2, "start_s": 1510, "end_s": 1515, "text": "Move approval.", "cluster_label": "S4", "agenda_item_id": 11,
             "is_silence": False, "speaker_name": "Maybe Someone", "speaker_confidence": 0.4}]
    out = render_transcript(segs, AGENDA, {"S0": 1, "S4": 2})
    assert "No speech" not in out and "[seq=0" not in out                     # silence excluded
    assert "=== Item 1 (agenda_item_id=10): Minutes approval ===" in out
    assert "[seq=1 t=00:15:05 Darrell O'Quinn] We are called to order." in out
    assert "[seq=2 t=00:25:10 Speaker 2] Move approval." in out                 # below the 0.6 floor -> Speaker N
    assert out.index("agenda_item_id=10") < out.index("agenda_item_id=11")


def test_render_agenda_flags_consent():
    out = render_agenda(AGENDA)
    assert "id=10 Item 1: Minutes approval" in out and "id=11 Item 2 [consent]: Consent: street closure" in out


def test_render_minutes_inserts_page_markers():
    text = "page one text\npage two text\npage three"
    out = render_minutes(text, [0, 14, 28])
    assert out.startswith("[[page 1]]\npage one text")
    assert "[[page 2]]\npage two text" in out and "[[page 3]]\npage three" in out
