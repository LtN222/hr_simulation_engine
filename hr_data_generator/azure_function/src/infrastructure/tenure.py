"""Continuous-service tenure shared by every simulator that needs it.

Tenure is measured from the employee's continuous service date
(`dim_employee.Aaneengesloten_Indienst_Datum`), never from the current
`fact_employment` row's `Startdatum`: that column is the start of the current
*event* and is reset by every salary review, contract renewal, promotion,
transfer and location move, so it makes almost everyone look newly hired.
"""

import pandas as pd


def service_start(employee, employment=None):
    """Return the continuous service start date, or NaT when unknown.

    Falls back to the employment row's `Startdatum` only when the employee's
    continuous service date is missing (or no employee row is available).
    """
    start = _get(employee, "Aaneengesloten_Indienst_Datum")
    if pd.isna(start):
        start = _get(employment, "Startdatum")
    return start


def service_days(employee, employment, today):
    """Whole days of continuous service on `today` (NaN-safe: returns None)."""
    start = service_start(employee, employment)
    if pd.isna(start):
        return None
    return (pd.Timestamp(today).normalize() - start.normalize()).days


def service_years(employee, employment, today):
    """Years of continuous service on `today`, never negative."""
    days = service_days(employee, employment, today)
    return 0.0 if days is None else max(0.0, days / 365.2425)


def _get(row, column):
    if row is None:
        return pd.NaT
    return pd.to_datetime(row.get(column), errors="coerce")
