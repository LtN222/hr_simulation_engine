"""The performance score an employee had before their first review."""

import pandas as pd

DEFAULT_PERFORMANCE = 3.4


def starting_performance(employee):
    """Performance to show before an employee's first review.

    `Aanvangs_Prestatie_Score` is the score they were hired/generated with.
    The current `Prestatie_Score` is only a fallback for rows that lack it:
    it is overwritten by every later review, so using it for a historical
    date would show a future score in the past (AR-11).
    """
    for column in ("Aanvangs_Prestatie_Score", "Prestatie_Score"):
        value = pd.to_numeric(employee.get(column), errors="coerce")
        if pd.notna(value):
            return float(value)
    return DEFAULT_PERFORMANCE
