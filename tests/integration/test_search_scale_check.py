"""The search scale check: it times the ranked statement on synthetic rows and leaves none behind.

Plan: plans/active/search-finds-what-was-said.md (M6). The 60,000-row run
and its promotion rule are the session's and the operator's; this file runs
2,000 rows and proves the check measures what its line says and cleans up.

The script is loaded inside a helper, not at the top of this file, so the
file collects before the script exists.
"""
import functools
import importlib.util
import pathlib
import re

import pytest

from docket.config import DATABASE_URL
from docket.db import db, db_cursor

pytestmark = pytest.mark.skipif(
    any(h in DATABASE_URL for h in ("railway.internal", "railway.app", "rlwy.net")),
    reason="Never run the synthetic fill against Railway.",
)

REPO = pathlib.Path(__file__).resolve().parents[2]
ROWS = 2000


@functools.lru_cache(maxsize=1)
def _script():
    spec = importlib.util.spec_from_file_location("search_scale_check", REPO / "scripts" / "search_scale_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _synthetic_counts() -> tuple[int, int]:
    with db_cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM agenda_items WHERE title LIKE 'SYNTH %'")
        items = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM meetings WHERE title = 'SYNTH search scale'")
        return items, cur.fetchone()["n"]


@pytest.fixture(scope="module")
def result():
    """One 2,000-row run, with the synthetic counts read before and after it."""
    before = _synthetic_counts()
    with db() as conn:
        out = _script().run_scale_check(conn, ROWS)
    return {"before": before, "after": _synthetic_counts(), "out": out}


def test_the_check_leaves_no_synthetic_row_behind(result):
    assert result["before"] == (0, 0)
    assert result["after"] == (0, 0)


def test_the_synthetic_rows_are_of_a_production_rows_order_of_size(result):
    out = result["out"]
    assert out["rows"] == ROWS
    assert out["vector_median_bytes"] >= 1000
    assert out["vector_p95_bytes"] >= out["vector_median_bytes"]


def test_the_three_queries_are_timed_and_each_finds_rows(result):
    out = result["out"]
    assert list(out["timings_ms"]) == ["rare-word", "three-word", "common-words"]
    assert all(ms > 0 for ms in out["timings_ms"].values())
    # The rare word is planted in a handful of rows; the other two queries fill a page.
    assert 1 <= out["returned"]["rare-word"] <= 20
    assert out["returned"]["three-word"] == 20
    assert out["returned"]["common-words"] == 20
    # Nearly every row is a candidate of the worst case, and few are of the rare word.
    assert out["candidates"]["common-words"] >= 0.9 * ROWS
    assert out["candidates"]["rare-word"] < 0.05 * ROWS


def test_the_line_states_the_rows_the_sizes_and_the_timings(result):
    line = _script().format_line(result["out"])
    assert re.fullmatch(
        r"scale: 2000 rows; vector median \d+(\.\d)? kB, p95 \d+(\.\d)? kB; "
        r"rare-word \d+ ms; three-word \d+ ms; common-words \d+ ms",
        line), line


def test_the_description_length_is_a_parameter(result):
    """Narrower descriptions make smaller vectors, which is what the operator turns if production's are larger."""
    with db() as conn:
        short = _script().run_scale_check(conn, 300, desc_words=(5, 10))
    assert short["vector_median_bytes"] < result["out"]["vector_median_bytes"]
    assert _synthetic_counts() == (0, 0)


@pytest.mark.parametrize("argv", [["--rows", "0"], ["--rows", "100", "--desc-words", "400-40"],
                                  ["--rows", "100", "--desc-words", "forty"]])
def test_the_command_refuses_a_bound_that_means_nothing(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        _script().main(argv)
    assert exc.value.code == 2
    assert _synthetic_counts() == (0, 0)


def test_the_command_refuses_a_railway_database(monkeypatch, capsys):
    script = _script()
    monkeypatch.setattr(script, "DATABASE_URL", "postgresql://u:p@postgres.railway.internal:5432/railway")
    assert script.main(["--rows", "100"]) == 2
    assert "Railway" in capsys.readouterr().err
