from docket.web.video_urls import chapter_url


GRANICUS_URL = "https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=1986"


def test_appends_meta_id_to_granicus_url():
    result = chapter_url(GRANICUS_URL, "371120")
    assert "meta_id=371120" in result
    assert result.startswith(
        "https://bhamal.granicus.com/MediaPlayer.php?"
    )
    # Existing params preserved
    assert "view_id=2" in result
    assert "clip_id=1986" in result


def test_accepts_int_meta_id():
    result = chapter_url(GRANICUS_URL, 371120)
    assert "meta_id=371120" in result


def test_returns_none_when_video_url_none():
    assert chapter_url(None, "371120") is None


def test_unchanged_when_meta_id_none():
    assert chapter_url(GRANICUS_URL, None) == GRANICUS_URL


def test_unchanged_when_meta_id_non_numeric():
    # Granicus adapter falls back to "{clip_id}-{i}" when JS cuepoint
    # lacks data-id. Don't pass a malformed meta_id through.
    assert chapter_url(GRANICUS_URL, "1986-3") == GRANICUS_URL


def test_unchanged_for_non_granicus_url():
    youtube = "https://www.youtube.com/watch?v=abc"
    assert chapter_url(youtube, "371120") == youtube


def test_strips_html5_time_fragment():
    # Old broken format had #t=NNN fragments. Don't carry those into
    # the fixed URL.
    legacy = GRANICUS_URL + "#t=180"
    result = chapter_url(legacy, "371120")
    assert "#" not in result
    assert "meta_id=371120" in result


def test_overwrites_existing_meta_id():
    # If a URL already has meta_id, the new value wins.
    url = GRANICUS_URL + "&meta_id=999"
    result = chapter_url(url, "371120")
    assert "meta_id=371120" in result
    assert "meta_id=999" not in result
