"""Tests for word count + reading time computation."""

from __future__ import annotations

from docket.blog.render import compute_reading_time, count_words


def test_count_words_strips_html():
    assert count_words("<p>one two three</p>") == 3
    assert count_words("<h1>Hello</h1><p>World, friends.</p>") == 3


def test_reading_time_minimum_one():
    assert compute_reading_time(50) == 1


def test_reading_time_scales():
    # 200 wpm default → 400 words = 2 min
    assert compute_reading_time(400) == 2
    assert compute_reading_time(1000) == 5
