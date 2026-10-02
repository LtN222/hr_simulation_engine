"""Score thresholds read from the satisfaction/engagement band dimensions.

Attrition and absence react to the same score bands that reporting shows. The
cut-offs therefore come from `dim_satisfaction_band`/`dim_engagement_band` (the
`Minimum_Score` of each band, in band order) instead of being repeated as
numbers in the simulators, so the bands and the behaviour always agree.
"""

import pandas as pd

TIER_NAMES = ("zeer_laag", "laag", "neutraal", "hoog", "zeer_hoog")

# Used only when a configuration carries no band dimension (narrow test fixtures).
DEFAULT_MINIMUMS = (1.0, 4.5, 6.0, 7.5, 8.5)


def band_minimums(config, dimension):
    """{tier name: Minimum_Score} for a band dimension, in band order.

    The five bands, ordered by `Minimum_Score`, are named by position:
    zeer_laag, laag, neutraal, hoog, zeer_hoog. A score belongs to the highest
    tier whose minimum it reaches.
    """
    bands = getattr(config, dimension, None) if config is not None else None
    if isinstance(bands, pd.DataFrame):
        bands = bands.to_dict("records")
    minimums = sorted(float(band["Minimum_Score"]) for band in (bands or []))
    if len(minimums) != len(TIER_NAMES):
        minimums = list(DEFAULT_MINIMUMS)
    return dict(zip(TIER_NAMES, minimums))
