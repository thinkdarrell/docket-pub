"""Transcript page: 404 until uploaded, full page vs HTMX partial, anchors, label."""
import html as htmllib
import pytest
from datetime import date
from docket.config import DATABASE_URL
from docket.db import db, db_cursor
from docket.web import create_app

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def meeting_with_transcript():
    with db_cursor() as cur:
        cur.execute("SELECT id FROM municipalities WHERE slug='birmingham'")
        muni = cur.fetchone()["id"]
        cur.execute("""INSERT INTO meetings (municipality_id, title, meeting_date, external_id, video_url)
                       VALUES (%s, 'TR test', %s, '999902',
                               'https://bhamal.granicus.com/MediaPlayer.php?view_id=2&clip_id=999902')
                       RETURNING id""", [muni, date(2026, 9, 2)])
        mid = cur.fetchone()["id"]
        cur.execute("INSERT INTO processing_status (meeting_id) VALUES (%s)", [mid])
        cur.execute("""INSERT INTO agenda_items (meeting_id, item_number, title, external_id)
                       VALUES (%s, '15', 'ALEA agreement', '77001') RETURNING id""", [mid])
        item = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcripts (meeting_id, status, version, asr_model, word_count)
                       VALUES (%s, 'claimed', 1, 'large-v3', 0) RETURNING id""", [mid])
        tid = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcript_speakers (meeting_id, cluster_label, display_name, confidence)
                       VALUES (%s, 'S0', 'Darrell O''Quinn', 0.9) RETURNING id""", [mid])
        sid = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcript_segments
                         (transcript_id, seq, start_s, end_s, text, cluster_label, speaker_id, agenda_item_id)
                       VALUES (%s, 0, 3309.0, 3312.0, 'Item fifteen.', 'S0', %s, %s),
                              (%s, 1, 3312.0, 3320.0, 'I would like a summary.', 'S0', %s, %s),
                              (%s, 2, 3320.0, 3325.0, 'Sure.', 'S1', NULL, %s)""",
                    [tid, sid, item, tid, sid, item, tid, item])
    yield {"meeting_id": mid, "transcript_id": tid, "item_id": item}
    with db_cursor() as cur:
        cur.execute("DELETE FROM meetings WHERE id = %s", [mid])


def _publish(tid):
    with db_cursor() as cur:
        cur.execute("UPDATE transcripts SET status='uploaded', uploaded_at=now() WHERE id=%s", [tid])


def test_404_while_not_public(client, meeting_with_transcript):
    mid = meeting_with_transcript["meeting_id"]
    assert client.get(f"/al/birmingham/meetings/{mid}/transcript/").status_code == 404
    page = client.get(f"/al/birmingham/meetings/{mid}/").get_data(as_text=True)
    assert "/transcript/" not in page


def test_full_page_renders_label_turns_and_anchors(client, meeting_with_transcript):
    fx = meeting_with_transcript; _publish(fx["transcript_id"])
    r = client.get(f"/al/birmingham/meetings/{fx['meeting_id']}/transcript/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Machine-generated transcript" in html and "large-v3" in html
    assert 'id="t-0"' in html and 'id="t-2"' in html and 'id="t-1"' not in html
    assert "Darrell O'Quinn" in htmllib.unescape(html) and "Speaker 2" in html
    assert f'id="item-{fx["item_id"]}"' in html
    assert "55:09" in html                      # 3309 s formatted by format_timestamp
    assert "/about/how-we-read-minutes/" in html
    assert "<html" in html


def test_htmx_request_returns_partial_only(client, meeting_with_transcript):
    fx = meeting_with_transcript; _publish(fx["transcript_id"])
    r = client.get(f"/al/birmingham/meetings/{fx['meeting_id']}/transcript/",
                   headers={"HX-Request": "true"})
    html = r.get_data(as_text=True)
    assert "<html" not in html and 'id="t-0"' in html


def test_meeting_page_links_to_transcript_with_hx_attrs(client, meeting_with_transcript):
    fx = meeting_with_transcript; _publish(fx["transcript_id"])
    html = client.get(f"/al/birmingham/meetings/{fx['meeting_id']}/").get_data(as_text=True)
    assert f'href="/al/birmingham/meetings/{fx["meeting_id"]}/transcript/"' in html
    assert 'hx-get="/al/birmingham/meetings/' in html and 'hx-push-url="true"' in html
