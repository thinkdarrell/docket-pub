# tests/integration/test_admin_discrepancies.py
"""Queue list, approve/reject/edit, citation and stale guards, CSRF, auth."""
import pytest

from docket.config import DATABASE_URL
from docket.db import db_cursor
from docket.services import discrepancies as D
from docket.web import create_app
from tests.support.transcript_fixtures import install_bundle, pilot_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)
TOK = "test-csrf-token"


@pytest.fixture(scope="module")
def app():
    a = create_app()
    a.config["TESTING"] = True
    return a


@pytest.fixture
def admin(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s["admin_user"] = "tester"
        s["csrf_token"] = TOK
    return c


@pytest.fixture
def pilot():
    i = install_bundle(pilot_bundle(), external_id="999015", status="compared")
    yield i
    i.cleanup()


def _event(mid, source, seq, et, item):
    with db_cursor() as cur:
        cur.execute("""INSERT INTO meeting_events (meeting_id, source, seq, event_type, scope, agenda_item_refs, summary, detail, prompt_version)
                       VALUES (%s, %s, %s, %s, 'item', %s, 'e', '{}', 200) RETURNING id""", [mid, source, seq, et, [item]])
        return cur.fetchone()["id"]


def _disc(inst, **kw):
    item = inst.item_ids[1501]
    t = _event(inst.meeting_id, "transcript", kw.pop("tseq", 1), "executive_session_motion", item)
    m = _event(inst.meeting_id, "minutes", kw.pop("mseq", 1), "executive_session_motion", item)
    row = {"meeting_id": inst.meeting_id, "agenda_item_id": item, "category": "wording", "severity": "material",
           "title": "Different statutory ground", "description": "Video cites (a)(4); minutes cite pending litigation.",
           "transcript_event_id": t, "minutes_event_id": m, "transcript_excerpt": "we will go into executive session",
           "transcript_start_s": 3400.0, "minutes_excerpt": "go into Executive Session", "minutes_page": 12,
           "citation_match": "exact", "confidence": 0.9, "origin": "aligner", "review_state": "proposed", "prompt_version": 200}
    row.update(kw)
    cols = list(row)
    with db_cursor() as cur:
        cur.execute(f"INSERT INTO minutes_discrepancies ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id",
                    [row[c] for c in cols])
        return cur.fetchone()["id"]


def _state(did):
    with db_cursor() as cur:
        cur.execute("SELECT review_state, reviewed_by, reject_reason, admin_title, admin_description, title, citation_match, transcript_excerpt FROM minutes_discrepancies WHERE id=%s", [did])
        return dict(cur.fetchone())


def test_queue_lists_material_first_with_both_excerpts_and_links(admin, pilot):
    minor = _disc(pilot, severity="minor", title="Minor wording", tseq=2, mseq=2)
    material = _disc(pilot)
    html = admin.get("/admin/review/discrepancies").get_data(as_text=True)
    assert html.index("Different statutory ground") < html.index("Minor wording")
    assert "we will go into executive session" in html and "go into Executive Session" in html
    assert "p. 12" in html and "00:56:40" in html                         # minutes page, transcript timestamp
    assert "MinutesViewer.php" in html and "meta_id=" not in html          # minutes link; chapter link needs numeric meta_id (pilot's is '1950-15')
    assert f"/admin/review/discrepancies/{material}/approve" in html


def test_filters_by_state_category_and_meeting(admin, pilot):
    _disc(pilot, review_state="dismissed_by_model", reject_reason="same words", title="Dismissed one")
    _disc(pilot, category="sequence", title="Sequence one", tseq=3, mseq=3)
    assert "Dismissed one" not in admin.get("/admin/review/discrepancies").get_data(as_text=True)
    assert "Dismissed one" in admin.get("/admin/review/discrepancies?state=dismissed_by_model").get_data(as_text=True)
    only_seq = admin.get("/admin/review/discrepancies?category=sequence").get_data(as_text=True)
    assert "Sequence one" in only_seq and "Different statutory ground" not in only_seq
    assert "Sequence one" in admin.get(f"/admin/review/discrepancies?meeting_id={pilot.meeting_id}").get_data(as_text=True)


def test_approve_sets_state_and_reviewer(admin, pilot):
    did = _disc(pilot)
    r = admin.post(f"/admin/review/discrepancies/{did}/approve", data={"csrf_token": TOK})
    assert r.status_code in (302, 303) and "/admin/review/discrepancies" in r.headers["Location"]
    s = _state(did)
    assert s["review_state"] == "approved" and s["reviewed_by"] == "tester"
    assert "approved" in admin.get("/admin/review/discrepancies").get_data(as_text=True).lower()


def test_missing_citation_cannot_be_approved_until_attached(admin, pilot):
    did = _disc(pilot, citation_match="missing", transcript_excerpt="words nobody said", confidence=0.4)
    html = admin.get("/admin/review/discrepancies").get_data(as_text=True)
    assert "disabled" in html.split(f"/discrepancies/{did}/approve")[0][-400:]           # Review Focus 2: button disabled
    r = admin.post(f"/admin/review/discrepancies/{did}/approve", data={"csrf_token": TOK})
    assert r.status_code in (302, 303) and _state(did)["review_state"] == "proposed"
    assert "attach a citation" in admin.get("/admin/review/discrepancies").get_data(as_text=True)   # flashed, not an error page
    # Reviewer attaches a transcript excerpt that the guard can find in the pilot transcript.
    r = admin.post(f"/admin/review/discrepancies/{did}/edit-approve",
                   data={"csrf_token": TOK, "admin_title": "Statutory ground differs", "admin_description": "Edited.",
                         "transcript_excerpt": "executive session", "minutes_excerpt": "go into Executive Session"})
    assert r.status_code in (302, 303)
    s = _state(did)
    assert s["review_state"] == "approved" and s["citation_match"] in ("exact", "fuzzy")
    assert s["admin_title"] == "Statutory ground differs" and s["title"] == "Different statutory ground"   # model text kept
    bad = _disc(pilot, citation_match="missing", tseq=5, mseq=5)
    r = admin.post(f"/admin/review/discrepancies/{bad}/edit-approve",
                   data={"csrf_token": TOK, "admin_title": "x", "admin_description": "y", "transcript_excerpt": "not in there at all"})
    assert r.status_code in (302, 303) and _state(bad)["review_state"] == "proposed"
    assert "not found in the transcript" in admin.get("/admin/review/discrepancies").get_data(as_text=True)


def test_stale_row_cannot_be_approved(admin, pilot):
    did = _disc(pilot, review_state="stale")
    r = admin.post(f"/admin/review/discrepancies/{did}/approve", data={"csrf_token": TOK})   # Review Focus 3
    assert r.status_code in (302, 303) and _state(did)["review_state"] == "stale"
    assert "row is stale" in admin.get("/admin/review/discrepancies?state=stale").get_data(as_text=True)
    assert "Different statutory ground" in admin.get("/admin/review/discrepancies?state=stale").get_data(as_text=True)


def test_reject_requires_reason(admin, pilot):
    did = _disc(pilot)
    assert admin.post(f"/admin/review/discrepancies/{did}/reject", data={"csrf_token": TOK}).status_code == 400
    r = admin.post(f"/admin/review/discrepancies/{did}/reject", data={"csrf_token": TOK, "reason": "same action, different words"})
    assert r.status_code in (302, 303)
    s = _state(did)
    assert s["review_state"] == "rejected" and s["reject_reason"] == "same action, different words"


def test_csrf_and_login_are_enforced(app, admin, pilot):
    did = _disc(pilot)
    assert admin.post(f"/admin/review/discrepancies/{did}/approve").status_code == 400                      # no token
    anon = app.test_client()
    r = anon.post(f"/admin/review/discrepancies/{did}/approve", data={"csrf_token": TOK})
    assert r.status_code in (302, 303) and "/admin/login" in r.headers["Location"]
    assert anon.get("/admin/review/discrepancies").status_code in (302, 303)
    assert _state(did)["review_state"] == "proposed"


def test_held_tab_lists_transcripts_and_retry_resets_them(admin, pilot):
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status='needs_review', needs_review_reason='candidate_cap', last_error='44 candidates' WHERE id=%s",
                    [pilot.transcript_id])
    html = admin.get("/admin/review/discrepancies?state=held").get_data(as_text=True)
    assert "candidate_cap" in html and "44 candidates" in html
    r = admin.post(f"/admin/transcripts/{pilot.meeting_id}/retry", data={"csrf_token": TOK})
    assert r.status_code in (302, 303)
    with db_cursor() as cur:
        cur.execute("SELECT status, stage_attempts, needs_review_reason FROM transcripts WHERE id=%s", [pilot.transcript_id])
        row = cur.fetchone()
    assert row["status"] == "uploaded" and row["stage_attempts"] == 0 and row["needs_review_reason"] is None  # no resolved speakers, no events -> start over


def test_public_reads_return_only_approved(pilot):
    a = _disc(pilot, review_state="approved")
    _disc(pilot, review_state="proposed", tseq=2, mseq=2)
    _disc(pilot, review_state="stale", tseq=3, mseq=3)
    rows = D.list_public_for_meeting(pilot.meeting_id)
    assert [r["id"] for r in rows] == [a]
    assert D.list_public_for_item(pilot.item_ids[1501])[0]["id"] == a
    assert any(r["id"] == a for r in D.list_public_recent())
