import random
from collections import Counter

import pandas as pd

from src.simulation.simulation_absence import AbsenceSimulator

TODAY = pd.Timestamp("2024-06-10")
TYPES = [
    {"AbsenceType_Key": 1, "Verzuim_Type_Naam": "Kort verzuim", "Telt_als_verzuim": True},
    {"AbsenceType_Key": 2, "Verzuim_Type_Naam": "Lang verzuim", "Telt_als_verzuim": True},
    {"AbsenceType_Key": 3, "Verzuim_Type_Naam": "Bedrijfsongeval", "Telt_als_verzuim": True},
]


def _simulator(excluded):
    config = type("Config", (), {
        "absence": {
            "type_weights": {"Kort verzuim": 0.8, "Lang verzuim": 0.2},
            "excluded_from_random_draw": excluded,
            "leave_type_rules": {},
        },
        "satisfaction": {},
        "engagement": {},
    })()
    simulator = AbsenceSimulator(config, schema=None, rng=random.Random(3))
    simulator._calculate_probability = lambda *args, **kwargs: 40.0  # nearly every week
    return simulator


def _draw(simulator, n=4000):
    counts = Counter()
    for _ in range(n):
        chosen = simulator._choose_incident_type(
            pd.Series({"Employee_Key": 1}), pd.Series({"Employee_Key": 1}),
            TYPES, {}, pd.DataFrame(), [], TODAY, {},
        )
        counts[chosen["Verzuim_Type_Naam"] if chosen else None] += 1
    return counts


def test_an_excluded_type_is_never_drawn_and_the_rest_keep_their_weights():
    counts = _draw(_simulator(["Bedrijfsongeval"]))

    assert counts["Bedrijfsongeval"] == 0
    drawn = counts["Kort verzuim"] + counts["Lang verzuim"]
    assert 0.75 < counts["Kort verzuim"] / drawn < 0.85


def test_without_the_exclusion_the_type_is_drawn_as_before():
    counts = _draw(_simulator([]))

    assert counts["Bedrijfsongeval"] > 0


def test_the_total_number_of_sickness_episodes_does_not_depend_on_the_exclusion():
    """Excluding a type only redistributes episodes over the remaining types."""
    def total(excluded):
        counts = _draw(_simulator(excluded), n=6000)
        return sum(counts[name] for name in ("Kort verzuim", "Lang verzuim", "Bedrijfsongeval"))

    assert total(["Bedrijfsongeval"]) == total([])


def test_the_direct_type_chooser_also_skips_excluded_types():
    simulator = _simulator(["Bedrijfsongeval"])

    names = {simulator._choose_absence_type(TYPES)["Verzuim_Type_Naam"] for _ in range(500)}

    assert names == {"Kort verzuim", "Lang verzuim"}
