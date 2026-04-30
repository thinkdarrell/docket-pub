"""Unit tests for GenericCMS date parsing from filenames."""

from datetime import date

from docket.adapters.generic_cms import GenericCMSAdapter


class TestParseDateFromFilename:
    """Tests for GenericCMSAdapter._parse_date_from_filename().

    Homewood uses MMDDYY prefixes with varying separators:
        042726+Council+Agenda.pdf      -> 2026-04-27 (plus signs)
        03+23+26+Council+Agenda.pdf    -> 2026-03-23 (spaces in date)
        051925_Council_Agenda_.pdf     -> 2025-05-19 (underscores)
        040824 Council Agenda .pdf     -> 2024-04-08 (spaces)
        032723%20Council%20Agenda.pdf  -> 2023-03-27 (URL encoded)
    """

    parse = staticmethod(GenericCMSAdapter._parse_date_from_filename)

    # --- Standard MMDDYY formats -------------------------------------------

    def test_plus_separator(self):
        assert self.parse("042726+Council+Agenda.pdf") == date(2026, 4, 27)

    def test_underscore_separator(self):
        assert self.parse("051925_Council_Agenda_.pdf") == date(2025, 5, 19)

    def test_space_separator(self):
        assert self.parse("040824 Council Agenda .pdf") == date(2024, 4, 8)

    def test_url_encoded_spaces(self):
        assert self.parse("032723%20Council%20Agenda.pdf") == date(2023, 3, 27)

    # --- Spaced digits in date ----------------------------------------------

    def test_spaced_digits(self):
        """03+23+26 -> month=03, day=23, year=26."""
        assert self.parse("03+23+26+Council+Agenda.pdf") == date(2026, 3, 23)

    def test_spaced_digits_with_real_spaces(self):
        assert self.parse("03 11 24 Council Agenda .pdf") == date(2024, 3, 11)

    # --- Special meeting types ----------------------------------------------

    def test_special_called(self):
        assert self.parse("012926+Special+Called+Council+Meeting+Agenda.pdf") == date(2026, 1, 29)

    def test_minutes(self):
        assert self.parse("030926+Council+Meeting+Minutes.pdf") == date(2026, 3, 9)

    # --- Edge cases ---------------------------------------------------------

    def test_no_date_prefix(self):
        assert self.parse("Hwd+Org+Chart.pdf") is None

    def test_budget_presentation(self):
        assert self.parse("Budget_Presentation.pdf") is None

    def test_invalid_month(self):
        assert self.parse("130126+Council.pdf") is None

    def test_invalid_day(self):
        assert self.parse("013226+Council.pdf") is None

    def test_suffix_version_number(self):
        """Filenames with _2 suffix should still parse the date."""
        assert self.parse("042726+Council+Agenda_2.pdf") == date(2026, 4, 27)

    def test_audio_file(self):
        assert self.parse("052225_Special_Called_Council.wav") == date(2025, 5, 22)

    def test_oldest_in_archive(self):
        assert self.parse("011022+Council+Agenda.pdf") == date(2022, 1, 10)
