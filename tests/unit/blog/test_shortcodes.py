"""Tests for shortcode collection and resolution."""

from __future__ import annotations

from unittest.mock import patch

from docket.blog.shortcodes import (
    collect_shortcode_refs,
    resolve_shortcode_titles,
)


def test_collect_item_and_meeting_refs():
    md = "Per [[item:3421]] and [[meeting:2232]] (and [[item:9999]])."
    items, meetings = collect_shortcode_refs(md)
    assert items == {3421, 9999}
    assert meetings == {2232}


def test_collect_handles_no_refs():
    items, meetings = collect_shortcode_refs("Plain text.")
    assert items == set()
    assert meetings == set()


def test_resolve_titles_batched():
    fake_cursor = _FakeCursor(
        items={3421: "Resolution to fund summer youth program"},
        meetings={2232: "Council Meeting — May 19, 2026"},
    )
    with patch("docket.blog.shortcodes._open_cursor") as mock_open:
        mock_open.return_value.__enter__.return_value = fake_cursor
        item_titles, meeting_titles = resolve_shortcode_titles(
            item_ids={3421}, meeting_ids={2232}
        )
    assert item_titles == {3421: "Resolution to fund summer youth program"}
    assert meeting_titles == {2232: "Council Meeting — May 19, 2026"}


def test_resolve_empty_sets_skips_query():
    with patch("docket.blog.shortcodes._open_cursor") as mock_open:
        item_titles, meeting_titles = resolve_shortcode_titles(
            item_ids=set(), meeting_ids=set()
        )
    assert item_titles == {}
    assert meeting_titles == {}
    mock_open.assert_not_called()


class _FakeCursor:
    def __init__(self, items, meetings):
        self.items = items
        self.meetings = meetings
        self._next = None

    def execute(self, sql, params):
        if "agenda_items" in sql:
            ids = params[0]
            self._next = [{"id": i, "title": self.items[i]} for i in ids if i in self.items]
        else:
            ids = params[0]
            self._next = [
                {"id": i, "title": self.meetings[i]} for i in ids if i in self.meetings
            ]

    def fetchall(self):
        return self._next
