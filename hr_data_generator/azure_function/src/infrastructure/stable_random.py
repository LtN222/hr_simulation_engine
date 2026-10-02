"""Deterministic pseudo-random values derived from hashes, with no stored state.

Satisfaction and engagement need values that are reproducible for the same
(identifier, purpose) in every run, in full and incremental runs alike. A sha256
hash gives a uniform number; mapping it through the inverse normal CDF gives a
standard normal one. A time-varying value combines monthly normal draws, so it
depends only on the employee and the *month* of the scoring date: every consumer
scoring the same employee in the same month gets the same value.
"""

import hashlib
import math
from functools import lru_cache
from statistics import NormalDist

import pandas as pd

_NORMAL = NormalDist()
_EPSILON = 1e-9


def stable_unit(identifier, purpose):
    """A reproducible uniform value in [0, 1] for (identifier, purpose)."""
    digest = hashlib.sha256(f"{identifier}:{purpose}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / (2 ** 64 - 1)


def stable_uniform(identifier, purpose):
    """A reproducible uniform value in [-1, 1] (the original `_stable_value`)."""
    return stable_unit(identifier, purpose) * 2 - 1


def stable_normal(identifier, purpose):
    """A reproducible standard normal value for (identifier, purpose).

    The hash value is clamped to (1e-9, 1 - 1e-9) so the inverse CDF stays finite.
    """
    unit = min(max(stable_unit(identifier, purpose), _EPSILON), 1 - _EPSILON)
    return _NORMAL.inv_cdf(unit)


def month_index(date):
    """Months since year 0 for the month of `date` (so consecutive months differ by 1)."""
    date = pd.Timestamp(date)
    return date.year * 12 + date.month - 1


@lru_cache(maxsize=200_000)
def _monthly_normal(identifier, month, purpose):
    return stable_normal(f"{identifier}:{month}", purpose)


def smoothing_weights(window_months):
    """Linearly decaying weights over the last K months, normalized to unit variance."""
    window = max(1, int(window_months))
    raw = [window - lag for lag in range(window)]
    norm = math.sqrt(sum(weight * weight for weight in raw))
    return [weight / norm for weight in raw]


def smoothed_monthly_normal(identifier, date, purpose, window_months=6):
    """A standard normal value for the month of `date`, smooth from month to month.

    The weighted sum of the last K monthly hashed normal draws (most recent
    heaviest), normalized to variance 1. Consecutive months share most of their
    draws, so the value drifts instead of jumping; the correlation between months
    `lag` apart is `sum(w[j] * w[j + lag]) `.
    """
    month = month_index(date)
    weights = smoothing_weights(window_months)
    return sum(
        weight * _monthly_normal(str(identifier), month - lag, purpose)
        for lag, weight in enumerate(weights)
    )


def lag_correlation(window_months, lag):
    """Expected correlation between smoothed values `lag` months apart."""
    weights = smoothing_weights(window_months)
    return sum(weights[j] * weights[j + lag] for j in range(len(weights) - lag))


def time_varying_component(identifier, as_of_date, settings, purpose):
    """The slowly varying personal component (in score points) for one month.

    `settings` is the model's `time_varying` block:
    `sd` (standard deviation in score points), `window_months` (smoothing window)
    and `shared_fraction` (the share of the variance that comes from a "life
    circumstances" draw shared by satisfaction and engagement; the rest is
    specific to `purpose`). Returns 0 without a date or with sd 0.
    """
    if not settings or as_of_date is None or pd.isna(as_of_date):
        return 0.0
    sd = float(settings.get("sd", 0.0))
    if sd == 0.0:
        return 0.0
    window = int(settings.get("window_months", 6))
    shared = min(1.0, max(0.0, float(settings.get("shared_fraction", 0.0))))
    specific = smoothed_monthly_normal(identifier, as_of_date, purpose, window)
    common = smoothed_monthly_normal(identifier, as_of_date, "life_circumstances", window)
    return sd * (math.sqrt(shared) * common + math.sqrt(1.0 - shared) * specific)
