"""What a reader sees of a vote a minutes reader wrote (plan `mobile-votes-from-minutes`, M5).

The three routes that print a vote (the meeting page, the item page and the
member page) are rendered over seeded rows. A vote with `minutes_reader` set
prints what the minutes declare in place of the stored result, the code and
caption the minutes print, the motion, and a link to the page of the city's
Minutes file it is printed on; a vote from any other writer renders as it did.

The meetings are seeded under external ids that begin `m5-test-` and the
council member under a name that begins `M5TEST`, and both are removed after.
"""

from __future__ import annotations

import re
from pathlib import Path

import psycopg2.extras
import pytest

from docket.db import db

PREFIX = "m5-test-"
MEMBER = "M5TEST Member"
MINUTES_URL = (
    "https://mobileal.api.civicclerk.com/v1/Meetings/"
    "GetMeetingFileStream(fileId=3854,plainText=false)"
)
UNSAFE_URL = "https://minutes.example.org/file.pdf"
BHAM_MINUTES_URL = "https://bhamal.granicus.com/MinutesViewer.php?view_id=2&clip_id=900001"
BHAM_VIDEO_URL = "https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=900001"

MOTION = (
    "Councilmember Ingram moved to adopt the resolution, which was seconded by "
    "Councilmember Gregory and the vote was as follows:"
)
CAPTION = "DECLARE THE STRUCTURE AT 1 EXAMPLE STREET A PUBLIC NUISANCE"
ITEM_TITLE = "40-948 Declare the structure at 1 Example Street a public nuisance"

LAYOUT_CSS = Path(__file__).resolve().parents[2] / "src/docket/web/static/layout.css"


def _cleanup() -> None:
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM meetings WHERE external_id LIKE %s", (PREFIX + "%",))
            cur.execute("DELETE FROM council_members WHERE name = %s", (MEMBER,))
        conn.commit()


def _meeting(cur, slug, ext, title, meeting_date, minutes_url=None, video_url=None) -> int:
    cur.execute(
        """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type,
                                 minutes_url, video_url)
           SELECT id, %s, %s, %s, 'council', %s, %s FROM municipalities WHERE slug = %s
           RETURNING id""",
        (PREFIX + ext, title, meeting_date, minutes_url, video_url, slug),
    )
    return cur.fetchone()["id"]


def _vote(cur, meeting_id, *, yeas=7, nays=0, result="passed", source="minutes_text",
          reader="mobile", page=None, declared=None, code=None, caption=None, motion=None,
          needs_review=False, review_reason=None, member_id=None, position="yea") -> int:
    cur.execute(
        """INSERT INTO votes (meeting_id, source, result, yeas, nays, abstentions, confidence,
                              needs_review, review_reason, resolution_number, minutes_reader,
                              source_page, caption, motion_text, declared_text)
           VALUES (%s, %s, %s, %s, %s, 0, 'high', %s, %s, %s, %s, %s, %s, %s, %s)
           RETURNING id""",
        (meeting_id, source, result, yeas, nays, needs_review, review_reason, code, reader,
         page, caption, motion, declared),
    )
    vote_id = cur.fetchone()["id"]
    cur.execute(
        "INSERT INTO member_votes (vote_id, council_member_id, member_name, position) "
        "VALUES (%s, NULL, 'Penn', 'yea')",
        (vote_id,),
    )
    if member_id is not None:
        cur.execute(
            "INSERT INTO member_votes (vote_id, council_member_id, member_name, position) "
            "VALUES (%s, %s, 'Member', %s)",
            (vote_id, member_id, position),
        )
    return vote_id


@pytest.fixture
def seeded():
    """Mobile and Birmingham meetings holding one vote of each kind this file reads.

    Mobile, 2026-11-03, with the city's minutes link: an older and a newer reader
    vote joined to one agenda item (`amendment`, `coded`), a reader vote with no item
    and no caption (`bare`), a flagged one (`flagged`), a carried motion to deny
    (`denied`) and an item held over (`held`). Mobile, 2026-10-27, no minutes link
    (`unlinked`). Mobile, 2026-10-20, a minutes link on a host outside the allowlist
    (`unsafe`). Mobile, 2026-10-13, a minutes vote no reader wrote (`plain`).
    Birmingham, 2026-11-04: a minutes vote (`bham_minutes`) and a video vote
    (`bham_video`).
    """
    _cleanup()
    ids: dict[str, int] = {}
    with db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO council_members (municipality_id, name, active)
                   SELECT id, %s, TRUE FROM municipalities WHERE slug = 'mobile' RETURNING id""",
                (MEMBER,),
            )
            member = ids["member"] = cur.fetchone()["id"]

            main = ids["main"] = _meeting(
                cur, "mobile", "main", "M5TEST Mobile council", "2026-11-03", MINUTES_URL)
            cur.execute(
                """INSERT INTO agenda_items (meeting_id, external_id, item_number, title,
                                             processing_status)
                   VALUES (%s, %s, '12', %s, 'completed') RETURNING id""",
                (main, PREFIX + "item", ITEM_TITLE),
            )
            ids["item"] = cur.fetchone()["id"]
            ids["amendment"] = _vote(
                cur, main, yeas=6, nays=1, page=4, declared="the amendment adopted",
                code="40-948-2026", caption=CAPTION,
                motion="Councilmember Small moved to amend the resolution.")
            ids["coded"] = _vote(
                cur, main, page=5, declared="the resolution adopted", code="40-948-2026",
                caption=CAPTION, motion=MOTION, member_id=member)
            for key in ("amendment", "coded"):
                cur.execute(
                    """INSERT INTO vote_agenda_items
                        (vote_id, agenda_item_id, association_type, match_method,
                         match_confidence, provisional, is_manual, is_active)
                       VALUES (%s, %s, 'explicit', 'minutes_code', 1.0, FALSE, FALSE, TRUE)""",
                    (ids[key], ids["item"]),
                )
            ids["bare"] = _vote(
                cur, main, page=2, declared="the agenda adopted",
                motion="Councilmember Small moved to adopt the agenda.", member_id=member)
            ids["flagged"] = _vote(
                cur, main, yeas=3, nays=0, result="unknown", page=9,
                caption="NOISE WAIVER FOR 2 EXAMPLE AVENUE",
                needs_review=True, review_reason="declaration_not_read")
            ids["denied"] = _vote(
                cur, main, page=11, declared="the waiver denied",
                caption="APPEAL OF A NOISE WAIVER FOR 3 EXAMPLE ROAD",
                motion="Councilmember Gregory moved to deny the waiver.", member_id=member)
            ids["held"] = _vote(
                cur, main, page=12, declared="the ordinance held over until November 10, 2026",
                code="64-042-2026", caption="AMEND THE EXAMPLE CODE")

            ids["unlinked_meeting"] = _meeting(
                cur, "mobile", "unlinked", "M5TEST no minutes link", "2026-10-27")
            ids["unlinked"] = _vote(
                cur, ids["unlinked_meeting"], page=3, declared="the resolution adopted")
            ids["unsafe_meeting"] = _meeting(
                cur, "mobile", "unsafe", "M5TEST unsafe minutes link", "2026-10-20", UNSAFE_URL)
            ids["unsafe"] = _vote(
                cur, ids["unsafe_meeting"], page=4, declared="the resolution adopted")
            ids["plain_meeting"] = _meeting(
                cur, "mobile", "plain", "M5TEST plain meeting", "2026-10-13", MINUTES_URL)
            ids["plain"] = _vote(
                cur, ids["plain_meeting"], yeas=1, reader=None, member_id=member)

            bham = ids["bham"] = _meeting(
                cur, "birmingham", "bham", "M5TEST Birmingham council", "2026-11-04",
                BHAM_MINUTES_URL, BHAM_VIDEO_URL)
            ids["bham_minutes"] = _vote(cur, bham, yeas=9, reader=None)
            ids["bham_video"] = _vote(
                cur, bham, yeas=3, nays=5, result="failed", source="video_ocr", reader=None)
        conn.commit()
    yield ids
    _cleanup()


def _page(client, path: str) -> str:
    resp = client.get(path)
    assert resp.status_code == 200, path
    return resp.get_data(as_text=True)


def _block(html: str, vote_id: int) -> str:
    """The meeting page's block of one vote: from its id to the next vote's, or the section's end."""
    start = html.index(f'id="vote-{vote_id}"')
    rest = html[start:]
    ends = [i for i in (rest.find('id="vote-', 1), rest.find("</section>")) if i != -1]
    return rest[: min(ends)]


def _text(html: str) -> str:
    """The text of a fragment, tags removed and white space run together."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _links(html: str) -> list[tuple[str, str]]:
    """(the whole opening tag, the link's text) of every link in a fragment."""
    return [(tag, _text(body)) for tag, body in re.findall(r"(<a\b[^>]*>)(.*?)</a>", html, re.S)]


def _main(client, ids) -> str:
    return _page(client, f"/al/mobile/meetings/{ids['main']}/")


# ── The meeting page ──────────────────────────────────────────────────────


def test_a_reader_vote_prints_the_declaration_in_its_head(client, seeded):
    block = _block(_main(client, seeded), seeded["coded"])
    head = re.search(r'<span class="vote-block-result[^"]*">(.*?)</span>', block, re.S)
    assert head is not None
    assert head.group(1).strip() == "the resolution adopted"


def test_a_reader_vote_prints_its_code_caption_motion_and_names(client, seeded):
    block = _block(_main(client, seeded), seeded["coded"])
    text = _text(block)
    assert f"40-948-2026 {CAPTION}" in text
    assert MOTION in text
    assert "Penn · YEA" in text
    assert "Member · YEA" in text
    # The vote is joined to its item, and the page still says which.
    assert "#12. " + ITEM_TITLE in text


def test_a_reader_vote_links_to_its_page_of_the_minutes(client, seeded):
    block = _block(_main(client, seeded), seeded["coded"])
    links = [(tag, text) for tag, text in _links(block) if "Minutes" in text]
    assert len(links) == 1
    tag, text = links[0]
    assert text.rstrip(" ↗") == "Minutes, page 5"
    assert f'href="{MINUTES_URL}#page=5"' in tag
    assert block.count("#page=") == 1


def test_the_page_link_opens_in_a_new_tab_without_a_referrer(client, seeded):
    block = _block(_main(client, seeded), seeded["coded"])
    (tag, _), = [(tag, text) for tag, text in _links(block) if "Minutes" in text]
    assert 'target="_blank"' in tag
    assert 'rel="noreferrer"' in tag


def test_each_reader_vote_links_to_its_own_page(client, seeded):
    html = _main(client, seeded)
    assert f'href="{MINUTES_URL}#page=4"' in _block(html, seeded["amendment"])
    assert "Minutes, page 4" in _text(_block(html, seeded["amendment"]))
    assert f'href="{MINUTES_URL}#page=2"' in _block(html, seeded["bare"])
    assert "Minutes, page 2" in _text(_block(html, seeded["bare"]))


def test_a_reader_vote_on_a_meeting_with_no_minutes_link_prints_no_link(client, seeded):
    html = _page(client, f"/al/mobile/meetings/{seeded['unlinked_meeting']}/")
    block = _block(html, seeded["unlinked"])
    assert "the resolution adopted" in block
    assert "#page=" not in block
    assert "Minutes, page" not in block


def test_a_reader_vote_whose_minutes_link_is_not_a_safe_address_prints_no_link(client, seeded):
    html = _page(client, f"/al/mobile/meetings/{seeded['unsafe_meeting']}/")
    block = _block(html, seeded["unsafe"])
    assert "the resolution adopted" in block
    assert "#page=" not in block
    assert "Minutes, page" not in block
    assert UNSAFE_URL not in block


def test_a_reader_vote_with_no_item_and_no_caption_does_not_say_no_item_is_linked(client, seeded):
    block = _block(_main(client, seeded), seeded["bare"])
    assert "No agenda item linked." not in block
    assert "Councilmember Small moved to adopt the agenda." in block
    # Nothing stands where the code and caption would: the motion follows the head.
    assert "None" not in _text(block)


def test_a_reader_vote_with_a_caption_and_no_item_prints_the_caption_alone(client, seeded):
    block = _block(_main(client, seeded), seeded["denied"])
    assert "No agenda item linked." not in block
    assert "APPEAL OF A NOISE WAIVER FOR 3 EXAMPLE ROAD" in block
    assert "None" not in _text(block)


def test_a_flagged_reader_vote_prints_the_review_callout(client, seeded):
    block = _block(_main(client, seeded), seeded["flagged"])
    assert "Needs review" in block
    assert "declaration_not_read" in block
    # With no declaration the head prints the stored result, as any other vote's does.
    assert '<span class="vote-block-result">unknown</span>' in block
    assert "NOISE WAIVER FOR 2 EXAMPLE AVENUE" in block
    assert "Minutes, page 9" in _text(block)


def test_the_declared_head_has_its_class_and_no_other_head_does(client, seeded):
    html = _main(client, seeded)
    assert ('<span class="vote-block-result vote-block-result--declared">the resolution adopted</span>'
            in _block(html, seeded["coded"]))
    assert "vote-block-result--declared" not in _block(html, seeded["flagged"])
    bham = _page(client, f"/al/birmingham/meetings/{seeded['bham']}/")
    assert "vote-block-result--declared" not in bham
    assert '<span class="vote-block-result">passed</span>' in _block(bham, seeded["bham_minutes"])


def test_the_block_is_coloured_by_what_was_declared(client, seeded):
    html = _main(client, seeded)

    def classes(key: str) -> list[str]:
        return re.match(r'id="vote-\d+" class="([^"]*)"', _block(html, seeded[key])).group(1).split()

    assert "is-pass" in classes("coded")
    # A motion to deny that carried: the result is passed and the waiver was denied.
    assert "is-fail" in classes("denied") and "is-pass" not in classes("denied")
    assert "is-pass" not in classes("held") and "is-fail" not in classes("held")
    assert "is-pass" not in classes("flagged") and "is-fail" not in classes("flagged")


def test_a_birmingham_minutes_vote_and_a_video_vote_render_as_before(client, seeded):
    html = _page(client, f"/al/birmingham/meetings/{seeded['bham']}/")
    minutes = _block(html, seeded["bham_minutes"])
    video = _block(html, seeded["bham_video"])

    assert re.match(r'id="vote-\d+" class="vote-block is-pass is-substantive"', minutes)
    assert '<span class="vote-block-result">passed</span>' in minutes
    assert "No agenda item linked." in minutes
    assert "official minutes · high" in _text(minutes)
    assert "9–0" in minutes

    assert re.match(r'id="vote-\d+" class="vote-block is-fail is-substantive"', video)
    assert '<span class="vote-block-result">failed</span>' in video
    assert "No agenda item linked." in video
    assert "video OCR · high" in _text(video)

    for block in (minutes, video):
        assert "#page=" not in block
        assert "Minutes, page" not in block


def test_a_minutes_vote_no_reader_wrote_renders_as_before_in_a_reader_city(client, seeded):
    html = _page(client, f"/al/mobile/meetings/{seeded['plain_meeting']}/")
    block = _block(html, seeded["plain"])
    assert '<span class="vote-block-result">passed</span>' in block
    assert "No agenda item linked." in block
    assert "#page=" not in block


# ── The item page ─────────────────────────────────────────────────────────


def _vote_result(client, ids) -> str:
    html = _page(client, f"/al/mobile/items/{ids['item']}/")
    start = html.index('<section class="item-vote-result">')
    return html[start: html.index("</section>", start)]


def test_the_item_page_prints_the_declaration_of_a_code_joined_vote(client, seeded):
    section = _vote_result(client, seeded)
    assert ('<span class="vote-block-result vote-block-result--declared">the resolution adopted</span>'
            in section)
    assert re.search(r'<div class="vote-block is-pass\s*">', section)


def test_the_item_pages_vote_link_names_the_page(client, seeded):
    section = _vote_result(client, seeded)
    banner = section[: section.index('<details class="vote-history">')]
    (tag, text), = _links(banner)
    assert text.rstrip(" ↗") == "Read minutes, page 5"
    assert f'href="{MINUTES_URL}#page=5"' in tag
    assert 'target="_blank"' in tag
    assert 'rel="noreferrer"' in tag


def test_the_item_pages_history_row_prints_its_own_declaration_and_page(client, seeded):
    section = _vote_result(client, seeded)
    history = section[section.index('<details class="vote-history">'):]
    assert re.search(
        r'<span class="vote-history-result t-mono vote-block-result--declared">\s*'
        r'the amendment adopted\s*</span>', history)
    (tag, text), = _links(history)
    assert text.rstrip(" ↗") == "Read minutes, page 4"
    assert f'href="{MINUTES_URL}#page=4"' in tag


def test_the_item_page_prints_no_page_link_for_an_address_that_is_not_safe(client, seeded):
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE meetings SET minutes_url = %s WHERE id = %s",
                        (UNSAFE_URL, seeded["main"]))
        conn.commit()
    section = _vote_result(client, seeded)
    assert "the resolution adopted" in section
    assert "#page=" not in section
    assert UNSAFE_URL not in section
    assert "Vote in meeting context" in section


# ── The member page ───────────────────────────────────────────────────────


def _history_rows(client, ids) -> dict[int, str]:
    html = _page(client, f"/al/mobile/council/{ids['member']}/")
    rows = re.findall(r'<a class="member-history-row vote-row"\s+href="[^"]*#vote-(\d+)">(.*?)</a>',
                      html, re.S)
    return {int(vote_id): _text(body) for vote_id, body in rows}


def test_the_member_page_prints_the_declaration_after_the_count(client, seeded):
    rows = _history_rows(client, seeded)
    assert "7–0 · the resolution adopted" in rows[seeded["coded"]]
    assert "7–0 · the waiver denied" in rows[seeded["denied"]]
    assert "passed" not in rows[seeded["coded"]]


def test_the_member_page_prints_the_caption_where_the_vote_has_no_agenda_link(client, seeded):
    rows = _history_rows(client, seeded)
    assert "APPEAL OF A NOISE WAIVER FOR 3 EXAMPLE ROAD" in rows[seeded["denied"]]
    assert "M5TEST Mobile council" not in rows[seeded["denied"]]
    # A vote joined to an item is still titled by the item, not by the caption.
    assert ITEM_TITLE in rows[seeded["coded"]]
    assert CAPTION not in rows[seeded["coded"]]
    # With neither a link nor a caption the meeting's title stands.
    assert "M5TEST Mobile council" in rows[seeded["bare"]]


def test_the_member_page_prints_any_other_vote_as_before(client, seeded):
    rows = _history_rows(client, seeded)
    assert "M5TEST plain meeting" in rows[seeded["plain"]]
    assert "1–0 · passed" in rows[seeded["plain"]]


# ── The stylesheet and the template globals ───────────────────────────────


def test_the_stylesheet_prints_a_declaration_as_the_minutes_have_it():
    css = re.sub(r"\s+", " ", LAYOUT_CSS.read_text(encoding="utf-8"))
    assert ".vote-block-result--declared { text-transform: none; letter-spacing: normal; }" in css
    # The rule comes after the two it overrides, which have its specificity.
    declared = css.index(".vote-block-result--declared {")
    assert css.index(".vote-block-result {") < declared
    assert css.index(".vote-history-result {") < declared


def test_the_label_and_the_tone_are_template_globals():
    from docket.models.vote import vote_label, vote_tone
    from docket.web import create_app

    app = create_app()
    assert app.jinja_env.globals["vote_label"] is vote_label
    assert app.jinja_env.globals["vote_tone"] is vote_tone
