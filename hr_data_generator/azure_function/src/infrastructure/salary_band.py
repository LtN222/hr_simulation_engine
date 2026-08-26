"""Lookup helper for reporting-oriented salary bands."""

import pandas as pd


def salary_band_key_for(salary_bands, salary):
    """Return the reporting bin that contains an actual annual salary."""
    numeric_salary = pd.to_numeric(salary, errors="coerce")
    if salary_bands is None or salary_bands.empty or pd.isna(numeric_salary):
        return None

    minimum = pd.to_numeric(salary_bands["Minimum_Salaris"], errors="coerce")
    maximum = pd.to_numeric(salary_bands["Maximum_Salaris"], errors="coerce")
    match = salary_bands[
        (minimum <= numeric_salary)
        & (maximum.isna() | (numeric_salary <= maximum))
    ]
    return int(match.iloc[0]["SalaryBand_Key"]) if not match.empty else None
