"""The pilot fixture is present, parseable, and names the two expected discrepancies."""
import json
from pathlib import Path

FIX = Path("tests/fixtures/transcript_pilot")


def test_fixture_files_present():
    for name in (
        "2026-02-17_clip1950_item15_small-en.srt",
        "2026-02-17_clip1950_item15_small-en.txt",
        "2026-02-17_clip1950_minutes.txt",
        "expected.json",
        "README.md",
    ):
        assert (FIX / name).exists(), name


def test_expected_names_two_material_discrepancies():
    exp = json.loads((FIX / "expected.json").read_text())
    assert exp["meeting_id"] == 15
    assert exp["granicus_clip_id"] == 1950
    cats = sorted(d["category"] for d in exp["discrepancies"])
    assert cats == ["sequence", "wording"]
    assert all(d["severity"] == "material" for d in exp["discrepancies"])
    wording = next(d for d in exp["discrepancies"] if d["category"] == "wording")
    assert "36-25A-7(a)(4)" in wording["transcript_must_contain"]
    assert "pending litigation" in wording["minutes_must_contain"]


def test_minutes_text_contains_exec_session_passage():
    text = (FIX / "2026-02-17_clip1950_minutes.txt").read_text()
    assert "go into Executive Session" in text
    assert "pending litigation" in text
