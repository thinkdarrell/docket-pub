"""docket.services.query: the reads behind the editorial-coverage admin pages.

``list_coverage_for_admin`` (the list and its filter tabs),
``list_active_outlets`` (the new-entry form), ``get_coverage_for_edit`` (the
edit form) and ``search_coverage_subjects`` (the subject picker) hold the
statements ``src/docket/web/admin.py`` executed itself before plan
`admin-routes-call-services`, M3.

Seeded rows carry the prefix ``admcov_test_`` (usernames, outlet slugs, the
city slug) or, for badge templates, ``admcovtest-`` (no underscore, so a
search for an underscore can tell a template that holds one from one that
does not), and are deleted before and after every test. Agenda items,
meetings and council members that a subject link points at are seeded under
explicit ids in three ranges of their own, because the label statement looks
one id up in all three tables. Every function here reads a whole table that
other tests and the migrations also fill, so the tests assert on the rows
seeded here, on a difference between two readings, or on something true of
every row returned. Each service name is imported inside the test, so the
file collects before the functions exist. Runs in the services tier
(DATABASE_URL names docket_test_*).
"""

from __future__ import annotations

import datetime
import itertools

import pytest

from docket.db import db_cursor

PREFIX = "admcov_test_"
BADGE_PREFIX = "admcovtest-"
CITY_SLUG = PREFIX + "city"
NO_SUCH_ID = 999999999
ITEM_IDS = 987650100
MEETING_IDS = 987650200
MEMBER_IDS = 987650300

_serial = itertools.count(1)


def _delete_seeded() -> None:
    like = (PREFIX + "%",)
    with db_cursor() as cur:
        cur.execute(
            "DELETE FROM coverage_entries WHERE author_id IN "
            "(SELECT id FROM admin_users WHERE username LIKE %s)",
            like,
        )
        cur.execute("DELETE FROM outlets WHERE slug LIKE %s", like)
        cur.execute("DELETE FROM admin_users WHERE username LIKE %s", like)
        cur.execute(
            "DELETE FROM meetings WHERE municipality_id IN "
            "(SELECT id FROM municipalities WHERE slug LIKE %s)",
            like,
        )
        cur.execute(
            "DELETE FROM council_members WHERE municipality_id IN "
            "(SELECT id FROM municipalities WHERE slug LIKE %s)",
            like,
        )
        cur.execute(
            "DELETE FROM priority_badge_templates WHERE slug LIKE %s",
            (BADGE_PREFIX + "%",),
        )
        cur.execute("DELETE FROM municipalities WHERE slug LIKE %s", like)


@pytest.fixture(autouse=True)
def _clean():
    _delete_seeded()
    yield
    _delete_seeded()


@pytest.fixture
def author() -> int:
    return _user("author", "Admcov Byline")


@pytest.fixture
def city() -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO municipalities (slug, name, adapter_class, adapter_config, active)
               VALUES (%s, 'Admcov Test City', 'GranicusAdapter', '{}', TRUE) RETURNING id""",
            (CITY_SLUG,),
        )
        return cur.fetchone()["id"]


def _user(suffix: str, display_name) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO admin_users (username, password_hash, display_name) "
            "VALUES (%s, 'unused', %s) RETURNING id",
            (PREFIX + suffix, display_name),
        )
        return cur.fetchone()["id"]


def _outlet(suffix: str, name: str, *, active: bool = True) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO outlets (slug, name, is_active) VALUES (%s, %s, %s) RETURNING id",
            (PREFIX + suffix, name, active),
        )
        return cur.fetchone()["id"]


def _note(author_id: int, *, status: str = "draft", body: str = "Admcov note body.",
          minutes_ago: int = 0, featured_until=None) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO coverage_entries (kind, status, body, author_id, updated_at, featured_until)
               VALUES ('note', %s::coverage_status, %s, %s,
                       NOW() - (%s || ' minutes')::interval, %s)
               RETURNING id""",
            (status, body, author_id, minutes_ago, featured_until),
        )
        return cur.fetchone()["id"]


def _citation(author_id: int, outlet_id: int, *, status: str = "draft",
              headline: str = "Admcov headline", minutes_ago: int = 0) -> int:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO coverage_entries
                      (kind, status, outlet_id, external_url, headline, author_id, updated_at)
               VALUES ('citation', %s::coverage_status, %s, 'https://example.test/admcov', %s, %s,
                       NOW() - (%s || ' minutes')::interval)
               RETURNING id""",
            (status, outlet_id, headline, author_id, minutes_ago),
        )
        return cur.fetchone()["id"]


def _link(coverage_id: int, subject_type: str, subject_id=None, subject_slug=None) -> None:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO coverage_subject_links (coverage_id, subject_type, subject_id, subject_slug)
               VALUES (%s, %s::coverage_subject_type, %s, %s)""",
            (coverage_id, subject_type, subject_id, subject_slug),
        )


def _meeting(city_id: int, title: str, day: str, *, meeting_id: int | None = None) -> int:
    meeting_id = meeting_id or MEETING_IDS + next(_serial)
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO meetings (id, municipality_id, title, meeting_date) VALUES (%s, %s, %s, %s)",
            (meeting_id, city_id, title, day),
        )
    return meeting_id


def _item(meeting_id: int, title: str) -> int:
    item_id = ITEM_IDS + next(_serial)
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO agenda_items (id, meeting_id, title) VALUES (%s, %s, %s)",
            (item_id, meeting_id, title),
        )
    return item_id


def _member(city_id: int, name: str) -> int:
    member_id = MEMBER_IDS + next(_serial)
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO council_members (id, municipality_id, name) VALUES (%s, %s, %s)",
            (member_id, city_id, name),
        )
    return member_id


def _badge(suffix: str, name: str) -> str:
    slug = BADGE_PREFIX + suffix
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO priority_badge_templates (slug, name, description, icon, kind)
               VALUES (%s, %s, 'Admcov test template', 'star', 'policy')""",
            (slug, name),
        )
    return slug


def _mine(rows, ids) -> list[dict]:
    wanted = set(ids)
    return [dict(r) for r in rows if r["id"] in wanted]


# --- list_coverage_for_admin -------------------------------------------------


def test_list_coverage_for_admin_with_no_filter_holds_the_nine_columns_of_each_entry(author):
    from docket.services.query import list_coverage_for_admin

    plain = _user("plain", None)
    outlet = _outlet("gazette", "Admcov Gazette")
    until = datetime.datetime(2031, 5, 6, 12, 0, tzinfo=datetime.timezone.utc)
    note = _note(author, status="published", body="Admcov published note.", featured_until=until)
    cite = _citation(plain, outlet, status="draft", headline="Admcov cited headline")

    rows, _counts, _subjects = list_coverage_for_admin(None, None)

    by_id = {r["id"]: dict(r) for r in rows}
    assert set(by_id[note]) == {
        "id", "kind", "status", "body", "headline", "updated_at",
        "featured_until", "author_label", "outlet_name",
    }
    updated = by_id[note].pop("updated_at")
    assert isinstance(updated, datetime.datetime)
    assert by_id[note] == {
        "id": note, "kind": "note", "status": "published",
        "body": "Admcov published note.", "headline": None,
        "featured_until": until, "author_label": "Admcov Byline", "outlet_name": None,
    }
    by_id[cite].pop("updated_at")
    assert by_id[cite] == {
        "id": cite, "kind": "citation", "status": "draft",
        "body": None, "headline": "Admcov cited headline",
        "featured_until": None, "author_label": PREFIX + "plain",
        "outlet_name": "Admcov Gazette",
    }


def test_list_coverage_for_admin_is_newest_update_first(author):
    from docket.services.query import list_coverage_for_admin

    middle = _note(author, minutes_ago=20)
    oldest = _note(author, minutes_ago=30)
    newest = _note(author, minutes_ago=10)

    rows, _counts, _subjects = list_coverage_for_admin(None, None)

    assert [r["id"] for r in _mine(rows, [middle, oldest, newest])] == [newest, middle, oldest]


def test_list_coverage_for_admin_with_a_status_filter_holds_that_status_only(author):
    from docket.services.query import list_coverage_for_admin

    outlet = _outlet("gazette", "Admcov Gazette")
    draft_note = _note(author, status="draft")
    draft_cite = _citation(author, outlet, status="draft")
    published = _note(author, status="published")

    rows, _counts, _subjects = list_coverage_for_admin("draft", None)

    assert {r["status"] for r in rows} == {"draft"}
    got = {r["id"] for r in rows}
    assert {draft_note, draft_cite} <= got
    assert published not in got


def test_list_coverage_for_admin_with_a_kind_filter_holds_that_kind_only(author):
    from docket.services.query import list_coverage_for_admin

    outlet = _outlet("gazette", "Admcov Gazette")
    draft_note = _note(author, status="draft")
    published_note = _note(author, status="published")
    cite = _citation(author, outlet, status="draft")

    rows, _counts, _subjects = list_coverage_for_admin(None, "note")

    assert {r["kind"] for r in rows} == {"note"}
    got = {r["id"] for r in rows}
    assert {draft_note, published_note} <= got
    assert cite not in got


def test_list_coverage_for_admin_with_both_filters_holds_rows_that_meet_both(author):
    from docket.services.query import list_coverage_for_admin

    outlet = _outlet("gazette", "Admcov Gazette")
    wanted = _citation(author, outlet, status="proposed")
    other_status = _citation(author, outlet, status="draft")
    other_kind = _note(author, status="proposed")

    rows, _counts, _subjects = list_coverage_for_admin("proposed", "citation")

    assert {(r["status"], r["kind"]) for r in rows} == {("proposed", "citation")}
    got = {r["id"] for r in rows}
    assert wanted in got
    assert other_status not in got and other_kind not in got


def test_list_coverage_for_admin_with_a_kind_no_entry_of_that_status_has(author, city):
    from docket.services.query import list_coverage_for_admin

    meeting = _meeting(city, "Admcov meeting", "2026-04-15")
    note = _note(author, status="rejected")
    _link(note, "meeting", subject_id=meeting)

    rows, _counts, subjects = list_coverage_for_admin("rejected", "citation")

    assert note not in {r["id"] for r in rows}
    assert note not in subjects


def test_list_coverage_for_admin_returns_at_most_two_hundred_rows(author):
    from docket.services.query import list_coverage_for_admin

    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO coverage_entries (kind, status, body, author_id)
               SELECT 'note', 'rejected', 'Admcov bulk note ' || n, %s
                 FROM generate_series(1, 201) AS n""",
            (author,),
        )

    rows, _counts, _subjects = list_coverage_for_admin("rejected", "note")

    assert len(rows) == 200


def test_list_coverage_for_admin_counts_every_status_whatever_the_filter(author):
    from docket.services.query import list_coverage_for_admin

    _rows, before, _subjects = list_coverage_for_admin(None, None)
    _note(author, status="draft")
    _note(author, status="draft")
    _note(author, status="published")
    _rows, after, _subjects = list_coverage_for_admin("rejected", "citation")

    assert after["draft"] - before.get("draft", 0) == 2
    assert after["published"] - before.get("published", 0) == 1
    assert after.get("proposed", 0) == before.get("proposed", 0)
    assert after.get("rejected", 0) == before.get("rejected", 0)


def test_list_coverage_for_admin_labels_the_subjects_of_each_entry_in_link_order(author, city):
    from docket.services.query import list_coverage_for_admin

    meeting = _meeting(city, "Admcov subject meeting", "2026-04-15")
    item = _item(meeting, "Admcov subject item")
    member = _member(city, "Admcov Subject Member")
    badge = _badge("subject", "Admcov Subject Badge")
    first = _note(author)
    _link(first, "council_member", subject_id=member)
    _link(first, "badge", subject_slug=badge)
    _link(first, "agenda_item", subject_id=item)
    _link(first, "meeting", subject_id=meeting)
    # Rewrite the first link, so the table no longer holds the four in the
    # order they were made and only the statement's ORDER BY gives it back.
    with db_cursor() as cur:
        cur.execute(
            "UPDATE coverage_subject_links SET created_at = created_at - INTERVAL '1 hour' "
            "WHERE coverage_id = %s AND subject_type = 'council_member'",
            (first,),
        )
    second = _note(author)
    _link(second, "agenda_item", subject_id=NO_SUCH_ID)
    bare = _note(author)

    _rows, _counts, subjects = list_coverage_for_admin(None, None)

    assert subjects[first] == [
        {"subject_type": "council_member", "label": "Admcov Subject Member"},
        {"subject_type": "badge", "label": "Admcov Subject Badge"},
        {"subject_type": "agenda_item", "label": "Admcov subject item"},
        {"subject_type": "meeting", "label": "Admcov subject meeting"},
    ]
    assert subjects[second] == [{"subject_type": "agenda_item", "label": ""}]
    assert bare not in subjects


def test_list_coverage_for_admin_holds_subjects_only_for_the_rows_it_returns(author, city):
    from docket.services.query import list_coverage_for_admin

    meeting = _meeting(city, "Admcov subject meeting", "2026-04-15")
    draft = _note(author, status="draft")
    _link(draft, "meeting", subject_id=meeting)
    published = _note(author, status="published")
    _link(published, "meeting", subject_id=meeting)

    rows, _counts, subjects = list_coverage_for_admin("published", None)

    assert published in subjects and draft not in subjects
    assert set(subjects) <= {r["id"] for r in rows}


# --- list_active_outlets -----------------------------------------------------


def test_list_active_outlets_holds_three_columns_and_leaves_out_an_inactive_outlet():
    from docket.services.query import list_active_outlets

    live = _outlet("live", "Admcov Live Outlet")
    gone = _outlet("gone", "Admcov Gone Outlet", active=False)

    rows = list_active_outlets()

    assert _mine(rows, [live, gone]) == [
        {"id": live, "slug": PREFIX + "live", "name": "Admcov Live Outlet"}
    ]


def test_list_active_outlets_is_ordered_by_name():
    from docket.services.query import list_active_outlets

    zulu = _outlet("a", "Admcov Zulu")
    alpha = _outlet("b", "Admcov Alpha")
    mike = _outlet("c", "Admcov Mike")

    rows = list_active_outlets()

    assert [r["id"] for r in _mine(rows, [zulu, alpha, mike])] == [alpha, mike, zulu]
    names = [r["name"] for r in rows]
    assert names.index("Admcov Alpha") < names.index("Admcov Mike") < names.index("Admcov Zulu")


# --- get_coverage_for_edit ---------------------------------------------------


def test_get_coverage_for_edit_returns_the_entry_its_links_and_the_outlets(author, city):
    from docket.services.query import get_coverage_for_edit

    used = _outlet("used", "Admcov Mike Used", active=False)
    live_late = _outlet("late", "Admcov Zulu Live")
    live_early = _outlet("early", "Admcov Alpha Live")
    other_gone = _outlet("gone", "Admcov Bravo Gone", active=False)
    meeting = _meeting(city, "Admcov edit meeting", "2026-04-15")
    badge = _badge("edit", "Admcov Edit Badge")
    cite = _citation(author, used, status="published", headline="Admcov edit headline")
    _link(cite, "meeting", subject_id=meeting)
    _link(cite, "badge", subject_slug=badge)
    other = _note(author)
    _link(other, "agenda_item", subject_id=NO_SUCH_ID)

    entry, subjects, outlets = get_coverage_for_edit(cite)

    entry = dict(entry)
    assert {
        "id", "kind", "status", "source", "body", "partner_credit", "outlet_id",
        "external_url", "headline", "reporter_byline", "excerpt",
        "article_published_at", "author_id", "byline", "created_at", "updated_at",
        "published_at", "featured_until",
    } <= set(entry)
    assert (entry["id"], entry["kind"], entry["status"], entry["outlet_id"]) == (
        cite, "citation", "published", used,
    )
    assert (entry["headline"], entry["external_url"], entry["author_id"]) == (
        "Admcov edit headline", "https://example.test/admcov", author,
    )
    assert sorted(
        (dict(s) for s in subjects), key=lambda s: s["subject_type"]
    ) == [
        {"subject_type": "badge", "subject_id": None, "subject_slug": badge},
        {"subject_type": "meeting", "subject_id": meeting, "subject_slug": None},
    ]
    assert _mine(outlets, [used, live_late, live_early, other_gone]) == [
        {"id": live_early, "slug": PREFIX + "early", "name": "Admcov Alpha Live"},
        {"id": used, "slug": PREFIX + "used", "name": "Admcov Mike Used"},
        {"id": live_late, "slug": PREFIX + "late", "name": "Admcov Zulu Live"},
    ]


def test_get_coverage_for_edit_of_a_note_lists_active_outlets_only(author):
    from docket.services.query import get_coverage_for_edit

    live = _outlet("live", "Admcov Live Outlet")
    gone = _outlet("gone", "Admcov Gone Outlet", active=False)
    note = _note(author, body="Admcov edit note.")

    entry, subjects, outlets = get_coverage_for_edit(note)

    assert (entry["id"], entry["body"], entry["outlet_id"]) == (note, "Admcov edit note.", None)
    assert list(subjects) == []
    assert [r["id"] for r in _mine(outlets, [live, gone])] == [live]


def test_get_coverage_for_edit_for_an_unknown_id_is_none(author):
    from docket.services.query import get_coverage_for_edit

    _note(author)
    assert get_coverage_for_edit(NO_SUCH_ID) is None


# --- search_coverage_subjects ------------------------------------------------

SUBJECT_TYPES = ["agenda_item", "meeting", "council_member", "badge"]


class _Subjects:
    """Seeds one row of a subject type whose searched text is ``text``."""

    def __init__(self, city_id: int):
        self.city_id = city_id
        self.holder = _meeting(city_id, "Holder of the test items", "2001-01-01")

    def add(self, subject_type: str, text: str):
        """Return (the id the search hands back, the label it hands back)."""
        n = next(_serial)
        if subject_type == "agenda_item":
            return _item(self.holder, text), text
        if subject_type == "meeting":
            day = datetime.date(2090, 1, 1) + datetime.timedelta(days=n)
            return _meeting(self.city_id, text, day.isoformat()), f"{text} ({day:%Y-%m-%d})"
        if subject_type == "council_member":
            return _member(self.city_id, text), text
        return _badge(f"s{n}", text), text


@pytest.fixture
def seed(city) -> _Subjects:
    return _Subjects(city)


@pytest.mark.parametrize("subject_type", SUBJECT_TYPES)
def test_search_coverage_subjects_finds_a_row_of_that_type_whatever_its_case(seed, subject_type):
    from docket.services.query import search_coverage_subjects

    found_id, label = seed.add(subject_type, "The Zzqadmcov Paving Matter")
    seed.add(subject_type, "The Other Admcov Matter")
    for other in SUBJECT_TYPES:
        if other != subject_type:
            seed.add(other, "A Zzqadmcov row of another type")

    assert search_coverage_subjects(subject_type, "zzqADMCOV pav") == [
        {"id": found_id, "label": label}
    ]


def test_search_coverage_subjects_for_agenda_items_is_highest_id_first(seed):
    from docket.services.query import search_coverage_subjects

    ids = [seed.add("agenda_item", f"Zzqadmcov item {n}")[0] for n in range(3)]

    got = [r["id"] for r in search_coverage_subjects("agenda_item", "Zzqadmcov item")]

    assert got == sorted(ids, reverse=True)


def test_search_coverage_subjects_for_meetings_is_latest_date_first(city):
    from docket.services.query import search_coverage_subjects

    middle = _meeting(city, "Zzqadmcov session", "2026-03-03")
    latest = _meeting(city, "Zzqadmcov session", "2026-09-09")
    earliest = _meeting(city, "Zzqadmcov session", "2025-01-01")

    assert search_coverage_subjects("meeting", "Zzqadmcov session") == [
        {"id": latest, "label": "Zzqadmcov session (2026-09-09)"},
        {"id": middle, "label": "Zzqadmcov session (2026-03-03)"},
        {"id": earliest, "label": "Zzqadmcov session (2025-01-01)"},
    ]


def test_search_coverage_subjects_for_badges_matches_the_slug_too_and_returns_it_as_id(seed):
    from docket.services.query import search_coverage_subjects

    slug, _label = seed.add("badge", "Admcov Plainly Named")

    assert search_coverage_subjects("badge", slug.upper()) == [
        {"id": slug, "label": "Admcov Plainly Named"}
    ]


@pytest.mark.parametrize("subject_type", SUBJECT_TYPES)
def test_search_coverage_subjects_returns_at_most_fifteen(seed, subject_type):
    from docket.services.query import search_coverage_subjects

    for n in range(16):
        seed.add(subject_type, f"Zzqadmcov many {n}")

    assert len(search_coverage_subjects(subject_type, "Zzqadmcov many")) == 15


@pytest.mark.parametrize("subject_type", SUBJECT_TYPES)
@pytest.mark.parametrize("needle", ["%", "_", "\\"])
def test_search_coverage_subjects_takes_a_wildcard_character_literally(seed, subject_type, needle):
    """A needle of ``%``, ``_`` or a backslash matches only a row that holds it."""
    from docket.services.query import search_coverage_subjects

    with_id, _label = seed.add(subject_type, f"Zzqadmcov 50{needle}off")
    without_id, _label = seed.add(subject_type, "Zzqadmcov plain")

    results = search_coverage_subjects(subject_type, needle)

    got = {r["id"] for r in results}
    assert with_id in got
    assert without_id not in got
    for r in results:
        assert needle in r["label"] or (subject_type == "badge" and needle in r["id"])


def test_search_coverage_subjects_for_an_unknown_subject_type_is_an_empty_list(seed):
    from docket.services.query import search_coverage_subjects

    for subject_type in SUBJECT_TYPES:
        seed.add(subject_type, "Zzqadmcov everywhere")

    assert search_coverage_subjects("ordinance", "Zzqadmcov") == []
