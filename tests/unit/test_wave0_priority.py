"""Tests for Stage 0a priority + Big Fish helpers."""

from __future__ import annotations

import pytest

from docket.ai._priority import _priority_from_title, _is_big_fish


class TestPriorityFromTitle:
    def test_high_keyword_settlement(self):
        assert _priority_from_title("Settlement of plaintiff vs. City") == 'high'

    def test_high_keyword_emergency(self):
        assert _priority_from_title("Emergency repair of water main") == 'high'

    def test_high_dollar_in_title(self):
        assert _priority_from_title("Award of $4,500,000 contract") == 'high'

    def test_high_keyword_annexation(self):
        assert _priority_from_title("Annexation of Hidden Lake parcel") == 'high'

    def test_low_keyword_fleet(self):
        assert _priority_from_title("Fleet fuel purchase Q2 2026") == 'low'

    def test_low_keyword_membership(self):
        assert _priority_from_title("Annual membership dues NLC") == 'low'

    def test_normal_default(self):
        assert _priority_from_title("Approval of professional services agreement") == 'normal'

    def test_empty_title(self):
        assert _priority_from_title("") == 'normal'
        assert _priority_from_title(None) == 'normal'


class TestIsBigFish:
    def test_settlement_is_big_fish(self):
        assert _is_big_fish("Settlement of Smith vs. City for $250,000")

    def test_sole_source_is_big_fish(self):
        assert _is_big_fish("Sole-source extension: Flock cameras 5yr $1.8M")

    def test_emergency_is_big_fish(self):
        assert _is_big_fish("Ratifying an emergency repair of water main")

    def test_million_dollar_title_is_big_fish(self):
        assert _is_big_fish("Award of $1,500,000 HVAC contract")

    def test_routine_fleet_is_not_big_fish(self):
        assert not _is_big_fish("Approval of fleet fuel purchase")

    def test_routine_minutes_is_not_big_fish(self):
        assert not _is_big_fish("Approval of minutes from May 1, 2026")

    def test_empty_is_not_big_fish(self):
        assert not _is_big_fish("")
        assert not _is_big_fish(None)
