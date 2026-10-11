from docket.ai.transcripts.compare import match_stale


def _row(cat, tev, item=5, mexc="Councilmember Tate made a motion to table item five"):
    return {"category": cat, "transcript_event_id": tev, "agenda_item_id": item, "minutes_excerpt": mexc}


def test_match_by_category_and_transcript_event():
    stale = [_row("wording", 10), _row("sequence", 10), _row("wording", 11)]
    assert match_stale(_row("wording", 10), stale) is stale[0]
    assert match_stale(_row("omission", 10), stale) is None


def test_additions_match_by_item_and_similar_minutes_excerpt():
    stale = [_row("addition", None, 5, "Councilmember Tate made a motion to table item five"),
             _row("addition", None, 6, "Councilmember Tate made a motion to table item five")]
    new = _row("addition", None, 5, "Councilmember Tate made  a motion to table item 5")
    assert match_stale(new, stale) is stale[0]
    assert match_stale(_row("addition", None, 5, "completely different text about a recess"), stale) is None
