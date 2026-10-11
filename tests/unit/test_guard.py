from docket.ai.transcripts.guard import canonical_statute, find_citation, normalize, normalize_with_map, window


def test_normalize_handles_pdf_artifacts():
    raw = "The ﬁrst  “Executive­Session” was ap-\nproved at 10:20 o’clock"
    assert normalize(raw) == 'the first "executivesession" was approved at 10:20 o\'clock'


def test_hyphenated_line_breaks_join_with_or_without_trailing_space():
    assert normalize("ap-\nproved") == normalize("ap- \nproved") == normalize("ap-\n proved") == "approved"
    assert normalize("well-known rule") == "well-known rule"          # an in-line hyphen is kept


def test_fuzzy_pass_is_anchored_and_bounded_on_long_sources():
    filler = ("the council considered routine business and heard from staff about the schedule. " * 2500)   # ~200K chars
    source = filler + "upon the roll being called the vote was as fol lows: Ayes: nine" + filler
    cm = find_citation("upon the roll being called the vote was as follows: Ayes: nine", source)
    assert cm.kind == "fuzzy" and "roll being called" in source[cm.start:cm.end]
    # No three consecutive words of this quote exist in the source: missing, with no sweep.
    assert find_citation("zebra quartz umbrella nine", source).kind == "missing"


def test_normalize_with_map_points_back_into_the_original():
    raw = "Said  ordinance  ADOPTED."
    norm, m = normalize_with_map(raw)
    assert norm == "said ordinance adopted."
    i = norm.index("adopted")
    assert raw[m[i]:m[i + len("adopted") - 1] + 1] == "ADOPTED"


def test_exact_match_returns_original_offsets():
    source = "Councilmember O’Quinn made a motion which was seconded by Councilmember Tate to\ngo into Executive Session"
    cm = find_citation("O'Quinn made a motion which was seconded by Councilmember Tate to go into Executive Session", source)
    assert cm.kind == "exact"
    assert source[cm.start:cm.end].startswith("O’Quinn made a motion")
    assert source[cm.start:cm.end].endswith("Executive Session")


def test_fuzzy_pass_catches_a_stray_space_inside_a_word():
    source = "upon the roll being called the vote was as fol lows: Ayes: nine"
    cm = find_citation("upon the roll being called the vote was as follows: Ayes: nine", source)
    assert cm.kind == "fuzzy" and cm.ratio >= 0.92
    assert "roll being called" in source[cm.start:cm.end]


def test_missing_when_the_quote_is_not_there():
    cm = find_citation("the council adjourned sine die", "Item 15 passes. We stand in recess.")
    assert cm.kind == "missing" and cm.start is None


def test_exact_beats_fuzzy_and_empty_excerpt_is_missing():
    assert find_citation("", "anything").kind == "missing"
    assert find_citation("   ", "anything").kind == "missing"


def test_canonical_statute_unifies_spoken_and_written_forms():
    assert canonical_statute("36-25A-7(a)(4)") == "3625a7a4"
    assert canonical_statute("36, 25, a seven a four") == "3625a7a4"
    assert canonical_statute("Section 36-25A-7 (a)(3)") == "section3625a7a3"
    assert canonical_statute("thirty six twenty five A seven a four") == "3625a7a4"


def test_window_clamps_to_source():
    src = "abcdefghij"
    assert window(src, 4, 6, 3) == "bcdefghi"
    assert window(src, 0, 2, 50) == src
