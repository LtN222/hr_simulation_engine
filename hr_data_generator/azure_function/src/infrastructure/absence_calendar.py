"""Workday and hour arithmetic shared by every fact_absence writer.

Absence dates are inclusive: a one-day absence starts and ends on the same
date, `Duur_dagen = (end - start).days + 1`, workdays are the business days in
that inclusive range and hours are workdays times contract hours per day.
"""

import pandas as pd


def workdays_between(start, end):
    """Business days in the inclusive range start..end (0 when end < start)."""
    if pd.Timestamp(end) < pd.Timestamp(start):
        return 0
    return len(pd.bdate_range(start, end))


def duration_days(start, end):
    """Inclusive calendar duration in days."""
    return (pd.Timestamp(end) - pd.Timestamp(start)).days + 1


def hours_per_workday(contract_hours, config):
    """Contract hours per workday; falls back to the full-time week."""
    weekly_hours = pd.to_numeric(contract_hours, errors="coerce")
    if pd.isna(weekly_hours):
        weekly_hours = getattr(config, "workforce", {}).get("full_time_weekly_hours", 40)
    return float(weekly_hours) / 5
