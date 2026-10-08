import pytest
from datetime import date
from docket.config import DATABASE_URL
from docket.db import db_cursor
from docket.services import transcripts as tsvc
from docket.web import create_app

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


@pytest.fixture(scope="module")
def client():
    app = create_app(); app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def searchable():
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, external_id, video_url)
                       VALUES (%s, 'TS test', %s, '999903', 'https://x/v') RETURNING id""",
                    [muni, date(2026, 9, 3)])
        mid = cur.fetchone()["id"]
        cur.execute("INSERT INTO processing_status (meeting_id) VALUES (%s)", [mid])
        cur.execute("""INSERT INTO transcripts (meeting_id, status, uploaded_at) VALUES (%s, 'uploaded', now())
                       RETURNING id""", [mid])
        tid = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcript_speakers (meeting_id, cluster_label, display_name, confidence)
                       VALUES (%s, 'S0', 'Darrell O''Quinn', 0.95) RETURNING id""", [mid])
        sid = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcript_segments (transcript_id, seq, start_s, end_s, text, cluster_label, speaker_id)
                       VALUES (%s, 0, 10, 14, 'the agreement is not in the packet', 'S0', %s),
                              (%s, 1, 14, 17, 'the packet contract was amended', 'S0', %s),
                              (%s, 2, 17, 20, 'license plate reader cameras give access', 'S1', NULL),
                              (%s, 3, 20, 90, '', NULL, NULL)""", [tid, sid, tid, sid, tid, tid])
        cur.execute("UPDATE transcript_segments SET is_silence = TRUE WHERE transcript_id=%s AND seq=3", [tid])
    yield {"meeting_id": mid}
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id = %s", [mid])


def test_text_search_returns_headline_and_anchor(searchable):
    rows = tsvc.search_transcripts("license plate", municipality_slug="birmingham", speaker=None)
    hit = next(r for r in rows if r["meeting_id"] == searchable["meeting_id"])
    assert "<mark>license</mark>" in hit["headline"]
    assert hit["anchor_url"].endswith(f"/meetings/{searchable['meeting_id']}/transcript/#t-2")


def test_speaker_filter_with_text(searchable):
    rows = tsvc.search_transcripts("packet", municipality_slug="birmingham", speaker="oquinn")
    assert [r["seq"] for r in rows if r["meeting_id"] == searchable["meeting_id"]] == [0, 1]


def test_speaker_only_query_has_no_sql_error_and_returns_turns(searchable):
    rows = tsvc.search_transcripts("", municipality_slug="birmingham", speaker="O'Quinn")
    assert any(r["meeting_id"] == searchable["meeting_id"] and r["seq"] == 0 for r in rows)


def test_headline_escapes_html_in_transcript_text(searchable):
    with db_cursor() as cur:
        cur.execute("SELECT id FROM transcripts WHERE meeting_id=%s", [searchable["meeting_id"]])
        tid = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcript_segments (transcript_id, seq, start_s, end_s, text, cluster_label)
                       VALUES (%s, 4, 95, 99, 'fee is <b>less</b> than 5 & <script>x</script> per license', 'S1')""",
                    [tid])
    # ts_headline path
    rows = tsvc.search_transcripts("license", municipality_slug="birmingham", speaker=None)
    hit = next(r for r in rows if r["meeting_id"] == searchable["meeting_id"] and r["seq"] == 4)
    assert "<script>" not in hit["headline"] and "&lt;script&gt;" in hit["headline"]
    assert "&amp;" in hit["headline"] and "<mark>license</mark>" in hit["headline"]
    # left(text, 240) fallback path
    rows = tsvc.search_transcripts("", municipality_slug="birmingham", speaker=None)
    hit = next(r for r in rows if r["meeting_id"] == searchable["meeting_id"] and r["seq"] == 4)
    assert "<script>" not in hit["headline"] and "&lt;b&gt;less&lt;/b&gt;" in hit["headline"]


def test_search_page_renders_transcript_section(client, searchable):
    html = client.get("/search?q=license+plate&city=birmingham").get_data(as_text=True)
    assert "From transcripts" in html
    assert f"/meetings/{searchable['meeting_id']}/transcript/#t-2" in html


def test_mid_turn_hit_anchor_exists_on_page(client, searchable):
    mid = searchable["meeting_id"]
    rows = tsvc.search_transcripts("amended", municipality_slug="birmingham", speaker=None)
    hit = next(r for r in rows if r["meeting_id"] == mid)
    assert hit["anchor_url"].endswith("#t-1")
    fragment = hit["anchor_url"].split("#", 1)[1]
    page = client.get(f"/al/birmingham/meetings/{mid}/transcript/").get_data(as_text=True)
    assert f'id="{fragment}"' in page
