"""Tests for adoption-pattern detection."""

from datetime import date

import pytest

from docket.services.minutes_adoption import (
    AdoptionParseError,
    extract_adoption_target,
    is_adoption_title,
)


def test_is_adoption_title_matches_canonical_patterns():
    assert is_adoption_title("Approval of Minutes from January 7, 2026")
    assert is_adoption_title("Adoption of the Minutes from December 5, 2024")
    assert is_adoption_title("Approval of the December 5, 2024 Minutes")
    assert is_adoption_title("Minutes from the Council Meeting of December 5, 2024")
    assert is_adoption_title("Minutes from the Regular Meeting of December 5, 2024")


def test_is_adoption_title_rejects_unrelated():
    assert not is_adoption_title("A Resolution authorizing HCL Contracting")
    assert not is_adoption_title("Approval of Contract with Acme Corp")


def test_extract_adoption_target_returns_date():
    target = extract_adoption_target(
        "Approval of Minutes from December 5, 2024",
        adoption_meeting_date=date(2026, 1, 7),
    )
    assert target == date(2024, 12, 5)


def test_extract_adoption_target_rejects_invalid_date():
    """Feb 31 is not a real date."""
    with pytest.raises(AdoptionParseError, match="invalid date"):
        extract_adoption_target(
            "Approval of Minutes from February 31, 2024",
            adoption_meeting_date=date(2026, 1, 7),
        )


def test_extract_adoption_target_rejects_future_date():
    with pytest.raises(AdoptionParseError, match="future"):
        extract_adoption_target(
            "Approval of Minutes from January 1, 2030",
            adoption_meeting_date=date(2026, 1, 7),
        )


def test_extract_adoption_target_rejects_too_old():
    """24-month window."""
    with pytest.raises(AdoptionParseError, match="window"):
        extract_adoption_target(
            "Approval of Minutes from January 1, 2020",
            adoption_meeting_date=date(2026, 1, 7),
        )
