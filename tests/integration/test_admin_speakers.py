# tests/integration/test_admin_speakers.py
import pytest

from docket.config import DATABASE_URL
from docket.db import db_cursor
from docket.services import speaker_correction as SC
from docket.web import create_app
from tests.support.transcript_fixtures import install_bundle, load_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)
TOK = "test-csrf-token"


@pytest.fixture(scope="module")
def app():
    a = create_app(); a.config["TESTING"] = True
    return a


@pytest.fixture
def admin(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s["admin_user"] = "tester"; s["csrf_token"] = TOK
    return c


@pytest.fixture
def inst():
    i = install_bundle(load_bundle("transcript_2543"), status="speakers_resolved")
    yield i
    i.cleanup()


def _row(mid, label):
    with db_cursor() as cur:
        cur.execute("SELECT council_member_id, display_name, role, confidence, method, is_manual, needs_review FROM transcript_speakers WHERE meeting_id=%s AND cluster_label=%s",
                    [mid, label])
        return dict(cur.fetchone())


def test_page_lists_every_cluster_with_samples_and_roster(admin, inst):
    clusters = SC.list_clusters(inst.meeting_id)
    assert len(clusters) >= 20 and clusters[0]["ordinal"] == 1
    assert all(1 <= len(c["samples"]) <= 3 for c in clusters if c["utterances"])
    html = admin.get(f"/admin/transcripts/{inst.meeting_id}/speakers").get_data(as_text=True)
    for c in clusters:
        assert f"Speaker {c['ordinal']}" in html and c["cluster_label"] in html
    assert "<option" in html and any(m["name"] in html for m in SC.roster_options(inst.meeting_id))


def test_reassign_two_clusters_to_one_member_sets_manual(admin, inst):
    labels = [c["cluster_label"] for c in SC.list_clusters(inst.meeting_id)][:2]
    member = SC.roster_options(inst.meeting_id)[0]
    for l in labels:
        r = admin.post(f"/admin/transcripts/{inst.meeting_id}/speakers/{l}",
                       data={"csrf_token": TOK, "council_member_id": member["id"], "role": "council"})
        assert r.status_code in (302, 303)
    for l in labels:
        row = _row(inst.meeting_id, l)
        assert row["council_member_id"] == member["id"] and row["is_manual"] and row["method"] == "manual"
        assert row["confidence"] == 1.0 and row["needs_review"] is False and row["display_name"] == member["name"]


def test_free_text_name_for_non_council_and_release(admin, inst):
    label = SC.list_clusters(inst.meeting_id)[3]["cluster_label"]
    r = admin.post(f"/admin/transcripts/{inst.meeting_id}/speakers/{label}",
                   data={"csrf_token": TOK, "council_member_id": "", "display_name": "City Attorney", "role": "attorney"})
    assert r.status_code in (302, 303)
    row = _row(inst.meeting_id, label)
    assert (row["display_name"], row["role"], row["is_manual"], row["council_member_id"]) == ("City Attorney", "attorney", True, None)
    r = admin.post(f"/admin/transcripts/{inst.meeting_id}/speakers/{label}/release", data={"csrf_token": TOK})
    assert r.status_code in (302, 303)
    row = _row(inst.meeting_id, label)
    assert row["is_manual"] is False and row["needs_review"] is True and row["display_name"] == "City Attorney"


def test_member_outside_roster_and_bad_role_are_400(admin, inst):
    label = SC.list_clusters(inst.meeting_id)[0]["cluster_label"]
    assert admin.post(f"/admin/transcripts/{inst.meeting_id}/speakers/{label}",
                      data={"csrf_token": TOK, "council_member_id": 999999, "role": "council"}).status_code == 400
    assert admin.post(f"/admin/transcripts/{inst.meeting_id}/speakers/{label}",
                      data={"csrf_token": TOK, "display_name": "X", "role": "wizard"}).status_code == 400
    assert admin.post(f"/admin/transcripts/{inst.meeting_id}/speakers/NOPE", data={"csrf_token": TOK, "display_name": "X", "role": "staff"}).status_code == 404
    assert admin.post(f"/admin/transcripts/{inst.meeting_id}/speakers/{label}", data={"display_name": "X", "role": "staff"}).status_code == 400  # CSRF


def test_transcript_page_shows_the_corrected_name(admin, inst):
    c = SC.list_clusters(inst.meeting_id)[0]
    SC.reassign(inst.meeting_id, c["cluster_label"], council_member_id=None, display_name="Zelda Testname", role="staff", actor="t")
    html = admin.get(f"/al/birmingham/meetings/{inst.meeting_id}/transcript/").get_data(as_text=True)
    assert "Zelda Testname" in html
