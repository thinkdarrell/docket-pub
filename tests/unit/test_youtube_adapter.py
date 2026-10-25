"""Tests for docket.adapters.youtube: the YouTube Data API v3 client, driven by a fake transport.

No network: the client takes its HTTP ``get`` as a constructor argument and the
tests pass a fake that records each call and returns canned JSON pages shaped
like the API's own answers.

The symbols under test are imported inside each test, so the file collects
and reads as failing, not as a collection error, before the module exists.

Plan: plans/completed/youtube-council-channel.md (M1).
"""

from datetime import datetime, timezone

import pytest


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeGet:
    """Answers each call with the next canned response and records the call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, params=None, timeout=None, **kwargs):
        self.calls.append((url, dict(params or {})))
        return self.responses.pop(0)


def _item(video_id, published, title=None):
    return {
        "snippet": {"title": title or f"Meeting {video_id}"},
        "contentDetails": {"videoId": video_id, "videoPublishedAt": published},
    }


def _page(items, next_token=None):
    body = {"items": items}
    if next_token:
        body["nextPageToken"] = next_token
    return FakeResponse(200, body)


CUTOFF = datetime(2026, 9, 24, tzinfo=timezone.utc)


class TestParseIsoDuration:
    @pytest.mark.parametrize(
        "text, seconds",
        [
            ("PT3H10M6S", 11406),
            ("PT23M", 1380),
            ("PT45S", 45),
            ("PT1H", 3600),
            ("P0D", 0),
            ("P1DT1S", 86401),
            ("", None),
            ("nonsense", None),
        ],
    )
    def test_durations(self, text, seconds):
        from docket.adapters.youtube import parse_iso_duration

        assert parse_iso_duration(text) == seconds


class TestUploadsPlaylistId:
    def test_reads_the_uploads_playlist(self):
        from docket.adapters.youtube import YouTubeClient

        get = FakeGet(
            [FakeResponse(200, {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UUxKV8MgjDbqw9PMGTsF_NUw"}}}]})]
        )
        client = YouTubeClient("KEY", get=get)
        assert client.uploads_playlist_id("citycouncilbham") == "UUxKV8MgjDbqw9PMGTsF_NUw"
        url, params = get.calls[0]
        assert url.endswith("/youtube/v3/channels")
        assert params["forHandle"] == "citycouncilbham"
        assert params["key"] == "KEY"

    def test_unknown_handle_raises(self):
        from docket.adapters.youtube import YouTubeAPIError, YouTubeClient

        client = YouTubeClient("KEY", get=FakeGet([FakeResponse(200, {"pageInfo": {"totalResults": 0}})]))
        with pytest.raises(YouTubeAPIError):
            client.uploads_playlist_id("nobody")


class TestListUploads:
    def test_pages_until_the_playlist_ends_without_a_cutoff(self):
        from docket.adapters.youtube import YouTubeClient

        get = FakeGet(
            [
                _page([_item("a", "2026-10-20T23:00:00Z"), _item("b", "2026-10-13T23:00:00Z")], "T2"),
                _page([_item("c", "2015-01-01T00:00:00Z")]),
            ]
        )
        videos = YouTubeClient("KEY", get=get).list_uploads("UU1")
        assert [v.video_id for v in videos] == ["a", "b", "c"]
        assert len(get.calls) == 2
        assert get.calls[0][1]["maxResults"] == 50
        assert get.calls[1][1]["pageToken"] == "T2"
        assert videos[0].published_at == datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)
        assert videos[0].title == "Meeting a"

    def test_a_page_mixing_new_and_old_does_not_stop_the_walk(self):
        from docket.adapters.youtube import YouTubeClient

        get = FakeGet(
            [
                # one old item out of order on page 1: the walk continues
                _page([_item("a", "2026-10-20T23:00:00Z"), _item("old1", "2026-09-01T00:00:00Z")], "T2"),
                _page([_item("b", "2026-09-30T23:00:00.123Z"), _item("old2", "2026-09-02T00:00:00Z")], "T3"),
                # every item older than the cutoff: the walk stops after this page
                _page([_item("old3", "2026-09-10T00:00:00Z"), _item("old4", "2026-09-09T00:00:00Z")], "T4"),
                _page([_item("never", "2026-10-01T00:00:00Z")]),
            ]
        )
        videos = YouTubeClient("KEY", get=get).list_uploads("UU1", published_after=CUTOFF)
        assert [v.video_id for v in videos] == ["a", "b"]
        assert len(get.calls) == 3

    def test_item_without_a_publish_time_falls_back_to_the_snippet(self):
        from docket.adapters.youtube import YouTubeClient

        item = {
            "snippet": {"title": "x", "publishedAt": "2026-10-01T00:00:00Z"},
            "contentDetails": {"videoId": "x"},
        }
        videos = YouTubeClient("KEY", get=FakeGet([_page([item])])).list_uploads("UU1")
        assert videos[0].published_at == datetime(2026, 10, 1, tzinfo=timezone.utc)


class TestFillDetails:
    def test_batches_fifty_ids_per_call_and_fills_fields(self):
        from docket.adapters.youtube import YouTubeClient, YouTubeVideo

        published = datetime(2026, 10, 1, tzinfo=timezone.utc)
        videos = [YouTubeVideo(video_id=f"v{i}", title=f"t{i}", published_at=published) for i in range(120)]

        def details(ids):
            return FakeResponse(
                200,
                {
                    "items": [
                        {
                            "id": vid,
                            "contentDetails": {"duration": "PT3H10M6S"},
                            "liveStreamingDetails": {"actualStartTime": "2026-09-30T22:00:12Z"},
                            "snippet": {"liveBroadcastContent": "none"},
                        }
                        for vid in ids
                    ]
                },
            )

        get = FakeGet(
            [
                details([f"v{i}" for i in range(0, 50)]),
                details([f"v{i}" for i in range(50, 100)]),
                details([f"v{i}" for i in range(100, 120)]),
            ]
        )
        filled = YouTubeClient("KEY", get=get).fill_details(videos)
        assert len(get.calls) == 3
        assert [len(c[1]["id"].split(",")) for c in get.calls] == [50, 50, 20]
        assert get.calls[0][0].endswith("/youtube/v3/videos")
        assert [v.video_id for v in filled] == [f"v{i}" for i in range(120)]
        assert filled[0].duration_s == 11406
        assert filled[0].started_at == datetime(2026, 9, 30, 22, 0, 12, tzinfo=timezone.utc)
        assert filled[0].broadcast == "none"
        assert filled[0].title == "t0"

    def test_upcoming_stream_and_missing_video(self):
        from docket.adapters.youtube import YouTubeClient, YouTubeVideo

        published = datetime(2026, 10, 1, tzinfo=timezone.utc)
        videos = [
            YouTubeVideo(video_id="up", title="u", published_at=published),
            YouTubeVideo(video_id="gone", title="g", published_at=published),
        ]
        get = FakeGet(
            [
                FakeResponse(
                    200,
                    {
                        "items": [
                            {
                                "id": "up",
                                "contentDetails": {"duration": "P0D"},
                                "snippet": {"liveBroadcastContent": "upcoming"},
                            }
                        ]
                    },
                )
            ]
        )
        up, gone = YouTubeClient("KEY", get=get).fill_details(videos)
        assert up.broadcast == "upcoming"
        assert up.started_at is None
        assert gone.duration_s is None


class TestErrors:
    def _error(self, status, reason):
        return FakeResponse(
            status,
            {"error": {"code": status, "message": reason, "errors": [{"reason": reason, "domain": "youtube"}]}},
        )

    def test_quota_exceeded_raises_quota_exceeded(self):
        from docket.adapters.youtube import QuotaExceeded, YouTubeClient

        client = YouTubeClient("KEY", get=FakeGet([self._error(403, "quotaExceeded")]))
        with pytest.raises(QuotaExceeded):
            client.list_uploads("UU1")

    def test_other_errors_raise_with_status_and_reason(self):
        from docket.adapters.youtube import QuotaExceeded, YouTubeAPIError, YouTubeClient

        client = YouTubeClient("KEY", get=FakeGet([self._error(400, "keyInvalid")]))
        with pytest.raises(YouTubeAPIError) as exc:
            client.uploads_playlist_id("citycouncilbham")
        assert not isinstance(exc.value, QuotaExceeded)
        assert exc.value.status == 400
        assert exc.value.reason == "keyInvalid"
        assert "400" in str(exc.value) and "keyInvalid" in str(exc.value)

    def test_error_body_that_is_not_json(self):
        from docket.adapters.youtube import YouTubeAPIError, YouTubeClient

        class Broken(FakeResponse):
            def json(self):
                raise ValueError("not json")

        client = YouTubeClient("KEY", get=FakeGet([Broken(500, None)]))
        with pytest.raises(YouTubeAPIError) as exc:
            client.list_uploads("UU1")
        assert exc.value.status == 500
