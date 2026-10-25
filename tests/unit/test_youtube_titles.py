"""Tests for the pure half of docket.services.youtube_meetings: titles and grouping.

The titles are the council channel's own, from the streams listing captured on
2026-10-24 (the inventory in the plan's Artifacts and Notes section). The
inventory is the contract: a new title shape is a new case here.

The symbols under test are imported inside each test, so the file collects
and reads as failing, not as a collection error, before the module exists.

Plan: plans/completed/youtube-council-channel.md (M1).
"""

from datetime import date, datetime, timezone

import pytest

TODAY = date(2026, 10, 24)


def _video(video_id, title, duration_s, *, broadcast="none"):
    from docket.adapters.youtube import YouTubeVideo

    return YouTubeVideo(
        video_id=video_id,
        title=title,
        published_at=datetime(2026, 10, 14, 1, 0, tzinfo=timezone.utc),
        duration_s=duration_s,
        started_at=None,
        broadcast=broadcast,
    )


class TestParseTitle:
    @pytest.mark.parametrize(
        "title, meeting_date, clean, part",
        [
            ("Committee of the Whole Meeting 9.30.26", date(2026, 9, 30), "Committee of the Whole Meeting", None),
            ("Committee of the Whole Meeting 2.18.26", date(2026, 2, 18), "Committee of the Whole Meeting", None),
            ("10.13.26 Public Safety Committee meeting", date(2026, 10, 13), "Public Safety Committee meeting", None),
            ("Community Development Committee Meeting 8.03.26", date(2026, 8, 3), "Community Development Committee Meeting", None),
            ("Community Development Committee Meeting 10.5.26", date(2026, 10, 5), "Community Development Committee Meeting", None),
            ("Arts and Parks Committee Meeting 8.17.26 Pt. 1", date(2026, 8, 17), "Arts and Parks Committee Meeting", 1),
            ("Arts and Parks Committee Meeting 8.17.26 Pt. 2", date(2026, 8, 17), "Arts and Parks Committee Meeting", 2),
            ("Birmingham City Council Meeting Part 2 12.23.24", date(2024, 12, 23), "Birmingham City Council Meeting", 2),
            ("Planning and Zoning Committee Meeting 4.14.26 Pt. 1", date(2026, 4, 14), "Planning and Zoning Committee Meeting", 1),
            ("Special Called Community Development Committee Meeting 9.8.26 Pt. 1", date(2026, 9, 8), "Special Called Community Development Committee Meeting", 1),
            ("Budget & Finance Committee Meeting 6.22.26", date(2026, 6, 22), "Budget & Finance Committee Meeting", None),
            ("Budget and Finance Committee Meeting 9.28.26", date(2026, 9, 28), "Budget and Finance Committee Meeting", None),
            ("Birmingham City Council Meeting 10.13.26", date(2026, 10, 13), "Birmingham City Council Meeting", None),
            ("Birmingham City Council Meeting 10.20.26", date(2026, 10, 20), "Birmingham City Council Meeting", None),
            ("Administration and Governmental Affairs Meeting 1.9.24", date(2024, 1, 9), "Administration and Governmental Affairs Meeting", None),
            ("Committee of the Whole Meeting 9/30/2026", date(2026, 9, 30), "Committee of the Whole Meeting", None),
        ],
    )
    def test_meeting_titles(self, title, meeting_date, clean, part):
        from docket.services.youtube_meetings import ParsedTitle, parse_title

        assert parse_title(title, today=TODAY) == ParsedTitle(meeting_date, clean, part)

    def test_slash_and_ampersand_survive_and_classify_as_committee(self):
        from docket.adapters._helpers import classify_title
        from docket.services.youtube_meetings import parse_title

        parsed = parse_title(
            "Committee of the Whole/Administration & Governmental Affairs Committee Meeting 3.12.26",
            today=TODAY,
        )
        assert parsed.meeting_date == date(2026, 3, 12)
        assert parsed.clean_title == "Committee of the Whole/Administration & Governmental Affairs Committee Meeting"
        assert classify_title(parsed.clean_title).meeting_type == "committee"

    @pytest.mark.parametrize(
        "title",
        [
            "Council Highlights: September 29 Edition",
            "SYSTEM TEST",
            "Test Stream",
            "Birmingham City Council Week Ahead Tease: 11/7 - 11/11",
            "D7 WENONAH PARADE  2025",
            "Your City Budget, Simplified",
            # a date but no meeting word
            "Juneteenth Parade 6.19.26",
            # a meeting word and a date but a rejected word
            "Council Meeting Recap 10.13.26",
            "Council Highlights 10.13.26 Edition",
            "Council Meeting Test 10.13.26",
        ],
    )
    def test_non_meetings_are_rejected(self, title):
        from docket.services.youtube_meetings import parse_title

        assert parse_title(title, today=TODAY) is None

    @pytest.mark.parametrize(
        "title",
        [
            "Council Meeting 12.31.07",  # before 2008
            "Council Meeting 10.26.26",  # after tomorrow
            "Council Meeting 13.40.26",  # no such date
        ],
    )
    def test_out_of_range_or_impossible_dates_are_rejected(self, title):
        from docket.services.youtube_meetings import parse_title

        assert parse_title(title, today=TODAY) is None

    def test_tomorrow_is_accepted(self):
        from docket.services.youtube_meetings import parse_title

        assert parse_title("Council Meeting 10.25.26", today=TODAY).meeting_date == date(2026, 10, 25)


class TestBodyKey:
    def test_ampersand_and_and_share_a_key(self):
        from docket.services.youtube_meetings import body_key, parse_title

        a = parse_title("Budget & Finance Committee Meeting 6.22.26", today=TODAY).clean_title
        b = parse_title("Budget and Finance Committee Meeting 6.8.26", today=TODAY).clean_title
        assert body_key(a) == body_key(b)
        assert body_key(a) == "budgetandfinancecommitteemeeting"

    def test_special_called_and_joint_are_ignored(self):
        from docket.services.youtube_meetings import body_key

        assert body_key("Special Called Community Development Committee Meeting") == body_key(
            "Community Development Committee Meeting"
        )
        assert body_key("Joint Public Safety Committee Meeting") == body_key("Public Safety Committee Meeting")

    def test_case_and_punctuation_are_ignored(self):
        from docket.services.youtube_meetings import body_key

        assert body_key("Public Safety Committee meeting") == body_key("Public Safety Committee Meeting")


class TestCleanTitle:
    def test_removes_date_and_part(self):
        from docket.services.youtube_meetings import clean_title

        assert clean_title("Public Safety Committee Meeting 2.10.26 Pt. 2") == "Public Safety Committee Meeting"
        assert clean_title("Council Meeting - 10.13.26") == "Council Meeting"


class TestGroupVideos:
    def test_test_streams_fold_into_the_one_real_council_recording(self):
        from docket.services.youtube_meetings import group_videos

        title = "Birmingham City Council Meeting 10.13.26"
        videos = [_video(f"short{i}", title, d) for i, d in enumerate([0, 30, 60, 120, 90, 299])]
        videos.append(_video("ara-4Ve6XCU", title, 1800))
        groups = group_videos(videos)
        assert len(groups) == 1
        cand = groups[0]
        assert cand.meeting_date == date(2026, 10, 13)
        assert cand.clean_title == "Birmingham City Council Meeting"
        assert cand.primary.video_id == "ara-4Ve6XCU"
        assert cand.others == []
        assert cand.classification.meeting_type == "council"

    def test_parts_fold_with_the_longest_as_primary(self):
        from docket.services.youtube_meetings import group_videos

        groups = group_videos(
            [
                _video("clN1E49-fyg", "Public Safety Committee Meeting 2.10.26 Pt. 1", 300),
                _video("2Gni3U6ODyM", "Public Safety Committee Meeting 2.10.26 Pt. 2", 1800),
            ]
        )
        assert len(groups) == 1
        cand = groups[0]
        assert cand.primary.video_id == "2Gni3U6ODyM"
        assert [v.video_id for v in cand.others] == ["clN1E49-fyg"]
        assert cand.total_duration_s == 2100
        assert cand.classification.meeting_type == "committee"
        assert cand.classification.body_name == "Public Safety Committee"

    def test_two_bodies_on_one_day_stay_apart(self):
        from docket.services.youtube_meetings import group_videos

        groups = group_videos(
            [
                _video("rJ6PPd2MDTE", "10.13.26 Public Safety Committee meeting", 2220),
                _video("pRNunlGGr5A", "Planning and Zoning Committee Meeting 10.13.26", 1320),
                _video("ara-4Ve6XCU", "Birmingham City Council Meeting 10.13.26", 1800),
            ]
        )
        assert sorted(c.primary.video_id for c in groups) == ["ara-4Ve6XCU", "pRNunlGGr5A", "rJ6PPd2MDTE"]

    def test_ampersand_variant_groups_with_and(self):
        from docket.services.youtube_meetings import group_videos

        groups = group_videos(
            [
                _video("a", "Budget & Finance Committee Meeting 6.22.26", 2280),
                _video("b", "Budget and Finance Committee Meeting 6.22.26", 600),
            ]
        )
        assert len(groups) == 1
        assert groups[0].primary.video_id == "a"

    def test_live_upcoming_unknown_duration_and_non_meetings_are_dropped(self):
        from docket.services.youtube_meetings import group_videos

        groups = group_videos(
            [
                _video("live", "Committee of the Whole Meeting 10.21.26", 4000, broadcast="live"),
                _video("up", "Public Safety Committee Meeting 10.27.26", 0, broadcast="upcoming"),
                _video("nodur", "Arts and Parks Committee Meeting 9.21.26", None),
                _video("hl", "Council Highlights: September 29 Edition", 600),
            ]
        )
        assert groups == []

    def test_committee_of_the_whole_is_named(self):
        from docket.services.youtube_meetings import group_videos

        (cand,) = group_videos([_video("6Cocqqq95Ew", "Committee of the Whole Meeting 9.30.26", 11406)])
        assert cand.classification.meeting_type == "committee"
        assert cand.classification.body_name == "Committee of the Whole"
        assert cand.total_duration_s == 11406

    def test_meeting_titled_uploads_it_cannot_read_are_reported_not_silently_dropped(self):
        # Review record, minor: a meeting-worded recording with no readable
        # date, or with no known duration, is handed back with its reason.
        from docket.services.youtube_meetings import group_videos

        dropped = []
        groups = group_videos(
            [
                _video("hyph", "Committee of the Whole Meeting 9-30-26", 11400),
                _video("nodate", "Public Safety Committee Meeting", 3600),
                _video("nodur", "Budget and Finance Committee Meeting 9.28.26", None),
                _video("promo", "City Council Highlights 9.30.26", 600),
                _video("short", "Birmingham City Council Meeting 10.13.26", 30),
                _video("live", "Birmingham City Council Meeting 10.13.26", None, broadcast="live"),
            ],
            today=TODAY,
            dropped=dropped,
        )
        assert groups == []
        assert [(v.video_id, reason) for v, reason in dropped] == [
            ("hyph", "no readable date"),
            ("nodate", "no readable date"),
            ("nodur", "no known duration"),
        ]

    def test_a_special_called_stream_is_its_own_group_beside_the_regular_one(self):
        # Review record (second panel), important: a same-day special-called
        # council stream must not fold into the regular meeting as a part.
        from docket.services.youtube_meetings import group_videos

        groups = group_videos(
            [
                _video("reg", "Birmingham City Council Meeting 9.29.26", 7200),
                _video("spc", "Special Called Birmingham City Council Meeting 9.29.26", 900),
            ],
            today=TODAY,
        )
        assert sorted((g.primary.video_id, [v.video_id for v in g.others], g.classification.session_kind)
                      for g in groups) == [("reg", [], "regular"), ("spc", [], "special")]

    def test_numbered_parts_still_fold_across_a_special_called_prefix(self):
        from docket.services.youtube_meetings import group_videos

        (cand,) = group_videos(
            [
                _video("p1", "Special Called Community Development Committee Meeting 9.8.26 Pt. 1", 1200),
                _video("p2", "Community Development Committee Meeting 9.8.26 Pt. 2", 2400),
            ],
            today=TODAY,
        )
        assert cand.primary.video_id == "p2"
        assert [v.video_id for v in cand.others] == ["p1"]
