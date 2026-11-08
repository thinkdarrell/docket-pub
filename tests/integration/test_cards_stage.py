"""The search-card stage: the claim, the build, the run row, the `ai_runs` row, the tick, and the command.

Plan: plans/completed/search-finds-what-was-said.md (M4). No model is called:
`FakeClient` stands where `StructuredClient` does, reads the rendered meeting
it is handed, and replies with one card per item marker, as the prompt asks.

Names M4 adds are read off their modules inside the tests, and the command
is loaded by path inside a helper, so this file collects before they exist.
"""
import importlib
import importlib.util
import re
from functools import lru_cache
from pathlib import Path

import pytest

from docket.ai.exceptions import (
    AIFatalError,
    AIPermanentRowError,
    AIRateLimited,
    AITransientError,
    TranscriptHeld,
)
from docket.ai.pricing import Usage, calculate_cost_usd, track_usage
from docket.ai.transcripts import cards as C
from docket.ai.transcripts import pipeline as P
from docket.ai.transcripts.client import StructuredResult
from docket.config import AI_DAILY_BUDGET_USD, DATABASE_URL
from docket.db import db, db_cursor
from docket.migrations import runner
from tests.support.transcript_fixtures import Bundle, install_bundle, load_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)

ROOT = Path(__file__).resolve().parents[2]
NOTES = "pytest_cards"
EXTERNAL_IDS = ["999951", "999952", "999953", "yt-pytest-cards"]
USAGE = Usage(1200, 0, 0, 300)
MARKER = re.compile(r"^=== ITEM MARKER item_id=(\d+) ")
LINE = re.compile(r"^\[seq=(\d+) t=\d\d:\d\d:\d\d [^\]]*\] (.*)$")
COUNT_LINE = re.compile(r"^cards: (\d+) Birmingham meetings with a public transcript; (\d+) past the events stage; "
                        r"(\d+) with current cards; (\d+) waiting; (\d+) held; (\d+) failed$")


@lru_cache(maxsize=1)
def _script():
    spec = importlib.util.spec_from_file_location("build_search_cards", ROOT / "scripts" / "build_search_cards.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reply_for(user: str) -> dict:
    """One card per item marker of a rendered meeting: the lines up to the next marker are the item's range."""
    blocks: list[dict] = []
    for line in user.splitlines():
        marker, spoken = MARKER.match(line), LINE.match(line)
        if marker:
            blocks.append({"item_id": int(marker.group(1)), "lines": []})
        elif spoken and blocks:
            blocks[-1]["lines"].append((int(spoken.group(1)), spoken.group(2)))
    cards = []
    for b in blocks:
        lines = b["lines"]
        cards.append({
            "item_id": b["item_id"], "discussed": bool(lines),
            "start_seq": lines[0][0] if lines else None, "end_seq": lines[-1][0] if lines else None,
            "aliases": ["zebra crossing rules"],
            "spoken_details": ([{"text": "What the first speaker said.", "seq": lines[0][0],
                                 "quote": " ".join(lines[0][1].split()[:6])}] if lines else []),
            "identifiers": [], "names": [],
            "outcome": {"result": "passed", "seq": None},
            "refers_to": {"text": "", "seq": None},
        })
    return {"cards": cards}


class FakeClient:
    """Stands where `StructuredClient` does. `reply` turns the default reply into the one a test wants."""

    def __init__(self, *, reply=None, raises=None, tokens=900, on_call=None):
        self.reply, self.raises, self.tokens, self.on_call = reply, raises, tokens, on_call
        self.counted: list[dict] = []
        self.calls: list[dict] = []

    def count_tokens(self, *, model, system, user):
        self.counted.append({"model": model, "system": system, "user": user})
        return self.tokens

    def call(self, *, model, system, user, schema, max_tokens=16000, effort="medium"):
        self.calls.append({"model": model, "system": system, "user": user, "schema": schema,
                           "max_tokens": max_tokens, "effort": effort})
        if self.raises is not None:
            raise self.raises
        if self.on_call is not None:
            self.on_call()
        track_usage(model, USAGE)   # the real client reports every reply's usage this way
        data = _reply_for(user)
        if self.reply is not None:
            data = self.reply(data)
        return StructuredResult(data=data, usage=USAGE, model=model, stop_reason="end_turn")


def _small_bundle(meeting_date: str) -> Bundle:
    """Three items, two of them with an index point; segments 2 to 4 fall under the first and 5 to 7 under the second."""
    seg = lambda seq, start, end, text, label, silence=False: {
        "seq": seq, "start_s": start, "end_s": end, "text": text, "cluster_label": label, "is_silence": silence,
        "avg_logprob": None, "no_speech_prob": None}
    speaker = lambda label, name, confidence: {
        "cluster_label": label, "council_member_id": None, "display_name": name, "role": None,
        "confidence": confidence, "method": None, "is_manual": False}
    return Bundle(
        meeting={"title": "Cards stage test", "meeting_date": meeting_date, "meeting_type": "council",
                 "video_url": "https://x/v", "minutes_url": None,
                 "transcript": {"version": 1, "engine": "test", "asr_model": "test", "diarization_model": None,
                                "audio_duration_s": 240.0, "speech_ratio": 0.9, "word_count": 5000}},
        agenda_items=[
            {"id": 1, "external_id": None, "item_number": "1", "is_consent": False, "video_timestamp_seconds": 100.0,
             "title": "Resolution approving a street paving contract"},
            {"id": 2, "external_id": None, "item_number": "2", "is_consent": False, "video_timestamp_seconds": 200.0,
             "title": "Ordinance amending Title 12 of the General Code"},
            {"id": 3, "external_id": None, "item_number": "3", "is_consent": False, "video_timestamp_seconds": None,
             "title": "Resolution setting a public hearing"},
        ],
        roster=[],
        speakers=[speaker("S0", "Council President", 0.9), speaker("S1", "Someone", 0.3)],
        segments=[
            seg(0, 0.0, 18.0, "", None, True),
            seg(1, 20.0, 30.0, "Good morning everyone and welcome to the meeting.", "S0"),
            seg(2, 100.0, 110.0, "Item one is the street paving contract with Dunn Construction.", "S0"),
            seg(3, 110.0, 125.0, "The contract is for four million dollars over two years.", "S1"),
            seg(4, 125.0, 140.0, "All in favor say aye. The item passes.", "S0"),
            seg(5, 200.0, 212.0, "Item two is the late night establishment ordinance.", "S0"),
            seg(6, 212.0, 230.0, "Clubs must keep security camera footage for thirty days.", "S1"),
            seg(7, 230.0, 240.0, "Motion carries on item two.", "S0"),
        ],
    )


@pytest.fixture(scope="module", autouse=True)
def ensure_041_function():
    """Install 041's trigger function, which an earlier integration file can leave at an older body (see M2's files)."""
    m041 = importlib.import_module("docket.migrations.041_search_cards")
    with db() as conn:
        runner.apply_migrations(conn)
        with conn.cursor() as cur:
            cur.execute(m041.SQL_UP)


def _wipe():
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE external_id = ANY(%s)", [EXTERNAL_IDS])
        cur.execute("DELETE FROM ai_runs WHERE notes LIKE %s", [NOTES + "%"])


@pytest.fixture
def spend(monkeypatch):
    """The day's AI spend as the stage reads it: zero unless a test says otherwise."""
    import docket.ai.worker as W
    state = {"usd": 0.0}
    monkeypatch.setattr(W, "_today_spend", lambda conn: state["usd"])
    return state


@pytest.fixture
def make(spend):
    """Install a meeting with a transcript; by default at `events_extracted` with its segments filed by index point."""
    _wipe()

    def _make(*, status="events_extracted", external_id="999951", meeting_date="2099-03-01", place=True, hidden=False,
              bundle=None):
        inst = install_bundle(bundle or _small_bundle(meeting_date), status=status, external_id=external_id)
        if place:
            P.assign_index_points(inst.transcript_id, inst.meeting_id)
        if hidden:
            with db_cursor() as cur:
                cur.execute("UPDATE meetings SET is_hidden = TRUE WHERE id = %s", [inst.meeting_id])
        return inst

    yield _make
    _wipe()


def _run(client, **kw):
    kw.setdefault("limit", 5)
    kw.setdefault("notes", NOTES)
    return C.run_cards(client=client, **kw)


def _run_row(inst) -> dict | None:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM transcript_card_runs WHERE transcript_id = %s", [inst.transcript_id])
        row = cur.fetchone()
        return dict(row) if row else None


def _card_rows(inst) -> list[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM agenda_item_search_cards WHERE transcript_id = %s ORDER BY agenda_item_id",
                    [inst.transcript_id])
        return [dict(r) for r in cur.fetchall()]


def _ai_runs(notes: str = NOTES) -> list[dict]:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM ai_runs WHERE notes = %s ORDER BY id", [notes])
        return [dict(r) for r in cur.fetchall()]


def _uploaded_at(inst):
    with db_cursor() as cur:
        cur.execute("SELECT uploaded_at FROM transcripts WHERE id = %s", [inst.transcript_id])
        return cur.fetchone()["uploaded_at"]


def _age_last_attempt(inst, hours: int = 25) -> None:
    with db_cursor() as cur:
        cur.execute("UPDATE transcript_card_runs SET last_attempted_at = now() - %s * interval '1 hour' "
                    "WHERE transcript_id = %s", [hours, inst.transcript_id])


def _matches(item_id: int, word: str) -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT search_vector @@ plainto_tsquery('english', %s) AS hit FROM agenda_items WHERE id = %s",
                    [word, item_id])
        return cur.fetchone()["hit"]


# --- the build ---------------------------------------------------------------------------------------------------


def test_a_transcript_past_the_events_stage_is_claimed_and_its_cards_are_written(make):
    inst = make()
    fake = FakeClient()
    summary = _run(fake)
    assert (summary.built, summary.failed, summary.held, summary.stopped_reason) == (1, 0, 0, None)
    cards = _card_rows(inst)
    assert [c["agenda_item_id"] for c in cards] == sorted([inst.item_ids[1], inst.item_ids[2]])
    by_item = {c["agenda_item_id"]: c for c in cards}
    first = by_item[inst.item_ids[1]]
    assert (first["start_seq"], first["end_seq"], first["discussed"]) == (2, 4, True)
    assert first["source_uploaded_at"] == _uploaded_at(inst)
    assert first["prompt_version"] == 200 and first["model"] == C.AI_TRANSCRIPT_CARDS_MODEL
    assert first["card"]["spoken_details"] == [{"text": "What the first speaker said.", "seq": 2,
                                                "quote": "Item one is the street paving"}]
    assert (by_item[inst.item_ids[2]]["start_seq"], by_item[inst.item_ids[2]]["end_seq"]) == (5, 7)
    run = _run_row(inst)
    assert (run["status"], run["attempts"], run["last_error"]) == ("done", 1, None)
    assert run["meeting_id"] == inst.meeting_id and run["model"] == C.AI_TRANSCRIPT_CARDS_MODEL
    assert run["source_uploaded_at"] == _uploaded_at(inst) and run["prompt_version"] == 200
    assert run["counts"]["placed"] == 2 and run["counts"]["cards"] == 2 and run["counts"]["missing"] == 0
    assert run["counts"]["written"] == 2


def test_the_cards_reach_the_items_search_vectors(make):
    inst = make()
    _run(FakeClient())
    assert _matches(inst.item_ids[1], "zebra") and _matches(inst.item_ids[2], "zebra")
    assert not _matches(inst.item_ids[3], "zebra")   # not placed, so no marker and no card


def test_the_model_is_called_once_with_the_card_prompt_schema_and_rendered_meeting(make):
    from docket.ai.transcripts.prompts import CARDS_SYSTEM
    from docket.ai.transcripts.schemas import CARDS_SCHEMA
    inst = make()
    fake = FakeClient()
    _run(fake)
    assert len(fake.counted) == 1 and len(fake.calls) == 1
    call = fake.calls[0]
    assert call["model"] == C.AI_TRANSCRIPT_CARDS_MODEL and call["system"] == CARDS_SYSTEM
    assert call["schema"] is CARDS_SCHEMA and (call["max_tokens"], call["effort"]) == (64000, "medium")
    user = call["user"]
    assert user == fake.counted[0]["user"]
    assert user.startswith("Meeting: Cards stage test on 2099-03-01")
    assert user.count("=== ITEM MARKER") == 2
    assert f"=== ITEM MARKER item_id={inst.item_ids[1]} (Item 1) ===" in user
    assert "[seq=2 t=00:01:40 Council President] Item one is the street paving contract" in user
    assert "[seq=3 t=00:01:50 Speaker 2] The contract is for four million dollars" in user   # below the floor: no name


def test_each_build_writes_an_ai_run_with_its_cost(make):
    make()
    _run(FakeClient())
    (run,) = _ai_runs()
    assert run["stage"] == "transcript_cards" and run["model"] == C.AI_TRANSCRIPT_CARDS_MODEL
    assert (run["rows_processed"], run["rows_failed"]) == (1, 0) and run["finished_at"] is not None
    assert float(run["cost_usd"]) == pytest.approx(calculate_cost_usd(C.AI_TRANSCRIPT_CARDS_MODEL, USAGE), abs=1e-4)
    assert run["usage"]["input_tokens"] == 1200 and run["usage"]["output_tokens"] == 300


def test_the_report_line_has_the_contracted_shape(make):
    inst = make()
    summary = _run(FakeClient())
    assert summary.reports == [
        (f"cards: meeting {inst.meeting_id} transcript {inst.transcript_id}: 2 placed, 2 cards "
         "(2 discussed, 0 missing, 0 extra), details 2 kept 0 re-pointed 0 dropped, bounds 2 kept 0 dropped, "
         "0 starts moved 20 s or more, 1200 in 300 out, $0.0054")
    ]


def test_the_real_meeting_2543_builds_a_card_for_each_of_its_nine_placed_items(make):
    inst = make(bundle=load_bundle("transcript_2543"), external_id="999952")
    summary = _run(FakeClient())
    assert summary.built == 1
    run = _run_row(inst)
    assert run["status"] == "done"
    assert (run["counts"]["placed"], run["counts"]["cards"], run["counts"]["missing"]) == (9, 9, 0)
    assert run["counts"]["details_kept"] == 9 and run["counts"]["bounds_kept"] == 9
    assert len(_card_rows(inst)) == 9
    assert " 9 placed, 9 cards (9 discussed, 0 missing, 0 extra)" in summary.reports[0]


# --- the claim ---------------------------------------------------------------------------------------------------


def test_a_second_run_claims_nothing(make):
    make()
    fake = FakeClient()
    assert _run(fake).built == 1
    again = _run(fake)
    assert (again.built, again.failed, again.held, again.reports) == (0, 0, 0, [])
    assert len(fake.calls) == 1 and len(_ai_runs()) == 1


def test_the_newest_meeting_is_claimed_first(make):
    older = make(meeting_date="2099-03-01", external_id="999951")
    newer = make(meeting_date="2099-04-01", external_id="999952")
    assert _run(FakeClient(), limit=1).built == 1
    assert _run_row(newer)["status"] == "done" and _run_row(older) is None


def test_a_later_upload_makes_it_claimable_again_and_resets_the_attempts(make):
    inst = make()
    assert _run(FakeClient(raises=AITransientError("503"))).failed == 1
    _age_last_attempt(inst)
    assert _run(FakeClient(raises=AITransientError("503"))).failed == 1
    assert _run_row(inst)["attempts"] == 2
    with db_cursor() as cur:   # a re-upload: the producer replaces the segments and stamps a new uploaded_at
        cur.execute("UPDATE transcripts SET uploaded_at = uploaded_at + interval '1 hour' WHERE id = %s",
                    [inst.transcript_id])
    assert _run(FakeClient()).built == 1   # no waiting out the 24 hours: the run row describes another upload
    run = _run_row(inst)
    assert (run["status"], run["attempts"]) == ("done", 1)
    assert run["source_uploaded_at"] == _uploaded_at(inst)
    assert {c["source_uploaded_at"] for c in _card_rows(inst)} == {_uploaded_at(inst)}


def test_a_done_run_is_claimed_again_after_a_later_upload(make):
    inst = make()
    fake = FakeClient()
    assert _run(fake).built == 1
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET uploaded_at = uploaded_at + interval '1 hour' WHERE id = %s",
                    [inst.transcript_id])
    assert _run(fake).built == 1
    assert len(fake.calls) == 2 and _run_row(inst)["attempts"] == 1


def test_a_run_from_an_older_prompt_version_is_claimed_again(make):
    inst = make()
    fake = FakeClient()
    _run(fake)
    with db_cursor() as cur:
        cur.execute("UPDATE transcript_card_runs SET prompt_version = 199, attempts = 3 WHERE transcript_id = %s",
                    [inst.transcript_id])
    assert _run(fake).built == 1
    run = _run_row(inst)
    assert (run["prompt_version"], run["attempts"], run["status"]) == (200, 1, "done")


@pytest.mark.parametrize("kw", [
    {"status": "uploaded"},
    {"status": "speakers_resolved"},
    {"status": "low_speech"},
    {"hidden": True},
    {"external_id": "yt-pytest-cards"},
], ids=["uploaded", "speakers_resolved", "low_speech", "hidden", "youtube_only"])
def test_what_is_never_claimed(make, kw):
    inst = make(**kw)
    fake = FakeClient()
    summary = _run(fake)
    assert (summary.built, summary.failed, summary.held) == (0, 0, 0)
    assert _run_row(inst) is None and _card_rows(inst) == [] and fake.calls == [] and _ai_runs() == []


def test_a_transcript_at_compared_is_claimed(make):
    inst = make(status="compared")
    assert _run(FakeClient()).built == 1
    assert _run_row(inst)["status"] == "done"


def test_the_stage_writes_nothing_to_the_transcripts_row(make):
    inst = make()
    with db_cursor() as cur:
        cur.execute("SELECT * FROM transcripts WHERE id = %s", [inst.transcript_id])
        before = dict(cur.fetchone())
    _run(FakeClient())
    _run(FakeClient(raises=AITransientError("503")), meeting_ids=[inst.meeting_id])
    with db_cursor() as cur:
        cur.execute("SELECT * FROM transcripts WHERE id = %s", [inst.transcript_id])
        assert dict(cur.fetchone()) == before


# --- what a failed, held, or incomplete build leaves ---------------------------------------------------------------


def test_a_transient_error_leaves_failed_and_waits_24_hours(make):
    inst = make()
    summary = _run(FakeClient(raises=AITransientError("Transient retries exhausted: 503")))
    assert (summary.built, summary.failed, summary.held) == (0, 1, 0)
    run = _run_row(inst)
    assert (run["status"], run["attempts"]) == ("failed", 1) and "503" in run["last_error"]
    (ai_run,) = _ai_runs()
    assert (ai_run["rows_processed"], ai_run["rows_failed"]) == (0, 1) and ai_run["finished_at"] is not None
    fake = FakeClient()
    assert _run(fake).built == 0 and fake.calls == []   # inside the 24 hours
    _age_last_attempt(inst)
    assert _run(fake).built == 1
    assert (_run_row(inst)["status"], _run_row(inst)["attempts"], _run_row(inst)["last_error"]) == ("done", 2, None)


def test_a_third_failure_is_not_claimed_again(make):
    inst = make()
    for _ in range(3):
        assert _run(FakeClient(raises=AITransientError("503"))).failed == 1
        _age_last_attempt(inst)
    assert (_run_row(inst)["status"], _run_row(inst)["attempts"]) == ("failed", 3)
    fake = FakeClient()
    assert _run(fake).built == 0 and fake.calls == []


def test_a_bug_in_the_build_leaves_failed_and_does_not_raise(make):
    inst = make()
    summary = _run(FakeClient(raises=RuntimeError("boom")))
    assert summary.failed == 1
    run = _run_row(inst)
    assert run["status"] == "failed" and run["last_error"] == "RuntimeError: boom"


@pytest.mark.parametrize("exc,starts", [
    (TranscriptHeld("refusal", "the model declined"), "refusal: the model declined"),
    (AIPermanentRowError("max_tokens: output hit the 64000 ceiling"), "permanent: max_tokens"),
], ids=["held", "permanent"])
def test_a_hold_leaves_held_and_is_not_retried(make, exc, starts):
    inst = make()
    summary = _run(FakeClient(raises=exc))
    assert (summary.built, summary.failed, summary.held) == (0, 0, 1)
    run = _run_row(inst)
    assert run["status"] == "held" and run["last_error"].startswith(starts)
    _age_last_attempt(inst)
    fake = FakeClient()
    assert _run(fake).built == 0 and fake.calls == []


def test_a_meeting_over_the_token_ceiling_is_held_without_a_call(make, monkeypatch):
    inst = make()
    monkeypatch.setattr(C, "TRANSCRIPT_TOKEN_CEILING", 500)
    fake = FakeClient(tokens=501)
    assert _run(fake).held == 1
    run = _run_row(inst)
    assert run["status"] == "held" and run["last_error"].startswith("token_ceiling: 501 tokens")
    assert fake.calls == [] and _card_rows(inst) == []


def test_a_reply_that_does_not_fit_the_models_is_held(make):
    inst = make()
    assert _run(FakeClient(reply=lambda data: {"cards": [{"item_id": inst.item_ids[1]}]})).held == 1
    run = _run_row(inst)
    assert run["status"] == "held" and run["last_error"].startswith("schema_invalid: ")
    assert _card_rows(inst) == []


def test_a_rate_limit_hands_the_attempt_back_and_stops_the_loop(make):
    first = make(meeting_date="2099-04-01", external_id="999952")
    second = make(meeting_date="2099-03-01", external_id="999951")
    fake = FakeClient(raises=AIRateLimited("Rate limit retries exhausted"))
    summary = _run(fake)
    assert (summary.built, summary.failed, summary.held, summary.stopped_reason) == (0, 0, 0, "rate_limited")
    assert len(fake.calls) == 1 and _run_row(second) is None
    run = _run_row(first)
    assert (run["status"], run["attempts"]) == ("claimed", 0) and run["last_error"].startswith("rate limited: ")
    good = FakeClient()
    assert _run(good, limit=1).built == 1 and _run_row(second)["status"] == "done"   # the first waits out its day
    _age_last_attempt(first)
    assert _run(good).built == 1
    assert (_run_row(first)["status"], _run_row(first)["attempts"]) == ("done", 1)


def test_a_fatal_error_propagates_and_closes_its_ai_run(make):
    make()
    with pytest.raises(AIFatalError):
        _run(FakeClient(raises=AIFatalError("Auth error from Anthropic")))
    (ai_run,) = _ai_runs()
    assert ai_run["finished_at"] is not None


def test_a_model_without_a_price_is_fatal_before_any_claim(make, monkeypatch):
    inst = make()
    monkeypatch.setattr(C, "AI_TRANSCRIPT_CARDS_MODEL", "claude-not-a-model")
    fake = FakeClient()
    with pytest.raises(AIFatalError, match="PRICING"):
        _run(fake)
    assert _run_row(inst) is None and fake.calls == [] and _ai_runs() == []


def test_a_reply_that_omits_a_placed_item_writes_the_rest_and_is_retried(make):
    inst = make()
    summary = _run(FakeClient(reply=lambda data: {"cards": data["cards"][:1]}))
    assert (summary.built, summary.failed, summary.held) == (0, 1, 0)
    assert [c["agenda_item_id"] for c in _card_rows(inst)] == [inst.item_ids[1]]
    assert _matches(inst.item_ids[1], "zebra") and not _matches(inst.item_ids[2], "zebra")
    run = _run_row(inst)
    assert run["status"] == "failed" and run["last_error"] == "incomplete: 1 of 2 placed items carded"
    assert run["counts"]["missing"] == 1 and run["model"] == C.AI_TRANSCRIPT_CARDS_MODEL
    assert "2 placed, 1 cards (1 discussed, 1 missing, 0 extra)" in summary.reports[0]
    fake = FakeClient()
    assert _run(fake).built == 0 and fake.calls == []   # inside the 24 hours
    _age_last_attempt(inst)
    assert _run(fake).built == 1
    assert (_run_row(inst)["status"], _run_row(inst)["attempts"]) == ("done", 2)
    assert len(_card_rows(inst)) == 2 and _matches(inst.item_ids[2], "zebra")


def test_a_reply_with_no_card_leaves_the_earlier_cards_in_place(make):
    inst = make()
    assert _run(FakeClient()).built == 1
    before = _card_rows(inst)
    summary = _run(FakeClient(reply=lambda data: {"cards": []}), meeting_ids=[inst.meeting_id])
    assert (summary.built, summary.failed) == (0, 1)
    assert _card_rows(inst) == before and _matches(inst.item_ids[1], "zebra")
    run = _run_row(inst)
    assert run["status"] == "failed" and run["last_error"] == "incomplete: 0 of 2 placed items carded"
    assert "2 placed, 0 cards (0 discussed, 2 missing, 0 extra)" in summary.reports[0]


def test_a_meeting_with_no_placed_item_is_done_without_a_call(make):
    inst = make(place=False)
    fake = FakeClient()
    summary = _run(fake)
    assert (summary.built, summary.failed, summary.held, summary.reports) == (1, 0, 0, [])
    assert fake.calls == [] and fake.counted == [] and _card_rows(inst) == []
    run = _run_row(inst)
    assert run["status"] == "done" and run["counts"]["placed"] == 0 and run["model"] is None
    assert _run(fake).built == 0   # done is done: it is not claimed on every tick


def test_an_upload_that_lands_during_the_call_writes_nothing_and_is_carded_once_it_is_past_events_again(make):
    inst = make()

    def reupload():   # what the producer's upload() does to the row: new segments, a new uploaded_at, status uploaded
        with db_cursor() as cur:
            cur.execute("""UPDATE transcripts SET uploaded_at = uploaded_at + interval '1 hour', status = 'uploaded'
                            WHERE id = %s""", [inst.transcript_id])

    summary = _run(FakeClient(on_call=reupload))
    assert (summary.built, summary.failed) == (0, 1) and len(summary.reports) == 1
    run = _run_row(inst)
    assert run["status"] == "failed" and run["last_error"] == "transcript changed during the run"
    assert run["counts"]["written"] == -1 and _card_rows(inst) == []
    fake = FakeClient()
    assert _run(fake).built == 0 and fake.calls == []   # not past the events stage any more
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status = 'events_extracted' WHERE id = %s", [inst.transcript_id])
    assert _run(fake).built == 1   # at once: the failed run describes the earlier upload
    assert (_run_row(inst)["status"], _run_row(inst)["attempts"]) == ("done", 1)
    assert {c["source_uploaded_at"] for c in _card_rows(inst)} == {_uploaded_at(inst)}


# --- named meetings, dry runs, and the budget ------------------------------------------------------------------------


def test_a_named_meeting_is_rebuilt_whatever_its_run_row_says(make):
    inst = make()
    fake = FakeClient()
    assert _run(fake).built == 1
    assert _run(fake, limit=1, meeting_ids=[inst.meeting_id]).built == 1
    assert len(fake.calls) == 2 and len(_card_rows(inst)) == 2
    assert (_run_row(inst)["status"], _run_row(inst)["attempts"]) == ("done", 2)


def test_a_named_meeting_that_cannot_be_carded_is_passed_over(make):
    waiting = make(status="uploaded", external_id="999951")
    ready = make(external_id="999952")
    fake = FakeClient()
    summary = _run(fake, meeting_ids=[waiting.meeting_id, ready.meeting_id])
    assert (summary.built, summary.failed, summary.held) == (1, 0, 0)
    assert _run_row(waiting) is None and _run_row(ready)["status"] == "done"


def test_named_meetings_are_bounded_by_the_limit(make):
    a = make(external_id="999951")
    b = make(external_id="999952")
    assert _run(FakeClient(), limit=1, meeting_ids=[a.meeting_id, b.meeting_id]).built == 1
    assert _run_row(a)["status"] == "done" and _run_row(b) is None


def test_a_dry_run_writes_no_card_and_no_run_row_and_does_write_its_ai_run(make):
    inst = make()
    fake = FakeClient()
    summary = _run(fake, dry_run=True)
    assert (summary.built, summary.failed, summary.held) == (1, 0, 0)
    assert len(fake.calls) == 1 and len(summary.reports) == 1 and "2 placed, 2 cards" in summary.reports[0]
    assert _card_rows(inst) == [] and _run_row(inst) is None and not _matches(inst.item_ids[1], "zebra")
    (ai_run,) = _ai_runs()
    assert ai_run["stage"] == "transcript_cards" and float(ai_run["cost_usd"]) > 0


def test_a_dry_run_with_a_limit_visits_each_waiting_meeting_once(make):
    make(meeting_date="2099-03-01", external_id="999951")
    make(meeting_date="2099-04-01", external_id="999952")
    fake = FakeClient()
    summary = _run(fake, limit=5, dry_run=True)
    assert summary.built == 2 and len(fake.calls) == 2
    assert [c["user"].splitlines()[0] for c in fake.calls] == ["Meeting: Cards stage test on 2099-04-01",
                                                               "Meeting: Cards stage test on 2099-03-01"]


def test_a_dry_run_of_a_named_meeting_leaves_its_run_row_and_cards_as_they_were(make):
    inst = make()
    _run(FakeClient())
    before = (_run_row(inst), _card_rows(inst))
    summary = _run(FakeClient(reply=lambda data: {"cards": data["cards"][:1]}), meeting_ids=[inst.meeting_id],
                   dry_run=True)
    assert summary.failed == 1 and "1 missing" in summary.reports[0]
    assert (_run_row(inst), _card_rows(inst)) == before


def test_a_days_spend_at_the_budget_stops_before_any_claim(make, spend):
    inst = make()
    spend["usd"] = AI_DAILY_BUDGET_USD
    fake = FakeClient()
    summary = _run(fake)
    assert (summary.built, summary.stopped_reason) == (0, "budget")
    assert _run_row(inst) is None and fake.calls == [] and _ai_runs() == []
    assert _run(fake, force_budget=True).built == 1


def test_the_budget_is_read_before_each_meeting(make, spend):
    make(meeting_date="2099-03-01", external_id="999951")
    make(meeting_date="2099-04-01", external_id="999952")

    def spend_it_all():
        spend["usd"] = AI_DAILY_BUDGET_USD

    fake = FakeClient(on_call=spend_it_all)
    summary = _run(fake)
    assert (summary.built, summary.stopped_reason) == (1, "budget") and len(fake.calls) == 1


# --- the tick ------------------------------------------------------------------------------------------------------


@pytest.fixture
def quiet_tick(monkeypatch):
    """The tick's housekeeping, recorded and not run: the sweep can fetch a minutes PDF and the alert can post."""
    import docket.ai.transcripts.alerts as A
    calls = []
    monkeypatch.setattr(P, "sweep_minutes_changes", lambda limit=10: calls.append("sweep") or 0)
    monkeypatch.setattr(A, "alert_if_producer_stalled", lambda: calls.append("stall") or False)
    return calls


def test_the_tick_builds_cards_and_reports_them(make, quiet_tick):
    inst = make()
    fake = FakeClient()
    s = P.run_transcript_pipeline(limit=0, notes=NOTES, client=fake)
    assert (s.cards_built, s.cards_failed, s.processed, s.stopped_reason) == (1, 0, 0, None)
    assert _run_row(inst)["status"] == "done" and len(_card_rows(inst)) == 2
    assert [r["stage"] for r in _ai_runs()] == ["transcript_cards"]
    assert quiet_tick == ["sweep", "stall"]
    assert "cards_built=1" in repr(s) and "cards_failed=0" in repr(s)   # the tick's log line prints the dataclass


def test_the_tick_builds_no_more_than_its_limit(make, quiet_tick, monkeypatch):
    make(meeting_date="2099-03-01", external_id="999951")
    make(meeting_date="2099-04-01", external_id="999952")
    make(meeting_date="2099-05-01", external_id="999953")
    monkeypatch.setattr(P, "TRANSCRIPT_CARDS_PER_TICK", 2)
    fake = FakeClient()
    assert P.run_transcript_pipeline(limit=0, notes=NOTES, client=fake).cards_built == 2
    assert len(fake.calls) == 2


def test_the_tick_counts_held_and_failed_builds_together(make, quiet_tick):
    make()
    s = P.run_transcript_pipeline(limit=0, notes=NOTES, client=FakeClient(raises=TranscriptHeld("refusal", "no")))
    assert (s.cards_built, s.cards_failed) == (0, 1)


def test_a_per_tick_limit_of_zero_turns_the_stage_off(make, quiet_tick, monkeypatch):
    inst = make()
    monkeypatch.setattr(P, "TRANSCRIPT_CARDS_PER_TICK", 0)
    fake = FakeClient()
    s = P.run_transcript_pipeline(limit=0, notes=NOTES, client=fake)
    assert (s.cards_built, s.cards_failed) == (0, 0) and fake.calls == [] and _run_row(inst) is None


def test_a_card_bug_does_not_take_the_tick_down(quiet_tick, monkeypatch):
    def boom(**kw):
        raise RuntimeError("card bug")

    monkeypatch.setattr(C, "run_cards", boom)
    s = P.run_transcript_pipeline(limit=0, notes=NOTES, client=FakeClient())
    assert (s.cards_built, s.cards_failed) == (0, 1) and quiet_tick == ["sweep", "stall"]


def test_a_fatal_card_error_reaches_the_tick(quiet_tick, monkeypatch):
    def fatal(**kw):
        raise AIFatalError("no price")

    monkeypatch.setattr(C, "run_cards", fatal)
    with pytest.raises(AIFatalError):
        P.run_transcript_pipeline(limit=0, notes=NOTES, client=FakeClient())
    assert quiet_tick == ["sweep", "stall"]


def test_the_tick_builds_no_cards_when_its_stage_loop_stopped(quiet_tick, monkeypatch, spend):
    monkeypatch.setattr(P, "reset_for_versions", lambda: 0)
    monkeypatch.setattr(P, "claim_next", lambda: {"id": 0, "meeting_id": 0, "status": "uploaded"})
    monkeypatch.setattr(P, "process_claim", lambda claim, *, client, notes: "rate_limited")
    monkeypatch.setattr(C, "run_cards", lambda **kw: (_ for _ in ()).throw(AssertionError("cards ran")))
    s = P.run_transcript_pipeline(limit=1, notes=NOTES, client=FakeClient())
    assert (s.stopped_reason, s.cards_built, s.cards_failed) == ("rate_limited", 0, 0)


# --- the command ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [
    [],
    ["--count", "--limit", "3"],
    ["--limit", "3", "--meeting-id", "7"],
    ["--count", "--dry-run"],
    ["--limit", "0"],
    ["--dry-run"],
], ids=["no_mode", "count_and_limit", "limit_and_meeting", "count_dry_run", "limit_zero", "dry_run_alone"])
def test_the_command_refuses_anything_but_exactly_one_bounded_mode(argv, capsys, monkeypatch):
    monkeypatch.setattr(C, "run_cards", lambda **kw: (_ for _ in ()).throw(AssertionError("ran")))
    with pytest.raises(SystemExit) as e:
        _script().main(argv)
    assert e.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_the_commands_count_line_and_what_each_number_means(make, capsys):
    def count():
        assert _script().main(["--count"]) == 0
        (line,) = capsys.readouterr().out.strip().splitlines()
        m = COUNT_LINE.match(line)
        assert m, line
        return [int(n) for n in m.groups()]

    base = count()
    not_yet = make(status="uploaded", external_id="999951")
    ready = make(external_id="999952")
    assert [a - b for a, b in zip(count(), base)] == [2, 1, 0, 1, 0, 0]   # two public, one past events and waiting
    _run(FakeClient())
    assert [a - b for a, b in zip(count(), base)] == [2, 1, 1, 0, 0, 0]   # current cards
    with db_cursor() as cur:
        cur.execute("UPDATE transcript_card_runs SET status = 'held' WHERE transcript_id = %s", [ready.transcript_id])
    assert [a - b for a, b in zip(count(), base)] == [2, 1, 0, 0, 1, 0]
    with db_cursor() as cur:
        cur.execute("UPDATE transcript_card_runs SET status = 'failed', attempts = 2 WHERE transcript_id = %s",
                    [ready.transcript_id])
    assert [a - b for a, b in zip(count(), base)] == [2, 1, 0, 1, 0, 0]   # a failed run with an attempt left waits
    with db_cursor() as cur:
        cur.execute("UPDATE transcript_card_runs SET attempts = 3 WHERE transcript_id = %s", [ready.transcript_id])
    assert [a - b for a, b in zip(count(), base)] == [2, 1, 0, 0, 0, 1]   # out of attempts
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET uploaded_at = uploaded_at + interval '1 hour' WHERE id = %s",
                    [ready.transcript_id])
    assert [a - b for a, b in zip(count(), base)] == [2, 1, 0, 1, 0, 0]   # a new upload waits again
    assert _run_row(not_yet) is None


@pytest.mark.parametrize("argv,expected", [
    (["--limit", "3"], {"limit": 3, "meeting_ids": None, "dry_run": False, "force_budget": False}),
    (["--limit", "3", "--dry-run", "--force-budget"],
     {"limit": 3, "meeting_ids": None, "dry_run": True, "force_budget": True}),
    (["--meeting-id", "2224", "--meeting-id", "2231", "--dry-run"],
     {"limit": 2, "meeting_ids": [2224, 2231], "dry_run": True, "force_budget": False}),
], ids=["limit", "limit_dry_forced", "two_meetings_dry"])
def test_the_command_passes_its_bound_to_run_cards_and_prints_the_reports(argv, expected, capsys, monkeypatch):
    seen = {}

    def fake_run_cards(**kw):
        seen.update(kw)
        return C.CardsSummary(built=1, failed=2, held=3, stopped_reason=None,
                              reports=["cards: meeting 1 transcript 2: a report line"])

    monkeypatch.setattr(C, "run_cards", fake_run_cards)
    assert _script().main(argv) == 0
    assert {k: seen[k] for k in expected} == expected and seen["notes"] == "cli_cards"
    assert capsys.readouterr().out.splitlines() == ["cards: meeting 1 transcript 2: a report line",
                                                    "cards: built 1, held 3, failed 2, stopped: none"]


def test_the_command_names_why_it_stopped_and_fails_on_a_fatal_error(capsys, monkeypatch):
    monkeypatch.setattr(C, "run_cards", lambda **kw: C.CardsSummary(stopped_reason="budget"))
    assert _script().main(["--limit", "1"]) == 0
    assert capsys.readouterr().out.splitlines() == ["cards: built 0, held 0, failed 0, stopped: budget"]
    monkeypatch.setattr(C, "run_cards", lambda **kw: (_ for _ in ()).throw(AIFatalError("ANTHROPIC_API_KEY is not set")))
    assert _script().main(["--limit", "1"]) == 1
    assert "cards: fatal: ANTHROPIC_API_KEY is not set" in capsys.readouterr().err


def test_the_claim_keeps_its_bookkeeping_out_of_the_transcripts_table():
    assert "UPDATE transcripts" not in C.CLAIM_CARDS_SQL and "transcript_card_runs" in C.CLAIM_CARDS_SQL
    assert "t.meeting_id = %(meeting_id)s" in C.CLAIM_CARDS_MEETING_SQL
    assert "interval '24 hours'" not in C.CLAIM_CARDS_MEETING_SQL and "r.attempts < 3" not in C.CLAIM_CARDS_MEETING_SQL
