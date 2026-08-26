import random

import pandas as pd

from src.simulation.simulation_vacancy import VacancySimulator


def _config():
    base = {
        "structure": {
            "Directie": {
                "Staff": {"target_weight": 1},
                "CEO": {
                    "target_weight": 1,
                    "leidinggevend": True,
                    "max_count": 1,
                },
            },
        },
        "workforce_planning": {"department_target_weights": {"Directie": 1}},
        "staffing": {},
        "dim_location": {},
        "growth": {},
    }
    return type("Config", (), base)()


def _dim_role():
    return pd.DataFrame({
        "Role_Key": [1, 2],
        "Role_Name": ["Staff", "CEO"],
        "Department_Name": ["Directie", "Directie"],
        "Department_Key": [1, 1],
    })


def _dim_department():
    return pd.DataFrame({
        "Department_Key": [1],
        "Department_Name": ["Directie"],
    })


def test_growth_selection_never_picks_a_role_that_is_already_at_its_max_count():
    """CEO is already at its cap of 1: even though its target-share gap
    would otherwise make it the overwhelming favourite in the weighted
    lottery, the hard ceiling must exclude it entirely, not just discount
    it."""
    simulator = VacancySimulator(_config(), schema=None, rng=random.Random(1))
    state = {"dim_role": _dim_role(), "dim_department": _dim_department()}
    role_counts = {1: 5, 2: 1}  # CEO (Role_Key 2) already at its max_count of 1

    for seed in range(20):
        simulator.rng = random.Random(seed)
        role = simulator._choose_role_for_growth(
            state, dict(role_counts), target_headcount=10, pending_by_role={}
        )
        assert role["Role_Name"] == "Staff"


def test_growth_selection_returns_none_once_every_active_role_is_at_capacity():
    simulator = VacancySimulator(_config(), schema=None, rng=random.Random(1))
    state = {"dim_role": _dim_role(), "dim_department": _dim_department()}
    role_counts = {1: 1, 2: 1}  # Staff has no cap but is already above target;
    # CEO is at its max_count of 1 - only relevant once Staff is also excluded
    # by giving it a max_count for this test.
    config = _config()
    config.structure["Directie"]["Staff"]["max_count"] = 1
    simulator.config = config

    role = simulator._choose_role_for_growth(
        state, role_counts, target_headcount=10, pending_by_role={}
    )

    assert role is None


def test_growth_selection_never_picks_a_role_already_covered_by_a_pending_vacancy():
    """CEO has 0 active holders but a vacancy for it is already open. Its
    active headcount alone would make it look understaffed forever while
    that vacancy is still being recruited - `pending_by_role` must count
    towards its cap just like an active hire would."""
    simulator = VacancySimulator(_config(), schema=None, rng=random.Random(1))
    state = {"dim_role": _dim_role(), "dim_department": _dim_department()}
    role_counts = {1: 5, 2: 0}
    pending_by_role = {2: 1}  # one vacancy already open for CEO

    for seed in range(20):
        simulator.rng = random.Random(seed)
        role = simulator._choose_role_for_growth(
            state, dict(role_counts), target_headcount=10, pending_by_role=pending_by_role
        )
        assert role["Role_Name"] == "Staff"


def test_run_does_not_create_a_second_growth_vacancy_for_a_role_with_one_already_pending():
    """Without accounting for the vacancy already open for CEO, its 0 active
    holders would keep tripping the under-minimum priority fill every week,
    piling up concurrent vacancies that could each independently end up
    filled and push a one-seat role past its cap."""
    config = _config()
    simulator = VacancySimulator(config, schema=None, rng=random.Random(1))
    state = {
        "dim_role": _dim_role(),
        "dim_department": _dim_department(),
        "fact_employment": pd.DataFrame({
            "Role_Key": [1],
            "Dienstverband_status": ["Actief"],
        }),
        "fact_vacancy": pd.DataFrame({
            "Vacancy_Key": [1],
            "Role_Key": [2],
            "Department_Key": [1],
            "Status": ["Open"],
        }),
    }

    state = simulator.run(state, today=pd.Timestamp("2024-01-01"), growth_vacancies=1)

    ceo_open_vacancies = state["fact_vacancy"][
        (state["fact_vacancy"]["Role_Key"] == 2)
        & (state["fact_vacancy"]["Status"] == "Open")
    ]
    assert len(ceo_open_vacancies) == 1


def test_minimum_for_role_scales_the_team_lead_role_with_department_headcount():
    """A department's team-lead role must be flagged understaffed based on
    its actual current span of control, not a flat "at least one" floor -
    otherwise a department that has grown well past `max_team_size` per
    lead never gets more, no matter how large it grows."""
    config = type("Config", (), {
        "structure": {
            "Productie": {
                "Operator": {"leidinggevend": False},
                "Teamleider": {"leidinggevend": True, "salaris_range": [45000, 60000]},
            },
        },
        "staffing": {"max_team_size": 10},
    })()
    simulator = VacancySimulator(config, schema=None, rng=random.Random(1))
    state = {
        "dim_role": pd.DataFrame({
            "Role_Key": [1, 2],
            "Role_Name": ["Operator", "Teamleider"],
            "Department_Name": ["Productie", "Productie"],
            "Department_Key": [1, 1],
        }),
        "dim_department": pd.DataFrame({
            "Department_Key": [1],
            "Department_Name": ["Productie"],
        }),
    }
    role_row = pd.Series({"Role_Key": 2, "Role_Name": "Teamleider", "Department_Key": 1})
    role_counts = {1: 24, 2: 1}  # 24 operators, only 1 team lead so far

    assert simulator._minimum_for_role(state, role_row, role_counts) == 3  # ceil(24/10)
