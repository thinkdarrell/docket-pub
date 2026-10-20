"""docket.services.briefing: the precomputed facts, the source rule, and the dollar check.

Every database test seeds Birmingham through tests/support/briefing_seed.py
and cleans up by its title prefix; the throwaway database is otherwise empty
of meetings. Runs in the services tier (DATABASE_URL names docket_test_*).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pytest

from docket.db import db, db_cursor
from docket.services import briefing
from tests.support import briefing_seed


@pytest.fixture
def seeded(request):
    options = getattr(request, "param", {})
    with db() as conn:
        ids = briefing_seed.seed(conn, **options)
    try:
        yield ids
    finally:
        with db() as conn:
            briefing_seed.cleanup(conn)


class _CountingCursor:
    """Delegates to a real cursor and records every execute."""

    def __init__(self, cur, log):
        self._cur = cur
        self._log = log

    def execute(self, sql, params=None):
        self._log.append(sql)
        return self._cur.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._cur, name)


@contextmanager
def _counting(log):
    with db_cursor() as cur:
        yield _CountingCursor(cur, log)


def _facts_rows():
    with db_cursor() as cur:
        cur.execute(
            """SELECT fact_set, payload, computed_at FROM city_briefing_facts
                WHERE municipality_id = (SELECT id FROM municipalities WHERE slug = 'birmingham')
                ORDER BY fact_set"""
        )
        return cur.fetchall()


# --- recompute -------------------------------------------------------------


def test_recompute_writes_two_rows_in_one_statement(seeded, monkeypatch):
    executed: list[str] = []
    monkeypatch.setattr(briefing, "db_cursor", lambda: _counting(executed))
    briefing.recompute_city_facts(seeded["municipality_id"])
    assert len(executed) == 3, "two SELECTs and one upsert"
    assert executed[2].lstrip().upper().startswith("INSERT INTO CITY_BRIEFING_FACTS")
    assert "ON CONFLICT (municipality_id, fact_set)" in executed[2]
    rows = _facts_rows()
    assert [r["fact_set"] for r in rows] == ["member_counts", "split_votes"]
    assert rows[0]["computed_at"] == rows[1]["computed_at"]
    # Running it again rewrites the same two rows in place.
    briefing.recompute_city_facts(seeded["municipality_id"])
    assert len(_facts_rows()) == 2


def test_split_votes_payload_uses_minutes_over_video_and_excludes_review(seeded):
    payload = briefing.recompute_city_facts(seeded["municipality_id"])["split_votes"]
    assert payload["window_days"] == 180
    assert payload["since"] == (date.today() - timedelta(days=180)).isoformat()
    # vote 3 (video_ocr, needs_review, three nays) is neither a split nor counted.
    assert payload["votes_in_window"] == 2
    assert len(payload["splits"]) == 1
    split = payload["splits"][0]
    assert split["vote_id"] == seeded["votes"]["split"]
    assert split["source"] == "minutes_text"
    assert split["meeting_id"] == seeded["past_meeting_id"]
    assert split["meeting_date"] == seeded["past_meeting_date"].isoformat()
    assert (split["result"], split["yeas"], split["nays"], split["abstentions"]) == ("passed", 8, 1, 0)
    assert split["dissenters"] == [
        {"member_name": "Hunter Williams", "council_member_id": seeded["nay_member_id"], "position": "nay"}
    ]
    assert payload["last_split"] == split


@pytest.mark.parametrize("seeded", [{"votes": "many_splits"}], indirect=True)
def test_split_names_single_linked_item_and_counts_many(seeded):
    payload = briefing.recompute_city_facts(seeded["municipality_id"])["split_votes"]
    by_vote = {s["vote_id"]: s for s in payload["splits"]}
    assert set(by_vote) == {seeded["votes"]["split"], seeded["votes"]["failed"], seeded["votes"]["two_items"]}
    one = by_vote[seeded["votes"]["split"]]
    assert one["linked_item_count"] == 1
    assert one["item"] == {"id": seeded["items"]["A"],
                           "label": "$10.1 million contract for citywide road resurfacing"}
    many = by_vote[seeded["votes"]["two_items"]]
    assert many["linked_item_count"] == 2
    assert many["item"] is None
    assert len(many["dissenters"]) == 2
    failed = by_vote[seeded["votes"]["failed"]]
    assert (failed["result"], failed["yeas"], failed["nays"]) == ("failed", 4, 5)
    # Newest first; all three share a date, so the newest vote id leads.
    assert [s["vote_id"] for s in payload["splits"]] == sorted(by_vote, reverse=True)


def test_member_counts_window_and_against_definition(seeded):
    # A meeting 400 days ago, outside the twelve-month window, with Hunter Williams voting no.
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type)
               VALUES (%s, %s, %s, %s, 'council') RETURNING id""",
            (seeded["municipality_id"], briefing_seed.PREFIX + "ancient",
             briefing_seed.PREFIX + "City Council Meeting (ancient)", date.today() - timedelta(days=400)),
        )
        ancient = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO votes (meeting_id, result, yeas, nays, abstentions, source)
               VALUES (%s, 'passed', 8, 1, 0, 'minutes_text') RETURNING id""",
            (ancient,),
        )
        vid = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO member_votes (vote_id, council_member_id, member_name, position)
               VALUES (%s, %s, 'Hunter Williams', 'nay')""",
            (vid, seeded["nay_member_id"]),
        )
    payload = briefing.recompute_city_facts(seeded["municipality_id"])["member_counts"]
    assert payload["window_days"] == 365
    assert payload["since"] == (date.today() - timedelta(days=365)).isoformat()
    members = payload["members"]
    assert len(members) == 9
    hunter = members[str(seeded["nay_member_id"])]
    assert hunter == {"roll_calls": 2, "attended": 2, "against": 1}
    absent = members[str(seeded["members"][briefing_seed.MEMBER_ABSENT])]
    assert absent == {"roll_calls": 2, "attended": 1, "against": 0}
    others = [m for k, m in members.items()
              if k not in (str(seeded["nay_member_id"]), str(seeded["members"][briefing_seed.MEMBER_ABSENT]))]
    assert others == [{"roll_calls": 2, "attended": 2, "against": 0}] * 7


@pytest.mark.parametrize("seeded", [{"votes": "unanimous", "old_split": True}], indirect=True)
def test_unanimity_fallback_carries_last_split(seeded):
    payload = briefing.recompute_city_facts(seeded["municipality_id"])["split_votes"]
    assert payload["splits"] == []
    assert payload["votes_in_window"] == 1
    last = payload["last_split"]
    assert last is not None
    assert last["vote_id"] == seeded["votes"]["old_split"]
    assert last["meeting_date"] == seeded["old_meeting_date"].isoformat()
    assert last["item"] == {"id": seeded["items"]["E"], "label": "$2 million fire truck purchase"}
    assert (last["yeas"], last["nays"]) == (7, 2)


@pytest.mark.parametrize("seeded", [{"votes": "none"}], indirect=True)
def test_no_votes_gives_empty_payload(seeded):
    payload = briefing.recompute_city_facts(seeded["municipality_id"])
    assert payload["split_votes"]["splits"] == []
    assert payload["split_votes"]["last_split"] is None
    assert payload["split_votes"]["votes_in_window"] == 0
    assert payload["member_counts"]["members"] == {}


def test_recompute_all_flagged_counts_birmingham_only(seeded):
    assert briefing.recompute_all_flagged() == 1
    rows = _facts_rows()
    assert len(rows) == 2


def test_get_city_facts_one_query(seeded, monkeypatch):
    briefing.recompute_city_facts(seeded["municipality_id"])
    executed: list[str] = []
    monkeypatch.setattr(briefing, "db_cursor", lambda: _counting(executed))
    facts = briefing.get_city_facts(seeded["municipality_id"])
    assert len(executed) == 1
    assert set(facts) == {"split_votes", "member_counts"}
    assert facts["split_votes"]["payload"]["votes_in_window"] == 2
    assert isinstance(facts["member_counts"]["payload"]["members"], dict)
    assert facts["split_votes"]["computed_at"] == facts["member_counts"]["computed_at"]
    assert briefing.get_city_facts(-1) == {}


def test_facts_freshness_warns_after_48h():
    now = datetime.now(timezone.utc)
    fresh = {"split_votes": {"payload": {}, "computed_at": now},
             "member_counts": {"payload": {}, "computed_at": now}}
    assert briefing.facts_freshness(fresh)["state"] == "good"
    assert briefing.facts_freshness(fresh)["computed_at"] == now
    stale = {"split_votes": {"payload": {}, "computed_at": now - timedelta(hours=49)},
             "member_counts": {"payload": {}, "computed_at": now}}
    assert briefing.facts_freshness(stale)["state"] == "warn"
    assert briefing.facts_freshness(stale)["computed_at"] == now - timedelta(hours=49)
    assert briefing.facts_freshness({})["state"] == "unknown"
    assert briefing.facts_freshness(None)["computed_at"] is None


# --- pure helpers ----------------------------------------------------------


def test_passes_dollar_check_examples():
    a, b = briefing_seed.ITEMS["A"], briefing_seed.ITEMS["B"]
    assert briefing.passes_dollar_check(a["title"], a["description"], a["headline"], a["dollars_amount"])
    assert not briefing.passes_dollar_check(b["title"], b["description"], b["headline"], b["dollars_amount"])
    # Headline within rounding of the stored amount: p = 100,000 for $10.1 million.
    assert briefing.passes_dollar_check("t", "no figure here", "$10.1 million contract", 10_125_000)
    # $10 million: p = 10,000,000, but the cap is h / 10 = 1,000,000.
    assert briefing.passes_dollar_check("t", "", "$10 million for roads", 9_600_000)
    assert not briefing.passes_dollar_check("t", "", "$10 million for roads", 14_000_000)
    # One amount in the text that differs from the stored amount fails.
    assert not briefing.passes_dollar_check("t", "Contract for $850,000.", None, 900_000)
    assert briefing.passes_dollar_check("t", "Contract for $850,000.", None, 850_000)
    assert not briefing.passes_dollar_check("t", "Contract for $850,000.", "", None)
    # A Decimal stored amount, as psycopg2 returns NUMERIC.
    from decimal import Decimal
    assert briefing.passes_dollar_check("t", "Contract for $850,000.", None, Decimal("850000.00"))


def test_clip_words():
    assert briefing.clip_words("one two three four", 4) == "one two three four"
    assert briefing.clip_words("one two three four five", 4) == "one two three four…"
    assert briefing.clip_words("  one   two ", 10) == "one two"
    assert briefing.clip_words("one two", 0) == "one…"
    assert briefing.clip_words(None, 3) == ""


def test_is_briefing_city():
    assert briefing.is_briefing_city({"metadata": {"briefing": True}})
    assert not briefing.is_briefing_city({"metadata": {"briefing": False}})
    assert not briefing.is_briefing_city({"metadata": {}})
    assert not briefing.is_briefing_city({"metadata": None})
    assert not briefing.is_briefing_city({})
    assert not briefing.is_briefing_city(None)
    assert briefing.is_briefing_city({"metadata": '{"briefing": true}'})


def test_birmingham_is_flagged_by_migration_037():
    with db_cursor() as cur:
        cur.execute("SELECT * FROM municipalities WHERE slug = 'birmingham'")
        bhm = dict(cur.fetchone())
        cur.execute("SELECT * FROM municipalities WHERE slug = 'mobile'")
        mobile = dict(cur.fetchone())
    assert briefing.is_briefing_city(bhm)
    assert not briefing.is_briefing_city(mobile)


# --- the source rule -------------------------------------------------------


def _chosen(scope: str, params) -> dict[int, str]:
    sql = "WITH " + briefing.chosen_source_cte(scope) + " SELECT meeting_id, chosen_source FROM meeting_vote_source"
    with db_cursor() as cur:
        cur.execute(sql, params)
        return {r["meeting_id"]: r["chosen_source"] for r in cur.fetchall()}


def test_chosen_source_cte_scopes_and_prefers_minutes(seeded):
    past, ghost, upcoming = seeded["past_meeting_id"], seeded["ghost_meeting_id"], seeded["upcoming_meeting_id"]
    with db_cursor() as cur:
        for meeting, source in ((ghost, "manual"), (ghost, "video_ocr"), (upcoming, "video_ocr"),
                                (past, "video_ocr")):
            cur.execute(
                "INSERT INTO votes (meeting_id, result, yeas, nays, abstentions, source) "
                "VALUES (%s, 'passed', 9, 0, 0, %s)",
                (meeting, source),
            )
    # Scoped to one meeting: the manual vote elsewhere does not change this meeting's source.
    assert _chosen("v.meeting_id = %s", (past,)) == {past: "minutes_text"}
    # Minutes beat manual and video; manual beats video; video alone is video.
    assert _chosen("v.meeting_id = %s", (ghost,)) == {ghost: "manual"}
    assert _chosen("v.meeting_id = %s", (upcoming,)) == {upcoming: "video_ocr"}
    # A wider scope names each meeting once, and only meetings the scope covers.
    assert _chosen("v.meeting_id IN (%s, %s)", (past, ghost)) == {past: "minutes_text", ghost: "manual"}
    # A meeting whose only vote needs review has no chosen source at all.
    with db_cursor() as cur:
        cur.execute("DELETE FROM votes WHERE meeting_id = %s AND needs_review = FALSE", (upcoming,))
        cur.execute(
            "INSERT INTO votes (meeting_id, result, yeas, nays, abstentions, source, needs_review) "
            "VALUES (%s, 'passed', 9, 0, 0, 'minutes_text', TRUE)",
            (upcoming,),
        )
    assert _chosen("v.meeting_id = %s", (upcoming,)) == {}


# --- M7: against the outcome, and the opener's three pure cases --------------


def _add_tabled_and_abstention_votes(seeded) -> str:
    """Two more minutes votes on the past meeting: a 9 to 0 motion the council
    tabled (every member yea) and an 8 to 0 that passed with one abstention.

    Returns the abstainer's name: the first roster member who is neither the
    seed's dissenter nor its absentee, so their other votes are aligned yeas.
    """
    roster = seeded["members"]
    names = list(roster)
    # Not the seed's dissenter or absentee, and not one of the three members
    # (names[2:5]) who vote no on its review-flagged video vote, which the
    # undated Dissent view still counts: the abstainer's other votes must all
    # be aligned yeas.
    abstainer = next(n for i, n in enumerate(names)
                     if n not in (briefing_seed.MEMBER_NAY, briefing_seed.MEMBER_ABSENT) and not 2 <= i < 5)
    with db() as conn:
        with briefing_seed._cur(conn) as cur:
            briefing_seed._insert_vote(cur, seeded["past_meeting_id"], result="tabled", yeas=9, nays=0,
                                       roster=roster)
            briefing_seed._insert_vote(cur, seeded["past_meeting_id"], result="passed", yeas=8, nays=0,
                                       abstentions=1, roster=roster, positions={abstainer: "abstain"})
        conn.commit()
    return abstainer


def test_member_counts_against_excludes_abstentions_and_tabled(seeded):
    abstainer = _add_tabled_and_abstention_votes(seeded)
    members = briefing.recompute_city_facts(seeded["municipality_id"])["member_counts"]["members"]
    roster = seeded["members"]
    nay, absent = str(roster[briefing_seed.MEMBER_NAY]), str(roster[briefing_seed.MEMBER_ABSENT])
    # Four chosen-source roll calls now: the split, the unanimous, the tabled, the abstention.
    assert members[nay] == {"roll_calls": 4, "attended": 4, "against": 1}
    # An abstention is a roll call attended, not a vote against anything.
    assert members[str(roster[abstainer])] == {"roll_calls": 4, "attended": 4, "against": 0}
    # A yea on a tabled motion is not against an outcome the motion never had.
    assert members[absent] == {"roll_calls": 4, "attended": 3, "against": 0}
    assert all(m["against"] == 0 for k, m in members.items() if k != nay)


# The reviewer's crafted facts (plan Surprises, revision after the review):
# 38 items, a 14-word headline, a split on an item whose label holds an
# abbreviation, and a 40-item next meeting. No database.
MUNI = {"id": 1, "slug": "birmingham", "name": "Birmingham"}
SPLIT_LABEL = ("Agreement with St. Vincent's Hospital for emergency medical services "
               "at the downtown clinic")
BIGGEST_HEADLINE = ("$4.2 million contract for curb ramps, crosswalk markings, "
                    "and neighborhood sidewalk reconstruction")


def _crafted_facts(dissenters: list[dict], next_items: int = 40) -> dict:
    split = {
        "vote_id": 9, "meeting_id": 1, "meeting_date": date(2026, 10, 14),
        "source": "minutes_text", "result": "passed", "yeas": 8, "nays": 1, "abstentions": 0,
        "item": {"id": 5, "label": SPLIT_LABEL}, "linked_item_count": 1,
        "dissenters": dissenters,
    }
    return {
        "last": {
            "meeting_id": 1, "meeting_date": date(2026, 10, 14), "item_count": 38, "stale": False,
            "biggest": {"item_id": 3, "amount": 4_200_000, "headline": BIGGEST_HEADLINE},
            "splits": {"count": 1, "first": split}, "vote_count": 6, "source_label": "",
        },
        "next": {"meeting_id": 2, "meeting_date": date(2026, 10, 21), "item_count": next_items},
    }


def _beat_text(beat: list[dict]) -> str:
    return "".join(s["text"] for s in beat if s["kind"] != "action")


def test_opener_one_unresolved_dissenter_is_singular():
    facts = _crafted_facts([{"member_name": "J. Doe", "council_member_id": None, "position": "nay"}])
    beats = briefing.opener_beats(facts, MUNI)
    text = _beat_text(beats[0])
    assert "passed 8 to 1, with one member voting no." in text
    assert "members" not in text
    phrase = [s for s in beats[0] if s["text"].startswith("with one member")]
    assert len(phrase) == 1
    assert phrase[0]["href"] == "/al/birmingham/meetings/1/#vote-9"


def test_opener_tally_only_split_drops_dissenter_phrase():
    facts = _crafted_facts([])
    beats = briefing.opener_beats(facts, MUNI)
    text = _beat_text(beats[0])
    assert "passed 8 to 1." in text
    assert "with " not in text[text.index("8 to 1"):]
    action = [s for s in beats[0] if s["kind"] == "action"]
    assert len(action) == 1
    assert action[0]["href"].endswith("#vote-9")


def test_opener_text_cuts_at_sentence_boundary_not_inside_label():
    facts = _crafted_facts([
        {"member_name": "J. Doe", "council_member_id": None, "position": "nay"},
        {"member_name": "R. Roe", "council_member_id": None, "position": "nay"},
    ])
    joined = " ".join(_beat_text(b).strip() for b in briefing.opener_beats(facts, MUNI))
    assert len(joined) > briefing.OPENER_TEXT_MAX, "the case must need a cut"
    text = briefing.opener_text(facts, MUNI)
    assert len(text) <= briefing.OPENER_TEXT_MAX
    assert text.endswith("sidewalk reconstruction.")
    assert "St." not in text


# --- M9: the stored verb, the year on a short date, the empty window -------


def test_split_sentence_and_door_line_print_the_stored_result():
    facts = _crafted_facts([{"member_name": "J. Doe", "council_member_id": 4, "position": "nay"}])
    split = facts["last"]["splits"]["first"]
    split["result"] = "tabled"
    text = _beat_text(briefing.opener_beats(facts, MUNI)[0])
    assert "tabled 8 to 1, with " in text
    assert "failed" not in text
    assert briefing._disagreement_line(split, "birmingham")["verb"] == "tabled"
    split["result"] = "failed"
    assert briefing._disagreement_line(split, "birmingham")["verb"] == "failed"


def test_short_date_carries_the_year_when_not_this_year():
    assert briefing._short_date(date(2024, 3, 3), today=date(2026, 10, 19)) == "March 3, 2024"
    assert briefing._short_date(date(2026, 3, 3), today=date(2026, 10, 19)) == "March 3"
    assert briefing._long_date(date(2024, 3, 3), today=date(2026, 10, 19)) == "Sunday, March 3, 2024"


def test_disagreement_is_none_with_no_vote_in_window():
    last_split = {
        "vote_id": 1, "meeting_id": 1, "meeting_date": "2024-03-03", "source": "minutes_text",
        "result": "tabled", "yeas": 7, "nays": 2, "abstentions": 0,
        "item": {"id": 5, "label": SPLIT_LABEL}, "linked_item_count": 1, "dissenters": [],
    }
    payload = {"splits": [], "votes_in_window": 0, "since": "2026-04-22", "last_split": last_split}
    assert briefing.disagreement({"split_votes": {"payload": payload}}, MUNI) is None
    payload["votes_in_window"] = 3
    shaped = briefing.disagreement({"split_votes": {"payload": payload}}, MUNI)
    assert shaped is not None
    assert shaped["mode"] == "unanimous"
    assert shaped["last_split"]["date_text"] == "March 3, 2024"
