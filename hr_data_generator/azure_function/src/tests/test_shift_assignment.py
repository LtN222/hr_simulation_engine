import random
from collections import Counter

import pandas as pd

from src.core.config_loader import ConfigLoader
from src.infrastructure.dimensions import build_dim_department, build_dim_role
from src.infrastructure.shift_assignment import assign_ploegendienst_key, shift_mix

SHIFTS = pd.DataFrame({
    "Shift_Key": [0, 1, 2, 3],
    "Ploegendienst_Naam": ["Niet van toepassing", "Dag", "2-ploeg", "3-ploeg"],
})
STATE = {"dim_shift": SHIFTS}
NAMES = dict(zip(SHIFTS["Shift_Key"], SHIFTS["Ploegendienst_Naam"]))


def _config(**assignment):
    base = {
        "values": ["Dag", "2-ploeg", "3-ploeg"],
        "weights": [0.3, 0.4, 0.3],
        "by_department": {
            "Techniek": {"weights": [0.4, 0.3, 0.3]},
            "Logistiek": {"weights": [0.5, 0.5, 0.0]},
        },
    }
    base.update(assignment)
    return type("Config", (), {"ploegendienst_assignment": base})()


def _role(department, flagged=True):
    return pd.Series({"Afdeling_Naam": department, "Ploegendienst_Flag": flagged})


def _draw(config, role, n=4000, seed=1):
    rng = random.Random(seed)
    return Counter(
        NAMES[assign_ploegendienst_key(role, STATE, config, rng)] for _ in range(n)
    )


def test_flagged_roles_get_shifts_from_their_departments_mix():
    config = _config()

    logistiek = _draw(config, _role("Logistiek"))
    techniek = _draw(config, _role("Techniek"))

    assert logistiek["3-ploeg"] == 0
    assert 0.45 < logistiek["Dag"] / 4000 < 0.55
    assert 0.35 < techniek["Dag"] / 4000 < 0.45
    assert 0.25 < techniek["3-ploeg"] / 4000 < 0.35
    assert techniek["Niet van toepassing"] == 0


def test_departments_without_an_override_use_the_default_mix():
    counts = _draw(_config(), _role("Productie"))

    assert 0.25 < counts["Dag"] / 4000 < 0.35
    assert 0.35 < counts["2-ploeg"] / 4000 < 0.45
    assert 0.25 < counts["3-ploeg"] / 4000 < 0.35


def test_a_config_without_by_department_keeps_the_previous_behaviour():
    config = type("Config", (), {"ploegendienst_assignment": {
        "values": ["Dag", "2-ploeg", "3-ploeg"], "weights": [0.3, 0.4, 0.3],
    }})()

    assert shift_mix(config, "Techniek") == (["Dag", "2-ploeg", "3-ploeg"], [0.3, 0.4, 0.3])
    assert shift_mix(type("Config", (), {})(), "Techniek")[1] == [0.3, 0.4, 0.3]


def test_unflagged_roles_stay_niet_van_toepassing():
    for department in ("Techniek", "Logistiek", "Productie"):
        assert _draw(_config(), _role(department, flagged=False), n=200) == {
            "Niet van toepassing": 200
        }


def test_each_assignment_uses_exactly_one_rng_draw():
    rng_a, rng_b = random.Random(5), random.Random(5)
    assign_ploegendienst_key(_role("Logistiek"), STATE, _config(), rng_a)
    rng_b.choices(["Dag", "2-ploeg", "3-ploeg"], weights=[0.5, 0.5, 0.0], k=1)

    assert rng_a.random() == rng_b.random()


def test_the_real_config_flags_the_intended_techniek_and_logistiek_roles():
    config = ConfigLoader().load()
    roles = build_dim_role(
        config.structure,
        build_dim_department(config.structure),
        pd.DataFrame(config.dim_salary_scale),
        config.salary_benchmark["market_median_by_role"],
        config.role_career_paths,
    )
    flagged = set(roles.loc[roles["Ploegendienst_Flag"], "Functie_Naam"])

    assert {"Monteur", "Teamleider Technische Dienst",
            "Magazijnmedewerker", "Teamleider Logistiek"} <= flagged
    for department in ("Techniek", "Logistiek"):
        in_department = roles[roles["Afdeling_Naam"] == department]
        assert set(in_department.loc[in_department["Ploegendienst_Flag"], "Functie_Naam"]) == (
            flagged & set(in_department["Functie_Naam"])
        )
    others = roles[
        roles["Afdeling_Naam"].isin(["Techniek", "Logistiek"])
        & ~roles["Functie_Naam"].isin({
            "Monteur", "Teamleider Technische Dienst",
            "Magazijnmedewerker", "Teamleider Logistiek",
        })
    ]
    assert not others["Ploegendienst_Flag"].any()
