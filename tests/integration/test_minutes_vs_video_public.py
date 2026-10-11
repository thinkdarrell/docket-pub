import pytest

from docket.config import DATABASE_URL
from docket.db import db_cursor
from docket.services import transcripts as tsvc
from docket.web import create_app
from tests.integration.test_admin_discrepancies import _disc
from tests.support.transcript_fixtures import install_bundle, load_bundle, pilot_bundle

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)
HONESTY = "The minutes remain the official record"


@pytest.fixture
def app():
    a = create_app(); a.config["TESTING"] = True
    return a


@pytest.fixture
def pilot():
    i = install_bundle(pilot_bundle(), external_id="999015", status="compared")
    yield i
    i.cleanup()


def test_flag_off_hides_block_and_listing(app, pilot):
    app.config["MINUTES_VS_VIDEO_UI"] = False
    _disc(pilot, review_state="approved")
    c = app.test_client()
    html = c.get(f"/al/birmingham/meetings/{pilot.meeting_id}/").get_data(as_text=True)
    assert "Minutes vs. video" not in html and "Different statutory ground" not in html
    assert c.get("/minutes-vs-video/").status_code == 404


def test_flag_on_renders_only_approved_rows_with_honesty_copy(app, pilot):
    app.config["MINUTES_VS_VIDEO_UI"] = True
    _disc(pilot, review_state="approved", admin_title="Statutory ground differs (edited)")
    _disc(pilot, review_state="proposed", title="Proposed one", tseq=2, mseq=2)
    _disc(pilot, review_state="stale", title="Stale one", tseq=3, mseq=3)
    c = app.test_client()
    html = c.get(f"/al/birmingham/meetings/{pilot.meeting_id}/").get_data(as_text=True)
    assert "Minutes vs. video" in html and "Statutory ground differs (edited)" in html
    assert "Proposed one" not in html and "Stale one" not in html
    assert "we will go into executive session" in html and "go into Executive Session" in html
    assert HONESTY in html and "/about/how-we-read-minutes/" in html and "reviewed by a person" in html
    assert "p. 12" in html and "56:40" in html
    item_html = c.get(f"/al/birmingham/items/{pilot.item_ids[1501]}/").get_data(as_text=True)
    assert "Statutory ground differs (edited)" in item_html and "Proposed one" not in item_html
    listing = c.get("/minutes-vs-video/").get_data(as_text=True)
    assert "Statutory ground differs (edited)" in listing and HONESTY in listing


def test_flag_on_with_nothing_approved_renders_no_section(app, pilot):
    app.config["MINUTES_VS_VIDEO_UI"] = True
    _disc(pilot, review_state="proposed")
    html = app.test_client().get(f"/al/birmingham/meetings/{pilot.meeting_id}/").get_data(as_text=True)
    assert "Minutes vs. video" not in html


def test_speaker_index_merges_clusters_by_person_and_links_search(app):
    inst = install_bundle(load_bundle("transcript_2543"), status="speakers_resolved")
    try:
        with db_cursor() as cur:
            cur.execute("SELECT cluster_label FROM transcript_speakers WHERE meeting_id=%s ORDER BY cluster_label LIMIT 3", [inst.meeting_id])
            a, b, c3 = [r["cluster_label"] for r in cur.fetchall()]
            cur.execute("SELECT id FROM council_members WHERE id = ANY(%s) AND name NOT LIKE %s ORDER BY id LIMIT 1",
                        [list(inst.member_ids.values()), "%''%"])      # autoescape would turn an apostrophe into &#39;
            member = cur.fetchone()["id"]
            cur.execute("""UPDATE transcript_speakers SET council_member_id=%s, confidence=0.75, method='roll_call' WHERE meeting_id=%s AND cluster_label=%s""",
                        [member, inst.meeting_id, a])
            cur.execute("""UPDATE transcript_speakers SET council_member_id=%s, confidence=1.0, method='manual', is_manual=TRUE WHERE meeting_id=%s AND cluster_label=%s""",
                        [member, inst.meeting_id, b])                                              # Review Focus 4: one by model, one by hand
            cur.execute("""UPDATE transcript_speakers SET display_name='Low Conf', confidence=0.4, method='llm_inference' WHERE meeting_id=%s AND cluster_label=%s""",
                        [inst.meeting_id, c3])
            cur.execute("SELECT name FROM council_members WHERE id=%s", [member]); name = cur.fetchone()["name"]
        idx = tsvc.speaker_index(inst.transcript_id)
        assert [e["name"] for e in idx] == [name]                      # merged, low-confidence cluster excluded
        assert set(idx[0]["cluster_labels"]) == {a, b} and idx[0]["turns"] > 0
        html = app.test_client().get(f"/al/birmingham/meetings/{inst.meeting_id}/transcript/").get_data(as_text=True)
        assert "Who spoke" in html and html.count(f">{name}<") >= 1
        import html as _html, urllib.parse as _up
        decoded = _up.unquote(_html.unescape(html))   # urlencode renders spaces as %20, not +
        assert f'/search?city=birmingham&q=speaker:"{name}"' in decoded
        search = app.test_client().get(f'/search?city=birmingham&q=speaker:"{name}"').get_data(as_text=True)
        assert "From transcripts" in search
    finally:
        inst.cleanup()


def test_methodology_page_describes_transcripts_and_comparison(app):
    html = app.test_client().get("/about/how-we-read-minutes/").get_data(as_text=True)
    assert "Transcripts" in html and "Minutes vs. video" in html and HONESTY in html
