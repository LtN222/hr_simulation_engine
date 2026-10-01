"""HP-03: a step-wise legal minimum and the Minimumloonaanpassing event."""
import datetime as dt
import math
import random

import pandas as pd
import pytest

from src.core.config_loader import ConfigLoader
from src.infrastructure.dimensions import build_dim_event_type
from src.infrastructure.salary_policy import SalaryPolicy
from src.simulation.simulation_career_events import (
    MINIMUM_WAGE_EVENT,
    _already_reviewed_this_year,
    _salary_review_week,
    _simulate_salary_reviews,
    simulate_minimum_wage_adjustments,
)

D = pd.Timestamp
EVENT_KEY = 9
REVIEW_KEY = 4


def _policy(indexation_months=None, **overrides):
    legal = {
        "reference_year": 2026,
        "annual_full_time_salary": 31179,
        "allowances": {"vakantiegeld": 0.08},
        **({"indexation_months": indexation_months} if indexation_months else {}),
    }
    config = type("Config", (), {
        "salary_benchmark": {
            "base_date": "2020-01-01",
            "annual_market_growth_rate": 0.025,
            "legal_minimum_salary": legal,
            "market_median_by_role": {"Operator": 36000},
            **overrides,
        },
        "dim_salary_scale": [{"SalaryScale_Key": 1, "Minimum_Salaris": 20000,
                              "Maximum_Salaris": 60000, "Aantal_Treden": 1}],
    })()
    return SalaryPolicy(config)


# ---------------------------------------------------------------------------
# the step-wise floor
# ---------------------------------------------------------------------------

def _indexed(base, indexation_date):
    reference = D(2026, 1, 1)
    growth = lambda d: 1.025 ** max(0.0, (d - D(2020, 1, 1)).days / 365.2425)
    return math.ceil(round(base * growth(indexation_date) / growth(reference), 6))


def test_the_floor_is_constant_between_indexation_dates_and_steps_on_1_january_and_1_july():
    policy = _policy()

    assert policy.legal_minimum(D("2026-01-01")) == 33674
    assert policy.legal_minimum(D("2026-03-17")) == 33674
    assert policy.legal_minimum(D("2026-06-30")) == 33674
    assert policy.legal_minimum(D("2026-07-01")) == _indexed(33674, D("2026-07-01")) == 34089
    assert policy.legal_minimum(D("2026-12-31")) == 34089
    assert policy.legal_minimum(D("2027-01-01")) == _indexed(33674, D("2027-01-01")) == 34516
    assert policy.legal_minimum(D("2025-12-31")) == _indexed(33674, D("2025-07-01"))   # still the July 2025 step


def test_dates_before_the_base_date_get_the_first_value():
    policy = _policy()
    first = policy.legal_minimum(D("2020-01-01"))

    assert first == 29036
    assert policy.legal_minimum(D("2019-12-31")) == policy.legal_minimum(D("2015-06-01")) == first
    assert policy.legal_minimum(D("2020-06-30")) == first                       # still the January step
    assert policy.legal_minimum(D("2020-07-01")) > first


def test_the_step_values_never_decrease():
    policy = _policy()
    values = [policy.legal_minimum(D(2020, 1, 1) + pd.Timedelta(days=day)) for day in range(0, 365 * 8, 7)]

    assert values == sorted(values)
    assert len(set(values)) == 16                       # two steps a year for eight years


def test_the_indexation_months_are_configurable():
    quarterly = _policy(indexation_months=[1, 4, 7, 10])

    assert quarterly.legal_minimum(D("2026-04-01")) > quarterly.legal_minimum(D("2026-03-31")) == 33674
    assert quarterly.legal_minimum(D("2026-04-01")) == quarterly.legal_minimum(D("2026-06-30"))


def test_the_real_config_declares_the_indexation_months_and_still_passes_validation():
    from src.infrastructure.config_validation import validate_role_configuration

    config = ConfigLoader().load()

    assert config.salary_benchmark["legal_minimum_salary"]["indexation_months"] == [1, 7]
    assert validate_role_configuration(config) == []
    assert SalaryPolicy(config).legal_minimum(D("2026-01-01")) == 33674


def test_apply_floor_uses_the_step_value():
    policy = _policy()

    assert policy.apply_floor(30000, D("2026-06-30")) == 33674
    assert policy.apply_floor(30000, D("2026-07-01")) == 34089
    assert policy.apply_floor(40000, D("2026-07-01")) == 40000


# ---------------------------------------------------------------------------
# when the adjustment is due: the 7 days ending on the simulated Monday
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("monday,expected", [
    ("2026-01-05", D("2026-01-01")),   # 1 January falls mid-week (Thursday): the window starts in December
    ("2025-12-29", None),              # the week that contains 1 January has not ended yet
    ("2026-01-12", None),
    ("2024-01-01", D("2024-01-01")),   # 1 January is itself the Monday
    ("2024-01-08", None),
    ("2026-07-06", D("2026-07-01")),
    ("2026-06-29", None),
    ("2026-02-02", None),              # no indexation in February
    ("2026-08-03", None),
])
def test_the_indexation_date_is_found_only_in_the_week_that_just_ended(monday, expected):
    assert _policy().indexation_date_in_week(D(monday)) == expected


# ---------------------------------------------------------------------------
# the adjustment itself
# ---------------------------------------------------------------------------

def _config(salary_increase_rate=1.0):
    return type("Config", (), {
        "salary_benchmark": {
            "base_date": "2020-01-01", "annual_market_growth_rate": 0.025,
            "legal_minimum_salary": {"reference_year": 2026, "annual_full_time_salary": 31179,
                                     "allowances": {"vakantiegeld": 0.08}},
            "market_median_by_role": {"Operator": 36000},
            "compa_ratio": {"minimum_ratio": 0.75},
        },
        "dim_salary_scale": [{"SalaryScale_Key": 1, "Minimum_Salaris": 20000,
                              "Maximum_Salaris": 60000, "Aantal_Treden": 1}],
        "career_events": {"salary_increase_rate": salary_increase_rate,
                          "relevant_experience_transfer_ratio": 0.45},
    })()


def _row(key, salary, start="2025-03-03", employment_key=None):
    return {
        "Employment_Key": employment_key or key, "Previous_Employment_Key": None, "Employee_Key": key,
        "HireSource_Key": 1, "Role_Key": 1, "Location_Key": 2, "Shift_Key": 3, "SalaryScale_Key": 1,
        "Streef_Compa_Ratio": 0.93, "Relevante_Ervaring_Jaren_Bij_Start": 2.0,
        "Startdatum": D(start), "Einddatum": None, "Dienstverband_status": "Actief", "Salaris": salary,
        "Contracttype": "Tijdelijk", "Contracturen": 32, "Contract_einddatum": D("2026-12-31"),
        "Contract_ronde": 2, "EventType_Key": 1, "DepartureReason_Key": None,
    }


def _state(config, rows, service_starts=None):
    keys = [row["Employee_Key"] for row in rows]
    service_starts = service_starts or {}
    return {
        "dim_salary_scale": pd.DataFrame(config.dim_salary_scale),
        "dim_employee": pd.DataFrame({
            "Employee_Key": keys,
            "Aaneengesloten_Indienst_Datum": [D(service_starts.get(k, "2018-01-01")) for k in keys],
        }),
        "fact_employment": pd.DataFrame(rows),
    }


EVENT_MAP = {MINIMUM_WAGE_EVENT: EVENT_KEY, "Salarisaanpassing": REVIEW_KEY}


def _employee_with_review_week(week):
    return next(key for key in range(1, 500) if _salary_review_week(key) == week)


def _employee_without_review_week(week):
    return next(key for key in range(1, 500) if _salary_review_week(key) != week)


def test_an_employee_below_the_new_floor_gets_a_row_at_the_floor_with_everything_carried():
    config = _config()
    key = _employee_without_review_week(2)
    state = _state(config, [_row(key, 33000)])
    today = D("2026-01-05")                                           # ISO week 2

    state = simulate_minimum_wage_adjustments(state, config, None, today, EVENT_MAP)

    old, new = state["fact_employment"].sort_values("Employment_Key").iloc
    assert old["Dienstverband_status"] == "Inactief" and old["Einddatum"] == today
    assert new["Dienstverband_status"] == "Actief" and pd.isna(new["Einddatum"])
    assert new["Startdatum"] == today
    assert new["Salaris"] == 33674
    assert new["EventType_Key"] == EVENT_KEY
    assert new["Previous_Employment_Key"] == old["Employment_Key"]
    for column in ("Role_Key", "Location_Key", "Shift_Key", "SalaryScale_Key", "Streef_Compa_Ratio",
                   "Contracttype", "Contracturen", "Contract_einddatum", "Contract_ronde", "HireSource_Key"):
        assert new[column] == old[column], column
    # experience keeps growing: 2.0 at the old start plus the ~10 months since
    assert new["Relevante_Ervaring_Jaren_Bij_Start"] == pytest.approx(2.0 + (today - D("2025-03-03")).days / 365.2425, abs=0.01)


def test_the_adjustment_triggers_only_in_the_week_after_an_indexation_date():
    config = _config()
    key = _employee_without_review_week(2)

    for monday, expected_rows in (("2026-01-05", 2), ("2026-01-12", 1), ("2025-12-29", 1), ("2026-03-02", 1)):
        state = _state(config, [_row(key, 33000)])
        state = simulate_minimum_wage_adjustments(state, config, None, D(monday), EVENT_MAP)
        assert len(state["fact_employment"]) == expected_rows, monday

    july = simulate_minimum_wage_adjustments(
        _state(config, [_row(key, 33700)]), config, None, D("2026-07-06"), EVENT_MAP)
    assert july["fact_employment"]["Salaris"].tolist() == [33700, 34089]        # above the old floor, below the new one


def test_employees_at_or_above_the_floor_and_inactive_rows_get_no_row():
    config = _config()
    rows = [_row(1, 33674), _row(2, 50000), {**_row(3, 30000), "Dienstverband_status": "Inactief"}]
    state = _state(config, rows)

    state = simulate_minimum_wage_adjustments(state, config, None, D("2026-01-05"), EVENT_MAP)

    assert len(state["fact_employment"]) == 3


def test_an_employee_whose_certain_review_falls_this_week_is_skipped_but_others_are_not():
    config = _config()
    today = D("2026-01-05")
    week = today.isocalendar()[1]
    reviewed = _employee_with_review_week(week)
    other = _employee_without_review_week(week)
    rows = [_row(reviewed, 33000), _row(other, 33000)]
    state = _state(config, rows)

    state = simulate_minimum_wage_adjustments(state, config, None, today, EVENT_MAP)

    adjusted = set(state["fact_employment"].query("EventType_Key == @EVENT_KEY")["Employee_Key"])
    assert adjusted == {other}                      # the review (same week) applies the floor for the other one


def test_a_review_week_employee_who_gets_no_review_is_adjusted_anyway():
    today = D("2026-01-05")
    week = today.isocalendar()[1]
    key = _employee_with_review_week(week)

    joined_this_year = simulate_minimum_wage_adjustments(
        _state(_config(), [_row(key, 33000)], {key: "2026-01-02"}), _config(), None, today, EVENT_MAP)
    assert (joined_this_year["fact_employment"]["EventType_Key"] == EVENT_KEY).sum() == 1

    random_review = simulate_minimum_wage_adjustments(
        _state(_config(0.5), [_row(key, 33000)]), _config(0.5), None, today, EVENT_MAP)
    assert (random_review["fact_employment"]["EventType_Key"] == EVENT_KEY).sum() == 1


def test_without_the_event_type_the_step_does_nothing():
    config = _config()
    state = _state(config, [_row(1, 33000)])

    state = simulate_minimum_wage_adjustments(state, config, None, D("2026-01-05"), {})

    assert len(state["fact_employment"]) == 1


def test_a_minimum_wage_row_does_not_count_as_the_annual_review_and_the_review_still_happens():
    config = _config()
    key = _employee_with_review_week(10)
    state = _state(config, [_row(key, 33000)])
    state = simulate_minimum_wage_adjustments(state, config, None, D("2026-01-05"), EVENT_MAP)
    employment = state["fact_employment"]

    assert not _already_reviewed_this_year(employment, key, REVIEW_KEY, 2026)
    employment.loc[len(employment)] = {**employment.iloc[-1].to_dict(), "EventType_Key": REVIEW_KEY,
                                       "Startdatum": D("2026-03-02")}
    assert _already_reviewed_this_year(employment, key, REVIEW_KEY, 2026)

    # and the real review step still produces the review after the January adjustment
    state = _state(config, [_row(key, 33000)])
    state = simulate_minimum_wage_adjustments(state, config, None, D("2026-01-05"), EVENT_MAP)
    review_monday = D(dt.date.fromisocalendar(2026, 10, 1))
    dim_role = pd.DataFrame({"Role_Key": [1], "Functie_Naam": ["Operator"], "Salaris_min": [30000],
                             "Salaris_max": [40000], "SalaryScale_Key": [1], "Department_Key": [1]})
    state["dim_employee"]["Prestatie_Score"] = 3.5
    state["dim_employee"]["Geslacht"] = "M"

    employment, _ = _simulate_salary_reviews(
        state["fact_employment"], state["dim_employee"], dim_role,
        SalaryPolicy(config, state["dim_salary_scale"]), config, review_monday, random.Random(1), EVENT_MAP,
    )

    assert (employment["EventType_Key"] == REVIEW_KEY).sum() == 1


# ---------------------------------------------------------------------------
# the new event type and its consumers
# ---------------------------------------------------------------------------

def test_the_new_event_type_is_appended_without_shifting_existing_keys():
    config = ConfigLoader().load()
    events = config.dim_event_type

    assert events[-1] == MINIMUM_WAGE_EVENT
    assert events[:8] == ["Aangenomen", "Promotie", "Transfer", "Salarisaanpassing", "Uit dienst",
                          "Contract omgezet naar vast", "Contract verlengd", "Locatietransfer"]
    dimension = build_dim_event_type(events)
    keys = dict(zip(dimension["Gebeurtenis"], dimension["EventType_Key"]))
    assert keys["Locatietransfer"] == 8 and keys[MINIMUM_WAGE_EVENT] == 9
    assert keys["Aangenomen"] == 1 and keys["Salarisaanpassing"] == 4


def test_career_momentum_ignores_the_minimum_wage_event():
    """Only Promotie and Transfer count as career moves in satisfaction/engagement."""
    from src.infrastructure.satisfaction import _compute_career_momentum

    state = {
        "dim_event_type": pd.DataFrame({"EventType_Key": [1, 2, 9],
                                        "Gebeurtenis": ["Aangenomen", "Promotie", MINIMUM_WAGE_EVENT]}),
        "fact_employment": pd.DataFrame([
            {**_row(1, 33000, "2024-01-01"), "EventType_Key": 1, "Employment_Key": 1},
            {**_row(1, 33674, "2026-01-05"), "EventType_Key": 9, "Employment_Key": 2},
        ]),
    }
    settings = {"career_momentum": {"momentum_months": 12, "promotion_max_effect": 0.18}}

    momentum = _compute_career_momentum(state, 1, D("2026-01-20"), 3.0, settings)

    assert momentum == 0.0                                  # a promotion in the same spot would give > 0
    state["fact_employment"].loc[1, "EventType_Key"] = 2
    state.pop("_employment_by_employee", None)
    state.pop("_employment_by_employee_source", None)
    assert _compute_career_momentum(state, 1, D("2026-01-20"), 3.0, settings) > 0
