"""Shared ISO-8601 week arithmetic for the weekly simulation loops.

Not every year has a week 53 (only years whose 1 January falls on a Thursday,
or a leap year starting on Wednesday, do). Incrementing the week number and
wrapping at a hard-coded 52 skips that week whenever the current year
actually has one, silently dropping a simulated week from every affected
year (2020, 2026, ... - roughly every 5-6 years).
"""

from datetime import date


def has_iso_week_53(year):
    """Return True if `year` has a 53rd ISO week."""
    try:
        date.fromisocalendar(year, 53, 1)
        return True
    except ValueError:
        return False


def next_iso_week(year, week):
    """Return the (year, week) that follows `week` of `year`.

    Advances to week 53 when the current year has one, otherwise wraps to
    week 1 of the next year - unlike a fixed `week > 52` check, which always
    wraps at 52 regardless of whether the current year has a 53rd week.
    """
    last_week = 53 if has_iso_week_53(year) else 52
    if week >= last_week:
        return year + 1, 1
    return year, week + 1
