from docket.services.video_links import chapter_url


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


# ---------------------------------------------------------------------------
# The link builder (docket.services.video_links). Each test imports the
# module itself, so the file collects whether or not the module exists.
# Plan: plans/completed/video-links-land-on-the-moment.md (M4).
# ---------------------------------------------------------------------------

PLAYER = "https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=2026"
YT = "FR84h22hQvA"


def _run_3184():
    """Meeting 3184's consent reading: 59 cue points, evenly spread over 1,990 to 2,085 seconds."""
    return [(1990.0 + i * 95.0 / 58.0, str(371100 + i)) for i in range(59)]


def _meeting_3184(vl, *, offset_s=635.48, recordings=None, consent=None):
    """A Granicus meeting with one passing recording, as the loader would hand it over."""
    if recordings is None:
        recordings = (vl.Recording(video_id=YT, offset_s=offset_s, start_s=635.5, end_s=3935.5),)
    return vl.MeetingVideo(video_url=PLAYER, recordings=tuple(recordings), consent=consent)


def test_consent_block_on_meeting_3184s_shape():
    from docket.services import video_links as vl

    block = vl.consent_block(_run_3184())

    assert block == vl.ConsentBlock(start_s=1990.0, end_s=2085.0, chapter_id="371100")


def test_a_consent_cue_point_far_from_the_run_is_outside_the_block():
    from docket.services import video_links as vl

    # An item pulled off consent and discussed fifteen minutes later keeps its
    # is_consent flag; its cue point must not stretch the block.
    cues = _run_3184() + [(3000.0, "371199")]
    assert vl.consent_block(cues) == vl.ConsentBlock(1990.0, 2085.0, "371100")
    # The order the cue points arrive in does not matter.
    assert vl.consent_block([(3000.0, "371199")] + _run_3184()) == vl.ConsentBlock(1990.0, 2085.0, "371100")
    # One that is within the gap of the run's last cue point does join it.
    joined = vl.consent_block(_run_3184() + [(2085.0 + vl.CONSENT_GAP_S, "371199")])
    assert (joined.start_s, joined.end_s) == (1990.0, 2205.0)


def test_two_consent_cue_points_make_no_block():
    from docket.services import video_links as vl

    assert vl.consent_block([(1990.0, "371100"), (1995.0, "371101")]) is None
    assert vl.consent_block([]) is None
    # Three cue points that are not neighbours are three runs of one.
    assert vl.consent_block([(100.0, "1"), (400.0, "2"), (700.0, "3")]) is None
    # Three is enough, and a gap of exactly CONSENT_GAP_S still joins.
    assert vl.CONSENT_MIN_ITEMS == 3 and vl.CONSENT_GAP_S == 120.0
    assert vl.consent_block([(100.0, "1"), (220.0, "2"), (340.0, "3")]) == vl.ConsentBlock(100.0, 340.0, "1")
    assert vl.consent_block([(100.0, "1"), (220.5, "2"), (340.0, "3")]) is None
    # A cue point with no second is not a cue point.
    assert vl.consent_block([(100.0, "1"), (None, "2"), (110.0, "3")]) is None


def test_of_two_runs_the_larger_is_the_block_and_of_two_equal_the_earlier():
    from docket.services import video_links as vl

    small = [(100.0, "11"), (110.0, "12"), (120.0, "13")]
    large = [(900.0, "21"), (910.0, "22"), (920.0, "23"), (930.0, "24")]
    assert vl.consent_block(small + large) == vl.ConsentBlock(900.0, 930.0, "21")
    assert vl.consent_block(large + small) == vl.ConsentBlock(900.0, 930.0, "21")

    later = [(900.0, "21"), (910.0, "22"), (920.0, "23")]
    assert vl.consent_block(small + later) == vl.ConsentBlock(100.0, 120.0, "11")
    assert vl.consent_block(later + small) == vl.ConsentBlock(100.0, 120.0, "11")


def test_item_moment_follows_the_consent_rule():
    from docket.services import video_links as vl

    block = vl.ConsentBlock(start_s=1990.0, end_s=2085.0, chapter_id="371100")
    video = vl.MeetingVideo(video_url=PLAYER, consent=block)
    no_block = vl.MeetingVideo(video_url=PLAYER)

    # A consent item inside the block, and one with no cue point: the block's start.
    assert vl.item_moment(video, is_consent=True, cue_s=2040.0, external_id="371130") == (1990.0, "371100")
    assert vl.item_moment(video, is_consent=True, cue_s=1990.0, external_id="371100") == (1990.0, "371100")
    assert vl.item_moment(video, is_consent=True, cue_s=2085.0, external_id="371158") == (1990.0, "371100")
    assert vl.item_moment(video, is_consent=True, cue_s=None, external_id="event-2715-7") == (1990.0, "371100")
    # The block's first cue point is inside it too, which shows when that item's
    # own id is not the block's chapter.
    pdf_first = vl.MeetingVideo(video_url=PLAYER, consent=vl.ConsentBlock(1990.0, 2085.0, "371101"))
    assert vl.item_moment(pdf_first, is_consent=True, cue_s=1990.0, external_id="event-2715-1") == (1990.0, "371101")
    # A consent item outside the block (pulled and discussed later): its own moment.
    assert vl.item_moment(video, is_consent=True, cue_s=3000.0, external_id="371199") == (3000.0, "371199")
    assert vl.item_moment(video, is_consent=True, cue_s=1989.0, external_id="371099") == (1989.0, "371099")
    # A non-consent item: always its own, also when its cue point falls inside the block.
    assert vl.item_moment(video, is_consent=False, cue_s=2145.0, external_id="371161") == (2145.0, "371161")
    assert vl.item_moment(video, is_consent=False, cue_s=2000.0, external_id="371162") == (2000.0, "371162")
    assert vl.item_moment(video, is_consent=False, cue_s=None, external_id="371163") == (None, "371163")
    # A consent item with no cue point in a meeting with no block: nothing.
    assert vl.item_moment(no_block, is_consent=True, cue_s=None, external_id="event-2715-7") == (None, None)
    assert vl.item_moment(None, is_consent=True, cue_s=None, external_id="event-2715-7") == (None, None)
    # With no block a cued consent item is simply its own moment.
    assert vl.item_moment(no_block, is_consent=True, cue_s=2040.0, external_id="371130") == (2040.0, "371130")
    assert vl.item_moment(None, is_consent=False, cue_s=2145.0, external_id="371161") == (2145.0, "371161")


def test_vote_link_opens_the_items_moment_and_a_late_consent_vote_at_its_own_second():
    from docket.services import video_links as vl

    block = vl.ConsentBlock(start_s=1990.0, end_s=2085.0, chapter_id="371100")
    video = _meeting_3184(vl, consent=block)        # offset 635.48, covers 635.5 to 3935.5
    watch = "https://www.youtube.com/watch?v=" + YT + "&t="

    def url(vote_s, *, is_consent, cue_s, external_id, video=video):
        return vl.vote_link(video, vote_s=vote_s, is_consent=is_consent, cue_s=cue_s,
                            external_id=external_id).url

    in_run = dict(is_consent=True, cue_s=2040.0, external_id="371130")
    uncued = dict(is_consent=True, cue_s=None, external_id="event-2715-7")

    # The link stands for the item: a consent item read out in the run, or
    # with no cue point, opens the start of the run (1,990 s is t=1354s),
    # whether the vote was read before the run, inside it, or up to
    # CONSENT_GAP_S after its end (2,085 + 120 = 2,205 s).
    for vote_s in (1900.0, 2050.0, 2205.0):
        assert url(vote_s, **in_run) == watch + "1354s", vote_s
        assert url(vote_s, **uncued) == watch + "1354s", vote_s

    # The guard: a vote read more than CONSENT_GAP_S after the run is not the
    # reading of the consent agenda, so on YouTube it opens at its own second.
    assert url(2205.5, **in_run) == watch + "1570s"
    assert url(3119.0, **uncued) == watch + "2483s"
    late = vl.vote_link(video, vote_s=3119.0, **in_run)
    assert (late.site, late.seconds, late.timed) == ("youtube", 2483, True)

    # The guard is for YouTube alone. Past the recording's coverage the link
    # is the item's as before: the start of the run, on YouTube.
    assert url(4000.0, **in_run) == watch + "1354s"
    # With nothing measured, Granicus can only open a chapter: the run's.
    unmeasured = vl.MeetingVideo(video_url=PLAYER, consent=block)
    granicus = vl.vote_link(unmeasured, vote_s=3119.0, **in_run)
    assert (granicus.url, granicus.site, granicus.timed) == (PLAYER + "&meta_id=371100", "granicus", True)

    # Every other item keeps its own moment however late its vote: a consent
    # item whose cue point is outside the run, and a non-consent item.
    assert url(3900.0, is_consent=True, cue_s=3000.0, external_id="371199") == watch + "2364s"
    assert url(3900.0, is_consent=False, cue_s=2256.0, external_id="371164") == watch + "1620s"
    # Also a non-consent item that happens to be cued during the run (2,040 s is t=1404s).
    assert url(3900.0, is_consent=False, cue_s=2040.0, external_id="371131") == watch + "1404s"
    # An item with no moment of its own opens at the vote's second.
    assert url(2401.0, is_consent=False, cue_s=None, external_id="x") == watch + "1765s"
    no_block = _meeting_3184(vl)
    assert url(2401.0, video=no_block, **uncued) == watch + "1765s"

    # A meeting whose own video is on YouTube needs no conversion.
    own = vl.MeetingVideo(video_url="https://www.youtube.com/watch?v=" + YT, consent=block)
    assert url(3119.9, video=own, **in_run) == watch + "3119s"
    assert url(2100.0, video=own, **in_run) == watch + "1990s"

    assert vl.vote_link(None, vote_s=3119.0, **in_run) is None


def test_link_for_opens_youtube_at_the_converted_second():
    from docket.services import video_links as vl

    video = _meeting_3184(vl)

    link = vl.link_for(video, seconds=2256, chapter_id="371164")
    assert link.url == "https://www.youtube.com/watch?v=FR84h22hQvA&t=1620s"
    assert (link.site, link.label, link.seconds, link.timed) == ("youtube", "YouTube", 1620, True)
    assert link.phrase == "video on YouTube"

    assert vl.link_for(video, seconds=1990.0, chapter_id="371100").url == (
        "https://www.youtube.com/watch?v=FR84h22hQvA&t=1354s")
    assert vl.link_for(video, seconds=2145.0, chapter_id="371161").url == (
        "https://www.youtube.com/watch?v=FR84h22hQvA&t=1509s")
    # The chapter id plays no part once a recording covers the second.
    assert vl.link_for(video, seconds=2145.0).url == "https://www.youtube.com/watch?v=FR84h22hQvA&t=1509s"
    # A second that arrives as text (a template value) is read as a number.
    assert vl.link_for(video, seconds="2256").seconds == 1620


def test_a_moment_outside_coverage_opens_the_granicus_chapter():
    from docket.services import video_links as vl

    video = _meeting_3184(vl)

    link = vl.link_for(video, seconds=4000.0, chapter_id="371180")
    assert link.url == PLAYER + "&meta_id=371180"
    assert (link.site, link.label, link.seconds, link.timed) == ("granicus", "Granicus", None, True)
    assert link.phrase == "video chapter on Granicus"

    assert vl.link_for(video, seconds=600.0, chapter_id="371090").site == "granicus"
    # Coverage is half-open: its first second is covered and its last is not.
    first = vl.link_for(video, seconds=635.5, chapter_id="371091")
    assert (first.site, first.url) == ("youtube", "https://www.youtube.com/watch?v=FR84h22hQvA&t=0s")
    assert vl.link_for(video, seconds=3935.4, chapter_id="371179").site == "youtube"
    assert vl.link_for(video, seconds=3935.5, chapter_id="371180").site == "granicus"
    # With no second there is nothing to convert, whatever the recordings cover.
    assert vl.link_for(video, chapter_id="371180").url == PLAYER + "&meta_id=371180"


def test_no_recordings_opens_granicus_and_a_non_chapter_id_the_plain_player():
    from docket.services import video_links as vl

    video = vl.MeetingVideo(video_url=PLAYER)

    link = vl.link_for(video, seconds=2256.0, chapter_id="371164")
    assert (link.url, link.site, link.timed) == (PLAYER + "&meta_id=371164", "granicus", True)

    plain = vl.link_for(video, seconds=2256.0, chapter_id="event-2715-64")
    assert plain.url == PLAYER
    assert (plain.site, plain.label, plain.seconds, plain.timed) == ("granicus", "Granicus", None, False)
    assert plain.phrase == "video on Granicus"

    none = vl.link_for(video, seconds=2256.0)
    assert (none.url, none.timed) == (PLAYER, False)
    # The source button has no MeetingVideo, only the anchor's own URL.
    button = vl.link_for(None, seconds=65, chapter_id="371120", url=PLAYER)
    assert (button.url, button.site, button.timed) == (PLAYER + "&meta_id=371120", "granicus", True)


def test_of_two_recordings_the_one_that_covers_the_moment_and_of_two_that_do_the_first():
    from docket.services import video_links as vl

    part_1 = vl.Recording(video_id="partOne0001", offset_s=100.0, start_s=100.0, end_s=3000.0)
    part_2 = vl.Recording(video_id="partTwo0002", offset_s=3100.0, start_s=3100.0, end_s=6000.0)
    video = _meeting_3184(vl, recordings=(part_1, part_2))
    assert vl.link_for(video, seconds=4000.0).url == "https://www.youtube.com/watch?v=partTwo0002&t=900s"
    assert vl.link_for(video, seconds=2000.0).url == "https://www.youtube.com/watch?v=partOne0001&t=1900s"
    assert vl.link_for(video, seconds=3050.0, chapter_id="371150").site == "granicus"  # between the parts

    # The same meeting uploaded twice: both cover the second, the first in order wins.
    upload_1 = vl.Recording(video_id="96jZkW4zv7U", offset_s=101.28, start_s=101.3, end_s=5000.0)
    upload_2 = vl.Recording(video_id="E0cpl0Snx20", offset_s=90.0, start_s=90.0, end_s=5000.0)
    assert vl.link_for(_meeting_3184(vl, recordings=(upload_1, upload_2)), seconds=1000.0).url == (
        "https://www.youtube.com/watch?v=96jZkW4zv7U&t=898s")
    assert vl.link_for(_meeting_3184(vl, recordings=(upload_2, upload_1)), seconds=1000.0).url == (
        "https://www.youtube.com/watch?v=E0cpl0Snx20&t=910s")


def test_a_youtube_meeting_links_to_its_own_video_with_no_conversion():
    from docket.services import video_links as vl

    # A yt- row: the meeting's own video is the YouTube one, and its seconds
    # are already on YouTube's clock.
    video = vl.MeetingVideo(video_url="https://www.youtube.com/watch?v=FR84h22hQvA")

    link = vl.link_for(video, seconds=65.9, chapter_id="371120")
    assert link.url == "https://www.youtube.com/watch?v=FR84h22hQvA&t=65s"
    assert (link.site, link.label, link.seconds, link.timed) == ("youtube", "YouTube", 65, True)

    plain = vl.link_for(video)
    assert plain.url == "https://www.youtube.com/watch?v=FR84h22hQvA"
    assert (plain.site, plain.label, plain.seconds, plain.timed) == ("youtube", "YouTube", None, False)
    assert plain.phrase == "video on YouTube"
    # A second that cannot be read as a number is treated as absent.
    assert vl.link_for(video, seconds="soon").url == "https://www.youtube.com/watch?v=FR84h22hQvA"
    # So is a second before the video starts.
    assert vl.link_for(video, seconds=-5).url == "https://www.youtube.com/watch?v=FR84h22hQvA"


def test_an_unknown_host_is_returned_unchanged_and_no_url_gives_no_link():
    from docket.services import video_links as vl

    url = "https://video.example.com/watch/123?x=1#frag"
    link = vl.link_for(vl.MeetingVideo(video_url=url), seconds=65, chapter_id="371120")
    assert link.url == url
    assert (link.site, link.label, link.seconds, link.timed) == ("other", None, None, False)
    assert link.phrase == "video"
    # A Granicus address that is not the player page cannot take a chapter.
    assert vl.link_for(None, seconds=65, chapter_id="371120", url="https://granicus.example.com/player").site == "other"

    assert vl.link_for(vl.MeetingVideo(video_url=None), seconds=65, chapter_id="371120") is None
    assert vl.link_for(vl.MeetingVideo(video_url=""), seconds=65) is None
    assert vl.link_for(None, seconds=65, chapter_id="371120") is None
    assert vl.link_for(None) is None


def test_a_covered_moment_whose_converted_second_would_be_negative_opens_granicus():
    from docket.services import video_links as vl

    # A stored span that begins before its own offset: second 650 is "covered"
    # and would be 50 seconds before the recording starts.
    early = vl.Recording(video_id=YT, offset_s=700.0, start_s=635.5, end_s=3935.5)
    video = _meeting_3184(vl, recordings=(early,))

    link = vl.link_for(video, seconds=650.0, chapter_id="371092")
    assert (link.site, link.url) == ("granicus", PLAYER + "&meta_id=371092")
    assert vl.link_for(video, seconds=700.0).url == "https://www.youtube.com/watch?v=FR84h22hQvA&t=0s"
    # A later recording that holds the same second without going negative is used.
    late = vl.Recording(video_id="E0cpl0Snx20", offset_s=600.0, start_s=600.0, end_s=3000.0)
    both = _meeting_3184(vl, recordings=(early, late))
    assert vl.link_for(both, seconds=650.0).url == "https://www.youtube.com/watch?v=E0cpl0Snx20&t=50s"


def test_phrase_names_the_site_and_says_chapter_only_when_the_link_carries_one():
    from docket.services import video_links as vl

    def phrase(site, label, timed, seconds=None):
        return vl.VideoLink(url="https://example.com/", site=site, label=label, seconds=seconds, timed=timed).phrase

    assert phrase("youtube", "YouTube", True, 1620) == "video on YouTube"
    assert phrase("youtube", "YouTube", False) == "video on YouTube"
    assert phrase("granicus", "Granicus", True) == "video chapter on Granicus"
    assert phrase("granicus", "Granicus", False) == "video on Granicus"
    assert phrase("other", None, False) == "video"


def test_the_consent_blocks_chapter_is_the_first_all_digit_id_in_the_run():
    from docket.services import video_links as vl

    # The run's first item kept its agenda-PDF id; the next has a real chapter.
    run = [(1990.0, "event-2715-1"), (1992.0, "371121"), (1994.0, "371122")]
    assert vl.consent_block(run) == vl.ConsentBlock(1990.0, 1994.0, "371121")
    # A chapter id outside the winning run is not borrowed.
    assert vl.consent_block([(100.0, "371001")] + run) == vl.ConsentBlock(1990.0, 1994.0, "371121")
    # No id in the run is all digits: the first id is kept (and no link can use it).
    none = [(1990.0, "event-2715-1"), (1992.0, "event-2715-2"), (1994.0, None)]
    assert vl.consent_block(none) == vl.ConsentBlock(1990.0, 1994.0, "event-2715-1")
    video = vl.MeetingVideo(video_url=PLAYER, consent=vl.consent_block(none))
    start, chapter = vl.item_moment(video, is_consent=True, cue_s=1992.0, external_id="event-2715-2")
    assert vl.link_for(video, seconds=start, chapter_id=chapter).url == PLAYER


def test_a_youtube_link_is_built_from_the_video_id_and_never_by_appending():
    from docket.services import video_links as vl

    short = vl.MeetingVideo(video_url="https://youtu.be/FR84h22hQvA?t=10")
    assert vl.link_for(short, seconds=65).url == "https://www.youtube.com/watch?v=FR84h22hQvA&t=65s"
    assert vl.link_for(short).url == "https://www.youtube.com/watch?v=FR84h22hQvA"
    stale = vl.MeetingVideo(video_url="https://www.youtube.com/watch?v=FR84h22hQvA&t=10s&list=PL1")
    assert vl.link_for(stale, seconds=65).url == "https://www.youtube.com/watch?v=FR84h22hQvA&t=65s"

    assert vl.youtube_id("https://www.youtube.com/watch?v=FR84h22hQvA") == "FR84h22hQvA"
    assert vl.youtube_id("https://youtu.be/FR84h22hQvA") == "FR84h22hQvA"
    assert vl.youtube_id(PLAYER) is None
    assert vl.youtube_id(None) is None

    # A YouTube address with no video id is any other host.
    channel = "https://www.youtube.com/@citycouncilbham"
    link = vl.link_for(vl.MeetingVideo(video_url=channel), seconds=65)
    assert (link.url, link.site, link.label, link.timed) == (channel, "other", None, False)
    # So is a look-alike host whose address happens to carry v=.
    assert vl.youtube_id("https://notyoutube.com/watch?v=FR84h22hQvA") is None
    assert vl.youtube_id("https://www.youtube.com/watch?v=") is None
