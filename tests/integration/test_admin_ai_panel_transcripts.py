import pytest

from docket.config import DATABASE_URL
from docket.db import db_cursor
from docket.web import create_app

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Refusing to run against Railway DB.",
)


def test_panel_shows_gate_stage_costs_and_statuses():
    app = create_app(); app.config["TESTING"] = True; app.config["MINUTES_VS_VIDEO_UI"] = False
    c = app.test_client()
    with c.session_transaction() as s:
        s["admin_user"] = "tester"
    with db_cursor() as cur:
        cur.execute("""INSERT INTO ai_runs (started_at, finished_at, stage, model, rows_processed, rows_failed, cost_usd, notes)
                       VALUES (now(), now(), 'transcript_compare', 'claude-opus-5-5', 1, 0, 0.4321, 'pytest_panel') RETURNING id""")
        rid = cur.fetchone()["id"]
    try:
        html = c.get("/admin/ai").get_data(as_text=True)
        assert "Minutes vs. video gate" in html and "flag off" in html
        assert "transcript_compare" in html and "0.4321" in html
        assert "Transcript pipeline" in html            # status table heading
        assert "citation" in html.lower()
    finally:
        with db_cursor() as cur:
            cur.execute("DELETE FROM ai_runs WHERE id=%s", [rid])
