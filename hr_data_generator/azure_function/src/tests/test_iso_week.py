from datetime import date

from src.core.iso_week import has_iso_week_53, next_iso_week


def test_has_iso_week_53_matches_known_years():
    # 2020 and 2026 both have a 53rd ISO week; 2021 and 2025 do not.
    assert has_iso_week_53(2020) is True
    assert has_iso_week_53(2026) is True
    assert has_iso_week_53(2021) is False
    assert has_iso_week_53(2025) is False


def test_next_iso_week_advances_within_a_year():
    assert next_iso_week(2024, 1) == (2024, 2)
    assert next_iso_week(2024, 51) == (2024, 52)


def test_next_iso_week_wraps_at_52_for_a_year_without_a_53rd_week():
    assert next_iso_week(2021, 52) == (2022, 1)


def test_next_iso_week_advances_into_week_53_instead_of_skipping_it():
    """Regression test: a hard-coded `week > 52` wrap always jumped straight
    to week 1 of the next year, silently dropping the 53rd simulated week in
    any year that actually has one (e.g. 2020, 2026)."""
    assert next_iso_week(2020, 52) == (2020, 53)
    assert next_iso_week(2020, 53) == (2021, 1)


def test_next_iso_week_result_is_always_a_valid_iso_calendar_date():
    year, week = 2019, 1
    for _ in range(6 * 52 + 10):
        year, week = next_iso_week(year, week)
        # Raises ValueError if (year, week) is not a real ISO calendar week.
        date.fromisocalendar(year, week, 1)
