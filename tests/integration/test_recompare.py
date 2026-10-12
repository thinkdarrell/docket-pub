"""Minutes change -> stale -> re-proposed in place; unmatched approvals stay stale; public reads exclude stale."""
from unittest.mock import MagicMock

import pytest

from docket.ai.pricing import Usage
from docket.ai.transcripts import compare as C
from docket.ai.transcripts import minutes as M
from docket.ai.transcripts import pipeline as P
from docket.ai.transcripts.client import StructuredResult
from docket.config import DATABASE_URL
from docket.db import db_cursor
from tests.integration.test_compare_stage import _claim, _client, _ids_in_prompt, _seed_events
from tests.support.transcript_fixtures import install_bundle, pilot_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


@pytest.fixture
def pilot():
    i = install_bundle(pilot_bundle(), external_id="999015", status="events_extracted")
    yield i
    i.cleanup()


def _real_all(info):
    def verdicts(user):
        out = []
        for cid in _ids_in_prompt(user):
            head = user.split(f"### Candidate {cid}")[1].split("\n")[0]
            cat = "sequence" if "sequence" in head else ("wording" if "wording" in head else "omission")
            out.append({"candidate_id": cid, "is_real": True, "category": cat, "severity": "material", "title": f"{cat} title",
                        "description": "desc", "transcript_quote": info["exec_text"], "minutes_quote": "go into Executive Session",
                        "confidence": 0.9, "dismiss_reason": None})
        return out
    return verdicts


def _checked_recently(mid):
    with db_cursor() as cur:
        cur.execute("SELECT last_checked_at > now() - interval '1 minute' AS ok FROM minutes_texts WHERE meeting_id=%s", [mid])
        return cur.fetchone()["ok"] is True


def _states(mid):
    with db_cursor() as cur:
        cur.execute("""SELECT id, category, review_state, previous_review_state, reviewed_by, reviewed_at
                         FROM minutes_discrepancies WHERE meeting_id=%s ORDER BY id""", [mid])
        return [dict(r) for r in cur.fetchall()]


def test_recompare_updates_matched_rows_in_place_and_leaves_others_stale(pilot, monkeypatch):
    """The minutes-changed case: approved rows go stale first and a candidate that comes back is re-proposed in place."""
    info = _seed_events(pilot)
    C.run_compare_stage(_claim(pilot), client=_client(_real_all(info)))
    first = _states(pilot.meeting_id)
    assert sorted(r["category"] for r in first) == ["sequence", "wording"]
    with db_cursor() as cur:   # the admin approves both
        cur.execute("UPDATE minutes_discrepancies SET review_state='approved', reviewed_at=now(), reviewed_by='t' WHERE meeting_id=%s", [pilot.meeting_id])

    # Second comparison: only the wording candidate is still judged real.
    def verdicts(user):
        out = []
        for cid in _ids_in_prompt(user):
            head = user.split(f"### Candidate {cid}")[1].split("\n")[0]
            real = "wording" in head
            out.append({"candidate_id": cid, "is_real": real, "category": "wording" if real else None, "severity": "material" if real else None,
                        "title": "wording title v2" if real else None, "description": "desc v2" if real else None,
                        "transcript_quote": info["exec_text"] if real else None, "minutes_quote": "go into Executive Session" if real else None,
                        "confidence": 0.9, "dismiss_reason": None if real else "now matches"})
        return out
    monkeypatch.setattr(C, "extract_minutes_side", lambda mid, *, client: "ok")   # the stage re-extracts the minutes side on this reason
    C.run_compare_stage(_claim(pilot, reason="minutes_changed"), client=_client(verdicts))
    second = _states(pilot.meeting_id)
    wording = next(r for r in second if r["category"] == "wording" and r["review_state"] != "dismissed_by_model")
    sequence = next(r for r in second if r["category"] == "sequence" and r["review_state"] != "dismissed_by_model")
    assert wording["id"] == next(r["id"] for r in first if r["category"] == "wording")      # updated in place, no duplicate
    assert (wording["review_state"], wording["previous_review_state"]) == ("proposed", "approved")
    assert wording["reviewed_by"] is None and wording["reviewed_at"] is None               # unreviewed again; history is in previous_review_state
    assert sequence["review_state"] == "stale" and sequence["reviewed_by"] == "t"            # corrected minutes no longer show it
    with db_cursor() as cur:
        cur.execute("SELECT title FROM minutes_discrepancies WHERE id=%s", [wording["id"]])
        assert cur.fetchone()["title"] == "wording title v2"
    assert len([r for r in second if r["review_state"] in ("proposed", "approved", "stale")]) == 2


def test_sweep_flags_changed_minutes_for_recompare(pilot, monkeypatch):
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status='compared' WHERE id=%s", [pilot.transcript_id])
        cur.execute("UPDATE minutes_texts SET extracted_at = now() - interval '10 days' WHERE meeting_id=%s", [pilot.meeting_id])
    monkeypatch.setattr(M, "recheck_minutes", lambda mid: True)
    assert P.sweep_minutes_changes() >= 1
    with db_cursor() as cur:
        cur.execute("SELECT status, compare_skipped_reason, stage_attempts FROM transcripts WHERE id=%s", [pilot.transcript_id])
        assert tuple(cur.fetchone().values()) == ("events_extracted", "minutes_changed", 0)
    assert _checked_recently(pilot.meeting_id)
    assert P.claim_next()["id"] == pilot.transcript_id       # claimable immediately


def test_unchanged_minutes_are_left_alone(pilot, monkeypatch):
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status='compared' WHERE id=%s", [pilot.transcript_id])
        cur.execute("UPDATE minutes_texts SET extracted_at = now() - interval '10 days' WHERE meeting_id=%s", [pilot.meeting_id])
    monkeypatch.setattr(M, "recheck_minutes", lambda mid: False)
    P.sweep_minutes_changes()
    with db_cursor() as cur:
        cur.execute("SELECT status FROM transcripts WHERE id=%s", [pilot.transcript_id])
        assert cur.fetchone()["status"] == "compared"
        # I4: last_checked_at records the recheck; extracted_at keeps meaning "text extracted at".
        cur.execute("SELECT extracted_at < now() - interval '9 days' AS old FROM minutes_texts WHERE meeting_id=%s", [pilot.meeting_id])
        assert cur.fetchone()["old"] is True
    assert _checked_recently(pilot.meeting_id)


def test_sweep_continues_past_a_raising_recheck(pilot, monkeypatch):
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status='compared' WHERE id=%s", [pilot.transcript_id])
        cur.execute("UPDATE minutes_texts SET extracted_at = now() - interval '10 days' WHERE meeting_id=%s", [pilot.meeting_id])
    seen = []

    def recheck(mid):
        seen.append(mid)
        if mid != pilot.meeting_id:
            raise RuntimeError("corrupt pdf")
        return True
    monkeypatch.setattr(M, "recheck_minutes", recheck)
    # Any other compared meeting in the local DB raises; ours must still be flagged.
    assert P.sweep_minutes_changes(limit=50) >= 1
    assert pilot.meeting_id in seen
    with db_cursor() as cur:
        cur.execute("SELECT status FROM transcripts WHERE id=%s", [pilot.transcript_id])
        assert cur.fetchone()["status"] == "events_extracted"


def test_sweep_survives_when_the_only_recheck_raises(pilot, monkeypatch):
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status='compared' WHERE id=%s", [pilot.transcript_id])
        cur.execute("UPDATE minutes_texts SET extracted_at = now() - interval '10 days' WHERE meeting_id=%s", [pilot.meeting_id])

    def boom(mid):
        raise RuntimeError("corrupt pdf")
    monkeypatch.setattr(M, "recheck_minutes", boom)
    assert P.sweep_minutes_changes(limit=50) == 0
    with db_cursor() as cur:
        cur.execute("SELECT status FROM transcripts WHERE id=%s", [pilot.transcript_id])
        assert cur.fetchone()["status"] == "compared"
    assert _checked_recently(pilot.meeting_id)          # a raising recheck still moves the sweep on (I4)


def test_none_recheck_is_not_selected_again_within_a_week(pilot, monkeypatch):
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status='compared' WHERE id=%s", [pilot.transcript_id])
        cur.execute("UPDATE minutes_texts SET extracted_at = now() - interval '10 days' WHERE meeting_id=%s", [pilot.meeting_id])
    seen = []
    monkeypatch.setattr(M, "recheck_minutes", lambda mid: (seen.append(mid), None)[1])
    P.sweep_minutes_changes(limit=50)
    assert pilot.meeting_id in seen and _checked_recently(pilot.meeting_id)
    seen.clear()
    P.sweep_minutes_changes(limit=50)
    assert pilot.meeting_id not in seen


def test_run_for_meeting_drives_stages_in_order(pilot, monkeypatch):
    calls = []
    def fake(stage):
        nxt = {"speakers": "speakers_resolved", "events": "events_extracted", "compare": "compared"}[stage]
        return lambda claim, client: (calls.append(stage), P.StageOutcome(nxt))[1]
    monkeypatch.setattr(P, "_stage_fn", fake)
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status='uploaded', word_count=5000 WHERE id=%s", [pilot.transcript_id])
    outcomes = P.run_for_meeting(pilot.meeting_id, client=MagicMock(), notes="pytest_run_for_meeting")
    assert calls == ["speakers", "events", "compare"] and outcomes == ["advanced", "advanced", "advanced"]
    with db_cursor() as cur:
        cur.execute("DELETE FROM ai_runs WHERE notes='pytest_run_for_meeting'")


def test_minutes_changed_rerun_survives_one_sided_rows(pilot, monkeypatch):
    """C1: re-extracting the minutes side deletes the old minutes events; one-sided rows must survive the SET NULL."""
    import json

    from docket.ai.transcripts import events as E
    from docket.ai.transcripts.schemas import ExtractedEvent

    info = _seed_events(pilot)
    item = info["item"]
    with db_cursor() as cur:
        cur.execute("SELECT text FROM minutes_texts WHERE meeting_id=%s", [pilot.meeting_id])
        mtext = cur.fetchone()["text"]
        cur.execute("SELECT id, start_s FROM transcript_segments WHERE transcript_id=%s AND text=%s", [pilot.transcript_id, info["exec_text"]])
        seg = cur.fetchone()
        adj_quote = "the Council adjourned at 11:30"
        # Transcript-only recess (-> omission candidate) and minutes-only adjourn (-> addition candidate).
        cur.execute("""INSERT INTO meeting_events (meeting_id, source, seq, event_type, scope, agenda_item_refs, summary, detail,
                                                   start_s, segment_id, prompt_version)
                       VALUES (%s, 'transcript', 3, 'recess', 'meeting', '{}', 'recess', %s::jsonb, %s, %s, 200)""",
                    [pilot.meeting_id, json.dumps({"quote": info["exec_text"]}), seg["start_s"] + 30, seg["id"]])
        cur.execute("""INSERT INTO meeting_events (meeting_id, source, seq, event_type, scope, agenda_item_refs, summary, detail,
                                                   page, char_offset, prompt_version)
                       VALUES (%s, 'minutes', 3, 'adjourn', 'meeting', '{}', 'adjourn', %s::jsonb, 1, %s, 200)""",
                    [pilot.meeting_id, json.dumps({"quote": adj_quote}), mtext.index(adj_quote)])

    def verdicts(user):
        out = []
        for cid in _ids_in_prompt(user):
            head = user.split(f"### Candidate {cid}")[1].split("\n")[0]
            cat = next(c for c in ("sequence", "wording", "omission", "addition") if c in head)
            out.append({"candidate_id": cid, "is_real": True, "category": cat, "severity": "material", "title": f"{cat} title",
                        "description": "desc",
                        "transcript_quote": info["exec_text"] if cat != "addition" else None,
                        "minutes_quote": (adj_quote if cat == "addition" else "go into Executive Session") if cat != "omission" else None,
                        "confidence": 0.9, "dismiss_reason": None})
        return out

    C.run_compare_stage(_claim(pilot), client=_client(verdicts))
    first = {r["id"]: r for r in _states(pilot.meeting_id)}
    cats = sorted(r["category"] for r in first.values())
    assert {"omission", "addition", "sequence", "wording"} <= set(cats)
    with db_cursor() as cur:
        cur.execute("UPDATE minutes_discrepancies SET review_state='approved', reviewed_at=now(), reviewed_by='t' WHERE meeting_id=%s",
                    [pilot.meeting_id])
        cur.execute("SELECT id, category, transcript_event_id, minutes_event_id FROM minutes_discrepancies WHERE meeting_id=%s",
                    [pilot.meeting_id])
        before = {r["id"]: dict(r) for r in cur.fetchall()}
    omission = next(r for r in before.values() if r["category"] == "omission")
    addition = next(r for r in before.values() if r["category"] == "addition")
    assert omission["minutes_event_id"] is None and addition["transcript_event_id"] is None

    # minutes_changed: the minutes side is re-extracted through the real write_events (delete + re-insert).
    def re_extract(mid, *, client):
        minutes = M.load_minutes(mid)
        evs = [ExtractedEvent(event_type="motion", scope="item", agenda_item_refs=[item], actor_text=None, actor_member_id=None,
                              summary="motion", detail={"action": "approve"}, segment_seq=None, page=1, quote=None),
               ExtractedEvent(event_type="vote", scope="item", agenda_item_refs=[item], actor_text=None, actor_member_id=None,
                              summary="vote", detail={"result": "passed"}, segment_seq=None, page=1, quote="said ordinance adopted"),
               ExtractedEvent(event_type="executive_session_motion", scope="item", agenda_item_refs=[item], actor_text=None,
                              actor_member_id=None, summary="exec",
                              detail={"stated_reason": "pending litigation, controversies not yet litigated"}, segment_seq=None,
                              page=1, quote="go into Executive Session at the recommendation of the City Attorney"),
               ExtractedEvent(event_type="adjourn", scope="meeting", agenda_item_refs=[], actor_text=None, actor_member_id=None,
                              summary="adjourn", detail={}, segment_seq=None, page=1, quote=adj_quote)]
        E.write_events(mid, "minutes", evs, minutes=minutes, roster=[], valid_item_ids={item})
        return "ok"
    monkeypatch.setattr(C, "extract_minutes_side", re_extract)

    out = C.run_compare_stage(_claim(pilot, reason="minutes_changed"), client=_client(verdicts))   # must not raise
    assert out.next_status == "compared"
    with db_cursor() as cur:
        cur.execute("""SELECT id, category, review_state, previous_review_state, transcript_event_id, minutes_event_id
                         FROM minutes_discrepancies WHERE id = ANY(%s)""", [list(before)])
        after = {r["id"]: dict(r) for r in cur.fetchall()}
        cur.execute("SELECT id FROM meeting_events WHERE meeting_id=%s AND source='minutes'", [pilot.meeting_id])
        new_minutes_ids = {r["id"] for r in cur.fetchall()}
    assert set(after) == set(before)                                    # nothing deleted
    for r in after.values():
        assert r["review_state"] == "stale" or (r["review_state"] == "proposed" and r["previous_review_state"] == "approved")
    add_after = after[addition["id"]]
    assert add_after["minutes_event_id"] is None or add_after["minutes_event_id"] in new_minutes_ids
    assert after[omission["id"]]["transcript_event_id"] == omission["transcript_event_id"]


def _wording_verdicts_only(info):
    """Second-pass judge: only the wording candidate is still real (same shape as the minutes-changed test above)."""
    def verdicts(user):
        out = []
        for cid in _ids_in_prompt(user):
            head = user.split(f"### Candidate {cid}")[1].split("\n")[0]
            real = "wording" in head
            out.append({"candidate_id": cid, "is_real": real, "category": "wording" if real else None, "severity": "material" if real else None,
                        "title": "wording title v2" if real else None, "description": "desc v2" if real else None,
                        "transcript_quote": info["exec_text"] if real else None, "minutes_quote": "go into Executive Session" if real else None,
                        "confidence": 0.9, "dismiss_reason": None if real else "now matches"})
        return out
    return verdicts


def _full_rows(mid):
    with db_cursor() as cur:
        cur.execute("""SELECT id, category, review_state, previous_review_state, reviewed_by, reviewed_at, title, prompt_version,
                              citation_match, transcript_excerpt
                         FROM minutes_discrepancies WHERE meeting_id=%s ORDER BY id""", [mid])
        return [dict(r) for r in cur.fetchall()]


def test_approved_rows_survive_an_unchanged_minutes_rerun(pilot):
    """Issue #112: a pass whose claim does not say minutes_changed (prompt bump, manual rerun) keeps every approved row."""
    from docket.services import discrepancies as D

    info = _seed_events(pilot)
    C.run_compare_stage(_claim(pilot), client=_client(_real_all(info)))
    first = _states(pilot.meeting_id)
    assert sorted(r["category"] for r in first) == ["sequence", "wording"]
    with db_cursor() as cur:   # the admin approves both; then a COMPARE_PROMPT_VERSION bump happens
        cur.execute("""UPDATE minutes_discrepancies SET review_state='approved', reviewed_at=now(), reviewed_by='t', prompt_version=%s
                        WHERE meeting_id=%s""", [C.COMPARE_PROMPT_VERSION - 1, pilot.meeting_id])
        cur.execute("UPDATE transcripts SET status='compared' WHERE id=%s", [pilot.transcript_id])
    approved_ids = {r["id"] for r in first}

    C.run_compare_stage(_claim(pilot), client=_client(_wording_verdicts_only(info)))     # reason None: minutes unchanged
    second = _full_rows(pilot.meeting_id)
    wording = next(r for r in second if r["category"] == "wording" and r["review_state"] != "dismissed_by_model")
    sequence = next(r for r in second if r["category"] == "sequence" and r["review_state"] != "dismissed_by_model")
    assert wording["id"] == next(r["id"] for r in first if r["category"] == "wording")      # refreshed in place, no duplicate
    assert wording["review_state"] == "approved" and wording["reviewed_by"] == "t" and wording["reviewed_at"] is not None
    assert wording["previous_review_state"] is None
    assert wording["title"] == "wording title v2" and wording["prompt_version"] == C.COMPARE_PROMPT_VERSION
    assert sequence["review_state"] == "approved" and sequence["reviewed_by"] == "t"        # the model's second opinion does not outrank a human
    assert sequence["prompt_version"] == C.COMPARE_PROMPT_VERSION - 1
    assert {r["id"] for r in D.list_public_for_meeting(pilot.meeting_id)} == approved_ids    # still on the public page
    assert not [r for r in second if r["review_state"] == "stale"]

    # The surviving approved row at the old version must not re-queue the meeting on every tick after the bump.
    P.advance(pilot.transcript_id, P.StageOutcome("compared"))
    assert P.reset_for_versions() == 0
    with db_cursor() as cur:
        cur.execute("SELECT status FROM transcripts WHERE id=%s", [pilot.transcript_id])
        assert cur.fetchone()["status"] == "compared"


def test_reconcile_minutes_changed_flag_decides_whether_approved_rows_go_stale(pilot):
    """Issue #112: reconcile stales approved rows only on a minutes_changed pass; a matched approved row keeps its verified citation."""
    info = _seed_events(pilot)
    mid = pilot.meeting_id
    with db_cursor() as cur:
        cur.execute("SELECT id, source, start_s FROM meeting_events WHERE meeting_id=%s AND event_type='executive_session_motion'", [mid])
        evs = {r["source"]: dict(r) for r in cur.fetchall()}
        t_ev, m_ev = evs["transcript"]["id"], evs["minutes"]["id"]
        cur.execute("""INSERT INTO minutes_discrepancies (meeting_id, agenda_item_id, category, severity, title, description,
                                                          transcript_event_id, minutes_event_id, transcript_excerpt, transcript_start_s,
                                                          citation_match, confidence, origin, review_state, reviewed_by, reviewed_at,
                                                          prompt_version)
                       VALUES (%s, %s, 'wording', 'material', 'original', 'd', %s, %s, %s, %s, 'exact', 0.9, 'aligner', 'approved', 't',
                               now(), %s) RETURNING id""",
                    [mid, info["item"], t_ev, m_ev, info["exec_text"], evs["transcript"]["start_s"], C.COMPARE_PROMPT_VERSION])
        rid = cur.fetchone()["id"]

    def row():
        return next(r for r in _full_rows(mid) if r["id"] == rid)

    C.reconcile(mid, [], minutes_changed=False)                   # unchanged minutes, nothing came back: approval stands
    assert row()["review_state"] == "approved" and row()["reviewed_by"] == "t"

    refreshed = {"meeting_id": mid, "agenda_item_id": info["item"], "category": "wording", "severity": "material", "title": "refreshed",
                 "description": "d2", "transcript_event_id": t_ev, "minutes_event_id": m_ev, "transcript_excerpt": "words nobody said",
                 "transcript_start_s": evs["transcript"]["start_s"], "minutes_excerpt": None, "minutes_page": None,
                 "citation_match": "missing", "confidence": 0.4, "origin": "aligner", "review_state": "proposed", "reject_reason": None,
                 "prompt_version": C.COMPARE_PROMPT_VERSION}
    assert set(refreshed) == set(C._COLS)
    C.reconcile(mid, [refreshed], minutes_changed=False)          # same finding came back with a quote the guard could not find
    r = row()
    assert r["review_state"] == "approved" and r["title"] == "refreshed"
    assert r["citation_match"] == "exact" and r["transcript_excerpt"] == info["exec_text"]   # an approved row never carries an unverified citation
    assert len([x for x in _full_rows(mid) if x["review_state"] != "dismissed_by_model"]) == 1

    C.reconcile(mid, [], minutes_changed=True)                    # the minutes PDF changed: today's stale-everything policy
    r = row()
    assert (r["review_state"], r["previous_review_state"], r["reviewed_by"]) == ("stale", "approved", "t")
