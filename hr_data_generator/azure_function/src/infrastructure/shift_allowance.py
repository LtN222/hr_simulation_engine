"""Ploegentoeslag: the shift allowance on top of base pay.

`Salaris` stays the full-time (1.0 FTE) BASE pay: the legal-minimum floor, the
market benchmark, `Streef_Compa_Ratio`, the gender-pay-gap calibration and the
satisfaction pay input all compare `Salaris` and must not see the allowance.
`Ploegentoeslag` is a separate full-time amount (EUR per year, same basis as
`Salaris`) derived from a row's own `Salaris` and `Shift_Key`; total pay is
`Salaris + Ploegentoeslag`, and the consumer applies FTE pro rata to both.

This module is the only place that computes it. `derive_ploegentoeslag` fills
the column on `fact_employment` in `post_process`, so no row builder has to know
about it and full and incremental runs give identical values; the workforce
snapshot copies it from the effective employment row like it copies `Salaris`.
"""

import numpy as np
import pandas as pd

from src.infrastructure.dimension_lookup import shift_name_for_key


def shift_percentages(config):
    """{Ploegendienst_Naam: fraction of Salaris} from `shift_allowance.percentages`."""
    settings = getattr(config, "shift_allowance", None) or {}
    return {name: float(value) for name, value in settings.get("percentages", {}).items()}


def shift_allowance(salary, shift_key, state, config):
    """round(Salaris * percentage of the shift); 0 when the shift or salary is missing."""
    salary = pd.to_numeric(salary, errors="coerce")
    if pd.isna(salary):
        return 0
    name = shift_name_for_key(state, shift_key)
    if name is None:
        return 0
    return int(round(float(salary) * shift_percentages(config).get(name, 0.0)))


def derive_ploegentoeslag(state, config):
    """Set `Ploegentoeslag` on every `fact_employment` row (same values as `shift_allowance`)."""
    employment = state.get("fact_employment")
    if employment is None or employment.empty:
        return state

    employment = employment.copy()
    percentage_by_key = {}
    for shift_key in pd.unique(employment["Shift_Key"].dropna()):
        name = shift_name_for_key(state, shift_key)
        percentage_by_key[shift_key] = shift_percentages(config).get(name, 0.0) if name else 0.0

    salary = pd.to_numeric(employment["Salaris"], errors="coerce")
    percentage = employment["Shift_Key"].map(percentage_by_key).astype(float)
    allowance = np.round((salary * percentage).to_numpy(dtype="float64"))   # half to even, like round()
    employment["Ploegentoeslag"] = np.where(np.isnan(allowance), 0, allowance).astype("int64")
    state["fact_employment"] = employment
    return state
