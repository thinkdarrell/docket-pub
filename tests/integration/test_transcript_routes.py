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


def test_htmx_partial_uses_namespaced_item_ids(client, meeting_with_transcript):
    fx = meeting_with_transcript; _publish(fx["transcript_id"])
    url = f"/al/birmingham/meetings/{fx['meeting_id']}/transcript/"
    part = client.get(url, headers={"HX-Request": "true"}).get_data(as_text=True)
    assert f'id="tr-item-{fx["item_id"]}"' in part
    assert f'id="item-{fx["item_id"]}"' not in part
    full = client.get(url).get_data(as_text=True)
    assert f'id="item-{fx["item_id"]}"' in full


def test_history_restore_gets_full_page_and_vary(client, meeting_with_transcript):
    fx = meeting_with_transcript; _publish(fx["transcript_id"])
    url = f"/al/birmingham/meetings/{fx['meeting_id']}/transcript/"
    r = client.get(url, headers={"HX-Request": "true", "HX-History-Restore-Request": "true"})
    assert "<html" in r.get_data(as_text=True)
    assert "HX-Request" in r.headers.get("Vary", "")
    assert "HX-Request" in client.get(url).headers.get("Vary", "")
    assert "HX-Request" in client.get(url, headers={"HX-Request": "true"}).headers.get("Vary", "")


def test_item_page_shows_excerpt_with_read_more(client, meeting_with_transcript):
    fx = meeting_with_transcript; _publish(fx["transcript_id"])
    html = client.get(f"/al/birmingham/items/{fx['item_id']}/").get_data(as_text=True)
    assert "From the video" in html
    assert "Item fifteen. I would like a summary." in html
    assert f"/al/birmingham/meetings/{fx['meeting_id']}/transcript/#t-0" in html


def test_item_page_without_segments_has_no_excerpt_block(client, meeting_with_transcript):
    fx = meeting_with_transcript; _publish(fx["transcript_id"])
    with db_cursor() as cur:
        cur.execute("""INSERT INTO agenda_items (meeting_id, item_number, title)
                       VALUES (%s, '16', 'Nothing said') RETURNING id""", [fx["meeting_id"]])
        other = cur.fetchone()["id"]
    html = client.get(f"/al/birmingham/items/{other}/").get_data(as_text=True)
    assert "From the video" not in html


def test_item_page_no_excerpt_when_transcript_not_public(client, meeting_with_transcript):
    fx = meeting_with_transcript
    html = client.get(f"/al/birmingham/items/{fx['item_id']}/").get_data(as_text=True)
    assert "From the video" not in html


def test_item_excerpt_speaker_numbers_match_full_page(client, meeting_with_transcript):
    # S0 (O'Quinn) is cluster 1 and S1 is cluster 2 in the fixture; a later item
    # whose only voice is a new cluster S2 must read "Speaker 3", not "Speaker 1".
    fx = meeting_with_transcript; _publish(fx["transcript_id"])
    with db_cursor() as cur:
        cur.execute("""INSERT INTO agenda_items (meeting_id, item_number, title)
                       VALUES (%s, '17', 'Later item') RETURNING id""", [fx["meeting_id"]])
        later = cur.fetchone()["id"]
        cur.execute("""INSERT INTO transcript_segments
                         (transcript_id, seq, start_s, end_s, text, cluster_label, agenda_item_id)
                       VALUES (%s, 3, 4000.0, 4004.0, 'Point of order.', 'S2', %s)""",
                    [fx["transcript_id"], later])
    item_html = client.get(f"/al/birmingham/items/{later}/").get_data(as_text=True)
    page_html = client.get(f"/al/birmingham/meetings/{fx['meeting_id']}/transcript/").get_data(as_text=True)
    assert "Speaker 3" in item_html and "Speaker 1" not in item_html
    assert "Speaker 3" in page_html
