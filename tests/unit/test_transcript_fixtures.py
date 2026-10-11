from pathlib import Path

from tests.support.transcript_fixtures import PILOT_CLIP_OFFSET_S, load_bundle, parse_srt, pilot_bundle


def test_parse_srt_offsets_and_numbers_segments():
    segs = parse_srt(Path("tests/fixtures/transcript_pilot/2026-02-17_clip1950_item15_small-en.srt"),
                     offset_s=PILOT_CLIP_OFFSET_S, cluster_label="S0")
    assert segs[0]["seq"] == 0 and segs[0]["start_s"] == 3290.0
    assert segs[1]["start_s"] == 3290.0 + 5.86
    assert all(s["cluster_label"] == "S0" and s["is_silence"] is False for s in segs)
    assert "CGI access security agreement" in segs[0]["text"]


def test_pilot_bundle_has_minutes_pages_and_item_15():
    b = pilot_bundle()
    assert b.meeting["meeting_date"] == "2026-02-17"
    assert len(b.minutes_pages) > 10 and b.minutes_pages[0] == 0
    assert "pending litigation" in b.minutes_text
    (item,) = b.agenda_items
    assert item["item_number"] == "15" and item["video_timestamp_seconds"] == 3309
    assert len(b.roster) >= 9


def test_2543_bundle_is_the_real_meeting():
    b = load_bundle("transcript_2543")
    assert b.meeting["meeting_date"] == "2026-10-06"
    assert len(b.segments) > 150
    clusters = {s["cluster_label"] for s in b.segments if s["cluster_label"]}
    assert len(clusters) >= 20                      # the over-clustering the stages must survive
    assert any(s["is_silence"] for s in b.segments)  # the pre-meeting silence turn
    assert sum(len(s["text"].split()) for s in b.segments) > 10_000
