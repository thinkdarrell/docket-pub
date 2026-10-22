"""Seeded Birmingham rows for the city briefing tests.

The throwaway database that ``tools/test-db`` builds holds Birmingham, its
districts, and its nine council members (migrations 002 and 005) and, from
migration 037, Birmingham's ``briefing`` flag, but no meetings. ``seed``
inserts, under Birmingham's id and with every title prefixed
``BRIEFING_TEST_``, the rows the page's full state needs:

* a past council meeting seven days ago (start 09:30, agenda, minutes, and
  video links) with items A to D: A is the $10.1 million resurfacing
  contract whose text holds that one amount; B is the KultureCity item whose
  headline says $7 million while the stored amount is $39.5 million (so it
  fails the dollar check); C is a consent item with no amount; D is routine;
* minutes votes on that meeting: vote 1 on item A passed 8 to 1 with nine
  member votes (Hunter Williams nay), vote 2 unanimous 9 to 0 linked to C
  and D with nine member votes (Clinton P. Woods absent), and vote 3 a
  ``video_ocr`` vote with ``needs_review`` set and three nays, which every
  count must ignore;
* an upcoming council meeting five days ahead with two items;
* a ghost meeting three days ago with no items and no documents;
* a public transcript on the past meeting with three segments tagged to
  item A, the first from a speaker cluster resolved to Hunter Williams;
* badges ``hidden_on_consent`` on item C and ``blight_accountability`` on A.

Options produce the partial states the plan's tests name: ``past_days``
ages the past meeting (default seven days); ``votes="tally_only"`` records
vote 1 with no member votes and ``votes="video"`` records votes 1 and 2
from the video (``video_ocr``, not flagged for review) so the video becomes
the meeting's chosen source; ``transcript="low_speech"`` writes the
transcript with that status, which ``transcripts.public_predicate`` hides;
``undocumented=True`` adds a council meeting ten days back with one item and
no agenda, minutes, video, or source link; ``cancelled=True`` adds a council
meeting two days back whose title says it was cancelled (the only mark
Birmingham's cancelled rows carry), with agenda and video links and one
posted consent item of $12 million, and ``cancelled="upcoming"`` the same
meeting two days ahead; ``work_session=True`` adds a council work session
(``session_kind`` ``work_session``) two days back with one item, which the
opener's "last meeting" must pass over. ``cleanup``
removes everything by the prefix, plus Birmingham's ``city_briefing_facts``
rows; ``seed`` calls it first, so a run killed midway is tidied by the next.
"""

from __future__ import annotations

from datetime import date, time, timedelta

import psycopg2.extras

PREFIX = "BRIEFING_TEST_"
MEMBER_NAY = "Hunter Williams"
MEMBER_ABSENT = "Clinton P. Woods"

ITEMS = {
    "A": {
        "item_number": "1",
        "title": PREFIX + "Citywide road resurfacing contract",
        "description": "Agreement with a paving contractor for citywide road resurfacing "
                       "in the amount of $10,100,000, funded from the capital budget.",
        "headline": "$10.1 million contract for citywide road resurfacing",
        "dollars_amount": 10_100_000,
        "is_consent": False,
        "topic": "public_works",
        "significance_score": 5,   # above the policy badges' default gate of 3
    },
    "B": {
        "item_number": "2",
        "title": PREFIX + "KultureCity campus funding agreement",
        "description": "Funding agreement for the $39.5 million KultureCity campus; the city "
                       "contributes $7 million over three fiscal years.",
        "headline": "$7 million city contribution to the KultureCity campus",
        "dollars_amount": 39_500_000,
        "is_consent": False,
        "topic": "contracts",
    },
    "C": {
        "item_number": "3",
        "title": PREFIX + "Housing rehabilitation grant acceptance",
        "description": "Acceptance of a federal grant for owner-occupied housing rehabilitation.",
        "headline": "Grant accepted for housing rehabilitation",
        "dollars_amount": None,
        "is_consent": True,
        "topic": "grants",
    },
    "D": {
        "item_number": "4",
        "title": PREFIX + "Approval of the minutes of the previous meeting",
        "description": "Approval of minutes.",
        "headline": None,
        "dollars_amount": None,
        "is_consent": False,
        "topic": "routine",
    },
}

UPCOMING_ITEMS = [
    {"item_number": "1", "title": PREFIX + "Resolution setting the tax levy hearing",
     "description": "Sets a public hearing date.", "topic": "budget"},
    {"item_number": "2", "title": PREFIX + "Rezoning of parcel 22-00-13",
     "description": "Rezoning from R-3 to B-2.", "topic": "zoning"},
]

OLD_ITEM = {
    "item_number": "1",
    "title": PREFIX + "Purchase of a fire apparatus",
    "description": "Purchase of one pumper truck for $2,000,000.",
    "headline": "$2 million fire truck purchase",
    "dollars_amount": 2_000_000,
    "is_consent": False,
    "topic": "public_safety",
    "significance_score": 4,
}


UNDOCUMENTED_ITEM = {
    "item_number": "1",
    "title": PREFIX + "Appointment to the library board",
    "description": "Appointment of one member to the library board.",
    "topic": "appointments",
}

WORK_SESSION_ITEM = {
    "item_number": "1",
    "title": PREFIX + "Discussion of the capital budget",
    "description": "Discussion only; no action taken.",
    "topic": "budget",
}

# Above item A's amount so that, unfiltered, it would head the money door
# and the opener.
CANCELLED_ITEM = {
    "item_number": "1",
    "title": PREFIX + "Stormwater pump station contract",
    "description": "Contract for the rebuild of the Valley Creek pump station in the amount "
                   "of $12,000,000.",
    "headline": "$12 million stormwater pump station contract",
    "dollars_amount": 12_000_000,
    "is_consent": True,
    "topic": "public_works",
}


def _cur(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def _birmingham_id(cur) -> int:
    cur.execute("SELECT id FROM municipalities WHERE slug = 'birmingham'")
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("Birmingham is not seeded; run the migrations first")
    return row["id"]


def _roster(cur, municipality_id: int) -> dict[str, int]:
    cur.execute(
        "SELECT id, name FROM council_members WHERE municipality_id = %s AND active = TRUE ORDER BY id",
        (municipality_id,),
    )
    roster = {r["name"]: r["id"] for r in cur.fetchall()}
    if len(roster) != 9 or MEMBER_NAY not in roster or MEMBER_ABSENT not in roster:
        raise RuntimeError(f"expected Birmingham's nine seeded members, found {sorted(roster)}")
    return roster


def _insert_meeting(cur, municipality_id, *, external_id, title, meeting_date, start_time=None,
                    meeting_type="council", session_kind="regular", agenda_url=None, minutes_url=None,
                    video_url=None, source_url=None) -> int:
    cur.execute(
        """INSERT INTO meetings (municipality_id, external_id, title, meeting_date, meeting_type,
                                 session_kind, start_time, agenda_url, minutes_url, video_url, source_url)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (municipality_id, PREFIX + external_id, title, meeting_date, meeting_type, session_kind,
         start_time, agenda_url, minutes_url, video_url, source_url),
    )
    mid = cur.fetchone()["id"]
    cur.execute("INSERT INTO processing_status (meeting_id) VALUES (%s)", (mid,))
    return mid


def _insert_item(cur, meeting_id: int, spec: dict, *, dollars: bool = True) -> int:
    """Insert one item as the pipeline leaves a finished one: ``processing_status``
    ``completed`` (the badge counts and the category pages show only those) and
    the spec's ``significance_score`` when it has one (the policy badges' gate)."""
    cur.execute(
        """INSERT INTO agenda_items (meeting_id, external_id, item_number, title, description,
                                     headline, dollars_amount, is_consent, topic,
                                     processing_status, significance_score)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'completed', %s) RETURNING id""",
        (meeting_id, f"{PREFIX}{meeting_id}-{spec['item_number']}", spec["item_number"],
         spec["title"], spec.get("description"), spec.get("headline"),
         spec.get("dollars_amount") if dollars else None, bool(spec.get("is_consent")),
         spec.get("topic"), spec.get("significance_score")),
    )
    return cur.fetchone()["id"]


def _insert_vote(cur, meeting_id: int, *, result, yeas, nays, abstentions=0, source="minutes_text",
                 needs_review=False, item_ids=(), roster=None, positions=None) -> int:
    """Insert a vote, its active links to ``item_ids``, and one member vote per roster member.

    ``positions`` maps member name to position; members not named vote ``yea``.
    """
    cur.execute(
        """INSERT INTO votes (meeting_id, external_id, result, yeas, nays, abstentions, source,
                              needs_review, raw_text)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (meeting_id, None, result, yeas, nays, abstentions, source, needs_review,
         f"{PREFIX} vote {result} {yeas}-{nays}"),
    )
    vid = cur.fetchone()["id"]
    for item_id in item_ids:
        cur.execute(
            """INSERT INTO vote_agenda_items (vote_id, agenda_item_id, association_type,
                                              match_confidence, provisional, is_active)
               VALUES (%s, %s, 'explicit', 1.0, FALSE, TRUE)""",
            (vid, item_id),
        )
    if roster:
        for name, member_id in roster.items():
            cur.execute(
                """INSERT INTO member_votes (vote_id, council_member_id, member_name, position)
                   VALUES (%s, %s, %s, %s)""",
                (vid, member_id, name, (positions or {}).get(name, "yea")),
            )
    return vid


def _insert_badge(cur, item_id: int, city_id: int, slug: str, kind: str, source: str, confidence) -> None:
    cur.execute(
        """INSERT INTO agenda_item_badges (agenda_item_id, city_id, badge_slug, kind, confidence,
                                           source, status)
           VALUES (%s, %s, %s, %s, %s, %s, 'applied')""",
        (item_id, city_id, slug, kind, confidence, source),
    )


def _insert_transcript(cur, meeting_id: int, item_id: int, roster: dict, *, resolved_speaker: bool,
                       status: str = "uploaded") -> int:
    """Insert a transcript with ``status`` (``low_speech`` hides it from the
    page, by ``transcripts.public_predicate``), its two speakers, and three
    segments tagged to ``item_id``; the segments are written whatever the
    status, since the predicate alone decides what the page shows."""
    cur.execute(
        """INSERT INTO transcripts (meeting_id, status, version, engine, asr_model, diarization_model,
                                    audio_duration_s, speech_ratio, word_count, uploaded_at)
           VALUES (%s, %s, 1, 'whisper', 'large-v3', 'pyannote', 5400, 0.8, 9000, now())
           RETURNING id""",
        (meeting_id, status),
    )
    tid = cur.fetchone()["id"]
    cur.execute(
        """INSERT INTO transcript_speakers (meeting_id, cluster_label, council_member_id, display_name,
                                            role, confidence, method)
           VALUES (%s, 'SPEAKER_01', %s, %s, %s, %s, %s) RETURNING id""",
        (meeting_id,
         roster[MEMBER_NAY] if resolved_speaker else None,
         MEMBER_NAY if resolved_speaker else None,
         "council" if resolved_speaker else "unknown",
         0.9 if resolved_speaker else None,
         "roll_call" if resolved_speaker else None),
    )
    resolved_id = cur.fetchone()["id"]
    cur.execute(
        """INSERT INTO transcript_speakers (meeting_id, cluster_label, role)
           VALUES (%s, 'SPEAKER_02', 'unknown') RETURNING id""",
        (meeting_id,),
    )
    other_id = cur.fetchone()["id"]
    segments = [
        (1, 600.0, 612.0, "I want to be clear that I cannot support this contract at this price, "
                           "not with the questions we still have about the bid.", "SPEAKER_01", resolved_id),
        (2, 612.0, 620.0, "The department has answered those questions in writing.", "SPEAKER_02", other_id),
        (3, 620.0, 631.0, "Then let the record show the answers, and let us vote.", "SPEAKER_02", other_id),
    ]
    for seq, start_s, end_s, text, label, speaker_id in segments:
        cur.execute(
            """INSERT INTO transcript_segments (transcript_id, seq, start_s, end_s, text, cluster_label,
                                                speaker_id, agenda_item_id, assignment_method)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'index_point')""",
            (tid, seq, start_s, end_s, text, label, speaker_id, item_id),
        )
    return tid


def cleanup(conn) -> None:
    """Remove every seeded row by the title prefix, and Birmingham's briefing facts."""
    with _cur(conn) as cur:
        cur.execute(
            "DELETE FROM city_briefing_facts WHERE municipality_id = "
            "(SELECT id FROM municipalities WHERE slug = 'birmingham')"
        )
        cur.execute(
            "DELETE FROM transcript_speakers WHERE meeting_id IN "
            "(SELECT id FROM meetings WHERE position(%s IN title) = 1)",
            (PREFIX,),
        )
        cur.execute("DELETE FROM meetings WHERE position(%s IN title) = 1", (PREFIX,))
    conn.commit()


def seed(conn, *, votes: str = "split", transcript: bool | str = True, upcoming: bool = True,
         dollars: bool = True, badges: bool = True, ghost: bool = True, old_split: bool = False,
         resolved_speaker: bool = True, past_days: int = 7, undocumented: bool = False,
         cancelled: bool | str = False, work_session: bool = False) -> dict:
    """Insert the Birmingham rows; returns the ids created.

    ``votes`` is ``"split"`` (the default), ``"unanimous"`` (no split vote on
    the past meeting), ``"none"`` (no votes at all), ``"many_splits"``
    (three split votes: vote 1, a failed 4 to 5 on item B, and a 7 to 2
    linked to C and D), ``"tally_only"`` (vote 1 with no member votes, so
    its dissenters are unknown), or ``"video"`` (votes 1 and 2 from the
    video and not flagged for review, so the video is the chosen source).
    ``transcript`` is ``True``, ``False``, or ``"low_speech"`` (the
    transcript exists with that status and the page hides it).
    ``dollars=False`` stores no amount on any item, so no item passes the
    dollar check. ``old_split=True`` adds a meeting 200 days ago with one
    split vote, outside the 180-day window. ``past_days`` is the past
    meeting's age in days (``out["past_meeting_date"]`` follows it).
    ``undocumented=True`` adds a council meeting ten days back with one item
    and no document links (``out["undocumented_meeting_id"]``).
    ``cancelled=True`` adds a council meeting two days back whose title says
    it was cancelled, with agenda and video links and one posted consent item
    (``CANCELLED_ITEM``, $12 million, above item A), returned as
    ``out["cancelled_meeting_id"]`` and ``out["items"]["cancelled"]``;
    ``cancelled="upcoming"`` adds the same meeting two days ahead, before the
    seed's upcoming meeting. ``work_session=True`` adds a council work
    session two days back with one item (``out["work_session_meeting_id"]``).
    """
    if votes not in ("split", "unanimous", "none", "many_splits", "tally_only", "video"):
        raise ValueError(f"unknown votes option {votes!r}")
    if cancelled not in (False, True, "upcoming"):
        raise ValueError(f"unknown cancelled option {cancelled!r}")
    cleanup(conn)
    today = date.today()
    out: dict = {"items": {}, "votes": {}, "upcoming_items": []}
    with _cur(conn) as cur:
        city = _birmingham_id(cur)
        roster = _roster(cur, city)
        out["municipality_id"] = city
        out["members"] = roster
        out["nay_member_id"] = roster[MEMBER_NAY]

        past = _insert_meeting(
            cur, city, external_id="past", title=PREFIX + "City Council Meeting",
            meeting_date=today - timedelta(days=past_days), start_time=time(9, 30),
            agenda_url="https://example.test/agendas/past.pdf",
            minutes_url="https://example.test/minutes/past.pdf",
            video_url="https://example.test/video/past",
            source_url="https://birminghamal.granicus.com/ViewPublisher.php?view_id=1",
        )
        out["past_meeting_id"] = past
        out["past_meeting_date"] = today - timedelta(days=past_days)
        for key, spec in ITEMS.items():
            out["items"][key] = _insert_item(cur, past, spec, dollars=dollars)
        a, b, c, d = (out["items"][k] for k in "ABCD")

        if votes != "none":
            source = "video_ocr" if votes == "video" else "minutes_text"
            if votes in ("split", "many_splits", "tally_only", "video"):
                out["votes"]["split"] = _insert_vote(
                    cur, past, result="passed", yeas=8, nays=1, item_ids=[a], source=source,
                    roster=None if votes == "tally_only" else roster,
                    positions={MEMBER_NAY: "nay"},
                )
            out["votes"]["unanimous"] = _insert_vote(
                cur, past, result="passed", yeas=9, nays=0, item_ids=[c, d], source=source,
                roster=roster, positions={MEMBER_ABSENT: "absent"},
            )
            names = list(roster)
            out["votes"]["review"] = _insert_vote(
                cur, past, result="passed", yeas=6, nays=3, source="video_ocr", needs_review=True,
                item_ids=[b], roster=roster, positions={n: "nay" for n in names[2:5]},
            )
            if votes == "many_splits":
                out["votes"]["failed"] = _insert_vote(
                    cur, past, result="failed", yeas=4, nays=5, item_ids=[b], roster=roster,
                    positions={n: "nay" for n in names[:5]},
                )
                out["votes"]["two_items"] = _insert_vote(
                    cur, past, result="passed", yeas=7, nays=2, item_ids=[c, d], roster=roster,
                    positions={n: "nay" for n in names[7:9]},
                )

        if upcoming:
            up = _insert_meeting(
                cur, city, external_id="upcoming", title=PREFIX + "City Council Meeting",
                meeting_date=today + timedelta(days=5), start_time=time(9, 30),
                agenda_url="https://example.test/agendas/upcoming.pdf",
            )
            out["upcoming_meeting_id"] = up
            out["upcoming_meeting_date"] = today + timedelta(days=5)
            for spec in UPCOMING_ITEMS:
                out["upcoming_items"].append(_insert_item(cur, up, spec))

        if cancelled:
            next_regular = (today + timedelta(days=5)).strftime("%m/%d/%Y")
            offset = timedelta(days=2) if cancelled == "upcoming" else timedelta(days=-2)
            can = _insert_meeting(
                cur, city, external_id="cancelled",
                title=PREFIX + "Regular City Council Meeting - Cancelled "
                      f"(Next Regular Meeting {next_regular})",
                meeting_date=today + offset, start_time=time(9, 30),
                agenda_url="https://example.test/agendas/cancelled.pdf",
                video_url="https://example.test/video/cancelled",
            )
            out["cancelled_meeting_id"] = can
            out["cancelled_meeting_date"] = today + offset
            out["items"]["cancelled"] = _insert_item(cur, can, CANCELLED_ITEM)

        if work_session:
            ws = _insert_meeting(
                cur, city, external_id="work_session",
                title=PREFIX + "City Council Regular Work Session",
                meeting_date=today - timedelta(days=2), start_time=time(14, 0),
                session_kind="work_session",
                agenda_url="https://example.test/agendas/work_session.pdf",
            )
            out["work_session_meeting_id"] = ws
            out["items"]["work_session"] = _insert_item(cur, ws, WORK_SESSION_ITEM)

        if ghost:
            out["ghost_meeting_id"] = _insert_meeting(
                cur, city, external_id="ghost", title=PREFIX + "Regular City Council Meeting",
                meeting_date=today - timedelta(days=3),
            )

        if undocumented:
            und = _insert_meeting(
                cur, city, external_id="undocumented",
                title=PREFIX + "City Council Meeting (no documents)",
                meeting_date=today - timedelta(days=10), start_time=time(9, 30),
            )
            out["undocumented_meeting_id"] = und
            out["items"]["undocumented"] = _insert_item(cur, und, UNDOCUMENTED_ITEM)

        if old_split:
            old = _insert_meeting(
                cur, city, external_id="old", title=PREFIX + "City Council Meeting (older)",
                meeting_date=today - timedelta(days=200), start_time=time(9, 30),
                minutes_url="https://example.test/minutes/old.pdf",
            )
            out["old_meeting_id"] = old
            out["old_meeting_date"] = today - timedelta(days=200)
            out["items"]["E"] = _insert_item(cur, old, OLD_ITEM, dollars=dollars)
            names = list(roster)
            out["votes"]["old_split"] = _insert_vote(
                cur, old, result="passed", yeas=7, nays=2, item_ids=[out["items"]["E"]], roster=roster,
                positions={n: "nay" for n in names[2:4]},
            )

        if transcript:
            out["transcript_id"] = _insert_transcript(
                cur, past, a, roster, resolved_speaker=resolved_speaker,
                status="low_speech" if transcript == "low_speech" else "uploaded",
            )

        if badges:
            _insert_badge(cur, c, city, "hidden_on_consent", "process", "deterministic", 1.0)
            _insert_badge(cur, a, city, "blight_accountability", "policy", "llm", 0.9)
    conn.commit()
    return out


def clear_caches() -> None:
    """Clear the per-process caches a test must not inherit from an earlier render."""
    from docket.web import public

    public._overview_cache.clear()
    from docket.services import briefing

    cache = getattr(briefing, "_provenance_cache", None)
    if cache is not None:
        cache.clear()
