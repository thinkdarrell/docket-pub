import importlib.util, pathlib
import pytest
from docket.config import DATABASE_URL
from docket.db import db, db_cursor

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Never run the synthetic fill against Railway.",
)

spec = importlib.util.spec_from_file_location(
    "scale_check", pathlib.Path("scripts/transcript_scale_check.py"))
scale_check = importlib.util.module_from_spec(spec); spec.loader.exec_module(scale_check)


def _count():
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM transcript_segments WHERE text LIKE 'SYNTH %'")
        return cur.fetchone()["n"]


def test_scale_check_runs_and_leaves_nothing_behind():
    before = _count()
    with db() as conn:
        result = scale_check.run_scale_check(conn, rows=5000)
    assert result["page_ms"] >= 0 and result["search_ms"] >= 0
    assert "Execution Time" in result["search_plan"] and "Execution Time" in result["page_plan"]
    assert "ANALYZE" in result["log"]
    # Index usage is asserted by eye on the 1M-row run (Step 5); at 5,000 rows a
    # sequential scan is a legitimate planner choice.
    assert _count() == before
